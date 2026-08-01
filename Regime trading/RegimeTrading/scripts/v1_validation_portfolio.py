from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, LEGACY_OUTPUT_DIRS
from RegimeTrading.core.research_config import (
    ORB_INITIAL_CAPITAL,
    ORB_POSITION_SIZE,
)
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    RESEARCH_STATUS,
    STRATEGY_ID,
)


VALIDATION_SUITE_VERSION = "V1_RESEARCH_VALIDATION_SUITE_STEP1"
PORTFOLIO_MODEL_ID = "MAX_2_FIXED_INITIAL_CAPITAL_V1"
MAX_OPEN_POSITIONS = 2
POSITION_SIZE_SEK = float(ORB_INITIAL_CAPITAL) * float(ORB_POSITION_SIZE)
ENTRY_PRIORITY_RULE = "ENTRY_TIME_THEN_TICKER_ASC"
SAME_TIMESTAMP_POLICY = "ENTRIES_BEFORE_EXITS"
PNL_SOURCE = "V1_NET_PNL_PCT_ALREADY_INCLUDES_COST"

SOURCE_TRADES_FILE = DATA_DIR / "regime_gap_recovery_trades.csv"
OUTPUT_DIR = LEGACY_OUTPUT_DIRS["v1_validation"]
SUMMARY_FILE = OUTPUT_DIR / "v1_validation_portfolio_summary.csv"
LEDGER_FILE = OUTPUT_DIR / "v1_validation_portfolio_trade_ledger.csv"
EQUITY_FILE = OUTPUT_DIR / "v1_validation_portfolio_equity_curve.csv"
DAILY_FILE = OUTPUT_DIR / "v1_validation_portfolio_daily.csv"

SUMMARY_COLUMNS = [
    "validation_suite_version",
    "portfolio_model_id",
    "strategy_id",
    "research_status",
    "initial_capital_sek",
    "position_size_pct",
    "position_size_sek",
    "max_open_positions",
    "entry_priority_rule",
    "same_timestamp_policy",
    "pnl_source",
    "input_trade_rows",
    "input_closed_trades",
    "input_open_trades",
    "selected_trade_rows",
    "selected_closed_trades",
    "selected_open_trades",
    "rejected_capacity_trades",
    "excluded_invalid_trades",
    "selection_rate",
    "max_open_positions_observed",
    "same_timestamp_ambiguous_groups",
    "days_with_capacity_rejections",
    "win_rate",
    "gross_profit_sek",
    "gross_loss_sek",
    "profit_factor",
    "total_realized_pnl_sek",
    "final_realized_equity_sek",
    "total_realized_return",
    "max_drawdown",
    "avg_r_multiple",
    "all_trades_counterfactual_pnl_sek",
    "rejected_counterfactual_pnl_sek",
    "capacity_pnl_difference_sek",
    "first_entry_time",
    "last_event_time",
]

LEDGER_COLUMNS = [
    "validation_suite_version",
    "portfolio_model_id",
    "strategy_id",
    "research_status",
    "source_trade_row",
    "date",
    "ticker",
    "entry_time",
    "exit_time",
    "exit_reason",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_price",
    "source_net_pnl_pct",
    "source_position_size_sek",
    "model_position_size_sek",
    "selected_for_portfolio",
    "selection_status",
    "rejection_reason",
    "entry_priority",
    "same_timestamp_entry_count",
    "available_slots_before_group",
    "active_positions_before_entry",
    "capacity_ambiguous",
    "portfolio_pnl_sek",
    "portfolio_return_contribution",
    "equity_before_exit_sek",
    "equity_after_exit_sek",
    "r_multiple_achieved",
    "gap",
    "gap_pct",
    "opening_range_pct",
    "risk_pct",
    "reward_risk",
    "early_market_regime",
    "research_universe",
]

EQUITY_COLUMNS = [
    "validation_suite_version",
    "portfolio_model_id",
    "event_number",
    "event_time",
    "event_type",
    "date",
    "ticker",
    "exit_reason",
    "pnl_sek",
    "realized_equity_sek",
    "cumulative_pnl_sek",
    "cumulative_return",
    "running_peak_equity_sek",
    "drawdown",
    "open_positions_after_event",
]

DAILY_COLUMNS = [
    "validation_suite_version",
    "portfolio_model_id",
    "date",
    "input_trade_rows",
    "selected_entries",
    "selected_closed_trades",
    "selected_open_trades",
    "rejected_capacity_trades",
    "capacity_ambiguous_trades",
    "wins",
    "losses",
    "daily_realized_pnl_sek",
    "daily_realized_return_on_initial_capital",
    "cumulative_realized_pnl_sek",
    "end_realized_equity_sek",
    "end_cumulative_return",
    "max_open_positions_observed",
]


@dataclass
class SimulationResult:
    summary: pd.DataFrame
    ledger: pd.DataFrame
    equity: pd.DataFrame
    daily: pd.DataFrame


def _parse_timestamp(values: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(values, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(values, errors="coerce")


def _safe_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")


def _profit_factor(pnl: pd.Series) -> float:
    clean = pd.to_numeric(pnl, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    gross_profit = float(clean[clean > 0].sum())
    gross_loss = abs(float(clean[clean < 0].sum()))
    if gross_loss == 0:
        return np.nan
    return gross_profit / gross_loss


def _empty_result() -> SimulationResult:
    summary = pd.DataFrame(
        [
            {
                "validation_suite_version": VALIDATION_SUITE_VERSION,
                "portfolio_model_id": PORTFOLIO_MODEL_ID,
                "strategy_id": STRATEGY_ID,
                "research_status": RESEARCH_STATUS,
                "initial_capital_sek": float(ORB_INITIAL_CAPITAL),
                "position_size_pct": float(ORB_POSITION_SIZE),
                "position_size_sek": POSITION_SIZE_SEK,
                "max_open_positions": MAX_OPEN_POSITIONS,
                "entry_priority_rule": ENTRY_PRIORITY_RULE,
                "same_timestamp_policy": SAME_TIMESTAMP_POLICY,
                "pnl_source": PNL_SOURCE,
                "input_trade_rows": 0,
                "input_closed_trades": 0,
                "input_open_trades": 0,
                "selected_trade_rows": 0,
                "selected_closed_trades": 0,
                "selected_open_trades": 0,
                "rejected_capacity_trades": 0,
                "excluded_invalid_trades": 0,
                "selection_rate": np.nan,
                "max_open_positions_observed": 0,
                "same_timestamp_ambiguous_groups": 0,
                "days_with_capacity_rejections": 0,
                "win_rate": np.nan,
                "gross_profit_sek": 0.0,
                "gross_loss_sek": 0.0,
                "profit_factor": np.nan,
                "total_realized_pnl_sek": 0.0,
                "final_realized_equity_sek": float(ORB_INITIAL_CAPITAL),
                "total_realized_return": 0.0,
                "max_drawdown": 0.0,
                "avg_r_multiple": np.nan,
                "all_trades_counterfactual_pnl_sek": 0.0,
                "rejected_counterfactual_pnl_sek": 0.0,
                "capacity_pnl_difference_sek": 0.0,
                "first_entry_time": "",
                "last_event_time": "",
            }
        ],
        columns=SUMMARY_COLUMNS,
    )
    return SimulationResult(
        summary=summary,
        ledger=pd.DataFrame(columns=LEDGER_COLUMNS),
        equity=pd.DataFrame(columns=EQUITY_COLUMNS),
        daily=pd.DataFrame(columns=DAILY_COLUMNS),
    )


def load_source_trades(path: Path = SOURCE_TRADES_FILE) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame()

    trades = pd.read_csv(path)
    if trades.empty:
        return trades

    trades = trades.copy().reset_index(drop=True)
    trades["source_trade_row"] = trades.index.astype(int)
    trades["entry_time_dt"] = _parse_timestamp(trades.get("entry_time", pd.Series(dtype=str)))
    trades["exit_time_dt"] = _parse_timestamp(trades.get("exit_time", pd.Series(dtype=str)))

    _safe_numeric(
        trades,
        [
            "entry_price",
            "stop_price",
            "target_price",
            "exit_price",
            "pnl_pct",
            "position_size_sek",
            "r_multiple_achieved",
            "gap",
            "gap_pct",
            "opening_range_pct",
            "risk_pct",
            "reward_risk",
        ],
    )

    for column in [
        "ticker",
        "exit_reason",
        "early_market_regime",
        "research_universe",
        "date",
    ]:
        if column not in trades.columns:
            trades[column] = ""
        trades[column] = trades[column].fillna("").astype(str)

    trades["is_closed"] = trades["exit_reason"].str.strip().ne("")
    trades["is_valid_entry"] = trades["entry_time_dt"].notna()
    trades["is_valid_closed_exit"] = (~trades["is_closed"]) | trades["exit_time_dt"].notna()
    trades["valid_for_simulation"] = trades["is_valid_entry"] & trades["is_valid_closed_exit"]

    return trades


def simulate_portfolio(trades: pd.DataFrame) -> SimulationResult:
    if trades is None or trades.empty:
        return _empty_result()

    work = trades.copy().reset_index(drop=True)
    if "source_trade_row" not in work.columns:
        work["source_trade_row"] = work.index.astype(int)
    if "entry_time_dt" not in work.columns:
        work["entry_time_dt"] = _parse_timestamp(work["entry_time"])
    if "exit_time_dt" not in work.columns:
        work["exit_time_dt"] = _parse_timestamp(work["exit_time"])
    if "is_closed" not in work.columns:
        work["is_closed"] = work["exit_reason"].fillna("").astype(str).str.strip().ne("")
    if "valid_for_simulation" not in work.columns:
        work["valid_for_simulation"] = work["entry_time_dt"].notna() & (
            (~work["is_closed"]) | work["exit_time_dt"].notna()
        )

    _safe_numeric(
        work,
        [
            "pnl_pct",
            "position_size_sek",
            "r_multiple_achieved",
            "entry_price",
            "stop_price",
            "target_price",
            "exit_price",
            "gap",
            "gap_pct",
            "opening_range_pct",
            "risk_pct",
            "reward_risk",
        ],
    )

    state: dict[int, dict] = {}
    for _, row in work.iterrows():
        trade_id = int(row["source_trade_row"])
        state[trade_id] = {
            "selected": False,
            "selection_status": "EXCLUDED_INVALID",
            "rejection_reason": "INVALID_ENTRY_OR_EXIT_TIMESTAMP",
            "entry_priority": np.nan,
            "same_timestamp_entry_count": 0,
            "available_slots_before_group": np.nan,
            "active_positions_before_entry": np.nan,
            "capacity_ambiguous": False,
            "portfolio_pnl_sek": 0.0,
            "equity_before_exit_sek": np.nan,
            "equity_after_exit_sek": np.nan,
        }

    valid = work[work["valid_for_simulation"]].copy()
    valid = valid.sort_values(["entry_time_dt", "ticker", "source_trade_row"]).reset_index(drop=True)

    entry_groups = {
        pd.Timestamp(timestamp): group.copy()
        for timestamp, group in valid.groupby("entry_time_dt", sort=True)
    }
    closed_valid = valid[valid["is_closed"]].copy()
    exit_groups = {
        pd.Timestamp(timestamp): group.copy()
        for timestamp, group in closed_valid.groupby("exit_time_dt", sort=True)
    }
    event_times = sorted(set(entry_groups) | set(exit_groups))

    active: set[int] = set()
    max_active = 0
    ambiguous_group_count = 0
    realized_equity = float(ORB_INITIAL_CAPITAL)
    equity_rows: list[dict] = [
        {
            "validation_suite_version": VALIDATION_SUITE_VERSION,
            "portfolio_model_id": PORTFOLIO_MODEL_ID,
            "event_number": 0,
            "event_time": "",
            "event_type": "START",
            "date": "",
            "ticker": "START",
            "exit_reason": "",
            "pnl_sek": 0.0,
            "realized_equity_sek": realized_equity,
            "cumulative_pnl_sek": 0.0,
            "cumulative_return": 0.0,
            "running_peak_equity_sek": realized_equity,
            "drawdown": 0.0,
            "open_positions_after_event": 0,
        }
    ]
    event_number = 0

    for event_time in event_times:
        entries = entry_groups.get(event_time, pd.DataFrame()).copy()
        if not entries.empty:
            entries = entries.sort_values(["ticker", "source_trade_row"]).reset_index(drop=True)
            available_before = max(MAX_OPEN_POSITIONS - len(active), 0)
            group_size = len(entries)
            group_ambiguous = available_before > 0 and group_size > available_before
            if group_ambiguous:
                ambiguous_group_count += 1

            for priority, (_, row) in enumerate(entries.iterrows(), start=1):
                trade_id = int(row["source_trade_row"])
                state[trade_id]["entry_priority"] = priority
                state[trade_id]["same_timestamp_entry_count"] = group_size
                state[trade_id]["available_slots_before_group"] = available_before
                state[trade_id]["active_positions_before_entry"] = len(active)
                state[trade_id]["capacity_ambiguous"] = group_ambiguous

                if len(active) < MAX_OPEN_POSITIONS:
                    state[trade_id]["selected"] = True
                    state[trade_id]["selection_status"] = (
                        "SELECTED_CLOSED" if bool(row["is_closed"]) else "SELECTED_OPEN"
                    )
                    state[trade_id]["rejection_reason"] = ""
                    active.add(trade_id)
                else:
                    state[trade_id]["selection_status"] = "REJECTED_CAPACITY"
                    state[trade_id]["rejection_reason"] = "MAX_OPEN_POSITIONS_REACHED"

            max_active = max(max_active, len(active))

        exits = exit_groups.get(event_time, pd.DataFrame()).copy()
        if not exits.empty:
            exits = exits.sort_values(["ticker", "source_trade_row"]).reset_index(drop=True)
            for _, row in exits.iterrows():
                trade_id = int(row["source_trade_row"])
                if not state[trade_id]["selected"]:
                    continue

                pnl_pct = float(row["pnl_pct"]) if pd.notna(row.get("pnl_pct")) else 0.0
                pnl_sek = POSITION_SIZE_SEK * pnl_pct
                equity_before = realized_equity
                realized_equity += pnl_sek

                state[trade_id]["portfolio_pnl_sek"] = pnl_sek
                state[trade_id]["equity_before_exit_sek"] = equity_before
                state[trade_id]["equity_after_exit_sek"] = realized_equity
                active.discard(trade_id)

                event_number += 1
                equity_rows.append(
                    {
                        "validation_suite_version": VALIDATION_SUITE_VERSION,
                        "portfolio_model_id": PORTFOLIO_MODEL_ID,
                        "event_number": event_number,
                        "event_time": event_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "event_type": "REALIZED_EXIT",
                        "date": event_time.date().isoformat(),
                        "ticker": str(row.get("ticker", "")),
                        "exit_reason": str(row.get("exit_reason", "")),
                        "pnl_sek": pnl_sek,
                        "realized_equity_sek": realized_equity,
                        "cumulative_pnl_sek": realized_equity - float(ORB_INITIAL_CAPITAL),
                        "cumulative_return": realized_equity / float(ORB_INITIAL_CAPITAL) - 1.0,
                        "running_peak_equity_sek": np.nan,
                        "drawdown": np.nan,
                        "open_positions_after_event": len(active),
                    }
                )

    ledger_rows: list[dict] = []
    work_lookup = work.set_index("source_trade_row", drop=False)
    for trade_id in sorted(state):
        row = work_lookup.loc[trade_id]
        row_state = state[trade_id]
        source_position_size = row.get("position_size_sek", np.nan)
        source_pnl_pct = row.get("pnl_pct", np.nan)

        ledger_rows.append(
            {
                "validation_suite_version": VALIDATION_SUITE_VERSION,
                "portfolio_model_id": PORTFOLIO_MODEL_ID,
                "strategy_id": str(row.get("strategy_id", STRATEGY_ID)),
                "research_status": str(row.get("research_status", RESEARCH_STATUS)),
                "source_trade_row": trade_id,
                "date": str(row.get("date", "")),
                "ticker": str(row.get("ticker", "")),
                "entry_time": (
                    row["entry_time_dt"].strftime("%Y-%m-%d %H:%M:%S")
                    if pd.notna(row["entry_time_dt"])
                    else ""
                ),
                "exit_time": (
                    row["exit_time_dt"].strftime("%Y-%m-%d %H:%M:%S")
                    if pd.notna(row["exit_time_dt"])
                    else ""
                ),
                "exit_reason": str(row.get("exit_reason", "")),
                "entry_price": row.get("entry_price", np.nan),
                "stop_price": row.get("stop_price", np.nan),
                "target_price": row.get("target_price", np.nan),
                "exit_price": row.get("exit_price", np.nan),
                "source_net_pnl_pct": source_pnl_pct,
                "source_position_size_sek": source_position_size,
                "model_position_size_sek": POSITION_SIZE_SEK,
                "selected_for_portfolio": bool(row_state["selected"]),
                "selection_status": row_state["selection_status"],
                "rejection_reason": row_state["rejection_reason"],
                "entry_priority": row_state["entry_priority"],
                "same_timestamp_entry_count": row_state["same_timestamp_entry_count"],
                "available_slots_before_group": row_state["available_slots_before_group"],
                "active_positions_before_entry": row_state["active_positions_before_entry"],
                "capacity_ambiguous": bool(row_state["capacity_ambiguous"]),
                "portfolio_pnl_sek": row_state["portfolio_pnl_sek"],
                "portfolio_return_contribution": (
                    row_state["portfolio_pnl_sek"] / float(ORB_INITIAL_CAPITAL)
                ),
                "equity_before_exit_sek": row_state["equity_before_exit_sek"],
                "equity_after_exit_sek": row_state["equity_after_exit_sek"],
                "r_multiple_achieved": row.get("r_multiple_achieved", np.nan),
                "gap": row.get("gap", np.nan),
                "gap_pct": row.get("gap_pct", np.nan),
                "opening_range_pct": row.get("opening_range_pct", np.nan),
                "risk_pct": row.get("risk_pct", np.nan),
                "reward_risk": row.get("reward_risk", np.nan),
                "early_market_regime": str(row.get("early_market_regime", "")),
                "research_universe": str(row.get("research_universe", "")),
            }
        )

    ledger = pd.DataFrame(ledger_rows, columns=LEDGER_COLUMNS)
    if not ledger.empty:
        ledger = ledger.sort_values(
            ["entry_time", "entry_priority", "ticker", "source_trade_row"],
            na_position="last",
        ).reset_index(drop=True)

    equity = pd.DataFrame(equity_rows, columns=EQUITY_COLUMNS)
    equity["running_peak_equity_sek"] = pd.to_numeric(
        equity["realized_equity_sek"], errors="coerce"
    ).cummax()
    equity["drawdown"] = (
        equity["realized_equity_sek"] / equity["running_peak_equity_sek"] - 1.0
    )

    selected = ledger[ledger["selected_for_portfolio"]].copy()
    selected_closed = selected[selected["selection_status"] == "SELECTED_CLOSED"].copy()
    selected_open = selected[selected["selection_status"] == "SELECTED_OPEN"].copy()
    rejected = ledger[ledger["selection_status"] == "REJECTED_CAPACITY"].copy()
    excluded = ledger[ledger["selection_status"] == "EXCLUDED_INVALID"].copy()

    selected_pnl = pd.to_numeric(selected_closed["portfolio_pnl_sek"], errors="coerce")
    gross_profit = float(selected_pnl[selected_pnl > 0].sum()) if not selected_pnl.empty else 0.0
    gross_loss = abs(float(selected_pnl[selected_pnl < 0].sum())) if not selected_pnl.empty else 0.0
    final_equity = float(equity.iloc[-1]["realized_equity_sek"]) if not equity.empty else float(ORB_INITIAL_CAPITAL)

    closed_input = work[work["is_closed"] & work["valid_for_simulation"]].copy()
    all_counterfactual = float(
        (pd.to_numeric(closed_input["pnl_pct"], errors="coerce").fillna(0.0) * POSITION_SIZE_SEK).sum()
    )
    rejected_closed = rejected[rejected["exit_reason"].fillna("").astype(str).str.strip().ne("")]
    rejected_counterfactual = float(
        (pd.to_numeric(rejected_closed["source_net_pnl_pct"], errors="coerce").fillna(0.0) * POSITION_SIZE_SEK).sum()
    )

    summary_row = {
        "validation_suite_version": VALIDATION_SUITE_VERSION,
        "portfolio_model_id": PORTFOLIO_MODEL_ID,
        "strategy_id": STRATEGY_ID,
        "research_status": RESEARCH_STATUS,
        "initial_capital_sek": float(ORB_INITIAL_CAPITAL),
        "position_size_pct": float(ORB_POSITION_SIZE),
        "position_size_sek": POSITION_SIZE_SEK,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "entry_priority_rule": ENTRY_PRIORITY_RULE,
        "same_timestamp_policy": SAME_TIMESTAMP_POLICY,
        "pnl_source": PNL_SOURCE,
        "input_trade_rows": int(len(work)),
        "input_closed_trades": int(work["is_closed"].sum()),
        "input_open_trades": int((~work["is_closed"]).sum()),
        "selected_trade_rows": int(len(selected)),
        "selected_closed_trades": int(len(selected_closed)),
        "selected_open_trades": int(len(selected_open)),
        "rejected_capacity_trades": int(len(rejected)),
        "excluded_invalid_trades": int(len(excluded)),
        "selection_rate": float(len(selected) / len(valid)) if len(valid) else np.nan,
        "max_open_positions_observed": int(max_active),
        "same_timestamp_ambiguous_groups": int(ambiguous_group_count),
        "days_with_capacity_rejections": int(rejected["date"].nunique()) if not rejected.empty else 0,
        "win_rate": float((selected_pnl > 0).mean()) if len(selected_closed) else np.nan,
        "gross_profit_sek": gross_profit,
        "gross_loss_sek": gross_loss,
        "profit_factor": _profit_factor(selected_pnl),
        "total_realized_pnl_sek": final_equity - float(ORB_INITIAL_CAPITAL),
        "final_realized_equity_sek": final_equity,
        "total_realized_return": final_equity / float(ORB_INITIAL_CAPITAL) - 1.0,
        "max_drawdown": float(equity["drawdown"].min()) if not equity.empty else 0.0,
        "avg_r_multiple": float(pd.to_numeric(selected_closed["r_multiple_achieved"], errors="coerce").mean()) if len(selected_closed) else np.nan,
        "all_trades_counterfactual_pnl_sek": all_counterfactual,
        "rejected_counterfactual_pnl_sek": rejected_counterfactual,
        "capacity_pnl_difference_sek": (final_equity - float(ORB_INITIAL_CAPITAL)) - all_counterfactual,
        "first_entry_time": (
            valid["entry_time_dt"].min().strftime("%Y-%m-%d %H:%M:%S") if len(valid) else ""
        ),
        "last_event_time": (
            max(event_times).strftime("%Y-%m-%d %H:%M:%S") if event_times else ""
        ),
    }
    summary = pd.DataFrame([summary_row], columns=SUMMARY_COLUMNS)

    daily = build_daily_ledger(ledger)

    return SimulationResult(summary=summary, ledger=ledger, equity=equity, daily=daily)


def build_daily_ledger(ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger is None or ledger.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    dates = sorted(ledger["date"].dropna().astype(str).unique())
    rows: list[dict] = []
    cumulative = 0.0

    for date_value in dates:
        day = ledger[ledger["date"].astype(str) == date_value].copy()
        selected = day[day["selected_for_portfolio"]].copy()
        selected_closed = selected[selected["selection_status"] == "SELECTED_CLOSED"]
        selected_open = selected[selected["selection_status"] == "SELECTED_OPEN"]
        rejected = day[day["selection_status"] == "REJECTED_CAPACITY"]
        pnl = pd.to_numeric(selected_closed["portfolio_pnl_sek"], errors="coerce").fillna(0.0)
        daily_pnl = float(pnl.sum())
        cumulative += daily_pnl

        active_before = pd.to_numeric(selected["active_positions_before_entry"], errors="coerce")
        observed = int(min(MAX_OPEN_POSITIONS, active_before.max() + 1)) if active_before.notna().any() else 0

        rows.append(
            {
                "validation_suite_version": VALIDATION_SUITE_VERSION,
                "portfolio_model_id": PORTFOLIO_MODEL_ID,
                "date": date_value,
                "input_trade_rows": int(len(day)),
                "selected_entries": int(len(selected)),
                "selected_closed_trades": int(len(selected_closed)),
                "selected_open_trades": int(len(selected_open)),
                "rejected_capacity_trades": int(len(rejected)),
                "capacity_ambiguous_trades": int(day["capacity_ambiguous"].fillna(False).astype(bool).sum()),
                "wins": int((pnl > 0).sum()),
                "losses": int((pnl < 0).sum()),
                "daily_realized_pnl_sek": daily_pnl,
                "daily_realized_return_on_initial_capital": daily_pnl / float(ORB_INITIAL_CAPITAL),
                "cumulative_realized_pnl_sek": cumulative,
                "end_realized_equity_sek": float(ORB_INITIAL_CAPITAL) + cumulative,
                "end_cumulative_return": cumulative / float(ORB_INITIAL_CAPITAL),
                "max_open_positions_observed": observed,
            }
        )

    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def export_result(result: SimulationResult) -> None:
    outputs = {
        SUMMARY_FILE: result.summary,
        LEDGER_FILE: result.ledger,
        EQUITY_FILE: result.equity,
        DAILY_FILE: result.daily,
    }
    for path, frame in outputs.items():
        export_csv_for_power_bi(frame, path)
        print(f"Saved {path.name}: {len(frame)} rows")


def main() -> None:
    print("\n=== V1 RESEARCH VALIDATION SUITE - STEP 1 ===")
    print("Module          : True max-two-position portfolio simulation")
    print(f"Strategy        : {STRATEGY_ID}")
    print(f"Portfolio model : {PORTFOLIO_MODEL_ID}")
    print(f"Initial capital : {float(ORB_INITIAL_CAPITAL):.2f} SEK")
    print(f"Position size   : {POSITION_SIZE_SEK:.2f} SEK")
    print(f"Max positions   : {MAX_OPEN_POSITIONS}")
    print(f"Tie break       : {ENTRY_PRIORITY_RULE}")
    print(f"Same timestamp  : {SAME_TIMESTAMP_POLICY}")
    print("V1 candidates, entries, stops, targets, exits, and costs are not changed.")

    trades = load_source_trades()
    result = simulate_portfolio(trades)
    export_result(result)

    row = result.summary.iloc[0]
    print("\n=== PORTFOLIO RESULT ===")
    print(f"Input trade rows       : {int(row['input_trade_rows'])}")
    print(f"Selected trade rows    : {int(row['selected_trade_rows'])}")
    print(f"Rejected by capacity   : {int(row['rejected_capacity_trades'])}")
    print(f"Selected closed trades : {int(row['selected_closed_trades'])}")
    print(f"Selected open trades   : {int(row['selected_open_trades'])}")
    print(f"Peak open positions    : {int(row['max_open_positions_observed'])}")
    print(f"Realized PnL           : {float(row['total_realized_pnl_sek']):.2f} SEK")
    print(f"Final realized equity  : {float(row['final_realized_equity_sek']):.2f} SEK")
    print(f"Max drawdown           : {float(row['max_drawdown']):.4%}")
    print("Step 1 validation export complete.")


if __name__ == "__main__":
    main()
