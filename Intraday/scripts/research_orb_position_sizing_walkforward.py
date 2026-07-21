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
    filter_to_completed_research_sessions,
    load_normalised_intraday_prices,
)
from Intraday.core.paths import DATA_DIR


OUTPUT_DIAGNOSTICS_FILE = DATA_DIR / "orb_position_sizing_walkforward_diagnostics.csv"
OUTPUT_METHOD_SUMMARY_FILE = DATA_DIR / "orb_position_sizing_walkforward_method_summary.csv"
OUTPUT_TRADES_FILE = DATA_DIR / "orb_position_sizing_walkforward_trades.csv"
OUTPUT_EQUITY_FILE = DATA_DIR / "orb_position_sizing_walkforward_equity_curve.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "orb_position_sizing_walkforward_candidates.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

PERIOD_SIZE_DATES = 15

RISK_FILTER_THRESHOLD = 0.0200

BASELINE_SELECTION_SET = "baseline_current_rules"
RISK_FILTER_SELECTION_SET = "shadow_risk_le_2_00pct"

BASELINE_SIZING_MODEL = "fixed_10pct"

POSITION_SIZING_MODELS = [
    {
        "sizing_model": "fixed_10pct",
        "model_type": "fixed",
        "description": "Fixed 10% notional position size. Current baseline.",
        "fixed_position_pct": ORB_POSITION_SIZE,
        "target_account_risk_pct": 0.0,
        "max_position_pct": ORB_POSITION_SIZE,
    },
    {
        "sizing_model": "fixed_15pct",
        "model_type": "fixed",
        "description": "Fixed 15% notional position size.",
        "fixed_position_pct": 0.15,
        "target_account_risk_pct": 0.0,
        "max_position_pct": 0.15,
    },
    {
        "sizing_model": "risk_target_0_10pct_cap_20pct",
        "model_type": "risk_adjusted",
        "description": "Target 0.10% account risk per trade, capped at 20% notional.",
        "fixed_position_pct": 0.0,
        "target_account_risk_pct": 0.0010,
        "max_position_pct": 0.20,
    },
    {
        "sizing_model": "risk_target_0_15pct_cap_20pct",
        "model_type": "risk_adjusted",
        "description": "Target 0.15% account risk per trade, capped at 20% notional.",
        "fixed_position_pct": 0.0,
        "target_account_risk_pct": 0.0015,
        "max_position_pct": 0.20,
    },
    {
        "sizing_model": "risk_target_0_20pct_cap_20pct",
        "model_type": "risk_adjusted",
        "description": "Target 0.20% account risk per trade, capped at 20% notional.",
        "fixed_position_pct": 0.0,
        "target_account_risk_pct": 0.0020,
        "max_position_pct": 0.20,
    },
]

# Research-only guardrails.
MIN_SELECTED_TRADES_PER_PERIOD = 8
MIN_AVG_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE = 0.0002
MIN_PERIODS_NOT_WORSE_THAN_FIXED_10PCT = 2
MAX_AVG_DRAWDOWN_WORSENING_ALLOWED = 0.0010


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
    selection_set: str,
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


def simulate_position_sizing(
    selected_trades: pd.DataFrame,
    sizing_model: dict,
    period_type: str,
    period_number: int,
    period_label: str,
    period_start: str,
    period_end: str,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    selection_set = (
        selected_trades["selection_set"].iloc[0]
        if not selected_trades.empty and "selection_set" in selected_trades.columns
        else ""
    )

    sizing_model_name = sizing_model["sizing_model"]

    empty_summary = {
        "period_type": period_type,
        "period_number": period_number,
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "selection_set": selection_set,
        "sizing_model": sizing_model_name,
        "model_type": sizing_model["model_type"],
        "description": sizing_model["description"],
        "target_account_risk_pct": sizing_model["target_account_risk_pct"],
        "max_position_pct_config": sizing_model["max_position_pct"],
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
            "period_type": period_type,
            "period_number": period_number,
            "period_label": period_label,
            "period_start": period_start,
            "period_end": period_end,
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
                "period_type": period_type,
                "period_number": period_number,
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
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
                "period_type": period_type,
                "period_number": period_number,
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
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

    exit_counts = calculate_exit_counts(trades_out)

    total_pnl_sek = float(trades_out["pnl_sek"].sum())
    total_return = total_pnl_sek / ORB_INITIAL_CAPITAL

    summary = {
        "period_type": period_type,
        "period_number": period_number,
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "selection_set": selection_set,
        "sizing_model": sizing_model_name,
        "model_type": sizing_model["model_type"],
        "description": sizing_model["description"],
        "target_account_risk_pct": sizing_model["target_account_risk_pct"],
        "max_position_pct_config": sizing_model["max_position_pct"],
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


def run_position_sizing_for_selection_set(
    selected_trades: pd.DataFrame,
    period_type: str,
    period_number: int,
    period_label: str,
    period_start: str,
    period_end: str,
) -> tuple[list[dict], list[pd.DataFrame], list[pd.DataFrame]]:
    summary_rows = []
    trade_frames = []
    equity_frames = []

    for sizing_model in POSITION_SIZING_MODELS:
        summary, trades_out, equity_curve = simulate_position_sizing(
            selected_trades=selected_trades,
            sizing_model=sizing_model,
            period_type=period_type,
            period_number=period_number,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
        )

        summary_rows.append(summary)

        if not trades_out.empty:
            trade_frames.append(trades_out)

        if not equity_curve.empty:
            equity_frames.append(equity_curve)

    return summary_rows, trade_frames, equity_frames


def add_fixed_10pct_comparison(diagnostics: pd.DataFrame) -> pd.DataFrame:
    diagnostics = diagnostics.copy()

    baseline = diagnostics[diagnostics["sizing_model"].eq(BASELINE_SIZING_MODEL)][
        [
            "period_type",
            "period_label",
            "selection_set",
            "total_return",
            "final_equity",
            "total_pnl_sek",
            "profit_factor",
            "max_drawdown",
        ]
    ].rename(
        columns={
            "total_return": "fixed_10pct_total_return",
            "final_equity": "fixed_10pct_final_equity",
            "total_pnl_sek": "fixed_10pct_total_pnl_sek",
            "profit_factor": "fixed_10pct_profit_factor",
            "max_drawdown": "fixed_10pct_max_drawdown",
        }
    )

    diagnostics = diagnostics.merge(
        baseline,
        on=["period_type", "period_label", "selection_set"],
        how="left",
    )

    diagnostics["excess_return_vs_fixed_10pct"] = (
        diagnostics["total_return"] - diagnostics["fixed_10pct_total_return"]
    )

    diagnostics["excess_equity_vs_fixed_10pct"] = (
        diagnostics["final_equity"] - diagnostics["fixed_10pct_final_equity"]
    )

    diagnostics["profit_factor_change_vs_fixed_10pct"] = (
        diagnostics["profit_factor"] - diagnostics["fixed_10pct_profit_factor"]
    )

    # More negative drawdown is worse.
    diagnostics["drawdown_change_vs_fixed_10pct"] = (
        diagnostics["max_drawdown"] - diagnostics["fixed_10pct_max_drawdown"]
    )

    diagnostics["beats_fixed_10pct"] = diagnostics["excess_return_vs_fixed_10pct"] > 0

    diagnostics["not_worse_than_fixed_10pct"] = (
        diagnostics["excess_return_vs_fixed_10pct"] >= 0
    )

    diagnostics["period_best_return"] = diagnostics.groupby(
        ["period_type", "period_label", "selection_set"]
    )["total_return"].transform("max")

    diagnostics["is_period_winner"] = (
        diagnostics["total_return"] == diagnostics["period_best_return"]
    )

    diagnostics = diagnostics.sort_values(
        [
            "period_type",
            "period_number",
            "selection_set",
            "total_return",
            "profit_factor",
        ],
        ascending=[
            True,
            True,
            True,
            False,
            False,
        ],
    ).reset_index(drop=True)

    return diagnostics


def build_method_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
    period_rows = diagnostics[diagnostics["period_type"].eq("PERIOD")].copy()

    if period_rows.empty:
        return pd.DataFrame()

    grouped = period_rows.groupby(
        [
            "selection_set",
            "sizing_model",
            "model_type",
        ]
    )

    summary = grouped.agg(
        periods_tested=("period_label", "nunique"),
        avg_total_return=("total_return", "mean"),
        median_total_return=("total_return", "median"),
        min_total_return=("total_return", "min"),
        max_total_return=("total_return", "max"),
        avg_excess_return_vs_fixed_10pct=("excess_return_vs_fixed_10pct", "mean"),
        median_excess_return_vs_fixed_10pct=("excess_return_vs_fixed_10pct", "median"),
        periods_beating_fixed_10pct=("beats_fixed_10pct", "sum"),
        periods_not_worse_than_fixed_10pct=("not_worse_than_fixed_10pct", "sum"),
        periods_won=("is_period_winner", "sum"),
        avg_selected_trades=("selected_trades", "mean"),
        min_selected_trades=("selected_trades", "min"),
        avg_profit_factor=("profit_factor", "mean"),
        avg_profit_factor_change_vs_fixed_10pct=(
            "profit_factor_change_vs_fixed_10pct",
            "mean",
        ),
        worst_drawdown=("max_drawdown", "min"),
        avg_drawdown_change_vs_fixed_10pct=("drawdown_change_vs_fixed_10pct", "mean"),
        avg_position_size_pct=("avg_position_size_pct", "mean"),
        max_position_size_pct=("max_position_size_pct", "max"),
        avg_estimated_account_risk_pct=("avg_estimated_account_risk_pct", "mean"),
        max_estimated_account_risk_pct=("max_estimated_account_risk_pct", "max"),
        avg_capped_trade_count=("capped_trade_count", "mean"),
    ).reset_index()

    summary["enough_trades_for_research_candidate"] = (
        summary["min_selected_trades"] >= MIN_SELECTED_TRADES_PER_PERIOD
    )

    summary["material_avg_excess_return"] = (
        summary["avg_excess_return_vs_fixed_10pct"]
        >= MIN_AVG_EXCESS_RETURN_FOR_RESEARCH_CANDIDATE
    )

    summary["stable_enough_vs_fixed_10pct"] = (
        summary["periods_not_worse_than_fixed_10pct"]
        >= MIN_PERIODS_NOT_WORSE_THAN_FIXED_10PCT
    )

    summary["avg_drawdown_not_much_worse"] = (
        summary["avg_drawdown_change_vs_fixed_10pct"]
        >= -MAX_AVG_DRAWDOWN_WORSENING_ALLOWED
    )

    summary["research_candidate"] = (
        summary["model_type"].eq("risk_adjusted")
        & summary["enough_trades_for_research_candidate"]
        & summary["material_avg_excess_return"]
        & summary["stable_enough_vs_fixed_10pct"]
        & summary["avg_drawdown_not_much_worse"]
        & (~summary["sizing_model"].eq(BASELINE_SIZING_MODEL))
    )

    summary = summary.sort_values(
        [
            "selection_set",
            "research_candidate",
            "avg_excess_return_vs_fixed_10pct",
            "avg_total_return",
            "avg_profit_factor",
        ],
        ascending=[
            True,
            False,
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    summary["method_rank"] = summary.groupby("selection_set").cumcount() + 1

    return summary


def main() -> None:
    print("\n=== ORB POSITION SIZING WALK-FORWARD ===")
    print("Research-only. This does not modify paper trades.")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Breakout window: {ORB_BREAKOUT_START} to {ORB_BREAKOUT_END}")
    print(f"R multiple: {ORB_R_MULTIPLE}")
    print(f"Max opening range: {ORB_MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {ORB_MIN_GAP:.2%}")
    print(f"Cost per trade: {ORB_COST_PER_TRADE:.4%}")
    print(f"Max open positions: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Current fixed position size: {ORB_POSITION_SIZE:.2%}")
    print(f"Walk-forward period size: {PERIOD_SIZE_DATES} unique trade dates")
    print(f"Shadow risk filter: risk_pct <= {RISK_FILTER_THRESHOLD:.2%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

    prices = filter_to_completed_research_sessions(
        prices,
        verbose=True,
    )

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

    candidates = assign_walkforward_periods(
        candidates=candidates,
        period_size_dates=PERIOD_SIZE_DATES,
    )

    all_summary_rows = []
    all_trade_frames = []
    all_equity_frames = []

    all_period_start = candidates["date"].min()
    all_period_end = candidates["date"].max()

    period_definitions = [
        {
            "period_type": "ALL",
            "period_number": 0,
            "period_label": "ALL",
            "period_start": all_period_start,
            "period_end": all_period_end,
            "period_candidates": candidates,
        }
    ]

    for period_number, period_candidates in candidates.groupby("period_number"):
        period_candidates = period_candidates.copy()

        period_definitions.append(
            {
                "period_type": "PERIOD",
                "period_number": int(period_number),
                "period_label": f"P{int(period_number):02d}",
                "period_start": period_candidates["date"].min(),
                "period_end": period_candidates["date"].max(),
                "period_candidates": period_candidates,
            }
        )

    for period_definition in period_definitions:
        period_type = period_definition["period_type"]
        period_number = period_definition["period_number"]
        period_label = period_definition["period_label"]
        period_start = period_definition["period_start"]
        period_end = period_definition["period_end"]
        period_candidates = period_definition["period_candidates"].copy()

        baseline_selected = select_earliest_trades_with_capacity(
            trades=period_candidates,
            selection_set=BASELINE_SELECTION_SET,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        risk_filter_candidates = period_candidates[
            period_candidates["passes_risk_filter"]
        ].copy()

        risk_filter_selected = select_earliest_trades_with_capacity(
            trades=risk_filter_candidates,
            selection_set=RISK_FILTER_SELECTION_SET,
            max_positions=ORB_MAX_OPEN_POSITIONS,
        )

        selection_sets = [
            {
                "selection_set": BASELINE_SELECTION_SET,
                "selected_trades": baseline_selected,
            },
            {
                "selection_set": RISK_FILTER_SELECTION_SET,
                "selected_trades": risk_filter_selected,
            },
        ]

        print(
            f"\n=== Period {period_label} "
            f"({period_start} to {period_end}) ==="
        )

        for selection_set_definition in selection_sets:
            selection_set = selection_set_definition["selection_set"]
            selected_trades = selection_set_definition["selected_trades"]

            print(f"Selection set: {selection_set}")
            print(f"Selected trades: {len(selected_trades)}")

            summary_rows, trade_frames, equity_frames = (
                run_position_sizing_for_selection_set(
                    selected_trades=selected_trades,
                    period_type=period_type,
                    period_number=period_number,
                    period_label=period_label,
                    period_start=period_start,
                    period_end=period_end,
                )
            )

            all_summary_rows.extend(summary_rows)
            all_trade_frames.extend(trade_frames)
            all_equity_frames.extend(equity_frames)

    diagnostics = pd.DataFrame(all_summary_rows)

    if diagnostics.empty:
        print("No diagnostics produced.")
        return

    diagnostics = add_fixed_10pct_comparison(diagnostics)
    method_summary = build_method_summary(diagnostics)

    trades_output = (
        pd.concat(all_trade_frames, ignore_index=True)
        if all_trade_frames
        else pd.DataFrame()
    )

    equity_output = (
        pd.concat(all_equity_frames, ignore_index=True)
        if all_equity_frames
        else pd.DataFrame()
    )

    export_csv_for_power_bi(diagnostics, OUTPUT_DIAGNOSTICS_FILE)
    export_csv_for_power_bi(method_summary, OUTPUT_METHOD_SUMMARY_FILE)
    export_csv_for_power_bi(trades_output, OUTPUT_TRADES_FILE)
    export_csv_for_power_bi(equity_output, OUTPUT_EQUITY_FILE)
    export_csv_for_power_bi(candidates, OUTPUT_CANDIDATES_FILE)

    print("\n=== POSITION SIZING METHOD SUMMARY ===")

    method_columns = [
        "selection_set",
        "method_rank",
        "sizing_model",
        "model_type",
        "periods_tested",
        "avg_total_return",
        "avg_excess_return_vs_fixed_10pct",
        "periods_beating_fixed_10pct",
        "periods_not_worse_than_fixed_10pct",
        "periods_won",
        "avg_selected_trades",
        "min_selected_trades",
        "avg_profit_factor",
        "worst_drawdown",
        "avg_drawdown_change_vs_fixed_10pct",
        "avg_position_size_pct",
        "max_position_size_pct",
        "avg_estimated_account_risk_pct",
        "max_estimated_account_risk_pct",
        "research_candidate",
    ]

    print(method_summary[method_columns].to_string(index=False))

    print("\n=== WALK-FORWARD PERIOD RESULTS ===")

    period_rows = diagnostics[diagnostics["period_type"].eq("PERIOD")].copy()

    period_columns = [
        "period_label",
        "period_start",
        "period_end",
        "selection_set",
        "sizing_model",
        "selected_trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "avg_position_size_pct",
        "max_estimated_account_risk_pct",
        "excess_return_vs_fixed_10pct",
        "beats_fixed_10pct",
        "is_period_winner",
    ]

    print(
        period_rows.sort_values(
            [
                "period_number",
                "selection_set",
                "total_return",
                "profit_factor",
            ],
            ascending=[
                True,
                True,
                False,
                False,
            ],
        )[period_columns].to_string(index=False)
    )

    print("\n=== WHOLE-SAMPLE RESULTS ===")

    all_rows = diagnostics[diagnostics["period_type"].eq("ALL")].copy()

    all_columns = [
        "selection_set",
        "sizing_model",
        "selected_trades",
        "total_return",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "avg_position_size_pct",
        "max_estimated_account_risk_pct",
        "excess_return_vs_fixed_10pct",
        "beats_fixed_10pct",
        "is_period_winner",
    ]

    print(
        all_rows.sort_values(
            [
                "selection_set",
                "total_return",
                "profit_factor",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        )[all_columns].to_string(index=False)
    )

    print("\n=== RESEARCH CANDIDATES ===")

    research_candidates = method_summary[method_summary["research_candidate"]].copy()

    if research_candidates.empty:
        print("No position-sizing model passed the walk-forward guardrails.")
    else:
        print(research_candidates[method_columns].to_string(index=False))

    print(f"\nSaved diagnostics    -> {OUTPUT_DIAGNOSTICS_FILE}")
    print(f"Saved method summary -> {OUTPUT_METHOD_SUMMARY_FILE}")
    print(f"Saved trades         -> {OUTPUT_TRADES_FILE}")
    print(f"Saved equity         -> {OUTPUT_EQUITY_FILE}")
    print(f"Saved candidates     -> {OUTPUT_CANDIDATES_FILE}")


if __name__ == "__main__":
    main()