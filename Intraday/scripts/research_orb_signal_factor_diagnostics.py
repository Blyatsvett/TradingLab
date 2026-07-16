import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_BREAKOUT_END,
    ORB_BREAKOUT_START,
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_MAX_OPEN_POSITIONS,
    ORB_MAX_OPENING_RANGE,
    ORB_MIN_GAP,
    ORB_POSITION_SIZE,
    ORB_R_MULTIPLE,
)
from Intraday.core.orb_research import (
    add_equity_curve_fields,
    build_research_trades,
    load_normalised_intraday_prices,
    summarize_research_backtest,
)
from Intraday.core.orb_strategy import simulate_orb_equity
from Intraday.core.paths import DATA_DIR


OUTPUT_DIAGNOSTICS_FILE = DATA_DIR / "orb_signal_factor_diagnostics.csv"
OUTPUT_SELECTED_FILE = DATA_DIR / "orb_signal_factor_selected_trades.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "orb_signal_factor_candidates.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None


def minmax_score(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")

    min_value = values.min()
    max_value = values.max()

    if pd.isna(min_value) or pd.isna(max_value) or max_value == min_value:
        return pd.Series(0.5, index=series.index)

    score = (values - min_value) / (max_value - min_value)

    if not higher_is_better:
        score = 1.0 - score

    return score.fillna(0.5)


def calculate_breakout_minutes(trades: pd.DataFrame) -> pd.Series:
    entry_times = pd.to_datetime(trades["entry_time"], errors="coerce")

    breakout_start_times = pd.to_datetime(
        entry_times.dt.strftime("%Y-%m-%d") + f" {ORB_BREAKOUT_START}",
        errors="coerce",
    )

    minutes = (entry_times - breakout_start_times).dt.total_seconds() / 60.0

    return minutes.fillna(0)


def add_factor_columns(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()

    trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")

    if "date" not in trades.columns:
        trades["date"] = trades["entry_time"].dt.strftime("%Y-%m-%d")

    trades["gap"] = pd.to_numeric(trades["gap"], errors="coerce")
    trades["gap_abs"] = trades["gap"].abs()

    trades["opening_range_pct"] = pd.to_numeric(
        trades["opening_range_pct"],
        errors="coerce",
    )

    trades["net_return"] = pd.to_numeric(trades["net_return"], errors="coerce")
    trades["gross_return"] = pd.to_numeric(trades["gross_return"], errors="coerce")

    trades["breakout_minutes_from_start"] = calculate_breakout_minutes(trades)

    ticker_quality = (
        trades.groupby("ticker")["net_return"]
        .mean()
        .rename("ticker_quality_raw")
        .reset_index()
    )

    trades = trades.merge(
        ticker_quality,
        on="ticker",
        how="left",
    )

    trades["opening_range_score"] = minmax_score(
        trades["opening_range_pct"],
        higher_is_better=False,
    )

    trades["opening_range_inverse_score"] = minmax_score(
        trades["opening_range_pct"],
        higher_is_better=True,
    )

    trades["gap_abs_score"] = minmax_score(
        trades["gap_abs"],
        higher_is_better=False,
    )

    trades["gap_abs_inverse_score"] = minmax_score(
        trades["gap_abs"],
        higher_is_better=True,
    )

    trades["gap_signed_score"] = minmax_score(
        trades["gap"],
        higher_is_better=True,
    )

    trades["gap_signed_inverse_score"] = minmax_score(
        trades["gap"],
        higher_is_better=False,
    )

    trades["breakout_time_score"] = minmax_score(
        trades["breakout_minutes_from_start"],
        higher_is_better=False,
    )

    trades["breakout_time_inverse_score"] = minmax_score(
        trades["breakout_minutes_from_start"],
        higher_is_better=True,
    )

    trades["ticker_quality_score"] = minmax_score(
        trades["ticker_quality_raw"],
        higher_is_better=True,
    )

    trades["ticker_quality_inverse_score"] = minmax_score(
        trades["ticker_quality_raw"],
        higher_is_better=False,
    )

    trades["combined_score"] = (
        0.35 * trades["opening_range_score"]
        + 0.25 * trades["breakout_time_score"]
        + 0.20 * trades["gap_abs_score"]
        + 0.20 * trades["ticker_quality_score"]
    ).round(6)

    trades["combined_inverse_score"] = (
        0.35 * trades["opening_range_inverse_score"]
        + 0.25 * trades["breakout_time_inverse_score"]
        + 0.20 * trades["gap_abs_inverse_score"]
        + 0.20 * trades["ticker_quality_inverse_score"]
    ).round(6)

    return trades


def can_accept_interval(
    accepted_intervals: list[dict],
    candidate_entry,
    candidate_exit,
    max_positions: int,
) -> bool:
    candidate_entry = pd.to_datetime(candidate_entry)
    candidate_exit = pd.to_datetime(candidate_exit)

    events = []

    for interval in accepted_intervals:
        events.append((pd.to_datetime(interval["entry_time"]), 1))
        events.append((pd.to_datetime(interval["exit_time"]), -1))

    events.append((candidate_entry, 1))
    events.append((candidate_exit, -1))

    # At identical timestamps, close before opening.
    events = sorted(events, key=lambda x: (x[0], x[1]))

    active = 0
    max_active = 0

    for _, change in events:
        active += change
        max_active = max(max_active, active)

    return max_active <= max_positions


def select_trades_with_capacity(
    trades: pd.DataFrame,
    method: str,
    score_column: str | None,
    max_positions: int,
) -> pd.DataFrame:
    trades = trades.copy()

    selected_rows = []

    for trade_date, day_trades in trades.groupby("date"):
        day_trades = day_trades.copy()

        if method == "earliest":
            day_trades = day_trades.sort_values(
                ["entry_time", "combined_score"],
                ascending=[True, False],
            )
        elif method == "latest":
            day_trades = day_trades.sort_values(
                ["entry_time", "combined_score"],
                ascending=[False, False],
            )
        else:
            if score_column is None:
                raise ValueError(f"score_column required for method={method}")

            day_trades = day_trades.sort_values(
                [score_column, "entry_time"],
                ascending=[False, True],
            )

        accepted_intervals = []
        selection_rank = 0

        for _, trade in day_trades.iterrows():
            can_accept = can_accept_interval(
                accepted_intervals=accepted_intervals,
                candidate_entry=trade["entry_time"],
                candidate_exit=trade["exit_time"],
                max_positions=max_positions,
            )

            if not can_accept:
                continue

            selection_rank += 1

            row = trade.to_dict()
            row["selection_method"] = method
            row["score_column"] = score_column or ""
            row["selection_rank"] = selection_rank
            row["max_positions"] = max_positions

            selected_rows.append(row)

            accepted_intervals.append(
                {
                    "entry_time": trade["entry_time"],
                    "exit_time": trade["exit_time"],
                }
            )

    selected = pd.DataFrame(selected_rows)

    if selected.empty:
        return selected

    selected = selected.sort_values("entry_time").reset_index(drop=True)
    selected["selected_trade_number"] = selected.index + 1

    return selected


def summarize_selected_trades(
    selected: pd.DataFrame,
    method: str,
    score_column: str | None,
) -> dict | None:
    if selected.empty:
        return None

    selected = selected.sort_values("entry_time").reset_index(drop=True)
    selected["trade_number"] = selected.index + 1

    selected_with_equity, equity_curve = simulate_orb_equity(
        selected,
        initial_capital=ORB_INITIAL_CAPITAL,
        position_size=ORB_POSITION_SIZE,
    )

    equity_curve = add_equity_curve_fields(
        equity_curve=equity_curve,
        initial_capital=ORB_INITIAL_CAPITAL,
    )

    summary = summarize_research_backtest(
        trades=selected_with_equity,
        equity_curve=equity_curve,
        initial_capital=ORB_INITIAL_CAPITAL,
    )

    if summary is None:
        return None

    return {
        "selection_method": method,
        "score_column": score_column or "",
        "max_positions": ORB_MAX_OPEN_POSITIONS,
        "trades": summary["trades"],
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
    }


def add_method_selection_flags(
    candidates: pd.DataFrame,
    selected_all: pd.DataFrame,
) -> pd.DataFrame:
    output = candidates.copy()

    output["candidate_id"] = (
        output["date"].astype(str)
        + "_"
        + output["ticker"].astype(str)
        + "_"
        + pd.to_datetime(output["entry_time"]).dt.strftime("%H%M%S")
    )

    if selected_all.empty:
        return output

    selected = selected_all.copy()
    selected["candidate_id"] = (
        selected["date"].astype(str)
        + "_"
        + selected["ticker"].astype(str)
        + "_"
        + pd.to_datetime(selected["entry_time"]).dt.strftime("%H%M%S")
    )

    methods = sorted(selected["selection_method"].unique())

    for method in methods:
        method_ids = set(
            selected.loc[
                selected["selection_method"] == method,
                "candidate_id",
            ]
        )

        safe_method = method.lower().replace(" ", "_").replace("-", "_")
        output[f"selected_by_{safe_method}"] = output["candidate_id"].isin(method_ids)

    return output


def main() -> None:
    print("\n=== ORB SIGNAL FACTOR DIAGNOSTICS ===")
    print("Research-only. This does not modify paper trades.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Breakout window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

    candidate_trades = build_research_trades(
        prices=prices,
        allowed_tickers=ORB_ALLOWED_TICKERS,
        breakout_start=ORB_BREAKOUT_START,
        breakout_end=ORB_BREAKOUT_END,
        r_multiple=ORB_R_MULTIPLE,
        max_opening_range=ORB_MAX_OPENING_RANGE,
        min_gap=ORB_MIN_GAP,
        cost_per_trade=ORB_COST_PER_TRADE,
        same_bar_priority=SAME_BAR_PRIORITY,
        eod_exit_time=EOD_EXIT_TIME,
        verbose=True,
    )

    if candidate_trades.empty:
        print("No candidate trades found.")
        return

    candidate_trades = candidate_trades.sort_values("entry_time").reset_index(drop=True)
    candidate_trades["candidate_number"] = candidate_trades.index + 1

    candidates = add_factor_columns(candidate_trades)

    methods = [
        ("earliest", None),
        ("latest", None),
        ("combined", "combined_score"),
        ("combined_inverse", "combined_inverse_score"),
        ("opening_range_small", "opening_range_score"),
        ("opening_range_large", "opening_range_inverse_score"),
        ("gap_abs_small", "gap_abs_score"),
        ("gap_abs_large", "gap_abs_inverse_score"),
        ("gap_signed_high", "gap_signed_score"),
        ("gap_signed_low", "gap_signed_inverse_score"),
        ("breakout_early", "breakout_time_score"),
        ("breakout_late", "breakout_time_inverse_score"),
        ("ticker_quality_high", "ticker_quality_score"),
        ("ticker_quality_low", "ticker_quality_inverse_score"),
    ]

    selected_frames = []
    summaries = []

    for method, score_column in methods:
        selected = select_trades_with_capacity(
            trades=candidates,
            method=method,
            score_column=score_column,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        if not selected.empty:
            selected_frames.append(selected)

        summary = summarize_selected_trades(
            selected=selected,
            method=method,
            score_column=score_column,
        )

        if summary is not None:
            summaries.append(summary)

    selected_all = (
        pd.concat(selected_frames, ignore_index=True)
        if selected_frames
        else pd.DataFrame()
    )

    diagnostics = pd.DataFrame(summaries)

    if not diagnostics.empty:
        diagnostics = diagnostics.sort_values(
            ["total_return", "profit_factor", "trades"],
            ascending=[False, False, False],
        ).reset_index(drop=True)

        diagnostics["rank_total_return"] = diagnostics.index + 1

    candidates_output = add_method_selection_flags(
        candidates=candidates,
        selected_all=selected_all,
    )

    export_csv_for_power_bi(diagnostics, OUTPUT_DIAGNOSTICS_FILE)
    export_csv_for_power_bi(selected_all, OUTPUT_SELECTED_FILE)
    export_csv_for_power_bi(candidates_output, OUTPUT_CANDIDATES_FILE)

    print("\n=== FACTOR DIAGNOSTIC RESULTS ===")
    print(diagnostics.to_string(index=False))

    print("\n=== TOP 20 CANDIDATES BY NET RETURN ===")
    display_columns = [
        "date",
        "ticker",
        "entry_time",
        "exit_reason",
        "net_return",
        "gap",
        "opening_range_pct",
        "breakout_minutes_from_start",
        "ticker_quality_raw",
        "combined_score",
    ]

    print(
        candidates_output.sort_values(
            ["net_return", "entry_time"],
            ascending=[False, True],
        )[display_columns]
        .head(20)
        .to_string(index=False)
    )

    print(f"\nSaved diagnostics -> {OUTPUT_DIAGNOSTICS_FILE}")
    print(f"Saved selected    -> {OUTPUT_SELECTED_FILE}")
    print(f"Saved candidates  -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()