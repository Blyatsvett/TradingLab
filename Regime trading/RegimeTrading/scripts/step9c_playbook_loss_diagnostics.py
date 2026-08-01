from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, legacy_output_path
from RegimeTrading.scripts.research_regime_aware_gap_recovery import load_intraday_prices
from RegimeTrading.scripts.step8_provisional_regime_taxonomy import REGIMES
from RegimeTrading.scripts.step9_playbook_specifications import PLAYBOOKS
from RegimeTrading.scripts.step9b_baseline_trade_generation import (
    CANDIDATE_FILE,
    LEG_FILE,
    PERFORMANCE_FILE,
    SESSION_FILE,
    SUMMARY_FILE as BASELINE_SUMMARY_FILE,
    TRADE_FILE,
    ROUND_TRIP_COST_RATE,
    _directional_execution,
)


DIAGNOSTIC_ID = "REGIME_PLAYBOOK_LOSS_DIAGNOSTICS_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_DIAGNOSTIC_NOT_OPTIMIZED"
MINIMUM_INFERENCE_TRADES = 8
TARGET_R_SCENARIOS = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00)
COST_BPS_SCENARIOS = (0.0, 1.0, 2.5, 5.0, 7.5, 10.0)

PLAYBOOK_EXIT_CUTOFF = {
    "RECOVERY": "16:30",
    "TREND_UP": "16:30",
    "TREND_DOWN": "16:30",
    "RANGE_LOW_VOL": "15:30",
    "HIGH_VOL_REVERSAL": "16:30",
    "HIGH_DISPERSION": "15:30",
    "VOLATILITY_EXPANSION": "16:30",
    "DEFENSIVE_MIXED": "14:30",
    "DATA_LIMITED_DEFENSIVE": "12:00",
}

SUMMARY_FILE = legacy_output_path("regime_playbook_diagnostic_summary.csv")
TRADE_DIAGNOSTIC_FILE = legacy_output_path("regime_playbook_trade_diagnostics.csv")
PLAYBOOK_DIAGNOSTIC_FILE = legacy_output_path("regime_playbook_diagnostics.csv")
SLICE_FILE = legacy_output_path("regime_playbook_diagnostic_slices.csv")
TARGET_SCENARIO_FILE = legacy_output_path("regime_playbook_target_scenarios.csv")
COST_SCENARIO_FILE = legacy_output_path("regime_playbook_cost_scenarios.csv")
LEAVE_ONE_DAY_OUT_FILE = legacy_output_path("regime_playbook_leave_one_day_out.csv")
PAIR_DIRECTION_FILE = legacy_output_path("regime_playbook_pair_direction_controls.csv")

SUMMARY_COLUMNS = [
    "diagnostic_id",
    "research_status",
    "source_simulation_id",
    "source_sessions",
    "source_trades",
    "enriched_trades",
    "single_trades",
    "paired_trades",
    "playbooks_evaluated",
    "playbooks_with_minimum_sample",
    "positive_gross_playbooks",
    "positive_net_playbooks",
    "keep_recommendations",
    "modify_recommendations",
    "invert_recommendations",
    "replace_recommendations",
    "insufficient_sample_recommendations",
    "gross_pnl_sek_unconstrained",
    "cost_sek_unconstrained",
    "net_pnl_sek_unconstrained",
    "all_source_trades_point_in_time_safe",
    "all_trades_enriched",
    "diagnostic_invariant_failures",
    "classification",
]

TRADE_DIAGNOSTIC_COLUMNS = [
    "diagnostic_id",
    "trade_id",
    "idea_id",
    "date",
    "primary_regime",
    "playbook_id",
    "idea_type",
    "direction",
    "ticker",
    "paired_ticker",
    "long_ticker",
    "short_ticker",
    "regime_confidence",
    "confidence_band",
    "entry_time",
    "entry_clock",
    "entry_time_bucket",
    "exit_time",
    "exit_reason",
    "trade_duration_minutes",
    "duration_bucket",
    "notional_sek",
    "gross_return",
    "gross_pnl_sek",
    "cost_sek",
    "net_pnl_sek",
    "winning_trade",
    "risk_per_share",
    "r_multiple_achieved",
    "actual_mfe_return",
    "actual_mae_return",
    "actual_mfe_pnl_sek",
    "actual_mae_pnl_sek",
    "actual_mfe_r",
    "actual_mae_r",
    "horizon_mfe_return",
    "horizon_mae_return",
    "horizon_close_return",
    "horizon_close_gross_pnl_sek",
    "stopped_then_positive_by_cutoff",
    "stopped_then_reached_half_r_by_cutoff",
    "gross_capture_of_actual_mfe",
    "pair_opposite_same_exit_gross_return",
    "pair_opposite_same_exit_gross_pnl_sek",
    "entry_bar_excursion_excluded",
    "point_in_time_pass",
    "diagnostic_pass",
    "diagnostic_status",
]

PLAYBOOK_DIAGNOSTIC_COLUMNS = [
    "diagnostic_id",
    "primary_regime",
    "playbook_id",
    "regime_sessions",
    "trades",
    "sessions_with_trades",
    "sample_status",
    "winning_trades",
    "losing_trades",
    "win_rate",
    "gross_pnl_sek_unconstrained",
    "cost_sek_unconstrained",
    "net_pnl_sek_unconstrained",
    "average_net_pnl_sek",
    "median_net_pnl_sek",
    "profit_factor",
    "target_hit_rate",
    "stop_hit_rate",
    "time_exit_rate",
    "average_actual_mfe_return",
    "average_actual_mae_return",
    "median_actual_mfe_r",
    "median_actual_mae_r",
    "average_gross_capture_of_mfe",
    "stopped_trades",
    "stopped_then_positive_by_cutoff",
    "stopped_then_positive_rate",
    "break_even_round_trip_cost_bps",
    "best_standardized_target_r",
    "best_standardized_target_net_pnl_sek",
    "pair_opposite_same_exit_gross_pnl_sek",
    "top_trade_abs_pnl_share",
    "top_day_abs_pnl_share",
    "leave_one_day_out_profitable_share",
    "leave_one_day_out_min_pnl_sek",
    "recommended_action",
    "recommendation_confidence",
    "diagnostic_rationale",
]

SLICE_COLUMNS = [
    "diagnostic_id",
    "primary_regime",
    "playbook_id",
    "dimension",
    "bucket",
    "trades",
    "winning_trades",
    "win_rate",
    "gross_pnl_sek",
    "cost_sek",
    "net_pnl_sek",
    "average_net_pnl_sek",
    "median_net_pnl_sek",
    "profit_factor",
    "average_actual_mfe_return",
    "average_actual_mae_return",
    "sample_status",
]

TARGET_SCENARIO_COLUMNS = [
    "diagnostic_id",
    "trade_id",
    "date",
    "primary_regime",
    "playbook_id",
    "direction",
    "ticker",
    "target_r",
    "scenario_exit_time",
    "scenario_exit_reason",
    "scenario_gross_return",
    "scenario_gross_pnl_sek",
    "scenario_cost_sek",
    "scenario_net_pnl_sek",
    "baseline_net_pnl_sek",
    "incremental_net_pnl_sek",
    "scenario_duration_minutes",
    "scenario_valid",
]

COST_SCENARIO_COLUMNS = [
    "diagnostic_id",
    "primary_regime",
    "playbook_id",
    "trades",
    "cost_bps_round_trip",
    "gross_pnl_sek",
    "modeled_cost_sek",
    "modeled_net_pnl_sek",
    "modeled_profitable",
]

LEAVE_ONE_DAY_OUT_COLUMNS = [
    "diagnostic_id",
    "primary_regime",
    "playbook_id",
    "omitted_date",
    "baseline_net_pnl_sek",
    "omitted_day_net_pnl_sek",
    "remaining_net_pnl_sek",
    "remaining_profitable",
]

PAIR_DIRECTION_COLUMNS = [
    "diagnostic_id",
    "trade_id",
    "date",
    "primary_regime",
    "playbook_id",
    "long_ticker",
    "short_ticker",
    "baseline_gross_return_same_exit",
    "baseline_gross_pnl_sek_same_exit",
    "opposite_gross_return_same_exit",
    "opposite_gross_pnl_sek_same_exit",
    "baseline_net_pnl_sek",
    "opposite_net_pnl_sek_same_exit",
    "direction_control_preference",
    "control_limitation",
]


def _num(value: object, default: float = np.nan) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if pd.isna(value):
        return False
    return bool(value)


def _profit_factor(values: Iterable[float]) -> float:
    pnl = pd.Series(list(values), dtype="float64").dropna()
    if pnl.empty:
        return np.nan
    gains = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl < 0].sum()))
    if losses == 0:
        return np.nan
    return gains / losses


def _safe_mean(values: object) -> float:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return float(series.mean()) if not series.empty else np.nan


def _safe_median(values: object) -> float:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return float(series.median()) if not series.empty else np.nan


def _entry_bucket(clock: str) -> str:
    if not clock:
        return "UNKNOWN"
    if clock < "10:00":
        return "09:45-09:59"
    if clock < "11:00":
        return "10:00-10:59"
    if clock < "12:00":
        return "11:00-11:59"
    if clock < "13:00":
        return "12:00-12:59"
    return "13:00_OR_LATER"


def _duration_bucket(minutes: float) -> str:
    if not np.isfinite(minutes):
        return "UNKNOWN"
    if minutes <= 15:
        return "0-15_MIN"
    if minutes <= 30:
        return "16-30_MIN"
    if minutes <= 60:
        return "31-60_MIN"
    if minutes <= 120:
        return "61-120_MIN"
    return "OVER_120_MIN"


def _session_lookup(prices: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    if prices.empty:
        return {}
    working = prices.copy()
    working["date_str"] = working["date"].astype(str)
    lookup: dict[tuple[str, str], pd.DataFrame] = {}
    for (date_str, ticker), group in working.groupby(["date_str", "ticker"], sort=False):
        bars = group.sort_values("datetime").copy()
        clock = bars["datetime"].dt.strftime("%H:%M")
        lookup[(str(date_str), str(ticker))] = bars[clock.ge("09:30") & clock.le("16:30")].copy()
    return lookup


def _return_for_price(side: str, entry: float, price: float) -> float:
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(price) or price <= 0:
        return np.nan
    if side.upper() == "LONG":
        return price / entry - 1.0
    return entry / price - 1.0


def _single_excursions(
    bars: pd.DataFrame,
    side: str,
    entry_time: pd.Timestamp,
    entry_price: float,
    exit_time: pd.Timestamp,
    exit_cutoff: str,
    realized_gross_return: float,
) -> dict:
    blank = {
        "actual_mfe_return": np.nan,
        "actual_mae_return": np.nan,
        "horizon_mfe_return": np.nan,
        "horizon_mae_return": np.nan,
        "horizon_close_return": np.nan,
        "entry_bar_excursion_excluded": True,
    }
    if bars is None or bars.empty:
        return blank
    clock = bars["datetime"].dt.strftime("%H:%M")
    horizon = bars[bars["datetime"].gt(entry_time) & clock.le(exit_cutoff)].copy()
    actual = horizon[horizon["datetime"].le(exit_time)].copy()

    def calc(frame: pd.DataFrame) -> tuple[float, float]:
        if frame.empty:
            return max(realized_gross_return, 0.0), min(realized_gross_return, 0.0)
        if side.upper() == "LONG":
            favorable = _return_for_price(side, entry_price, _num(frame["high"].max()))
            adverse = _return_for_price(side, entry_price, _num(frame["low"].min()))
        else:
            favorable = _return_for_price(side, entry_price, _num(frame["low"].min()))
            adverse = _return_for_price(side, entry_price, _num(frame["high"].max()))
        favorable = max(_num(favorable, 0.0), realized_gross_return, 0.0)
        adverse = min(_num(adverse, 0.0), realized_gross_return, 0.0)
        return favorable, adverse

    actual_mfe, actual_mae = calc(actual)
    horizon_mfe, horizon_mae = calc(horizon)
    horizon_close = np.nan
    if not horizon.empty:
        horizon_close = _return_for_price(side, entry_price, _num(horizon.iloc[-1].get("close")))
    elif np.isfinite(realized_gross_return):
        horizon_close = realized_gross_return
    return {
        "actual_mfe_return": actual_mfe,
        "actual_mae_return": actual_mae,
        "horizon_mfe_return": horizon_mfe,
        "horizon_mae_return": horizon_mae,
        "horizon_close_return": horizon_close,
        "entry_bar_excursion_excluded": True,
    }


def _pair_path(
    long_bars: pd.DataFrame,
    short_bars: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_long: float,
    entry_short: float,
    exit_time: pd.Timestamp,
    exit_cutoff: str,
) -> dict:
    blank = {
        "actual_mfe_return": np.nan,
        "actual_mae_return": np.nan,
        "horizon_mfe_return": np.nan,
        "horizon_mae_return": np.nan,
        "horizon_close_return": np.nan,
        "pair_opposite_same_exit_gross_return": np.nan,
        "entry_bar_excursion_excluded": False,
    }
    if long_bars is None or short_bars is None or long_bars.empty or short_bars.empty:
        return blank
    left = long_bars[["datetime", "close"]].rename(columns={"close": "long_close"})
    right = short_bars[["datetime", "close"]].rename(columns={"close": "short_close"})
    common = left.merge(right, on="datetime", how="inner").sort_values("datetime")
    clock = common["datetime"].dt.strftime("%H:%M")
    horizon = common[common["datetime"].ge(entry_time) & clock.le(exit_cutoff)].copy()
    if horizon.empty or entry_long <= 0 or entry_short <= 0:
        return blank
    horizon["pair_return"] = 0.5 * (
        horizon["long_close"] / entry_long - 1.0
        + entry_short / horizon["short_close"] - 1.0
    )
    actual = horizon[horizon["datetime"].le(exit_time)].copy()
    if actual.empty:
        actual = horizon.iloc[[0]].copy()
    actual_mfe = max(float(actual["pair_return"].max()), 0.0)
    actual_mae = min(float(actual["pair_return"].min()), 0.0)
    horizon_mfe = max(float(horizon["pair_return"].max()), 0.0)
    horizon_mae = min(float(horizon["pair_return"].min()), 0.0)
    horizon_close = float(horizon.iloc[-1]["pair_return"])
    actual_exit_return = float(actual.iloc[-1]["pair_return"])
    return {
        "actual_mfe_return": actual_mfe,
        "actual_mae_return": actual_mae,
        "horizon_mfe_return": horizon_mfe,
        "horizon_mae_return": horizon_mae,
        "horizon_close_return": horizon_close,
        "pair_opposite_same_exit_gross_return": -actual_exit_return,
        "entry_bar_excursion_excluded": False,
    }


def _standardized_target_scenarios(
    trade: pd.Series,
    bars: pd.DataFrame,
) -> list[dict]:
    rows: list[dict] = []
    if str(trade.get("idea_type")) != "SINGLE" or bars is None or bars.empty:
        return rows
    entry = _num(trade.get("entry_price"))
    stop = _num(trade.get("stop_price"))
    risk = abs(entry - stop)
    if not all(np.isfinite(x) for x in (entry, stop, risk)) or entry <= 0 or risk <= 0:
        return rows
    side = str(trade.get("direction", "")).upper()
    entry_time = pd.Timestamp(trade.get("entry_time"))
    cutoff = PLAYBOOK_EXIT_CUTOFF.get(str(trade.get("primary_regime")), "16:30")
    notional = _num(trade.get("notional_sek"), 0.0)
    baseline_net = _num(trade.get("net_pnl_sek"), 0.0)
    cost = _num(trade.get("cost_sek"), notional * ROUND_TRIP_COST_RATE)
    for target_r in TARGET_R_SCENARIOS:
        target = entry + target_r * risk if side == "LONG" else entry - target_r * risk
        execution = _directional_execution(
            bars=bars,
            side=side,
            entry_time=entry_time,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            exit_cutoff=cutoff,
        )
        valid = execution is not None
        gross_return = execution.gross_return if valid else np.nan
        gross_pnl = gross_return * notional if valid else np.nan
        net_pnl = gross_pnl - cost if valid else np.nan
        rows.append(
            {
                "diagnostic_id": DIAGNOSTIC_ID,
                "trade_id": trade.get("trade_id"),
                "date": str(trade.get("date")),
                "primary_regime": trade.get("primary_regime"),
                "playbook_id": trade.get("playbook_id"),
                "direction": side,
                "ticker": trade.get("ticker"),
                "target_r": target_r,
                "scenario_exit_time": execution.exit_time.strftime("%Y-%m-%d %H:%M:%S") if valid else "",
                "scenario_exit_reason": execution.exit_reason if valid else "INVALID",
                "scenario_gross_return": gross_return,
                "scenario_gross_pnl_sek": gross_pnl,
                "scenario_cost_sek": cost if valid else np.nan,
                "scenario_net_pnl_sek": net_pnl,
                "baseline_net_pnl_sek": baseline_net,
                "incremental_net_pnl_sek": net_pnl - baseline_net if valid else np.nan,
                "scenario_duration_minutes": execution.duration_minutes if valid else np.nan,
                "scenario_valid": valid,
            }
        )
    return rows


def build_trade_diagnostics(
    trades: pd.DataFrame,
    sessions: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if trades.empty:
        return (
            pd.DataFrame(columns=TRADE_DIAGNOSTIC_COLUMNS),
            pd.DataFrame(columns=TARGET_SCENARIO_COLUMNS),
            pd.DataFrame(columns=PAIR_DIRECTION_COLUMNS),
        )
    lookup = _session_lookup(prices)
    session_meta = sessions[["date", "regime_confidence", "confidence_band"]].copy() if not sessions.empty else pd.DataFrame(columns=["date", "regime_confidence", "confidence_band"])
    session_meta["date"] = session_meta["date"].astype(str)
    session_meta = session_meta.drop_duplicates("date")
    working = trades.copy()
    working["date"] = working["date"].astype(str)
    working = working.merge(session_meta, on="date", how="left")

    detail_rows: list[dict] = []
    target_rows: list[dict] = []
    pair_rows: list[dict] = []
    for _, trade in working.iterrows():
        date = str(trade.get("date"))
        regime = str(trade.get("primary_regime"))
        idea_type = str(trade.get("idea_type"))
        entry_time = pd.Timestamp(trade.get("entry_time"))
        exit_time = pd.Timestamp(trade.get("exit_time"))
        cutoff = PLAYBOOK_EXIT_CUTOFF.get(regime, "16:30")
        notional = _num(trade.get("notional_sek"), 0.0)
        realized = _num(trade.get("gross_return"), 0.0)
        path: dict
        source_available = False
        if idea_type == "SINGLE":
            ticker = str(trade.get("ticker"))
            bars = lookup.get((date, ticker), pd.DataFrame())
            source_available = not bars.empty
            path = _single_excursions(
                bars=bars,
                side=str(trade.get("direction")),
                entry_time=entry_time,
                entry_price=_num(trade.get("entry_price")),
                exit_time=exit_time,
                exit_cutoff=cutoff,
                realized_gross_return=realized,
            )
            target_rows.extend(_standardized_target_scenarios(trade, bars))
        else:
            long_ticker = str(trade.get("long_ticker"))
            short_ticker = str(trade.get("short_ticker"))
            long_bars = lookup.get((date, long_ticker), pd.DataFrame())
            short_bars = lookup.get((date, short_ticker), pd.DataFrame())
            source_available = not long_bars.empty and not short_bars.empty
            path = _pair_path(
                long_bars=long_bars,
                short_bars=short_bars,
                entry_time=entry_time,
                entry_long=_num(trade.get("pair_entry_long_price")),
                entry_short=_num(trade.get("pair_entry_short_price")),
                exit_time=exit_time,
                exit_cutoff=cutoff,
            )
            opposite_return = _num(path.get("pair_opposite_same_exit_gross_return"))
            opposite_gross = opposite_return * notional if np.isfinite(opposite_return) else np.nan
            cost = _num(trade.get("cost_sek"), 0.0)
            pair_rows.append(
                {
                    "diagnostic_id": DIAGNOSTIC_ID,
                    "trade_id": trade.get("trade_id"),
                    "date": date,
                    "primary_regime": regime,
                    "playbook_id": trade.get("playbook_id"),
                    "long_ticker": long_ticker,
                    "short_ticker": short_ticker,
                    "baseline_gross_return_same_exit": realized,
                    "baseline_gross_pnl_sek_same_exit": _num(trade.get("gross_pnl_sek"), realized * notional),
                    "opposite_gross_return_same_exit": opposite_return,
                    "opposite_gross_pnl_sek_same_exit": opposite_gross,
                    "baseline_net_pnl_sek": _num(trade.get("net_pnl_sek")),
                    "opposite_net_pnl_sek_same_exit": opposite_gross - cost if np.isfinite(opposite_gross) else np.nan,
                    "direction_control_preference": (
                        "OPPOSITE_DIRECTION_BETTER_SAME_EXIT"
                        if np.isfinite(opposite_gross) and opposite_gross > _num(trade.get("gross_pnl_sek"))
                        else "BASELINE_DIRECTION_BETTER_OR_EQUAL_SAME_EXIT"
                    ),
                    "control_limitation": "Same entry and exit timestamps only; this does not re-simulate opposite-direction stop and target rules.",
                }
            )

        actual_mfe = _num(path.get("actual_mfe_return"))
        actual_mae = _num(path.get("actual_mae_return"))
        horizon_mfe = _num(path.get("horizon_mfe_return"))
        horizon_mae = _num(path.get("horizon_mae_return"))
        horizon_close = _num(path.get("horizon_close_return"))
        risk_per_share = _num(trade.get("risk_per_share"))
        entry_price = _num(trade.get("entry_price"))
        risk_return = risk_per_share / entry_price if np.isfinite(risk_per_share) and np.isfinite(entry_price) and entry_price > 0 else np.nan
        actual_mfe_r = actual_mfe / risk_return if np.isfinite(actual_mfe) and np.isfinite(risk_return) and risk_return > 0 else np.nan
        actual_mae_r = actual_mae / risk_return if np.isfinite(actual_mae) and np.isfinite(risk_return) and risk_return > 0 else np.nan
        stopped = "STOP" in str(trade.get("exit_reason", ""))
        diagnostic_pass = source_available and np.isfinite(actual_mfe) and np.isfinite(actual_mae) and np.isfinite(horizon_close)
        gross_capture = realized / actual_mfe if np.isfinite(actual_mfe) and actual_mfe > 0 else np.nan
        detail_rows.append(
            {
                "diagnostic_id": DIAGNOSTIC_ID,
                "trade_id": trade.get("trade_id"),
                "idea_id": trade.get("idea_id"),
                "date": date,
                "primary_regime": regime,
                "playbook_id": trade.get("playbook_id"),
                "idea_type": idea_type,
                "direction": trade.get("direction"),
                "ticker": trade.get("ticker"),
                "paired_ticker": trade.get("paired_ticker"),
                "long_ticker": trade.get("long_ticker"),
                "short_ticker": trade.get("short_ticker"),
                "regime_confidence": _num(trade.get("regime_confidence")),
                "confidence_band": trade.get("confidence_band"),
                "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "entry_clock": entry_time.strftime("%H:%M"),
                "entry_time_bucket": _entry_bucket(entry_time.strftime("%H:%M")),
                "exit_time": exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_reason": trade.get("exit_reason"),
                "trade_duration_minutes": _num(trade.get("trade_duration_minutes")),
                "duration_bucket": _duration_bucket(_num(trade.get("trade_duration_minutes"))),
                "notional_sek": notional,
                "gross_return": realized,
                "gross_pnl_sek": _num(trade.get("gross_pnl_sek")),
                "cost_sek": _num(trade.get("cost_sek")),
                "net_pnl_sek": _num(trade.get("net_pnl_sek")),
                "winning_trade": _num(trade.get("net_pnl_sek"), 0.0) > 0,
                "risk_per_share": risk_per_share,
                "r_multiple_achieved": _num(trade.get("r_multiple_achieved")),
                "actual_mfe_return": actual_mfe,
                "actual_mae_return": actual_mae,
                "actual_mfe_pnl_sek": actual_mfe * notional if np.isfinite(actual_mfe) else np.nan,
                "actual_mae_pnl_sek": actual_mae * notional if np.isfinite(actual_mae) else np.nan,
                "actual_mfe_r": actual_mfe_r,
                "actual_mae_r": actual_mae_r,
                "horizon_mfe_return": horizon_mfe,
                "horizon_mae_return": horizon_mae,
                "horizon_close_return": horizon_close,
                "horizon_close_gross_pnl_sek": horizon_close * notional if np.isfinite(horizon_close) else np.nan,
                "stopped_then_positive_by_cutoff": bool(stopped and np.isfinite(horizon_close) and horizon_close > 0),
                "stopped_then_reached_half_r_by_cutoff": bool(stopped and np.isfinite(horizon_mfe) and np.isfinite(risk_return) and risk_return > 0 and horizon_mfe >= 0.5 * risk_return),
                "gross_capture_of_actual_mfe": gross_capture,
                "pair_opposite_same_exit_gross_return": _num(path.get("pair_opposite_same_exit_gross_return")),
                "pair_opposite_same_exit_gross_pnl_sek": _num(path.get("pair_opposite_same_exit_gross_return")) * notional if np.isfinite(_num(path.get("pair_opposite_same_exit_gross_return"))) else np.nan,
                "entry_bar_excursion_excluded": _bool(path.get("entry_bar_excursion_excluded")),
                "point_in_time_pass": _bool(trade.get("point_in_time_pass")),
                "diagnostic_pass": diagnostic_pass,
                "diagnostic_status": "ENRICHED" if diagnostic_pass else "MISSING_OR_INVALID_PRICE_PATH",
            }
        )

    return (
        pd.DataFrame(detail_rows, columns=TRADE_DIAGNOSTIC_COLUMNS),
        pd.DataFrame(target_rows, columns=TARGET_SCENARIO_COLUMNS),
        pd.DataFrame(pair_rows, columns=PAIR_DIRECTION_COLUMNS),
    )


def _aggregate_metrics(group: pd.DataFrame) -> dict:
    pnl = pd.to_numeric(group.get("net_pnl_sek"), errors="coerce").dropna()
    gross = pd.to_numeric(group.get("gross_pnl_sek"), errors="coerce").fillna(0.0)
    cost = pd.to_numeric(group.get("cost_sek"), errors="coerce").fillna(0.0)
    return {
        "trades": len(group),
        "winning_trades": int((pnl > 0).sum()),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "gross_pnl_sek": float(gross.sum()),
        "cost_sek": float(cost.sum()),
        "net_pnl_sek": float(pnl.sum()),
        "average_net_pnl_sek": float(pnl.mean()) if len(pnl) else np.nan,
        "median_net_pnl_sek": float(pnl.median()) if len(pnl) else np.nan,
        "profit_factor": _profit_factor(pnl),
        "average_actual_mfe_return": _safe_mean(group.get("actual_mfe_return", [])),
        "average_actual_mae_return": _safe_mean(group.get("actual_mae_return", [])),
    }


def build_slices(trade_diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    if trade_diagnostics.empty:
        return pd.DataFrame(columns=SLICE_COLUMNS)
    working = trade_diagnostics.copy()
    working["ticker_or_pair"] = np.where(
        working["idea_type"].eq("PAIR"),
        working["long_ticker"].astype(str) + " / " + working["short_ticker"].astype(str),
        working["ticker"].astype(str),
    )
    dimensions = {
        "EXIT_REASON": "exit_reason",
        "DIRECTION": "direction",
        "CONFIDENCE_BAND": "confidence_band",
        "ENTRY_TIME_BUCKET": "entry_time_bucket",
        "DURATION_BUCKET": "duration_bucket",
        "TICKER_OR_PAIR": "ticker_or_pair",
    }
    for (regime, playbook_id), playbook_group in working.groupby(["primary_regime", "playbook_id"], dropna=False):
        for dimension, column in dimensions.items():
            for bucket, group in playbook_group.groupby(column, dropna=False):
                metrics = _aggregate_metrics(group)
                rows.append(
                    {
                        "diagnostic_id": DIAGNOSTIC_ID,
                        "primary_regime": regime,
                        "playbook_id": playbook_id,
                        "dimension": dimension,
                        "bucket": str(bucket),
                        **metrics,
                        "sample_status": "ENOUGH_FOR_SCREENING" if len(group) >= MINIMUM_INFERENCE_TRADES else "SMALL_SLICE_DESCRIPTIVE_ONLY",
                    }
                )
    return pd.DataFrame(rows, columns=SLICE_COLUMNS)


def build_cost_scenarios(trade_diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for regime, spec in PLAYBOOKS.items():
        group = trade_diagnostics[trade_diagnostics["primary_regime"].eq(regime)] if not trade_diagnostics.empty else pd.DataFrame()
        gross = pd.to_numeric(group.get("gross_pnl_sek"), errors="coerce").sum() if not group.empty else 0.0
        total_notional = pd.to_numeric(group.get("notional_sek"), errors="coerce").sum() if not group.empty else 0.0
        for bps in COST_BPS_SCENARIOS:
            modeled_cost = total_notional * bps / 10000.0
            net = gross - modeled_cost
            rows.append(
                {
                    "diagnostic_id": DIAGNOSTIC_ID,
                    "primary_regime": regime,
                    "playbook_id": spec.playbook_id,
                    "trades": len(group),
                    "cost_bps_round_trip": bps,
                    "gross_pnl_sek": gross,
                    "modeled_cost_sek": modeled_cost,
                    "modeled_net_pnl_sek": net,
                    "modeled_profitable": net > 0,
                }
            )
    return pd.DataFrame(rows, columns=COST_SCENARIO_COLUMNS)


def build_leave_one_day_out(trade_diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    if trade_diagnostics.empty:
        return pd.DataFrame(columns=LEAVE_ONE_DAY_OUT_COLUMNS)
    for (regime, playbook_id), group in trade_diagnostics.groupby(["primary_regime", "playbook_id"]):
        baseline = pd.to_numeric(group["net_pnl_sek"], errors="coerce").sum()
        daily = group.groupby("date")["net_pnl_sek"].sum()
        for date, day_pnl in daily.items():
            remaining = baseline - day_pnl
            rows.append(
                {
                    "diagnostic_id": DIAGNOSTIC_ID,
                    "primary_regime": regime,
                    "playbook_id": playbook_id,
                    "omitted_date": str(date),
                    "baseline_net_pnl_sek": baseline,
                    "omitted_day_net_pnl_sek": day_pnl,
                    "remaining_net_pnl_sek": remaining,
                    "remaining_profitable": remaining > 0,
                }
            )
    return pd.DataFrame(rows, columns=LEAVE_ONE_DAY_OUT_COLUMNS)


def _best_target(targets: pd.DataFrame, regime: str) -> tuple[float, float]:
    group = targets[targets["primary_regime"].eq(regime) & targets["scenario_valid"].fillna(False).astype(bool)] if not targets.empty else pd.DataFrame()
    if group.empty:
        return np.nan, np.nan
    agg = group.groupby("target_r", as_index=False)["scenario_net_pnl_sek"].sum()
    row = agg.sort_values(["scenario_net_pnl_sek", "target_r"], ascending=[False, True]).iloc[0]
    return _num(row["target_r"]), _num(row["scenario_net_pnl_sek"])


def _concentration(group: pd.DataFrame) -> tuple[float, float]:
    if group.empty:
        return np.nan, np.nan
    pnl = pd.to_numeric(group["net_pnl_sek"], errors="coerce").fillna(0.0)
    abs_total = abs(float(pnl.sum()))
    if abs_total <= 1e-12:
        abs_total = float(pnl.abs().sum())
    if abs_total <= 1e-12:
        return np.nan, np.nan
    top_trade = float(pnl.abs().max()) / abs_total
    daily = group.groupby("date")["net_pnl_sek"].sum()
    top_day = float(daily.abs().max()) / abs_total
    return top_trade, top_day


def _recommendation(
    trades: int,
    gross: float,
    net: float,
    cost: float,
    win_rate: float,
    profit_factor: float,
    median_mfe_r: float,
    best_target_net: float,
    opposite_pair_gross: float,
) -> tuple[str, str, str]:
    if trades < MINIMUM_INFERENCE_TRADES:
        return (
            "INSUFFICIENT_SAMPLE",
            "LOW",
            f"Only {trades} trades; retain as a research candidate but do not infer edge or select a final strategy.",
        )
    if np.isfinite(opposite_pair_gross) and opposite_pair_gross > max(gross + max(cost, 0.0), 0.0):
        return (
            "INVERT",
            "MEDIUM",
            "The opposite long-short direction was materially better at the same entry and exit timestamps; run a fully re-simulated inversion control before promotion.",
        )
    if gross > 0 and net > 0 and (not np.isfinite(profit_factor) or profit_factor >= 1.10):
        return (
            "KEEP",
            "MEDIUM",
            "Baseline is positive after modeled costs. Keep unchanged for robustness and out-of-sample validation before any promotion.",
        )
    if gross > 0 and net <= 0:
        return (
            "MODIFY",
            "MEDIUM",
            "Raw signal is positive but does not clear costs; focus on selectivity, turnover, stop asymmetry, and expected-edge filters.",
        )
    if np.isfinite(best_target_net) and best_target_net > net + max(cost, 1.0):
        return (
            "MODIFY",
            "MEDIUM",
            "Standardized target diagnostics materially improve the baseline, suggesting exit geometry is a major loss driver rather than complete signal absence.",
        )
    if np.isfinite(median_mfe_r) and median_mfe_r >= 0.75:
        return (
            "MODIFY",
            "MEDIUM",
            "Trades commonly develop useful favorable excursion but fail to retain it; investigate entry confirmation, stop placement, profit-taking, and time exits.",
        )
    if np.isfinite(win_rate) and win_rate < 0.35 and np.isfinite(profit_factor) and profit_factor < 0.50 and gross < 0:
        return (
            "REPLACE",
            "MEDIUM",
            "The baseline has a low win rate, weak payoff ratio, and negative gross result; test a different regime response rather than local parameter tuning.",
        )
    return (
        "MODIFY",
        "LOW",
        "The baseline is not positive, but diagnostics do not yet isolate a decisive inversion or replacement case. Modify one hypothesis at a time and re-test.",
    )


def build_playbook_diagnostics(
    trade_diagnostics: pd.DataFrame,
    sessions: pd.DataFrame,
    targets: pd.DataFrame,
    leave_one_out: pd.DataFrame,
    pair_controls: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    for regime in REGIMES:
        spec = PLAYBOOKS[regime]
        group = trade_diagnostics[trade_diagnostics["primary_regime"].eq(regime)] if not trade_diagnostics.empty else pd.DataFrame(columns=TRADE_DIAGNOSTIC_COLUMNS)
        regime_sessions = int(sessions["primary_regime"].eq(regime).sum()) if not sessions.empty else 0
        pnl = pd.to_numeric(group.get("net_pnl_sek"), errors="coerce").dropna()
        gross = float(pd.to_numeric(group.get("gross_pnl_sek"), errors="coerce").fillna(0.0).sum()) if not group.empty else 0.0
        cost = float(pd.to_numeric(group.get("cost_sek"), errors="coerce").fillna(0.0).sum()) if not group.empty else 0.0
        net = float(pnl.sum()) if len(pnl) else 0.0
        wins = int((pnl > 0).sum())
        losses = int((pnl <= 0).sum())
        win_rate = float((pnl > 0).mean()) if len(pnl) else np.nan
        pf = _profit_factor(pnl)
        exit_reason = group.get("exit_reason", pd.Series(dtype="object")).astype(str)
        target_hit_rate = float(exit_reason.str.contains("TARGET").mean()) if len(group) else np.nan
        stop_hit_rate = float(exit_reason.str.contains("STOP").mean()) if len(group) else np.nan
        time_exit_rate = float(exit_reason.eq("TIME_EXIT").mean()) if len(group) else np.nan
        stopped = group[exit_reason.str.contains("STOP")] if len(group) else group
        stopped_positive = int(stopped.get("stopped_then_positive_by_cutoff", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if len(stopped) else 0
        stopped_positive_rate = stopped_positive / len(stopped) if len(stopped) else np.nan
        total_notional = float(pd.to_numeric(group.get("notional_sek"), errors="coerce").fillna(0.0).sum()) if len(group) else 0.0
        break_even_bps = gross / total_notional * 10000.0 if gross > 0 and total_notional > 0 else 0.0
        best_target_r, best_target_net = _best_target(targets, regime)
        pair_opposite = float(pd.to_numeric(pair_controls.loc[pair_controls["primary_regime"].eq(regime), "opposite_gross_pnl_sek_same_exit"], errors="coerce").sum()) if not pair_controls.empty else np.nan
        if not pair_controls.empty and pair_controls["primary_regime"].eq(regime).sum() == 0:
            pair_opposite = np.nan
        top_trade, top_day = _concentration(group)
        loo_group = leave_one_out[leave_one_out["primary_regime"].eq(regime)] if not leave_one_out.empty else pd.DataFrame()
        loo_share = float(loo_group["remaining_profitable"].fillna(False).astype(bool).mean()) if not loo_group.empty else np.nan
        loo_min = float(pd.to_numeric(loo_group["remaining_net_pnl_sek"], errors="coerce").min()) if not loo_group.empty else np.nan
        median_mfe_r = _safe_median(group.get("actual_mfe_r", [])) if len(group) else np.nan
        recommendation, recommendation_confidence, rationale = _recommendation(
            trades=len(group),
            gross=gross,
            net=net,
            cost=cost,
            win_rate=win_rate,
            profit_factor=pf,
            median_mfe_r=median_mfe_r,
            best_target_net=best_target_net,
            opposite_pair_gross=pair_opposite,
        )
        rows.append(
            {
                "diagnostic_id": DIAGNOSTIC_ID,
                "primary_regime": regime,
                "playbook_id": spec.playbook_id,
                "regime_sessions": regime_sessions,
                "trades": len(group),
                "sessions_with_trades": int(group["date"].nunique()) if len(group) else 0,
                "sample_status": "MINIMUM_SCREENING_SAMPLE" if len(group) >= MINIMUM_INFERENCE_TRADES else "TOO_FEW_TRADES_FOR_INFERENCE",
                "winning_trades": wins,
                "losing_trades": losses,
                "win_rate": win_rate,
                "gross_pnl_sek_unconstrained": gross,
                "cost_sek_unconstrained": cost,
                "net_pnl_sek_unconstrained": net,
                "average_net_pnl_sek": float(pnl.mean()) if len(pnl) else np.nan,
                "median_net_pnl_sek": float(pnl.median()) if len(pnl) else np.nan,
                "profit_factor": pf,
                "target_hit_rate": target_hit_rate,
                "stop_hit_rate": stop_hit_rate,
                "time_exit_rate": time_exit_rate,
                "average_actual_mfe_return": _safe_mean(group.get("actual_mfe_return", [])) if len(group) else np.nan,
                "average_actual_mae_return": _safe_mean(group.get("actual_mae_return", [])) if len(group) else np.nan,
                "median_actual_mfe_r": median_mfe_r,
                "median_actual_mae_r": _safe_median(group.get("actual_mae_r", [])) if len(group) else np.nan,
                "average_gross_capture_of_mfe": _safe_mean(pd.to_numeric(group.get("gross_capture_of_actual_mfe", pd.Series(dtype="float64")), errors="coerce").replace([np.inf, -np.inf], np.nan)) if len(group) else np.nan,
                "stopped_trades": len(stopped),
                "stopped_then_positive_by_cutoff": stopped_positive,
                "stopped_then_positive_rate": stopped_positive_rate,
                "break_even_round_trip_cost_bps": break_even_bps,
                "best_standardized_target_r": best_target_r,
                "best_standardized_target_net_pnl_sek": best_target_net,
                "pair_opposite_same_exit_gross_pnl_sek": pair_opposite,
                "top_trade_abs_pnl_share": top_trade,
                "top_day_abs_pnl_share": top_day,
                "leave_one_day_out_profitable_share": loo_share,
                "leave_one_day_out_min_pnl_sek": loo_min,
                "recommended_action": recommendation,
                "recommendation_confidence": recommendation_confidence,
                "diagnostic_rationale": rationale,
            }
        )
    return pd.DataFrame(rows, columns=PLAYBOOK_DIAGNOSTIC_COLUMNS)


def build_summary(
    baseline_summary: pd.DataFrame,
    trade_diagnostics: pd.DataFrame,
    playbook_diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    source = baseline_summary.iloc[0] if not baseline_summary.empty else pd.Series(dtype="object")
    actions = playbook_diagnostics["recommended_action"].value_counts() if not playbook_diagnostics.empty else pd.Series(dtype="int64")
    all_enriched = len(trade_diagnostics) > 0 and bool(trade_diagnostics["diagnostic_pass"].fillna(False).astype(bool).all())
    all_pit = len(trade_diagnostics) > 0 and bool(trade_diagnostics["point_in_time_pass"].fillna(False).astype(bool).all())
    failures = int((~trade_diagnostics["diagnostic_pass"].fillna(False).astype(bool)).sum()) if not trade_diagnostics.empty else int(_num(source.get("triggered_trades"), 0))
    classification = (
        "LOSS_DRIVERS_DIAGNOSTIC_READY_FOR_PLAYBOOK_REDESIGN"
        if all_enriched and all_pit and failures == 0
        else "LOSS_DIAGNOSTIC_DATA_GAPS_REQUIRE_REVIEW"
    )
    return pd.DataFrame(
        [
            {
                "diagnostic_id": DIAGNOSTIC_ID,
                "research_status": RESEARCH_STATUS,
                "source_simulation_id": source.get("simulation_id", ""),
                "source_sessions": int(_num(source.get("processed_sessions"), 0)),
                "source_trades": int(_num(source.get("triggered_trades"), len(trade_diagnostics))),
                "enriched_trades": int(trade_diagnostics["diagnostic_pass"].fillna(False).astype(bool).sum()) if not trade_diagnostics.empty else 0,
                "single_trades": int(trade_diagnostics["idea_type"].eq("SINGLE").sum()) if not trade_diagnostics.empty else 0,
                "paired_trades": int(trade_diagnostics["idea_type"].eq("PAIR").sum()) if not trade_diagnostics.empty else 0,
                "playbooks_evaluated": len(playbook_diagnostics),
                "playbooks_with_minimum_sample": int(playbook_diagnostics["trades"].ge(MINIMUM_INFERENCE_TRADES).sum()) if not playbook_diagnostics.empty else 0,
                "positive_gross_playbooks": int(playbook_diagnostics["gross_pnl_sek_unconstrained"].gt(0).sum()) if not playbook_diagnostics.empty else 0,
                "positive_net_playbooks": int(playbook_diagnostics["net_pnl_sek_unconstrained"].gt(0).sum()) if not playbook_diagnostics.empty else 0,
                "keep_recommendations": int(actions.get("KEEP", 0)),
                "modify_recommendations": int(actions.get("MODIFY", 0)),
                "invert_recommendations": int(actions.get("INVERT", 0)),
                "replace_recommendations": int(actions.get("REPLACE", 0)),
                "insufficient_sample_recommendations": int(actions.get("INSUFFICIENT_SAMPLE", 0)),
                "gross_pnl_sek_unconstrained": _num(source.get("gross_pnl_sek_unconstrained"), trade_diagnostics["gross_pnl_sek"].sum() if not trade_diagnostics.empty else 0.0),
                "cost_sek_unconstrained": _num(source.get("cost_sek_unconstrained"), trade_diagnostics["cost_sek"].sum() if not trade_diagnostics.empty else 0.0),
                "net_pnl_sek_unconstrained": _num(source.get("net_pnl_sek_unconstrained"), trade_diagnostics["net_pnl_sek"].sum() if not trade_diagnostics.empty else 0.0),
                "all_source_trades_point_in_time_safe": all_pit,
                "all_trades_enriched": all_enriched,
                "diagnostic_invariant_failures": failures,
                "classification": classification,
            }
        ],
        columns=SUMMARY_COLUMNS,
    )


def build_loss_diagnostics(
    baseline_summary: pd.DataFrame,
    sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    legs: pd.DataFrame,
    baseline_performance: pd.DataFrame,
    prices: pd.DataFrame,
):
    del candidates, legs, baseline_performance  # source files are validated upstream; Step 9C diagnoses closed trades.
    trade_diagnostics, target_scenarios, pair_controls = build_trade_diagnostics(trades, sessions, prices)
    slices = build_slices(trade_diagnostics)
    cost_scenarios = build_cost_scenarios(trade_diagnostics)
    leave_one_out = build_leave_one_day_out(trade_diagnostics)
    playbook_diagnostics = build_playbook_diagnostics(
        trade_diagnostics=trade_diagnostics,
        sessions=sessions,
        targets=target_scenarios,
        leave_one_out=leave_one_out,
        pair_controls=pair_controls,
    )
    summary = build_summary(baseline_summary, trade_diagnostics, playbook_diagnostics)
    return (
        summary,
        trade_diagnostics,
        playbook_diagnostics,
        slices,
        target_scenarios,
        cost_scenarios,
        leave_one_out,
        pair_controls,
    )


def run_loss_diagnostics(
    baseline_summary_file: Path = BASELINE_SUMMARY_FILE,
    sessions_file: Path = SESSION_FILE,
    candidates_file: Path = CANDIDATE_FILE,
    trades_file: Path = TRADE_FILE,
    legs_file: Path = LEG_FILE,
    performance_file: Path = PERFORMANCE_FILE,
    db_path: Path = INTRADAY_DB,
):
    required = [
        baseline_summary_file,
        sessions_file,
        candidates_file,
        trades_file,
        legs_file,
        performance_file,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Step 9B output(s): " + ", ".join(missing))
    baseline_summary = pd.read_csv(baseline_summary_file)
    sessions = pd.read_csv(sessions_file)
    candidates = pd.read_csv(candidates_file)
    trades = pd.read_csv(trades_file)
    legs = pd.read_csv(legs_file)
    performance = pd.read_csv(performance_file)
    prices = load_intraday_prices(db_path)
    return build_loss_diagnostics(
        baseline_summary,
        sessions,
        candidates,
        trades,
        legs,
        performance,
        prices,
    )


def main() -> None:
    print("\n=== STEP 9C PLAYBOOK LOSS-DRIVER DIAGNOSTICS ===")
    print(f"Diagnostic       : {DIAGNOSTIC_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Minimum sample   : {MINIMUM_INFERENCE_TRADES} trades for screening")
    print("This step diagnoses loss sources; it does not optimize parameters or promote strategies.")

    outputs = run_loss_diagnostics()
    paths = [
        SUMMARY_FILE,
        TRADE_DIAGNOSTIC_FILE,
        PLAYBOOK_DIAGNOSTIC_FILE,
        SLICE_FILE,
        TARGET_SCENARIO_FILE,
        COST_SCENARIO_FILE,
        LEAVE_ONE_DAY_OUT_FILE,
        PAIR_DIRECTION_FILE,
    ]
    for dataframe, path in zip(outputs, paths):
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")

    summary = outputs[0].iloc[0]
    print("\n=== STEP 9C LOSS-DIAGNOSTIC RESULT ===")
    print(f"Source / enriched trades      : {int(summary['source_trades'])}/{int(summary['enriched_trades'])}")
    print(f"Single / paired trades        : {int(summary['single_trades'])}/{int(summary['paired_trades'])}")
    print(f"Playbooks evaluated           : {int(summary['playbooks_evaluated'])}")
    print(f"Minimum-sample playbooks      : {int(summary['playbooks_with_minimum_sample'])}")
    print(f"Positive gross / net          : {int(summary['positive_gross_playbooks'])}/{int(summary['positive_net_playbooks'])}")
    print(
        "Actions KEEP/MODIFY/INVERT/REPLACE/INSUFFICIENT: "
        f"{int(summary['keep_recommendations'])}/"
        f"{int(summary['modify_recommendations'])}/"
        f"{int(summary['invert_recommendations'])}/"
        f"{int(summary['replace_recommendations'])}/"
        f"{int(summary['insufficient_sample_recommendations'])}"
    )
    print(f"Diagnostic invariant failures: {int(summary['diagnostic_invariant_failures'])}")
    print(f"Classification                : {summary['classification']}")
    print("Step 9C export complete. Review playbook_diagnostics before designing controlled alternatives.")


if __name__ == "__main__":
    main()
