from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, LEGACY_OUTPUT_DIRS
from RegimeTrading.core.research_config import ORB_INITIAL_CAPITAL, ORB_POSITION_SIZE
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    RESEARCH_STATUS,
    STRATEGY_ID,
)
from RegimeTrading.scripts.v1_validation_portfolio import (
    MAX_OPEN_POSITIONS,
    POSITION_SIZE_SEK,
)


VALIDATION_STEP = "V1_VALIDATION_STEP_6_EXPOSURE_CAPITAL_EFFICIENCY"
VALIDATION_STATUS = "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION"
EXPOSURE_MODEL_ID = "TIME_WEIGHTED_SELECTED_PORTFOLIO_EXPOSURE_V1"
SESSION_START_CLOCK = "09:45:00"
SESSION_END_CLOCK = "16:30:00"
FULL_SESSION_MINUTES = 405.0
OPEN_POSITION_POLICY = "COUNT_TO_LATEST_OBSERVED_BAR_NO_UNREALIZED_PNL"
SIZING_POLICY = "LINEAR_FIXED_SIZE_SELECTION_UNCHANGED_NO_COMPOUNDING"

OUTPUT_DIR = LEGACY_OUTPUT_DIRS["v1_validation"]
PORTFOLIO_LEDGER_FILE = OUTPUT_DIR / "v1_validation_portfolio_trade_ledger.csv"
PORTFOLIO_EQUITY_FILE = OUTPUT_DIR / "v1_validation_portfolio_equity_curve.csv"
RESEARCH_DAILY_FILE = DATA_DIR / "regime_gap_recovery_daily.csv"
CANDIDATES_FILE = DATA_DIR / "regime_gap_recovery_candidates.csv"

SUMMARY_FILE = OUTPUT_DIR / "v1_validation_exposure_efficiency_summary.csv"
POSITION_DETAIL_FILE = OUTPUT_DIR / "v1_validation_exposure_position_detail.csv"
INTERVAL_DETAIL_FILE = OUTPUT_DIR / "v1_validation_exposure_interval_detail.csv"
DAILY_FILE = OUTPUT_DIR / "v1_validation_exposure_daily.csv"
SIZING_FILE = OUTPUT_DIR / "v1_validation_position_size_scenarios.csv"

SUMMARY_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "exposure_model_id",
    "open_position_policy",
    "session_start_clock",
    "session_end_clock",
    "full_session_minutes",
    "study_start_date",
    "study_end_date",
    "study_calendar_days",
    "observed_research_sessions",
    "complete_observed_sessions",
    "incomplete_observed_sessions",
    "active_trading_days",
    "selected_position_count",
    "selected_closed_positions",
    "selected_open_positions",
    "initial_capital_sek",
    "position_size_sek",
    "max_open_positions",
    "max_deployable_capital_sek",
    "total_observed_strategy_hours",
    "total_position_hours",
    "closed_position_hours",
    "open_observed_position_hours",
    "position_session_equivalents",
    "capital_hours_sek",
    "average_deployed_capital_sek",
    "average_deployed_capital_active_days_sek",
    "maximum_deployed_capital_sek",
    "account_capital_utilization_rate",
    "active_day_account_utilization_rate",
    "slot_capacity_utilization_rate",
    "idle_cash_rate",
    "time_zero_positions_rate",
    "time_one_position_rate",
    "time_two_positions_rate",
    "realized_pnl_sek",
    "account_period_return",
    "return_on_average_deployed_capital",
    "return_on_maximum_deployed_capital",
    "average_realized_pnl_per_closed_trade_sek",
    "average_net_return_per_closed_trade",
    "realized_pnl_per_closed_position_hour_sek",
    "realized_pnl_per_active_trading_day_sek",
    "realized_pnl_per_observed_session_sek",
    "mechanical_annualized_account_return",
    "mechanical_annualized_return_on_average_deployed_capital",
    "capital_efficiency_classification",
    "generated_at_utc",
]

POSITION_DETAIL_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "source_trade_row",
    "date",
    "ticker",
    "selection_status",
    "entry_time",
    "reported_exit_time",
    "effective_exposure_end_time",
    "exposure_end_source",
    "is_realized_closed_position",
    "is_open_position",
    "model_position_size_sek",
    "exposure_minutes",
    "position_hours",
    "capital_minutes_sek",
    "capital_hours_sek",
    "position_session_equivalents",
    "realized_pnl_sek",
    "realized_return_on_position_size",
    "exit_reason",
    "early_market_regime",
    "research_universe",
]

INTERVAL_DETAIL_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "date",
    "interval_start",
    "interval_end",
    "interval_minutes",
    "open_positions",
    "active_tickers",
    "deployed_capital_sek",
    "account_capital_utilization_rate",
    "slot_capacity_utilization_rate",
    "idle_cash_sek",
    "realized_equity_at_interval_start_sek",
    "cumulative_realized_pnl_at_interval_start_sek",
    "session_complete",
]

DAILY_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "date",
    "observed_session_start",
    "observed_session_end",
    "observed_strategy_minutes",
    "session_complete",
    "selected_positions",
    "selected_closed_positions",
    "selected_open_positions",
    "zero_position_minutes",
    "one_position_minutes",
    "two_position_minutes",
    "position_minutes",
    "position_hours",
    "capital_hours_sek",
    "average_deployed_capital_sek",
    "maximum_deployed_capital_sek",
    "account_capital_utilization_rate",
    "slot_capacity_utilization_rate",
    "idle_cash_rate",
    "realized_pnl_sek",
    "realized_pnl_per_position_hour_sek",
    "active_trading_day",
]

SIZING_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "scenario_order",
    "scenario_id",
    "scenario_label",
    "fixed_position_size_sek",
    "position_size_pct_of_account",
    "max_two_slot_allocation_sek",
    "max_two_slot_allocation_rate",
    "selection_unchanged",
    "selected_closed_positions",
    "scaled_realized_pnl_sek",
    "scaled_final_realized_equity_sek",
    "scaled_account_period_return",
    "scaled_max_drawdown",
    "scaled_average_deployed_capital_sek",
    "scaled_account_capital_utilization_rate",
    "mechanical_annualized_account_return",
    "sizing_policy",
]


@dataclass(frozen=True)
class ExposureEfficiencyResult:
    summary: pd.DataFrame
    position_detail: pd.DataFrame
    interval_detail: pd.DataFrame
    daily: pd.DataFrame
    sizing_scenarios: pd.DataFrame


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_datetime(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(series, errors="coerce")


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator is None or not np.isfinite(denominator) or denominator == 0:
        return np.nan
    return float(numerator) / float(denominator)


def _annualize(period_return: float, calendar_days: int) -> float:
    if calendar_days <= 0 or not np.isfinite(period_return) or period_return <= -1.0:
        return np.nan
    return float((1.0 + period_return) ** (365.0 / float(calendar_days)) - 1.0)


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _study_dates(research_daily: pd.DataFrame, ledger: pd.DataFrame) -> list[str]:
    values: set[str] = set()
    if not research_daily.empty and "date" in research_daily:
        values.update(research_daily["date"].dropna().astype(str).tolist())
    if not ledger.empty and "date" in ledger:
        values.update(ledger["date"].dropna().astype(str).tolist())
    return sorted(value for value in values if value and value.lower() != "nan")


def _observed_session_ends(
    dates: list[str], candidates: pd.DataFrame
) -> dict[str, pd.Timestamp]:
    candidate_last: dict[str, pd.Timestamp] = {}
    if not candidates.empty and {"date", "last_bar"}.issubset(candidates.columns):
        work = candidates[["date", "last_bar"]].copy()
        work["date"] = work["date"].astype(str)
        work["last_bar_dt"] = _parse_datetime(work["last_bar"])
        grouped = work.dropna(subset=["last_bar_dt"]).groupby("date")["last_bar_dt"].max()
        candidate_last = {str(key): pd.Timestamp(value) for key, value in grouped.items()}

    output: dict[str, pd.Timestamp] = {}
    for date_text in dates:
        start = pd.Timestamp(f"{date_text} {SESSION_START_CLOCK}")
        full_end = pd.Timestamp(f"{date_text} {SESSION_END_CLOCK}")
        observed = candidate_last.get(date_text, full_end)
        observed = min(max(pd.Timestamp(observed), start), full_end)
        output[date_text] = observed
    return output


def build_position_detail(
    ledger: pd.DataFrame,
    observed_ends: dict[str, pd.Timestamp],
) -> pd.DataFrame:
    if ledger.empty:
        return pd.DataFrame(columns=POSITION_DETAIL_COLUMNS)

    selected = ledger.copy()
    if "selected_for_portfolio" in selected:
        selected = selected[
            selected["selected_for_portfolio"].astype(str).str.lower().isin({"true", "1"})
        ].copy()
    else:
        selected = selected[selected["selection_status"].astype(str).str.startswith("SELECTED")].copy()

    selected["entry_dt"] = _parse_datetime(selected.get("entry_time", pd.Series(dtype=str)))
    selected["exit_dt"] = _parse_datetime(selected.get("exit_time", pd.Series(dtype=str)))
    selected["model_position_size_sek"] = pd.to_numeric(
        selected.get("model_position_size_sek", POSITION_SIZE_SEK), errors="coerce"
    ).fillna(POSITION_SIZE_SEK)
    selected["portfolio_pnl_sek"] = pd.to_numeric(
        selected.get("portfolio_pnl_sek", 0.0), errors="coerce"
    ).fillna(0.0)

    rows: list[dict] = []
    for _, row in selected.iterrows():
        date_text = str(row.get("date", ""))
        entry = row.get("entry_dt")
        if pd.isna(entry) or date_text not in observed_ends:
            continue
        observed_end = observed_ends[date_text]
        is_closed = str(row.get("selection_status", "")) == "SELECTED_CLOSED"
        reported_exit = row.get("exit_dt")
        if is_closed and pd.notna(reported_exit):
            effective_end = min(pd.Timestamp(reported_exit), observed_end)
            end_source = "ACTUAL_REPORTED_EXIT"
        else:
            effective_end = observed_end
            end_source = "LATEST_OBSERVED_BAR_OPEN_POSITION"
        effective_end = max(pd.Timestamp(entry), effective_end)
        duration = max((effective_end - pd.Timestamp(entry)).total_seconds() / 60.0, 0.0)
        size = float(row.get("model_position_size_sek", POSITION_SIZE_SEK))
        pnl = float(row.get("portfolio_pnl_sek", 0.0)) if is_closed else 0.0
        rows.append(
            {
                "strategy_id": STRATEGY_ID,
                "validation_step": VALIDATION_STEP,
                "validation_status": VALIDATION_STATUS,
                "source_trade_row": row.get("source_trade_row", np.nan),
                "date": date_text,
                "ticker": str(row.get("ticker", "")),
                "selection_status": str(row.get("selection_status", "")),
                "entry_time": pd.Timestamp(entry).strftime("%Y-%m-%d %H:%M:%S"),
                "reported_exit_time": (
                    pd.Timestamp(reported_exit).strftime("%Y-%m-%d %H:%M:%S")
                    if pd.notna(reported_exit)
                    else ""
                ),
                "effective_exposure_end_time": effective_end.strftime("%Y-%m-%d %H:%M:%S"),
                "exposure_end_source": end_source,
                "is_realized_closed_position": bool(is_closed),
                "is_open_position": bool(not is_closed),
                "model_position_size_sek": size,
                "exposure_minutes": duration,
                "position_hours": duration / 60.0,
                "capital_minutes_sek": duration * size,
                "capital_hours_sek": duration * size / 60.0,
                "position_session_equivalents": duration / FULL_SESSION_MINUTES,
                "realized_pnl_sek": pnl,
                "realized_return_on_position_size": _safe_divide(pnl, size),
                "exit_reason": str(row.get("exit_reason", "")) if is_closed else "",
                "early_market_regime": str(row.get("early_market_regime", "")),
                "research_universe": str(row.get("research_universe", "")),
            }
        )
    return pd.DataFrame(rows, columns=POSITION_DETAIL_COLUMNS).sort_values(
        ["entry_time", "ticker"], ignore_index=True
    ) if rows else pd.DataFrame(columns=POSITION_DETAIL_COLUMNS)


def _realized_exit_events(position_detail: pd.DataFrame) -> dict[pd.Timestamp, float]:
    events: dict[pd.Timestamp, float] = {}
    if position_detail.empty:
        return events
    closed = position_detail[position_detail["is_realized_closed_position"].astype(bool)]
    for _, row in closed.iterrows():
        timestamp = pd.to_datetime(row["effective_exposure_end_time"], errors="coerce")
        if pd.isna(timestamp):
            continue
        events[pd.Timestamp(timestamp)] = events.get(pd.Timestamp(timestamp), 0.0) + float(
            row["realized_pnl_sek"]
        )
    return events


def build_interval_detail(
    dates: list[str],
    observed_ends: dict[str, pd.Timestamp],
    position_detail: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    realized_equity = float(ORB_INITIAL_CAPITAL)
    exit_events = _realized_exit_events(position_detail)

    for date_text in dates:
        session_start = pd.Timestamp(f"{date_text} {SESSION_START_CLOCK}")
        session_end = observed_ends[date_text]
        day_positions = position_detail[position_detail["date"].astype(str) == date_text].copy()
        if not day_positions.empty:
            day_positions["entry_dt"] = _parse_datetime(day_positions["entry_time"])
            day_positions["end_dt"] = _parse_datetime(day_positions["effective_exposure_end_time"])
        event_times = {session_start, session_end}
        if not day_positions.empty:
            event_times.update(pd.Timestamp(value) for value in day_positions["entry_dt"].dropna())
            event_times.update(pd.Timestamp(value) for value in day_positions["end_dt"].dropna())
        event_times = sorted(value for value in event_times if session_start <= value <= session_end)

        active: dict[int, str] = {}
        for index in range(len(event_times) - 1):
            current = event_times[index]
            following = event_times[index + 1]

            # Apply entries before exits at the same timestamp, matching the portfolio
            # simulator. A trade that enters and exits on the same five-minute bar
            # therefore contributes zero elapsed exposure after the timestamp.
            if current in exit_events:
                realized_equity += exit_events[current]
            if not day_positions.empty:
                starting = day_positions[day_positions["entry_dt"] == current]
                for _, trade in starting.iterrows():
                    active[int(trade["source_trade_row"])] = str(trade["ticker"])
                ending = day_positions[day_positions["end_dt"] == current]
                for _, trade in ending.iterrows():
                    active.pop(int(trade["source_trade_row"]), None)

            minutes = max((following - current).total_seconds() / 60.0, 0.0)
            count = len(active)
            deployed = float(count) * float(POSITION_SIZE_SEK)
            rows.append(
                {
                    "strategy_id": STRATEGY_ID,
                    "validation_step": VALIDATION_STEP,
                    "validation_status": VALIDATION_STATUS,
                    "date": date_text,
                    "interval_start": current.strftime("%Y-%m-%d %H:%M:%S"),
                    "interval_end": following.strftime("%Y-%m-%d %H:%M:%S"),
                    "interval_minutes": minutes,
                    "open_positions": count,
                    "active_tickers": ";".join(sorted(active.values())),
                    "deployed_capital_sek": deployed,
                    "account_capital_utilization_rate": deployed / float(ORB_INITIAL_CAPITAL),
                    "slot_capacity_utilization_rate": _safe_divide(
                        deployed, float(POSITION_SIZE_SEK) * float(MAX_OPEN_POSITIONS)
                    ),
                    "idle_cash_sek": float(ORB_INITIAL_CAPITAL) - deployed,
                    "realized_equity_at_interval_start_sek": realized_equity,
                    "cumulative_realized_pnl_at_interval_start_sek": realized_equity
                    - float(ORB_INITIAL_CAPITAL),
                    "session_complete": bool(session_end == pd.Timestamp(f"{date_text} {SESSION_END_CLOCK}")),
                }
            )

        if session_end in exit_events:
            realized_equity += exit_events[session_end]

    return pd.DataFrame(rows, columns=INTERVAL_DETAIL_COLUMNS)


def build_daily(
    dates: list[str],
    observed_ends: dict[str, pd.Timestamp],
    position_detail: pd.DataFrame,
    interval_detail: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    for date_text in dates:
        start = pd.Timestamp(f"{date_text} {SESSION_START_CLOCK}")
        end = observed_ends[date_text]
        observed_minutes = max((end - start).total_seconds() / 60.0, 0.0)
        intervals = interval_detail[interval_detail["date"].astype(str) == date_text].copy()
        positions = position_detail[position_detail["date"].astype(str) == date_text].copy()
        minute_by_count = {
            count: float(
                pd.to_numeric(
                    intervals.loc[intervals["open_positions"] == count, "interval_minutes"],
                    errors="coerce",
                ).fillna(0.0).sum()
            )
            for count in (0, 1, 2)
        }
        position_minutes = minute_by_count[1] + 2.0 * minute_by_count[2]
        capital_hours = position_minutes * float(POSITION_SIZE_SEK) / 60.0
        average_deployed = _safe_divide(position_minutes * float(POSITION_SIZE_SEK), observed_minutes)
        realized_pnl = float(pd.to_numeric(positions["realized_pnl_sek"], errors="coerce").fillna(0.0).sum()) if not positions.empty else 0.0
        position_hours = position_minutes / 60.0
        rows.append(
            {
                "strategy_id": STRATEGY_ID,
                "validation_step": VALIDATION_STEP,
                "validation_status": VALIDATION_STATUS,
                "date": date_text,
                "observed_session_start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "observed_session_end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "observed_strategy_minutes": observed_minutes,
                "session_complete": bool(end == pd.Timestamp(f"{date_text} {SESSION_END_CLOCK}")),
                "selected_positions": int(len(positions)),
                "selected_closed_positions": int(positions["is_realized_closed_position"].astype(bool).sum()) if not positions.empty else 0,
                "selected_open_positions": int(positions["is_open_position"].astype(bool).sum()) if not positions.empty else 0,
                "zero_position_minutes": minute_by_count[0],
                "one_position_minutes": minute_by_count[1],
                "two_position_minutes": minute_by_count[2],
                "position_minutes": position_minutes,
                "position_hours": position_hours,
                "capital_hours_sek": capital_hours,
                "average_deployed_capital_sek": average_deployed,
                "maximum_deployed_capital_sek": float(pd.to_numeric(intervals["deployed_capital_sek"], errors="coerce").max()) if not intervals.empty else 0.0,
                "account_capital_utilization_rate": _safe_divide(average_deployed, float(ORB_INITIAL_CAPITAL)),
                "slot_capacity_utilization_rate": _safe_divide(
                    average_deployed, float(POSITION_SIZE_SEK) * float(MAX_OPEN_POSITIONS)
                ),
                "idle_cash_rate": 1.0 - _safe_divide(average_deployed, float(ORB_INITIAL_CAPITAL)) if np.isfinite(average_deployed) else np.nan,
                "realized_pnl_sek": realized_pnl,
                "realized_pnl_per_position_hour_sek": _safe_divide(realized_pnl, position_hours),
                "active_trading_day": bool(len(positions) > 0),
            }
        )
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def _scaled_max_drawdown(position_detail: pd.DataFrame, scale: float) -> float:
    closed = position_detail[position_detail["is_realized_closed_position"].astype(bool)].copy()
    if closed.empty:
        return 0.0
    closed["end_dt"] = _parse_datetime(closed["effective_exposure_end_time"])
    closed = closed.sort_values(["end_dt", "ticker", "source_trade_row"])
    pnl = pd.to_numeric(closed["realized_pnl_sek"], errors="coerce").fillna(0.0) * scale
    equity = float(ORB_INITIAL_CAPITAL) + pnl.cumsum()
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min()) if not drawdown.empty else 0.0


def build_sizing_scenarios(
    position_detail: pd.DataFrame,
    average_deployed_capital_sek: float,
    study_calendar_days: int,
) -> pd.DataFrame:
    sizes = [1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 4000.0, 5000.0]
    baseline_pnl = float(pd.to_numeric(position_detail["realized_pnl_sek"], errors="coerce").fillna(0.0).sum()) if not position_detail.empty else 0.0
    closed_count = int(position_detail["is_realized_closed_position"].astype(bool).sum()) if not position_detail.empty else 0
    rows: list[dict] = []
    for order, size in enumerate(sizes, start=1):
        scale = size / float(POSITION_SIZE_SEK)
        pnl = baseline_pnl * scale
        period_return = pnl / float(ORB_INITIAL_CAPITAL)
        average_deployed = average_deployed_capital_sek * scale
        rows.append(
            {
                "strategy_id": STRATEGY_ID,
                "validation_step": VALIDATION_STEP,
                "validation_status": VALIDATION_STATUS,
                "scenario_order": order,
                "scenario_id": "CURRENT_V1" if size == POSITION_SIZE_SEK else f"FIXED_{int(size)}_SEK",
                "scenario_label": "Current V1 position size" if size == POSITION_SIZE_SEK else f"Fixed {int(size):,} SEK per position",
                "fixed_position_size_sek": size,
                "position_size_pct_of_account": size / float(ORB_INITIAL_CAPITAL),
                "max_two_slot_allocation_sek": size * float(MAX_OPEN_POSITIONS),
                "max_two_slot_allocation_rate": size * float(MAX_OPEN_POSITIONS) / float(ORB_INITIAL_CAPITAL),
                "selection_unchanged": True,
                "selected_closed_positions": closed_count,
                "scaled_realized_pnl_sek": pnl,
                "scaled_final_realized_equity_sek": float(ORB_INITIAL_CAPITAL) + pnl,
                "scaled_account_period_return": period_return,
                "scaled_max_drawdown": _scaled_max_drawdown(position_detail, scale),
                "scaled_average_deployed_capital_sek": average_deployed,
                "scaled_account_capital_utilization_rate": average_deployed / float(ORB_INITIAL_CAPITAL),
                "mechanical_annualized_account_return": _annualize(period_return, study_calendar_days),
                "sizing_policy": SIZING_POLICY,
            }
        )
    return pd.DataFrame(rows, columns=SIZING_COLUMNS)


def _classification(realized_pnl: float, utilization: float) -> str:
    if realized_pnl <= 0:
        return "NON_POSITIVE_EDGE"
    if utilization < 0.05:
        return "POSITIVE_EDGE_VERY_LOW_ACCOUNT_UTILIZATION"
    if utilization < 0.15:
        return "POSITIVE_EDGE_LOW_ACCOUNT_UTILIZATION"
    if utilization < 0.35:
        return "POSITIVE_EDGE_MODERATE_ACCOUNT_UTILIZATION"
    return "POSITIVE_EDGE_HIGH_ACCOUNT_UTILIZATION"


def build_summary(
    dates: list[str],
    observed_ends: dict[str, pd.Timestamp],
    position_detail: pd.DataFrame,
    interval_detail: pd.DataFrame,
    daily: pd.DataFrame,
) -> pd.DataFrame:
    observed_minutes = float(pd.to_numeric(daily["observed_strategy_minutes"], errors="coerce").fillna(0.0).sum()) if not daily.empty else 0.0
    position_hours = float(pd.to_numeric(position_detail["position_hours"], errors="coerce").fillna(0.0).sum()) if not position_detail.empty else 0.0
    closed = position_detail[position_detail["is_realized_closed_position"].astype(bool)].copy() if not position_detail.empty else position_detail.copy()
    opened = position_detail[position_detail["is_open_position"].astype(bool)].copy() if not position_detail.empty else position_detail.copy()
    closed_hours = float(pd.to_numeric(closed.get("position_hours", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    open_hours = float(pd.to_numeric(opened.get("position_hours", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    capital_minutes = position_hours * 60.0 * float(POSITION_SIZE_SEK)
    average_deployed = _safe_divide(capital_minutes, observed_minutes)
    active_daily = daily[daily["active_trading_day"].astype(bool)] if not daily.empty else daily
    active_minutes = float(pd.to_numeric(active_daily.get("observed_strategy_minutes", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    average_active = _safe_divide(capital_minutes, active_minutes)
    realized_pnl = float(pd.to_numeric(closed.get("realized_pnl_sek", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    account_return = realized_pnl / float(ORB_INITIAL_CAPITAL)
    study_start = dates[0] if dates else ""
    study_end = dates[-1] if dates else ""
    calendar_days = (
        (pd.Timestamp(study_end) - pd.Timestamp(study_start)).days + 1
        if study_start and study_end
        else 0
    )
    total_interval_minutes = float(pd.to_numeric(interval_detail.get("interval_minutes", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    minutes_by_count = {
        count: float(pd.to_numeric(interval_detail.loc[interval_detail["open_positions"] == count, "interval_minutes"], errors="coerce").fillna(0.0).sum())
        if not interval_detail.empty else 0.0
        for count in (0, 1, 2)
    }
    maximum_deployed = float(pd.to_numeric(interval_detail.get("deployed_capital_sek", pd.Series(dtype=float)), errors="coerce").max()) if not interval_detail.empty else 0.0
    closed_entry_capital = float(pd.to_numeric(closed.get("model_position_size_sek", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    utilization = _safe_divide(average_deployed, float(ORB_INITIAL_CAPITAL))
    return_on_average = _safe_divide(realized_pnl, average_deployed)

    row = {
        "strategy_id": STRATEGY_ID,
        "validation_step": VALIDATION_STEP,
        "validation_status": VALIDATION_STATUS,
        "exposure_model_id": EXPOSURE_MODEL_ID,
        "open_position_policy": OPEN_POSITION_POLICY,
        "session_start_clock": SESSION_START_CLOCK,
        "session_end_clock": SESSION_END_CLOCK,
        "full_session_minutes": FULL_SESSION_MINUTES,
        "study_start_date": study_start,
        "study_end_date": study_end,
        "study_calendar_days": calendar_days,
        "observed_research_sessions": len(dates),
        "complete_observed_sessions": int(sum(observed_ends[d] == pd.Timestamp(f"{d} {SESSION_END_CLOCK}") for d in dates)),
        "incomplete_observed_sessions": int(sum(observed_ends[d] != pd.Timestamp(f"{d} {SESSION_END_CLOCK}") for d in dates)),
        "active_trading_days": int(daily["active_trading_day"].astype(bool).sum()) if not daily.empty else 0,
        "selected_position_count": int(len(position_detail)),
        "selected_closed_positions": int(len(closed)),
        "selected_open_positions": int(len(opened)),
        "initial_capital_sek": float(ORB_INITIAL_CAPITAL),
        "position_size_sek": float(POSITION_SIZE_SEK),
        "max_open_positions": int(MAX_OPEN_POSITIONS),
        "max_deployable_capital_sek": float(POSITION_SIZE_SEK) * float(MAX_OPEN_POSITIONS),
        "total_observed_strategy_hours": observed_minutes / 60.0,
        "total_position_hours": position_hours,
        "closed_position_hours": closed_hours,
        "open_observed_position_hours": open_hours,
        "position_session_equivalents": position_hours / (FULL_SESSION_MINUTES / 60.0),
        "capital_hours_sek": position_hours * float(POSITION_SIZE_SEK),
        "average_deployed_capital_sek": average_deployed,
        "average_deployed_capital_active_days_sek": average_active,
        "maximum_deployed_capital_sek": maximum_deployed,
        "account_capital_utilization_rate": utilization,
        "active_day_account_utilization_rate": _safe_divide(average_active, float(ORB_INITIAL_CAPITAL)),
        "slot_capacity_utilization_rate": _safe_divide(average_deployed, float(POSITION_SIZE_SEK) * float(MAX_OPEN_POSITIONS)),
        "idle_cash_rate": 1.0 - utilization if np.isfinite(utilization) else np.nan,
        "time_zero_positions_rate": _safe_divide(minutes_by_count[0], total_interval_minutes),
        "time_one_position_rate": _safe_divide(minutes_by_count[1], total_interval_minutes),
        "time_two_positions_rate": _safe_divide(minutes_by_count[2], total_interval_minutes),
        "realized_pnl_sek": realized_pnl,
        "account_period_return": account_return,
        "return_on_average_deployed_capital": return_on_average,
        "return_on_maximum_deployed_capital": _safe_divide(realized_pnl, maximum_deployed),
        "average_realized_pnl_per_closed_trade_sek": _safe_divide(realized_pnl, len(closed)),
        "average_net_return_per_closed_trade": _safe_divide(realized_pnl, closed_entry_capital),
        "realized_pnl_per_closed_position_hour_sek": _safe_divide(realized_pnl, closed_hours),
        "realized_pnl_per_active_trading_day_sek": _safe_divide(realized_pnl, int(daily["active_trading_day"].astype(bool).sum()) if not daily.empty else 0),
        "realized_pnl_per_observed_session_sek": _safe_divide(realized_pnl, len(dates)),
        "mechanical_annualized_account_return": _annualize(account_return, calendar_days),
        "mechanical_annualized_return_on_average_deployed_capital": _annualize(return_on_average, calendar_days),
        "capital_efficiency_classification": _classification(realized_pnl, utilization),
        "generated_at_utc": _now_utc(),
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_analysis(
    ledger: pd.DataFrame,
    research_daily: pd.DataFrame,
    candidates: pd.DataFrame,
) -> ExposureEfficiencyResult:
    dates = _study_dates(research_daily, ledger)
    observed_ends = _observed_session_ends(dates, candidates)
    position_detail = build_position_detail(ledger, observed_ends)
    interval_detail = build_interval_detail(dates, observed_ends, position_detail)
    daily = build_daily(dates, observed_ends, position_detail, interval_detail)
    summary = build_summary(dates, observed_ends, position_detail, interval_detail, daily)
    calendar_days = int(summary.iloc[0]["study_calendar_days"]) if not summary.empty else 0
    average_deployed = float(summary.iloc[0]["average_deployed_capital_sek"]) if not summary.empty else 0.0
    sizing = build_sizing_scenarios(position_detail, average_deployed, calendar_days)
    return ExposureEfficiencyResult(summary, position_detail, interval_detail, daily, sizing)


def export_result(result: ExposureEfficiencyResult) -> None:
    outputs = {
        SUMMARY_FILE: result.summary,
        POSITION_DETAIL_FILE: result.position_detail,
        INTERVAL_DETAIL_FILE: result.interval_detail,
        DAILY_FILE: result.daily,
        SIZING_FILE: result.sizing_scenarios,
    }
    for path, frame in outputs.items():
        export_csv_for_power_bi(frame, path)
        print(f"Saved {path.name}: {len(frame)} rows")


def main() -> None:
    print("\n=== V1 RESEARCH VALIDATION SUITE - STEP 6 ===")
    print("Module          : Exposure and capital-efficiency report")
    print(f"Strategy        : {STRATEGY_ID}")
    print(f"Exposure model  : {EXPOSURE_MODEL_ID}")
    print(f"Session window  : {SESSION_START_CLOCK[:5]}-{SESSION_END_CLOCK[:5]}")
    print(f"Position size   : {POSITION_SIZE_SEK:.2f} SEK")
    print(f"Max positions   : {MAX_OPEN_POSITIONS}")
    print(f"Open positions  : {OPEN_POSITION_POLICY}")
    print("V1 trade selection and execution outcomes are not changed.")

    result = run_analysis(
        _load_csv(PORTFOLIO_LEDGER_FILE),
        _load_csv(RESEARCH_DAILY_FILE),
        _load_csv(CANDIDATES_FILE),
    )
    export_result(result)

    row = result.summary.iloc[0]
    print("\n=== EXPOSURE AND CAPITAL EFFICIENCY RESULT ===")
    print(f"Observed sessions            : {int(row['observed_research_sessions'])}")
    print(f"Active trading days          : {int(row['active_trading_days'])}")
    print(f"Total position hours         : {float(row['total_position_hours']):.2f}")
    print(f"Average deployed capital     : {float(row['average_deployed_capital_sek']):.2f} SEK")
    print(f"Account capital utilization  : {float(row['account_capital_utilization_rate']):.2%}")
    print(f"Time with zero positions     : {float(row['time_zero_positions_rate']):.2%}")
    print(f"Time with one position       : {float(row['time_one_position_rate']):.2%}")
    print(f"Time with two positions      : {float(row['time_two_positions_rate']):.2%}")
    print(f"Realized PnL                 : {float(row['realized_pnl_sek']):.2f} SEK")
    print(f"Account period return        : {float(row['account_period_return']):.4%}")
    print(f"Return on avg deployed cap.  : {float(row['return_on_average_deployed_capital']):.2%}")
    print(f"Annualized account return    : {float(row['mechanical_annualized_account_return']):.2%}")
    print(f"Classification               : {row['capital_efficiency_classification']}")
    print("Step 6 validation export complete.")


if __name__ == "__main__":
    main()
