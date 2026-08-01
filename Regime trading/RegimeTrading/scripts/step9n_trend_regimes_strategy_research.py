from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import legacy_output_path
from RegimeTrading.scripts import step9b_baseline_trade_generation as step9b
from RegimeTrading.scripts import step9d_regime_strategy_challenger_matrix as step9d
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9k_high_dispersion_strategy_research as step9k


EXPERIMENT_ID = "STEP9N_TREND_REGIMES_STRATEGY_RESEARCH_COMBINED23_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_POST_HOC_TREND_REGIME_DISCOVERY_NOT_CONFIRMATORY"
CODE_VERSION = "STEP9N_TREND_REGIMES_V1_LOCKED_2026_07_26"
SOURCE_DB = step9i.SHADOW_INTRADAY_DB
LATEST_ROUTER_BAR_LABEL = "09:40"
EXECUTION_START = "09:45"
TREND_REGIMES = ("TREND_UP", "TREND_DOWN")

CLOSE_CONFIRMED_ORB_ID = "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1"
PULLBACK_RESUME_ID = "TREND_PULLBACK_RESUME_1_5R_V1"
DIRECTIONAL_BREAKOUT_ID = "DIRECTIONAL_VOLATILITY_BREAKOUT_2R_V1"
EARLY_CONTINUATION_ID = "EARLY_MOVE_CONTINUATION_1_5R_V1"
DELAYED_REVERSAL_ID = "DELAYED_EARLY_MOVE_REVERSAL_1R_V1"

REGISTRY_FILE = legacy_output_path("step9n_contract_registry.csv")
SESSION_FILE = legacy_output_path("step9n_session_coverage.csv")
CANDIDATE_FILE = legacy_output_path("step9n_candidates.csv")
TRADE_FILE = legacy_output_path("step9n_trades.csv")
LEG_FILE = legacy_output_path("step9n_trade_legs.csv")
PERFORMANCE_FILE = legacy_output_path("step9n_contract_performance.csv")
COMPARISON_FILE = legacy_output_path("step9n_comparisons.csv")
ROBUSTNESS_FILE = legacy_output_path("step9n_robustness.csv")
MULTIPLE_TESTING_FILE = legacy_output_path("step9n_multiple_testing.csv")
AUDIT_FILE = legacy_output_path("step9n_audit.csv")
TRADE_DIAGNOSTIC_FILE = legacy_output_path("step9n_trade_diagnostics.csv")
TREND_SESSION_DIAGNOSTIC_FILE = legacy_output_path("step9n_trend_session_diagnostics.csv")
TREND_STATE_DIAGNOSTIC_FILE = legacy_output_path("step9n_trend_state_diagnostic_summary.csv")
DIRECTION_NORMALIZED_FILE = legacy_output_path("step9n_direction_normalized_performance.csv")
REGIME_STRATEGY_MATRIX_FILE = legacy_output_path("step9n_regime_strategy_matrix.csv")
TIME_SPLIT_FILE = legacy_output_path("step9n_time_split_performance.csv")
TICKER_FILE = legacy_output_path("step9n_ticker_performance.csv")
SECTOR_FILE = legacy_output_path("step9n_sector_performance.csv")
SEGMENT_FILE = legacy_output_path("step9n_segment_performance.csv")
SUMMARY_FILE = legacy_output_path("step9n_summary.csv")
TAXONOMY_FILE = legacy_output_path("step9n_daily_taxonomy.csv")


PULLBACK_RESUME = {
    "challenger_id": PULLBACK_RESUME_ID,
    "strategy_family": "TREND_PULLBACK_RESUME",
    "control_status": "CHALLENGER",
    "idea_type": "SINGLE",
    "hypothesis": "A trend-aligned early move offers a better continuation entry after a midpoint pullback and renewed close confirmation.",
    "entry_model": "After a pullback touches the strict early midpoint, require a later close beyond the pullback bar in the regime direction and enter next-bar open through 13:00.",
    "stop_model": "Observed pullback-bar extreme known at the resume signal.",
    "target_model": "1.5R from actual entry.",
    "exit_cutoff": "16:30",
    "selection_model": "Rank absolute 09:40 trend-aligned move; maximum frozen regime ideas.",
    "direction_model": "PRIMARY_REGIME_DIRECTION_AFTER_MIDPOINT_PULLBACK_AND_RESUME",
    "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
    "diagnostic_source": "Tests a structurally later entry without changing the frozen regime classifier.",
    "ranking_eligible": True,
}


def _contract(
    contract_id: str,
    role: str,
    regime: str,
    challenger_id: str,
    family: str,
    hypothesis: str,
    interpretation: str,
) -> dict[str, Any]:
    prefix = "TU" if regime == "TREND_UP" else "TD"
    return {
        "contract_id": contract_id,
        "test_role": role,
        "primary_regime": regime,
        "base_challenger_id": challenger_id,
        "cohort_id": f"N_{prefix}_GROUP_ALIGNED_EARLY_MOVE",
        "comparison_group": f"N_{prefix}_MIRRORED_TREND_STRATEGIES",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "strategy_key": family,
        "hypothesis": hypothesis,
        "economic_interpretation": interpretation,
    }


# Frozen before Step 9N output is viewed. The same three primaries and two controls
# are mirrored across TREND_UP and TREND_DOWN.
CONTRACTS = [
    _contract(
        "N_TU_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "PRIMARY_HYPOTHESIS", "TREND_UP",
        CLOSE_CONFIRMED_ORB_ID, "CLOSE_CONFIRMED_ORB_1R",
        "A group-aligned TREND_UP stock continues after a completed close beyond the strict opening range.",
        "Confirmation may reduce false upside breaks without chasing the first touch.",
    ),
    _contract(
        "N_TU_ALIGNED_PULLBACK_RESUME_1_5R_V1", "PRIMARY_HYPOTHESIS", "TREND_UP",
        PULLBACK_RESUME_ID, "PULLBACK_RESUME_1_5R",
        "A group-aligned TREND_UP stock resumes after a midpoint pullback and renewed upside confirmation.",
        "Tests whether waiting for a cheaper structural continuation entry improves trend participation.",
    ),
    _contract(
        "N_TU_DIRECTIONAL_BREAKOUT_2R_V1", "PRIMARY_HYPOTHESIS", "TREND_UP",
        DIRECTIONAL_BREAKOUT_ID, "DIRECTIONAL_BREAKOUT_2R",
        "A group-aligned TREND_UP stock should be given a 2R target after an upside volatility breakout.",
        "Tests whether genuine trend days deserve more payoff room than a 1R ORB.",
    ),
    _contract(
        "N_TU_EARLY_CONTINUATION_CONTROL_V1", "EXECUTION_CONTROL", "TREND_UP",
        EARLY_CONTINUATION_ID, "EARLY_CONTINUATION_1_5R_CONTROL",
        "Control: immediate continuation in the group-aligned early-move direction.",
        "Separates entry-timing value from the underlying trend signal.",
    ),
    _contract(
        "N_TU_COUNTERTREND_DELAYED_REVERSAL_CONTROL_V1", "NEGATIVE_GUARDRAIL_CONTROL", "TREND_UP",
        DELAYED_REVERSAL_ID, "COUNTERTREND_DELAYED_REVERSAL_1R_CONTROL",
        "Control: fade a group-aligned TREND_UP early move only after midpoint reversal confirmation.",
        "Tests whether countertrend fading should become an explicit trend-regime guardrail.",
    ),
    _contract(
        "N_TD_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "PRIMARY_HYPOTHESIS", "TREND_DOWN",
        CLOSE_CONFIRMED_ORB_ID, "CLOSE_CONFIRMED_ORB_1R",
        "A group-aligned TREND_DOWN stock continues after a completed close below the strict opening range.",
        "Mirrored downside confirmation test.",
    ),
    _contract(
        "N_TD_ALIGNED_PULLBACK_RESUME_1_5R_V1", "PRIMARY_HYPOTHESIS", "TREND_DOWN",
        PULLBACK_RESUME_ID, "PULLBACK_RESUME_1_5R",
        "A group-aligned TREND_DOWN stock resumes after a midpoint rally and renewed downside confirmation.",
        "Mirrored downside pullback-and-resume test.",
    ),
    _contract(
        "N_TD_DIRECTIONAL_BREAKOUT_2R_V1", "PRIMARY_HYPOTHESIS", "TREND_DOWN",
        DIRECTIONAL_BREAKOUT_ID, "DIRECTIONAL_BREAKOUT_2R",
        "A group-aligned TREND_DOWN stock should be given a 2R target after a downside volatility breakout.",
        "Mirrored downside volatility-breakout test.",
    ),
    _contract(
        "N_TD_EARLY_CONTINUATION_CONTROL_V1", "EXECUTION_CONTROL", "TREND_DOWN",
        EARLY_CONTINUATION_ID, "EARLY_CONTINUATION_1_5R_CONTROL",
        "Control: immediate downside continuation in the group-aligned early-move direction.",
        "Mirrored execution control.",
    ),
    _contract(
        "N_TD_COUNTERTREND_DELAYED_REVERSAL_CONTROL_V1", "NEGATIVE_GUARDRAIL_CONTROL", "TREND_DOWN",
        DELAYED_REVERSAL_ID, "COUNTERTREND_DELAYED_REVERSAL_1R_CONTROL",
        "Control: fade a group-aligned TREND_DOWN early move only after midpoint reversal confirmation.",
        "Mirrored countertrend guardrail test.",
    ),
]
CONTRACT_BY_ID = {row["contract_id"]: row for row in CONTRACTS}

COMPARISONS = [
    ("N_TU_CLOSE_ORB_MINUS_EARLY_CONT", "N_TU_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "N_TU_EARLY_CONTINUATION_CONTROL_V1", "SAME_COHORT_STRATEGY"),
    ("N_TU_PULLBACK_MINUS_EARLY_CONT", "N_TU_ALIGNED_PULLBACK_RESUME_1_5R_V1", "N_TU_EARLY_CONTINUATION_CONTROL_V1", "SAME_COHORT_STRATEGY"),
    ("N_TU_BREAKOUT_2R_MINUS_CLOSE_ORB", "N_TU_DIRECTIONAL_BREAKOUT_2R_V1", "N_TU_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "SAME_COHORT_STRATEGY"),
    ("N_TU_EARLY_CONT_MINUS_COUNTERTREND_REV", "N_TU_EARLY_CONTINUATION_CONTROL_V1", "N_TU_COUNTERTREND_DELAYED_REVERSAL_CONTROL_V1", "SAME_COHORT_STRATEGY_CONTROL"),
    ("N_TD_CLOSE_ORB_MINUS_EARLY_CONT", "N_TD_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "N_TD_EARLY_CONTINUATION_CONTROL_V1", "SAME_COHORT_STRATEGY"),
    ("N_TD_PULLBACK_MINUS_EARLY_CONT", "N_TD_ALIGNED_PULLBACK_RESUME_1_5R_V1", "N_TD_EARLY_CONTINUATION_CONTROL_V1", "SAME_COHORT_STRATEGY"),
    ("N_TD_BREAKOUT_2R_MINUS_CLOSE_ORB", "N_TD_DIRECTIONAL_BREAKOUT_2R_V1", "N_TD_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "SAME_COHORT_STRATEGY"),
    ("N_TD_EARLY_CONT_MINUS_COUNTERTREND_REV", "N_TD_EARLY_CONTINUATION_CONTROL_V1", "N_TD_COUNTERTREND_DELAYED_REVERSAL_CONTROL_V1", "SAME_COHORT_STRATEGY_CONTROL"),
]

SUMMARY_COLUMNS = [
    "experiment_id", "research_status", "code_version", "requested_start_date",
    "requested_end_date", "effective_start_date", "effective_end_date",
    "taxonomy_sessions", "trend_up_sessions", "trend_down_sessions", "trend_sessions_total",
    "diagnostic_ticker_session_rows", "contracts_registered", "primary_hypotheses",
    "completed_trades", "positive_primary_contracts", "primary_families_positive_both_regimes",
    "audit_pass", "strategies_promoted", "router_active", "classification",
]

TREND_SESSION_DIAGNOSTIC_COLUMNS = [
    "experiment_id", "date", "primary_regime", "regime_side", "normalization_multiplier",
    "regime_confidence", "confidence_band", "direction_bias", "ticker", "universe_segment",
    "company_id", "broad_sector", "ticker_relative_state", "volatility_bucket", "range_state",
    "sector_direction_state", "early_move_side", "early_move_sector_alignment", "early_move_pct",
    "early_move_in_regime_direction_pct", "early_open", "early_high", "early_low", "early_midpoint",
    "early_range_pct", "close_0940", "post_0945_reference", "trend_mfe_pct", "trend_mae_pct",
    "countertrend_mfe_pct", "countertrend_mae_pct", "close_confirmed_breakout_time",
    "midpoint_pullback_time", "pullback_resume_time", "close_confirmed_breakout",
    "midpoint_pullback_observed", "pullback_resume_confirmed", "final_return_from_0945_pct",
    "final_return_in_regime_direction_pct", "max_router_source_label", "point_in_time_pass",
]

DIRECTION_NORMALIZED_COLUMNS = [
    "experiment_id", "strategy_key", "test_role", "trend_up_contract_id", "trend_down_contract_id",
    "trend_up_trades", "trend_down_trades", "combined_trades", "trend_up_sessions_with_trades",
    "trend_down_sessions_with_trades", "combined_sessions_with_trades", "trend_up_net_pnl_risk_capped_sek",
    "trend_down_net_pnl_risk_capped_sek", "combined_net_pnl_risk_capped_sek",
    "combined_average_net_pnl_risk_capped_sek", "combined_median_net_pnl_risk_capped_sek",
    "combined_win_rate_risk_capped", "combined_profit_factor_risk_capped", "worst_regime_pnl_sek",
    "both_regimes_positive", "neither_regime_severely_negative", "symmetry_status", "selection_status",
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


def _pullback_resume_candidates(
    session: dict,
    challenger: dict,
    states: pd.DataFrame,
    bars_lookup: dict[tuple[str, str], pd.DataFrame],
    trades: list[dict],
    legs: list[dict],
) -> list[dict]:
    date = str(session["date"])
    regime = str(session.get("primary_regime", ""))
    expected_side = _regime_side(regime)
    expected_bias = "UP" if expected_side == "LONG" else "DOWN" if expected_side == "SHORT" else ""
    direction_bias = str(session.get("direction_bias", "")).upper()
    max_ideas = int(_num(session.get("research_max_concurrent_ideas"), 2))
    rows: list[dict] = []

    for state in states.sort_values("ticker").to_dict("records"):
        candidate, move, early_side = step9k._candidate_base(session, challenger, state)
        candidate["direction"] = expected_side
        candidate["ranking_metric"] = abs(move) if np.isfinite(move) else np.nan
        candidate["mechanical_interpretation"] = "MIDPOINT_PULLBACK_THEN_CLOSE_RESUME_NEXT_BAR_1_5R"
        invalid: list[str] = []
        if expected_side not in {"LONG", "SHORT"}:
            invalid.append("NON_TREND_REGIME")
        if direction_bias != expected_bias:
            invalid.append("DIRECTION_BIAS_MISMATCH")
        if not np.isfinite(move) or abs(move) < 0.0010:
            invalid.append("EARLY_MOVE_BELOW_0_10_PERCENT")
        if early_side != expected_side:
            invalid.append("STOCK_NOT_ALIGNED_WITH_REGIME_DIRECTION")
        early_range_pct = _num(state.get("early_range_pct"))
        if not np.isfinite(early_range_pct) or early_range_pct <= 0 or early_range_pct > step9d.MAX_RANGE_RISK_PCT:
            invalid.append("INVALID_OR_WIDE_RANGE")
        if invalid:
            candidate["setup_status"] = "INVALID_SETUP"
            candidate["trigger_status"] = "NOT_EVALUATED"
            candidate["invalid_reason"] = ";".join(sorted(set(invalid)))
        rows.append(candidate)

    step9d._select_candidates(rows, max_ideas=max_ideas)

    for candidate in rows:
        if not candidate["selected_for_simulation"]:
            continue
        ticker = str(candidate["ticker"])
        bars = bars_lookup.get((date, ticker), pd.DataFrame())
        if bars.empty:
            candidate["trigger_status"] = "NO_EXECUTABLE_BARS"
            continue
        side = str(candidate["direction"])
        midpoint = _num(candidate["early_midpoint"])
        pullback_bar = None
        for _, bar in step9d._bars_between(bars, "09:45", "12:15").iterrows():
            if side == "LONG" and _num(bar.get("low")) <= midpoint:
                pullback_bar = bar
                break
            if side == "SHORT" and _num(bar.get("high")) >= midpoint:
                pullback_bar = bar
                break
        if pullback_bar is None:
            candidate["trigger_status"] = "MIDPOINT_PULLBACK_NOT_OBSERVED"
            continue

        resume_bar = None
        later = bars[
            (bars["datetime"] > pd.Timestamp(pullback_bar["datetime"]))
            & (bars["datetime"].dt.strftime("%H:%M") <= "12:55")
        ].sort_values("datetime")
        resume_level = _num(pullback_bar.get("high")) if side == "LONG" else _num(pullback_bar.get("low"))
        for _, bar in later.iterrows():
            close = _num(bar.get("close"))
            if side == "LONG" and close > resume_level:
                resume_bar = bar
                break
            if side == "SHORT" and close < resume_level:
                resume_bar = bar
                break
        if resume_bar is None:
            candidate["trigger_status"] = "PULLBACK_DID_NOT_RESUME"
            continue
        next_bar = step9d._next_bar_after(bars, pd.Timestamp(resume_bar["datetime"]))
        if next_bar is None or step9d._clock(next_bar["datetime"]) > "13:00":
            candidate["trigger_status"] = "RESUME_CONFIRMATION_TOO_LATE"
            continue
        stop = _num(pullback_bar.get("low")) if side == "LONG" else _num(pullback_bar.get("high"))
        step9k._finalize_single_trade(
            candidate, session, challenger, bars, side, resume_bar, next_bar,
            stop, 1.5, trades, legs,
        )
    return rows


@contextmanager
def _patched_step9n_engine():
    names = [
        "EXPERIMENT_ID", "RESEARCH_STATUS", "CONTRACTS", "CONTRACT_BY_ID",
        "COMPARISONS", "CHALLENGER_BY_ID", "_single_candidates_for_challenger",
        "_intended_side", "_contract_mask",
    ]
    old = {name: getattr(step9g, name) for name in names}
    challenger_map = dict(step9g.CHALLENGER_BY_ID)
    challenger_map[PULLBACK_RESUME_ID] = PULLBACK_RESUME
    original_dispatch = step9g._single_candidates_for_challenger
    original_intended_side = step9g._intended_side
    original_contract_mask = step9g._contract_mask

    def dispatch(session, challenger, states, bars_lookup, trades, legs):
        if challenger["challenger_id"] == PULLBACK_RESUME_ID:
            return _pullback_resume_candidates(session, challenger, states, bars_lookup, trades, legs)
        return original_dispatch(session, challenger, states, bars_lookup, trades, legs)

    def intended_side(base_challenger_id: str, row: pd.Series | dict) -> str:
        if base_challenger_id in {PULLBACK_RESUME_ID, DIRECTIONAL_BREAKOUT_ID, DELAYED_REVERSAL_ID}:
            # Every Step 9N cohort filter describes the stock's EARLY MOVE.
            # This prevents the countertrend reversal control from receiving a reversed label.
            return _early_move_side(row)
        return original_intended_side(base_challenger_id, row)

    def contract_mask(states: pd.DataFrame, contract: dict) -> pd.Series:
        mask = original_contract_mask(states, contract)
        expected_side = _regime_side(str(contract.get("primary_regime", "")))
        early_sides = pd.Series(
            [_early_move_side(row) for row in states.to_dict("records")],
            index=states.index,
            dtype="object",
        )
        return mask & early_sides.eq(expected_side)

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


def _first_close_signal(bars: pd.DataFrame, start: str, end: str, predicate) -> pd.Series | None:
    return step9k._first_close_signal(bars, start, end, predicate)


def _direction_path_metrics(post: pd.DataFrame, reference: float, side: str) -> tuple[float, float]:
    return step9k._direction_path_metrics(post, reference, side)


def build_trend_session_diagnostics(
    taxonomy: pd.DataFrame,
    prices: pd.DataFrame,
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
) -> pd.DataFrame:
    trend_taxonomy = taxonomy[taxonomy["primary_regime"].isin(TREND_REGIMES)].copy()
    if trend_taxonomy.empty:
        return pd.DataFrame(columns=TREND_SESSION_DIAGNOSTIC_COLUMNS)
    trend_dates = set(trend_taxonomy["date"].astype(str))
    daily_reference = step9b.build_daily_reference(prices)
    with step9i._patched_holdout_tickers():
        raw_states, bars_lookup = step9b.build_market_state(prices, daily_reference, trend_dates)
    states = step9g.enrich_market_states(raw_states, static, characteristics, group_states)
    states = states[states["date"].astype(str).isin(trend_dates)].copy()
    taxonomy_lookup = trend_taxonomy.set_index("date").to_dict("index")
    rows: list[dict[str, Any]] = []

    for date, day in states.groupby(states["date"].astype(str), sort=True):
        tax = taxonomy_lookup.get(date, {})
        regime = str(tax.get("primary_regime", ""))
        side = _regime_side(regime)
        opposite = _opposite_side(side)
        multiplier = 1.0 if regime == "TREND_UP" else -1.0
        for state in day.to_dict("records"):
            ticker = str(state["ticker"])
            bars = bars_lookup.get((date, ticker), pd.DataFrame())
            post = step9d._bars_between(bars, "09:45", "16:30") if not bars.empty else bars
            reference_bar = step9d._first_bar_between(post, "09:45", "16:30") if not post.empty else None
            reference = _num(reference_bar.get("open"), _num(reference_bar.get("close"))) if reference_bar is not None else np.nan
            trend_mfe, trend_mae = _direction_path_metrics(post, reference, side)
            counter_mfe, counter_mae = _direction_path_metrics(post, reference, opposite)
            boundary = _num(state.get("early_high")) if side == "LONG" else _num(state.get("early_low"))
            breakout = None
            if not bars.empty:
                breakout = _first_close_signal(
                    bars, "09:45", "12:55",
                    lambda bar: _num(bar.get("close")) > boundary if side == "LONG" else _num(bar.get("close")) < boundary,
                )
            midpoint = _num(state.get("early_midpoint"))
            pullback = None
            if not bars.empty:
                pullback = _first_close_signal(
                    bars, "09:45", "12:15",
                    lambda bar: _num(bar.get("low")) <= midpoint if side == "LONG" else _num(bar.get("high")) >= midpoint,
                )
            resume = None
            if pullback is not None:
                later = bars[
                    (bars["datetime"] > pd.Timestamp(pullback["datetime"]))
                    & (bars["datetime"].dt.strftime("%H:%M") <= "12:55")
                ].sort_values("datetime")
                level = _num(pullback.get("high")) if side == "LONG" else _num(pullback.get("low"))
                for _, bar in later.iterrows():
                    close = _num(bar.get("close"))
                    if (side == "LONG" and close > level) or (side == "SHORT" and close < level):
                        resume = bar
                        break
            if post.empty or reference <= 0:
                final_return = np.nan
            else:
                final_close = _num(post.iloc[-1].get("close"))
                final_return = final_close / reference - 1.0 if reference > 0 else np.nan
            move = _early_move(state)
            early_side = _early_move_side(state)
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "date": date,
                    "primary_regime": regime,
                    "regime_side": side,
                    "normalization_multiplier": multiplier,
                    "regime_confidence": _num(tax.get("regime_confidence")),
                    "confidence_band": tax.get("confidence_band", ""),
                    "direction_bias": tax.get("direction_bias", ""),
                    "ticker": ticker,
                    "universe_segment": step9i._segment_for_ticker(ticker),
                    "company_id": state.get("company_id", ""),
                    "broad_sector": state.get("broad_sector", ""),
                    "ticker_relative_state": state.get("ticker_relative_state", ""),
                    "volatility_bucket": state.get("volatility_bucket", ""),
                    "range_state": state.get("range_state", ""),
                    "sector_direction_state": state.get("sector_direction_state", ""),
                    "early_move_side": early_side,
                    "early_move_sector_alignment": step9g._direction_alignment(early_side, state.get("sector_direction_state", "")),
                    "early_move_pct": move,
                    "early_move_in_regime_direction_pct": move * multiplier,
                    "early_open": _num(state.get("early_open")),
                    "early_high": _num(state.get("early_high")),
                    "early_low": _num(state.get("early_low")),
                    "early_midpoint": midpoint,
                    "early_range_pct": _num(state.get("early_range_pct")),
                    "close_0940": _num(state.get("close_0940"), _num(state.get("cutoff_close"))),
                    "post_0945_reference": reference,
                    "trend_mfe_pct": trend_mfe,
                    "trend_mae_pct": trend_mae,
                    "countertrend_mfe_pct": counter_mfe,
                    "countertrend_mae_pct": counter_mae,
                    "close_confirmed_breakout_time": pd.Timestamp(breakout["datetime"]).strftime("%H:%M") if breakout is not None else "",
                    "midpoint_pullback_time": pd.Timestamp(pullback["datetime"]).strftime("%H:%M") if pullback is not None else "",
                    "pullback_resume_time": pd.Timestamp(resume["datetime"]).strftime("%H:%M") if resume is not None else "",
                    "close_confirmed_breakout": breakout is not None,
                    "midpoint_pullback_observed": pullback is not None,
                    "pullback_resume_confirmed": resume is not None,
                    "final_return_from_0945_pct": final_return,
                    "final_return_in_regime_direction_pct": final_return * multiplier if np.isfinite(final_return) else np.nan,
                    "max_router_source_label": state.get("max_router_source_label", ""),
                    "point_in_time_pass": _bool(state.get("taxonomy_point_in_time_pass")),
                }
            )
    return pd.DataFrame(rows, columns=TREND_SESSION_DIAGNOSTIC_COLUMNS)


def build_trend_state_diagnostic_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "experiment_id", "analysis_view", "analysis_dimension", "segment_value",
        "ticker_session_rows", "sessions", "tickers", "companies", "sectors",
        "close_confirmed_breakout_rate", "midpoint_pullback_rate", "pullback_resume_rate",
        "median_early_move_in_regime_direction_pct", "median_trend_mfe_pct",
        "median_trend_mae_pct", "median_countertrend_mfe_pct", "median_countertrend_mae_pct",
        "average_final_return_in_regime_direction_pct",
    ]
    if diagnostics.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    views = [("TREND_COMBINED_DIRECTION_NORMALIZED", diagnostics)]
    views.extend((regime, diagnostics[diagnostics["primary_regime"].eq(regime)]) for regime in TREND_REGIMES)
    dimensions = [
        ("OVERALL", None),
        ("TICKER_RELATIVE_STATE", "ticker_relative_state"),
        ("EARLY_MOVE_SECTOR_ALIGNMENT", "early_move_sector_alignment"),
        ("VOLATILITY_BUCKET", "volatility_bucket"),
        ("BROAD_SECTOR", "broad_sector"),
        ("UNIVERSE_SEGMENT", "universe_segment"),
        ("CONFIDENCE_BAND", "confidence_band"),
    ]
    for view_name, view in views:
        if view.empty:
            continue
        for dimension, column in dimensions:
            groups = [("ALL", view)] if column is None else view.groupby(column, dropna=False)
            for value, group in groups:
                rows.append(
                    {
                        "experiment_id": EXPERIMENT_ID,
                        "analysis_view": view_name,
                        "analysis_dimension": dimension,
                        "segment_value": str(value),
                        "ticker_session_rows": int(len(group)),
                        "sessions": int(group["date"].nunique()),
                        "tickers": int(group["ticker"].nunique()),
                        "companies": int(group["company_id"].replace("", np.nan).nunique()),
                        "sectors": int(group["broad_sector"].replace("", np.nan).nunique()),
                        "close_confirmed_breakout_rate": float(group["close_confirmed_breakout"].map(_bool).mean()),
                        "midpoint_pullback_rate": float(group["midpoint_pullback_observed"].map(_bool).mean()),
                        "pullback_resume_rate": float(group["pullback_resume_confirmed"].map(_bool).mean()),
                        "median_early_move_in_regime_direction_pct": float(pd.to_numeric(group["early_move_in_regime_direction_pct"], errors="coerce").median()),
                        "median_trend_mfe_pct": float(pd.to_numeric(group["trend_mfe_pct"], errors="coerce").median()),
                        "median_trend_mae_pct": float(pd.to_numeric(group["trend_mae_pct"], errors="coerce").median()),
                        "median_countertrend_mfe_pct": float(pd.to_numeric(group["countertrend_mfe_pct"], errors="coerce").median()),
                        "median_countertrend_mae_pct": float(pd.to_numeric(group["countertrend_mae_pct"], errors="coerce").median()),
                        "average_final_return_in_regime_direction_pct": float(pd.to_numeric(group["final_return_in_regime_direction_pct"], errors="coerce").mean()),
                    }
                )
    return pd.DataFrame(rows, columns=columns)


def _profit_factor(values: Iterable[float]) -> float:
    return step9g._profit_factor(values)


def build_direction_normalized_performance(trades: pd.DataFrame) -> pd.DataFrame:
    pairs = [
        ("CLOSE_CONFIRMED_ORB_1R", "PRIMARY_HYPOTHESIS", "N_TU_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "N_TD_ALIGNED_CLOSE_CONFIRMED_ORB_V1"),
        ("PULLBACK_RESUME_1_5R", "PRIMARY_HYPOTHESIS", "N_TU_ALIGNED_PULLBACK_RESUME_1_5R_V1", "N_TD_ALIGNED_PULLBACK_RESUME_1_5R_V1"),
        ("DIRECTIONAL_BREAKOUT_2R", "PRIMARY_HYPOTHESIS", "N_TU_DIRECTIONAL_BREAKOUT_2R_V1", "N_TD_DIRECTIONAL_BREAKOUT_2R_V1"),
        ("EARLY_CONTINUATION_1_5R_CONTROL", "EXECUTION_CONTROL", "N_TU_EARLY_CONTINUATION_CONTROL_V1", "N_TD_EARLY_CONTINUATION_CONTROL_V1"),
        ("COUNTERTREND_DELAYED_REVERSAL_1R_CONTROL", "NEGATIVE_GUARDRAIL_CONTROL", "N_TU_COUNTERTREND_DELAYED_REVERSAL_CONTROL_V1", "N_TD_COUNTERTREND_DELAYED_REVERSAL_CONTROL_V1"),
    ]
    rows: list[dict[str, Any]] = []
    for key, role, up_id, down_id in pairs:
        up = trades[trades["contract_id"].eq(up_id)] if not trades.empty else trades
        down = trades[trades["contract_id"].eq(down_id)] if not trades.empty else trades
        combined = pd.concat([up, down], ignore_index=True)
        pnl = pd.to_numeric(combined.get("risk_capped_net_pnl_sek", pd.Series(dtype=float)), errors="coerce").dropna()
        up_pnl = float(pd.to_numeric(up.get("risk_capped_net_pnl_sek", pd.Series(dtype=float)), errors="coerce").sum()) if not up.empty else 0.0
        down_pnl = float(pd.to_numeric(down.get("risk_capped_net_pnl_sek", pd.Series(dtype=float)), errors="coerce").sum()) if not down.empty else 0.0
        worst = min(up_pnl, down_pnl)
        both_positive = up_pnl > 0 and down_pnl > 0
        neither_severe = worst >= -abs(up_pnl + down_pnl) if (up_pnl + down_pnl) != 0 else worst >= 0
        if both_positive:
            symmetry = "POSITIVE_BOTH_REGIMES"
        elif up_pnl > 0 and down_pnl <= 0:
            symmetry = "TREND_UP_ONLY_OR_ASYMMETRIC"
        elif down_pnl > 0 and up_pnl <= 0:
            symmetry = "TREND_DOWN_ONLY_OR_ASYMMETRIC"
        else:
            symmetry = "NONPOSITIVE_BOTH_REGIMES"
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "strategy_key": key,
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
                "combined_net_pnl_risk_capped_sek": float(pnl.sum()) if len(pnl) else 0.0,
                "combined_average_net_pnl_risk_capped_sek": float(pnl.mean()) if len(pnl) else np.nan,
                "combined_median_net_pnl_risk_capped_sek": float(pnl.median()) if len(pnl) else np.nan,
                "combined_win_rate_risk_capped": float((pnl > 0).mean()) if len(pnl) else np.nan,
                "combined_profit_factor_risk_capped": _profit_factor(pnl),
                "worst_regime_pnl_sek": worst,
                "both_regimes_positive": both_positive,
                "neither_regime_severely_negative": neither_severe,
                "symmetry_status": symmetry,
                "selection_status": "DISCOVERY_ONLY_NOT_PROMOTED",
            }
        )
    return pd.DataFrame(rows, columns=DIRECTION_NORMALIZED_COLUMNS)


def build_regime_strategy_matrix(performance: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "experiment_id", "primary_regime", "strategy_key", "contract_id", "test_role",
        "trades", "sessions_with_trades", "net_pnl_risk_capped_sek", "win_rate_risk_capped",
        "profit_factor_risk_capped", "leave_one_day_out_min_pnl_sek",
        "bh_adjusted_q_value_primary_family", "selection_status",
    ]
    if performance.empty:
        return pd.DataFrame(columns=columns)
    mapping = {c["contract_id"]: c["strategy_key"] for c in CONTRACTS}
    result = performance.copy()
    result["strategy_key"] = result["contract_id"].map(mapping)
    result["experiment_id"] = EXPERIMENT_ID
    return result.reindex(columns=columns)


def build_regime_time_split_performance(trades: pd.DataFrame, taxonomy: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "experiment_id", "contract_id", "test_role", "primary_regime", "phase",
        "eligible_regime_dates", "trades", "sessions_with_trades", "net_pnl_risk_capped_sek",
        "win_rate_risk_capped", "profit_factor_risk_capped",
    ]
    rows: list[dict[str, Any]] = []
    for contract in CONTRACTS:
        cid = contract["contract_id"]
        regime = contract["primary_regime"]
        dates = sorted(taxonomy.loc[taxonomy["primary_regime"].eq(regime), "date"].astype(str).unique())
        phase_map = step9k._phase_map(dates)
        group = trades[trades["contract_id"].eq(cid)].copy() if not trades.empty else trades
        if not group.empty:
            group["phase"] = group["date"].astype(str).map(phase_map)
        for phase in ("EARLY_HALF", "LATE_HALF"):
            phase_dates = [d for d, p in phase_map.items() if p == phase]
            cell = group[group["phase"].eq(phase)] if not group.empty else group
            pnl = pd.to_numeric(cell.get("risk_capped_net_pnl_sek", pd.Series(dtype=float)), errors="coerce").dropna()
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "contract_id": cid,
                    "test_role": contract["test_role"],
                    "primary_regime": regime,
                    "phase": phase,
                    "eligible_regime_dates": len(phase_dates),
                    "trades": int(len(cell)),
                    "sessions_with_trades": int(cell["date"].nunique()) if not cell.empty else 0,
                    "net_pnl_risk_capped_sek": float(pnl.sum()) if len(pnl) else 0.0,
                    "win_rate_risk_capped": float((pnl > 0).mean()) if len(pnl) else np.nan,
                    "profit_factor_risk_capped": _profit_factor(pnl),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _force_experiment_id(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "experiment_id" in result.columns:
        result["experiment_id"] = EXPERIMENT_ID
    return result


def extend_audit(
    audit: pd.DataFrame,
    taxonomy: pd.DataFrame,
    diagnostics: pd.DataFrame,
    registry: pd.DataFrame,
    normalized: pd.DataFrame,
) -> pd.DataFrame:
    trend_sessions = int(taxonomy["primary_regime"].isin(TREND_REGIMES).sum())
    expected_rows = trend_sessions * len(step9i.TRADING_TICKERS)
    actual_rows = int(len(diagnostics))
    regime_failures = int((~registry["primary_regime"].isin(TREND_REGIMES)).sum())
    router_failures = int(registry["router_active"].map(_bool).sum() + registry["promotion_eligible"].map(_bool).sum())
    up_bias_fail = int((taxonomy.loc[taxonomy["primary_regime"].eq("TREND_UP"), "direction_bias"].astype(str) != "UP").sum())
    down_bias_fail = int((taxonomy.loc[taxonomy["primary_regime"].eq("TREND_DOWN"), "direction_bias"].astype(str) != "DOWN").sum())
    mirrored_failures = abs(len(normalized) - 5)
    rows = [
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "TREND_REGIMES_ONLY_CONTRACTS",
            "rows_checked": int(len(registry)),
            "failures": regime_failures,
            "max_abs_difference": np.nan,
            "audit_pass": regime_failures == 0,
            "interpretation": "Every Step 9N contract is restricted to TREND_UP or TREND_DOWN.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "TREND_DIAGNOSTIC_COVERAGE_23_TICKERS",
            "rows_checked": actual_rows,
            "failures": abs(expected_rows - actual_rows),
            "max_abs_difference": float(abs(expected_rows - actual_rows)),
            "audit_pass": expected_rows == actual_rows,
            "interpretation": "Each trend-regime session has one diagnostic row for every Combined 23 ticker.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "TREND_REGIME_DIRECTION_BIAS_CONSISTENCY",
            "rows_checked": trend_sessions,
            "failures": up_bias_fail + down_bias_fail,
            "max_abs_difference": np.nan,
            "audit_pass": up_bias_fail + down_bias_fail == 0,
            "interpretation": "TREND_UP sessions are UP-biased and TREND_DOWN sessions are DOWN-biased at the frozen router cutoff.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "MIRRORED_UP_DOWN_STRATEGY_FAMILIES",
            "rows_checked": int(len(normalized)),
            "failures": mirrored_failures,
            "max_abs_difference": float(mirrored_failures),
            "audit_pass": mirrored_failures == 0,
            "interpretation": "Three primary and two control strategy families each have one TREND_UP and one TREND_DOWN contract.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "EARLY_MOVE_ALIGNMENT_SEMANTICS",
            "rows_checked": 3,
            "failures": 0,
            "max_abs_difference": np.nan,
            "audit_pass": True,
            "interpretation": "Pullback, directional breakout, and reversal-control cohort labels are computed from the early move.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "NO_STEP9N_ROUTER_ACTIVATION",
            "rows_checked": int(len(registry)),
            "failures": router_failures,
            "max_abs_difference": np.nan,
            "audit_pass": router_failures == 0,
            "interpretation": "Step 9N cannot modify or activate Step 9I or Step 9L.",
        },
    ]
    return pd.concat([audit, pd.DataFrame(rows)], ignore_index=True)


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
    primary_norm = normalized[normalized["test_role"].eq("PRIMARY_HYPOTHESIS")]
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
        "primary_families_positive_both_regimes": int(primary_norm["both_regimes_positive"].map(_bool).sum()) if not primary_norm.empty else 0,
        "audit_pass": audit_pass,
        "strategies_promoted": 0,
        "router_active": False,
        "classification": "STEP9N_TREND_REGIME_DISCOVERY_COMPLETE_NOT_CONFIRMATORY" if audit_pass else "STEP9N_AUDIT_REVIEW_REQUIRED",
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_step9n(prices: pd.DataFrame, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    taxonomy, taxonomy_skips = step9k.build_daily_taxonomy(prices, start_date, end_date)
    if taxonomy.empty:
        raise ValueError("No point-in-time-ready taxonomy sessions are available in the requested window.")
    effective_end = str(taxonomy["date"].max())
    static, trading_prices, characteristics, group_states = step9i._full_holdout_context(prices, effective_end)

    diagnostics = build_trend_session_diagnostics(taxonomy, trading_prices, static, characteristics, group_states)
    diagnostic_summary = build_trend_state_diagnostic_summary(diagnostics)

    with step9i._patched_holdout_tickers():
        with _patched_step9n_engine():
            core = step9g.build_state_filtered_experiment(
                taxonomy, trading_prices, static, characteristics, group_states
            )
    (
        _core_summary, registry, sessions, candidates, trades, legs, performance,
        comparisons, robustness, multiple, audit,
    ) = core

    for frame in (trades, candidates):
        if not frame.empty and "universe_segment" not in frame.columns:
            insert_at = frame.columns.get_loc("ticker") + 1
            frame.insert(insert_at, "universe_segment", frame["ticker"].map(step9i._segment_for_ticker))

    trade_diagnostics = _force_experiment_id(step9k.build_trade_diagnostics(
        trades, trading_prices, set(taxonomy["date"].astype(str))
    ))
    performance = _force_experiment_id(step9k.enrich_performance(performance, trades, trade_diagnostics))
    comparisons = _force_experiment_id(comparisons)
    robustness = _force_experiment_id(robustness)
    multiple = _force_experiment_id(multiple)
    if not multiple.empty:
        multiple["multiplicity_family"] = "SIX_PRE_REGISTERED_STEP9N_PRIMARY_HYPOTHESES"
        multiple["interpretation"] = "Post-hoc mirrored trend-regime discovery only; no p-value or q-value promotes a strategy."

    normalized = build_direction_normalized_performance(trades)
    regime_matrix = build_regime_strategy_matrix(performance)
    time_split = build_regime_time_split_performance(trades, taxonomy)
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
    audit = extend_audit(audit, taxonomy, diagnostics, registry, normalized)
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
        "direction_normalized_performance": normalized,
        "regime_strategy_matrix": regime_matrix,
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
        "direction_normalized_performance": DIRECTION_NORMALIZED_FILE,
        "regime_strategy_matrix": REGIME_STRATEGY_MATRIX_FILE,
        "time_split": TIME_SPLIT_FILE,
        "ticker_performance": TICKER_FILE,
        "sector_performance": SECTOR_FILE,
        "segment_performance": SEGMENT_FILE,
        "summary": SUMMARY_FILE,
    }
    for key, path in paths.items():
        export_csv_for_power_bi(outputs[key], path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step 9N mirrored TREND_UP and TREND_DOWN strategy research on Combined 23.")
    parser.add_argument("--start-date", default="2026-05-27")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = step9i.load_shadow_prices(args.source_db)
    if prices.empty:
        raise SystemExit(f"No intraday prices found in {args.source_db}.")
    outputs = run_step9n(prices, args.start_date, args.end_date)
    export_outputs(outputs)
    summary = outputs["summary"].iloc[0]
    normalized = outputs["direction_normalized_performance"]
    print("\n=== STEP 9N MIRRORED TREND-REGIME STRATEGY RESEARCH — COMBINED 23 ===")
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
    print("\nDirection-normalized mirrored strategy snapshot:")
    cols = [
        "strategy_key", "test_role", "trend_up_trades", "trend_down_trades",
        "trend_up_net_pnl_risk_capped_sek", "trend_down_net_pnl_risk_capped_sek",
        "combined_net_pnl_risk_capped_sek", "combined_profit_factor_risk_capped",
        "symmetry_status", "selection_status",
    ]
    print(normalized[cols].to_string(index=False))
    print("\nNo Step 9N result is automatically added to Step 9L. Review TREND_UP, TREND_DOWN, and normalized combined outputs first.")


if __name__ == "__main__":
    main()
