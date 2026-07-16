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


OUTPUT_RESEARCH_FILE = DATA_DIR / "orb_signal_scoring_research.csv"
OUTPUT_SUMMARY_FILE = DATA_DIR / "orb_signal_scoring_summary.csv"
OUTPUT_SELECTED_FILE = DATA_DIR / "orb_signal_scoring_selected_trades.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
# Paper trading uses 16:30, but historical research currently uses final bar.
EOD_EXIT_TIME = None

SCORE_WEIGHTS = {
    "opening_range_score": 0.35,
    "breakout_time_score": 0.25,
    "gap_score": 0.20,
    "ticker_quality_score": 0.20,
}


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


def add_signal_scores(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()

    trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")

    if "date" not in trades.columns:
        trades["date"] = trades["entry_time"].dt.strftime("%Y-%m-%d")

    trades["gap_abs"] = pd.to_numeric(trades["gap"], errors="coerce").abs()
    trades["opening_range_pct"] = pd.to_numeric(
        trades["opening_range_pct"],
        errors="coerce",
    )
    trades["net_return"] = pd.to_numeric(trades["net_return"], errors="coerce")

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

    trades["gap_score"] = minmax_score(
        trades["gap_abs"],
        higher_is_better=False,
    )

    trades["breakout_time_score"] = minmax_score(
        trades["breakout_minutes_from_start"],
        higher_is_better=False,
    )

    trades["ticker_quality_score"] = minmax_score(
        trades["ticker_quality_raw"],
        higher_is_better=True,
    )

    trades["signal_score"] = 0.0

    for column, weight in SCORE_WEIGHTS.items():
        trades["signal_score"] += trades[column] * weight

    trades["signal_score"] = trades["signal_score"].round(6)

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
    max_positions: int,
) -> pd.DataFrame:
    trades = trades.copy()

    if method not in {"earliest", "score"}:
        raise ValueError(f"Unknown selection method: {method}")

    selected_rows = []

    for trade_date, day_trades in trades.groupby("date"):
        day_trades = day_trades.copy()

        if method == "earliest":
            day_trades = day_trades.sort_values(
                ["entry_time", "signal_score"],
                ascending=[True, False],
            )
        else:
            day_trades = day_trades.sort_values(
                ["signal_score", "entry_time"],
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
        "max_positions": ORB_MAX_OPEN_POSITIONS,
        "trades": summary["trades"],
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
    }


def add_selection_flags(
    scored_trades: pd.DataFrame,
    earliest_selected: pd.DataFrame,
    score_selected: pd.DataFrame,
) -> pd.DataFrame:
    output = scored_trades.copy()

    output["candidate_id"] = (
        output["date"].astype(str)
        + "_"
        + output["ticker"].astype(str)
        + "_"
        + pd.to_datetime(output["entry_time"]).dt.strftime("%H%M%S")
    )

    output["selected_by_earliest"] = False
    output["selected_by_score"] = False
    output["earliest_selection_rank"] = 0
    output["score_selection_rank"] = 0

    if not earliest_selected.empty:
        earliest = earliest_selected.copy()
        earliest["candidate_id"] = (
            earliest["date"].astype(str)
            + "_"
            + earliest["ticker"].astype(str)
            + "_"
            + pd.to_datetime(earliest["entry_time"]).dt.strftime("%H%M%S")
        )

        earliest_rank_map = dict(
            zip(
                earliest["candidate_id"],
                earliest["selection_rank"],
            )
        )

        output["selected_by_earliest"] = output["candidate_id"].isin(
            earliest_rank_map.keys()
        )
        output["earliest_selection_rank"] = (
            output["candidate_id"].map(earliest_rank_map).fillna(0).astype(int)
        )

    if not score_selected.empty:
        score = score_selected.copy()
        score["candidate_id"] = (
            score["date"].astype(str)
            + "_"
            + score["ticker"].astype(str)
            + "_"
            + pd.to_datetime(score["entry_time"]).dt.strftime("%H%M%S")
        )

        score_rank_map = dict(
            zip(
                score["candidate_id"],
                score["selection_rank"],
            )
        )

        output["selected_by_score"] = output["candidate_id"].isin(
            score_rank_map.keys()
        )
        output["score_selection_rank"] = (
            output["candidate_id"].map(score_rank_map).fillna(0).astype(int)
        )

    return output


def main() -> None:
    print("\n=== ORB SIGNAL SCORING RESEARCH ===")
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

    scored_trades = add_signal_scores(candidate_trades)

    earliest_selected = select_trades_with_capacity(
        trades=scored_trades,
        method="earliest",
        max_positions=ORB_MAX_OPEN_POSITIONS,
    )

    score_selected = select_trades_with_capacity(
        trades=scored_trades,
        method="score",
        max_positions=ORB_MAX_OPEN_POSITIONS,
    )

    research_output = add_selection_flags(
        scored_trades=scored_trades,
        earliest_selected=earliest_selected,
        score_selected=score_selected,
    )

    selected_output = pd.concat(
        [
            earliest_selected,
            score_selected,
        ],
        ignore_index=True,
    )

    summaries = []

    earliest_summary = summarize_selected_trades(
        selected=earliest_selected,
        method="earliest",
    )

    score_summary = summarize_selected_trades(
        selected=score_selected,
        method="score",
    )

    if earliest_summary is not None:
        summaries.append(earliest_summary)

    if score_summary is not None:
        summaries.append(score_summary)

    summary_df = pd.DataFrame(summaries)

    export_csv_for_power_bi(research_output, OUTPUT_RESEARCH_FILE)
    export_csv_for_power_bi(summary_df, OUTPUT_SUMMARY_FILE)
    export_csv_for_power_bi(selected_output, OUTPUT_SELECTED_FILE)

    print("\n=== SIGNAL SCORING SUMMARY ===")
    print(summary_df.to_string(index=False))

    print("\n=== TOP 20 SCORED CANDIDATES ===")
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
        "signal_score",
        "selected_by_earliest",
        "selected_by_score",
    ]

    print(
        research_output.sort_values(
            ["signal_score", "entry_time"],
            ascending=[False, True],
        )[display_columns]
        .head(20)
        .to_string(index=False)
    )

    print(f"\nSaved research output -> {OUTPUT_RESEARCH_FILE}")
    print(f"Saved summary output  -> {OUTPUT_SUMMARY_FILE}")
    print(f"Saved selected trades -> {OUTPUT_SELECTED_FILE}")


if __name__ == "__main__":
    main()