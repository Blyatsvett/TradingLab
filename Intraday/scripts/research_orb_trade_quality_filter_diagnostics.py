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


OUTPUT_DIAGNOSTICS_FILE = DATA_DIR / "orb_trade_quality_filter_diagnostics.csv"
OUTPUT_SELECTED_FILE = DATA_DIR / "orb_trade_quality_filter_selected_trades.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "orb_trade_quality_filter_candidates.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

BASELINE_FILTER_NAME = "baseline_all_valid"

# Guardrails for research-only candidate classification.
# These do NOT make production decisions.
MIN_SELECTED_TRADES_FOR_RESEARCH_CANDIDATE = 30
MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE = 0.0010  # 0.10% account return


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

        # Pure production-style baseline:
        # earliest entry first, ticker only used as stable deterministic tie-breaker.
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


def build_filter_definitions() -> list[dict]:
    return [
        {
            "filter_name": BASELINE_FILTER_NAME,
            "filter_group": "baseline",
            "description": "All valid candidate trades. Current research baseline.",
            "filter_fn": lambda df: pd.Series(True, index=df.index),
        },
        {
            "filter_name": "opening_range_min_0_50pct",
            "filter_group": "opening_range",
            "description": "Keep trades with opening range >= 0.50%.",
            "filter_fn": lambda df: df["opening_range_pct"] >= 0.005,
        },
        {
            "filter_name": "opening_range_min_0_75pct",
            "filter_group": "opening_range",
            "description": "Keep trades with opening range >= 0.75%.",
            "filter_fn": lambda df: df["opening_range_pct"] >= 0.0075,
        },
        {
            "filter_name": "opening_range_max_1_50pct",
            "filter_group": "opening_range",
            "description": "Keep trades with opening range <= 1.50%.",
            "filter_fn": lambda df: df["opening_range_pct"] <= 0.015,
        },
        {
            "filter_name": "opening_range_max_2_00pct",
            "filter_group": "opening_range",
            "description": "Keep trades with opening range <= 2.00%.",
            "filter_fn": lambda df: df["opening_range_pct"] <= 0.020,
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
            "filter_name": "gap_abs_max_1_00pct",
            "filter_group": "gap",
            "description": "Keep trades with absolute gap <= 1.00%.",
            "filter_fn": lambda df: df["gap_abs"] <= 0.010,
        },
        {
            "filter_name": "gap_abs_max_1_50pct",
            "filter_group": "gap",
            "description": "Keep trades with absolute gap <= 1.50%.",
            "filter_fn": lambda df: df["gap_abs"] <= 0.015,
        },
        {
            "filter_name": "gap_abs_min_0_25pct",
            "filter_group": "gap",
            "description": "Keep trades with absolute gap >= 0.25%.",
            "filter_fn": lambda df: df["gap_abs"] >= 0.0025,
        },
        {
            "filter_name": "gap_abs_between_0_25pct_and_1_50pct",
            "filter_group": "gap",
            "description": "Keep trades with absolute gap between 0.25% and 1.50%.",
            "filter_fn": lambda df: (
                (df["gap_abs"] >= 0.0025)
                & (df["gap_abs"] <= 0.015)
            ),
        },
        {
            "filter_name": "risk_pct_max_1_00pct",
            "filter_group": "risk",
            "description": "Keep trades with risk <= 1.00%.",
            "filter_fn": lambda df: df["risk_pct"] <= 0.010,
        },
        {
            "filter_name": "risk_pct_max_1_50pct",
            "filter_group": "risk",
            "description": "Keep trades with risk <= 1.50%.",
            "filter_fn": lambda df: df["risk_pct"] <= 0.015,
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
            "filter_name": "only_09_35_to_10_00",
            "filter_group": "entry_time",
            "description": "Keep only entries from 09:35 through 10:00.",
            "filter_fn": lambda df: df["entry_minutes"] <= time_to_minutes("10:00"),
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
            "filter_name": "quality_combo_or_0_50_to_2_00_gap_max_1_50",
            "filter_group": "combo",
            "description": "Opening range 0.50%-2.00% and absolute gap <= 1.50%.",
            "filter_fn": lambda df: (
                (df["opening_range_pct"] >= 0.005)
                & (df["opening_range_pct"] <= 0.020)
                & (df["gap_abs"] <= 0.015)
            ),
        },
        {
            "filter_name": "quality_combo_or_0_50_to_2_00_gap_max_1_50_exclude_09_40",
            "filter_group": "combo",
            "description": (
                "Opening range 0.50%-2.00%, absolute gap <= 1.50%, "
                "and exclude 09:40 entries."
            ),
            "filter_fn": lambda df: (
                (df["opening_range_pct"] >= 0.005)
                & (df["opening_range_pct"] <= 0.020)
                & (df["gap_abs"] <= 0.015)
                & (df["entry_time_bucket"] != "09:40")
            ),
        },
    ]


def calculate_profit_factor(returns: pd.Series) -> float:
    returns = pd.to_numeric(returns, errors="coerce").dropna()

    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()

    if losses == 0:
        if gains > 0:
            return 999.0
        return 0.0

    return float(gains / abs(losses))


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


def summarize_filter_result(
    filtered_candidates: pd.DataFrame,
    selected_trades: pd.DataFrame,
    filter_name: str,
    filter_group: str,
    description: str,
    total_candidates_before_filter: int,
) -> tuple[dict, pd.DataFrame]:
    candidate_count = len(filtered_candidates)

    empty_summary = {
        "filter_name": filter_name,
        "filter_group": filter_group,
        "description": description,
        "candidates_before_filter": total_candidates_before_filter,
        "candidates_after_filter": candidate_count,
        "candidate_keep_rate": (
            candidate_count / total_candidates_before_filter
            if total_candidates_before_filter > 0
            else 0.0
        ),
        "selected_trades": 0,
        "unique_trade_dates": 0,
        "first_date": "",
        "last_date": "",
        "final_equity": ORB_INITIAL_CAPITAL,
        "total_return": 0.0,
        "win_rate": 0.0,
        "avg_trade": 0.0,
        "median_trade": 0.0,
        "best_trade": 0.0,
        "worst_trade": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "target_count": 0,
        "stop_count": 0,
        "close_count": 0,
        "other_exit_count": 0,
        "avg_gap": 0.0,
        "avg_gap_abs": 0.0,
        "avg_opening_range_pct": 0.0,
        "avg_risk_pct": 0.0,
        "avg_entry_minutes_from_breakout_start": 0.0,
    }

    if selected_trades.empty:
        return empty_summary, pd.DataFrame()

    selected_trades = normalise_trade_data(selected_trades)
    selected_trades = selected_trades.sort_values("entry_time").reset_index(drop=True)
    selected_trades["trade_number"] = selected_trades.index + 1

    selected_with_equity, equity_curve = simulate_orb_equity(
        selected_trades,
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

    returns = pd.to_numeric(selected_with_equity["net_return"], errors="coerce")
    exit_counts = calculate_exit_counts(selected_with_equity)

    selected_with_equity["filter_name"] = filter_name
    selected_with_equity["filter_group"] = filter_group
    selected_with_equity["filter_description"] = description

    summary_row = {
        "filter_name": filter_name,
        "filter_group": filter_group,
        "description": description,
        "candidates_before_filter": total_candidates_before_filter,
        "candidates_after_filter": candidate_count,
        "candidate_keep_rate": (
            candidate_count / total_candidates_before_filter
            if total_candidates_before_filter > 0
            else 0.0
        ),
        "selected_trades": summary["trades"],
        "unique_trade_dates": int(selected_with_equity["date"].nunique()),
        "first_date": selected_with_equity["date"].min(),
        "last_date": selected_with_equity["date"].max(),
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "median_trade": float(returns.median()) if len(returns.dropna()) > 0 else 0.0,
        "best_trade": float(returns.max()) if len(returns.dropna()) > 0 else 0.0,
        "worst_trade": float(returns.min()) if len(returns.dropna()) > 0 else 0.0,
        "profit_factor": summary["profit_factor"],
        "max_drawdown": summary["max_drawdown"],
        "avg_gap": float(selected_with_equity["gap"].mean()),
        "avg_gap_abs": float(selected_with_equity["gap_abs"].mean()),
        "avg_opening_range_pct": float(selected_with_equity["opening_range_pct"].mean()),
        "avg_risk_pct": float(selected_with_equity["risk_pct"].mean()),
        "avg_entry_minutes_from_breakout_start": float(
            selected_with_equity["entry_minutes_from_breakout_start"].mean()
        ),
    }

    summary_row.update(exit_counts)

    return summary_row, selected_with_equity


def add_baseline_comparison(diagnostics: pd.DataFrame) -> pd.DataFrame:
    diagnostics = diagnostics.copy()

    baseline_rows = diagnostics[diagnostics["filter_name"] == BASELINE_FILTER_NAME]

    if baseline_rows.empty:
        diagnostics["baseline_total_return"] = 0.0
        diagnostics["baseline_final_equity"] = ORB_INITIAL_CAPITAL
        diagnostics["baseline_profit_factor"] = 0.0
        diagnostics["baseline_selected_trades"] = 0
        diagnostics["excess_return_vs_baseline"] = 0.0
        diagnostics["excess_equity_vs_baseline"] = 0.0
        diagnostics["beats_baseline"] = False
        diagnostics["trade_count_change_vs_baseline"] = 0
        diagnostics["research_candidate"] = False
        return diagnostics

    baseline = baseline_rows.iloc[0]

    diagnostics["baseline_total_return"] = baseline["total_return"]
    diagnostics["baseline_final_equity"] = baseline["final_equity"]
    diagnostics["baseline_profit_factor"] = baseline["profit_factor"]
    diagnostics["baseline_selected_trades"] = baseline["selected_trades"]

    diagnostics["excess_return_vs_baseline"] = (
        diagnostics["total_return"] - diagnostics["baseline_total_return"]
    )

    diagnostics["excess_equity_vs_baseline"] = (
        diagnostics["final_equity"] - diagnostics["baseline_final_equity"]
    )

    diagnostics["beats_baseline"] = diagnostics["excess_return_vs_baseline"] > 0

    diagnostics["trade_count_change_vs_baseline"] = (
        diagnostics["selected_trades"] - diagnostics["baseline_selected_trades"]
    )

    diagnostics["enough_trades_for_research_candidate"] = (
        diagnostics["selected_trades"] >= MIN_SELECTED_TRADES_FOR_RESEARCH_CANDIDATE
    )

    diagnostics["materially_beats_baseline"] = (
        diagnostics["excess_return_vs_baseline"]
        >= MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE
    )

    diagnostics["research_candidate"] = (
        diagnostics["enough_trades_for_research_candidate"]
        & diagnostics["materially_beats_baseline"]
        & (diagnostics["filter_name"] != BASELINE_FILTER_NAME)
    )

    diagnostics = diagnostics.sort_values(
        [
            "total_return",
            "profit_factor",
            "selected_trades",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    diagnostics["filter_rank"] = diagnostics.index + 1

    return diagnostics


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
    print("\n=== ORB TRADE QUALITY FILTER DIAGNOSTICS ===")
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
    print(
        "Minimum selected trades for research candidate: "
        f"{MIN_SELECTED_TRADES_FOR_RESEARCH_CANDIDATE}"
    )
    print(
        "Minimum excess return for research candidate: "
        f"{MIN_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE:.2%}"
    )

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

    filter_definitions = build_filter_definitions()

    summary_rows = []
    selected_frames = []

    total_candidates_before_filter = len(candidate_trades)

    for filter_definition in filter_definitions:
        filter_name = filter_definition["filter_name"]
        filter_group = filter_definition["filter_group"]
        description = filter_definition["description"]
        filter_fn = filter_definition["filter_fn"]

        print(f"\n--- Testing filter: {filter_name} ---")

        filter_mask = filter_fn(candidate_trades).fillna(False)
        filtered_candidates = candidate_trades[filter_mask].copy()

        selected_trades = select_earliest_trades_with_capacity(
            trades=filtered_candidates,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        summary_row, selected_with_equity = summarize_filter_result(
            filtered_candidates=filtered_candidates,
            selected_trades=selected_trades,
            filter_name=filter_name,
            filter_group=filter_group,
            description=description,
            total_candidates_before_filter=total_candidates_before_filter,
        )

        summary_rows.append(summary_row)

        if not selected_with_equity.empty:
            selected_frames.append(selected_with_equity)

        print(
            f"Candidates kept: {len(filtered_candidates)} / "
            f"{total_candidates_before_filter}"
        )
        print(f"Selected trades: {summary_row['selected_trades']}")
        print(f"Total return: {summary_row['total_return']:.4%}")
        print(f"Profit factor: {summary_row['profit_factor']:.4f}")

    diagnostics = pd.DataFrame(summary_rows)

    if diagnostics.empty:
        print("No diagnostics produced.")
        return

    diagnostics = add_baseline_comparison(diagnostics)

    selected_output = (
        pd.concat(selected_frames, ignore_index=True)
        if selected_frames
        else pd.DataFrame()
    )

    candidate_output = add_candidate_filter_flags(
        candidates=candidate_trades,
        filter_definitions=filter_definitions,
    )

    export_csv_for_power_bi(diagnostics, OUTPUT_DIAGNOSTICS_FILE)
    export_csv_for_power_bi(selected_output, OUTPUT_SELECTED_FILE)
    export_csv_for_power_bi(candidate_output, OUTPUT_CANDIDATES_FILE)

    print("\n=== TRADE QUALITY FILTER DIAGNOSTIC RESULTS ===")

    display_columns = [
        "filter_rank",
        "filter_name",
        "filter_group",
        "candidates_after_filter",
        "selected_trades",
        "total_return",
        "win_rate",
        "avg_trade",
        "profit_factor",
        "max_drawdown",
        "excess_return_vs_baseline",
        "trade_count_change_vs_baseline",
        "research_candidate",
    ]

    print(diagnostics[display_columns].to_string(index=False))

    print("\n=== RESEARCH CANDIDATES ===")

    candidates = diagnostics[diagnostics["research_candidate"]].copy()

    if candidates.empty:
        print("No filter passed the research-candidate guardrails.")
    else:
        print(candidates[display_columns].to_string(index=False))

    print(f"\nSaved diagnostics -> {OUTPUT_DIAGNOSTICS_FILE}")
    print(f"Saved selected    -> {OUTPUT_SELECTED_FILE}")
    print(f"Saved candidates  -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()