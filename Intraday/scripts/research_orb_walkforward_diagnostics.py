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


OUTPUT_DIAGNOSTICS_FILE = DATA_DIR / "orb_walkforward_diagnostics.csv"
OUTPUT_METHOD_SUMMARY_FILE = DATA_DIR / "orb_walkforward_method_summary.csv"
OUTPUT_SELECTED_FILE = DATA_DIR / "orb_walkforward_selected_trades.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "orb_walkforward_candidates.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

# Number of unique trade dates per walk-forward chunk.
PERIOD_SIZE_DATES = 15


METHODS = [
    {
        "selection_method": "earliest",
        "score_column": None,
        "description": "Earliest entry first. Pure deterministic baseline.",
    },
    {
        "selection_method": "breakout_early",
        "score_column": "breakout_time_score",
        "description": "Earlier breakout receives higher score.",
    },
    {
        "selection_method": "opening_range_large",
        "score_column": "opening_range_large_score",
        "description": "Larger opening range receives higher score.",
    },
    {
        "selection_method": "gap_abs_small",
        "score_column": "gap_abs_score",
        "description": "Smaller absolute gap receives higher score.",
    },
    {
        "selection_method": "combined_observable",
        "score_column": "combined_observable_score",
        "description": "Observable combo: early breakout, larger range, smaller gap.",
    },
    {
        "selection_method": "latest",
        "score_column": None,
        "description": "Latest entry first. Negative-control baseline.",
    },
]


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


def add_observable_factor_columns(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()

    trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")

    if "date" not in trades.columns:
        trades["date"] = trades["entry_time"].dt.strftime("%Y-%m-%d")

    trades["date"] = pd.to_datetime(trades["date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )

    trades["gap"] = pd.to_numeric(trades["gap"], errors="coerce")
    trades["gap_abs"] = trades["gap"].abs()

    trades["opening_range_pct"] = pd.to_numeric(
        trades["opening_range_pct"],
        errors="coerce",
    )

    trades["net_return"] = pd.to_numeric(trades["net_return"], errors="coerce")
    trades["gross_return"] = pd.to_numeric(trades["gross_return"], errors="coerce")

    trades["breakout_minutes_from_start"] = calculate_breakout_minutes(trades)

    trades["breakout_time_score"] = minmax_score(
        trades["breakout_minutes_from_start"],
        higher_is_better=False,
    )

    trades["opening_range_small_score"] = minmax_score(
        trades["opening_range_pct"],
        higher_is_better=False,
    )

    trades["opening_range_large_score"] = minmax_score(
        trades["opening_range_pct"],
        higher_is_better=True,
    )

    trades["gap_abs_score"] = minmax_score(
        trades["gap_abs"],
        higher_is_better=False,
    )

    trades["gap_abs_large_score"] = minmax_score(
        trades["gap_abs"],
        higher_is_better=True,
    )

    # Observable-only combined score.
    # No ticker-quality factor here, because ticker quality based on the same sample
    # would leak future outcome information.
    trades["combined_observable_score"] = (
        0.45 * trades["breakout_time_score"]
        + 0.35 * trades["opening_range_large_score"]
        + 0.20 * trades["gap_abs_score"]
    ).round(6)

    return trades


def assign_walkforward_periods(
    candidates: pd.DataFrame,
    period_size_dates: int,
) -> pd.DataFrame:
    candidates = candidates.copy()

    unique_dates = (
        pd.Series(candidates["date"].dropna().unique())
        .sort_values()
        .reset_index(drop=True)
    )

    date_to_period = {}

    for date_index, date_value in enumerate(unique_dates):
        period_number = int(date_index // period_size_dates) + 1
        date_to_period[date_value] = period_number

    candidates["period_number"] = candidates["date"].map(date_to_period)
    candidates["period_label"] = candidates["period_number"].apply(
        lambda value: f"P{int(value):02d}"
    )

    period_rows = []

    for period_number, period_candidates in candidates.groupby("period_number"):
        period_dates = sorted(period_candidates["date"].unique())

        period_rows.append(
            {
                "period_number": int(period_number),
                "period_label": f"P{int(period_number):02d}",
                "period_start": period_dates[0],
                "period_end": period_dates[-1],
                "unique_trade_dates": len(period_dates),
                "candidate_trades": len(period_candidates),
            }
        )

    period_df = pd.DataFrame(period_rows)

    candidates = candidates.merge(
        period_df[
            [
                "period_number",
                "period_start",
                "period_end",
                "unique_trade_dates",
                "candidate_trades",
            ]
        ],
        on="period_number",
        how="left",
    )

    return candidates


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
    selection_method: str,
    score_column: str | None,
    max_positions: int,
) -> pd.DataFrame:
    trades = trades.copy()

    selected_rows = []

    for trade_date, day_trades in trades.groupby("date"):
        day_trades = day_trades.copy()

        if selection_method == "earliest":
            # Pure deterministic baseline:
            # earliest entry first, ticker only used as stable tie-breaker.
            day_trades = day_trades.sort_values(
                ["entry_time", "ticker"],
                ascending=[True, True],
            )

        elif selection_method == "latest":
            # Negative-control baseline:
            # latest entry first, ticker only used as stable tie-breaker.
            day_trades = day_trades.sort_values(
                ["entry_time", "ticker"],
                ascending=[False, True],
            )

        else:
            if score_column is None:
                raise ValueError(
                    f"score_column required for selection_method={selection_method}"
                )

            day_trades = day_trades.sort_values(
                [score_column, "entry_time", "ticker"],
                ascending=[False, True, True],
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
            row["selection_method"] = selection_method
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
    period_type: str,
    period_number: int,
    period_label: str,
    period_start: str,
    period_end: str,
    selection_method: str,
    score_column: str | None,
    description: str,
) -> tuple[dict | None, pd.DataFrame]:
    if selected.empty:
        return None, pd.DataFrame()

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
        return None, pd.DataFrame()

    selected_with_equity["period_type"] = period_type
    selected_with_equity["period_number"] = period_number
    selected_with_equity["period_label"] = period_label
    selected_with_equity["period_start"] = period_start
    selected_with_equity["period_end"] = period_end
    selected_with_equity["selection_method"] = selection_method
    selected_with_equity["score_column"] = score_column or ""
    selected_with_equity["selection_description"] = description

    summary_row = {
        "period_type": period_type,
        "period_number": period_number,
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "selection_method": selection_method,
        "score_column": score_column or "",
        "selection_description": description,
        "max_positions": ORB_MAX_OPEN_POSITIONS,
        "trades": summary["trades"],
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
    }

    return summary_row, selected_with_equity


def run_method_set_for_period(
    period_type: str,
    period_number: int,
    period_label: str,
    period_start: str,
    period_end: str,
    candidates: pd.DataFrame,
) -> tuple[list[dict], list[pd.DataFrame]]:
    summaries = []
    selected_frames = []

    for method_config in METHODS:
        selection_method = method_config["selection_method"]
        score_column = method_config["score_column"]
        description = method_config["description"]

        selected = select_trades_with_capacity(
            trades=candidates,
            selection_method=selection_method,
            score_column=score_column,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        summary, selected_with_equity = summarize_selected_trades(
            selected=selected,
            period_type=period_type,
            period_number=period_number,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
            selection_method=selection_method,
            score_column=score_column,
            description=description,
        )

        if summary is not None:
            summaries.append(summary)

        if not selected_with_equity.empty:
            selected_frames.append(selected_with_equity)

    return summaries, selected_frames


def add_relative_metrics(diagnostics: pd.DataFrame) -> pd.DataFrame:
    diagnostics = diagnostics.copy()

    baseline = diagnostics[
        diagnostics["selection_method"] == "earliest"
    ][
        [
            "period_type",
            "period_label",
            "total_return",
            "final_equity",
            "profit_factor",
        ]
    ].rename(
        columns={
            "total_return": "earliest_total_return",
            "final_equity": "earliest_final_equity",
            "profit_factor": "earliest_profit_factor",
        }
    )

    diagnostics = diagnostics.merge(
        baseline,
        on=["period_type", "period_label"],
        how="left",
    )

    diagnostics["excess_return_vs_earliest"] = (
        diagnostics["total_return"] - diagnostics["earliest_total_return"]
    )

    diagnostics["excess_equity_vs_earliest"] = (
        diagnostics["final_equity"] - diagnostics["earliest_final_equity"]
    )

    diagnostics["beats_earliest"] = diagnostics["excess_return_vs_earliest"] > 0

    diagnostics["period_best_return"] = diagnostics.groupby(
        ["period_type", "period_label"]
    )["total_return"].transform("max")

    diagnostics["is_period_winner"] = (
        diagnostics["total_return"] == diagnostics["period_best_return"]
    )

    diagnostics = diagnostics.sort_values(
        [
            "period_type",
            "period_number",
            "total_return",
            "profit_factor",
        ],
        ascending=[
            True,
            True,
            False,
            False,
        ],
    ).reset_index(drop=True)

    return diagnostics


def build_method_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
    period_only = diagnostics[diagnostics["period_type"] == "PERIOD"].copy()

    if period_only.empty:
        return pd.DataFrame()

    grouped = period_only.groupby("selection_method")

    summary = grouped.agg(
        periods_tested=("period_label", "nunique"),
        avg_total_return=("total_return", "mean"),
        median_total_return=("total_return", "median"),
        min_total_return=("total_return", "min"),
        max_total_return=("total_return", "max"),
        avg_excess_return_vs_earliest=("excess_return_vs_earliest", "mean"),
        periods_beating_earliest=("beats_earliest", "sum"),
        periods_won=("is_period_winner", "sum"),
        avg_trades=("trades", "mean"),
        avg_profit_factor=("profit_factor", "mean"),
        worst_drawdown=("max_drawdown", "min"),
    ).reset_index()

    summary = summary.sort_values(
        [
            "avg_excess_return_vs_earliest",
            "avg_total_return",
            "avg_profit_factor",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    summary["method_rank"] = summary.index + 1

    return summary


def main() -> None:
    print("\n=== ORB WALK-FORWARD DIAGNOSTICS ===")
    print("Research-only. This does not modify paper trades.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Breakout window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Walk-forward period size: {PERIOD_SIZE_DATES} unique trade dates")
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

    candidates = add_observable_factor_columns(candidate_trades)

    candidates = assign_walkforward_periods(
        candidates=candidates,
        period_size_dates=PERIOD_SIZE_DATES,
    )

    all_summaries = []
    all_selected_frames = []

    all_period_start = candidates["date"].min()
    all_period_end = candidates["date"].max()

    summaries, selected_frames = run_method_set_for_period(
        period_type="ALL",
        period_number=0,
        period_label="ALL",
        period_start=all_period_start,
        period_end=all_period_end,
        candidates=candidates,
    )

    all_summaries.extend(summaries)
    all_selected_frames.extend(selected_frames)

    for period_number, period_candidates in candidates.groupby("period_number"):
        period_candidates = period_candidates.copy()

        period_label = f"P{int(period_number):02d}"
        period_start = period_candidates["date"].min()
        period_end = period_candidates["date"].max()

        summaries, selected_frames = run_method_set_for_period(
            period_type="PERIOD",
            period_number=int(period_number),
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
            candidates=period_candidates,
        )

        all_summaries.extend(summaries)
        all_selected_frames.extend(selected_frames)

    diagnostics = pd.DataFrame(all_summaries)

    if diagnostics.empty:
        print("No diagnostics produced.")
        return

    diagnostics = add_relative_metrics(diagnostics)
    method_summary = build_method_summary(diagnostics)

    selected_all = (
        pd.concat(all_selected_frames, ignore_index=True)
        if all_selected_frames
        else pd.DataFrame()
    )

    export_csv_for_power_bi(diagnostics, OUTPUT_DIAGNOSTICS_FILE)
    export_csv_for_power_bi(method_summary, OUTPUT_METHOD_SUMMARY_FILE)
    export_csv_for_power_bi(selected_all, OUTPUT_SELECTED_FILE)
    export_csv_for_power_bi(candidates, OUTPUT_CANDIDATES_FILE)

    print("\n=== METHOD SUMMARY ACROSS WALK-FORWARD PERIODS ===")
    print(method_summary.to_string(index=False))

    print("\n=== WALK-FORWARD PERIOD RESULTS ===")

    period_columns = [
        "period_label",
        "period_start",
        "period_end",
        "selection_method",
        "trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "excess_return_vs_earliest",
        "beats_earliest",
        "is_period_winner",
    ]

    print(
        diagnostics.loc[
            diagnostics["period_type"] == "PERIOD",
            period_columns,
        ].to_string(index=False)
    )

    print("\n=== WHOLE-SAMPLE RESULTS ===")

    all_columns = [
        "selection_method",
        "trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "excess_return_vs_earliest",
        "beats_earliest",
        "is_period_winner",
    ]

    print(
        diagnostics.loc[
            diagnostics["period_type"] == "ALL",
            all_columns,
        ].to_string(index=False)
    )

    print(f"\nSaved diagnostics    -> {OUTPUT_DIAGNOSTICS_FILE}")
    print(f"Saved method summary -> {OUTPUT_METHOD_SUMMARY_FILE}")
    print(f"Saved selected       -> {OUTPUT_SELECTED_FILE}")
    print(f"Saved candidates     -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()