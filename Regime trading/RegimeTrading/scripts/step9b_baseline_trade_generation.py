from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, legacy_output_path
from RegimeTrading.core.research_config import (
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_POSITION_SIZE,
)
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    GAP_RECOVERY_TICKERS,
    build_daily_reference,
    load_intraday_prices,
)
from RegimeTrading.scripts.step8_provisional_regime_taxonomy import REGIMES
from RegimeTrading.scripts.step9_playbook_specifications import PLAYBOOKS


SIMULATION_ID = "REGIME_PLAYBOOK_BASELINE_TRADE_GENERATION_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_BASELINE_MECHANICAL_DIAGNOSTIC"
DECISION_TIME = "09:45"
LATEST_ROUTER_BAR_LABEL = "09:40"
EXECUTION_OBSERVATION_START = "09:45"
BAR_INTERVAL_MINUTES = 5
BASELINE_NOTIONAL_SEK = float(ORB_INITIAL_CAPITAL) * float(ORB_POSITION_SIZE)
ROUND_TRIP_COST_RATE = float(ORB_COST_PER_TRADE)
MAX_DIRECTIONAL_RISK_PCT = 0.03
MIN_HIGH_DISPERSION_SPREAD = 0.0030
MIN_DEFENSIVE_SPREAD = 0.0010

TAXONOMY_FILE = legacy_output_path("regime_daily_taxonomy.csv")
COVERAGE_FILE = legacy_output_path("regime_playbook_session_coverage.csv")

SUMMARY_FILE = legacy_output_path("regime_playbook_baseline_summary.csv")
SESSION_FILE = legacy_output_path("regime_playbook_baseline_sessions.csv")
CANDIDATE_FILE = legacy_output_path("regime_playbook_baseline_candidates.csv")
TRADE_FILE = legacy_output_path("regime_playbook_baseline_trades.csv")
LEG_FILE = legacy_output_path("regime_playbook_baseline_trade_legs.csv")
PERFORMANCE_FILE = legacy_output_path("regime_playbook_baseline_performance.csv")
AUDIT_FILE = legacy_output_path("regime_playbook_baseline_audit.csv")

SUMMARY_COLUMNS = [
    "simulation_id",
    "research_status",
    "decision_time",
    "latest_router_bar_label",
    "execution_observation_start",
    "taxonomy_sessions",
    "processed_sessions",
    "active_response_sessions",
    "observed_regimes",
    "specified_playbooks",
    "regimes_with_selected_ideas",
    "regimes_with_triggered_trades",
    "candidate_rows",
    "selected_ideas",
    "triggered_trades",
    "closed_trades",
    "sessions_with_triggered_trades",
    "sessions_active_no_trigger",
    "sessions_active_no_valid_setup",
    "single_leg_trades",
    "paired_trades",
    "long_legs",
    "short_legs",
    "gross_pnl_sek_unconstrained",
    "cost_sek_unconstrained",
    "net_pnl_sek_unconstrained",
    "win_rate",
    "profit_factor",
    "point_in_time_audit_pass_sessions",
    "point_in_time_audit_fail_sessions",
    "execution_invariant_failures",
    "trade_leg_reconciliation_max_abs_diff_sek",
    "all_observed_regimes_processed",
    "classification",
]

SESSION_COLUMNS = [
    "simulation_id",
    "date",
    "primary_regime",
    "playbook_id",
    "regime_confidence",
    "confidence_band",
    "direction_bias",
    "research_risk_multiplier",
    "max_concurrent_ideas",
    "input_tickers",
    "candidate_rows",
    "valid_setup_candidates",
    "selected_ideas",
    "triggered_trades",
    "closed_trades",
    "winning_trades",
    "losing_trades",
    "gross_pnl_sek_unconstrained",
    "cost_sek_unconstrained",
    "net_pnl_sek_unconstrained",
    "minimum_entry_time",
    "maximum_exit_time",
    "max_router_source_label",
    "point_in_time_session_pass",
    "execution_invariant_pass",
    "session_status",
]

CANDIDATE_COLUMNS = [
    "simulation_id",
    "date",
    "primary_regime",
    "playbook_id",
    "idea_id",
    "idea_type",
    "selection_rank",
    "selected_for_simulation",
    "setup_status",
    "trigger_status",
    "invalid_reason",
    "direction",
    "ticker",
    "paired_ticker",
    "long_ticker",
    "short_ticker",
    "ranking_metric",
    "cutoff_return_from_open",
    "paired_cutoff_return_from_open",
    "opening_gap",
    "previous_close",
    "early_open",
    "early_high",
    "early_low",
    "early_midpoint",
    "early_range_pct",
    "signal_time",
    "entry_time",
    "entry_price",
    "stop_price",
    "target_price",
    "pair_entry_long_price",
    "pair_entry_short_price",
    "pair_stop_return",
    "pair_target_return",
    "exit_time",
    "exit_price",
    "pair_exit_long_price",
    "pair_exit_short_price",
    "exit_reason",
    "gross_return",
    "net_return",
    "notional_sek",
    "gross_pnl_sek",
    "cost_sek",
    "net_pnl_sek",
    "trade_duration_minutes",
    "max_router_source_label",
    "point_in_time_pass",
    "execution_observation_start",
    "same_bar_priority",
    "mechanical_interpretation",
]

TRADE_COLUMNS = [
    "simulation_id",
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
    "entry_time",
    "entry_price",
    "stop_price",
    "target_price",
    "pair_entry_long_price",
    "pair_entry_short_price",
    "pair_stop_return",
    "pair_target_return",
    "exit_time",
    "exit_price",
    "pair_exit_long_price",
    "pair_exit_short_price",
    "exit_reason",
    "gross_return",
    "net_return",
    "notional_sek",
    "gross_pnl_sek",
    "cost_sek",
    "net_pnl_sek",
    "account_return",
    "trade_duration_minutes",
    "risk_per_share",
    "r_multiple_achieved",
    "same_bar_priority",
    "execution_granularity",
    "point_in_time_pass",
]

LEG_COLUMNS = [
    "simulation_id",
    "trade_id",
    "leg_id",
    "date",
    "primary_regime",
    "playbook_id",
    "ticker",
    "side",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "exit_reason",
    "notional_sek",
    "gross_return",
    "gross_pnl_sek",
    "cost_sek",
    "net_pnl_sek",
]

PERFORMANCE_COLUMNS = [
    "simulation_id",
    "primary_regime",
    "playbook_id",
    "regime_sessions",
    "candidate_rows",
    "valid_setup_candidates",
    "selected_ideas",
    "triggered_trades",
    "closed_trades",
    "sessions_with_trades",
    "winning_trades",
    "losing_trades",
    "win_rate",
    "gross_pnl_sek_unconstrained",
    "cost_sek_unconstrained",
    "net_pnl_sek_unconstrained",
    "average_net_pnl_sek",
    "median_net_pnl_sek",
    "profit_factor",
    "average_net_return",
    "average_trade_duration_minutes",
    "performance_status",
]

AUDIT_COLUMNS = [
    "simulation_id",
    "date",
    "primary_regime",
    "playbook_id",
    "taxonomy_contract_pass",
    "max_router_source_label",
    "router_cutoff_pass",
    "minimum_entry_time",
    "entry_time_pass",
    "maximum_exit_time",
    "exit_after_entry_pass",
    "trade_leg_pnl_difference_sek",
    "trade_leg_reconciliation_pass",
    "execution_invariant_pass",
    "audit_status",
]


@dataclass(frozen=True)
class SingleExecution:
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    gross_return: float
    duration_minutes: float
    risk_per_share: float
    r_multiple: float


@dataclass(frozen=True)
class PairExecution:
    exit_time: pd.Timestamp
    exit_long_price: float
    exit_short_price: float
    exit_reason: str
    long_return: float
    short_return: float
    gross_return: float
    duration_minutes: float


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if pd.isna(value):
        return False
    return bool(value)


def _num(value: object, default: float = np.nan) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _clock(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%H:%M")


def _profit_factor(values: Iterable[float]) -> float:
    pnl = pd.Series(list(values), dtype="float64").dropna()
    if pnl.empty:
        return np.nan
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = abs(float(pnl[pnl < 0].sum()))
    if gross_loss == 0:
        return np.nan
    return gross_profit / gross_loss


def _first_bar_between(bars: pd.DataFrame, start: str, end: str) -> pd.Series | None:
    if bars.empty:
        return None
    clocks = bars["datetime"].dt.strftime("%H:%M")
    window = bars[clocks.ge(start) & clocks.le(end)]
    if window.empty:
        return None
    return window.iloc[0]


def _bars_through(bars: pd.DataFrame, cutoff: str) -> pd.DataFrame:
    if bars.empty:
        return bars.copy()
    clocks = bars["datetime"].dt.strftime("%H:%M")
    return bars[clocks.le(cutoff)].copy()


def _bars_between(bars: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if bars.empty:
        return bars.copy()
    clocks = bars["datetime"].dt.strftime("%H:%M")
    return bars[clocks.ge(start) & clocks.le(end)].copy()


def build_market_state(
    prices: pd.DataFrame,
    daily_reference: pd.DataFrame,
    taxonomy_dates: set[str] | None = None,
) -> tuple[pd.DataFrame, dict[tuple[str, str], pd.DataFrame]]:
    columns = [
        "date",
        "ticker",
        "previous_close",
        "early_open",
        "opening_bar_high",
        "opening_bar_low",
        "early_high",
        "early_low",
        "early_midpoint",
        "early_range_pct",
        "cutoff_close",
        "cutoff_return_from_open",
        "opening_gap",
        "close_0935",
        "close_0940",
        "high_0940",
        "low_0940",
        "max_router_source_label",
    ]
    if prices.empty:
        return pd.DataFrame(columns=columns), {}

    reference = daily_reference.copy()
    reference["date"] = reference["date"].astype(str)
    reference_lookup = reference.set_index(["date", "ticker"]).to_dict("index")

    states: list[dict] = []
    lookup: dict[tuple[str, str], pd.DataFrame] = {}
    working = prices[prices["ticker"].isin(GAP_RECOVERY_TICKERS)].copy()
    working["date_str"] = working["date"].astype(str)
    if taxonomy_dates is not None:
        working = working[working["date_str"].isin(taxonomy_dates)].copy()

    for (date_str, ticker), group in working.groupby(["date_str", "ticker"], sort=True):
        bars = group.sort_values("datetime").reset_index(drop=True)
        session = _bars_between(bars, "09:30", "16:30")
        if session.empty:
            continue
        lookup[(date_str, str(ticker))] = session
        early = _bars_between(session, "09:30", LATEST_ROUTER_BAR_LABEL)
        opening = early[early["datetime"].dt.strftime("%H:%M").eq("09:30")]
        if early.empty or opening.empty:
            continue
        ref = reference_lookup.get((date_str, str(ticker)), {})
        previous_close = _num(ref.get("previous_close"))
        early_open = _num(opening.iloc[0].get("open"))
        if not np.isfinite(early_open) or early_open <= 0:
            early_open = _num(opening.iloc[0].get("close"))
        early_high = _num(early["high"].max())
        early_low = _num(early["low"].min())
        cutoff = early.iloc[-1]
        cutoff_close = _num(cutoff.get("close"))
        bar_0935 = early[early["datetime"].dt.strftime("%H:%M").eq("09:35")]
        bar_0940 = early[early["datetime"].dt.strftime("%H:%M").eq("09:40")]
        opening_gap = (
            early_open / previous_close - 1.0
            if np.isfinite(previous_close) and previous_close > 0 and early_open > 0
            else np.nan
        )
        states.append(
            {
                "date": date_str,
                "ticker": str(ticker),
                "previous_close": previous_close,
                "early_open": early_open,
                "opening_bar_high": _num(opening.iloc[0].get("high")),
                "opening_bar_low": _num(opening.iloc[0].get("low")),
                "early_high": early_high,
                "early_low": early_low,
                "early_midpoint": (early_high + early_low) / 2.0,
                "early_range_pct": (early_high - early_low) / early_open if early_open > 0 else np.nan,
                "cutoff_close": cutoff_close,
                "cutoff_return_from_open": cutoff_close / early_open - 1.0 if early_open > 0 else np.nan,
                "opening_gap": opening_gap,
                "close_0935": _num(bar_0935.iloc[-1].get("close")) if not bar_0935.empty else np.nan,
                "close_0940": _num(bar_0940.iloc[-1].get("close")) if not bar_0940.empty else cutoff_close,
                "high_0940": _num(bar_0940.iloc[-1].get("high")) if not bar_0940.empty else _num(cutoff.get("high")),
                "low_0940": _num(bar_0940.iloc[-1].get("low")) if not bar_0940.empty else _num(cutoff.get("low")),
                "max_router_source_label": _clock(early["datetime"].max()),
            }
        )
    return pd.DataFrame(states, columns=columns), lookup


def _directional_execution(
    bars: pd.DataFrame,
    side: str,
    entry_time: pd.Timestamp,
    entry_price: float,
    stop_price: float,
    target_price: float,
    exit_cutoff: str,
) -> SingleExecution | None:
    if bars.empty or not all(np.isfinite(x) for x in [entry_price, stop_price, target_price]):
        return None
    trade_bars = _bars_between(bars, _clock(entry_time), exit_cutoff)
    trade_bars = trade_bars[trade_bars["datetime"].ge(entry_time)].copy()
    if trade_bars.empty:
        return None

    side = side.upper()
    for _, bar in trade_bars.iterrows():
        high = _num(bar.get("high"))
        low = _num(bar.get("low"))
        if side == "LONG":
            stop_hit = low <= stop_price
            target_hit = high >= target_price
        else:
            stop_hit = high >= stop_price
            target_hit = low <= target_price

        if stop_hit:
            exit_price = stop_price
            reason = "STOP_HIT"
        elif target_hit:
            exit_price = target_price
            reason = "TARGET_HIT"
        else:
            continue

        exit_time = pd.Timestamp(bar["datetime"])
        gross_return = (
            exit_price / entry_price - 1.0
            if side == "LONG"
            else entry_price / exit_price - 1.0
        )
        risk = entry_price - stop_price if side == "LONG" else stop_price - entry_price
        reward = exit_price - entry_price if side == "LONG" else entry_price - exit_price
        return SingleExecution(
            exit_time=exit_time,
            exit_price=float(exit_price),
            exit_reason=reason,
            gross_return=float(gross_return),
            duration_minutes=(exit_time - entry_time).total_seconds() / 60.0,
            risk_per_share=max(float(risk), 0.0),
            r_multiple=float(reward / risk) if risk > 0 else 0.0,
        )

    last = trade_bars.iloc[-1]
    exit_time = pd.Timestamp(last["datetime"])
    exit_price = _num(last.get("close"))
    gross_return = (
        exit_price / entry_price - 1.0
        if side == "LONG"
        else entry_price / exit_price - 1.0
    )
    risk = entry_price - stop_price if side == "LONG" else stop_price - entry_price
    reward = exit_price - entry_price if side == "LONG" else entry_price - exit_price
    return SingleExecution(
        exit_time=exit_time,
        exit_price=float(exit_price),
        exit_reason="TIME_EXIT",
        gross_return=float(gross_return),
        duration_minutes=(exit_time - entry_time).total_seconds() / 60.0,
        risk_per_share=max(float(risk), 0.0),
        r_multiple=float(reward / risk) if risk > 0 else 0.0,
    )


def _first_breakout(
    bars: pd.DataFrame,
    side: str,
    trigger: float,
    start: str,
    end: str,
) -> tuple[pd.Series, float] | None:
    window = _bars_between(bars, start, end)
    if window.empty or not np.isfinite(trigger):
        return None
    for _, bar in window.iterrows():
        open_price = _num(bar.get("open"), _num(bar.get("close")))
        if side.upper() == "LONG" and _num(bar.get("high")) >= trigger:
            return bar, max(float(trigger), float(open_price))
        if side.upper() == "SHORT" and _num(bar.get("low")) <= trigger:
            return bar, min(float(trigger), float(open_price))
    return None


def _next_bar_after(bars: pd.DataFrame, signal_bar_time: pd.Timestamp) -> pd.Series | None:
    next_rows = bars[bars["datetime"].gt(signal_bar_time)].sort_values("datetime")
    if next_rows.empty:
        return None
    return next_rows.iloc[0]


def _common_pair_bars(long_bars: pd.DataFrame, short_bars: pd.DataFrame) -> pd.DataFrame:
    left = long_bars[["datetime", "open", "close"]].rename(
        columns={"open": "long_open", "close": "long_close"}
    )
    right = short_bars[["datetime", "open", "close"]].rename(
        columns={"open": "short_open", "close": "short_close"}
    )
    return left.merge(right, on="datetime", how="inner").sort_values("datetime").reset_index(drop=True)


def _pair_execution(
    common: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_long_price: float,
    entry_short_price: float,
    stop_return: float,
    target_return: float,
    exit_cutoff: str,
) -> PairExecution | None:
    if common.empty:
        return None
    clocks = common["datetime"].dt.strftime("%H:%M")
    trade_bars = common[
        common["datetime"].ge(entry_time) & clocks.le(exit_cutoff)
    ].copy()
    if trade_bars.empty:
        return None

    exit_row = None
    exit_reason = "TIME_EXIT"
    for _, row in trade_bars.iterrows():
        long_return = _num(row.get("long_close")) / entry_long_price - 1.0
        short_return = entry_short_price / _num(row.get("short_close")) - 1.0
        gross_return = 0.5 * (long_return + short_return)
        if gross_return <= stop_return:
            exit_row = row
            exit_reason = "PAIR_STOP_HIT"
            break
        if gross_return >= target_return:
            exit_row = row
            exit_reason = "PAIR_TARGET_HIT"
            break
    if exit_row is None:
        exit_row = trade_bars.iloc[-1]

    exit_time = pd.Timestamp(exit_row["datetime"])
    exit_long = _num(exit_row.get("long_close"))
    exit_short = _num(exit_row.get("short_close"))
    long_return = exit_long / entry_long_price - 1.0
    short_return = entry_short_price / exit_short - 1.0
    gross_return = 0.5 * (long_return + short_return)
    return PairExecution(
        exit_time=exit_time,
        exit_long_price=float(exit_long),
        exit_short_price=float(exit_short),
        exit_reason=exit_reason,
        long_return=float(long_return),
        short_return=float(short_return),
        gross_return=float(gross_return),
        duration_minutes=(exit_time - entry_time).total_seconds() / 60.0,
    )


def _candidate_template(
    date: str,
    regime: str,
    playbook_id: str,
    idea_id: str,
    idea_type: str,
) -> dict:
    return {
        "simulation_id": SIMULATION_ID,
        "date": date,
        "primary_regime": regime,
        "playbook_id": playbook_id,
        "idea_id": idea_id,
        "idea_type": idea_type,
        "selection_rank": np.nan,
        "selected_for_simulation": False,
        "setup_status": "INVALID_SETUP",
        "trigger_status": "NOT_EVALUATED",
        "invalid_reason": "",
        "direction": "",
        "ticker": "",
        "paired_ticker": "",
        "long_ticker": "",
        "short_ticker": "",
        "ranking_metric": np.nan,
        "cutoff_return_from_open": np.nan,
        "paired_cutoff_return_from_open": np.nan,
        "opening_gap": np.nan,
        "previous_close": np.nan,
        "early_open": np.nan,
        "early_high": np.nan,
        "early_low": np.nan,
        "early_midpoint": np.nan,
        "early_range_pct": np.nan,
        "signal_time": "",
        "entry_time": "",
        "entry_price": np.nan,
        "stop_price": np.nan,
        "target_price": np.nan,
        "pair_entry_long_price": np.nan,
        "pair_entry_short_price": np.nan,
        "pair_stop_return": np.nan,
        "pair_target_return": np.nan,
        "exit_time": "",
        "exit_price": np.nan,
        "pair_exit_long_price": np.nan,
        "pair_exit_short_price": np.nan,
        "exit_reason": "",
        "gross_return": np.nan,
        "net_return": np.nan,
        "notional_sek": np.nan,
        "gross_pnl_sek": np.nan,
        "cost_sek": np.nan,
        "net_pnl_sek": np.nan,
        "trade_duration_minutes": np.nan,
        "max_router_source_label": "",
        "point_in_time_pass": False,
        "execution_observation_start": EXECUTION_OBSERVATION_START,
        "same_bar_priority": "STOP",
        "mechanical_interpretation": "",
    }


def _state_to_candidate(candidate: dict, state: dict) -> None:
    candidate.update(
        {
            "ticker": state.get("ticker", ""),
            "cutoff_return_from_open": _num(state.get("cutoff_return_from_open")),
            "opening_gap": _num(state.get("opening_gap")),
            "previous_close": _num(state.get("previous_close")),
            "early_open": _num(state.get("early_open")),
            "early_high": _num(state.get("early_high")),
            "early_low": _num(state.get("early_low")),
            "early_midpoint": _num(state.get("early_midpoint")),
            "early_range_pct": _num(state.get("early_range_pct")),
            "max_router_source_label": state.get("max_router_source_label", ""),
            "point_in_time_pass": str(state.get("max_router_source_label", "")) <= LATEST_ROUTER_BAR_LABEL,
        }
    )


def _append_single_trade(
    candidate: dict,
    trades: list[dict],
    legs: list[dict],
    execution: SingleExecution,
    side: str,
    risk_multiplier: float,
) -> None:
    notional = BASELINE_NOTIONAL_SEK * risk_multiplier
    gross_pnl = notional * execution.gross_return
    cost = notional * ROUND_TRIP_COST_RATE
    net_pnl = gross_pnl - cost
    net_return = net_pnl / notional if notional > 0 else np.nan
    trade_id = f"{candidate['idea_id']}|TRADE"
    candidate.update(
        {
            "trigger_status": "TRIGGERED_CLOSED",
            "exit_time": _iso(execution.exit_time),
            "exit_price": execution.exit_price,
            "exit_reason": execution.exit_reason,
            "gross_return": execution.gross_return,
            "net_return": net_return,
            "notional_sek": notional,
            "gross_pnl_sek": gross_pnl,
            "cost_sek": cost,
            "net_pnl_sek": net_pnl,
            "trade_duration_minutes": execution.duration_minutes,
        }
    )
    trade = {
        "simulation_id": SIMULATION_ID,
        "trade_id": trade_id,
        "idea_id": candidate["idea_id"],
        "date": candidate["date"],
        "primary_regime": candidate["primary_regime"],
        "playbook_id": candidate["playbook_id"],
        "idea_type": candidate["idea_type"],
        "direction": side,
        "ticker": candidate["ticker"],
        "paired_ticker": "",
        "long_ticker": candidate["ticker"] if side == "LONG" else "",
        "short_ticker": candidate["ticker"] if side == "SHORT" else "",
        "entry_time": candidate["entry_time"],
        "entry_price": candidate["entry_price"],
        "stop_price": candidate["stop_price"],
        "target_price": candidate["target_price"],
        "pair_entry_long_price": np.nan,
        "pair_entry_short_price": np.nan,
        "pair_stop_return": np.nan,
        "pair_target_return": np.nan,
        "exit_time": _iso(execution.exit_time),
        "exit_price": execution.exit_price,
        "pair_exit_long_price": np.nan,
        "pair_exit_short_price": np.nan,
        "exit_reason": execution.exit_reason,
        "gross_return": execution.gross_return,
        "net_return": net_return,
        "notional_sek": notional,
        "gross_pnl_sek": gross_pnl,
        "cost_sek": cost,
        "net_pnl_sek": net_pnl,
        "account_return": net_pnl / float(ORB_INITIAL_CAPITAL),
        "trade_duration_minutes": execution.duration_minutes,
        "risk_per_share": execution.risk_per_share,
        "r_multiple_achieved": execution.r_multiple,
        "same_bar_priority": "STOP",
        "execution_granularity": "FIVE_MINUTE_OHLC_CONSERVATIVE_SAME_BAR_STOP",
        "point_in_time_pass": candidate["point_in_time_pass"],
    }
    trades.append(trade)
    legs.append(
        {
            "simulation_id": SIMULATION_ID,
            "trade_id": trade_id,
            "leg_id": f"{trade_id}|LEG1",
            "date": candidate["date"],
            "primary_regime": candidate["primary_regime"],
            "playbook_id": candidate["playbook_id"],
            "ticker": candidate["ticker"],
            "side": side,
            "entry_time": candidate["entry_time"],
            "entry_price": candidate["entry_price"],
            "exit_time": _iso(execution.exit_time),
            "exit_price": execution.exit_price,
            "exit_reason": execution.exit_reason,
            "notional_sek": notional,
            "gross_return": execution.gross_return,
            "gross_pnl_sek": gross_pnl,
            "cost_sek": cost,
            "net_pnl_sek": net_pnl,
        }
    )


def _append_pair_trade(
    candidate: dict,
    trades: list[dict],
    legs: list[dict],
    execution: PairExecution,
    risk_multiplier: float,
) -> None:
    total_notional = BASELINE_NOTIONAL_SEK * risk_multiplier
    leg_notional = total_notional / 2.0
    long_gross_pnl = leg_notional * execution.long_return
    short_gross_pnl = leg_notional * execution.short_return
    leg_cost = leg_notional * ROUND_TRIP_COST_RATE
    gross_pnl = long_gross_pnl + short_gross_pnl
    cost = 2.0 * leg_cost
    net_pnl = gross_pnl - cost
    net_return = net_pnl / total_notional if total_notional > 0 else np.nan
    trade_id = f"{candidate['idea_id']}|TRADE"
    candidate.update(
        {
            "trigger_status": "TRIGGERED_CLOSED",
            "exit_time": _iso(execution.exit_time),
            "pair_exit_long_price": execution.exit_long_price,
            "pair_exit_short_price": execution.exit_short_price,
            "exit_reason": execution.exit_reason,
            "gross_return": execution.gross_return,
            "net_return": net_return,
            "notional_sek": total_notional,
            "gross_pnl_sek": gross_pnl,
            "cost_sek": cost,
            "net_pnl_sek": net_pnl,
            "trade_duration_minutes": execution.duration_minutes,
        }
    )
    trades.append(
        {
            "simulation_id": SIMULATION_ID,
            "trade_id": trade_id,
            "idea_id": candidate["idea_id"],
            "date": candidate["date"],
            "primary_regime": candidate["primary_regime"],
            "playbook_id": candidate["playbook_id"],
            "idea_type": "PAIR",
            "direction": "LONG_SHORT",
            "ticker": candidate["long_ticker"],
            "paired_ticker": candidate["short_ticker"],
            "long_ticker": candidate["long_ticker"],
            "short_ticker": candidate["short_ticker"],
            "entry_time": candidate["entry_time"],
            "entry_price": np.nan,
            "stop_price": np.nan,
            "target_price": np.nan,
            "pair_entry_long_price": candidate["pair_entry_long_price"],
            "pair_entry_short_price": candidate["pair_entry_short_price"],
            "pair_stop_return": candidate["pair_stop_return"],
            "pair_target_return": candidate["pair_target_return"],
            "exit_time": _iso(execution.exit_time),
            "exit_price": np.nan,
            "pair_exit_long_price": execution.exit_long_price,
            "pair_exit_short_price": execution.exit_short_price,
            "exit_reason": execution.exit_reason,
            "gross_return": execution.gross_return,
            "net_return": net_return,
            "notional_sek": total_notional,
            "gross_pnl_sek": gross_pnl,
            "cost_sek": cost,
            "net_pnl_sek": net_pnl,
            "account_return": net_pnl / float(ORB_INITIAL_CAPITAL),
            "trade_duration_minutes": execution.duration_minutes,
            "risk_per_share": np.nan,
            "r_multiple_achieved": np.nan,
            "same_bar_priority": "PAIR_CLOSE_ONLY",
            "execution_granularity": "SYNCHRONIZED_FIVE_MINUTE_CLOSE_PAIR",
            "point_in_time_pass": candidate["point_in_time_pass"],
        }
    )
    for index, (ticker, side, entry, exit_price, gross_ret, gross_leg) in enumerate(
        [
            (
                candidate["long_ticker"],
                "LONG",
                candidate["pair_entry_long_price"],
                execution.exit_long_price,
                execution.long_return,
                long_gross_pnl,
            ),
            (
                candidate["short_ticker"],
                "SHORT",
                candidate["pair_entry_short_price"],
                execution.exit_short_price,
                execution.short_return,
                short_gross_pnl,
            ),
        ],
        start=1,
    ):
        legs.append(
            {
                "simulation_id": SIMULATION_ID,
                "trade_id": trade_id,
                "leg_id": f"{trade_id}|LEG{index}",
                "date": candidate["date"],
                "primary_regime": candidate["primary_regime"],
                "playbook_id": candidate["playbook_id"],
                "ticker": ticker,
                "side": side,
                "entry_time": candidate["entry_time"],
                "entry_price": entry,
                "exit_time": _iso(execution.exit_time),
                "exit_price": exit_price,
                "exit_reason": execution.exit_reason,
                "notional_sek": leg_notional,
                "gross_return": gross_ret,
                "gross_pnl_sek": gross_leg,
                "cost_sek": leg_cost,
                "net_pnl_sek": gross_leg - leg_cost,
            }
        )


def _select_candidates(candidates: list[dict], max_ideas: int, descending: bool = True) -> None:
    valid = [row for row in candidates if row["setup_status"] == "VALID_SETUP"]
    valid.sort(
        key=lambda row: (
            -_num(row.get("ranking_metric"), -np.inf) if descending else _num(row.get("ranking_metric"), np.inf),
            str(row.get("ticker", "")),
            str(row.get("paired_ticker", "")),
        )
    )
    for rank, row in enumerate(valid, start=1):
        row["selection_rank"] = rank
        if rank <= max_ideas:
            row["selected_for_simulation"] = True
            row["trigger_status"] = "SELECTED_NOT_TRIGGERED"
        else:
            row["trigger_status"] = "ELIGIBLE_NOT_SELECTED"


def _generate_single_candidates(
    session: dict,
    states: pd.DataFrame,
    bars_lookup: dict[tuple[str, str], pd.DataFrame],
    trades: list[dict],
    legs: list[dict],
) -> list[dict]:
    date = str(session["date"])
    regime = str(session["primary_regime"])
    spec = PLAYBOOKS[regime]
    risk_multiplier = float(spec.research_risk_multiplier)
    max_ideas = int(spec.max_concurrent_ideas)
    rows: list[dict] = []

    for state in states.sort_values("ticker").to_dict("records"):
        ticker = str(state["ticker"])
        candidate = _candidate_template(date, regime, spec.playbook_id, f"{date}|{regime}|{ticker}", "SINGLE")
        _state_to_candidate(candidate, state)
        candidate["setup_status"] = "VALID_SETUP"
        invalid: list[str] = []
        cutoff_return = _num(state.get("cutoff_return_from_open"))
        early_open = _num(state.get("early_open"))
        early_high = _num(state.get("early_high"))
        early_low = _num(state.get("early_low"))
        early_mid = _num(state.get("early_midpoint"))
        early_range_pct = _num(state.get("early_range_pct"))
        previous_close = _num(state.get("previous_close"))
        opening_gap = _num(state.get("opening_gap"))

        if regime == "RECOVERY":
            candidate["direction"] = "LONG"
            candidate["ranking_metric"] = 0.0
            candidate["entry_price"] = _num(state.get("opening_bar_high"))
            candidate["stop_price"] = _num(state.get("opening_bar_low"))
            candidate["target_price"] = previous_close
            candidate["mechanical_interpretation"] = "STRICT_0930_RANGE_RECLAIM_TO_PREVIOUS_CLOSE"
            if not np.isfinite(opening_gap) or opening_gap < -0.0200 or opening_gap > -0.0010:
                invalid.append("GAP_OUTSIDE_RECOVERY_RANGE")
            if not np.isfinite(previous_close):
                invalid.append("MISSING_PREVIOUS_CLOSE")
            if candidate["target_price"] <= candidate["entry_price"]:
                invalid.append("TARGET_NOT_ABOVE_ENTRY")
            if candidate["stop_price"] >= candidate["entry_price"]:
                invalid.append("INVALID_OPENING_RANGE")
            risk_pct = (candidate["entry_price"] - candidate["stop_price"]) / candidate["entry_price"] if candidate["entry_price"] > 0 else np.nan
            if not np.isfinite(risk_pct) or risk_pct > MAX_DIRECTIONAL_RISK_PCT:
                invalid.append("RISK_ABOVE_3_PERCENT_CAP")
        elif regime == "TREND_UP":
            candidate["direction"] = "LONG"
            candidate["ranking_metric"] = cutoff_return
            candidate["entry_price"] = early_high
            candidate["stop_price"] = early_low
            risk = early_high - early_low
            candidate["target_price"] = early_high + risk
            candidate["mechanical_interpretation"] = "STRICT_EARLY_RANGE_LONG_BREAKOUT_1R"
            if cutoff_return <= 0:
                invalid.append("NOT_POSITIVE_FROM_OPEN")
            if np.isfinite(previous_close) and _num(state.get("cutoff_close")) <= previous_close:
                invalid.append("NOT_ABOVE_PREVIOUS_CLOSE")
            if not np.isfinite(early_range_pct) or early_range_pct <= 0 or early_range_pct > MAX_DIRECTIONAL_RISK_PCT:
                invalid.append("INVALID_OR_TOO_WIDE_EARLY_RANGE")
        elif regime == "TREND_DOWN":
            candidate["direction"] = "SHORT"
            candidate["ranking_metric"] = -cutoff_return
            candidate["entry_price"] = early_low
            candidate["stop_price"] = early_high
            risk = early_high - early_low
            candidate["target_price"] = early_low - risk
            candidate["mechanical_interpretation"] = "STRICT_EARLY_RANGE_SHORT_BREAKOUT_1R"
            if cutoff_return >= 0:
                invalid.append("NOT_NEGATIVE_FROM_OPEN")
            if np.isfinite(previous_close) and _num(state.get("cutoff_close")) >= previous_close:
                invalid.append("NOT_BELOW_PREVIOUS_CLOSE")
            if candidate["target_price"] <= 0:
                invalid.append("NONPOSITIVE_TARGET")
            if not np.isfinite(early_range_pct) or early_range_pct <= 0 or early_range_pct > MAX_DIRECTIONAL_RISK_PCT:
                invalid.append("INVALID_OR_TOO_WIDE_EARLY_RANGE")
        elif regime == "RANGE_LOW_VOL":
            candidate["ranking_metric"] = abs(_num(state.get("cutoff_close")) / early_mid - 1.0) if early_mid > 0 else np.nan
            candidate["mechanical_interpretation"] = "FADE_SAME_SIDE_RANGE_FAILURE_ENTER_NEXT_BAR_OPEN"
            if not np.isfinite(early_range_pct) or early_range_pct <= 0:
                invalid.append("INVALID_EARLY_RANGE")
            if _num(state.get("cutoff_close")) > early_mid:
                candidate["direction"] = "SHORT"
            elif _num(state.get("cutoff_close")) < early_mid:
                candidate["direction"] = "LONG"
            else:
                invalid.append("NO_CUTOFF_DEVIATION")
        elif regime == "HIGH_VOL_REVERSAL":
            close_0935 = _num(state.get("close_0935"))
            close_0940 = _num(state.get("close_0940"))
            initial_move = close_0935 / early_open - 1.0 if early_open > 0 and np.isfinite(close_0935) else np.nan
            final_move = close_0940 / early_open - 1.0 if early_open > 0 and np.isfinite(close_0940) else np.nan
            retracement = abs(initial_move) - abs(final_move) if np.isfinite(initial_move) and np.isfinite(final_move) else np.nan
            sign_flip = np.isfinite(initial_move) and np.isfinite(final_move) and initial_move * final_move < 0
            candidate["ranking_metric"] = abs(initial_move) + max(retracement, 0.0) + (abs(initial_move) if sign_flip else 0.0) if np.isfinite(initial_move) else np.nan
            candidate["mechanical_interpretation"] = "REVERSE_0935_MOVE_ON_0940_PIVOT_BREAK"
            if not np.isfinite(initial_move) or abs(initial_move) < 0.0010:
                invalid.append("INSUFFICIENT_INITIAL_MOVE")
            elif initial_move > 0 and close_0940 < close_0935:
                candidate["direction"] = "SHORT"
                candidate["entry_price"] = _num(state.get("low_0940"))
                candidate["stop_price"] = early_high
            elif initial_move < 0 and close_0940 > close_0935:
                candidate["direction"] = "LONG"
                candidate["entry_price"] = _num(state.get("high_0940"))
                candidate["stop_price"] = early_low
            else:
                invalid.append("NO_EARLY_RETRACEMENT")
            if not sign_flip and np.isfinite(retracement) and retracement <= 0:
                invalid.append("RETRACEMENT_NOT_POSITIVE")
        elif regime == "VOLATILITY_EXPANSION":
            direction_bias = str(session.get("direction_bias", "NEUTRAL")).upper()
            candidate["ranking_metric"] = early_range_pct + abs(cutoff_return) if np.isfinite(early_range_pct) else np.nan
            candidate["mechanical_interpretation"] = "DIRECTION_ALIGNED_OR_NEUTRAL_TWO_SIDED_1_5R_BREAKOUT"
            if direction_bias == "UP":
                candidate["direction"] = "LONG"
            elif direction_bias == "DOWN":
                candidate["direction"] = "SHORT"
            else:
                candidate["direction"] = "TWO_SIDED"
            if not np.isfinite(early_range_pct) or early_range_pct <= 0 or early_range_pct > MAX_DIRECTIONAL_RISK_PCT:
                invalid.append("INVALID_OR_TOO_WIDE_EARLY_RANGE")
            if direction_bias == "UP" and cutoff_return < 0:
                invalid.append("STOCK_NOT_ALIGNED_UP")
            if direction_bias == "DOWN" and cutoff_return > 0:
                invalid.append("STOCK_NOT_ALIGNED_DOWN")

        if invalid:
            candidate["setup_status"] = "INVALID_SETUP"
            candidate["invalid_reason"] = ";".join(sorted(set(invalid)))
            candidate["trigger_status"] = "NOT_EVALUATED"
        rows.append(candidate)

    _select_candidates(rows, max_ideas=max_ideas, descending=True)

    for candidate in rows:
        if not candidate["selected_for_simulation"]:
            continue
        ticker = candidate["ticker"]
        bars = bars_lookup.get((date, ticker), pd.DataFrame())
        side = candidate["direction"]
        trigger_result: tuple[pd.Series, float] | None = None
        signal_time = ""
        exit_cutoff = "16:30"

        if regime == "RECOVERY":
            trigger_result = _first_breakout(bars, "LONG", candidate["entry_price"], "09:45", "13:00")
        elif regime == "TREND_UP":
            trigger_result = _first_breakout(bars, "LONG", candidate["entry_price"], "09:45", "13:00")
        elif regime == "TREND_DOWN":
            trigger_result = _first_breakout(bars, "SHORT", candidate["entry_price"], "09:45", "13:00")
        elif regime == "HIGH_VOL_REVERSAL":
            trigger_result = _first_breakout(bars, side, candidate["entry_price"], "09:45", "13:00")
        elif regime == "VOLATILITY_EXPANSION":
            window = _bars_between(bars, "09:45", "12:00")
            if side == "TWO_SIDED":
                for _, bar in window.iterrows():
                    up = _num(bar.get("high")) >= _num(candidate.get("early_high"))
                    down = _num(bar.get("low")) <= _num(candidate.get("early_low"))
                    if up and down:
                        candidate["trigger_status"] = "AMBIGUOUS_SAME_BAR_TWO_SIDED_BREAK"
                        candidate["invalid_reason"] = "INTRABAR_BREAK_ORDER_UNKNOWN"
                        break
                    if up:
                        side = "LONG"
                        trigger_result = (bar, max(_num(candidate.get("early_high")), _num(bar.get("open"))))
                        break
                    if down:
                        side = "SHORT"
                        trigger_result = (bar, min(_num(candidate.get("early_low")), _num(bar.get("open"))))
                        break
            elif side == "LONG":
                trigger_result = _first_breakout(bars, "LONG", _num(candidate.get("early_high")), "09:45", "12:00")
            else:
                trigger_result = _first_breakout(bars, "SHORT", _num(candidate.get("early_low")), "09:45", "12:00")
            if trigger_result is not None:
                candidate["direction"] = side
                midpoint = _num(candidate.get("early_midpoint"))
                entry_for_levels = trigger_result[1]
                if side == "LONG":
                    candidate["stop_price"] = midpoint
                    risk = entry_for_levels - midpoint
                    candidate["target_price"] = entry_for_levels + 1.5 * risk
                else:
                    candidate["stop_price"] = midpoint
                    risk = midpoint - entry_for_levels
                    candidate["target_price"] = entry_for_levels - 1.5 * risk
        elif regime == "RANGE_LOW_VOL":
            desired_side = side
            signal_window = _bars_between(bars, "09:45", "13:55")
            signal_bar = None
            for _, bar in signal_window.iterrows():
                if desired_side == "SHORT" and _num(bar.get("high")) >= _num(candidate.get("early_high")) and _num(bar.get("close")) < _num(candidate.get("early_high")):
                    signal_bar = bar
                    break
                if desired_side == "LONG" and _num(bar.get("low")) <= _num(candidate.get("early_low")) and _num(bar.get("close")) > _num(candidate.get("early_low")):
                    signal_bar = bar
                    break
            if signal_bar is not None:
                next_bar = _next_bar_after(bars, pd.Timestamp(signal_bar["datetime"]))
                if next_bar is not None and _clock(next_bar["datetime"]) <= "14:00":
                    entry_price = _num(next_bar.get("open"), _num(next_bar.get("close")))
                    trigger_result = (next_bar, entry_price)
                    signal_time = _iso(pd.Timestamp(signal_bar["datetime"]) + pd.Timedelta(minutes=BAR_INTERVAL_MINUTES))
                    width = _num(candidate.get("early_high")) - _num(candidate.get("early_low"))
                    if desired_side == "SHORT":
                        candidate["stop_price"] = _num(candidate.get("early_high")) + width
                    else:
                        candidate["stop_price"] = _num(candidate.get("early_low")) - width
                    candidate["target_price"] = _num(candidate.get("early_midpoint"))
                    exit_cutoff = "15:30"

        if trigger_result is None:
            if candidate["trigger_status"] == "SELECTED_NOT_TRIGGERED":
                candidate["trigger_status"] = "NOT_TRIGGERED"
            continue

        entry_bar, actual_entry = trigger_result
        entry_time = pd.Timestamp(entry_bar["datetime"])
        candidate["signal_time"] = signal_time or _iso(entry_time)
        candidate["entry_time"] = _iso(entry_time)
        candidate["entry_price"] = float(actual_entry)

        if regime == "HIGH_VOL_REVERSAL":
            risk = (
                candidate["entry_price"] - candidate["stop_price"]
                if side == "LONG"
                else candidate["stop_price"] - candidate["entry_price"]
            )
            if risk <= 0:
                candidate["trigger_status"] = "INVALID_TRIGGER_LEVELS"
                candidate["invalid_reason"] = "NONPOSITIVE_REVERSAL_RISK"
                continue
            open_price = _num(candidate.get("early_open"))
            if side == "LONG":
                candidate["target_price"] = min(open_price, candidate["entry_price"] + risk) if open_price > candidate["entry_price"] else candidate["entry_price"] + risk
            else:
                candidate["target_price"] = max(open_price, candidate["entry_price"] - risk) if open_price < candidate["entry_price"] else candidate["entry_price"] - risk

        risk = (
            candidate["entry_price"] - candidate["stop_price"]
            if side == "LONG"
            else candidate["stop_price"] - candidate["entry_price"]
        )
        reward = (
            candidate["target_price"] - candidate["entry_price"]
            if side == "LONG"
            else candidate["entry_price"] - candidate["target_price"]
        )
        if not np.isfinite(risk) or not np.isfinite(reward) or risk <= 0 or reward <= 0:
            candidate["trigger_status"] = "INVALID_TRIGGER_LEVELS"
            candidate["invalid_reason"] = "NONPOSITIVE_RISK_OR_REWARD_AT_ACTUAL_ENTRY"
            continue

        execution = _directional_execution(
            bars=bars,
            side=side,
            entry_time=entry_time,
            entry_price=candidate["entry_price"],
            stop_price=candidate["stop_price"],
            target_price=candidate["target_price"],
            exit_cutoff=exit_cutoff,
        )
        if execution is None:
            candidate["trigger_status"] = "NO_EXECUTABLE_BARS_AFTER_ENTRY"
            continue
        _append_single_trade(candidate, trades, legs, execution, side, risk_multiplier)
    return rows


def _pair_candidate(
    session: dict,
    states: pd.DataFrame,
    bars_lookup: dict[tuple[str, str], pd.DataFrame],
    trades: list[dict],
    legs: list[dict],
) -> list[dict]:
    date = str(session["date"])
    regime = str(session["primary_regime"])
    spec = PLAYBOOKS[regime]
    candidate = _candidate_template(date, regime, spec.playbook_id, f"{date}|{regime}|PAIR1", "PAIR")
    candidate["setup_status"] = "VALID_SETUP"
    candidate["selected_for_simulation"] = True
    candidate["selection_rank"] = 1
    candidate["trigger_status"] = "SELECTED_NOT_TRIGGERED"
    candidate["direction"] = "LONG_SHORT"
    candidate["point_in_time_pass"] = True
    candidate["max_router_source_label"] = LATEST_ROUTER_BAR_LABEL

    usable = states.dropna(subset=["cutoff_return_from_open"]).copy()
    invalid: list[str] = []
    long_state = None
    short_state = None
    stop_return = np.nan
    target_return = np.nan
    exit_cutoff = "15:30"

    if len(usable) < 2:
        invalid.append("FEWER_THAN_TWO_USABLE_TICKERS")
    elif regime == "HIGH_DISPERSION":
        ordered = usable.sort_values(["cutoff_return_from_open", "ticker"])
        short_state = ordered.iloc[0]
        long_state = ordered.iloc[-1]
        spread = _num(long_state["cutoff_return_from_open"]) - _num(short_state["cutoff_return_from_open"])
        candidate["ranking_metric"] = spread
        candidate["mechanical_interpretation"] = "LONG_STRONGEST_SHORT_WEAKEST_RELATIVE_STRENGTH_CONTINUATION"
        if spread < MIN_HIGH_DISPERSION_SPREAD:
            invalid.append("EARLY_SPREAD_BELOW_HIGH_DISPERSION_THRESHOLD")
        stop_return = -max(0.0015, 0.25 * spread)
        target_return = max(0.0010, 0.25 * spread)
        exit_cutoff = "15:30"
    elif regime == "DEFENSIVE_MIXED":
        controlled = usable.copy()
        if controlled["early_range_pct"].notna().sum() >= 4:
            cap = controlled["early_range_pct"].quantile(0.75)
            filtered = controlled[controlled["early_range_pct"].le(cap)].copy()
            if len(filtered) >= 2:
                controlled = filtered
        ordered = controlled.sort_values(["cutoff_return_from_open", "ticker"])
        long_state = ordered.iloc[0]
        short_state = ordered.iloc[-1]
        spread = _num(short_state["cutoff_return_from_open"]) - _num(long_state["cutoff_return_from_open"])
        candidate["ranking_metric"] = spread
        candidate["mechanical_interpretation"] = "LONG_WEAKER_SHORT_STRONGER_CONTROLLED_CONVERGENCE"
        if spread < MIN_DEFENSIVE_SPREAD:
            invalid.append("EARLY_SPREAD_BELOW_DEFENSIVE_THRESHOLD")
        stop_return = -max(0.0010, 0.125 * spread)
        target_return = max(0.00075, 0.175 * spread)
        exit_cutoff = "14:30"
    else:
        # The data-limited response does not infer direction. It uses the two
        # smallest absolute early movers when available; otherwise ticker order.
        if len(usable) >= 2:
            ordered = usable.assign(
                abs_move=usable["cutoff_return_from_open"].abs()
            ).sort_values(["abs_move", "ticker"])
        else:
            ordered = states.sort_values("ticker")
        if len(ordered) >= 2:
            first = ordered.iloc[0]
            second = ordered.iloc[1]
            pair = sorted([str(first["ticker"]), str(second["ticker"])])
            long_state = states[states["ticker"].eq(pair[0])].iloc[0]
            short_state = states[states["ticker"].eq(pair[1])].iloc[0]
        candidate["ranking_metric"] = 0.0
        candidate["mechanical_interpretation"] = "DETERMINISTIC_MINIMUM_GROSS_HEDGE_NO_DIRECTIONAL_INFERENCE"
        stop_return = -0.0050
        target_return = 0.0025
        exit_cutoff = "12:00"

    if long_state is None or short_state is None:
        invalid.append("PAIR_SELECTION_FAILED")
    if invalid:
        candidate["setup_status"] = "INVALID_SETUP"
        candidate["selected_for_simulation"] = False
        candidate["trigger_status"] = "NOT_EVALUATED"
        candidate["invalid_reason"] = ";".join(sorted(set(invalid)))
        return [candidate]

    long_ticker = str(long_state["ticker"])
    short_ticker = str(short_state["ticker"])
    candidate.update(
        {
            "ticker": long_ticker,
            "paired_ticker": short_ticker,
            "long_ticker": long_ticker,
            "short_ticker": short_ticker,
            "cutoff_return_from_open": _num(long_state.get("cutoff_return_from_open")),
            "paired_cutoff_return_from_open": _num(short_state.get("cutoff_return_from_open")),
            "pair_stop_return": stop_return,
            "pair_target_return": target_return,
            "max_router_source_label": max(
                str(long_state.get("max_router_source_label", "")),
                str(short_state.get("max_router_source_label", "")),
            ),
        }
    )
    candidate["point_in_time_pass"] = candidate["max_router_source_label"] <= LATEST_ROUTER_BAR_LABEL
    long_bars = bars_lookup.get((date, long_ticker), pd.DataFrame())
    short_bars = bars_lookup.get((date, short_ticker), pd.DataFrame())
    common = _common_pair_bars(long_bars, short_bars)
    entry = _first_bar_between(common, "09:45", "10:00")
    if entry is None:
        candidate["trigger_status"] = "NO_COMMON_ENTRY_BAR"
        return [candidate]

    entry_time = pd.Timestamp(entry["datetime"])
    entry_long = _num(entry.get("long_open"), _num(entry.get("long_close")))
    entry_short = _num(entry.get("short_open"), _num(entry.get("short_close")))
    candidate.update(
        {
            "signal_time": _iso(entry_time),
            "entry_time": _iso(entry_time),
            "pair_entry_long_price": entry_long,
            "pair_entry_short_price": entry_short,
        }
    )
    execution = _pair_execution(
        common=common,
        entry_time=entry_time,
        entry_long_price=entry_long,
        entry_short_price=entry_short,
        stop_return=stop_return,
        target_return=target_return,
        exit_cutoff=exit_cutoff,
    )
    if execution is None:
        candidate["trigger_status"] = "NO_EXECUTABLE_PAIR_BARS"
        return [candidate]
    _append_pair_trade(candidate, trades, legs, execution, float(spec.research_risk_multiplier))
    return [candidate]


def build_baseline_simulation(
    taxonomy: pd.DataFrame,
    coverage: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    taxonomy = taxonomy.copy()
    taxonomy["date"] = taxonomy["date"].astype(str)
    coverage = coverage.copy()
    if not coverage.empty:
        coverage["date"] = coverage["date"].astype(str)
    dates = set(taxonomy["date"].tolist())
    daily_reference = build_daily_reference(prices)
    state, bars_lookup = build_market_state(prices, daily_reference, dates)

    coverage_fields = coverage[
        ["date", "playbook_id", "point_in_time_contract_pass"]
    ].rename(
        columns={
            "playbook_id": "coverage_playbook_id",
            "point_in_time_contract_pass": "coverage_point_in_time_contract_pass",
        }
    ) if not coverage.empty else pd.DataFrame(columns=["date", "coverage_playbook_id", "coverage_point_in_time_contract_pass"])
    sessions = taxonomy.merge(coverage_fields, on="date", how="left", validate="one_to_one")

    candidate_rows: list[dict] = []
    trade_rows: list[dict] = []
    leg_rows: list[dict] = []

    for session in sessions.sort_values("date").to_dict("records"):
        date = str(session["date"])
        regime = str(session["primary_regime"])
        day_states = state[state["date"].eq(date)].copy()
        if regime in {"HIGH_DISPERSION", "DEFENSIVE_MIXED", "DATA_LIMITED_DEFENSIVE"}:
            candidate_rows.extend(_pair_candidate(session, day_states, bars_lookup, trade_rows, leg_rows))
        else:
            candidate_rows.extend(_generate_single_candidates(session, day_states, bars_lookup, trade_rows, leg_rows))

    candidates = pd.DataFrame(candidate_rows, columns=CANDIDATE_COLUMNS)
    trades = pd.DataFrame(trade_rows, columns=TRADE_COLUMNS)
    legs = pd.DataFrame(leg_rows, columns=LEG_COLUMNS)
    session_summary = build_session_summary(sessions, state, candidates, trades)
    audit = build_audit(sessions, candidates, trades, legs)
    performance = build_performance(sessions, candidates, trades)
    summary = build_summary(sessions, candidates, trades, legs, performance, audit)
    return summary, session_summary, candidates, trades, legs, performance, audit


def build_session_summary(
    sessions: pd.DataFrame,
    state: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    for session in sessions.sort_values("date").to_dict("records"):
        date = str(session["date"])
        regime = str(session["primary_regime"])
        spec = PLAYBOOKS[regime]
        day_candidates = candidates[candidates["date"].eq(date)] if not candidates.empty else candidates
        day_trades = trades[trades["date"].eq(date)] if not trades.empty else trades
        selected = int(day_candidates["selected_for_simulation"].fillna(False).astype(bool).sum()) if not day_candidates.empty else 0
        triggered = len(day_trades)
        valid = int(day_candidates["setup_status"].eq("VALID_SETUP").sum()) if not day_candidates.empty else 0
        if triggered > 0:
            status = "TRADES_GENERATED"
        elif selected > 0:
            status = "ACTIVE_RESPONSE_NO_TRIGGER"
        else:
            status = "ACTIVE_RESPONSE_NO_VALID_SETUP"
        entries = pd.to_datetime(day_trades["entry_time"], errors="coerce") if not day_trades.empty else pd.Series(dtype="datetime64[ns]")
        exits = pd.to_datetime(day_trades["exit_time"], errors="coerce") if not day_trades.empty else pd.Series(dtype="datetime64[ns]")
        invariant = True
        if not day_trades.empty:
            invariant = bool(
                entries.notna().all()
                and exits.notna().all()
                and (entries.dt.strftime("%H:%M") >= EXECUTION_OBSERVATION_START).all()
                and (exits >= entries).all()
            )
        max_router = day_candidates["max_router_source_label"].dropna().astype(str).max() if not day_candidates.empty else ""
        point_pass = bool(day_candidates["point_in_time_pass"].fillna(False).all()) if not day_candidates.empty else regime == "DATA_LIMITED_DEFENSIVE"
        pnl = pd.to_numeric(day_trades.get("net_pnl_sek"), errors="coerce") if not day_trades.empty else pd.Series(dtype="float64")
        rows.append(
            {
                "simulation_id": SIMULATION_ID,
                "date": date,
                "primary_regime": regime,
                "playbook_id": spec.playbook_id,
                "regime_confidence": _num(session.get("regime_confidence")),
                "confidence_band": session.get("confidence_band", ""),
                "direction_bias": session.get("direction_bias", ""),
                "research_risk_multiplier": spec.research_risk_multiplier,
                "max_concurrent_ideas": spec.max_concurrent_ideas,
                "input_tickers": int(state[state["date"].eq(date)]["ticker"].nunique()),
                "candidate_rows": len(day_candidates),
                "valid_setup_candidates": valid,
                "selected_ideas": selected,
                "triggered_trades": triggered,
                "closed_trades": triggered,
                "winning_trades": int((pnl > 0).sum()),
                "losing_trades": int((pnl < 0).sum()),
                "gross_pnl_sek_unconstrained": pd.to_numeric(day_trades.get("gross_pnl_sek"), errors="coerce").sum() if not day_trades.empty else 0.0,
                "cost_sek_unconstrained": pd.to_numeric(day_trades.get("cost_sek"), errors="coerce").sum() if not day_trades.empty else 0.0,
                "net_pnl_sek_unconstrained": pnl.sum() if not day_trades.empty else 0.0,
                "minimum_entry_time": _iso(entries.min()) if not entries.empty and entries.notna().any() else "",
                "maximum_exit_time": _iso(exits.max()) if not exits.empty and exits.notna().any() else "",
                "max_router_source_label": max_router,
                "point_in_time_session_pass": point_pass,
                "execution_invariant_pass": invariant,
                "session_status": status,
            }
        )
    return pd.DataFrame(rows, columns=SESSION_COLUMNS)


def build_audit(
    sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    legs: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    for session in sessions.sort_values("date").to_dict("records"):
        date = str(session["date"])
        regime = str(session["primary_regime"])
        day_candidates = candidates[candidates["date"].eq(date)] if not candidates.empty else candidates
        day_trades = trades[trades["date"].eq(date)] if not trades.empty else trades
        day_legs = legs[legs["date"].eq(date)] if not legs.empty else legs
        max_router = day_candidates["max_router_source_label"].dropna().astype(str).max() if not day_candidates.empty else ""
        router_pass = bool(day_candidates["point_in_time_pass"].fillna(False).all()) if not day_candidates.empty else regime == "DATA_LIMITED_DEFENSIVE"
        entries = pd.to_datetime(day_trades["entry_time"], errors="coerce") if not day_trades.empty else pd.Series(dtype="datetime64[ns]")
        exits = pd.to_datetime(day_trades["exit_time"], errors="coerce") if not day_trades.empty else pd.Series(dtype="datetime64[ns]")
        entry_pass = bool(entries.notna().all() and (entries.dt.strftime("%H:%M") >= EXECUTION_OBSERVATION_START).all()) if not entries.empty else True
        exit_pass = bool(exits.notna().all() and (exits >= entries).all()) if not exits.empty else True
        trade_pnl = pd.to_numeric(day_trades.get("net_pnl_sek"), errors="coerce").sum() if not day_trades.empty else 0.0
        leg_pnl = pd.to_numeric(day_legs.get("net_pnl_sek"), errors="coerce").sum() if not day_legs.empty else 0.0
        difference = float(trade_pnl - leg_pnl)
        reconciliation_pass = abs(difference) <= 1e-9
        contract_pass = _bool(session.get("coverage_point_in_time_contract_pass"))
        overall = contract_pass and router_pass and entry_pass and exit_pass and reconciliation_pass
        rows.append(
            {
                "simulation_id": SIMULATION_ID,
                "date": date,
                "primary_regime": regime,
                "playbook_id": PLAYBOOKS[regime].playbook_id,
                "taxonomy_contract_pass": contract_pass,
                "max_router_source_label": max_router,
                "router_cutoff_pass": router_pass,
                "minimum_entry_time": _iso(entries.min()) if not entries.empty and entries.notna().any() else "",
                "entry_time_pass": entry_pass,
                "maximum_exit_time": _iso(exits.max()) if not exits.empty and exits.notna().any() else "",
                "exit_after_entry_pass": exit_pass,
                "trade_leg_pnl_difference_sek": difference,
                "trade_leg_reconciliation_pass": reconciliation_pass,
                "execution_invariant_pass": overall,
                "audit_status": "PASS" if overall else "FAIL",
            }
        )
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def build_performance(
    sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    for regime in REGIMES:
        spec = PLAYBOOKS[regime]
        regime_sessions = sessions[sessions["primary_regime"].eq(regime)]
        regime_candidates = candidates[candidates["primary_regime"].eq(regime)] if not candidates.empty else candidates
        regime_trades = trades[trades["primary_regime"].eq(regime)] if not trades.empty else trades
        pnl = pd.to_numeric(regime_trades.get("net_pnl_sek"), errors="coerce") if not regime_trades.empty else pd.Series(dtype="float64")
        net_returns = pd.to_numeric(regime_trades.get("net_return"), errors="coerce") if not regime_trades.empty else pd.Series(dtype="float64")
        if len(regime_sessions) == 0:
            status = "REGIME_NOT_OBSERVED"
        elif len(regime_trades) == 0:
            status = "OBSERVED_NO_TRIGGERED_TRADES"
        elif len(regime_trades) < 5:
            status = "TOO_FEW_TRADES_FOR_INFERENCE"
        else:
            status = "BASELINE_DIAGNOSTIC_ONLY_NOT_VALIDATED"
        rows.append(
            {
                "simulation_id": SIMULATION_ID,
                "primary_regime": regime,
                "playbook_id": spec.playbook_id,
                "regime_sessions": len(regime_sessions),
                "candidate_rows": len(regime_candidates),
                "valid_setup_candidates": int(regime_candidates["setup_status"].eq("VALID_SETUP").sum()) if not regime_candidates.empty else 0,
                "selected_ideas": int(regime_candidates["selected_for_simulation"].fillna(False).astype(bool).sum()) if not regime_candidates.empty else 0,
                "triggered_trades": len(regime_trades),
                "closed_trades": len(regime_trades),
                "sessions_with_trades": int(regime_trades["date"].nunique()) if not regime_trades.empty else 0,
                "winning_trades": int((pnl > 0).sum()),
                "losing_trades": int((pnl < 0).sum()),
                "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
                "gross_pnl_sek_unconstrained": pd.to_numeric(regime_trades.get("gross_pnl_sek"), errors="coerce").sum() if not regime_trades.empty else 0.0,
                "cost_sek_unconstrained": pd.to_numeric(regime_trades.get("cost_sek"), errors="coerce").sum() if not regime_trades.empty else 0.0,
                "net_pnl_sek_unconstrained": pnl.sum() if len(pnl) else 0.0,
                "average_net_pnl_sek": pnl.mean() if len(pnl) else np.nan,
                "median_net_pnl_sek": pnl.median() if len(pnl) else np.nan,
                "profit_factor": _profit_factor(pnl),
                "average_net_return": net_returns.mean() if len(net_returns) else np.nan,
                "average_trade_duration_minutes": pd.to_numeric(regime_trades.get("trade_duration_minutes"), errors="coerce").mean() if not regime_trades.empty else np.nan,
                "performance_status": status,
            }
        )
    return pd.DataFrame(rows, columns=PERFORMANCE_COLUMNS)


def build_summary(
    sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    legs: pd.DataFrame,
    performance: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    pnl = pd.to_numeric(trades.get("net_pnl_sek"), errors="coerce") if not trades.empty else pd.Series(dtype="float64")
    trade_leg_diff = 0.0
    if not trades.empty or not legs.empty:
        trade_by_id = trades.groupby("trade_id")["net_pnl_sek"].sum() if not trades.empty else pd.Series(dtype="float64")
        leg_by_id = legs.groupby("trade_id")["net_pnl_sek"].sum() if not legs.empty else pd.Series(dtype="float64")
        reconciliation = pd.concat([trade_by_id.rename("trade"), leg_by_id.rename("legs")], axis=1).fillna(0.0)
        trade_leg_diff = float((reconciliation["trade"] - reconciliation["legs"]).abs().max()) if not reconciliation.empty else 0.0
    observed = set(sessions["primary_regime"].astype(str).unique())
    performance_observed = set(performance.loc[performance["regime_sessions"].gt(0), "primary_regime"].astype(str))
    all_processed = observed == performance_observed
    audit_failures = int((~audit["execution_invariant_pass"].fillna(False).astype(bool)).sum()) if not audit.empty else len(sessions)
    classification = (
        "BASELINE_TRADE_GENERATION_READY_FOR_DIAGNOSTIC_REVIEW"
        if len(sessions) > 0
        and all_processed
        and audit_failures == 0
        and trade_leg_diff <= 1e-9
        else "BASELINE_TRADE_GENERATION_MECHANICAL_REVIEW_REQUIRED"
    )
    single_trades = trades[trades["idea_type"].eq("SINGLE")] if not trades.empty else trades
    pair_trades = trades[trades["idea_type"].eq("PAIR")] if not trades.empty else trades
    return pd.DataFrame(
        [
            {
                "simulation_id": SIMULATION_ID,
                "research_status": RESEARCH_STATUS,
                "decision_time": DECISION_TIME,
                "latest_router_bar_label": LATEST_ROUTER_BAR_LABEL,
                "execution_observation_start": EXECUTION_OBSERVATION_START,
                "taxonomy_sessions": len(sessions),
                "processed_sessions": int(audit["date"].nunique()) if not audit.empty else 0,
                "active_response_sessions": len(sessions),
                "observed_regimes": len(observed),
                "specified_playbooks": len(PLAYBOOKS),
                "regimes_with_selected_ideas": int(candidates.loc[candidates["selected_for_simulation"].fillna(False).astype(bool), "primary_regime"].nunique()) if not candidates.empty else 0,
                "regimes_with_triggered_trades": int(trades["primary_regime"].nunique()) if not trades.empty else 0,
                "candidate_rows": len(candidates),
                "selected_ideas": int(candidates["selected_for_simulation"].fillna(False).astype(bool).sum()) if not candidates.empty else 0,
                "triggered_trades": len(trades),
                "closed_trades": len(trades),
                "sessions_with_triggered_trades": int(trades["date"].nunique()) if not trades.empty else 0,
                "sessions_active_no_trigger": int(
                    len(
                        set(
                            candidates.loc[
                                candidates["selected_for_simulation"].fillna(False).astype(bool),
                                "date",
                            ].astype(str)
                        )
                        - set(trades["date"].astype(str))
                    )
                ) if not candidates.empty else 0,
                "sessions_active_no_valid_setup": int(
                    len(set(sessions["date"].astype(str)) - set(
                        candidates.loc[
                            candidates["selected_for_simulation"].fillna(False).astype(bool),
                            "date",
                        ].astype(str)
                    ))
                ) if not candidates.empty else len(sessions),
                "single_leg_trades": len(single_trades),
                "paired_trades": len(pair_trades),
                "long_legs": int(legs["side"].eq("LONG").sum()) if not legs.empty else 0,
                "short_legs": int(legs["side"].eq("SHORT").sum()) if not legs.empty else 0,
                "gross_pnl_sek_unconstrained": pd.to_numeric(trades.get("gross_pnl_sek"), errors="coerce").sum() if not trades.empty else 0.0,
                "cost_sek_unconstrained": pd.to_numeric(trades.get("cost_sek"), errors="coerce").sum() if not trades.empty else 0.0,
                "net_pnl_sek_unconstrained": pnl.sum() if len(pnl) else 0.0,
                "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
                "profit_factor": _profit_factor(pnl),
                "point_in_time_audit_pass_sessions": int(audit["execution_invariant_pass"].fillna(False).astype(bool).sum()) if not audit.empty else 0,
                "point_in_time_audit_fail_sessions": audit_failures,
                "execution_invariant_failures": audit_failures,
                "trade_leg_reconciliation_max_abs_diff_sek": trade_leg_diff,
                "all_observed_regimes_processed": all_processed,
                "classification": classification,
            }
        ],
        columns=SUMMARY_COLUMNS,
    )


def run_baseline_trade_generation(
    taxonomy_file: Path = TAXONOMY_FILE,
    coverage_file: Path = COVERAGE_FILE,
    db_path: Path = INTRADAY_DB,
):
    if not taxonomy_file.exists():
        raise FileNotFoundError(f"Missing Step 8 taxonomy file: {taxonomy_file}")
    if not coverage_file.exists():
        raise FileNotFoundError(f"Missing Step 9A coverage file: {coverage_file}")
    taxonomy = pd.read_csv(taxonomy_file)
    coverage = pd.read_csv(coverage_file)
    prices = load_intraday_prices(db_path)
    return build_baseline_simulation(taxonomy, coverage, prices)


def main() -> None:
    print("\n=== STEP 9B BASELINE PLAYBOOK TRADE GENERATION ===")
    print(f"Simulation       : {SIMULATION_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Router cutoff    : {LATEST_ROUTER_BAR_LABEL}")
    print(f"Execution starts : {EXECUTION_OBSERVATION_START}")
    print("This step generates unconstrained mechanical baseline trades by assigned playbook.")
    print("It does not yet combine playbooks in a shared account and does not validate profitability.")

    summary, sessions, candidates, trades, legs, performance, audit = run_baseline_trade_generation()
    outputs = [
        (summary, SUMMARY_FILE),
        (sessions, SESSION_FILE),
        (candidates, CANDIDATE_FILE),
        (trades, TRADE_FILE),
        (legs, LEG_FILE),
        (performance, PERFORMANCE_FILE),
        (audit, AUDIT_FILE),
    ]
    for dataframe, path in outputs:
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")

    result = summary.iloc[0]
    print("\n=== STEP 9B BASELINE TRADE GENERATION RESULT ===")
    print(f"Taxonomy / processed sessions : {int(result['taxonomy_sessions'])}/{int(result['processed_sessions'])}")
    print(f"Observed regimes              : {int(result['observed_regimes'])}")
    print(f"Candidate rows                : {int(result['candidate_rows'])}")
    print(f"Selected ideas                : {int(result['selected_ideas'])}")
    print(f"Triggered / closed trades     : {int(result['triggered_trades'])}/{int(result['closed_trades'])}")
    print(f"Regimes with triggered trades : {int(result['regimes_with_triggered_trades'])}/{int(result['observed_regimes'])}")
    print(f"PIT audit pass sessions       : {int(result['point_in_time_audit_pass_sessions'])}/{int(result['taxonomy_sessions'])}")
    print(f"Execution invariant failures  : {int(result['execution_invariant_failures'])}")
    print(f"Leg reconciliation max diff   : {float(result['trade_leg_reconciliation_max_abs_diff_sek']):.12f} SEK")
    print(f"Unconstrained net P&L         : {float(result['net_pnl_sek_unconstrained']):.2f} SEK")
    print(f"Classification                : {result['classification']}")
    print("Step 9B export complete. Review playbook-level diagnostics before shared-account simulation.")


if __name__ == "__main__":
    main()
