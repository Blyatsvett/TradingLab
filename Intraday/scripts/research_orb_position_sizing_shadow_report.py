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
    build_research_trades,
    load_normalised_intraday_prices,
)
from Intraday.core.paths import DATA_DIR


OUTPUT_SUMMARY_FILE = DATA_DIR / "orb_position_sizing_shadow_summary.csv"
OUTPUT_REPORT_FILE = DATA_DIR / "orb_position_sizing_shadow_report.csv"
OUTPUT_DAILY_FILE = DATA_DIR / "orb_position_sizing_shadow_daily_summary.csv"
OUTPUT_TRADES_FILE = DATA_DIR / "orb_position_sizing_shadow_trades.csv"
OUTPUT_EQUITY_FILE = DATA_DIR / "orb_position_sizing_shadow_equity_curve.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "orb_position_sizing_shadow_candidates.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

RISK_FILTER_THRESHOLD = 0.0200

BASELINE_METHOD = "baseline_fixed_10pct"

SIZING_FIXED_10 = {
    "sizing_model": "fixed_10pct",
    "model_type": "fixed",
    "description": "Fixed 10% notional position size. Current live baseline.",
    "fixed_position_pct": ORB_POSITION_SIZE,
    "target_account_risk_pct": 0.0,
    "max_position_pct": ORB_POSITION_SIZE,
}

SIZING_RISK_TARGET_015_CAP_20 = {
    "sizing_model": "risk_target_0_15pct_cap_20pct",
    "model_type": "risk_adjusted",
    "description": "Target 0.15% account risk per trade, capped at 20% notional.",
    "fixed_position_pct": 0.0,
    "target_account_risk_pct": 0.0015,
    "max_position_pct": 0.20,
}

SHADOW_METHODS = [
    {
        "shadow_method": BASELINE_METHOD,
        "selection_set": "baseline_current_rules",
        "apply_risk_filter": False,
        "sizing_model": SIZING_FIXED_10,
        "description": "Current baseline: normal selection, fixed 10% position size.",
    },
    {
        "shadow_method": "shadow_risk_sizing_0_15_cap_20",
        "selection_set": "baseline_current_rules",
        "apply_risk_filter": False,
        "sizing_model": SIZING_RISK_TARGET_015_CAP_20,
        "description": "Normal selection, risk-target sizing 0.15% account risk capped at 20%.",
    },
    {
        "shadow_method": "shadow_risk_filter_fixed_10pct",
        "selection_set": "shadow_risk_le_2_00pct",
        "apply_risk_filter": True,
        "sizing_model": SIZING_FIXED_10,
        "description": "Risk <= 2.00% selection filter, fixed 10% position size.",
    },
    {
        "shadow_method": "shadow_risk_filter_plus_risk_sizing",
        "selection_set": "shadow_risk_le_2_00pct",
        "apply_risk_filter": True,
        "sizing_model": SIZING_RISK_TARGET_015_CAP_20,
        "description": "Risk <= 2.00% filter plus risk-target sizing 0.15% capped at 20%.",
    },
]


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

    trades["side"] = "LONG"
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
    selection_set: str,
    max_positions: int,
) -> pd.DataFrame:
    trades = normalise_trade_data(trades)

    selected_rows = []

    for trade_date, day_trades in trades.groupby("date"):
        day_trades = day_trades.copy()

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
            row["selection_set"] = selection_set
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


def calculate_position_pct(
    trade: pd.Series,
    sizing_model: dict,
) -> tuple[float, float, bool]:
    model_type = sizing_model["model_type"]

    if model_type == "fixed":
        position_pct = float(sizing_model["fixed_position_pct"])
        raw_position_pct = position_pct
        capped_by_max_position_size = False

        return position_pct, raw_position_pct, capped_by_max_position_size

    if model_type != "risk_adjusted":
        raise ValueError(f"Unknown sizing model type: {model_type}")

    risk_pct = float(trade.get("risk_pct", 0.0))
    target_account_risk_pct = float(sizing_model["target_account_risk_pct"])
    max_position_pct = float(sizing_model["max_position_pct"])

    if risk_pct <= 0:
        raw_position_pct = 0.0
    else:
        raw_position_pct = target_account_risk_pct / risk_pct

    position_pct = min(raw_position_pct, max_position_pct)
    position_pct = max(position_pct, 0.0)

    capped_by_max_position_size = raw_position_pct > max_position_pct

    return position_pct, raw_position_pct, capped_by_max_position_size


def calculate_profit_factor_from_pnl(pnl: pd.Series) -> float:
    pnl = pd.to_numeric(pnl, errors="coerce").dropna()

    gains = pnl[pnl > 0].sum()
    losses = pnl[pnl < 0].sum()

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


def simulate_shadow_method(
    selected_trades: pd.DataFrame,
    method_definition: dict,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    shadow_method = method_definition["shadow_method"]
    selection_set = method_definition["selection_set"]
    sizing_model = method_definition["sizing_model"]
    sizing_model_name = sizing_model["sizing_model"]

    empty_summary = {
        "shadow_method": shadow_method,
        "selection_set": selection_set,
        "sizing_model": sizing_model_name,
        "model_type": sizing_model["model_type"],
        "description": method_definition["description"],
        "apply_risk_filter": method_definition["apply_risk_filter"],
        "selected_trades": 0,
        "first_date": "",
        "last_date": "",
        "final_equity": ORB_INITIAL_CAPITAL,
        "total_return": 0.0,
        "total_pnl_sek": 0.0,
        "win_rate": 0.0,
        "avg_trade_account_return": 0.0,
        "avg_trade_notional_return": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "avg_position_size_pct": 0.0,
        "max_position_size_pct": 0.0,
        "min_position_size_pct": 0.0,
        "avg_position_size_sek": 0.0,
        "avg_estimated_account_risk_pct": 0.0,
        "max_estimated_account_risk_pct": 0.0,
        "avg_trade_risk_pct": 0.0,
        "max_trade_risk_pct": 0.0,
        "capped_trade_count": 0,
        "target_count": 0,
        "stop_count": 0,
        "close_count": 0,
        "other_exit_count": 0,
    }

    if selected_trades.empty:
        return empty_summary, pd.DataFrame(), pd.DataFrame()

    trades = normalise_trade_data(selected_trades)
    trades = trades.sort_values("entry_time").reset_index(drop=True)

    equity = ORB_INITIAL_CAPITAL
    peak_equity = ORB_INITIAL_CAPITAL

    trade_rows = []
    equity_rows = [
        {
            "shadow_method": shadow_method,
            "selection_set": selection_set,
            "sizing_model": sizing_model_name,
            "trade_number": 0,
            "date": "",
            "ticker": "START",
            "entry_time": "",
            "exit_time": "",
            "equity": ORB_INITIAL_CAPITAL,
            "pnl_sek": 0.0,
            "account_return": 0.0,
            "cumulative_return": 0.0,
            "drawdown_pct": 0.0,
            "position_size_pct": 0.0,
            "estimated_account_risk_pct": 0.0,
        }
    ]

    for trade_index, trade in trades.iterrows():
        position_pct, raw_position_pct, capped_by_max_position_size = (
            calculate_position_pct(
                trade=trade,
                sizing_model=sizing_model,
            )
        )

        position_size_sek = ORB_INITIAL_CAPITAL * position_pct

        # Long-only PnL:
        # positive net_return means the long trade gained.
        # negative net_return means the long trade lost.
        pnl_sek = position_size_sek * float(trade["net_return"])
        account_return = pnl_sek / ORB_INITIAL_CAPITAL

        equity += pnl_sek
        peak_equity = max(peak_equity, equity)

        drawdown_pct = (equity / peak_equity) - 1.0
        cumulative_return = (equity / ORB_INITIAL_CAPITAL) - 1.0

        estimated_account_risk_pct = position_pct * float(trade["risk_pct"])

        row = trade.to_dict()
        row.update(
            {
                "shadow_method": shadow_method,
                "selection_set": selection_set,
                "sizing_model": sizing_model_name,
                "model_type": sizing_model["model_type"],
                "sizing_description": sizing_model["description"],
                "trade_number": trade_index + 1,
                "position_size_pct": position_pct,
                "raw_position_size_pct": raw_position_pct,
                "position_size_sek": position_size_sek,
                "estimated_account_risk_pct": estimated_account_risk_pct,
                "capped_by_max_position_size": capped_by_max_position_size,
                "pnl_sek": pnl_sek,
                "account_return": account_return,
                "equity": equity,
                "cumulative_return": cumulative_return,
                "drawdown_pct": drawdown_pct,
            }
        )

        trade_rows.append(row)

        equity_rows.append(
            {
                "shadow_method": shadow_method,
                "selection_set": selection_set,
                "sizing_model": sizing_model_name,
                "trade_number": trade_index + 1,
                "date": trade["date"],
                "ticker": trade["ticker"],
                "entry_time": trade["entry_time"],
                "exit_time": trade["exit_time"],
                "equity": equity,
                "pnl_sek": pnl_sek,
                "account_return": account_return,
                "cumulative_return": cumulative_return,
                "drawdown_pct": drawdown_pct,
                "position_size_pct": position_pct,
                "estimated_account_risk_pct": estimated_account_risk_pct,
            }
        )

    trades_out = pd.DataFrame(trade_rows)
    equity_curve = pd.DataFrame(equity_rows)

    total_pnl_sek = float(trades_out["pnl_sek"].sum())
    total_return = total_pnl_sek / ORB_INITIAL_CAPITAL

    exit_counts = calculate_exit_counts(trades_out)

    summary = {
        "shadow_method": shadow_method,
        "selection_set": selection_set,
        "sizing_model": sizing_model_name,
        "model_type": sizing_model["model_type"],
        "description": method_definition["description"],
        "apply_risk_filter": method_definition["apply_risk_filter"],
        "selected_trades": int(len(trades_out)),
        "first_date": trades_out["date"].min(),
        "last_date": trades_out["date"].max(),
        "final_equity": float(ORB_INITIAL_CAPITAL + total_pnl_sek),
        "total_return": total_return,
        "total_pnl_sek": total_pnl_sek,
        "win_rate": float((trades_out["pnl_sek"] > 0).mean()),
        "avg_trade_account_return": float(trades_out["account_return"].mean()),
        "avg_trade_notional_return": float(trades_out["net_return"].mean()),
        "profit_factor": calculate_profit_factor_from_pnl(trades_out["pnl_sek"]),
        "max_drawdown": float(equity_curve["drawdown_pct"].min()),
        "avg_position_size_pct": float(trades_out["position_size_pct"].mean()),
        "max_position_size_pct": float(trades_out["position_size_pct"].max()),
        "min_position_size_pct": float(trades_out["position_size_pct"].min()),
        "avg_position_size_sek": float(trades_out["position_size_sek"].mean()),
        "avg_estimated_account_risk_pct": float(
            trades_out["estimated_account_risk_pct"].mean()
        ),
        "max_estimated_account_risk_pct": float(
            trades_out["estimated_account_risk_pct"].max()
        ),
        "avg_trade_risk_pct": float(trades_out["risk_pct"].mean()),
        "max_trade_risk_pct": float(trades_out["risk_pct"].max()),
        "capped_trade_count": int(trades_out["capped_by_max_position_size"].sum()),
    }

    summary.update(exit_counts)

    return summary, trades_out, equity_curve


def add_summary_comparison(summary: pd.DataFrame) -> pd.DataFrame:
    summary = summary.copy()

    baseline = summary[summary["shadow_method"].eq(BASELINE_METHOD)]

    if baseline.empty:
        summary["baseline_total_return"] = 0.0
        summary["baseline_final_equity"] = ORB_INITIAL_CAPITAL
        summary["baseline_total_pnl_sek"] = 0.0
        summary["baseline_profit_factor"] = 0.0
        summary["baseline_max_drawdown"] = 0.0
        summary["excess_return_vs_baseline"] = 0.0
        summary["excess_equity_vs_baseline"] = 0.0
        summary["excess_pnl_sek_vs_baseline"] = 0.0
        summary["profit_factor_change_vs_baseline"] = 0.0
        summary["drawdown_change_vs_baseline"] = 0.0
        summary["beats_baseline"] = False
        return summary

    baseline_row = baseline.iloc[0]

    summary["baseline_total_return"] = baseline_row["total_return"]
    summary["baseline_final_equity"] = baseline_row["final_equity"]
    summary["baseline_total_pnl_sek"] = baseline_row["total_pnl_sek"]
    summary["baseline_profit_factor"] = baseline_row["profit_factor"]
    summary["baseline_max_drawdown"] = baseline_row["max_drawdown"]

    summary["excess_return_vs_baseline"] = (
        summary["total_return"] - summary["baseline_total_return"]
    )

    summary["excess_equity_vs_baseline"] = (
        summary["final_equity"] - summary["baseline_final_equity"]
    )

    summary["excess_pnl_sek_vs_baseline"] = (
        summary["total_pnl_sek"] - summary["baseline_total_pnl_sek"]
    )

    summary["profit_factor_change_vs_baseline"] = (
        summary["profit_factor"] - summary["baseline_profit_factor"]
    )

    # More negative drawdown is worse.
    summary["drawdown_change_vs_baseline"] = (
        summary["max_drawdown"] - summary["baseline_max_drawdown"]
    )

    summary["beats_baseline"] = summary["excess_return_vs_baseline"] > 0

    summary = summary.sort_values(
        ["total_return", "profit_factor"],
        ascending=[False, False],
    ).reset_index(drop=True)

    summary["shadow_rank"] = summary.index + 1

    return summary


def build_shadow_action_report(trades_output: pd.DataFrame) -> pd.DataFrame:
    if trades_output.empty:
        return pd.DataFrame()

    baseline = trades_output[trades_output["shadow_method"].eq(BASELINE_METHOD)].copy()

    if baseline.empty:
        return pd.DataFrame()

    baseline_by_key = baseline.set_index("trade_key")

    rows = []

    for method_name, method_trades in trades_output.groupby("shadow_method"):
        if method_name == BASELINE_METHOD:
            continue

        method_trades = method_trades.copy()
        method_by_key = method_trades.set_index("trade_key")

        all_trade_keys = sorted(
            set(baseline_by_key.index).union(set(method_by_key.index))
        )

        for trade_key in all_trade_keys:
            selected_by_baseline = trade_key in baseline_by_key.index
            selected_by_shadow = trade_key in method_by_key.index

            if selected_by_shadow:
                source = method_by_key.loc[trade_key]
            else:
                source = baseline_by_key.loc[trade_key]

            baseline_row = (
                baseline_by_key.loc[trade_key] if selected_by_baseline else None
            )
            shadow_row = method_by_key.loc[trade_key] if selected_by_shadow else None

            if selected_by_baseline and selected_by_shadow:
                action = "TAKEN_BY_BOTH"
            elif selected_by_baseline and not selected_by_shadow:
                if not bool(source.get("passes_risk_filter", True)):
                    action = "REMOVED_BY_RISK_FILTER"
                else:
                    action = "REMOVED_BY_SELECTION_CHANGE"
            elif not selected_by_baseline and selected_by_shadow:
                action = "ADDED_BY_SHADOW_METHOD"
            else:
                action = "NOT_SELECTED"

            baseline_account_return = (
                float(baseline_row["account_return"]) if baseline_row is not None else 0.0
            )
            shadow_account_return = (
                float(shadow_row["account_return"]) if shadow_row is not None else 0.0
            )

            baseline_pnl_sek = (
                float(baseline_row["pnl_sek"]) if baseline_row is not None else 0.0
            )
            shadow_pnl_sek = (
                float(shadow_row["pnl_sek"]) if shadow_row is not None else 0.0
            )

            baseline_position_size_pct = (
                float(baseline_row["position_size_pct"])
                if baseline_row is not None
                else 0.0
            )
            shadow_position_size_pct = (
                float(shadow_row["position_size_pct"]) if shadow_row is not None else 0.0
            )

            rows.append(
                {
                    "shadow_method": method_name,
                    "trade_key": trade_key,
                    "date": source["date"],
                    "ticker": source["ticker"],
                    "side": "LONG",
                    "entry_time": source["entry_time"],
                    "exit_time": source["exit_time"],
                    "exit_reason": source["exit_reason"],
                    "entry_price": source["entry_price"],
                    "exit_price": source["exit_price"],
                    "stop_price": source["stop_price"],
                    "target_price": source["target_price"],
                    "net_return": source["net_return"],
                    "opening_range_pct": source["opening_range_pct"],
                    "gap": source["gap"],
                    "risk_pct": source["risk_pct"],
                    "passes_risk_filter": source["passes_risk_filter"],
                    "selected_by_baseline": selected_by_baseline,
                    "selected_by_shadow": selected_by_shadow,
                    "shadow_action": action,
                    "baseline_position_size_pct": baseline_position_size_pct,
                    "shadow_position_size_pct": shadow_position_size_pct,
                    "position_size_pct_difference": (
                        shadow_position_size_pct - baseline_position_size_pct
                    ),
                    "baseline_account_return": baseline_account_return,
                    "shadow_account_return": shadow_account_return,
                    "shadow_account_return_difference": (
                        shadow_account_return - baseline_account_return
                    ),
                    "baseline_pnl_sek": baseline_pnl_sek,
                    "shadow_pnl_sek": shadow_pnl_sek,
                    "shadow_pnl_sek_difference": shadow_pnl_sek - baseline_pnl_sek,
                }
            )

    report = pd.DataFrame(rows)

    if report.empty:
        return report

    report = report.sort_values(
        ["shadow_method", "date", "entry_time", "ticker"]
    ).reset_index(drop=True)

    report["report_row_number"] = report.groupby("shadow_method").cumcount() + 1

    return report


def build_daily_shadow_summary(shadow_report: pd.DataFrame) -> pd.DataFrame:
    if shadow_report.empty:
        return pd.DataFrame()

    rows = []

    for (method_name, trade_date), day in shadow_report.groupby(
        ["shadow_method", "date"]
    ):
        rows.append(
            {
                "shadow_method": method_name,
                "date": trade_date,
                "baseline_trades": int(day["selected_by_baseline"].sum()),
                "shadow_trades": int(day["selected_by_shadow"].sum()),
                "taken_by_both": int(day["shadow_action"].eq("TAKEN_BY_BOTH").sum()),
                "removed_by_risk_filter": int(
                    day["shadow_action"].eq("REMOVED_BY_RISK_FILTER").sum()
                ),
                "removed_by_selection_change": int(
                    day["shadow_action"].eq("REMOVED_BY_SELECTION_CHANGE").sum()
                ),
                "added_by_shadow_method": int(
                    day["shadow_action"].eq("ADDED_BY_SHADOW_METHOD").sum()
                ),
                "baseline_account_return": float(day["baseline_account_return"].sum()),
                "shadow_account_return": float(day["shadow_account_return"].sum()),
                "shadow_account_return_difference": float(
                    day["shadow_account_return_difference"].sum()
                ),
                "baseline_pnl_sek": float(day["baseline_pnl_sek"].sum()),
                "shadow_pnl_sek": float(day["shadow_pnl_sek"].sum()),
                "shadow_pnl_sek_difference": float(
                    day["shadow_pnl_sek_difference"].sum()
                ),
                "max_baseline_position_size_pct": float(
                    day["baseline_position_size_pct"].max()
                ),
                "max_shadow_position_size_pct": float(
                    day["shadow_position_size_pct"].max()
                ),
                "max_risk_pct": float(day["risk_pct"].max()),
            }
        )

    daily = pd.DataFrame(rows)

    return daily.sort_values(["shadow_method", "date"]).reset_index(drop=True)


def main() -> None:
    print("\n=== ORB POSITION SIZING SHADOW REPORT ===")
    print("Research-only. This does not modify paper trades.")
    print("Long-only: buys/entries are long, sells are exits only.")
    print("No short selling is simulated.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Breakout window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Current fixed position size: {ORB_POSITION_SIZE:.2%}")
    print(f"Shadow risk filter: risk_pct <= {RISK_FILTER_THRESHOLD:.2%}")
    print("Shadow sizing candidate: target 0.15% account risk, cap 20% notional")
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

    summary_rows = []
    trade_frames = []
    equity_frames = []

    for method_definition in SHADOW_METHODS:
        method_name = method_definition["shadow_method"]
        selection_set = method_definition["selection_set"]

        print(f"\n=== Shadow method: {method_name} ===")

        method_candidates = candidates.copy()

        if method_definition["apply_risk_filter"]:
            method_candidates = method_candidates[
                method_candidates["passes_risk_filter"]
            ].copy()

        selected = select_earliest_trades_with_capacity(
            trades=method_candidates,
            selection_set=selection_set,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        print(f"Candidates: {len(method_candidates)}")
        print(f"Selected trades: {len(selected)}")

        summary, trades_out, equity_curve = simulate_shadow_method(
            selected_trades=selected,
            method_definition=method_definition,
        )

        summary_rows.append(summary)

        if not trades_out.empty:
            trade_frames.append(trades_out)

        if not equity_curve.empty:
            equity_frames.append(equity_curve)

        print(f"Total return: {summary['total_return']:.4%}")
        print(f"Final equity: {summary['final_equity']:.2f} SEK")
        print(f"Profit factor: {summary['profit_factor']:.4f}")
        print(f"Max drawdown: {summary['max_drawdown']:.4%}")
        print(f"Avg position size: {summary['avg_position_size_pct']:.2%}")
        print(
            "Max estimated account risk: "
            f"{summary['max_estimated_account_risk_pct']:.4%}"
        )

    summary = pd.DataFrame(summary_rows)

    if summary.empty:
        print("No summary produced.")
        return

    summary = add_summary_comparison(summary)

    trades_output = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame()
    )

    equity_output = (
        pd.concat(equity_frames, ignore_index=True)
        if equity_frames
        else pd.DataFrame()
    )

    shadow_report = build_shadow_action_report(trades_output)
    daily_summary = build_daily_shadow_summary(shadow_report)

    candidates["shadow_risk_filter_threshold"] = RISK_FILTER_THRESHOLD

    export_csv_for_power_bi(summary, OUTPUT_SUMMARY_FILE)
    export_csv_for_power_bi(shadow_report, OUTPUT_REPORT_FILE)
    export_csv_for_power_bi(daily_summary, OUTPUT_DAILY_FILE)
    export_csv_for_power_bi(trades_output, OUTPUT_TRADES_FILE)
    export_csv_for_power_bi(equity_output, OUTPUT_EQUITY_FILE)
    export_csv_for_power_bi(candidates, OUTPUT_CANDIDATES_FILE)

    print("\n=== POSITION SIZING SHADOW SUMMARY ===")

    summary_columns = [
        "shadow_rank",
        "shadow_method",
        "selection_set",
        "sizing_model",
        "selected_trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "avg_position_size_pct",
        "max_position_size_pct",
        "avg_estimated_account_risk_pct",
        "max_estimated_account_risk_pct",
        "excess_return_vs_baseline",
        "excess_pnl_sek_vs_baseline",
        "drawdown_change_vs_baseline",
        "beats_baseline",
    ]

    print(summary[summary_columns].to_string(index=False))

    print("\n=== SHADOW ACTION SUMMARY ===")

    if shadow_report.empty:
        print("No shadow action report produced.")
    else:
        action_summary = (
            shadow_report.groupby(["shadow_method", "shadow_action"])
            .agg(
                trades=("trade_key", "count"),
                baseline_pnl_sek=("baseline_pnl_sek", "sum"),
                shadow_pnl_sek=("shadow_pnl_sek", "sum"),
                shadow_pnl_sek_difference=("shadow_pnl_sek_difference", "sum"),
                shadow_account_return_difference=(
                    "shadow_account_return_difference",
                    "sum",
                ),
            )
            .reset_index()
            .sort_values(
                ["shadow_method", "shadow_pnl_sek_difference"],
                ascending=[True, False],
            )
        )

        print(action_summary.to_string(index=False))

    print("\n=== TRADES REMOVED BY SHADOW METHODS ===")

    if shadow_report.empty:
        print("No removed trades.")
    else:
        removed = shadow_report[
            shadow_report["shadow_action"].isin(
                ["REMOVED_BY_RISK_FILTER", "REMOVED_BY_SELECTION_CHANGE"]
            )
        ].copy()

        removed_columns = [
            "shadow_method",
            "date",
            "ticker",
            "entry_time",
            "exit_time",
            "exit_reason",
            "net_return",
            "opening_range_pct",
            "gap",
            "risk_pct",
            "baseline_pnl_sek",
            "shadow_pnl_sek",
            "shadow_pnl_sek_difference",
        ]

        if removed.empty:
            print("No baseline trades were removed by shadow methods.")
        else:
            print(removed[removed_columns].to_string(index=False))

    print("\n=== DAILY SHADOW DIFFERENCES ===")

    if daily_summary.empty:
        print("No daily shadow summary produced.")
    else:
        changed_days = daily_summary[
            daily_summary["shadow_pnl_sek_difference"].abs() > 0
        ].copy()

        daily_columns = [
            "shadow_method",
            "date",
            "baseline_trades",
            "shadow_trades",
            "removed_by_risk_filter",
            "added_by_shadow_method",
            "baseline_pnl_sek",
            "shadow_pnl_sek",
            "shadow_pnl_sek_difference",
            "shadow_account_return_difference",
        ]

        if changed_days.empty:
            print("No daily differences versus baseline.")
        else:
            print(changed_days[daily_columns].to_string(index=False))

    print(f"\nSaved summary       -> {OUTPUT_SUMMARY_FILE}")
    print(f"Saved report        -> {OUTPUT_REPORT_FILE}")
    print(f"Saved daily summary -> {OUTPUT_DAILY_FILE}")
    print(f"Saved trades        -> {OUTPUT_TRADES_FILE}")
    print(f"Saved equity        -> {OUTPUT_EQUITY_FILE}")
    print(f"Saved candidates    -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()