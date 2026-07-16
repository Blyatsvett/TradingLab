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


OUTPUT_DIAGNOSTICS_FILE = (
    DATA_DIR / "orb_trade_quality_filter_walkforward_diagnostics.csv"
)
OUTPUT_METHOD_SUMMARY_FILE = (
    DATA_DIR / "orb_trade_quality_filter_walkforward_method_summary.csv"
)
OUTPUT_SELECTED_FILE = (
    DATA_DIR / "orb_trade_quality_filter_walkforward_selected_trades.csv"
)
OUTPUT_CANDIDATES_FILE = (
    DATA_DIR / "orb_trade_quality_filter_walkforward_candidates.csv"
)

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

BASELINE_FILTER_NAME = "baseline_all_valid"

# Number of unique trade dates per walk-forward period.
PERIOD_SIZE_DATES = 15

# Guardrails for research-only classification.
MIN_SELECTED_TRADES_FOR_RESEARCH_CANDIDATE = 10
MIN_AVG_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE = 0.0002
MIN_PERIODS_NOT_WORSE_THAN_BASELINE = 2


def time_to_minutes(time_value: str) -> int:
    timestamp = pd.to_datetime(f"2000-01-01 {time_value}")
    return int(timestamp.hour * 60 + timestamp.minute)


def normalise_trade_data(trades: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()

    trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")

    if "date" not in trades.columns:
        trades["date"] = trades["entry_time"].dt.strftime("%Y-%m-%d")
    else:
        trades["date"] = pd.to_datetime(trades["date"], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )

    trades["entry_time_bucket"] = trades["entry_time"].dt.strftime("%H:%M")
    trades["entry_minutes"] = (
        trades["entry_time"].dt.hour * 60 + trades["entry_time"].dt.minute
    )

    breakout_start_minutes = time_to_minutes(ORB_BREAKOUT_START)
    trades["entry_minutes_from_breakout_start"] = (
        trades["entry_minutes"] - breakout_start_minutes
    )

    trades["net_return"] = pd.to_numeric(trades["net_return"], errors="coerce")
    trades["gross_return"] = pd.to_numeric(trades["gross_return"], errors="coerce")

    trades["entry_price"] = pd.to_numeric(trades["entry_price"], errors="coerce")
    trades["stop_price"] = pd.to_numeric(trades["stop_price"], errors="coerce")
    trades["target_price"] = pd.to_numeric(trades["target_price"], errors="coerce")

    if "gap" in trades.columns:
        trades["gap"] = pd.to_numeric(trades["gap"], errors="coerce")
    else:
        trades["gap"] = 0.0

    trades["gap_abs"] = trades["gap"].abs()

    if "opening_range_pct" in trades.columns:
        trades["opening_range_pct"] = pd.to_numeric(
            trades["opening_range_pct"],
            errors="coerce",
        )
    else:
        trades["opening_range_pct"] = 0.0

    trades["risk_pct"] = (
        (trades["entry_price"] - trades["stop_price"]) / trades["entry_price"]
    )

    trades["target_return_pct"] = (
        (trades["target_price"] - trades["entry_price"]) / trades["entry_price"]
    )

    trades["risk_pct"] = pd.to_numeric(trades["risk_pct"], errors="coerce").fillna(0.0)
    trades["target_return_pct"] = pd.to_numeric(
        trades["target_return_pct"],
        errors="coerce",
    ).fillna(0.0)

    return trades


def build_filter_definitions() -> list[dict]:
    return [
        {
            "filter_name": BASELINE_FILTER_NAME,
            "filter_group": "baseline",
            "description": "All valid candidate trades. Current baseline.",
            "filter_fn": lambda df: pd.Series(True, index=df.index),
        },
        {
            "filter_name": "risk_pct_max_2_00pct",
            "filter_group": "risk",
            "description": "Keep trades with risk <= 2.00%.",
            "filter_fn": lambda df: df["risk_pct"] <= 0.020,
        },
        {
            "filter_name": "exclude_09_40",
            "filter_group": "entry_time",
            "description": "Exclude 09:40 entries.",
            "filter_fn": lambda df: df["entry_time_bucket"] != "09:40",
        },
        {
            "filter_name": "exclude_after_10_45",
            "filter_group": "entry_time",
            "description": "Exclude entries after 10:45.",
            "filter_fn": lambda df: df["entry_minutes"] <= time_to_minutes("10:45"),
        },
        {
            "filter_name": "exclude_09_40_and_after_10_45",
            "filter_group": "combo",
            "description": "Exclude 09:40 entries and entries after 10:45.",
            "filter_fn": lambda df: (
                (df["entry_time_bucket"] != "09:40")
                & (df["entry_minutes"] <= time_to_minutes("10:45"))
            ),
        },
        {
            "filter_name": "opening_range_min_0_50pct",
            "filter_group": "opening_range",
            "description": "Keep trades with opening range >= 0.50%.",
            "filter_fn": lambda df: df["opening_range_pct"] >= 0.005,
        },
        {
            "filter_name": "opening_range_between_0_50pct_and_2_00pct",
            "filter_group": "opening_range",
            "description": "Keep trades with opening range between 0.50% and 2.00%.",
            "filter_fn": lambda df: (
                (df["opening_range_pct"] >= 0.005)
                & (df["opening_range_pct"] <= 0.020)
            ),
        },
        {
            "filter_name": "gap_abs_max_1_50pct",
            "filter_group": "gap",
            "description": "Keep trades with absolute gap <= 1.50%.",
            "filter_fn": lambda df: df["gap_abs"] <= 0.015,
        },
    ]


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
                "candidate_trades_in_period": len(period_candidates),
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
                "candidate_trades_in_period",
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


def select_earliest_trades_with_capacity(
    trades: pd.DataFrame,
    max_positions: int,
) -> pd.DataFrame:
    trades = normalise_trade_data(trades)

    selected_rows = []

    for trade_date, day_trades in trades.groupby("date"):
        day_trades = day_trades.copy()

        # Production-style selection:
        # earliest entry first, ticker only used as deterministic tie-breaker.
        day_trades = day_trades.sort_values(
            ["entry_time", "ticker"],
            ascending=[True, True],
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


def calculate_exit_counts(trades: pd.DataFrame) -> dict:
    if trades.empty or "exit_reason" not in trades.columns:
        return {
            "target_count": 0,
            "stop_count": 0,
            "close_count": 0,
            "other_exit_count": 0,
        }

    exit_reasons = trades["exit_reason"].astype(str).str.lower()

    return {
        "target_count": int((exit_reasons == "target").sum()),
        "stop_count": int((exit_reasons == "stop").sum()),
        "close_count": int((exit_reasons == "close").sum()),
        "other_exit_count": int(
            (~exit_reasons.isin(["target", "stop", "close"])).sum()
        ),
    }


def summarize_selected_trades(
    selected: pd.DataFrame,
    period_type: str,
    period_number: int,
    period_label: str,
    period_start: str,
    period_end: str,
    filter_name: str,
    filter_group: str,
    filter_description: str,
    candidates_before_filter: int,
    candidates_after_filter: int,
) -> tuple[dict, pd.DataFrame]:
    empty_summary = {
        "period_type": period_type,
        "period_number": period_number,
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "filter_name": filter_name,
        "filter_group": filter_group,
        "filter_description": filter_description,
        "candidates_before_filter": candidates_before_filter,
        "candidates_after_filter": candidates_after_filter,
        "candidate_keep_rate": (
            candidates_after_filter / candidates_before_filter
            if candidates_before_filter > 0
            else 0.0
        ),
        "selected_trades": 0,
        "unique_trade_dates": 0,
        "final_equity": ORB_INITIAL_CAPITAL,
        "total_return": 0.0,
        "win_rate": 0.0,
        "avg_trade": 0.0,
        "max_drawdown": 0.0,
        "profit_factor": 0.0,
        "target_count": 0,
        "stop_count": 0,
        "close_count": 0,
        "other_exit_count": 0,
        "avg_gap_abs": 0.0,
        "avg_opening_range_pct": 0.0,
        "avg_risk_pct": 0.0,
        "avg_entry_minutes_from_breakout_start": 0.0,
    }

    if selected.empty:
        return empty_summary, pd.DataFrame()

    selected = normalise_trade_data(selected)
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
        return empty_summary, pd.DataFrame()

    exit_counts = calculate_exit_counts(selected_with_equity)

    selected_with_equity["period_type"] = period_type
    selected_with_equity["period_number"] = period_number
    selected_with_equity["period_label"] = period_label
    selected_with_equity["period_start"] = period_start
    selected_with_equity["period_end"] = period_end
    selected_with_equity["filter_name"] = filter_name
    selected_with_equity["filter_group"] = filter_group
    selected_with_equity["filter_description"] = filter_description

    summary_row = {
        "period_type": period_type,
        "period_number": period_number,
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "filter_name": filter_name,
        "filter_group": filter_group,
        "filter_description": filter_description,
        "candidates_before_filter": candidates_before_filter,
        "candidates_after_filter": candidates_after_filter,
        "candidate_keep_rate": (
            candidates_after_filter / candidates_before_filter
            if candidates_before_filter > 0
            else 0.0
        ),
        "selected_trades": summary["trades"],
        "unique_trade_dates": int(selected_with_equity["date"].nunique()),
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
        "avg_gap_abs": float(selected_with_equity["gap_abs"].mean()),
        "avg_opening_range_pct": float(
            selected_with_equity["opening_range_pct"].mean()
        ),
        "avg_risk_pct": float(selected_with_equity["risk_pct"].mean()),
        "avg_entry_minutes_from_breakout_start": float(
            selected_with_equity["entry_minutes_from_breakout_start"].mean()
        ),
    }

    summary_row.update(exit_counts)

    return summary_row, selected_with_equity


def run_filters_for_period(
    candidates: pd.DataFrame,
    period_type: str,
    period_number: int,
    period_label: str,
    period_start: str,
    period_end: str,
    filter_definitions: list[dict],
) -> tuple[list[dict], list[pd.DataFrame]]:
    summaries = []
    selected_frames = []

    candidates_before_filter = len(candidates)

    for filter_definition in filter_definitions:
        filter_name = filter_definition["filter_name"]
        filter_group = filter_definition["filter_group"]
        filter_description = filter_definition["description"]
        filter_fn = filter_definition["filter_fn"]

        filter_mask = filter_fn(candidates).fillna(False)
        filtered_candidates = candidates[filter_mask].copy()

        selected = select_earliest_trades_with_capacity(
            trades=filtered_candidates,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        summary_row, selected_with_equity = summarize_selected_trades(
            selected=selected,
            period_type=period_type,
            period_number=period_number,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
            filter_name=filter_name,
            filter_group=filter_group,
            filter_description=filter_description,
            candidates_before_filter=candidates_before_filter,
            candidates_after_filter=len(filtered_candidates),
        )

        summaries.append(summary_row)

        if not selected_with_equity.empty:
            selected_frames.append(selected_with_equity)

    return summaries, selected_frames


def add_baseline_comparison(diagnostics: pd.DataFrame) -> pd.DataFrame:
    diagnostics = diagnostics.copy()

    baseline = diagnostics[
        diagnostics["filter_name"] == BASELINE_FILTER_NAME
    ][
        [
            "period_type",
            "period_label",
            "total_return",
            "final_equity",
            "profit_factor",
            "selected_trades",
        ]
    ].rename(
        columns={
            "total_return": "baseline_total_return",
            "final_equity": "baseline_final_equity",
            "profit_factor": "baseline_profit_factor",
            "selected_trades": "baseline_selected_trades",
        }
    )

    diagnostics = diagnostics.merge(
        baseline,
        on=["period_type", "period_label"],
        how="left",
    )

    diagnostics["excess_return_vs_baseline"] = (
        diagnostics["total_return"] - diagnostics["baseline_total_return"]
    )

    diagnostics["excess_equity_vs_baseline"] = (
        diagnostics["final_equity"] - diagnostics["baseline_final_equity"]
    )

    diagnostics["beats_baseline"] = diagnostics["excess_return_vs_baseline"] > 0

    diagnostics["not_worse_than_baseline"] = (
        diagnostics["excess_return_vs_baseline"] >= 0
    )

    diagnostics["trade_count_change_vs_baseline"] = (
        diagnostics["selected_trades"] - diagnostics["baseline_selected_trades"]
    )

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

    grouped = period_only.groupby(["filter_name", "filter_group"])

    summary = grouped.agg(
        periods_tested=("period_label", "nunique"),
        avg_total_return=("total_return", "mean"),
        median_total_return=("total_return", "median"),
        min_total_return=("total_return", "min"),
        max_total_return=("total_return", "max"),
        avg_excess_return_vs_baseline=("excess_return_vs_baseline", "mean"),
        median_excess_return_vs_baseline=("excess_return_vs_baseline", "median"),
        periods_beating_baseline=("beats_baseline", "sum"),
        periods_not_worse_than_baseline=("not_worse_than_baseline", "sum"),
        periods_won=("is_period_winner", "sum"),
        avg_selected_trades=("selected_trades", "mean"),
        min_selected_trades=("selected_trades", "min"),
        avg_profit_factor=("profit_factor", "mean"),
        worst_drawdown=("max_drawdown", "min"),
    ).reset_index()

    summary["enough_trades_for_research_candidate"] = (
        summary["min_selected_trades"] >= MIN_SELECTED_TRADES_FOR_RESEARCH_CANDIDATE
    )

    summary["material_avg_excess_return"] = (
        summary["avg_excess_return_vs_baseline"]
        >= MIN_AVG_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE
    )

    summary["stable_enough_vs_baseline"] = (
        summary["periods_not_worse_than_baseline"]
        >= MIN_PERIODS_NOT_WORSE_THAN_BASELINE
    )

    summary["research_candidate"] = (
        summary["enough_trades_for_research_candidate"]
        & summary["material_avg_excess_return"]
        & summary["stable_enough_vs_baseline"]
        & (summary["filter_name"] != BASELINE_FILTER_NAME)
    )

    summary = summary.sort_values(
        [
            "research_candidate",
            "avg_excess_return_vs_baseline",
            "avg_total_return",
            "avg_profit_factor",
        ],
        ascending=[
            False,
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    summary["method_rank"] = summary.index + 1

    return summary


def add_candidate_filter_flags(
    candidates: pd.DataFrame,
    filter_definitions: list[dict],
) -> pd.DataFrame:
    output = candidates.copy()

    for filter_definition in filter_definitions:
        filter_name = filter_definition["filter_name"]
        filter_fn = filter_definition["filter_fn"]

        safe_name = filter_name.lower().replace("-", "_").replace(" ", "_")

        try:
            output[f"passes_{safe_name}"] = filter_fn(output).fillna(False)
        except Exception:
            output[f"passes_{safe_name}"] = False

    return output


def main() -> None:
    print("\n=== ORB TRADE QUALITY FILTER WALK-FORWARD ===")
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

    candidate_trades = normalise_trade_data(candidate_trades)
    candidate_trades = candidate_trades.sort_values("entry_time").reset_index(drop=True)
    candidate_trades["candidate_number"] = candidate_trades.index + 1

    candidate_trades = assign_walkforward_periods(
        candidates=candidate_trades,
        period_size_dates=PERIOD_SIZE_DATES,
    )

    filter_definitions = build_filter_definitions()

    all_summary_rows = []
    all_selected_frames = []

    all_period_start = candidate_trades["date"].min()
    all_period_end = candidate_trades["date"].max()

    summaries, selected_frames = run_filters_for_period(
        candidates=candidate_trades,
        period_type="ALL",
        period_number=0,
        period_label="ALL",
        period_start=all_period_start,
        period_end=all_period_end,
        filter_definitions=filter_definitions,
    )

    all_summary_rows.extend(summaries)
    all_selected_frames.extend(selected_frames)

    for period_number, period_candidates in candidate_trades.groupby("period_number"):
        period_candidates = period_candidates.copy()

        period_label = f"P{int(period_number):02d}"
        period_start = period_candidates["date"].min()
        period_end = period_candidates["date"].max()

        summaries, selected_frames = run_filters_for_period(
            candidates=period_candidates,
            period_type="PERIOD",
            period_number=int(period_number),
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
            filter_definitions=filter_definitions,
        )

        all_summary_rows.extend(summaries)
        all_selected_frames.extend(selected_frames)

    diagnostics = pd.DataFrame(all_summary_rows)

    if diagnostics.empty:
        print("No diagnostics produced.")
        return

    diagnostics = add_baseline_comparison(diagnostics)
    method_summary = build_method_summary(diagnostics)

    selected_output = (
        pd.concat(all_selected_frames, ignore_index=True)
        if all_selected_frames
        else pd.DataFrame()
    )

    candidate_output = add_candidate_filter_flags(
        candidates=candidate_trades,
        filter_definitions=filter_definitions,
    )

    export_csv_for_power_bi(diagnostics, OUTPUT_DIAGNOSTICS_FILE)
    export_csv_for_power_bi(method_summary, OUTPUT_METHOD_SUMMARY_FILE)
    export_csv_for_power_bi(selected_output, OUTPUT_SELECTED_FILE)
    export_csv_for_power_bi(candidate_output, OUTPUT_CANDIDATES_FILE)

    print("\n=== METHOD SUMMARY ACROSS WALK-FORWARD PERIODS ===")

    method_columns = [
        "method_rank",
        "filter_name",
        "filter_group",
        "periods_tested",
        "avg_total_return",
        "avg_excess_return_vs_baseline",
        "periods_beating_baseline",
        "periods_not_worse_than_baseline",
        "periods_won",
        "avg_selected_trades",
        "min_selected_trades",
        "avg_profit_factor",
        "worst_drawdown",
        "research_candidate",
    ]

    print(method_summary[method_columns].to_string(index=False))

    print("\n=== WALK-FORWARD PERIOD RESULTS ===")

    period_columns = [
        "period_label",
        "period_start",
        "period_end",
        "filter_name",
        "selected_trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "excess_return_vs_baseline",
        "beats_baseline",
        "is_period_winner",
    ]

    period_rows = diagnostics[diagnostics["period_type"] == "PERIOD"].copy()

    print(
        period_rows.sort_values(
            [
                "period_number",
                "total_return",
                "profit_factor",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        )[period_columns].to_string(index=False)
    )

    print("\n=== WHOLE-SAMPLE RESULTS ===")

    all_columns = [
        "filter_name",
        "selected_trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "excess_return_vs_baseline",
        "beats_baseline",
        "is_period_winner",
    ]

    all_rows = diagnostics[diagnostics["period_type"] == "ALL"].copy()

    print(
        all_rows.sort_values(
            [
                "total_return",
                "profit_factor",
            ],
            ascending=[
                False,
                False,
            ],
        )[all_columns].to_string(index=False)
    )

    print("\n=== RESEARCH CANDIDATES ===")

    research_candidates = method_summary[method_summary["research_candidate"]].copy()

    if research_candidates.empty:
        print("No filter passed the walk-forward research-candidate guardrails.")
    else:
        print(research_candidates[method_columns].to_string(index=False))

    print(f"\nSaved diagnostics    -> {OUTPUT_DIAGNOSTICS_FILE}")
    print(f"Saved method summary -> {OUTPUT_METHOD_SUMMARY_FILE}")
    print(f"Saved selected       -> {OUTPUT_SELECTED_FILE}")
    print(f"Saved candidates     -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()