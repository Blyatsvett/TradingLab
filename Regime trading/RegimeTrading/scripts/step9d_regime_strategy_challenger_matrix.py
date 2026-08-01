from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, legacy_output_path
from RegimeTrading.core.research_config import ORB_COST_PER_TRADE, ORB_INITIAL_CAPITAL, ORB_POSITION_SIZE
from RegimeTrading.scripts.research_regime_aware_gap_recovery import build_daily_reference, load_intraday_prices
from RegimeTrading.scripts.step8_provisional_regime_taxonomy import REGIMES
from RegimeTrading.scripts.step9b_baseline_trade_generation import (
    BASELINE_NOTIONAL_SEK,
    BAR_INTERVAL_MINUTES,
    CANDIDATE_FILE as BASELINE_CANDIDATE_FILE,
    LEG_FILE as BASELINE_LEG_FILE,
    SESSION_FILE as BASELINE_SESSION_FILE,
    TRADE_FILE as BASELINE_TRADE_FILE,
    _bars_between,
    _clock,
    _common_pair_bars,
    _directional_execution,
    _first_bar_between,
    _first_breakout,
    _iso,
    _next_bar_after,
    _num,
    _pair_execution,
    build_market_state,
)


MATRIX_ID = "REGIME_STRATEGY_CHALLENGER_MATRIX_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_CONTROLLED_CHALLENGER_DISCOVERY_NOT_OPTIMIZED"
LATEST_ROUTER_BAR_LABEL = "09:40"
EXECUTION_START = "09:45"
MINIMUM_SCREENING_TRADES = 8
MINIMUM_SCREENING_SESSIONS = 4
ROUND_TRIP_COST_RATE = float(ORB_COST_PER_TRADE)
MAX_NOTIONAL_SEK = float(ORB_INITIAL_CAPITAL) * float(ORB_POSITION_SIZE)
FULL_RISK_BUDGET_SEK = MAX_NOTIONAL_SEK * 0.005
MAX_RANGE_RISK_PCT = 0.03
PAIR_MIN_SPREAD = 0.0030

TAXONOMY_FILE = legacy_output_path("regime_daily_taxonomy.csv")
SUMMARY_FILE = legacy_output_path("regime_challenger_matrix_summary.csv")
REGISTRY_FILE = legacy_output_path("regime_challenger_registry.csv")
CANDIDATE_FILE = legacy_output_path("regime_challenger_candidates.csv")
TRADE_FILE = legacy_output_path("regime_challenger_trades.csv")
LEG_FILE = legacy_output_path("regime_challenger_trade_legs.csv")
PERFORMANCE_FILE = legacy_output_path("regime_challenger_performance.csv")
RANKING_FILE = legacy_output_path("regime_challenger_rankings.csv")
SESSION_FILE = legacy_output_path("regime_challenger_session_coverage.csv")
AUDIT_FILE = legacy_output_path("regime_challenger_audit.csv")

CHALLENGERS = [
    {
        "challenger_id": "ROUTED_BASELINE_CONTROL_V1",
        "strategy_family": "ROUTED_BASELINE_CONTROL",
        "control_status": "FROZEN_STEP9B_CONTROL",
        "idea_type": "MIXED",
        "hypothesis": "Preserve the exact Step 9B routed baseline as the comparison control.",
        "entry_model": "Existing Step 9B contract by primary regime.",
        "stop_model": "Existing Step 9B contract by primary regime.",
        "target_model": "Existing Step 9B contract by primary regime.",
        "exit_cutoff": "PLAYBOOK_SPECIFIC",
        "selection_model": "Existing Step 9B routed basket.",
        "direction_model": "PLAYBOOK_SPECIFIC",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "Frozen control; no hypothesis change.",
        "ranking_eligible": False,
    },
    {
        "challenger_id": "STRICT_GAP_RECOVERY_CROSS_REGIME_V1",
        "strategy_family": "GAP_RECOVERY",
        "control_status": "CHALLENGER",
        "idea_type": "SINGLE",
        "hypothesis": "Strict gap recovery may work outside sessions labelled RECOVERY.",
        "entry_model": "First reclaim of 09:30 opening-bar high from 09:45 through 13:00.",
        "stop_model": "09:30 opening-bar low.",
        "target_model": "Previous official close.",
        "exit_cutoff": "16:30",
        "selection_model": "Negative gaps from -2.0% through -0.1%; deterministic ticker order; max router ideas.",
        "direction_model": "LONG_ONLY",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "Recovery sample too small and prior broader strict-V2 evidence differed from routed sample.",
        "ranking_eligible": True,
    },
    {
        "challenger_id": "ORB_CONTINUATION_IMMEDIATE_1R_V1",
        "strategy_family": "OPENING_RANGE_CONTINUATION",
        "control_status": "CHALLENGER",
        "idea_type": "SINGLE",
        "hypothesis": "Immediate opening-range continuation can work when risk is capped consistently.",
        "entry_model": "First strict 09:30-09:40 range break from 09:45 through 13:00.",
        "stop_model": "Opposite strict early-range boundary.",
        "target_model": "1.0R.",
        "exit_cutoff": "16:30",
        "selection_model": "Rank aligned positive/negative 09:40 moves by absolute strength; max router ideas.",
        "direction_model": "SESSION_BIAS_ALIGNED_OR_CROSS_SECTIONAL_SIGN",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "Trend baselines showed uneven monetary risk under equal notional sizing.",
        "ranking_eligible": True,
    },
    {
        "challenger_id": "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1",
        "strategy_family": "OPENING_RANGE_CONTINUATION",
        "control_status": "CHALLENGER",
        "idea_type": "SINGLE",
        "hypothesis": "A close-confirmed breakout with next-bar entry reduces false 09:45 breaks.",
        "entry_model": "First close beyond strict range, then next-bar open through 13:00.",
        "stop_model": "Opposite strict early-range boundary.",
        "target_model": "1.0R from actual entry.",
        "exit_cutoff": "16:30",
        "selection_model": "Same point-in-time ranking as immediate continuation.",
        "direction_model": "SESSION_BIAS_ALIGNED_OR_CROSS_SECTIONAL_SIGN",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "Most baseline losses occurred in entries before 10:00; confirmation is tested instead of arbitrary delay.",
        "ranking_eligible": True,
    },
    {
        "challenger_id": "RANGE_REJECTION_REVERSION_1_25R_V1",
        "strategy_family": "RANGE_REVERSION",
        "control_status": "CHALLENGER",
        "idea_type": "SINGLE",
        "hypothesis": "Boundary rejection contains signal but requires a larger standardized payoff.",
        "entry_model": "Boundary test and close back inside, followed by next-bar entry through 14:00.",
        "stop_model": "One strict early-range width beyond the rejected boundary.",
        "target_model": "1.25R from actual entry.",
        "exit_cutoff": "15:30",
        "selection_model": "Rank absolute 09:40 deviation from early midpoint; max router ideas.",
        "direction_model": "FADE_CUTOFF_DEVIATION",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "Range baseline had positive gross signal and best standardized diagnostic at 1.25R.",
        "ranking_eligible": True,
    },
    {
        "challenger_id": "EARLY_MOVE_CONTINUATION_1_5R_V1",
        "strategy_family": "EARLY_MOVE_CONTINUATION",
        "control_status": "CHALLENGER",
        "idea_type": "SINGLE",
        "hypothesis": "Large early moves are more often continuation setups than immediate reversal setups.",
        "entry_model": "Break of the 09:40 bar in the direction of the 09:40 return from open through 13:00.",
        "stop_model": "Opposite side of the 09:40 bar.",
        "target_model": "1.5R.",
        "exit_cutoff": "16:30",
        "selection_model": "Rank absolute 09:40 return from open; require at least 0.10%; max router ideas.",
        "direction_model": "EARLY_MOVE_DIRECTION",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "High-vol reversal had weak MFE and was marked REPLACE.",
        "ranking_eligible": True,
    },
    {
        "challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "strategy_family": "DELAYED_REVERSAL",
        "control_status": "CHALLENGER",
        "idea_type": "SINGLE",
        "hypothesis": "Reversal requires a later structural break rather than a 09:40 pivot alone.",
        "entry_model": "After 10:00, first close through the early midpoint against the initial move, then next-bar open.",
        "stop_model": "Strict early-session extreme against the reversal.",
        "target_model": "1.0R from actual entry.",
        "exit_cutoff": "16:30",
        "selection_model": "Rank absolute 09:40 return from open; require at least 0.10%; max router ideas.",
        "direction_model": "OPPOSITE_EARLY_MOVE_AFTER_MIDPOINT_CONFIRMATION",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "Tests a conceptually stronger reversal rather than tuning the failed immediate reversal.",
        "ranking_eligible": True,
    },
    {
        "challenger_id": "DIRECTIONAL_VOLATILITY_BREAKOUT_2R_V1",
        "strategy_family": "VOLATILITY_BREAKOUT",
        "control_status": "CHALLENGER",
        "idea_type": "SINGLE",
        "hypothesis": "Volatility breakouts require more payoff room than the original 1.5R target.",
        "entry_model": "First strict early-range break in session direction bias; neutral sessions are two-sided.",
        "stop_model": "Strict early-range midpoint.",
        "target_model": "2.0R.",
        "exit_cutoff": "16:30",
        "selection_model": "Rank early range plus absolute early return; max router ideas.",
        "direction_model": "SESSION_DIRECTION_BIAS",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "Volatility-expansion target diagnostics improved materially at 2.0R.",
        "ranking_eligible": True,
    },
    {
        "challenger_id": "PAIR_RELATIVE_STRENGTH_CONTINUATION_V1",
        "strategy_family": "CROSS_SECTIONAL_PAIR",
        "control_status": "CHALLENGER",
        "idea_type": "PAIR",
        "hypothesis": "Early cross-sectional leaders continue outperforming laggards when dispersion is large enough.",
        "entry_model": "Synchronized first bar open from 09:45 through 10:00.",
        "stop_model": "Pair loss of max(0.15%, 25% of initial spread).",
        "target_model": "Pair gain of max(0.10%, 25% of initial spread).",
        "exit_cutoff": "15:30",
        "selection_model": "Long strongest and short weakest 09:40 return; minimum 0.30% spread.",
        "direction_model": "LONG_STRONGEST_SHORT_WEAKEST",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "High-dispersion baseline was gross-flat; direction needs a clean controlled comparison.",
        "ranking_eligible": True,
    },
    {
        "challenger_id": "PAIR_SPREAD_CONVERGENCE_V1",
        "strategy_family": "CROSS_SECTIONAL_PAIR",
        "control_status": "CHALLENGER",
        "idea_type": "PAIR",
        "hypothesis": "Early cross-sectional extremes mean-revert when dispersion is large enough.",
        "entry_model": "Synchronized first bar open from 09:45 through 10:00.",
        "stop_model": "Pair loss of max(0.15%, 25% of initial spread).",
        "target_model": "Pair gain of max(0.10%, 25% of initial spread).",
        "exit_cutoff": "15:30",
        "selection_model": "Long weakest and short strongest 09:40 return; minimum 0.30% spread.",
        "direction_model": "LONG_WEAKEST_SHORT_STRONGEST",
        "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
        "diagnostic_source": "Same pair and symmetric exits isolate convergence versus continuation.",
        "ranking_eligible": True,
    },
]
CHALLENGER_BY_ID = {row["challenger_id"]: row for row in CHALLENGERS}
GENERATED_CHALLENGERS = [row for row in CHALLENGERS if row["control_status"] == "CHALLENGER"]

SUMMARY_COLUMNS = [
    "matrix_id", "research_status", "router_cutoff", "execution_start", "taxonomy_sessions",
    "observed_regimes", "registered_challengers", "generated_challengers", "matrix_cells",
    "candidate_rows", "generated_trades", "control_trades", "total_comparison_trades",
    "screenable_cells", "positive_gross_cells_risk_capped", "positive_net_cells_risk_capped",
    "regimes_with_positive_net_challenger", "point_in_time_audit_pass_challengers",
    "execution_invariant_failures", "trade_leg_reconciliation_max_abs_diff_equal_notional_sek",
    "trade_leg_reconciliation_max_abs_diff_risk_capped_sek", "strategies_promoted",
    "classification",
]
REGISTRY_COLUMNS = [
    "matrix_id", "challenger_id", "strategy_family", "control_status", "idea_type", "hypothesis",
    "entry_model", "stop_model", "target_model", "exit_cutoff", "selection_model", "direction_model",
    "sizing_model", "diagnostic_source", "ranking_eligible",
]
CANDIDATE_COLUMNS = [
    "matrix_id", "date", "primary_regime", "challenger_id", "idea_id", "idea_type", "ticker",
    "paired_ticker", "long_ticker", "short_ticker", "direction", "ranking_metric", "selection_rank",
    "selected_for_simulation", "setup_status", "trigger_status", "invalid_reason", "opening_gap",
    "previous_close", "early_open", "early_high", "early_low", "early_midpoint", "cutoff_close",
    "cutoff_return_from_open", "paired_cutoff_return_from_open", "early_range_pct", "signal_time",
    "entry_time", "entry_price", "stop_price", "target_price", "pair_entry_long_price",
    "pair_entry_short_price", "pair_stop_return", "pair_target_return", "exit_time", "exit_reason",
    "max_router_source_label", "point_in_time_pass", "mechanical_interpretation",
]
TRADE_COLUMNS = [
    "matrix_id", "trade_id", "date", "primary_regime", "challenger_id", "strategy_family", "control_status",
    "idea_type", "direction", "ticker", "paired_ticker", "long_ticker", "short_ticker", "regime_confidence",
    "confidence_band", "direction_bias", "entry_time", "entry_price", "stop_price", "target_price",
    "pair_entry_long_price", "pair_entry_short_price", "pair_stop_return", "pair_target_return", "exit_time",
    "exit_price", "pair_exit_long_price", "pair_exit_short_price", "exit_reason", "gross_return",
    "risk_pct_at_entry", "r_multiple_achieved", "trade_duration_minutes", "research_risk_multiplier",
    "equal_notional_sek", "equal_gross_pnl_sek", "equal_cost_sek", "equal_net_pnl_sek",
    "risk_capped_notional_sek", "risk_capped_gross_pnl_sek", "risk_capped_cost_sek", "risk_capped_net_pnl_sek",
    "point_in_time_pass", "execution_invariant_pass",
]
LEG_COLUMNS = [
    "matrix_id", "trade_id", "leg_id", "date", "primary_regime", "challenger_id", "ticker", "side",
    "entry_time", "entry_price", "exit_time", "exit_price", "exit_reason", "equal_notional_sek",
    "equal_gross_pnl_sek", "equal_cost_sek", "equal_net_pnl_sek", "risk_capped_notional_sek",
    "risk_capped_gross_pnl_sek", "risk_capped_cost_sek", "risk_capped_net_pnl_sek",
]
PERFORMANCE_COLUMNS = [
    "matrix_id", "primary_regime", "challenger_id", "strategy_family", "control_status", "ranking_eligible",
    "regime_sessions", "candidate_rows", "valid_setups", "selected_ideas", "trades", "sessions_with_trades",
    "winning_trades_equal_notional", "win_rate_equal_notional", "gross_pnl_equal_notional_sek",
    "cost_equal_notional_sek", "net_pnl_equal_notional_sek", "profit_factor_equal_notional",
    "winning_trades_risk_capped", "win_rate_risk_capped", "gross_pnl_risk_capped_sek",
    "cost_risk_capped_sek", "net_pnl_risk_capped_sek", "average_net_pnl_risk_capped_sek",
    "median_net_pnl_risk_capped_sek", "profit_factor_risk_capped", "average_r_multiple",
    "top_day_abs_pnl_share", "leave_one_day_out_profitable_share", "leave_one_day_out_min_pnl_sek",
    "sample_status", "discovery_status", "baseline_control_net_pnl_risk_capped_sek",
    "incremental_vs_baseline_risk_capped_sek",
]
RANKING_COLUMNS = [
    "matrix_id", "primary_regime", "challenger_id", "strategy_family", "control_status", "ranking_eligible",
    "trades", "sessions_with_trades", "net_pnl_risk_capped_sek", "gross_pnl_risk_capped_sek",
    "profit_factor_risk_capped", "average_r_multiple", "sample_status", "discovery_status",
    "rank_all_challengers", "rank_screenable_challengers", "baseline_control_net_pnl_risk_capped_sek",
    "incremental_vs_baseline_risk_capped_sek", "selection_status",
]
SESSION_COLUMNS = [
    "matrix_id", "date", "primary_regime", "challenger_id", "strategy_family", "control_status",
    "regime_confidence", "confidence_band", "direction_bias", "candidate_rows", "valid_setups",
    "selected_ideas", "trades", "equal_net_pnl_sek", "risk_capped_net_pnl_sek", "minimum_entry_time",
    "maximum_exit_time", "max_router_source_label", "point_in_time_pass", "execution_invariant_pass",
    "session_status",
]
AUDIT_COLUMNS = [
    "matrix_id", "challenger_id", "control_status", "sessions_processed", "candidate_rows", "trades",
    "max_router_source_label", "point_in_time_pass", "minimum_entry_time", "entry_time_pass",
    "exit_after_entry_pass", "trade_leg_reconciliation_max_abs_diff_equal_notional_sek",
    "trade_leg_reconciliation_max_abs_diff_risk_capped_sek", "execution_invariant_pass", "audit_status",
]


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if pd.isna(value):
        return False
    return bool(value)


def _profit_factor(values: Iterable[float]) -> float:
    pnl = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if pnl.empty:
        return np.nan
    gains = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl < 0].sum()))
    if losses == 0:
        return np.nan
    return gains / losses


def _risk_notionals(risk_pct: float, risk_multiplier: float) -> tuple[float, float]:
    equal_notional = MAX_NOTIONAL_SEK * max(float(risk_multiplier), 0.0)
    risk_budget = FULL_RISK_BUDGET_SEK * max(float(risk_multiplier), 0.0)
    if not np.isfinite(risk_pct) or risk_pct <= 0:
        return equal_notional, equal_notional
    risk_capped = min(equal_notional, risk_budget / float(risk_pct))
    return float(equal_notional), max(float(risk_capped), 0.0)


def _base_candidate(session: dict, challenger: dict, idea_id: str, idea_type: str) -> dict:
    return {
        "matrix_id": MATRIX_ID,
        "date": str(session["date"]),
        "primary_regime": str(session["primary_regime"]),
        "challenger_id": challenger["challenger_id"],
        "idea_id": idea_id,
        "idea_type": idea_type,
        "ticker": "",
        "paired_ticker": "",
        "long_ticker": "",
        "short_ticker": "",
        "direction": "",
        "ranking_metric": np.nan,
        "selection_rank": np.nan,
        "selected_for_simulation": False,
        "setup_status": "NOT_EVALUATED",
        "trigger_status": "NOT_EVALUATED",
        "invalid_reason": "",
        "opening_gap": np.nan,
        "previous_close": np.nan,
        "early_open": np.nan,
        "early_high": np.nan,
        "early_low": np.nan,
        "early_midpoint": np.nan,
        "cutoff_close": np.nan,
        "cutoff_return_from_open": np.nan,
        "paired_cutoff_return_from_open": np.nan,
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
        "exit_reason": "",
        "max_router_source_label": "",
        "point_in_time_pass": False,
        "mechanical_interpretation": "",
    }


def _add_state(candidate: dict, state: dict) -> None:
    for key in [
        "ticker", "opening_gap", "previous_close", "early_open", "early_high", "early_low",
        "early_midpoint", "cutoff_close", "cutoff_return_from_open", "early_range_pct",
        "max_router_source_label",
    ]:
        candidate[key] = state.get(key, candidate.get(key))
    candidate["point_in_time_pass"] = str(candidate.get("max_router_source_label", "")) <= LATEST_ROUTER_BAR_LABEL


def _select_candidates(rows: list[dict], max_ideas: int, deterministic: bool = False) -> None:
    valid = [row for row in rows if row["setup_status"] == "VALID_SETUP"]
    if deterministic:
        valid.sort(key=lambda row: (str(row.get("ticker", "")), str(row.get("paired_ticker", ""))))
    else:
        valid.sort(
            key=lambda row: (
                -_num(row.get("ranking_metric"), -np.inf),
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


def _direction_allowed(side: str, direction_bias: str) -> bool:
    bias = str(direction_bias).upper()
    if bias == "UP":
        return side == "LONG"
    if bias == "DOWN":
        return side == "SHORT"
    return True


def _append_single_trade(
    candidate: dict,
    session: dict,
    challenger: dict,
    execution,
    side: str,
    entry_time: pd.Timestamp,
    entry_price: float,
    stop_price: float,
    target_price: float,
    trades: list[dict],
    legs: list[dict],
) -> None:
    risk_pct = abs(entry_price - stop_price) / entry_price if entry_price > 0 else np.nan
    multiplier = _num(session.get("research_risk_multiplier"), 1.0)
    equal_notional, risk_capped_notional = _risk_notionals(risk_pct, multiplier)
    equal_gross = equal_notional * execution.gross_return
    equal_cost = equal_notional * ROUND_TRIP_COST_RATE
    risk_gross = risk_capped_notional * execution.gross_return
    risk_cost = risk_capped_notional * ROUND_TRIP_COST_RATE
    trade_id = f"{candidate['idea_id']}|TRADE"
    row = {
        "matrix_id": MATRIX_ID,
        "trade_id": trade_id,
        "date": candidate["date"],
        "primary_regime": candidate["primary_regime"],
        "challenger_id": challenger["challenger_id"],
        "strategy_family": challenger["strategy_family"],
        "control_status": challenger["control_status"],
        "idea_type": "SINGLE",
        "direction": side,
        "ticker": candidate["ticker"],
        "paired_ticker": "",
        "long_ticker": candidate["ticker"] if side == "LONG" else "",
        "short_ticker": candidate["ticker"] if side == "SHORT" else "",
        "regime_confidence": _num(session.get("regime_confidence")),
        "confidence_band": session.get("confidence_band", ""),
        "direction_bias": session.get("direction_bias", ""),
        "entry_time": _iso(entry_time),
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
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
        "risk_pct_at_entry": risk_pct,
        "r_multiple_achieved": execution.r_multiple,
        "trade_duration_minutes": execution.duration_minutes,
        "research_risk_multiplier": multiplier,
        "equal_notional_sek": equal_notional,
        "equal_gross_pnl_sek": equal_gross,
        "equal_cost_sek": equal_cost,
        "equal_net_pnl_sek": equal_gross - equal_cost,
        "risk_capped_notional_sek": risk_capped_notional,
        "risk_capped_gross_pnl_sek": risk_gross,
        "risk_capped_cost_sek": risk_cost,
        "risk_capped_net_pnl_sek": risk_gross - risk_cost,
        "point_in_time_pass": candidate["point_in_time_pass"],
        "execution_invariant_pass": _clock(entry_time) >= EXECUTION_START and execution.exit_time >= entry_time,
    }
    trades.append(row)
    legs.append(
        {
            "matrix_id": MATRIX_ID,
            "trade_id": trade_id,
            "leg_id": f"{trade_id}|LEG1",
            "date": candidate["date"],
            "primary_regime": candidate["primary_regime"],
            "challenger_id": challenger["challenger_id"],
            "ticker": candidate["ticker"],
            "side": side,
            "entry_time": _iso(entry_time),
            "entry_price": entry_price,
            "exit_time": _iso(execution.exit_time),
            "exit_price": execution.exit_price,
            "exit_reason": execution.exit_reason,
            "equal_notional_sek": equal_notional,
            "equal_gross_pnl_sek": equal_gross,
            "equal_cost_sek": equal_cost,
            "equal_net_pnl_sek": equal_gross - equal_cost,
            "risk_capped_notional_sek": risk_capped_notional,
            "risk_capped_gross_pnl_sek": risk_gross,
            "risk_capped_cost_sek": risk_cost,
            "risk_capped_net_pnl_sek": risk_gross - risk_cost,
        }
    )
    candidate.update(
        {
            "trigger_status": "TRIGGERED_CLOSED",
            "entry_time": _iso(entry_time),
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "exit_time": _iso(execution.exit_time),
            "exit_reason": execution.exit_reason,
        }
    )


def _append_pair_trade(
    candidate: dict,
    session: dict,
    challenger: dict,
    execution,
    entry_time: pd.Timestamp,
    entry_long: float,
    entry_short: float,
    stop_return: float,
    target_return: float,
    trades: list[dict],
    legs: list[dict],
) -> None:
    risk_pct = abs(stop_return)
    multiplier = _num(session.get("research_risk_multiplier"), 1.0)
    equal_notional, risk_capped_notional = _risk_notionals(risk_pct, multiplier)
    equal_leg = equal_notional / 2.0
    risk_leg = risk_capped_notional / 2.0
    equal_long_gross = equal_leg * execution.long_return
    equal_short_gross = equal_leg * execution.short_return
    risk_long_gross = risk_leg * execution.long_return
    risk_short_gross = risk_leg * execution.short_return
    equal_leg_cost = equal_leg * ROUND_TRIP_COST_RATE
    risk_leg_cost = risk_leg * ROUND_TRIP_COST_RATE
    equal_gross = equal_long_gross + equal_short_gross
    risk_gross = risk_long_gross + risk_short_gross
    trade_id = f"{candidate['idea_id']}|TRADE"
    trades.append(
        {
            "matrix_id": MATRIX_ID,
            "trade_id": trade_id,
            "date": candidate["date"],
            "primary_regime": candidate["primary_regime"],
            "challenger_id": challenger["challenger_id"],
            "strategy_family": challenger["strategy_family"],
            "control_status": challenger["control_status"],
            "idea_type": "PAIR",
            "direction": "LONG_SHORT",
            "ticker": candidate["long_ticker"],
            "paired_ticker": candidate["short_ticker"],
            "long_ticker": candidate["long_ticker"],
            "short_ticker": candidate["short_ticker"],
            "regime_confidence": _num(session.get("regime_confidence")),
            "confidence_band": session.get("confidence_band", ""),
            "direction_bias": session.get("direction_bias", ""),
            "entry_time": _iso(entry_time),
            "entry_price": np.nan,
            "stop_price": np.nan,
            "target_price": np.nan,
            "pair_entry_long_price": entry_long,
            "pair_entry_short_price": entry_short,
            "pair_stop_return": stop_return,
            "pair_target_return": target_return,
            "exit_time": _iso(execution.exit_time),
            "exit_price": np.nan,
            "pair_exit_long_price": execution.exit_long_price,
            "pair_exit_short_price": execution.exit_short_price,
            "exit_reason": execution.exit_reason,
            "gross_return": execution.gross_return,
            "risk_pct_at_entry": risk_pct,
            "r_multiple_achieved": execution.gross_return / risk_pct if risk_pct > 0 else np.nan,
            "trade_duration_minutes": execution.duration_minutes,
            "research_risk_multiplier": multiplier,
            "equal_notional_sek": equal_notional,
            "equal_gross_pnl_sek": equal_gross,
            "equal_cost_sek": 2.0 * equal_leg_cost,
            "equal_net_pnl_sek": equal_gross - 2.0 * equal_leg_cost,
            "risk_capped_notional_sek": risk_capped_notional,
            "risk_capped_gross_pnl_sek": risk_gross,
            "risk_capped_cost_sek": 2.0 * risk_leg_cost,
            "risk_capped_net_pnl_sek": risk_gross - 2.0 * risk_leg_cost,
            "point_in_time_pass": candidate["point_in_time_pass"],
            "execution_invariant_pass": _clock(entry_time) >= EXECUTION_START and execution.exit_time >= entry_time,
        }
    )
    leg_specs = [
        (candidate["long_ticker"], "LONG", entry_long, execution.exit_long_price, execution.long_return, equal_long_gross, risk_long_gross),
        (candidate["short_ticker"], "SHORT", entry_short, execution.exit_short_price, execution.short_return, equal_short_gross, risk_short_gross),
    ]
    for idx, (ticker, side, entry, exit_price, gross_return, equal_gross_leg, risk_gross_leg) in enumerate(leg_specs, 1):
        legs.append(
            {
                "matrix_id": MATRIX_ID,
                "trade_id": trade_id,
                "leg_id": f"{trade_id}|LEG{idx}",
                "date": candidate["date"],
                "primary_regime": candidate["primary_regime"],
                "challenger_id": challenger["challenger_id"],
                "ticker": ticker,
                "side": side,
                "entry_time": _iso(entry_time),
                "entry_price": entry,
                "exit_time": _iso(execution.exit_time),
                "exit_price": exit_price,
                "exit_reason": execution.exit_reason,
                "equal_notional_sek": equal_leg,
                "equal_gross_pnl_sek": equal_gross_leg,
                "equal_cost_sek": equal_leg_cost,
                "equal_net_pnl_sek": equal_gross_leg - equal_leg_cost,
                "risk_capped_notional_sek": risk_leg,
                "risk_capped_gross_pnl_sek": risk_gross_leg,
                "risk_capped_cost_sek": risk_leg_cost,
                "risk_capped_net_pnl_sek": risk_gross_leg - risk_leg_cost,
            }
        )
    candidate.update(
        {
            "trigger_status": "TRIGGERED_CLOSED",
            "entry_time": _iso(entry_time),
            "pair_entry_long_price": entry_long,
            "pair_entry_short_price": entry_short,
            "pair_stop_return": stop_return,
            "pair_target_return": target_return,
            "exit_time": _iso(execution.exit_time),
            "exit_reason": execution.exit_reason,
        }
    )


def _single_candidates_for_challenger(
    session: dict,
    challenger: dict,
    states: pd.DataFrame,
    bars_lookup: dict[tuple[str, str], pd.DataFrame],
    trades: list[dict],
    legs: list[dict],
) -> list[dict]:
    cid = challenger["challenger_id"]
    date = str(session["date"])
    rows: list[dict] = []
    max_ideas = int(_num(session.get("research_max_concurrent_ideas"), 2))
    direction_bias = str(session.get("direction_bias", "NEUTRAL"))

    for state in states.sort_values("ticker").to_dict("records"):
        ticker = str(state["ticker"])
        candidate = _base_candidate(session, challenger, f"{date}|{cid}|{ticker}", "SINGLE")
        _add_state(candidate, state)
        candidate["setup_status"] = "VALID_SETUP"
        invalid: list[str] = []
        early_open = _num(state.get("early_open"))
        early_high = _num(state.get("early_high"))
        early_low = _num(state.get("early_low"))
        early_mid = _num(state.get("early_midpoint"))
        early_range_pct = _num(state.get("early_range_pct"))
        cutoff_close = _num(state.get("cutoff_close"))
        cutoff_return = _num(state.get("cutoff_return_from_open"))
        previous_close = _num(state.get("previous_close"))
        opening_gap = _num(state.get("opening_gap"))
        close_0940 = _num(state.get("close_0940"))
        high_0940 = _num(state.get("high_0940"))
        low_0940 = _num(state.get("low_0940"))

        if cid == "STRICT_GAP_RECOVERY_CROSS_REGIME_V1":
            candidate["direction"] = "LONG"
            candidate["ranking_metric"] = 0.0
            candidate["entry_price"] = _num(state.get("opening_bar_high"))
            candidate["stop_price"] = _num(state.get("opening_bar_low"))
            candidate["target_price"] = previous_close
            candidate["mechanical_interpretation"] = "STRICT_0930_RECLAIM_CROSS_REGIME"
            if not np.isfinite(opening_gap) or opening_gap < -0.0200 or opening_gap > -0.0010:
                invalid.append("GAP_OUTSIDE_RANGE")
            if not np.isfinite(previous_close):
                invalid.append("MISSING_PREVIOUS_CLOSE")
            if _num(candidate["target_price"]) <= _num(candidate["entry_price"]):
                invalid.append("TARGET_NOT_ABOVE_ENTRY")
        elif cid in {"ORB_CONTINUATION_IMMEDIATE_1R_V1", "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1"}:
            if cutoff_return > 0:
                side = "LONG"
            elif cutoff_return < 0:
                side = "SHORT"
            else:
                side = ""
                invalid.append("NO_EARLY_DIRECTION")
            candidate["direction"] = side
            candidate["ranking_metric"] = abs(cutoff_return)
            candidate["mechanical_interpretation"] = "IMMEDIATE_ORB_1R" if "IMMEDIATE" in cid else "CLOSE_CONFIRMED_ORB_NEXT_BAR_1R"
            if side and not _direction_allowed(side, direction_bias):
                invalid.append("NOT_ALIGNED_WITH_SESSION_DIRECTION_BIAS")
            if side == "LONG" and np.isfinite(previous_close) and cutoff_close <= previous_close:
                invalid.append("LONG_NOT_ABOVE_PREVIOUS_CLOSE")
            if side == "SHORT" and np.isfinite(previous_close) and cutoff_close >= previous_close:
                invalid.append("SHORT_NOT_BELOW_PREVIOUS_CLOSE")
            if not np.isfinite(early_range_pct) or early_range_pct <= 0 or early_range_pct > MAX_RANGE_RISK_PCT:
                invalid.append("INVALID_OR_WIDE_RANGE")
        elif cid == "RANGE_REJECTION_REVERSION_1_25R_V1":
            candidate["ranking_metric"] = abs(cutoff_close / early_mid - 1.0) if early_mid > 0 else np.nan
            candidate["mechanical_interpretation"] = "BOUNDARY_REJECTION_NEXT_BAR_1_25R"
            if cutoff_close > early_mid:
                candidate["direction"] = "SHORT"
            elif cutoff_close < early_mid:
                candidate["direction"] = "LONG"
            else:
                invalid.append("NO_MIDPOINT_DEVIATION")
            if not np.isfinite(early_range_pct) or early_range_pct <= 0:
                invalid.append("INVALID_EARLY_RANGE")
        elif cid in {"EARLY_MOVE_CONTINUATION_1_5R_V1", "DELAYED_EARLY_MOVE_REVERSAL_1R_V1"}:
            initial_move = close_0940 / early_open - 1.0 if early_open > 0 else np.nan
            candidate["ranking_metric"] = abs(initial_move)
            if not np.isfinite(initial_move) or abs(initial_move) < 0.0010:
                invalid.append("EARLY_MOVE_BELOW_0_10_PERCENT")
            if cid == "EARLY_MOVE_CONTINUATION_1_5R_V1":
                candidate["direction"] = "LONG" if initial_move > 0 else "SHORT"
                candidate["mechanical_interpretation"] = "BREAK_0940_BAR_IN_EARLY_MOVE_DIRECTION_1_5R"
                range_0940_pct = (high_0940 - low_0940) / close_0940 if close_0940 > 0 else np.nan
                if not np.isfinite(range_0940_pct) or range_0940_pct <= 0 or range_0940_pct > MAX_RANGE_RISK_PCT:
                    invalid.append("INVALID_OR_WIDE_0940_BAR")
            else:
                candidate["direction"] = "SHORT" if initial_move > 0 else "LONG"
                candidate["mechanical_interpretation"] = "POST_1000_MIDPOINT_REVERSAL_NEXT_BAR_1R"
        elif cid == "DIRECTIONAL_VOLATILITY_BREAKOUT_2R_V1":
            candidate["ranking_metric"] = early_range_pct + abs(cutoff_return) if np.isfinite(early_range_pct) else np.nan
            bias = direction_bias.upper()
            candidate["direction"] = "LONG" if bias == "UP" else "SHORT" if bias == "DOWN" else "TWO_SIDED"
            candidate["mechanical_interpretation"] = "DIRECTION_BIAS_VOLATILITY_BREAKOUT_2R"
            if not np.isfinite(early_range_pct) or early_range_pct <= 0 or early_range_pct > MAX_RANGE_RISK_PCT:
                invalid.append("INVALID_OR_WIDE_RANGE")
            if bias == "UP" and cutoff_return < 0:
                invalid.append("STOCK_NOT_ALIGNED_UP")
            if bias == "DOWN" and cutoff_return > 0:
                invalid.append("STOCK_NOT_ALIGNED_DOWN")
        else:
            invalid.append("UNKNOWN_SINGLE_CHALLENGER")

        if invalid:
            candidate["setup_status"] = "INVALID_SETUP"
            candidate["trigger_status"] = "NOT_EVALUATED"
            candidate["invalid_reason"] = ";".join(sorted(set(invalid)))
        rows.append(candidate)

    _select_candidates(rows, max_ideas=max_ideas, deterministic=cid == "STRICT_GAP_RECOVERY_CROSS_REGIME_V1")

    for candidate in rows:
        if not candidate["selected_for_simulation"]:
            continue
        bars = bars_lookup.get((date, str(candidate["ticker"])), pd.DataFrame())
        side = str(candidate["direction"])
        trigger = None
        signal_time = ""
        exit_cutoff = challenger["exit_cutoff"]
        stop = np.nan
        target = np.nan

        if cid == "STRICT_GAP_RECOVERY_CROSS_REGIME_V1":
            trigger = _first_breakout(bars, "LONG", _num(candidate["entry_price"]), "09:45", "13:00")
            stop = _num(candidate["stop_price"])
            target = _num(candidate["target_price"])
        elif cid == "ORB_CONTINUATION_IMMEDIATE_1R_V1":
            trigger_level = _num(candidate["early_high"]) if side == "LONG" else _num(candidate["early_low"])
            trigger = _first_breakout(bars, side, trigger_level, "09:45", "13:00")
            if trigger is not None:
                actual_entry = trigger[1]
                stop = _num(candidate["early_low"]) if side == "LONG" else _num(candidate["early_high"])
                risk = actual_entry - stop if side == "LONG" else stop - actual_entry
                target = actual_entry + risk if side == "LONG" else actual_entry - risk
        elif cid == "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1":
            window = _bars_between(bars, "09:45", "12:55")
            signal_bar = None
            for _, bar in window.iterrows():
                close = _num(bar.get("close"))
                if side == "LONG" and close > _num(candidate["early_high"]):
                    signal_bar = bar
                    break
                if side == "SHORT" and close < _num(candidate["early_low"]):
                    signal_bar = bar
                    break
            if signal_bar is not None:
                next_bar = _next_bar_after(bars, pd.Timestamp(signal_bar["datetime"]))
                if next_bar is not None and _clock(next_bar["datetime"]) <= "13:00":
                    actual_entry = _num(next_bar.get("open"), _num(next_bar.get("close")))
                    trigger = (next_bar, actual_entry)
                    signal_time = _iso(pd.Timestamp(signal_bar["datetime"]) + pd.Timedelta(minutes=BAR_INTERVAL_MINUTES))
                    stop = _num(candidate["early_low"]) if side == "LONG" else _num(candidate["early_high"])
                    risk = actual_entry - stop if side == "LONG" else stop - actual_entry
                    target = actual_entry + risk if side == "LONG" else actual_entry - risk
        elif cid == "RANGE_REJECTION_REVERSION_1_25R_V1":
            signal_window = _bars_between(bars, "09:45", "13:55")
            signal_bar = None
            for _, bar in signal_window.iterrows():
                if side == "SHORT" and _num(bar.get("high")) >= _num(candidate["early_high"]) and _num(bar.get("close")) < _num(candidate["early_high"]):
                    signal_bar = bar
                    break
                if side == "LONG" and _num(bar.get("low")) <= _num(candidate["early_low"]) and _num(bar.get("close")) > _num(candidate["early_low"]):
                    signal_bar = bar
                    break
            if signal_bar is not None:
                next_bar = _next_bar_after(bars, pd.Timestamp(signal_bar["datetime"]))
                if next_bar is not None and _clock(next_bar["datetime"]) <= "14:00":
                    actual_entry = _num(next_bar.get("open"), _num(next_bar.get("close")))
                    trigger = (next_bar, actual_entry)
                    signal_time = _iso(pd.Timestamp(signal_bar["datetime"]) + pd.Timedelta(minutes=BAR_INTERVAL_MINUTES))
                    width = _num(candidate["early_high"]) - _num(candidate["early_low"])
                    stop = _num(candidate["early_high"]) + width if side == "SHORT" else _num(candidate["early_low"]) - width
                    risk = stop - actual_entry if side == "SHORT" else actual_entry - stop
                    target = actual_entry - 1.25 * risk if side == "SHORT" else actual_entry + 1.25 * risk
        elif cid == "EARLY_MOVE_CONTINUATION_1_5R_V1":
            trigger_level = _num(candidate.get("high_0940"), np.nan)
            if not np.isfinite(trigger_level):
                state_row = states[states["ticker"].eq(candidate["ticker"])]
                trigger_level = _num(state_row.iloc[0].get("high_0940")) if not state_row.empty else np.nan
            if side == "LONG":
                trigger_level = _num(states[states["ticker"].eq(candidate["ticker"])].iloc[0].get("high_0940"))
                stop = _num(states[states["ticker"].eq(candidate["ticker"])].iloc[0].get("low_0940"))
            else:
                trigger_level = _num(states[states["ticker"].eq(candidate["ticker"])].iloc[0].get("low_0940"))
                stop = _num(states[states["ticker"].eq(candidate["ticker"])].iloc[0].get("high_0940"))
            trigger = _first_breakout(bars, side, trigger_level, "09:45", "13:00")
            if trigger is not None:
                actual_entry = trigger[1]
                risk = actual_entry - stop if side == "LONG" else stop - actual_entry
                target = actual_entry + 1.5 * risk if side == "LONG" else actual_entry - 1.5 * risk
        elif cid == "DELAYED_EARLY_MOVE_REVERSAL_1R_V1":
            signal_window = _bars_between(bars, "10:00", "12:55")
            signal_bar = None
            for _, bar in signal_window.iterrows():
                close = _num(bar.get("close"))
                if side == "SHORT" and close < _num(candidate["early_midpoint"]):
                    signal_bar = bar
                    break
                if side == "LONG" and close > _num(candidate["early_midpoint"]):
                    signal_bar = bar
                    break
            if signal_bar is not None:
                next_bar = _next_bar_after(bars, pd.Timestamp(signal_bar["datetime"]))
                if next_bar is not None and _clock(next_bar["datetime"]) <= "13:00":
                    actual_entry = _num(next_bar.get("open"), _num(next_bar.get("close")))
                    trigger = (next_bar, actual_entry)
                    signal_time = _iso(pd.Timestamp(signal_bar["datetime"]) + pd.Timedelta(minutes=BAR_INTERVAL_MINUTES))
                    stop = _num(candidate["early_high"]) if side == "SHORT" else _num(candidate["early_low"])
                    risk = stop - actual_entry if side == "SHORT" else actual_entry - stop
                    target = actual_entry - risk if side == "SHORT" else actual_entry + risk
        elif cid == "DIRECTIONAL_VOLATILITY_BREAKOUT_2R_V1":
            if side == "TWO_SIDED":
                window = _bars_between(bars, "09:45", "12:00")
                for _, bar in window.iterrows():
                    up = _num(bar.get("high")) >= _num(candidate["early_high"])
                    down = _num(bar.get("low")) <= _num(candidate["early_low"])
                    if up and down:
                        candidate["trigger_status"] = "AMBIGUOUS_SAME_BAR_TWO_SIDED_BREAK"
                        candidate["invalid_reason"] = "INTRABAR_BREAK_ORDER_UNKNOWN"
                        break
                    if up:
                        side = "LONG"
                        trigger = (bar, max(_num(candidate["early_high"]), _num(bar.get("open"))))
                        break
                    if down:
                        side = "SHORT"
                        trigger = (bar, min(_num(candidate["early_low"]), _num(bar.get("open"))))
                        break
            else:
                level = _num(candidate["early_high"]) if side == "LONG" else _num(candidate["early_low"])
                trigger = _first_breakout(bars, side, level, "09:45", "12:00")
            if trigger is not None:
                actual_entry = trigger[1]
                stop = _num(candidate["early_midpoint"])
                risk = actual_entry - stop if side == "LONG" else stop - actual_entry
                target = actual_entry + 2.0 * risk if side == "LONG" else actual_entry - 2.0 * risk

        if trigger is None:
            if candidate["trigger_status"] == "SELECTED_NOT_TRIGGERED":
                candidate["trigger_status"] = "NOT_TRIGGERED"
            continue
        entry_bar, actual_entry = trigger
        entry_time = pd.Timestamp(entry_bar["datetime"])
        if not (np.isfinite(actual_entry) and np.isfinite(stop) and np.isfinite(target)):
            candidate["trigger_status"] = "INVALID_TRIGGER_LEVELS"
            candidate["invalid_reason"] = "NONFINITE_ENTRY_STOP_OR_TARGET"
            continue
        risk = actual_entry - stop if side == "LONG" else stop - actual_entry
        reward = target - actual_entry if side == "LONG" else actual_entry - target
        if risk <= 0 or reward <= 0:
            candidate["trigger_status"] = "INVALID_TRIGGER_LEVELS"
            candidate["invalid_reason"] = "NONPOSITIVE_RISK_OR_REWARD"
            continue
        candidate["signal_time"] = signal_time or _iso(entry_time)
        execution = _directional_execution(
            bars=bars,
            side=side,
            entry_time=entry_time,
            entry_price=actual_entry,
            stop_price=stop,
            target_price=target,
            exit_cutoff=exit_cutoff,
        )
        if execution is None:
            candidate["trigger_status"] = "NO_EXECUTABLE_BARS"
            continue
        _append_single_trade(candidate, session, challenger, execution, side, entry_time, actual_entry, stop, target, trades, legs)
    return rows


def _pair_candidate_for_challenger(
    session: dict,
    challenger: dict,
    states: pd.DataFrame,
    bars_lookup: dict[tuple[str, str], pd.DataFrame],
    trades: list[dict],
    legs: list[dict],
) -> list[dict]:
    date = str(session["date"])
    cid = challenger["challenger_id"]
    candidate = _base_candidate(session, challenger, f"{date}|{cid}|PAIR1", "PAIR")
    candidate.update({"setup_status": "VALID_SETUP", "selected_for_simulation": True, "selection_rank": 1, "trigger_status": "SELECTED_NOT_TRIGGERED", "direction": "LONG_SHORT"})
    available_labels = states.get("max_router_source_label", pd.Series(dtype="object")).dropna().astype(str) if not states.empty else pd.Series(dtype="object")
    candidate["max_router_source_label"] = available_labels.max() if not available_labels.empty else LATEST_ROUTER_BAR_LABEL
    candidate["point_in_time_pass"] = candidate["max_router_source_label"] <= LATEST_ROUTER_BAR_LABEL
    usable = states.dropna(subset=["cutoff_return_from_open"]).copy()
    if len(usable) < 2:
        candidate.update({"setup_status": "INVALID_SETUP", "selected_for_simulation": False, "trigger_status": "NOT_EVALUATED", "invalid_reason": "FEWER_THAN_TWO_USABLE_TICKERS"})
        return [candidate]
    ordered = usable.sort_values(["cutoff_return_from_open", "ticker"])
    weakest = ordered.iloc[0]
    strongest = ordered.iloc[-1]
    spread = _num(strongest["cutoff_return_from_open"]) - _num(weakest["cutoff_return_from_open"])
    if spread < PAIR_MIN_SPREAD:
        candidate.update({"setup_status": "INVALID_SETUP", "selected_for_simulation": False, "trigger_status": "NOT_EVALUATED", "invalid_reason": "SPREAD_BELOW_0_30_PERCENT"})
        return [candidate]
    if cid == "PAIR_RELATIVE_STRENGTH_CONTINUATION_V1":
        long_state, short_state = strongest, weakest
        interpretation = "LONG_STRONGEST_SHORT_WEAKEST_SYMMETRIC_CONTROL"
    else:
        long_state, short_state = weakest, strongest
        interpretation = "LONG_WEAKEST_SHORT_STRONGEST_SYMMETRIC_CONTROL"
    long_ticker = str(long_state["ticker"])
    short_ticker = str(short_state["ticker"])
    stop_return = -max(0.0015, 0.25 * spread)
    target_return = max(0.0010, 0.25 * spread)
    candidate.update(
        {
            "ticker": long_ticker,
            "paired_ticker": short_ticker,
            "long_ticker": long_ticker,
            "short_ticker": short_ticker,
            "ranking_metric": spread,
            "cutoff_return_from_open": _num(long_state["cutoff_return_from_open"]),
            "paired_cutoff_return_from_open": _num(short_state["cutoff_return_from_open"]),
            "pair_stop_return": stop_return,
            "pair_target_return": target_return,
            "max_router_source_label": max(str(long_state.get("max_router_source_label", "")), str(short_state.get("max_router_source_label", ""))),
            "mechanical_interpretation": interpretation,
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
    execution = _pair_execution(common, entry_time, entry_long, entry_short, stop_return, target_return, "15:30")
    if execution is None:
        candidate["trigger_status"] = "NO_EXECUTABLE_PAIR_BARS"
        return [candidate]
    _append_pair_trade(candidate, session, challenger, execution, entry_time, entry_long, entry_short, stop_return, target_return, trades, legs)
    return [candidate]


def _control_rows(
    taxonomy: pd.DataFrame,
    baseline_trades: pd.DataFrame,
    baseline_legs: pd.DataFrame,
) -> tuple[list[dict], list[dict]]:
    if baseline_trades.empty:
        return [], []
    sessions = taxonomy.set_index("date").to_dict("index")
    control = CHALLENGER_BY_ID["ROUTED_BASELINE_CONTROL_V1"]
    trade_rows: list[dict] = []
    leg_rows: list[dict] = []
    trade_scale: dict[str, tuple[float, float]] = {}
    for source in baseline_trades.to_dict("records"):
        date = str(source["date"])
        session = sessions.get(date, {})
        idea_type = str(source.get("idea_type", "SINGLE"))
        if idea_type == "PAIR":
            risk_pct = abs(_num(source.get("pair_stop_return")))
        else:
            entry = _num(source.get("entry_price"))
            risk_pct = _num(source.get("risk_per_share")) / entry if entry > 0 else np.nan
        multiplier = _num(session.get("research_risk_multiplier"), 1.0)
        equal_notional, risk_notional = _risk_notionals(risk_pct, multiplier)
        gross_return = _num(source.get("gross_return"), 0.0)
        equal_gross = equal_notional * gross_return
        risk_gross = risk_notional * gross_return
        source_id = str(source["trade_id"])
        trade_id = f"CONTROL|{source_id}"
        trade_scale[source_id] = (equal_notional, risk_notional)
        entry_time = pd.to_datetime(source.get("entry_time"), errors="coerce")
        exit_time = pd.to_datetime(source.get("exit_time"), errors="coerce")
        trade_rows.append(
            {
                "matrix_id": MATRIX_ID,
                "trade_id": trade_id,
                "date": date,
                "primary_regime": str(source.get("primary_regime", session.get("primary_regime", ""))),
                "challenger_id": control["challenger_id"],
                "strategy_family": control["strategy_family"],
                "control_status": control["control_status"],
                "idea_type": idea_type,
                "direction": source.get("direction", ""),
                "ticker": source.get("ticker", ""),
                "paired_ticker": source.get("paired_ticker", ""),
                "long_ticker": source.get("long_ticker", ""),
                "short_ticker": source.get("short_ticker", ""),
                "regime_confidence": _num(session.get("regime_confidence")),
                "confidence_band": session.get("confidence_band", ""),
                "direction_bias": session.get("direction_bias", ""),
                "entry_time": source.get("entry_time", ""),
                "entry_price": _num(source.get("entry_price")),
                "stop_price": _num(source.get("stop_price")),
                "target_price": _num(source.get("target_price")),
                "pair_entry_long_price": _num(source.get("pair_entry_long_price")),
                "pair_entry_short_price": _num(source.get("pair_entry_short_price")),
                "pair_stop_return": _num(source.get("pair_stop_return")),
                "pair_target_return": _num(source.get("pair_target_return")),
                "exit_time": source.get("exit_time", ""),
                "exit_price": _num(source.get("exit_price")),
                "pair_exit_long_price": _num(source.get("pair_exit_long_price")),
                "pair_exit_short_price": _num(source.get("pair_exit_short_price")),
                "exit_reason": source.get("exit_reason", ""),
                "gross_return": gross_return,
                "risk_pct_at_entry": risk_pct,
                "r_multiple_achieved": _num(source.get("r_multiple_achieved")),
                "trade_duration_minutes": _num(source.get("trade_duration_minutes")),
                "research_risk_multiplier": multiplier,
                "equal_notional_sek": equal_notional,
                "equal_gross_pnl_sek": equal_gross,
                "equal_cost_sek": equal_notional * ROUND_TRIP_COST_RATE,
                "equal_net_pnl_sek": equal_gross - equal_notional * ROUND_TRIP_COST_RATE,
                "risk_capped_notional_sek": risk_notional,
                "risk_capped_gross_pnl_sek": risk_gross,
                "risk_capped_cost_sek": risk_notional * ROUND_TRIP_COST_RATE,
                "risk_capped_net_pnl_sek": risk_gross - risk_notional * ROUND_TRIP_COST_RATE,
                "point_in_time_pass": _bool(source.get("point_in_time_pass")),
                "execution_invariant_pass": pd.notna(entry_time) and pd.notna(exit_time) and _clock(entry_time) >= EXECUTION_START and exit_time >= entry_time,
            }
        )
    source_trade_notional = baseline_trades.set_index("trade_id")["notional_sek"].to_dict()
    for source in baseline_legs.to_dict("records"):
        source_id = str(source["trade_id"])
        if source_id not in trade_scale:
            continue
        equal_total, risk_total = trade_scale[source_id]
        source_total = _num(source_trade_notional.get(source_id))
        source_leg_notional = _num(source.get("notional_sek"))
        share = source_leg_notional / source_total if source_total > 0 else 1.0
        equal_leg = equal_total * share
        risk_leg = risk_total * share
        gross_return = _num(source.get("gross_return"), 0.0)
        leg_rows.append(
            {
                "matrix_id": MATRIX_ID,
                "trade_id": f"CONTROL|{source_id}",
                "leg_id": f"CONTROL|{source.get('leg_id', '')}",
                "date": str(source.get("date", "")),
                "primary_regime": source.get("primary_regime", ""),
                "challenger_id": control["challenger_id"],
                "ticker": source.get("ticker", ""),
                "side": source.get("side", ""),
                "entry_time": source.get("entry_time", ""),
                "entry_price": _num(source.get("entry_price")),
                "exit_time": source.get("exit_time", ""),
                "exit_price": _num(source.get("exit_price")),
                "exit_reason": source.get("exit_reason", ""),
                "equal_notional_sek": equal_leg,
                "equal_gross_pnl_sek": equal_leg * gross_return,
                "equal_cost_sek": equal_leg * ROUND_TRIP_COST_RATE,
                "equal_net_pnl_sek": equal_leg * gross_return - equal_leg * ROUND_TRIP_COST_RATE,
                "risk_capped_notional_sek": risk_leg,
                "risk_capped_gross_pnl_sek": risk_leg * gross_return,
                "risk_capped_cost_sek": risk_leg * ROUND_TRIP_COST_RATE,
                "risk_capped_net_pnl_sek": risk_leg * gross_return - risk_leg * ROUND_TRIP_COST_RATE,
            }
        )
    return trade_rows, leg_rows


def _concentration(group: pd.DataFrame) -> tuple[float, float, float]:
    if group.empty:
        return np.nan, np.nan, np.nan
    pnl = pd.to_numeric(group["risk_capped_net_pnl_sek"], errors="coerce").fillna(0.0)
    total_abs = float(pnl.abs().sum())
    daily = group.assign(_pnl=pnl).groupby("date", as_index=False)["_pnl"].sum()
    top_day_share = float(daily["_pnl"].abs().max() / total_abs) if total_abs > 0 and not daily.empty else np.nan
    baseline = float(pnl.sum())
    remaining = [baseline - float(value) for value in daily["_pnl"]]
    loo_share = float(np.mean([value > 0 for value in remaining])) if remaining else np.nan
    loo_min = float(min(remaining)) if remaining else np.nan
    return top_day_share, loo_share, loo_min


def build_performance(
    taxonomy: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    for regime in REGIMES:
        regime_sessions = taxonomy[taxonomy["primary_regime"].eq(regime)]
        for challenger in CHALLENGERS:
            cid = challenger["challenger_id"]
            cands = candidates[(candidates["primary_regime"].eq(regime)) & (candidates["challenger_id"].eq(cid))] if not candidates.empty else candidates
            cell = trades[(trades["primary_regime"].eq(regime)) & (trades["challenger_id"].eq(cid))] if not trades.empty else trades
            equal_pnl = pd.to_numeric(cell.get("equal_net_pnl_sek"), errors="coerce") if not cell.empty else pd.Series(dtype="float64")
            risk_pnl = pd.to_numeric(cell.get("risk_capped_net_pnl_sek"), errors="coerce") if not cell.empty else pd.Series(dtype="float64")
            sessions_with_trades = int(cell["date"].nunique()) if not cell.empty else 0
            sample_status = "SCREENABLE_DISCOVERY_SAMPLE" if len(cell) >= MINIMUM_SCREENING_TRADES and sessions_with_trades >= MINIMUM_SCREENING_SESSIONS else "INSUFFICIENT_SAMPLE"
            gross_risk = float(pd.to_numeric(cell.get("risk_capped_gross_pnl_sek"), errors="coerce").sum()) if not cell.empty else 0.0
            net_risk = float(risk_pnl.sum()) if not cell.empty else 0.0
            if challenger["control_status"] != "CHALLENGER":
                discovery = "FROZEN_BASELINE_CONTROL"
            elif sample_status == "INSUFFICIENT_SAMPLE":
                discovery = "INSUFFICIENT_SAMPLE"
            elif gross_risk <= 0:
                discovery = "NEGATIVE_GROSS_DISCOVERY"
            elif net_risk <= 0:
                discovery = "RAW_SIGNAL_COST_ERODED"
            else:
                _, loo_share, _ = _concentration(cell)
                discovery = "POSITIVE_CONCENTRATED_DISCOVERY" if np.isfinite(loo_share) and loo_share < 0.5 else "POSITIVE_DISCOVERY_ONLY"
            top_day, loo_share, loo_min = _concentration(cell)
            rows.append(
                {
                    "matrix_id": MATRIX_ID,
                    "primary_regime": regime,
                    "challenger_id": cid,
                    "strategy_family": challenger["strategy_family"],
                    "control_status": challenger["control_status"],
                    "ranking_eligible": challenger["ranking_eligible"],
                    "regime_sessions": len(regime_sessions),
                    "candidate_rows": len(cands),
                    "valid_setups": int(cands["setup_status"].eq("VALID_SETUP").sum()) if not cands.empty else 0,
                    "selected_ideas": int(cands["selected_for_simulation"].fillna(False).astype(bool).sum()) if not cands.empty else 0,
                    "trades": len(cell),
                    "sessions_with_trades": sessions_with_trades,
                    "winning_trades_equal_notional": int((equal_pnl > 0).sum()),
                    "win_rate_equal_notional": float((equal_pnl > 0).mean()) if len(equal_pnl) else np.nan,
                    "gross_pnl_equal_notional_sek": float(pd.to_numeric(cell.get("equal_gross_pnl_sek"), errors="coerce").sum()) if not cell.empty else 0.0,
                    "cost_equal_notional_sek": float(pd.to_numeric(cell.get("equal_cost_sek"), errors="coerce").sum()) if not cell.empty else 0.0,
                    "net_pnl_equal_notional_sek": float(equal_pnl.sum()) if len(equal_pnl) else 0.0,
                    "profit_factor_equal_notional": _profit_factor(equal_pnl),
                    "winning_trades_risk_capped": int((risk_pnl > 0).sum()),
                    "win_rate_risk_capped": float((risk_pnl > 0).mean()) if len(risk_pnl) else np.nan,
                    "gross_pnl_risk_capped_sek": gross_risk,
                    "cost_risk_capped_sek": float(pd.to_numeric(cell.get("risk_capped_cost_sek"), errors="coerce").sum()) if not cell.empty else 0.0,
                    "net_pnl_risk_capped_sek": net_risk,
                    "average_net_pnl_risk_capped_sek": float(risk_pnl.mean()) if len(risk_pnl) else np.nan,
                    "median_net_pnl_risk_capped_sek": float(risk_pnl.median()) if len(risk_pnl) else np.nan,
                    "profit_factor_risk_capped": _profit_factor(risk_pnl),
                    "average_r_multiple": float(pd.to_numeric(cell.get("r_multiple_achieved"), errors="coerce").mean()) if not cell.empty else np.nan,
                    "top_day_abs_pnl_share": top_day,
                    "leave_one_day_out_profitable_share": loo_share,
                    "leave_one_day_out_min_pnl_sek": loo_min,
                    "sample_status": sample_status,
                    "discovery_status": discovery,
                    "baseline_control_net_pnl_risk_capped_sek": np.nan,
                    "incremental_vs_baseline_risk_capped_sek": np.nan,
                }
            )
    performance = pd.DataFrame(rows, columns=PERFORMANCE_COLUMNS)
    baseline = performance[performance["challenger_id"].eq("ROUTED_BASELINE_CONTROL_V1")].set_index("primary_regime")["net_pnl_risk_capped_sek"].to_dict()
    performance["baseline_control_net_pnl_risk_capped_sek"] = performance["primary_regime"].map(baseline)
    performance["incremental_vs_baseline_risk_capped_sek"] = performance["net_pnl_risk_capped_sek"] - performance["baseline_control_net_pnl_risk_capped_sek"]
    return performance


def build_rankings(performance: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for regime, group in performance.groupby("primary_regime", sort=False):
        challengers = group[group["ranking_eligible"].fillna(False).astype(bool)].copy()
        challengers["rank_all"] = challengers["net_pnl_risk_capped_sek"].rank(method="min", ascending=False)
        screenable = challengers[challengers["sample_status"].eq("SCREENABLE_DISCOVERY_SAMPLE")].copy()
        screenable_ranks = screenable["net_pnl_risk_capped_sek"].rank(method="min", ascending=False).to_dict()
        for idx, row in group.iterrows():
            if row["control_status"] != "CHALLENGER":
                selection = "BASELINE_CONTROL_NOT_RANKED"
            elif row["sample_status"] != "SCREENABLE_DISCOVERY_SAMPLE":
                selection = "INSUFFICIENT_SAMPLE_NO_SELECTION"
            elif row["net_pnl_risk_capped_sek"] > 0:
                selection = "DISCOVERY_LEADER_CANDIDATE_NOT_PROMOTED" if screenable_ranks.get(idx) == 1 else "POSITIVE_CHALLENGER_NOT_PROMOTED"
            else:
                selection = "NEGATIVE_CHALLENGER_RETAIN_OR_REJECT_AFTER_REVIEW"
            rank_all = challengers.loc[idx, "rank_all"] if idx in challengers.index else np.nan
            rows.append(
                {
                    "matrix_id": MATRIX_ID,
                    "primary_regime": regime,
                    "challenger_id": row["challenger_id"],
                    "strategy_family": row["strategy_family"],
                    "control_status": row["control_status"],
                    "ranking_eligible": row["ranking_eligible"],
                    "trades": row["trades"],
                    "sessions_with_trades": row["sessions_with_trades"],
                    "net_pnl_risk_capped_sek": row["net_pnl_risk_capped_sek"],
                    "gross_pnl_risk_capped_sek": row["gross_pnl_risk_capped_sek"],
                    "profit_factor_risk_capped": row["profit_factor_risk_capped"],
                    "average_r_multiple": row["average_r_multiple"],
                    "sample_status": row["sample_status"],
                    "discovery_status": row["discovery_status"],
                    "rank_all_challengers": rank_all,
                    "rank_screenable_challengers": screenable_ranks.get(idx, np.nan),
                    "baseline_control_net_pnl_risk_capped_sek": row["baseline_control_net_pnl_risk_capped_sek"],
                    "incremental_vs_baseline_risk_capped_sek": row["incremental_vs_baseline_risk_capped_sek"],
                    "selection_status": selection,
                }
            )
    return pd.DataFrame(rows, columns=RANKING_COLUMNS)


def build_session_coverage(
    taxonomy: pd.DataFrame,
    baseline_sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    baseline_sessions = baseline_sessions.copy()
    if "date" not in baseline_sessions.columns:
        baseline_sessions = pd.DataFrame(columns=["date"])
    elif not baseline_sessions.empty:
        baseline_sessions["date"] = baseline_sessions["date"].astype(str)
    for session in taxonomy.sort_values("date").to_dict("records"):
        date = str(session["date"])
        regime = str(session["primary_regime"])
        for challenger in CHALLENGERS:
            cid = challenger["challenger_id"]
            day_trades = trades[(trades["date"].eq(date)) & (trades["challenger_id"].eq(cid))] if not trades.empty else trades
            day_candidates = candidates[(candidates["date"].eq(date)) & (candidates["challenger_id"].eq(cid))] if not candidates.empty else candidates
            if challenger["control_status"] != "CHALLENGER":
                source = baseline_sessions[baseline_sessions["date"].eq(date)]
                candidate_count = int(_num(source.iloc[0].get("candidate_rows"), 0)) if not source.empty else 0
                valid = int(_num(source.iloc[0].get("valid_setup_candidates"), 0)) if not source.empty else 0
                selected = int(_num(source.iloc[0].get("selected_ideas"), 0)) if not source.empty else 0
                max_router = source.iloc[0].get("max_router_source_label", LATEST_ROUTER_BAR_LABEL) if not source.empty else LATEST_ROUTER_BAR_LABEL
                pit = _bool(source.iloc[0].get("point_in_time_session_pass")) if not source.empty else True
            else:
                candidate_count = len(day_candidates)
                valid = int(day_candidates["setup_status"].eq("VALID_SETUP").sum()) if not day_candidates.empty else 0
                selected = int(day_candidates["selected_for_simulation"].fillna(False).astype(bool).sum()) if not day_candidates.empty else 0
                max_router = day_candidates["max_router_source_label"].dropna().astype(str).max() if not day_candidates.empty else ""
                pit = bool(day_candidates["point_in_time_pass"].fillna(False).all()) if not day_candidates.empty else True
            entries = pd.to_datetime(day_trades["entry_time"], errors="coerce") if not day_trades.empty else pd.Series(dtype="datetime64[ns]")
            exits = pd.to_datetime(day_trades["exit_time"], errors="coerce") if not day_trades.empty else pd.Series(dtype="datetime64[ns]")
            invariant = bool(day_trades["execution_invariant_pass"].fillna(False).all()) if not day_trades.empty else True
            if len(day_trades):
                status = "TRADES_GENERATED"
            elif selected:
                status = "SELECTED_NO_TRIGGER"
            elif valid:
                status = "VALID_SETUP_NOT_SELECTED"
            else:
                status = "NO_VALID_SETUP"
            rows.append(
                {
                    "matrix_id": MATRIX_ID,
                    "date": date,
                    "primary_regime": regime,
                    "challenger_id": cid,
                    "strategy_family": challenger["strategy_family"],
                    "control_status": challenger["control_status"],
                    "regime_confidence": _num(session.get("regime_confidence")),
                    "confidence_band": session.get("confidence_band", ""),
                    "direction_bias": session.get("direction_bias", ""),
                    "candidate_rows": candidate_count,
                    "valid_setups": valid,
                    "selected_ideas": selected,
                    "trades": len(day_trades),
                    "equal_net_pnl_sek": float(pd.to_numeric(day_trades.get("equal_net_pnl_sek"), errors="coerce").sum()) if not day_trades.empty else 0.0,
                    "risk_capped_net_pnl_sek": float(pd.to_numeric(day_trades.get("risk_capped_net_pnl_sek"), errors="coerce").sum()) if not day_trades.empty else 0.0,
                    "minimum_entry_time": _iso(entries.min()) if not entries.empty and entries.notna().any() else "",
                    "maximum_exit_time": _iso(exits.max()) if not exits.empty and exits.notna().any() else "",
                    "max_router_source_label": max_router,
                    "point_in_time_pass": pit,
                    "execution_invariant_pass": invariant,
                    "session_status": status,
                }
            )
    return pd.DataFrame(rows, columns=SESSION_COLUMNS)


def build_audit(taxonomy: pd.DataFrame, candidates: pd.DataFrame, trades: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for challenger in CHALLENGERS:
        cid = challenger["challenger_id"]
        cands = candidates[candidates["challenger_id"].eq(cid)] if not candidates.empty else candidates
        cell = trades[trades["challenger_id"].eq(cid)] if not trades.empty else trades
        cell_legs = legs[legs["challenger_id"].eq(cid)] if not legs.empty else legs
        entries = pd.to_datetime(cell["entry_time"], errors="coerce") if not cell.empty else pd.Series(dtype="datetime64[ns]")
        exits = pd.to_datetime(cell["exit_time"], errors="coerce") if not cell.empty else pd.Series(dtype="datetime64[ns]")
        entry_pass = bool(entries.notna().all() and (entries.dt.strftime("%H:%M") >= EXECUTION_START).all()) if not cell.empty else True
        exit_pass = bool(exits.notna().all() and (exits >= entries).all()) if not cell.empty else True
        pit_pass = bool(cell["point_in_time_pass"].fillna(False).all()) if not cell.empty else True
        if challenger["control_status"] == "CHALLENGER" and not cands.empty:
            pit_pass = pit_pass and bool(cands["point_in_time_pass"].fillna(False).all())
        max_router = cands["max_router_source_label"].dropna().astype(str).max() if not cands.empty else LATEST_ROUTER_BAR_LABEL
        trade_equal = cell.groupby("trade_id")["equal_net_pnl_sek"].sum() if not cell.empty else pd.Series(dtype="float64")
        leg_equal = cell_legs.groupby("trade_id")["equal_net_pnl_sek"].sum() if not cell_legs.empty else pd.Series(dtype="float64")
        trade_risk = cell.groupby("trade_id")["risk_capped_net_pnl_sek"].sum() if not cell.empty else pd.Series(dtype="float64")
        leg_risk = cell_legs.groupby("trade_id")["risk_capped_net_pnl_sek"].sum() if not cell_legs.empty else pd.Series(dtype="float64")
        equal_recon = pd.concat([trade_equal.rename("trade"), leg_equal.rename("legs")], axis=1).fillna(0.0)
        risk_recon = pd.concat([trade_risk.rename("trade"), leg_risk.rename("legs")], axis=1).fillna(0.0)
        equal_diff = float((equal_recon["trade"] - equal_recon["legs"]).abs().max()) if not equal_recon.empty else 0.0
        risk_diff = float((risk_recon["trade"] - risk_recon["legs"]).abs().max()) if not risk_recon.empty else 0.0
        invariant = pit_pass and entry_pass and exit_pass and equal_diff <= 1e-9 and risk_diff <= 1e-9 and (bool(cell["execution_invariant_pass"].fillna(False).all()) if not cell.empty else True)
        rows.append(
            {
                "matrix_id": MATRIX_ID,
                "challenger_id": cid,
                "control_status": challenger["control_status"],
                "sessions_processed": len(taxonomy),
                "candidate_rows": len(cands),
                "trades": len(cell),
                "max_router_source_label": max_router,
                "point_in_time_pass": pit_pass,
                "minimum_entry_time": _iso(entries.min()) if not entries.empty and entries.notna().any() else "",
                "entry_time_pass": entry_pass,
                "exit_after_entry_pass": exit_pass,
                "trade_leg_reconciliation_max_abs_diff_equal_notional_sek": equal_diff,
                "trade_leg_reconciliation_max_abs_diff_risk_capped_sek": risk_diff,
                "execution_invariant_pass": invariant,
                "audit_status": "PASS" if invariant else "REVIEW_REQUIRED",
            }
        )
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def build_summary(taxonomy: pd.DataFrame, candidates: pd.DataFrame, trades: pd.DataFrame, performance: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    generated = trades[trades["control_status"].eq("CHALLENGER")] if not trades.empty else trades
    control = trades[trades["control_status"].ne("CHALLENGER")] if not trades.empty else trades
    positive = performance[(performance["control_status"].eq("CHALLENGER")) & (performance["net_pnl_risk_capped_sek"].gt(0))]
    audit_failures = int((~audit["execution_invariant_pass"].fillna(False).astype(bool)).sum()) if not audit.empty else len(CHALLENGERS)
    equal_diff = float(pd.to_numeric(audit["trade_leg_reconciliation_max_abs_diff_equal_notional_sek"], errors="coerce").max()) if not audit.empty else np.inf
    risk_diff = float(pd.to_numeric(audit["trade_leg_reconciliation_max_abs_diff_risk_capped_sek"], errors="coerce").max()) if not audit.empty else np.inf
    matrix_cells = len(REGIMES) * len(CHALLENGERS)
    complete = len(performance) == matrix_cells
    classification = (
        "REGIME_STRATEGY_CHALLENGER_MATRIX_READY_FOR_DISCOVERY_REVIEW"
        if len(taxonomy) > 0 and complete and audit_failures == 0 and equal_diff <= 1e-9 and risk_diff <= 1e-9
        else "REGIME_STRATEGY_CHALLENGER_MATRIX_REQUIRES_MECHANICAL_REVIEW"
    )
    return pd.DataFrame(
        [
            {
                "matrix_id": MATRIX_ID,
                "research_status": RESEARCH_STATUS,
                "router_cutoff": LATEST_ROUTER_BAR_LABEL,
                "execution_start": EXECUTION_START,
                "taxonomy_sessions": len(taxonomy),
                "observed_regimes": int(taxonomy["primary_regime"].nunique()),
                "registered_challengers": len(CHALLENGERS),
                "generated_challengers": len(GENERATED_CHALLENGERS),
                "matrix_cells": len(performance),
                "candidate_rows": len(candidates),
                "generated_trades": len(generated),
                "control_trades": len(control),
                "total_comparison_trades": len(trades),
                "screenable_cells": int(performance["sample_status"].eq("SCREENABLE_DISCOVERY_SAMPLE").sum()),
                "positive_gross_cells_risk_capped": int(((performance["control_status"].eq("CHALLENGER")) & performance["gross_pnl_risk_capped_sek"].gt(0)).sum()),
                "positive_net_cells_risk_capped": len(positive),
                "regimes_with_positive_net_challenger": int(positive["primary_regime"].nunique()),
                "point_in_time_audit_pass_challengers": int(audit["execution_invariant_pass"].fillna(False).astype(bool).sum()),
                "execution_invariant_failures": audit_failures,
                "trade_leg_reconciliation_max_abs_diff_equal_notional_sek": equal_diff,
                "trade_leg_reconciliation_max_abs_diff_risk_capped_sek": risk_diff,
                "strategies_promoted": 0,
                "classification": classification,
            }
        ],
        columns=SUMMARY_COLUMNS,
    )


def build_challenger_matrix(
    taxonomy: pd.DataFrame,
    prices: pd.DataFrame,
    baseline_candidates: pd.DataFrame,
    baseline_sessions: pd.DataFrame,
    baseline_trades: pd.DataFrame,
    baseline_legs: pd.DataFrame,
):
    taxonomy = taxonomy.copy()
    taxonomy["date"] = taxonomy["date"].astype(str)
    daily_reference = build_daily_reference(prices)
    state, bars_lookup = build_market_state(prices, daily_reference, set(taxonomy["date"]))
    candidates: list[dict] = []
    trades: list[dict] = []
    legs: list[dict] = []

    control_trades, control_legs = _control_rows(taxonomy, baseline_trades, baseline_legs)
    trades.extend(control_trades)
    legs.extend(control_legs)

    for session in taxonomy.sort_values("date").to_dict("records"):
        date = str(session["date"])
        day_states = state[state["date"].eq(date)].copy()
        for challenger in GENERATED_CHALLENGERS:
            if challenger["idea_type"] == "PAIR":
                candidates.extend(_pair_candidate_for_challenger(session, challenger, day_states, bars_lookup, trades, legs))
            else:
                candidates.extend(_single_candidates_for_challenger(session, challenger, day_states, bars_lookup, trades, legs))

    candidate_df = pd.DataFrame(candidates, columns=CANDIDATE_COLUMNS)
    trade_df = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    leg_df = pd.DataFrame(legs, columns=LEG_COLUMNS)
    registry = pd.DataFrame([{**{"matrix_id": MATRIX_ID}, **row} for row in CHALLENGERS], columns=REGISTRY_COLUMNS)
    performance = build_performance(taxonomy, candidate_df, trade_df)
    rankings = build_rankings(performance)
    sessions = build_session_coverage(taxonomy, baseline_sessions, candidate_df, trade_df)
    audit = build_audit(taxonomy, candidate_df, trade_df, leg_df)
    summary = build_summary(taxonomy, candidate_df, trade_df, performance, audit)
    return summary, registry, candidate_df, trade_df, leg_df, performance, rankings, sessions, audit


def run_challenger_matrix(
    taxonomy_file: Path = TAXONOMY_FILE,
    db_path: Path = INTRADAY_DB,
    baseline_candidate_file: Path = BASELINE_CANDIDATE_FILE,
    baseline_session_file: Path = BASELINE_SESSION_FILE,
    baseline_trade_file: Path = BASELINE_TRADE_FILE,
    baseline_leg_file: Path = BASELINE_LEG_FILE,
):
    required = [taxonomy_file, baseline_candidate_file, baseline_session_file, baseline_trade_file, baseline_leg_file]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required Step 8/9B outputs: " + ", ".join(str(path) for path in missing))
    taxonomy = pd.read_csv(taxonomy_file)
    prices = load_intraday_prices(db_path)
    baseline_candidates = pd.read_csv(baseline_candidate_file)
    baseline_sessions = pd.read_csv(baseline_session_file)
    baseline_trades = pd.read_csv(baseline_trade_file)
    baseline_legs = pd.read_csv(baseline_leg_file)
    return build_challenger_matrix(taxonomy, prices, baseline_candidates, baseline_sessions, baseline_trades, baseline_legs)


def main() -> None:
    print("\n=== STEP 9D REGIME × STRATEGY CHALLENGER MATRIX ===")
    print(f"Matrix           : {MATRIX_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Router cutoff    : {LATEST_ROUTER_BAR_LABEL}")
    print(f"Execution starts : {EXECUTION_START}")
    print("The frozen Step 9B baseline is retained as a control.")
    print("Nine pre-registered challenger hypotheses are simulated across every observed regime.")
    print("No strategy is optimized, selected for production, or promoted in this step.")

    outputs = run_challenger_matrix()
    paths = [SUMMARY_FILE, REGISTRY_FILE, CANDIDATE_FILE, TRADE_FILE, LEG_FILE, PERFORMANCE_FILE, RANKING_FILE, SESSION_FILE, AUDIT_FILE]
    for dataframe, path in zip(outputs, paths):
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")

    result = outputs[0].iloc[0]
    print("\n=== STEP 9D CHALLENGER MATRIX RESULT ===")
    print(f"Taxonomy sessions             : {int(result['taxonomy_sessions'])}")
    print(f"Observed regimes              : {int(result['observed_regimes'])}")
    print(f"Registered/generated challengers: {int(result['registered_challengers'])}/{int(result['generated_challengers'])}")
    print(f"Regime × challenger cells     : {int(result['matrix_cells'])}")
    print(f"Generated/control trades      : {int(result['generated_trades'])}/{int(result['control_trades'])}")
    print(f"Screenable cells              : {int(result['screenable_cells'])}")
    print(f"Positive gross/net cells      : {int(result['positive_gross_cells_risk_capped'])}/{int(result['positive_net_cells_risk_capped'])}")
    print(f"Regimes with positive challenger: {int(result['regimes_with_positive_net_challenger'])}")
    print(f"PIT audit pass challengers    : {int(result['point_in_time_audit_pass_challengers'])}/{int(result['registered_challengers'])}")
    print(f"Execution invariant failures  : {int(result['execution_invariant_failures'])}")
    print(f"Equal/risk reconciliation max : {float(result['trade_leg_reconciliation_max_abs_diff_equal_notional_sek']):.12f} / {float(result['trade_leg_reconciliation_max_abs_diff_risk_capped_sek']):.12f} SEK")
    print(f"Strategies promoted           : {int(result['strategies_promoted'])}")
    print(f"Classification                : {result['classification']}")
    print("Step 9D export complete. Rankings are discovery evidence only, not final regime strategy choices.")


if __name__ == "__main__":
    main()
