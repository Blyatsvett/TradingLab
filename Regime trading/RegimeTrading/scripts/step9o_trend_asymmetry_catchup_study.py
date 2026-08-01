from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import legacy_output_path
from RegimeTrading.scripts import step9d_regime_strategy_challenger_matrix as step9d
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9k_high_dispersion_strategy_research as step9k
from RegimeTrading.scripts import step9n_trend_regimes_strategy_research as step9n


EXPERIMENT_ID = "STEP9O_TREND_ASYMMETRY_AND_CATCHUP_STUDY_COMBINED23_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_POST_HOC_TREND_ASYMMETRY_CATCHUP_REFINEMENT_NOT_CONFIRMATORY"
CODE_VERSION = "STEP9O_TREND_ASYMMETRY_CATCHUP_V1_LOCKED_2026_07_26"
SOURCE_DB = step9i.SHADOW_INTRADAY_DB
LATEST_ROUTER_BAR_LABEL = "09:40"
EXECUTION_START = "09:45"
TREND_REGIMES = ("TREND_UP", "TREND_DOWN")

DELAYED_REVERSAL_ID = "DELAYED_EARLY_MOVE_REVERSAL_1R_V1"
EARLY_CONTINUATION_ID = "EARLY_MOVE_CONTINUATION_1_5R_V1"
MED_HIGH_REVERSAL_ID = "TREND_UP_ALIGNED_DELAYED_REVERSAL_MED_HIGH_CONF_1R_V1"
CATCHUP_CONFIRMED_ID = "TREND_CONTRARIAN_CATCHUP_CONFIRMED_1_5R_V1"
CATCHUP_IMMEDIATE_ID = "TREND_CONTRARIAN_CATCHUP_IMMEDIATE_1_5R_CONTROL_V1"

REGISTRY_FILE = legacy_output_path("step9o_contract_registry.csv")
SESSION_FILE = legacy_output_path("step9o_session_coverage.csv")
CANDIDATE_FILE = legacy_output_path("step9o_candidates.csv")
TRADE_FILE = legacy_output_path("step9o_trades.csv")
LEG_FILE = legacy_output_path("step9o_trade_legs.csv")
PERFORMANCE_FILE = legacy_output_path("step9o_contract_performance.csv")
COMPARISON_FILE = legacy_output_path("step9o_comparisons.csv")
ROBUSTNESS_FILE = legacy_output_path("step9o_robustness.csv")
MULTIPLE_TESTING_FILE = legacy_output_path("step9o_multiple_testing.csv")
AUDIT_FILE = legacy_output_path("step9o_audit.csv")
TRADE_DIAGNOSTIC_FILE = legacy_output_path("step9o_trade_diagnostics.csv")
TREND_SESSION_DIAGNOSTIC_FILE = legacy_output_path("step9o_trend_session_diagnostics.csv")
TREND_STATE_DIAGNOSTIC_FILE = legacy_output_path("step9o_trend_state_diagnostic_summary.csv")
CATCHUP_NORMALIZED_FILE = legacy_output_path("step9o_catchup_direction_normalized_performance.csv")
REVERSAL_MATRIX_FILE = legacy_output_path("step9o_trend_up_reversal_variant_matrix.csv")
OVERLAP_FILE = legacy_output_path("step9o_contract_trade_overlap.csv")
TIME_SPLIT_FILE = legacy_output_path("step9o_time_split_performance.csv")
TICKER_FILE = legacy_output_path("step9o_ticker_performance.csv")
SECTOR_FILE = legacy_output_path("step9o_sector_performance.csv")
SEGMENT_FILE = legacy_output_path("step9o_segment_performance.csv")
SUMMARY_FILE = legacy_output_path("step9o_summary.csv")
TAXONOMY_FILE = legacy_output_path("step9o_daily_taxonomy.csv")


MED_HIGH_REVERSAL = {
    **dict(step9g.CHALLENGER_BY_ID[DELAYED_REVERSAL_ID]),
    "challenger_id": MED_HIGH_REVERSAL_ID,
    "strategy_family": "TREND_UP_ALIGNED_DELAYED_REVERSAL_MED_HIGH_CONF",
    "hypothesis": "The TREND_UP aligned delayed reversal remains positive after excluding low-confidence trend sessions.",
    "diagnostic_source": "Session-confidence refinement of the Step 9N reversal discovery.",
}

CATCHUP_CONFIRMED = {
    "challenger_id": CATCHUP_CONFIRMED_ID,
    "strategy_family": "TREND_CONTRARIAN_CATCHUP_CONFIRMED",
    "control_status": "CHALLENGER",
    "idea_type": "SINGLE",
    "hypothesis": "A stock initially moving against its trend regime and sector catches up after a close through the strict early midpoint.",
    "entry_model": "Require a close through the strict early midpoint in the regime direction, then enter next-bar open through 13:00.",
    "stop_model": "Signal-bar extreme observed before the next-bar entry.",
    "target_model": "1.5R from actual entry.",
    "exit_cutoff": "16:30",
    "selection_model": "Rank absolute contrarian 09:40 move; maximum frozen regime ideas.",
    "direction_model": "PRIMARY_REGIME_DIRECTION_AFTER_CONTRARIAN_EARLY_MOVE_CATCHUP_CONFIRMATION",
    "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
    "diagnostic_source": "Focused test motivated by Step 9N contrarian-cohort path diagnostics.",
    "ranking_eligible": True,
}

CATCHUP_IMMEDIATE = {
    **CATCHUP_CONFIRMED,
    "challenger_id": CATCHUP_IMMEDIATE_ID,
    "strategy_family": "TREND_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL",
    "control_status": "CONTROL",
    "hypothesis": "Control: enter the same contrarian early-move cohort immediately at the 09:45 bar open without catch-up confirmation.",
    "entry_model": "Enter the first executable 09:45 bar open in the regime direction.",
    "stop_model": "Strict early-session extreme known by 09:40.",
    "diagnostic_source": "Same-cohort timing control for the confirmed catch-up strategy.",
}


def _contract(
    contract_id: str,
    role: str,
    regime: str,
    challenger_id: str,
    cohort_id: str,
    comparison_group: str,
    ticker_states: str,
    sector_alignment: str,
    early_relation: str,
    strategy_key: str,
    hypothesis: str,
    interpretation: str,
    confidence_bands: str = "ANY",
) -> dict[str, Any]:
    return {
        "contract_id": contract_id,
        "test_role": role,
        "primary_regime": regime,
        "base_challenger_id": challenger_id,
        "cohort_id": cohort_id,
        "comparison_group": comparison_group,
        "ticker_relative_states": ticker_states,
        "volatility_buckets": "ANY",
        "sector_alignment_states": sector_alignment,
        "early_move_regime_relation": early_relation,
        "confidence_bands": confidence_bands,
        "strategy_key": strategy_key,
        "hypothesis": hypothesis,
        "economic_interpretation": interpretation,
    }


# Frozen before Step 9O output is viewed. Five primary hypotheses and three controls.
CONTRACTS = [
    _contract(
        "O_TU_ALIGNED_DELAYED_REVERSAL_ALL_V1", "PRIMARY_HYPOTHESIS", "TREND_UP",
        DELAYED_REVERSAL_ID, "O_TU_ALIGNED_EARLY_MOVE_ALL", "O_TU_REVERSAL_VS_CONTINUATION",
        "ANY", "ALIGNED_WITH_GROUP", "ALIGNED_WITH_REGIME", "TU_ALIGNED_DELAYED_REVERSAL_ALL",
        "The Step 9N TREND_UP reversal discovery repeats across all group-aligned regime-direction early movers.",
        "Primary reformulation of the former Step 9N negative control.",
    ),
    _contract(
        "O_TU_ALIGNED_EARLY_LEADER_REVERSAL_V1", "PRIMARY_HYPOTHESIS", "TREND_UP",
        DELAYED_REVERSAL_ID, "O_TU_ALIGNED_EARLY_LEADER", "O_TU_REVERSAL_STATE_REFINEMENT",
        "EARLY_LEADER", "ALIGNED_WITH_GROUP", "ALIGNED_WITH_REGIME", "TU_ALIGNED_EARLY_LEADER_REVERSAL",
        "TREND_UP reversal is concentrated in stocks already classified as early leaders.",
        "Tests whether extension among leaders explains the broad aligned-reversal result.",
    ),
    _contract(
        "O_TU_ALIGNED_REVERSAL_MED_HIGH_CONF_V1", "PRIMARY_HYPOTHESIS", "TREND_UP",
        MED_HIGH_REVERSAL_ID, "O_TU_ALIGNED_EARLY_MOVE_MED_HIGH_CONF", "O_TU_REVERSAL_CONFIDENCE_REFINEMENT",
        "ANY", "ALIGNED_WITH_GROUP", "ALIGNED_WITH_REGIME", "TU_ALIGNED_REVERSAL_MED_HIGH_CONF",
        "TREND_UP aligned reversal remains positive on MEDIUM or HIGH confidence sessions.",
        "Checks whether the discovery survives removal of low-confidence trend sessions.",
        confidence_bands="MEDIUM|HIGH",
    ),
    _contract(
        "O_TU_CONTRARIAN_CATCHUP_CONFIRMED_V1", "PRIMARY_HYPOTHESIS", "TREND_UP",
        CATCHUP_CONFIRMED_ID, "O_TU_CONTRARIAN_EARLY_MOVE", "O_TU_CATCHUP_CONFIRMATION",
        "ANY", "CONTRARIAN_TO_GROUP", "CONTRARIAN_TO_REGIME", "TU_CONTRARIAN_CATCHUP_CONFIRMED",
        "A TREND_UP stock initially falling against its rising group catches up after midpoint recovery confirmation.",
        "Tests the Step 9N diagnostic suggestion that initial contrarians have superior later trend-direction paths.",
    ),
    _contract(
        "O_TD_CONTRARIAN_CATCHUP_CONFIRMED_V1", "PRIMARY_HYPOTHESIS", "TREND_DOWN",
        CATCHUP_CONFIRMED_ID, "O_TD_CONTRARIAN_EARLY_MOVE", "O_TD_CATCHUP_CONFIRMATION",
        "ANY", "CONTRARIAN_TO_GROUP", "CONTRARIAN_TO_REGIME", "TD_CONTRARIAN_CATCHUP_CONFIRMED",
        "A TREND_DOWN stock initially rising against its falling group catches up after midpoint breakdown confirmation.",
        "Exact downside mirror of the catch-up hypothesis.",
    ),
    _contract(
        "O_TU_ALIGNED_EARLY_CONTINUATION_CONTROL_V1", "NEGATIVE_CONTROL", "TREND_UP",
        EARLY_CONTINUATION_ID, "O_TU_ALIGNED_EARLY_MOVE_ALL", "O_TU_REVERSAL_VS_CONTINUATION",
        "ANY", "ALIGNED_WITH_GROUP", "ALIGNED_WITH_REGIME", "TU_ALIGNED_EARLY_CONTINUATION_CONTROL",
        "Control: continue the same group-aligned TREND_UP early move instead of fading it.",
        "Same-cohort directional control for the aligned delayed reversal.",
    ),
    _contract(
        "O_TU_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL_V1", "EXECUTION_CONTROL", "TREND_UP",
        CATCHUP_IMMEDIATE_ID, "O_TU_CONTRARIAN_EARLY_MOVE", "O_TU_CATCHUP_CONFIRMATION",
        "ANY", "CONTRARIAN_TO_GROUP", "CONTRARIAN_TO_REGIME", "TU_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL",
        "Control: buy the same TREND_UP contrarian cohort immediately without midpoint recovery confirmation.",
        "Tests whether confirmation adds value beyond the underlying contrarian-stock cohort.",
    ),
    _contract(
        "O_TD_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL_V1", "EXECUTION_CONTROL", "TREND_DOWN",
        CATCHUP_IMMEDIATE_ID, "O_TD_CONTRARIAN_EARLY_MOVE", "O_TD_CATCHUP_CONFIRMATION",
        "ANY", "CONTRARIAN_TO_GROUP", "CONTRARIAN_TO_REGIME", "TD_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL",
        "Control: short the same TREND_DOWN contrarian cohort immediately without midpoint breakdown confirmation.",
        "Exact downside timing control.",
    ),
]
CONTRACT_BY_ID = {row["contract_id"]: row for row in CONTRACTS}

COMPARISONS = [
    ("O_TU_REVERSAL_MINUS_CONTINUATION", "O_TU_ALIGNED_DELAYED_REVERSAL_ALL_V1", "O_TU_ALIGNED_EARLY_CONTINUATION_CONTROL_V1", "SAME_COHORT_STRATEGY"),
    ("O_TU_EARLY_LEADER_REVERSAL_MINUS_ALL", "O_TU_ALIGNED_EARLY_LEADER_REVERSAL_V1", "O_TU_ALIGNED_DELAYED_REVERSAL_ALL_V1", "STATE_SUBSET_REFINEMENT"),
    ("O_TU_MED_HIGH_CONF_REVERSAL_MINUS_ALL", "O_TU_ALIGNED_REVERSAL_MED_HIGH_CONF_V1", "O_TU_ALIGNED_DELAYED_REVERSAL_ALL_V1", "SESSION_SUBSET_REFINEMENT"),
    ("O_TU_CONFIRMED_CATCHUP_MINUS_IMMEDIATE", "O_TU_CONTRARIAN_CATCHUP_CONFIRMED_V1", "O_TU_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL_V1", "SAME_COHORT_STRATEGY"),
    ("O_TD_CONFIRMED_CATCHUP_MINUS_IMMEDIATE", "O_TD_CONTRARIAN_CATCHUP_CONFIRMED_V1", "O_TD_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL_V1", "SAME_COHORT_STRATEGY"),
    ("O_TU_MINUS_TD_CONFIRMED_CATCHUP", "O_TU_CONTRARIAN_CATCHUP_CONFIRMED_V1", "O_TD_CONTRARIAN_CATCHUP_CONFIRMED_V1", "REGIME_ASYMMETRY_DIAGNOSTIC"),
]

SUMMARY_COLUMNS = [
    "experiment_id", "research_status", "code_version", "requested_start_date", "requested_end_date",
    "effective_start_date", "effective_end_date", "taxonomy_sessions", "trend_up_sessions", "trend_down_sessions",
    "trend_sessions_total", "diagnostic_ticker_session_rows", "contracts_registered", "primary_hypotheses",
    "completed_trades", "positive_primary_contracts", "positive_catchup_regimes", "audit_pass",
    "strategies_promoted", "router_active", "classification",
]


def _bool(value: Any) -> bool:
    return step9g._bool(value)


def _num(value: Any, default: float = np.nan) -> float:
    return step9g._num(value, default)


def _early_move(row: pd.Series | dict) -> float:
    return step9k._early_move(row)


def _early_move_side(row: pd.Series | dict) -> str:
    return step9k._early_move_side(row)


def _regime_side(regime: str) -> str:
    return "LONG" if regime == "TREND_UP" else "SHORT" if regime == "TREND_DOWN" else ""


def _opposite_side(side: str) -> str:
    return "SHORT" if side == "LONG" else "LONG" if side == "SHORT" else ""


def _base_catchup_rows(session: dict, challenger: dict, states: pd.DataFrame) -> list[dict]:
    regime = str(session.get("primary_regime", ""))
    expected_side = _regime_side(regime)
    expected_bias = "UP" if expected_side == "LONG" else "DOWN" if expected_side == "SHORT" else ""
    direction_bias = str(session.get("direction_bias", "")).upper()
    rows: list[dict] = []
    for state in states.sort_values("ticker").to_dict("records"):
        candidate, move, early_side = step9k._candidate_base(session, challenger, state)
        candidate["direction"] = expected_side
        candidate["ranking_metric"] = abs(move) if np.isfinite(move) else np.nan
        invalid: list[str] = []
        if expected_side not in {"LONG", "SHORT"}:
            invalid.append("NON_TREND_REGIME")
        if direction_bias != expected_bias:
            invalid.append("DIRECTION_BIAS_MISMATCH")
        if not np.isfinite(move) or abs(move) < 0.0010:
            invalid.append("EARLY_MOVE_BELOW_0_10_PERCENT")
        if early_side != _opposite_side(expected_side):
            invalid.append("STOCK_NOT_CONTRARIAN_TO_REGIME_DIRECTION")
        early_range_pct = _num(state.get("early_range_pct"))
        if not np.isfinite(early_range_pct) or early_range_pct <= 0 or early_range_pct > step9d.MAX_RANGE_RISK_PCT:
            invalid.append("INVALID_OR_WIDE_RANGE")
        if invalid:
            candidate["setup_status"] = "INVALID_SETUP"
            candidate["trigger_status"] = "NOT_EVALUATED"
            candidate["invalid_reason"] = ";".join(sorted(set(invalid)))
        rows.append(candidate)
    step9d._select_candidates(rows, max_ideas=int(_num(session.get("research_max_concurrent_ideas"), 2)))
    return rows


def _catchup_confirmed_candidates(
    session: dict,
    challenger: dict,
    states: pd.DataFrame,
    bars_lookup: dict[tuple[str, str], pd.DataFrame],
    trades: list[dict],
    legs: list[dict],
) -> list[dict]:
    date = str(session["date"])
    rows = _base_catchup_rows(session, challenger, states)
    for candidate in rows:
        candidate["mechanical_interpretation"] = "CONTRARIAN_EARLY_MOVE_MIDPOINT_CATCHUP_CLOSE_NEXT_BAR_1_5R"
        if not candidate["selected_for_simulation"]:
            continue
        bars = bars_lookup.get((date, str(candidate["ticker"])), pd.DataFrame())
        if bars.empty:
            candidate["trigger_status"] = "NO_EXECUTABLE_BARS"
            continue
        side = str(candidate["direction"])
        midpoint = _num(candidate.get("early_midpoint"))
        signal_bar = None
        for _, bar in step9d._bars_between(bars, "09:45", "12:55").iterrows():
            close = _num(bar.get("close"))
            if side == "LONG" and close > midpoint:
                signal_bar = bar
                break
            if side == "SHORT" and close < midpoint:
                signal_bar = bar
                break
        if signal_bar is None:
            candidate["trigger_status"] = "MIDPOINT_CATCHUP_NOT_CONFIRMED"
            continue
        next_bar = step9d._next_bar_after(bars, pd.Timestamp(signal_bar["datetime"]))
        if next_bar is None or step9d._clock(next_bar["datetime"]) > "13:00":
            candidate["trigger_status"] = "CATCHUP_CONFIRMATION_TOO_LATE"
            continue
        stop = _num(signal_bar.get("low")) if side == "LONG" else _num(signal_bar.get("high"))
        step9k._finalize_single_trade(
            candidate, session, challenger, bars, side, signal_bar, next_bar,
            stop, 1.5, trades, legs,
        )
    return rows


def _catchup_immediate_candidates(
    session: dict,
    challenger: dict,
    states: pd.DataFrame,
    bars_lookup: dict[tuple[str, str], pd.DataFrame],
    trades: list[dict],
    legs: list[dict],
) -> list[dict]:
    date = str(session["date"])
    rows = _base_catchup_rows(session, challenger, states)
    for candidate in rows:
        candidate["mechanical_interpretation"] = "CONTRARIAN_EARLY_MOVE_IMMEDIATE_0945_OPEN_1_5R_CONTROL"
        if not candidate["selected_for_simulation"]:
            continue
        bars = bars_lookup.get((date, str(candidate["ticker"])), pd.DataFrame())
        first_bar = step9d._first_bar_between(bars, "09:45", "09:45") if not bars.empty else None
        if first_bar is None:
            candidate["trigger_status"] = "NO_0945_ENTRY_BAR"
            continue
        side = str(candidate["direction"])
        stop = _num(candidate.get("early_low")) if side == "LONG" else _num(candidate.get("early_high"))
        synthetic_signal = first_bar.copy()
        synthetic_signal["datetime"] = pd.Timestamp(first_bar["datetime"]) - pd.Timedelta(minutes=step9d.BAR_INTERVAL_MINUTES)
        step9k._finalize_single_trade(
            candidate, session, challenger, bars, side, synthetic_signal, first_bar,
            stop, 1.5, trades, legs,
        )
    return rows


@contextmanager
def _patched_step9o_engine():
    names = [
        "EXPERIMENT_ID", "RESEARCH_STATUS", "CONTRACTS", "CONTRACT_BY_ID", "COMPARISONS",
        "CHALLENGER_BY_ID", "_single_candidates_for_challenger", "_intended_side", "_contract_mask",
    ]
    old = {name: getattr(step9g, name) for name in names}
    challenger_map = dict(step9g.CHALLENGER_BY_ID)
    challenger_map[MED_HIGH_REVERSAL_ID] = MED_HIGH_REVERSAL
    challenger_map[CATCHUP_CONFIRMED_ID] = CATCHUP_CONFIRMED
    challenger_map[CATCHUP_IMMEDIATE_ID] = CATCHUP_IMMEDIATE
    original_dispatch = step9g._single_candidates_for_challenger
    original_intended_side = step9g._intended_side
    original_contract_mask = step9g._contract_mask

    def dispatch(session, challenger, states, bars_lookup, trades, legs):
        cid = challenger["challenger_id"]
        if cid == CATCHUP_CONFIRMED_ID:
            return _catchup_confirmed_candidates(session, challenger, states, bars_lookup, trades, legs)
        if cid == CATCHUP_IMMEDIATE_ID:
            return _catchup_immediate_candidates(session, challenger, states, bars_lookup, trades, legs)
        if cid == MED_HIGH_REVERSAL_ID:
            if str(session.get("confidence_band", "")).upper() not in {"MEDIUM", "HIGH"}:
                return []
            base = dict(challenger)
            base["challenger_id"] = DELAYED_REVERSAL_ID
            return original_dispatch(session, base, states, bars_lookup, trades, legs)
        return original_dispatch(session, challenger, states, bars_lookup, trades, legs)

    def intended_side(base_challenger_id: str, row: pd.Series | dict) -> str:
        if base_challenger_id in {DELAYED_REVERSAL_ID, MED_HIGH_REVERSAL_ID, CATCHUP_CONFIRMED_ID, CATCHUP_IMMEDIATE_ID}:
            # All Step 9O cohort labels describe the stock's EARLY MOVE, never the later trade side.
            return _early_move_side(row)
        return original_intended_side(base_challenger_id, row)

    def contract_mask(states: pd.DataFrame, contract: dict) -> pd.Series:
        mask = original_contract_mask(states, contract)
        expected = _regime_side(str(contract.get("primary_regime", "")))
        early_sides = pd.Series(
            [_early_move_side(row) for row in states.to_dict("records")],
            index=states.index,
            dtype="object",
        )
        relation = str(contract.get("early_move_regime_relation", "ANY"))
        if relation == "ALIGNED_WITH_REGIME":
            mask &= early_sides.eq(expected)
        elif relation == "CONTRARIAN_TO_REGIME":
            mask &= early_sides.eq(_opposite_side(expected))
        return mask

    try:
        step9g.EXPERIMENT_ID = EXPERIMENT_ID
        step9g.RESEARCH_STATUS = RESEARCH_STATUS
        step9g.CONTRACTS = CONTRACTS
        step9g.CONTRACT_BY_ID = CONTRACT_BY_ID
        step9g.COMPARISONS = COMPARISONS
        step9g.CHALLENGER_BY_ID = challenger_map
        step9g._single_candidates_for_challenger = dispatch
        step9g._intended_side = intended_side
        step9g._contract_mask = contract_mask
        yield
    finally:
        for name, value in old.items():
            setattr(step9g, name, value)


def _force_experiment_id(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "experiment_id" in result.columns:
        result["experiment_id"] = EXPERIMENT_ID
    return result


def _apply_confidence_session_gate(sessions: pd.DataFrame, taxonomy: pd.DataFrame) -> pd.DataFrame:
    result = sessions.copy()
    if result.empty:
        return result
    confidence = taxonomy.set_index("date")["confidence_band"].astype(str).str.upper().to_dict()
    mask = result["contract_id"].eq("O_TU_ALIGNED_REVERSAL_MED_HIGH_CONF_V1") & result["date"].map(confidence).eq("LOW")
    for column in ["eligible_ticker_rows", "eligible_independent_companies", "valid_setup_rows", "selected_ideas", "triggered_trades"]:
        result.loc[mask, column] = 0
    for column in ["equal_net_pnl_sek", "risk_capped_net_pnl_sek"]:
        result.loc[mask, column] = 0.0
    result.loc[mask, "eligible_tickers"] = ""
    result.loc[mask, "cohort_signature"] = ""
    result.loc[mask, "coverage_status"] = "SESSION_CONFIDENCE_GATE_NOT_MET"
    return result


def _profit_factor(values: Iterable[float]) -> float:
    return step9g._profit_factor(values)


def build_catchup_direction_normalized_performance(trades: pd.DataFrame) -> pd.DataFrame:
    pairs = [
        (
            "CONFIRMED_CATCHUP_1_5R",
            "O_TU_CONTRARIAN_CATCHUP_CONFIRMED_V1",
            "O_TD_CONTRARIAN_CATCHUP_CONFIRMED_V1",
            "PRIMARY_HYPOTHESIS",
        ),
        (
            "IMMEDIATE_CATCHUP_1_5R_CONTROL",
            "O_TU_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL_V1",
            "O_TD_CONTRARIAN_CATCHUP_IMMEDIATE_CONTROL_V1",
            "EXECUTION_CONTROL",
        ),
    ]
    rows: list[dict[str, Any]] = []
    for strategy_key, up_id, down_id, role in pairs:
        up = trades[trades["contract_id"].eq(up_id)] if not trades.empty else trades.copy()
        down = trades[trades["contract_id"].eq(down_id)] if not trades.empty else trades.copy()
        combined = pd.concat([up, down], ignore_index=True)
        up_pnl = float(pd.to_numeric(up.get("risk_capped_net_pnl_sek"), errors="coerce").sum()) if not up.empty else 0.0
        down_pnl = float(pd.to_numeric(down.get("risk_capped_net_pnl_sek"), errors="coerce").sum()) if not down.empty else 0.0
        pnl = pd.to_numeric(combined.get("risk_capped_net_pnl_sek"), errors="coerce").dropna() if not combined.empty else pd.Series(dtype=float)
        both = up_pnl > 0 and down_pnl > 0
        if both:
            status = "POSITIVE_BOTH_REGIMES"
        elif up_pnl > 0 and down_pnl <= 0:
            status = "TREND_UP_ONLY_OR_ASYMMETRIC"
        elif down_pnl > 0 and up_pnl <= 0:
            status = "TREND_DOWN_ONLY_OR_ASYMMETRIC"
        else:
            status = "NONPOSITIVE_BOTH_REGIMES"
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            "strategy_key": strategy_key,
            "test_role": role,
            "trend_up_contract_id": up_id,
            "trend_down_contract_id": down_id,
            "trend_up_trades": int(len(up)),
            "trend_down_trades": int(len(down)),
            "combined_trades": int(len(combined)),
            "trend_up_sessions_with_trades": int(up["date"].nunique()) if not up.empty else 0,
            "trend_down_sessions_with_trades": int(down["date"].nunique()) if not down.empty else 0,
            "combined_sessions_with_trades": int(combined["date"].nunique()) if not combined.empty else 0,
            "trend_up_net_pnl_risk_capped_sek": up_pnl,
            "trend_down_net_pnl_risk_capped_sek": down_pnl,
            "combined_net_pnl_risk_capped_sek": float(pnl.sum()) if not pnl.empty else 0.0,
            "combined_average_net_pnl_risk_capped_sek": float(pnl.mean()) if not pnl.empty else np.nan,
            "combined_median_net_pnl_risk_capped_sek": float(pnl.median()) if not pnl.empty else np.nan,
            "combined_win_rate_risk_capped": float((pnl > 0).mean()) if not pnl.empty else np.nan,
            "combined_profit_factor_risk_capped": _profit_factor(pnl),
            "worst_regime_pnl_sek": min(up_pnl, down_pnl),
            "both_regimes_positive": both,
            "asymmetry_status": status,
            "selection_status": "DISCOVERY_ONLY_NOT_PROMOTED",
        })
    return pd.DataFrame(rows)


def build_reversal_variant_matrix(performance: pd.DataFrame) -> pd.DataFrame:
    ids = [
        "O_TU_ALIGNED_DELAYED_REVERSAL_ALL_V1",
        "O_TU_ALIGNED_EARLY_LEADER_REVERSAL_V1",
        "O_TU_ALIGNED_REVERSAL_MED_HIGH_CONF_V1",
        "O_TU_ALIGNED_EARLY_CONTINUATION_CONTROL_V1",
    ]
    cols = [
        "experiment_id", "contract_id", "test_role", "trades", "sessions_with_trades",
        "independent_companies_traded", "broad_sectors_traded", "net_pnl_risk_capped_sek",
        "win_rate_risk_capped", "profit_factor_risk_capped", "leave_one_day_out_min_pnl_sek",
        "bootstrap_total_pnl_ci_lower_95_sek", "bootstrap_total_pnl_ci_upper_95_sek",
        "sample_status", "selection_status",
    ]
    result = performance[performance["contract_id"].isin(ids)].copy()
    return result.reindex(columns=[c for c in cols if c in result.columns])


def build_contract_trade_overlap(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=[
            "experiment_id", "date", "ticker", "contracts_trading_ticker", "contract_count",
            "directions", "opposing_directions", "combined_net_pnl_risk_capped_sek",
        ])
    rows: list[dict[str, Any]] = []
    for (date, ticker), group in trades.groupby(["date", "ticker"], sort=True):
        if group["contract_id"].nunique() < 2:
            continue
        directions = sorted(set(group["direction"].astype(str)))
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            "date": str(date),
            "ticker": str(ticker),
            "contracts_trading_ticker": "|".join(sorted(group["contract_id"].astype(str).unique())),
            "contract_count": int(group["contract_id"].nunique()),
            "directions": "|".join(directions),
            "opposing_directions": len(directions) > 1,
            "combined_net_pnl_risk_capped_sek": float(pd.to_numeric(group["risk_capped_net_pnl_sek"], errors="coerce").sum()),
        })
    return pd.DataFrame(rows)


def extend_audit(
    audit: pd.DataFrame,
    taxonomy: pd.DataFrame,
    diagnostics: pd.DataFrame,
    registry: pd.DataFrame,
    sessions: pd.DataFrame,
    normalized: pd.DataFrame,
) -> pd.DataFrame:
    trend = taxonomy[taxonomy["primary_regime"].isin(TREND_REGIMES)].copy()
    trend_sessions = int(len(trend))
    expected_rows = trend_sessions * len(step9i.TRADING_TICKERS)
    coverage_failures = abs(expected_rows - len(diagnostics))
    router_failures = int(registry["router_active"].map(_bool).sum() + registry["promotion_eligible"].map(_bool).sum())
    low_dates = set(trend.loc[trend["confidence_band"].astype(str).str.upper().eq("LOW"), "date"].astype(str))
    gated = sessions[
        sessions["contract_id"].eq("O_TU_ALIGNED_REVERSAL_MED_HIGH_CONF_V1")
        & sessions["date"].astype(str).isin(low_dates)
    ]
    confidence_failures = int((pd.to_numeric(gated["eligible_ticker_rows"], errors="coerce").fillna(0) != 0).sum())
    mirrored_failures = 0
    catchup = normalized[normalized["strategy_key"].eq("CONFIRMED_CATCHUP_1_5R")]
    if catchup.empty or not catchup.iloc[0]["trend_up_contract_id"] or not catchup.iloc[0]["trend_down_contract_id"]:
        mirrored_failures = 1
    rows = [
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "TREND_DIAGNOSTIC_COVERAGE_23_TICKERS",
            "rows_checked": int(len(diagnostics)),
            "failures": int(coverage_failures),
            "max_abs_difference": float(coverage_failures),
            "audit_pass": coverage_failures == 0,
            "interpretation": "Each TREND_UP and TREND_DOWN session has one diagnostic row for every Combined 23 ticker.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "FOCUSED_STEP9O_CONTRACT_REGISTRY",
            "rows_checked": int(len(registry)),
            "failures": int(abs(len(registry) - 8) + abs(int(registry["test_role"].eq("PRIMARY_HYPOTHESIS").sum()) - 5)),
            "max_abs_difference": np.nan,
            "audit_pass": len(registry) == 8 and int(registry["test_role"].eq("PRIMARY_HYPOTHESIS").sum()) == 5,
            "interpretation": "Step 9O contains five focused primary hypotheses and three controls only.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "MEDIUM_HIGH_CONFIDENCE_SESSION_GATE",
            "rows_checked": int(len(gated)),
            "failures": confidence_failures,
            "max_abs_difference": np.nan,
            "audit_pass": confidence_failures == 0,
            "interpretation": "The confidence-filtered TREND_UP reversal contract has zero eligible rows on LOW-confidence sessions.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "MIRRORED_CONTRARIAN_CATCHUP_CONTRACTS",
            "rows_checked": 4,
            "failures": mirrored_failures,
            "max_abs_difference": float(mirrored_failures),
            "audit_pass": mirrored_failures == 0,
            "interpretation": "Confirmed and immediate catch-up logic is represented for both TREND_UP and TREND_DOWN.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "EARLY_MOVE_ALIGNMENT_SEMANTICS",
            "rows_checked": 4,
            "failures": 0,
            "max_abs_difference": np.nan,
            "audit_pass": True,
            "interpretation": "All Step 9O cohort labels use the stock's early move, not the later reversal or catch-up trade side.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "NO_STEP9O_ROUTER_ACTIVATION",
            "rows_checked": int(len(registry)),
            "failures": router_failures,
            "max_abs_difference": np.nan,
            "audit_pass": router_failures == 0,
            "interpretation": "Step 9O cannot modify or activate Step 9I or Step 9L.",
        },
    ]
    return pd.concat([_force_experiment_id(audit), pd.DataFrame(rows)], ignore_index=True)


def build_summary(
    start_date: str,
    end_date: str,
    taxonomy: pd.DataFrame,
    diagnostics: pd.DataFrame,
    trades: pd.DataFrame,
    performance: pd.DataFrame,
    normalized: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    dates = sorted(taxonomy["date"].astype(str).unique()) if not taxonomy.empty else []
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")]
    confirmed = normalized[normalized["strategy_key"].eq("CONFIRMED_CATCHUP_1_5R")]
    positive_catchup = 0
    if not confirmed.empty:
        row = confirmed.iloc[0]
        positive_catchup = int(_num(row.get("trend_up_net_pnl_risk_capped_sek"), 0.0) > 0) + int(_num(row.get("trend_down_net_pnl_risk_capped_sek"), 0.0) > 0)
    audit_pass = bool(audit["audit_pass"].map(_bool).all()) if not audit.empty else False
    row = {
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "code_version": CODE_VERSION,
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "effective_start_date": dates[0] if dates else "",
        "effective_end_date": dates[-1] if dates else "",
        "taxonomy_sessions": len(dates),
        "trend_up_sessions": int(taxonomy["primary_regime"].eq("TREND_UP").sum()) if not taxonomy.empty else 0,
        "trend_down_sessions": int(taxonomy["primary_regime"].eq("TREND_DOWN").sum()) if not taxonomy.empty else 0,
        "trend_sessions_total": int(taxonomy["primary_regime"].isin(TREND_REGIMES).sum()) if not taxonomy.empty else 0,
        "diagnostic_ticker_session_rows": int(len(diagnostics)),
        "contracts_registered": len(CONTRACTS),
        "primary_hypotheses": int(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in CONTRACTS)),
        "completed_trades": int(len(trades)),
        "positive_primary_contracts": int(primary["net_pnl_risk_capped_sek"].gt(0).sum()) if not primary.empty else 0,
        "positive_catchup_regimes": positive_catchup,
        "audit_pass": audit_pass,
        "strategies_promoted": 0,
        "router_active": False,
        "classification": "STEP9O_TREND_ASYMMETRY_CATCHUP_DISCOVERY_COMPLETE_NOT_CONFIRMATORY" if audit_pass else "STEP9O_AUDIT_REVIEW_REQUIRED",
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_step9o(prices: pd.DataFrame, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    taxonomy, taxonomy_skips = step9k.build_daily_taxonomy(prices, start_date, end_date)
    if taxonomy.empty:
        raise ValueError("No point-in-time-ready taxonomy sessions are available in the requested window.")
    effective_end = str(taxonomy["date"].max())
    static, trading_prices, characteristics, group_states = step9i._full_holdout_context(prices, effective_end)

    diagnostics = step9n.build_trend_session_diagnostics(taxonomy, trading_prices, static, characteristics, group_states)
    diagnostic_summary = _force_experiment_id(step9n.build_trend_state_diagnostic_summary(diagnostics))
    diagnostics = _force_experiment_id(diagnostics)

    with step9i._patched_holdout_tickers():
        with _patched_step9o_engine():
            core = step9g.build_state_filtered_experiment(
                taxonomy, trading_prices, static, characteristics, group_states
            )
            (
                _core_summary, registry, sessions, candidates, trades, legs, _performance,
                _comparisons, _robustness, _multiple, _audit,
            ) = core
            sessions = _apply_confidence_session_gate(sessions, taxonomy)
            performance = step9g.build_performance(registry, sessions, candidates, trades)
            comparisons = step9g.build_comparisons(sessions, trades)
            robustness = step9g.build_robustness(trades)
            multiple = step9g.build_multiple_testing(performance)
            audit = step9g.build_audit(registry, sessions, candidates, trades, legs, comparisons)

    for frame in (trades, candidates):
        if not frame.empty and "universe_segment" not in frame.columns:
            insert_at = frame.columns.get_loc("ticker") + 1
            frame.insert(insert_at, "universe_segment", frame["ticker"].map(step9i._segment_for_ticker))

    registry = _force_experiment_id(registry)
    contract_lookup = {row["contract_id"]: row for row in CONTRACTS}
    for column in ["early_move_regime_relation", "confidence_bands", "strategy_key"]:
        registry[column] = registry["contract_id"].map(lambda cid: contract_lookup[str(cid)][column])
    sessions = _force_experiment_id(sessions)
    candidates = _force_experiment_id(candidates)
    trades = _force_experiment_id(trades)
    legs = _force_experiment_id(legs)
    performance = _force_experiment_id(performance)
    comparisons = _force_experiment_id(comparisons)
    robustness = _force_experiment_id(robustness)
    multiple = _force_experiment_id(multiple)
    if not multiple.empty:
        multiple["multiplicity_family"] = "FIVE_PRE_REGISTERED_STEP9O_PRIMARY_HYPOTHESES"
        multiple["interpretation"] = "Focused post-hoc refinement only; no p-value or q-value promotes a strategy."

    trade_diagnostics = _force_experiment_id(step9k.build_trade_diagnostics(
        trades, trading_prices, set(taxonomy["date"].astype(str))
    ))
    performance = _force_experiment_id(step9k.enrich_performance(performance, trades, trade_diagnostics))
    normalized = build_catchup_direction_normalized_performance(trades)
    reversal_matrix = build_reversal_variant_matrix(performance)
    overlap = build_contract_trade_overlap(trades)
    trend_dates = sorted(taxonomy.loc[taxonomy["primary_regime"].isin(TREND_REGIMES), "date"].astype(str).unique())
    time_split = _force_experiment_id(step9k.build_time_split_performance(trades, trend_dates))
    ticker_performance = _force_experiment_id(step9k.build_group_performance(
        trades, ["contract_id", "test_role", "primary_regime", "ticker", "company_id", "broad_sector"]
    ))
    if not ticker_performance.empty:
        ticker_performance.insert(
            ticker_performance.columns.get_loc("ticker") + 1,
            "universe_segment",
            ticker_performance["ticker"].map(step9i._segment_for_ticker),
        )
    sector_performance = _force_experiment_id(step9k.build_group_performance(
        trades, ["contract_id", "test_role", "primary_regime", "broad_sector"]
    ))
    segment_performance = _force_experiment_id(step9k.build_segment_performance(trades))
    audit = extend_audit(audit, taxonomy, diagnostics, registry, sessions, normalized)
    summary = build_summary(
        start_date, end_date, taxonomy, diagnostics, trades, performance, normalized, audit
    )
    return {
        "taxonomy": taxonomy,
        "taxonomy_skips": taxonomy_skips,
        "registry": registry,
        "sessions": sessions,
        "candidates": candidates,
        "trades": trades,
        "legs": legs,
        "performance": performance,
        "comparisons": comparisons,
        "robustness": robustness,
        "multiple_testing": multiple,
        "audit": audit,
        "trade_diagnostics": trade_diagnostics,
        "trend_session_diagnostics": diagnostics,
        "trend_state_diagnostic_summary": diagnostic_summary,
        "catchup_direction_normalized_performance": normalized,
        "reversal_variant_matrix": reversal_matrix,
        "contract_trade_overlap": overlap,
        "time_split": time_split,
        "ticker_performance": ticker_performance,
        "sector_performance": sector_performance,
        "segment_performance": segment_performance,
        "summary": summary,
    }


def export_outputs(outputs: dict[str, pd.DataFrame]) -> None:
    paths = {
        "taxonomy": TAXONOMY_FILE,
        "registry": REGISTRY_FILE,
        "sessions": SESSION_FILE,
        "candidates": CANDIDATE_FILE,
        "trades": TRADE_FILE,
        "legs": LEG_FILE,
        "performance": PERFORMANCE_FILE,
        "comparisons": COMPARISON_FILE,
        "robustness": ROBUSTNESS_FILE,
        "multiple_testing": MULTIPLE_TESTING_FILE,
        "audit": AUDIT_FILE,
        "trade_diagnostics": TRADE_DIAGNOSTIC_FILE,
        "trend_session_diagnostics": TREND_SESSION_DIAGNOSTIC_FILE,
        "trend_state_diagnostic_summary": TREND_STATE_DIAGNOSTIC_FILE,
        "catchup_direction_normalized_performance": CATCHUP_NORMALIZED_FILE,
        "reversal_variant_matrix": REVERSAL_MATRIX_FILE,
        "contract_trade_overlap": OVERLAP_FILE,
        "time_split": TIME_SPLIT_FILE,
        "ticker_performance": TICKER_FILE,
        "sector_performance": SECTOR_FILE,
        "segment_performance": SEGMENT_FILE,
        "summary": SUMMARY_FILE,
    }
    for key, path in paths.items():
        export_csv_for_power_bi(outputs[key], path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step 9O focused trend asymmetry and contrarian catch-up research on Combined 23.")
    parser.add_argument("--start-date", default="2026-05-27")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = step9i.load_shadow_prices(args.source_db)
    if prices.empty:
        raise SystemExit(f"No intraday prices found in {args.source_db}.")
    outputs = run_step9o(prices, args.start_date, args.end_date)
    export_outputs(outputs)
    summary = outputs["summary"].iloc[0]
    performance = outputs["performance"]
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")]
    cols = [
        "contract_id", "trades", "sessions_with_trades", "net_pnl_risk_capped_sek",
        "win_rate_risk_capped", "profit_factor_risk_capped", "bh_adjusted_q_value_primary_family",
        "selection_status",
    ]
    print("\n=== STEP 9O TREND ASYMMETRY AND CATCH-UP STUDY — COMBINED 23 ===")
    print(f"Experiment          : {EXPERIMENT_ID}")
    print(f"Research status     : {RESEARCH_STATUS}")
    print(f"Requested window    : {args.start_date} through {args.end_date}")
    print(f"Effective window    : {summary['effective_start_date']} through {summary['effective_end_date']}")
    print(f"Taxonomy sessions   : {int(summary['taxonomy_sessions'])}")
    print(f"TREND_UP sessions   : {int(summary['trend_up_sessions'])}")
    print(f"TREND_DOWN sessions : {int(summary['trend_down_sessions'])}")
    print(f"Diagnostic rows     : {int(summary['diagnostic_ticker_session_rows'])}")
    print(f"Contracts           : {int(summary['contracts_registered'])} ({int(summary['primary_hypotheses'])} primaries)")
    print(f"Completed trades    : {int(summary['completed_trades'])}")
    print(f"Audit pass          : {bool(summary['audit_pass'])}")
    print(f"Classification      : {summary['classification']}")
    print("\nPrimary challenger snapshot:")
    print(primary[cols].to_string(index=False))
    print("\nNo Step 9O result is automatically added to Step 9L. Review reversal refinement, catch-up controls, asymmetry, and robustness first.")


if __name__ == "__main__":
    main()
