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


OUTPUT_SUMMARY_FILE = DATA_DIR / "orb_risk_filter_shadow_summary.csv"
OUTPUT_REPORT_FILE = DATA_DIR / "orb_risk_filter_shadow_report.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "orb_risk_filter_shadow_candidates.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention.
# This keeps the shadow report consistent with the recent research scripts.
EOD_EXIT_TIME = None

RISK_FILTER_THRESHOLD = 0.0200

BASELINE_METHOD = "baseline_current_rules"
RISK_FILTER_METHOD = "shadow_risk_le_2_00pct"


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

    trades["entry_minutes_from_breakout_start"] = (
        trades["entry_minutes"] - time_to_minutes(ORB_BREAKOUT_START)
    )

    numeric_columns = [
        "net_return",
        "gross_return",
        "entry_price",
        "exit_price",
        "stop_price",
        "target_price",
        "gap",
        "opening_range_pct",
    ]

    for column in numeric_columns:
        if column in trades.columns:
            trades[column] = pd.to_numeric(trades[column], errors="coerce")

    if "gap" not in trades.columns:
        trades["gap"] = 0.0

    if "opening_range_pct" not in trades.columns:
        trades["opening_range_pct"] = 0.0

    trades["gap_abs"] = trades["gap"].abs()

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

    trades["passes_risk_filter"] = trades["risk_pct"] <= RISK_FILTER_THRESHOLD

    trades["trade_key"] = (
        trades["date"].astype(str)
        + "_"
        + trades["ticker"].astype(str)
        + "_"
        + trades["entry_time"].dt.strftime("%H:%M:%S")
    )

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
    method_name: str,
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
            row["selection_method"] = method_name
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
    selection_method: str,
) -> tuple[dict, pd.DataFrame]:
    empty_summary = {
        "selection_method": selection_method,
        "risk_filter_threshold": (
            RISK_FILTER_THRESHOLD if selection_method == RISK_FILTER_METHOD else 0.0
        ),
        "selected_trades": 0,
        "unique_trade_dates": 0,
        "first_date": "",
        "last_date": "",
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
        "avg_risk_pct": 0.0,
        "max_risk_pct": 0.0,
        "avg_gap_abs": 0.0,
        "avg_opening_range_pct": 0.0,
    }

    if selected.empty:
        return empty_summary, pd.DataFrame()

    selected = normalise_trade_data(selected)
    selected = selected.sort_values("entry_time").reset_index(drop=True)
    selected["trade_number"] = selected.index + 1
    selected["selection_method"] = selection_method

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

    summary_row = {
        "selection_method": selection_method,
        "risk_filter_threshold": (
            RISK_FILTER_THRESHOLD if selection_method == RISK_FILTER_METHOD else 0.0
        ),
        "selected_trades": summary["trades"],
        "unique_trade_dates": int(selected_with_equity["date"].nunique()),
        "first_date": selected_with_equity["date"].min(),
        "last_date": selected_with_equity["date"].max(),
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
        "avg_risk_pct": float(selected_with_equity["risk_pct"].mean()),
        "max_risk_pct": float(selected_with_equity["risk_pct"].max()),
        "avg_gap_abs": float(selected_with_equity["gap_abs"].mean()),
        "avg_opening_range_pct": float(
            selected_with_equity["opening_range_pct"].mean()
        ),
    }

    summary_row.update(exit_counts)

    return summary_row, selected_with_equity


def classify_shadow_actions(
    baseline_selected: pd.DataFrame,
    risk_selected: pd.DataFrame,
) -> pd.DataFrame:
    baseline = baseline_selected.copy()
    risk = risk_selected.copy()

    if baseline.empty and risk.empty:
        return pd.DataFrame()

    baseline_keys = set(baseline["trade_key"]) if not baseline.empty else set()
    risk_keys = set(risk["trade_key"]) if not risk.empty else set()

    baseline_rank_map = (
        baseline.set_index("trade_key")["selection_rank"].to_dict()
        if not baseline.empty and "selection_rank" in baseline.columns
        else {}
    )

    risk_rank_map = (
        risk.set_index("trade_key")["selection_rank"].to_dict()
        if not risk.empty and "selection_rank" in risk.columns
        else {}
    )

    report = pd.concat(
        [
            baseline,
            risk,
        ],
        ignore_index=True,
    )

    report = report.sort_values("entry_time").drop_duplicates(
        subset=["trade_key"],
        keep="first",
    )

    report["selected_by_baseline"] = report["trade_key"].isin(baseline_keys)
    report["selected_by_shadow_risk_filter"] = report["trade_key"].isin(risk_keys)

    report["baseline_selection_rank"] = (
        report["trade_key"].map(baseline_rank_map).fillna(0)
    )

    report["shadow_selection_rank"] = (
        report["trade_key"].map(risk_rank_map).fillna(0)
    )

    if "passes_risk_filter" not in report.columns:
        report["passes_risk_filter"] = report["risk_pct"] <= RISK_FILTER_THRESHOLD

    def action(row) -> str:
        if row["selected_by_baseline"] and row["selected_by_shadow_risk_filter"]:
            return "TAKEN_BY_BOTH"

        if row["selected_by_baseline"] and not row["selected_by_shadow_risk_filter"]:
            if not row["passes_risk_filter"]:
                return "REMOVED_BY_RISK_FILTER"
            return "REMOVED_BY_CAPACITY_CHANGE"

        if not row["selected_by_baseline"] and row["selected_by_shadow_risk_filter"]:
            return "ADDED_BY_RISK_FILTER_CAPACITY"

        return "NOT_SELECTED"

    report["shadow_action"] = report.apply(action, axis=1)

    report["shadow_pnl_difference_return"] = 0.0

    report.loc[
        report["shadow_action"].eq("REMOVED_BY_RISK_FILTER"),
        "shadow_pnl_difference_return",
    ] = -report["net_return"]

    report.loc[
        report["shadow_action"].eq("REMOVED_BY_CAPACITY_CHANGE"),
        "shadow_pnl_difference_return",
    ] = -report["net_return"]

    report.loc[
        report["shadow_action"].eq("ADDED_BY_RISK_FILTER_CAPACITY"),
        "shadow_pnl_difference_return",
    ] = report["net_return"]

    report["shadow_pnl_difference_sek_estimate"] = (
        report["shadow_pnl_difference_return"]
        * ORB_INITIAL_CAPITAL
        * ORB_POSITION_SIZE
    )

    report = report.sort_values(
        [
            "date",
            "entry_time",
            "ticker",
        ]
    ).reset_index(drop=True)

    report["report_row_number"] = report.index + 1

    return report
    baseline = baseline_selected.copy()
    risk = risk_selected.copy()

    baseline["selected_by_baseline"] = True
    risk["selected_by_shadow_risk_filter"] = True

    baseline_cols = [
        "trade_key",
        "selected_by_baseline",
        "selection_rank",
    ]

    risk_cols = [
        "trade_key",
        "selected_by_shadow_risk_filter",
        "selection_rank",
    ]

    baseline_flags = baseline[baseline_cols].rename(
        columns={"selection_rank": "baseline_selection_rank"}
    )

    risk_flags = risk[risk_cols].rename(
        columns={"selection_rank": "shadow_selection_rank"}
    )

    all_selected = pd.concat(
        [
            baseline,
            risk,
        ],
        ignore_index=True,
    )

    all_selected = all_selected.sort_values("entry_time").drop_duplicates(
        subset=["trade_key"],
        keep="first",
    )

    report = all_selected.merge(
        baseline_flags,
        on="trade_key",
        how="left",
    ).merge(
        risk_flags,
        on="trade_key",
        how="left",
    )

    report["selected_by_baseline"] = report["selected_by_baseline"].fillna(False)
    report["selected_by_shadow_risk_filter"] = report[
        "selected_by_shadow_risk_filter"
    ].fillna(False)

    report["baseline_selection_rank"] = report["baseline_selection_rank"].fillna(0)
    report["shadow_selection_rank"] = report["shadow_selection_rank"].fillna(0)

    def action(row) -> str:
        if row["selected_by_baseline"] and row["selected_by_shadow_risk_filter"]:
            return "TAKEN_BY_BOTH"

        if row["selected_by_baseline"] and not row["selected_by_shadow_risk_filter"]:
            if not row["passes_risk_filter"]:
                return "REMOVED_BY_RISK_FILTER"
            return "REMOVED_BY_CAPACITY_CHANGE"

        if not row["selected_by_baseline"] and row["selected_by_shadow_risk_filter"]:
            return "ADDED_BY_RISK_FILTER_CAPACITY"

        return "NOT_SELECTED"

    report["shadow_action"] = report.apply(action, axis=1)

    report["shadow_pnl_difference_return"] = 0.0

    report.loc[
        report["shadow_action"].eq("REMOVED_BY_RISK_FILTER"),
        "shadow_pnl_difference_return",
    ] = -report["net_return"]

    report.loc[
        report["shadow_action"].eq("REMOVED_BY_CAPACITY_CHANGE"),
        "shadow_pnl_difference_return",
    ] = -report["net_return"]

    report.loc[
        report["shadow_action"].eq("ADDED_BY_RISK_FILTER_CAPACITY"),
        "shadow_pnl_difference_return",
    ] = report["net_return"]

    report["shadow_pnl_difference_sek_estimate"] = (
        report["shadow_pnl_difference_return"]
        * ORB_INITIAL_CAPITAL
        * ORB_POSITION_SIZE
    )

    report = report.sort_values(
        [
            "date",
            "entry_time",
            "ticker",
        ]
    ).reset_index(drop=True)

    report["report_row_number"] = report.index + 1

    return report


def build_daily_shadow_summary(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty:
        return pd.DataFrame()

    rows = []

    for trade_date, day in report.groupby("date"):
        baseline_trades = day[day["selected_by_baseline"]]
        shadow_trades = day[day["selected_by_shadow_risk_filter"]]

        removed_by_risk = day[day["shadow_action"].eq("REMOVED_BY_RISK_FILTER")]
        removed_by_capacity = day[
            day["shadow_action"].eq("REMOVED_BY_CAPACITY_CHANGE")
        ]
        added_by_capacity = day[
            day["shadow_action"].eq("ADDED_BY_RISK_FILTER_CAPACITY")
        ]

        rows.append(
            {
                "date": trade_date,
                "baseline_trades": int(len(baseline_trades)),
                "shadow_trades": int(len(shadow_trades)),
                "removed_by_risk_filter": int(len(removed_by_risk)),
                "removed_by_capacity_change": int(len(removed_by_capacity)),
                "added_by_risk_filter_capacity": int(len(added_by_capacity)),
                "baseline_net_return": float(baseline_trades["net_return"].sum()),
                "shadow_net_return": float(shadow_trades["net_return"].sum()),
                "shadow_return_difference": float(
                    shadow_trades["net_return"].sum()
                    - baseline_trades["net_return"].sum()
                ),
                "shadow_pnl_difference_sek_estimate": float(
                    (
                        shadow_trades["net_return"].sum()
                        - baseline_trades["net_return"].sum()
                    )
                    * ORB_INITIAL_CAPITAL
                    * ORB_POSITION_SIZE
                ),
                "max_baseline_risk_pct": (
                    float(baseline_trades["risk_pct"].max())
                    if not baseline_trades.empty
                    else 0.0
                ),
                "max_shadow_risk_pct": (
                    float(shadow_trades["risk_pct"].max())
                    if not shadow_trades.empty
                    else 0.0
                ),
            }
        )

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def add_summary_comparison(summary: pd.DataFrame) -> pd.DataFrame:
    summary = summary.copy()

    baseline = summary[summary["selection_method"].eq(BASELINE_METHOD)]

    if baseline.empty:
        summary["baseline_total_return"] = 0.0
        summary["baseline_final_equity"] = ORB_INITIAL_CAPITAL
        summary["baseline_profit_factor"] = 0.0
        summary["excess_return_vs_baseline"] = 0.0
        summary["excess_equity_vs_baseline"] = 0.0
        summary["beats_baseline"] = False
        return summary

    baseline_row = baseline.iloc[0]

    summary["baseline_total_return"] = baseline_row["total_return"]
    summary["baseline_final_equity"] = baseline_row["final_equity"]
    summary["baseline_profit_factor"] = baseline_row["profit_factor"]

    summary["excess_return_vs_baseline"] = (
        summary["total_return"] - summary["baseline_total_return"]
    )

    summary["excess_equity_vs_baseline"] = (
        summary["final_equity"] - summary["baseline_final_equity"]
    )

    summary["beats_baseline"] = summary["excess_return_vs_baseline"] > 0

    return summary


def main() -> None:
    print("\n=== ORB RISK FILTER SHADOW REPORT ===")
    print("Research-only. This does not modify paper trades.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Breakout window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Shadow risk filter: risk_pct <= {RISK_FILTER_THRESHOLD:.2%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

    candidates = build_research_trades(
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

    if candidates.empty:
        print("No candidate trades found.")
        return

    candidates = normalise_trade_data(candidates)
    candidates = candidates.sort_values("entry_time").reset_index(drop=True)
    candidates["candidate_number"] = candidates.index + 1

    baseline_selected = select_earliest_trades_with_capacity(
        trades=candidates,
        method_name=BASELINE_METHOD,
        max_positions=ORB_MAX_OPEN_POSITIONS,
    )

    risk_candidates = candidates[candidates["passes_risk_filter"]].copy()

    risk_selected = select_earliest_trades_with_capacity(
        trades=risk_candidates,
        method_name=RISK_FILTER_METHOD,
        max_positions=ORB_MAX_OPEN_POSITIONS,
    )

    baseline_summary, baseline_with_equity = summarize_selected_trades(
        selected=baseline_selected,
        selection_method=BASELINE_METHOD,
    )

    risk_summary, risk_with_equity = summarize_selected_trades(
        selected=risk_selected,
        selection_method=RISK_FILTER_METHOD,
    )

    summary = pd.DataFrame([baseline_summary, risk_summary])
    summary = add_summary_comparison(summary)

    shadow_report = classify_shadow_actions(
        baseline_selected=baseline_with_equity,
        risk_selected=risk_with_equity,
    )

    daily_summary = build_daily_shadow_summary(shadow_report)

    candidates["shadow_risk_filter_threshold"] = RISK_FILTER_THRESHOLD

    export_csv_for_power_bi(summary, OUTPUT_SUMMARY_FILE)
    export_csv_for_power_bi(shadow_report, OUTPUT_REPORT_FILE)
    export_csv_for_power_bi(candidates, OUTPUT_CANDIDATES_FILE)

    print("\n=== SHADOW SUMMARY ===")

    summary_columns = [
        "selection_method",
        "selected_trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "avg_risk_pct",
        "max_risk_pct",
        "excess_return_vs_baseline",
        "excess_equity_vs_baseline",
        "beats_baseline",
    ]

    print(summary[summary_columns].to_string(index=False))

    print("\n=== SHADOW ACTIONS ===")

    action_summary = (
        shadow_report.groupby("shadow_action")
        .agg(
            trades=("trade_key", "count"),
            total_net_return=("net_return", "sum"),
            shadow_return_difference=("shadow_pnl_difference_return", "sum"),
            shadow_pnl_difference_sek_estimate=(
                "shadow_pnl_difference_sek_estimate",
                "sum",
            ),
        )
        .reset_index()
        .sort_values("shadow_return_difference", ascending=False)
    )

    print(action_summary.to_string(index=False))

    print("\n=== TRADES REMOVED BY RISK FILTER ===")

    removed = shadow_report[
        shadow_report["shadow_action"].eq("REMOVED_BY_RISK_FILTER")
    ].copy()

    removed_columns = [
        "date",
        "ticker",
        "entry_time",
        "exit_time",
        "exit_reason",
        "net_return",
        "opening_range_pct",
        "gap",
        "risk_pct",
        "shadow_pnl_difference_sek_estimate",
    ]

    if removed.empty:
        print("No baseline trades were removed by the risk filter.")
    else:
        print(removed[removed_columns].to_string(index=False))

    print("\n=== TRADES ADDED BY SHADOW RISK FILTER ===")

    added = shadow_report[
        shadow_report["shadow_action"].eq("ADDED_BY_RISK_FILTER_CAPACITY")
    ].copy()

    added_columns = [
        "date",
        "ticker",
        "entry_time",
        "exit_time",
        "exit_reason",
        "net_return",
        "opening_range_pct",
        "gap",
        "risk_pct",
        "shadow_pnl_difference_sek_estimate",
    ]

    if added.empty:
        print("No replacement trades were added by the risk filter.")
    else:
        print(added[added_columns].to_string(index=False))

    print("\n=== DAILY SHADOW DIFFERENCES ===")

    daily_display_columns = [
        "date",
        "baseline_trades",
        "shadow_trades",
        "removed_by_risk_filter",
        "added_by_risk_filter_capacity",
        "baseline_net_return",
        "shadow_net_return",
        "shadow_return_difference",
        "shadow_pnl_difference_sek_estimate",
    ]

    if daily_summary.empty:
        print("No daily shadow summary produced.")
    else:
        changed_days = daily_summary[
            daily_summary["shadow_return_difference"].abs() > 0
        ].copy()

        if changed_days.empty:
            print("No days differed between baseline and shadow risk filter.")
        else:
            print(changed_days[daily_display_columns].to_string(index=False))

    print(f"\nSaved summary    -> {OUTPUT_SUMMARY_FILE}")
    print(f"Saved report     -> {OUTPUT_REPORT_FILE}")
    print(f"Saved candidates -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()