from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, REFERENCE_DATA_DIR, legacy_output_path
from RegimeTrading.scripts.research_regime_aware_gap_recovery import build_daily_reference, load_intraday_prices
from RegimeTrading.scripts.step9b_baseline_trade_generation import build_market_state
from RegimeTrading.scripts.step9d_regime_strategy_challenger_matrix import (
    CHALLENGER_BY_ID,
    _single_candidates_for_challenger,
)


EXPERIMENT_ID = "REGIME_STATE_FILTERED_CONTRACT_EXPERIMENTS_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_PRE_REGISTERED_STATE_FILTERED_DISCOVERY_NOT_ROUTER_ACTIVE"
LATEST_ROUTER_BAR_LABEL = "09:40"
EXECUTION_START = "09:45"
MINIMUM_SCREENING_TRADES = 8
MINIMUM_SCREENING_SESSIONS = 4
BOOTSTRAP_ITERATIONS = 5000
SIGN_FLIP_ITERATIONS = 10000
RANDOM_SEED = 9027

TAXONOMY_FILE = DATA_DIR / "regime_daily_taxonomy.csv"
STATIC_FILE = REFERENCE_DATA_DIR / "instrument_static_taxonomy.csv"
CHARACTERISTIC_FILE = REFERENCE_DATA_DIR / "instrument_point_in_time_characteristics.csv"
GROUP_STATE_FILE = REFERENCE_DATA_DIR / "instrument_group_daily_state.csv"

SUMMARY_FILE = legacy_output_path("regime_state_filtered_summary.csv")
REGISTRY_FILE = legacy_output_path("regime_state_filtered_contract_registry.csv")
SESSION_FILE = legacy_output_path("regime_state_filtered_session_coverage.csv")
CANDIDATE_FILE = legacy_output_path("regime_state_filtered_candidates.csv")
TRADE_FILE = legacy_output_path("regime_state_filtered_trades.csv")
LEG_FILE = legacy_output_path("regime_state_filtered_trade_legs.csv")
PERFORMANCE_FILE = legacy_output_path("regime_state_filtered_performance.csv")
COMPARISON_FILE = legacy_output_path("regime_state_filtered_same_cohort_comparisons.csv")
ROBUSTNESS_FILE = legacy_output_path("regime_state_filtered_robustness.csv")
MULTIPLE_TESTING_FILE = legacy_output_path("regime_state_filtered_multiple_testing.csv")
AUDIT_FILE = legacy_output_path("regime_state_filtered_audit.csv")


# Fixed before Step 9G results are observed. Complements are explicit controls, not
# alternative winners added after seeing the output.
CONTRACTS = [
    {
        "contract_id": "TU_EARLY_LEADER_RANGE_REJECTION_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "TREND_UP",
        "base_challenger_id": "RANGE_REJECTION_REVERSION_1_25R_V1",
        "cohort_id": "TU_RANGE_REJECTION_RELATIVE_STATE",
        "comparison_group": "TU_RANGE_REJECTION_LEADER_VS_LAGGARD",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "In a rising market, an early relative leader offers a favorable long/short range-rejection entry after temporary adverse movement is rejected.",
        "economic_interpretation": "Supportive market regime plus stock-level rejection rather than breakout chasing.",
    },
    {
        "contract_id": "TU_EARLY_LAGGARD_RANGE_REJECTION_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "TREND_UP",
        "base_challenger_id": "RANGE_REJECTION_REVERSION_1_25R_V1",
        "cohort_id": "TU_RANGE_REJECTION_RELATIVE_STATE",
        "comparison_group": "TU_RANGE_REJECTION_LEADER_VS_LAGGARD",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "Complement control for the TREND_UP early-leader range-rejection hypothesis.",
        "economic_interpretation": "Tests whether the finding is specific to leaders rather than any non-neutral stock.",
    },
    {
        "contract_id": "VE_GROUP_ALIGNED_EARLY_CONTINUATION_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "VOLATILITY_EXPANSION",
        "base_challenger_id": "EARLY_MOVE_CONTINUATION_1_5R_V1",
        "cohort_id": "VE_GROUP_ALIGNED_DIRECTIONAL",
        "comparison_group": "VE_EARLY_CONTINUATION_ALIGNMENT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "During volatility expansion, early moves aligned with the stock's group continue.",
        "economic_interpretation": "Group confirmation validates directional continuation.",
    },
    {
        "contract_id": "VE_GROUP_CONTRARIAN_EARLY_CONTINUATION_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "VOLATILITY_EXPANSION",
        "base_challenger_id": "EARLY_MOVE_CONTINUATION_1_5R_V1",
        "cohort_id": "VE_GROUP_CONTRARIAN_DIRECTIONAL",
        "comparison_group": "VE_EARLY_CONTINUATION_ALIGNMENT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "CONTRARIAN_TO_GROUP",
        "hypothesis": "Complement control for group-aligned early continuation.",
        "economic_interpretation": "Tests whether continuation survives when the stock direction conflicts with its group.",
    },
    {
        "contract_id": "VE_GROUP_ALIGNED_CLOSE_CONFIRMED_ORB_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "VOLATILITY_EXPANSION",
        "base_challenger_id": "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1",
        "cohort_id": "VE_GROUP_ALIGNED_DIRECTIONAL",
        "comparison_group": "VE_CLOSE_ORB_ALIGNMENT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "During volatility expansion, a group-aligned close-confirmed opening-range break has positive continuation value.",
        "economic_interpretation": "A later close confirmation may reduce false breaks while preserving group alignment.",
    },
    {
        "contract_id": "VE_GROUP_CONTRARIAN_CLOSE_CONFIRMED_ORB_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "VOLATILITY_EXPANSION",
        "base_challenger_id": "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1",
        "cohort_id": "VE_GROUP_CONTRARIAN_DIRECTIONAL",
        "comparison_group": "VE_CLOSE_ORB_ALIGNMENT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "CONTRARIAN_TO_GROUP",
        "hypothesis": "Complement control for group-aligned close-confirmed ORB.",
        "economic_interpretation": "Tests whether confirmation alone is sufficient without group agreement.",
    },
    {
        "contract_id": "HD_EARLY_LAGGARD_CONTINUATION_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": "EARLY_MOVE_CONTINUATION_1_5R_V1",
        "cohort_id": "HD_EARLY_LAGGARD",
        "comparison_group": "HD_CONTINUATION_LAGGARD_VS_LEADER",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "During high dispersion, early laggards continue in their initial direction when a continuation trigger occurs.",
        "economic_interpretation": "Persistent cross-sectional weakness after 09:45.",
    },
    {
        "contract_id": "HD_EARLY_LEADER_CONTINUATION_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": "EARLY_MOVE_CONTINUATION_1_5R_V1",
        "cohort_id": "HD_EARLY_LEADER",
        "comparison_group": "HD_CONTINUATION_LAGGARD_VS_LEADER",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "Complement control for high-dispersion laggard continuation.",
        "economic_interpretation": "Tests whether continuation is asymmetric between laggards and leaders.",
    },
    {
        "contract_id": "HD_EARLY_LAGGARD_DELAYED_REVERSAL_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "HD_EARLY_LAGGARD",
        "comparison_group": "HD_DELAYED_REVERSAL_LAGGARD_VS_LEADER",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "During high dispersion, early laggards reverse after a post-10:00 midpoint confirmation.",
        "economic_interpretation": "The later trigger distinguishes genuine recovery from continued weakness.",
    },
    {
        "contract_id": "HD_EARLY_LEADER_DELAYED_REVERSAL_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "HD_EARLY_LEADER",
        "comparison_group": "HD_DELAYED_REVERSAL_LAGGARD_VS_LEADER",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "Complement control for high-dispersion laggard delayed reversal.",
        "economic_interpretation": "Tests whether delayed reversal is specific to laggards rather than symmetric.",
    },
    {
        "contract_id": "RLV_LAGGARD_HIGH_REL_VOL_DELAYED_REVERSAL_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "RLV_LAGGARD_DELAYED_REVERSAL",
        "comparison_group": "RLV_DELAYED_REVERSAL_HIGH_VS_NOT_HIGH_VOL",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "HIGH_RELATIVE_VOL",
        "sector_alignment_states": "ANY",
        "hypothesis": "In a quiet market, an idiosyncratically high-volatility early laggard is a delayed-reversal candidate.",
        "economic_interpretation": "Broad quiet plus stock-specific dislocation creates reversion potential.",
    },
    {
        "contract_id": "RLV_LAGGARD_NOT_HIGH_REL_VOL_DELAYED_REVERSAL_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "RLV_LAGGARD_DELAYED_REVERSAL",
        "comparison_group": "RLV_DELAYED_REVERSAL_HIGH_VS_NOT_HIGH_VOL",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "LOW_RELATIVE_VOL|MEDIUM_RELATIVE_VOL",
        "sector_alignment_states": "ANY",
        "hypothesis": "Complement control for high-relative-volatility laggard reversal.",
        "economic_interpretation": "Tests whether idiosyncratic volatility adds information beyond laggard status.",
    },
    {
        "contract_id": "RLV_GROUP_CONTRARIAN_RANGE_REJECTION_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "RANGE_REJECTION_REVERSION_1_25R_V1",
        "cohort_id": "RLV_RANGE_REJECTION_ALIGNMENT",
        "comparison_group": "RLV_RANGE_REJECTION_CONTRARIAN_VS_ALIGNED",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "CONTRARIAN_TO_GROUP",
        "hypothesis": "In a quiet market, range rejection works when the intended trade direction is contrary to the stock's group direction.",
        "economic_interpretation": "An idiosyncratic deviation is faded toward the quiet group environment.",
    },
    {
        "contract_id": "RLV_GROUP_ALIGNED_RANGE_REJECTION_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "RANGE_REJECTION_REVERSION_1_25R_V1",
        "cohort_id": "RLV_RANGE_REJECTION_ALIGNMENT",
        "comparison_group": "RLV_RANGE_REJECTION_CONTRARIAN_VS_ALIGNED",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "Complement control for contrarian-to-group range rejection.",
        "economic_interpretation": "Tests whether range rejection loses value when the intended trade follows the group.",
    },
]
CONTRACT_BY_ID = {row["contract_id"]: row for row in CONTRACTS}

# Explicit paired comparisons. The last three compare competing strategies on the
# same pre-entry cohort; the others compare a primary state filter with its complement.
COMPARISONS = [
    ("TU_RANGE_REJECTION_LEADER_MINUS_LAGGARD", "TU_EARLY_LEADER_RANGE_REJECTION_V1", "TU_EARLY_LAGGARD_RANGE_REJECTION_CONTROL_V1", "STATE_COMPLEMENT"),
    ("VE_EARLY_CONT_ALIGNED_MINUS_CONTRARIAN", "VE_GROUP_ALIGNED_EARLY_CONTINUATION_V1", "VE_GROUP_CONTRARIAN_EARLY_CONTINUATION_CONTROL_V1", "STATE_COMPLEMENT"),
    ("VE_CLOSE_ORB_ALIGNED_MINUS_CONTRARIAN", "VE_GROUP_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "VE_GROUP_CONTRARIAN_CLOSE_CONFIRMED_ORB_CONTROL_V1", "STATE_COMPLEMENT"),
    ("HD_CONT_LAGGARD_MINUS_LEADER", "HD_EARLY_LAGGARD_CONTINUATION_V1", "HD_EARLY_LEADER_CONTINUATION_CONTROL_V1", "STATE_COMPLEMENT"),
    ("HD_REV_LAGGARD_MINUS_LEADER", "HD_EARLY_LAGGARD_DELAYED_REVERSAL_V1", "HD_EARLY_LEADER_DELAYED_REVERSAL_CONTROL_V1", "STATE_COMPLEMENT"),
    ("RLV_REV_HIGH_MINUS_NOT_HIGH_VOL", "RLV_LAGGARD_HIGH_REL_VOL_DELAYED_REVERSAL_V1", "RLV_LAGGARD_NOT_HIGH_REL_VOL_DELAYED_REVERSAL_CONTROL_V1", "STATE_COMPLEMENT"),
    ("RLV_REJECTION_CONTRARIAN_MINUS_ALIGNED", "RLV_GROUP_CONTRARIAN_RANGE_REJECTION_V1", "RLV_GROUP_ALIGNED_RANGE_REJECTION_CONTROL_V1", "STATE_COMPLEMENT"),
    ("VE_ALIGNED_EARLY_CONT_MINUS_CLOSE_ORB", "VE_GROUP_ALIGNED_EARLY_CONTINUATION_V1", "VE_GROUP_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "SAME_COHORT_STRATEGY"),
    ("HD_LAGGARD_CONT_MINUS_DELAYED_REV", "HD_EARLY_LAGGARD_CONTINUATION_V1", "HD_EARLY_LAGGARD_DELAYED_REVERSAL_V1", "SAME_COHORT_STRATEGY"),
    ("HD_LEADER_CONT_MINUS_DELAYED_REV", "HD_EARLY_LEADER_CONTINUATION_CONTROL_V1", "HD_EARLY_LEADER_DELAYED_REVERSAL_CONTROL_V1", "SAME_COHORT_STRATEGY_CONTROL"),
]

SUMMARY_COLUMNS = [
    "experiment_id", "research_status", "router_cutoff", "execution_start", "taxonomy_sessions",
    "contracts_registered", "primary_hypotheses", "complement_controls", "same_cohort_comparisons",
    "session_contract_rows", "regime_match_session_rows", "eligible_ticker_rows", "valid_setup_rows",
    "selected_ideas", "triggered_closed_trades", "screenable_contracts", "positive_net_primary_contracts",
    "primary_contracts_with_positive_bootstrap_lower_bound", "primary_contracts_raw_p_below_0_05",
    "primary_contracts_bh_q_below_0_10", "point_in_time_pass_contracts", "execution_invariant_failures",
    "trade_leg_reconciliation_max_abs_diff_equal_notional_sek",
    "trade_leg_reconciliation_max_abs_diff_risk_capped_sek", "strategies_promoted", "router_active",
    "classification",
]
REGISTRY_COLUMNS = [
    "experiment_id", "contract_id", "test_role", "primary_regime", "base_challenger_id", "strategy_family",
    "cohort_id", "comparison_group", "ticker_relative_states", "volatility_buckets",
    "sector_alignment_states", "hypothesis", "economic_interpretation", "pre_registered",
    "router_active", "promotion_eligible",
]
SESSION_COLUMNS = [
    "experiment_id", "date", "contract_id", "test_role", "primary_regime_required",
    "observed_primary_regime", "regime_match", "cohort_id", "eligible_ticker_rows",
    "eligible_independent_companies", "eligible_tickers", "valid_setup_rows", "selected_ideas",
    "triggered_trades", "equal_net_pnl_sek", "risk_capped_net_pnl_sek", "cohort_signature",
    "point_in_time_pass", "coverage_status",
]
CANDIDATE_COLUMNS = [
    "experiment_id", "contract_id", "test_role", "cohort_id", "comparison_group", "date",
    "primary_regime", "base_challenger_id", "idea_id", "ticker", "company_id", "broad_sector",
    "direction", "ticker_relative_state", "volatility_bucket", "range_state", "sector_direction_state",
    "sector_direction_alignment", "contract_eligible", "selection_rank", "selected_for_simulation",
    "setup_status", "trigger_status", "invalid_reason", "ranking_metric", "signal_time", "entry_time",
    "entry_price", "stop_price", "target_price", "exit_time", "exit_reason", "max_router_source_label",
    "point_in_time_pass", "mechanical_interpretation",
]
TRADE_COLUMNS = [
    "experiment_id", "contract_id", "test_role", "cohort_id", "comparison_group", "trade_id", "date",
    "primary_regime", "base_challenger_id", "strategy_family", "direction", "ticker", "company_id",
    "broad_sector", "ticker_relative_state", "volatility_bucket", "range_state", "sector_direction_state",
    "sector_direction_alignment", "regime_confidence", "confidence_band", "entry_time", "entry_price",
    "stop_price", "target_price", "exit_time", "exit_price", "exit_reason", "gross_return",
    "risk_pct_at_entry", "r_multiple_achieved", "trade_duration_minutes", "research_risk_multiplier",
    "equal_notional_sek", "equal_gross_pnl_sek", "equal_cost_sek", "equal_net_pnl_sek",
    "risk_capped_notional_sek", "risk_capped_gross_pnl_sek", "risk_capped_cost_sek",
    "risk_capped_net_pnl_sek", "point_in_time_pass", "execution_invariant_pass",
]
LEG_COLUMNS = [
    "experiment_id", "contract_id", "trade_id", "leg_id", "date", "primary_regime",
    "base_challenger_id", "ticker", "company_id", "broad_sector", "side", "entry_time",
    "entry_price", "exit_time", "exit_price", "exit_reason", "equal_notional_sek",
    "equal_gross_pnl_sek", "equal_cost_sek", "equal_net_pnl_sek", "risk_capped_notional_sek",
    "risk_capped_gross_pnl_sek", "risk_capped_cost_sek", "risk_capped_net_pnl_sek",
]
PERFORMANCE_COLUMNS = [
    "experiment_id", "contract_id", "test_role", "primary_regime", "base_challenger_id",
    "strategy_family", "cohort_id", "eligible_ticker_rows", "eligible_sessions", "valid_setup_rows",
    "selected_ideas", "trades", "sessions_with_trades", "independent_companies", "winning_trades_equal_notional",
    "win_rate_equal_notional", "gross_pnl_equal_notional_sek", "cost_equal_notional_sek",
    "net_pnl_equal_notional_sek", "profit_factor_equal_notional", "winning_trades_risk_capped",
    "win_rate_risk_capped", "gross_pnl_risk_capped_sek", "cost_risk_capped_sek",
    "net_pnl_risk_capped_sek", "average_net_pnl_risk_capped_sek", "median_net_pnl_risk_capped_sek",
    "profit_factor_risk_capped", "top_day_abs_pnl_share", "leave_one_day_out_profitable_share",
    "leave_one_day_out_min_pnl_sek", "bootstrap_total_pnl_ci_lower_95_sek",
    "bootstrap_total_pnl_ci_upper_95_sek", "bootstrap_probability_positive", "one_sided_sign_flip_p_value",
    "bh_adjusted_q_value_primary_family", "sample_status", "statistical_screen_status", "selection_status",
]
COMPARISON_COLUMNS = [
    "experiment_id", "comparison_id", "comparison_type", "left_contract_id", "right_contract_id",
    "left_cohort_id", "right_cohort_id", "cohort_match_required", "cohort_signature_match",
    "comparison_dates", "left_eligible_sessions", "right_eligible_sessions", "left_trades", "right_trades",
    "left_net_pnl_risk_capped_sek", "right_net_pnl_risk_capped_sek", "net_pnl_difference_sek",
    "bootstrap_difference_ci_lower_95_sek", "bootstrap_difference_ci_upper_95_sek",
    "bootstrap_probability_difference_positive", "one_sided_sign_flip_p_value_difference",
    "comparison_status", "selection_status",
]
ROBUSTNESS_COLUMNS = [
    "experiment_id", "contract_id", "test_role", "exclusion_type", "excluded_value", "baseline_trades",
    "excluded_trades", "remaining_trades", "remaining_sessions", "baseline_net_pnl_risk_capped_sek",
    "remaining_net_pnl_risk_capped_sek", "pnl_change_after_exclusion_sek", "remaining_positive",
    "robustness_status",
]
MULTIPLE_TESTING_COLUMNS = [
    "experiment_id", "contract_id", "primary_regime", "base_challenger_id", "test_role", "trades",
    "sessions_with_trades", "one_sided_sign_flip_p_value", "bh_adjusted_q_value", "raw_p_below_0_05",
    "bh_q_below_0_10", "multiplicity_family", "interpretation",
]
AUDIT_COLUMNS = [
    "experiment_id", "audit_item", "rows_checked", "failures", "max_abs_difference", "audit_pass",
    "interpretation",
]


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if pd.isna(value):
        return False
    return bool(value)


def _num(value: object, default: float = np.nan) -> float:
    converted = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(converted) if pd.notna(converted) else default


def _profit_factor(values: Iterable[float]) -> float:
    pnl = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if pnl.empty:
        return np.nan
    gains = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl < 0].sum()))
    return np.nan if losses == 0 else gains / losses


def _direction_alignment(side: str, group_direction: str) -> str:
    side = str(side).upper()
    direction = str(group_direction).upper()
    if direction not in {"UP", "DOWN"} or side not in {"LONG", "SHORT"}:
        return "GROUP_MIXED_OR_UNAVAILABLE"
    if (side == "LONG" and direction == "UP") or (side == "SHORT" and direction == "DOWN"):
        return "ALIGNED_WITH_GROUP"
    return "CONTRARIAN_TO_GROUP"


def _intended_side(base_challenger_id: str, row: pd.Series | dict) -> str:
    early_open = _num(row.get("early_open"))
    cutoff_close = _num(row.get("cutoff_close"))
    early_midpoint = _num(row.get("early_midpoint"))
    close_0940 = _num(row.get("close_0940"), cutoff_close)
    cutoff_return = _num(row.get("cutoff_return_from_open"))
    if base_challenger_id == "RANGE_REJECTION_REVERSION_1_25R_V1":
        if cutoff_close > early_midpoint:
            return "SHORT"
        if cutoff_close < early_midpoint:
            return "LONG"
        return ""
    if base_challenger_id in {"EARLY_MOVE_CONTINUATION_1_5R_V1", "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1"}:
        move = close_0940 / early_open - 1.0 if early_open > 0 else cutoff_return
        return "LONG" if move > 0 else "SHORT" if move < 0 else ""
    if base_challenger_id == "DELAYED_EARLY_MOVE_REVERSAL_1R_V1":
        move = close_0940 / early_open - 1.0 if early_open > 0 else cutoff_return
        return "SHORT" if move > 0 else "LONG" if move < 0 else ""
    return ""


def _split_allowed(value: str) -> set[str] | None:
    text = str(value)
    if text == "ANY":
        return None
    return {item for item in text.split("|") if item}


def _contract_mask(states: pd.DataFrame, contract: dict) -> pd.Series:
    mask = pd.Series(True, index=states.index)
    rel = _split_allowed(contract["ticker_relative_states"])
    vol = _split_allowed(contract["volatility_buckets"])
    alignment = _split_allowed(contract["sector_alignment_states"])
    if rel is not None:
        mask &= states["ticker_relative_state"].isin(rel)
    if vol is not None:
        mask &= states["volatility_bucket"].isin(vol)
    if alignment is not None:
        mask &= states["contract_sector_alignment"].isin(alignment)
    mask &= states["taxonomy_point_in_time_pass"].map(_bool)
    return mask


def enrich_market_states(
    market_states: pd.DataFrame,
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
) -> pd.DataFrame:
    market = market_states.copy()
    market["date"] = market["date"].astype(str)
    static = static.copy()
    characteristics = characteristics.copy()
    characteristics["date"] = characteristics["date"].astype(str)
    group_states = group_states.copy()
    group_states["date"] = group_states["date"].astype(str)
    char_columns = [
        "date", "ticker", "ticker_relative_state", "volatility_bucket", "range_state",
        "historical_tendency", "point_in_time_pass",
    ]
    static_columns = ["ticker", "company_id", "broad_sector"]
    enriched = market.merge(static[static_columns], on="ticker", how="left", validate="many_to_one")
    enriched = enriched.merge(characteristics[char_columns], on=["date", "ticker"], how="left", validate="many_to_one")
    sector = group_states[group_states["aggregation_level"].eq("BROAD_SECTOR")][
        ["date", "group_name", "group_direction_state", "point_in_time_pass"]
    ].rename(
        columns={
            "group_name": "broad_sector",
            "group_direction_state": "sector_direction_state",
            "point_in_time_pass": "sector_state_point_in_time_pass",
        }
    )
    enriched = enriched.merge(sector, on=["date", "broad_sector"], how="left", validate="many_to_one")
    enriched["taxonomy_point_in_time_pass"] = (
        enriched["point_in_time_pass"].map(_bool)
        & enriched["sector_state_point_in_time_pass"].map(_bool)
        & enriched["max_router_source_label"].astype(str).le(LATEST_ROUTER_BAR_LABEL)
    )
    return enriched


def _cohort_signature(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    return ";".join(sorted(f"{d}|{t}" for d, t in zip(frame["date"].astype(str), frame["ticker"].astype(str))))


def _daily_pnl_for_contract(
    contract_id: str,
    session_coverage: pd.DataFrame,
    trades: pd.DataFrame,
    pnl_column: str = "risk_capped_net_pnl_sek",
) -> pd.DataFrame:
    eligible_dates = session_coverage[
        session_coverage["contract_id"].eq(contract_id)
        & session_coverage["regime_match"].map(_bool)
        & session_coverage["eligible_ticker_rows"].gt(0)
    ][["date"]].drop_duplicates()
    daily = trades[trades["contract_id"].eq(contract_id)].groupby("date", as_index=False)[pnl_column].sum()
    return eligible_dates.merge(daily, on="date", how="left").fillna({pnl_column: 0.0}).sort_values("date")


def _bootstrap_total(values: np.ndarray, iterations: int = BOOTSTRAP_ITERATIONS, seed: int = RANDOM_SEED) -> tuple[float, float, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, values.size, size=(iterations, values.size))
    totals = values[indices].sum(axis=1)
    return float(np.quantile(totals, 0.025)), float(np.quantile(totals, 0.975)), float(np.mean(totals > 0))


def _sign_flip_p_value(values: np.ndarray, iterations: int = SIGN_FLIP_ITERATIONS, seed: int = RANDOM_SEED) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0 or np.allclose(values, 0.0):
        return 1.0
    observed = float(values.sum())
    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(iterations, values.size))
    permuted = (signs * values).sum(axis=1)
    return float((1.0 + np.sum(permuted >= observed)) / (iterations + 1.0))


def _bh_adjust(p_values: pd.Series) -> pd.Series:
    values = pd.to_numeric(p_values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna().clip(lower=0.0, upper=1.0)
    if valid.empty:
        return result
    ordered = valid.sort_values()
    m = len(ordered)
    raw = ordered.to_numpy() * m / np.arange(1, m + 1)
    adjusted = np.minimum.accumulate(raw[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    result.loc[ordered.index] = adjusted
    return result


def _concentration(frame: pd.DataFrame) -> tuple[float, float, float]:
    if frame.empty:
        return np.nan, np.nan, np.nan
    daily = frame.groupby("date", as_index=False)["risk_capped_net_pnl_sek"].sum()
    total_abs = float(daily["risk_capped_net_pnl_sek"].abs().sum())
    top_share = float(daily["risk_capped_net_pnl_sek"].abs().max() / total_abs) if total_abs > 0 else np.nan
    baseline = float(daily["risk_capped_net_pnl_sek"].sum())
    remaining = [baseline - float(value) for value in daily["risk_capped_net_pnl_sek"]]
    return (
        top_share,
        float(np.mean([value > 0 for value in remaining])) if remaining else np.nan,
        float(min(remaining)) if remaining else np.nan,
    )


def build_performance(
    registry: pd.DataFrame,
    sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for contract in registry.to_dict("records"):
        cid = contract["contract_id"]
        cov = sessions[sessions["contract_id"].eq(cid)]
        cand = candidates[candidates["contract_id"].eq(cid)]
        group = trades[trades["contract_id"].eq(cid)]
        eligible_sessions = int(cov["eligible_ticker_rows"].gt(0).sum())
        trade_sessions = int(group["date"].nunique()) if not group.empty else 0
        risk_values = pd.to_numeric(group.get("risk_capped_net_pnl_sek", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        equal_values = pd.to_numeric(group.get("equal_net_pnl_sek", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        daily = _daily_pnl_for_contract(cid, sessions, trades)
        daily_values = daily["risk_capped_net_pnl_sek"].to_numpy(dtype=float) if not daily.empty else np.array([])
        ci_low, ci_high, prob_pos = _bootstrap_total(daily_values, seed=RANDOM_SEED + len(rows))
        p_value = _sign_flip_p_value(daily_values, seed=RANDOM_SEED + 100 + len(rows))
        top_share, loo_share, loo_min = _concentration(group)
        sample_status = (
            "SCREENABLE_PRE_REGISTERED_DISCOVERY"
            if len(group) >= MINIMUM_SCREENING_TRADES and trade_sessions >= MINIMUM_SCREENING_SESSIONS
            else "INSUFFICIENT_TRIGGERED_SAMPLE"
        )
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "contract_id": cid,
                "test_role": contract["test_role"],
                "primary_regime": contract["primary_regime"],
                "base_challenger_id": contract["base_challenger_id"],
                "strategy_family": contract["strategy_family"],
                "cohort_id": contract["cohort_id"],
                "eligible_ticker_rows": int(cov["eligible_ticker_rows"].sum()),
                "eligible_sessions": eligible_sessions,
                "valid_setup_rows": int((cand["setup_status"] == "VALID_SETUP").sum()) if not cand.empty else 0,
                "selected_ideas": int(cand["selected_for_simulation"].map(_bool).sum()) if not cand.empty else 0,
                "trades": int(len(group)),
                "sessions_with_trades": trade_sessions,
                "independent_companies": int(group["company_id"].replace("", np.nan).nunique()) if not group.empty else 0,
                "winning_trades_equal_notional": int((equal_values > 0).sum()),
                "win_rate_equal_notional": float((equal_values > 0).mean()) if len(group) else np.nan,
                "gross_pnl_equal_notional_sek": float(pd.to_numeric(group.get("equal_gross_pnl_sek", pd.Series(dtype=float)), errors="coerce").sum()),
                "cost_equal_notional_sek": float(pd.to_numeric(group.get("equal_cost_sek", pd.Series(dtype=float)), errors="coerce").sum()),
                "net_pnl_equal_notional_sek": float(equal_values.sum()),
                "profit_factor_equal_notional": _profit_factor(equal_values),
                "winning_trades_risk_capped": int((risk_values > 0).sum()),
                "win_rate_risk_capped": float((risk_values > 0).mean()) if len(group) else np.nan,
                "gross_pnl_risk_capped_sek": float(pd.to_numeric(group.get("risk_capped_gross_pnl_sek", pd.Series(dtype=float)), errors="coerce").sum()),
                "cost_risk_capped_sek": float(pd.to_numeric(group.get("risk_capped_cost_sek", pd.Series(dtype=float)), errors="coerce").sum()),
                "net_pnl_risk_capped_sek": float(risk_values.sum()),
                "average_net_pnl_risk_capped_sek": float(risk_values.mean()) if len(group) else np.nan,
                "median_net_pnl_risk_capped_sek": float(risk_values.median()) if len(group) else np.nan,
                "profit_factor_risk_capped": _profit_factor(risk_values),
                "top_day_abs_pnl_share": top_share,
                "leave_one_day_out_profitable_share": loo_share,
                "leave_one_day_out_min_pnl_sek": loo_min,
                "bootstrap_total_pnl_ci_lower_95_sek": ci_low,
                "bootstrap_total_pnl_ci_upper_95_sek": ci_high,
                "bootstrap_probability_positive": prob_pos,
                "one_sided_sign_flip_p_value": p_value,
                "bh_adjusted_q_value_primary_family": np.nan,
                "sample_status": sample_status,
                "statistical_screen_status": "PENDING_MULTIPLE_TESTING_REVIEW" if contract["test_role"] == "PRIMARY_HYPOTHESIS" else "COMPLEMENT_CONTROL_NOT_IN_PRIMARY_FAMILY",
                "selection_status": "DISCOVERY_ONLY_NOT_PROMOTED",
            }
        )
    result = pd.DataFrame(rows, columns=PERFORMANCE_COLUMNS)
    primary_mask = result["test_role"].eq("PRIMARY_HYPOTHESIS")
    result.loc[primary_mask, "bh_adjusted_q_value_primary_family"] = _bh_adjust(
        result.loc[primary_mask, "one_sided_sign_flip_p_value"]
    )
    result.loc[primary_mask, "statistical_screen_status"] = np.select(
        [
            result.loc[primary_mask, "sample_status"].ne("SCREENABLE_PRE_REGISTERED_DISCOVERY"),
            result.loc[primary_mask, "bh_adjusted_q_value_primary_family"].lt(0.10),
            result.loc[primary_mask, "one_sided_sign_flip_p_value"].lt(0.05),
        ],
        [
            "INSUFFICIENT_SAMPLE_FOR_STATISTICAL_SCREEN",
            "BH_Q_BELOW_0_10_DISCOVERY_ONLY",
            "RAW_P_BELOW_0_05_NOT_BH_CONTROLLED",
        ],
        default="NO_STATISTICAL_SCREEN_SIGNAL",
    )
    return result


def build_multiple_testing(performance: pd.DataFrame) -> pd.DataFrame:
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")].copy()
    rows = []
    for row in primary.to_dict("records"):
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "contract_id": row["contract_id"],
                "primary_regime": row["primary_regime"],
                "base_challenger_id": row["base_challenger_id"],
                "test_role": row["test_role"],
                "trades": row["trades"],
                "sessions_with_trades": row["sessions_with_trades"],
                "one_sided_sign_flip_p_value": row["one_sided_sign_flip_p_value"],
                "bh_adjusted_q_value": row["bh_adjusted_q_value_primary_family"],
                "raw_p_below_0_05": _num(row["one_sided_sign_flip_p_value"], 1.0) < 0.05,
                "bh_q_below_0_10": _num(row["bh_adjusted_q_value_primary_family"], 1.0) < 0.10,
                "multiplicity_family": "SEVEN_PRE_REGISTERED_PRIMARY_CONTRACTS",
                "interpretation": "Discovery screen only; neither raw nor adjusted significance promotes a strategy.",
            }
        )
    return pd.DataFrame(rows, columns=MULTIPLE_TESTING_COLUMNS)


def build_comparisons(
    sessions: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for idx, (comparison_id, left_id, right_id, comparison_type) in enumerate(COMPARISONS):
        left_contract = CONTRACT_BY_ID[left_id]
        right_contract = CONTRACT_BY_ID[right_id]
        left_daily = _daily_pnl_for_contract(left_id, sessions, trades).rename(columns={"risk_capped_net_pnl_sek": "left_pnl"})
        right_daily = _daily_pnl_for_contract(right_id, sessions, trades).rename(columns={"risk_capped_net_pnl_sek": "right_pnl"})
        all_dates = sorted(set(left_daily["date"].astype(str)).union(set(right_daily["date"].astype(str))))
        if all_dates:
            dates = pd.DataFrame({"date": pd.Series(all_dates, dtype="object")})
            paired = dates.merge(left_daily, on="date", how="left").merge(right_daily, on="date", how="left").fillna({"left_pnl": 0.0, "right_pnl": 0.0})
        else:
            paired = pd.DataFrame(columns=["date", "left_pnl", "right_pnl"])
        difference = paired["left_pnl"].to_numpy(dtype=float) - paired["right_pnl"].to_numpy(dtype=float)
        ci_low, ci_high, prob = _bootstrap_total(difference, seed=RANDOM_SEED + 300 + idx)
        p_value = _sign_flip_p_value(difference, seed=RANDOM_SEED + 500 + idx)
        left_cov = sessions[(sessions["contract_id"].eq(left_id)) & sessions["eligible_ticker_rows"].gt(0)]
        right_cov = sessions[(sessions["contract_id"].eq(right_id)) & sessions["eligible_ticker_rows"].gt(0)]
        cohort_match_required = comparison_type.startswith("SAME_COHORT")
        left_signatures = left_cov.set_index("date")["cohort_signature"].to_dict()
        right_signatures = right_cov.set_index("date")["cohort_signature"].to_dict()
        all_signature_dates = set(left_signatures).union(right_signatures)
        signature_match = all(left_signatures.get(d, "") == right_signatures.get(d, "") for d in all_signature_dates)
        left_trades = trades[trades["contract_id"].eq(left_id)]
        right_trades = trades[trades["contract_id"].eq(right_id)]
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "comparison_id": comparison_id,
                "comparison_type": comparison_type,
                "left_contract_id": left_id,
                "right_contract_id": right_id,
                "left_cohort_id": left_contract["cohort_id"],
                "right_cohort_id": right_contract["cohort_id"],
                "cohort_match_required": cohort_match_required,
                "cohort_signature_match": signature_match if cohort_match_required else np.nan,
                "comparison_dates": int(len(paired)),
                "left_eligible_sessions": int(left_cov["date"].nunique()),
                "right_eligible_sessions": int(right_cov["date"].nunique()),
                "left_trades": int(len(left_trades)),
                "right_trades": int(len(right_trades)),
                "left_net_pnl_risk_capped_sek": float(left_trades["risk_capped_net_pnl_sek"].sum()) if not left_trades.empty else 0.0,
                "right_net_pnl_risk_capped_sek": float(right_trades["risk_capped_net_pnl_sek"].sum()) if not right_trades.empty else 0.0,
                "net_pnl_difference_sek": float(difference.sum()) if difference.size else 0.0,
                "bootstrap_difference_ci_lower_95_sek": ci_low,
                "bootstrap_difference_ci_upper_95_sek": ci_high,
                "bootstrap_probability_difference_positive": prob,
                "one_sided_sign_flip_p_value_difference": p_value,
                "comparison_status": (
                    "SAME_COHORT_CONFIRMED_DISCOVERY_ONLY" if cohort_match_required and signature_match
                    else "SAME_COHORT_MISMATCH_REVIEW" if cohort_match_required
                    else "STATE_COMPLEMENT_DISCOVERY_ONLY"
                ),
                "selection_status": "DISCOVERY_ONLY_NOT_PROMOTED",
            }
        )
    return pd.DataFrame(rows, columns=COMPARISON_COLUMNS)


def build_robustness(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for contract in CONTRACTS:
        cid = contract["contract_id"]
        group = trades[trades["contract_id"].eq(cid)].copy()
        baseline = float(group["risk_capped_net_pnl_sek"].sum()) if not group.empty else 0.0
        for exclusion_type, column in [("COMPANY", "company_id"), ("BROAD_SECTOR", "broad_sector"), ("DATE", "date")]:
            values = sorted(value for value in group[column].dropna().astype(str).unique() if value)
            for value in values:
                excluded = group[group[column].astype(str).eq(value)]
                remaining = group[~group[column].astype(str).eq(value)]
                remaining_pnl = float(remaining["risk_capped_net_pnl_sek"].sum()) if not remaining.empty else 0.0
                rows.append(
                    {
                        "experiment_id": EXPERIMENT_ID,
                        "contract_id": cid,
                        "test_role": contract["test_role"],
                        "exclusion_type": exclusion_type,
                        "excluded_value": value,
                        "baseline_trades": int(len(group)),
                        "excluded_trades": int(len(excluded)),
                        "remaining_trades": int(len(remaining)),
                        "remaining_sessions": int(remaining["date"].nunique()) if not remaining.empty else 0,
                        "baseline_net_pnl_risk_capped_sek": baseline,
                        "remaining_net_pnl_risk_capped_sek": remaining_pnl,
                        "pnl_change_after_exclusion_sek": remaining_pnl - baseline,
                        "remaining_positive": remaining_pnl > 0,
                        "robustness_status": "REMAINS_POSITIVE" if remaining_pnl > 0 else "NONPOSITIVE_AFTER_EXCLUSION",
                    }
                )
    return pd.DataFrame(rows, columns=ROBUSTNESS_COLUMNS)


def build_audit(
    registry: pd.DataFrame,
    sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    legs: pd.DataFrame,
    comparisons: pd.DataFrame,
) -> pd.DataFrame:
    trade_equal = trades.set_index("trade_id")["equal_net_pnl_sek"] if not trades.empty else pd.Series(dtype=float)
    leg_equal = legs.groupby("trade_id")["equal_net_pnl_sek"].sum() if not legs.empty else pd.Series(dtype=float)
    trade_risk = trades.set_index("trade_id")["risk_capped_net_pnl_sek"] if not trades.empty else pd.Series(dtype=float)
    leg_risk = legs.groupby("trade_id")["risk_capped_net_pnl_sek"].sum() if not legs.empty else pd.Series(dtype=float)
    equal_diff = float((trade_equal - leg_equal.reindex(trade_equal.index).fillna(0.0)).abs().max()) if not trade_equal.empty else 0.0
    risk_diff = float((trade_risk - leg_risk.reindex(trade_risk.index).fillna(0.0)).abs().max()) if not trade_risk.empty else 0.0
    rows = [
        {
            "audit_item": "PRE_REGISTERED_CONTRACT_REGISTRY",
            "rows_checked": len(registry),
            "failures": int((~registry["pre_registered"].map(_bool)).sum()),
            "max_abs_difference": np.nan,
            "interpretation": "Every state-filtered contract and complement is fixed in code before results are generated.",
        },
        {
            "audit_item": "POINT_IN_TIME_CANDIDATES",
            "rows_checked": len(candidates),
            "failures": int((~candidates["point_in_time_pass"].map(_bool)).sum()) if not candidates.empty else 0,
            "max_abs_difference": np.nan,
            "interpretation": "Eligibility and strategy routing use only state available by 09:40.",
        },
        {
            "audit_item": "POINT_IN_TIME_TRADES",
            "rows_checked": len(trades),
            "failures": int((~trades["point_in_time_pass"].map(_bool)).sum()) if not trades.empty else 0,
            "max_abs_difference": np.nan,
            "interpretation": "No generated trade uses future information for contract eligibility.",
        },
        {
            "audit_item": "EXECUTION_INVARIANTS",
            "rows_checked": len(trades),
            "failures": int((~trades["execution_invariant_pass"].map(_bool)).sum()) if not trades.empty else 0,
            "max_abs_difference": np.nan,
            "interpretation": "Entries start at or after 09:45 and exits do not precede entries.",
        },
        {
            "audit_item": "TRADE_LEG_RECONCILIATION_EQUAL_NOTIONAL",
            "rows_checked": len(trades),
            "failures": int(equal_diff > 1e-9),
            "max_abs_difference": equal_diff,
            "interpretation": "Trade P&L equals leg P&L under equal-notional sizing.",
        },
        {
            "audit_item": "TRADE_LEG_RECONCILIATION_RISK_CAPPED",
            "rows_checked": len(trades),
            "failures": int(risk_diff > 1e-9),
            "max_abs_difference": risk_diff,
            "interpretation": "Trade P&L equals leg P&L under fixed-risk-capped sizing.",
        },
        {
            "audit_item": "SAME_COHORT_COMPARISONS",
            "rows_checked": int(comparisons["cohort_match_required"].map(_bool).sum()),
            "failures": int(((comparisons["cohort_match_required"].map(_bool)) & (~comparisons["cohort_signature_match"].map(_bool))).sum()),
            "max_abs_difference": np.nan,
            "interpretation": "Competing strategy contracts marked same-cohort receive identical pre-entry eligible ticker-session cohorts.",
        },
        {
            "audit_item": "NO_AUTOMATIC_PROMOTION",
            "rows_checked": len(registry),
            "failures": int(registry["promotion_eligible"].map(_bool).sum() + registry["router_active"].map(_bool).sum()),
            "max_abs_difference": np.nan,
            "interpretation": "No discovery result can activate the router or promote a strategy in Step 9G.",
        },
    ]
    result = pd.DataFrame(rows)
    result.insert(0, "experiment_id", EXPERIMENT_ID)
    result["audit_pass"] = result["failures"].eq(0)
    return result.reindex(columns=AUDIT_COLUMNS)


def build_summary(
    taxonomy: pd.DataFrame,
    registry: pd.DataFrame,
    sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    legs: pd.DataFrame,
    performance: pd.DataFrame,
    comparisons: pd.DataFrame,
    multiple_testing: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    equal_audit = audit[audit["audit_item"].eq("TRADE_LEG_RECONCILIATION_EQUAL_NOTIONAL")]
    risk_audit = audit[audit["audit_item"].eq("TRADE_LEG_RECONCILIATION_RISK_CAPPED")]
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")]
    all_pass = bool(audit["audit_pass"].all())
    classification = (
        "STATE_FILTERED_CONTRACT_EXPERIMENT_READY_FOR_CONTROLLED_REVIEW"
        if all_pass
        else "STATE_FILTERED_CONTRACT_EXPERIMENT_AUDIT_REVIEW_REQUIRED"
    )
    row = {
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "router_cutoff": LATEST_ROUTER_BAR_LABEL,
        "execution_start": EXECUTION_START,
        "taxonomy_sessions": int(taxonomy["date"].nunique()),
        "contracts_registered": int(len(registry)),
        "primary_hypotheses": int(registry["test_role"].eq("PRIMARY_HYPOTHESIS").sum()),
        "complement_controls": int(registry["test_role"].eq("COMPLEMENT_CONTROL").sum()),
        "same_cohort_comparisons": int(comparisons["cohort_match_required"].map(_bool).sum()),
        "session_contract_rows": int(len(sessions)),
        "regime_match_session_rows": int(sessions["regime_match"].map(_bool).sum()),
        "eligible_ticker_rows": int(sessions["eligible_ticker_rows"].sum()),
        "valid_setup_rows": int((candidates["setup_status"] == "VALID_SETUP").sum()) if not candidates.empty else 0,
        "selected_ideas": int(candidates["selected_for_simulation"].map(_bool).sum()) if not candidates.empty else 0,
        "triggered_closed_trades": int(len(trades)),
        "screenable_contracts": int(performance["sample_status"].eq("SCREENABLE_PRE_REGISTERED_DISCOVERY").sum()),
        "positive_net_primary_contracts": int(primary["net_pnl_risk_capped_sek"].gt(0).sum()),
        "primary_contracts_with_positive_bootstrap_lower_bound": int(primary["bootstrap_total_pnl_ci_lower_95_sek"].gt(0).sum()),
        "primary_contracts_raw_p_below_0_05": int(multiple_testing["raw_p_below_0_05"].map(_bool).sum()),
        "primary_contracts_bh_q_below_0_10": int(multiple_testing["bh_q_below_0_10"].map(_bool).sum()),
        "point_in_time_pass_contracts": int(
            sessions.groupby("contract_id")["point_in_time_pass"].all().reindex(registry["contract_id"], fill_value=True).sum()
        ),
        "execution_invariant_failures": int((~trades["execution_invariant_pass"].map(_bool)).sum()) if not trades.empty else 0,
        "trade_leg_reconciliation_max_abs_diff_equal_notional_sek": float(equal_audit.iloc[0]["max_abs_difference"]) if not equal_audit.empty else 0.0,
        "trade_leg_reconciliation_max_abs_diff_risk_capped_sek": float(risk_audit.iloc[0]["max_abs_difference"]) if not risk_audit.empty else 0.0,
        "strategies_promoted": 0,
        "router_active": False,
        "classification": classification,
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def build_state_filtered_experiment(
    taxonomy: pd.DataFrame,
    prices: pd.DataFrame,
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
):
    taxonomy = taxonomy.copy()
    taxonomy["date"] = taxonomy["date"].astype(str)
    daily_reference = build_daily_reference(prices)
    raw_states, bars_lookup = build_market_state(prices, daily_reference, set(taxonomy["date"]))
    states = enrich_market_states(raw_states, static, characteristics, group_states)

    registry_rows = []
    for contract in CONTRACTS:
        challenger = CHALLENGER_BY_ID[contract["base_challenger_id"]]
        registry_rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                **contract,
                "strategy_family": challenger["strategy_family"],
                "pre_registered": True,
                "router_active": False,
                "promotion_eligible": False,
            }
        )
    registry = pd.DataFrame(registry_rows, columns=REGISTRY_COLUMNS)

    candidate_rows: list[dict] = []
    trade_rows: list[dict] = []
    leg_rows: list[dict] = []
    session_rows: list[dict] = []

    static_lookup = static.set_index("ticker")[["company_id", "broad_sector"]].to_dict("index")

    for session in taxonomy.sort_values("date").to_dict("records"):
        date = str(session["date"])
        observed_regime = str(session["primary_regime"])
        day_states = states[states["date"].eq(date)].copy()
        for contract in CONTRACTS:
            cid = contract["contract_id"]
            regime_match = observed_regime == contract["primary_regime"]
            contract_states = day_states.copy()
            if not contract_states.empty:
                contract_states["intended_side"] = [
                    _intended_side(contract["base_challenger_id"], row)
                    for row in contract_states.to_dict("records")
                ]
                contract_states["contract_sector_alignment"] = [
                    _direction_alignment(side, direction)
                    for side, direction in zip(contract_states["intended_side"], contract_states["sector_direction_state"])
                ]
            if not regime_match:
                eligible = contract_states.iloc[0:0].copy()
            else:
                eligible = contract_states[_contract_mask(contract_states, contract)].copy() if not contract_states.empty else contract_states.copy()

            local_candidates: list[dict] = []
            local_trades: list[dict] = []
            local_legs: list[dict] = []
            if regime_match and not eligible.empty:
                challenger = CHALLENGER_BY_ID[contract["base_challenger_id"]]
                local_candidates = _single_candidates_for_challenger(
                    session=session,
                    challenger=challenger,
                    states=eligible,
                    bars_lookup=bars_lookup,
                    trades=local_trades,
                    legs=local_legs,
                )

            eligible_lookup = eligible.set_index("ticker").to_dict("index") if not eligible.empty else {}
            trade_id_map: dict[str, str] = {}
            for source in local_candidates:
                ticker = str(source.get("ticker", ""))
                context = eligible_lookup.get(ticker, {})
                original_idea = str(source.get("idea_id", ""))
                idea_id = f"{cid}|{original_idea}"
                candidate_rows.append(
                    {
                        "experiment_id": EXPERIMENT_ID,
                        "contract_id": cid,
                        "test_role": contract["test_role"],
                        "cohort_id": contract["cohort_id"],
                        "comparison_group": contract["comparison_group"],
                        "date": date,
                        "primary_regime": observed_regime,
                        "base_challenger_id": contract["base_challenger_id"],
                        "idea_id": idea_id,
                        "ticker": ticker,
                        "company_id": context.get("company_id", static_lookup.get(ticker, {}).get("company_id", "")),
                        "broad_sector": context.get("broad_sector", static_lookup.get(ticker, {}).get("broad_sector", "")),
                        "direction": source.get("direction", ""),
                        "ticker_relative_state": context.get("ticker_relative_state", ""),
                        "volatility_bucket": context.get("volatility_bucket", ""),
                        "range_state": context.get("range_state", ""),
                        "sector_direction_state": context.get("sector_direction_state", ""),
                        "sector_direction_alignment": context.get("contract_sector_alignment", ""),
                        "contract_eligible": True,
                        "selection_rank": source.get("selection_rank", np.nan),
                        "selected_for_simulation": source.get("selected_for_simulation", False),
                        "setup_status": source.get("setup_status", ""),
                        "trigger_status": source.get("trigger_status", ""),
                        "invalid_reason": source.get("invalid_reason", ""),
                        "ranking_metric": source.get("ranking_metric", np.nan),
                        "signal_time": source.get("signal_time", ""),
                        "entry_time": source.get("entry_time", ""),
                        "entry_price": source.get("entry_price", np.nan),
                        "stop_price": source.get("stop_price", np.nan),
                        "target_price": source.get("target_price", np.nan),
                        "exit_time": source.get("exit_time", ""),
                        "exit_reason": source.get("exit_reason", ""),
                        "max_router_source_label": source.get("max_router_source_label", ""),
                        "point_in_time_pass": _bool(source.get("point_in_time_pass")) and _bool(context.get("taxonomy_point_in_time_pass", False)),
                        "mechanical_interpretation": source.get("mechanical_interpretation", ""),
                    }
                )
            for source in local_trades:
                ticker = str(source.get("ticker", ""))
                context = eligible_lookup.get(ticker, {})
                original_trade_id = str(source["trade_id"])
                trade_id = f"{cid}|{original_trade_id}"
                trade_id_map[original_trade_id] = trade_id
                trade_rows.append(
                    {
                        "experiment_id": EXPERIMENT_ID,
                        "contract_id": cid,
                        "test_role": contract["test_role"],
                        "cohort_id": contract["cohort_id"],
                        "comparison_group": contract["comparison_group"],
                        "trade_id": trade_id,
                        "date": date,
                        "primary_regime": observed_regime,
                        "base_challenger_id": contract["base_challenger_id"],
                        "strategy_family": CHALLENGER_BY_ID[contract["base_challenger_id"]]["strategy_family"],
                        "direction": source.get("direction", ""),
                        "ticker": ticker,
                        "company_id": context.get("company_id", static_lookup.get(ticker, {}).get("company_id", "")),
                        "broad_sector": context.get("broad_sector", static_lookup.get(ticker, {}).get("broad_sector", "")),
                        "ticker_relative_state": context.get("ticker_relative_state", ""),
                        "volatility_bucket": context.get("volatility_bucket", ""),
                        "range_state": context.get("range_state", ""),
                        "sector_direction_state": context.get("sector_direction_state", ""),
                        "sector_direction_alignment": context.get("contract_sector_alignment", ""),
                        "regime_confidence": source.get("regime_confidence", np.nan),
                        "confidence_band": source.get("confidence_band", ""),
                        "entry_time": source.get("entry_time", ""),
                        "entry_price": source.get("entry_price", np.nan),
                        "stop_price": source.get("stop_price", np.nan),
                        "target_price": source.get("target_price", np.nan),
                        "exit_time": source.get("exit_time", ""),
                        "exit_price": source.get("exit_price", np.nan),
                        "exit_reason": source.get("exit_reason", ""),
                        "gross_return": source.get("gross_return", np.nan),
                        "risk_pct_at_entry": source.get("risk_pct_at_entry", np.nan),
                        "r_multiple_achieved": source.get("r_multiple_achieved", np.nan),
                        "trade_duration_minutes": source.get("trade_duration_minutes", np.nan),
                        "research_risk_multiplier": source.get("research_risk_multiplier", np.nan),
                        "equal_notional_sek": source.get("equal_notional_sek", np.nan),
                        "equal_gross_pnl_sek": source.get("equal_gross_pnl_sek", np.nan),
                        "equal_cost_sek": source.get("equal_cost_sek", np.nan),
                        "equal_net_pnl_sek": source.get("equal_net_pnl_sek", np.nan),
                        "risk_capped_notional_sek": source.get("risk_capped_notional_sek", np.nan),
                        "risk_capped_gross_pnl_sek": source.get("risk_capped_gross_pnl_sek", np.nan),
                        "risk_capped_cost_sek": source.get("risk_capped_cost_sek", np.nan),
                        "risk_capped_net_pnl_sek": source.get("risk_capped_net_pnl_sek", np.nan),
                        "point_in_time_pass": _bool(source.get("point_in_time_pass")) and _bool(context.get("taxonomy_point_in_time_pass", False)),
                        "execution_invariant_pass": _bool(source.get("execution_invariant_pass")),
                    }
                )
            for source in local_legs:
                ticker = str(source.get("ticker", ""))
                original_trade_id = str(source["trade_id"])
                trade_id = trade_id_map.get(original_trade_id, f"{cid}|{original_trade_id}")
                meta = static_lookup.get(ticker, {})
                leg_rows.append(
                    {
                        "experiment_id": EXPERIMENT_ID,
                        "contract_id": cid,
                        "trade_id": trade_id,
                        "leg_id": f"{cid}|{source.get('leg_id', '')}",
                        "date": date,
                        "primary_regime": observed_regime,
                        "base_challenger_id": contract["base_challenger_id"],
                        "ticker": ticker,
                        "company_id": meta.get("company_id", ""),
                        "broad_sector": meta.get("broad_sector", ""),
                        "side": source.get("side", ""),
                        "entry_time": source.get("entry_time", ""),
                        "entry_price": source.get("entry_price", np.nan),
                        "exit_time": source.get("exit_time", ""),
                        "exit_price": source.get("exit_price", np.nan),
                        "exit_reason": source.get("exit_reason", ""),
                        "equal_notional_sek": source.get("equal_notional_sek", np.nan),
                        "equal_gross_pnl_sek": source.get("equal_gross_pnl_sek", np.nan),
                        "equal_cost_sek": source.get("equal_cost_sek", np.nan),
                        "equal_net_pnl_sek": source.get("equal_net_pnl_sek", np.nan),
                        "risk_capped_notional_sek": source.get("risk_capped_notional_sek", np.nan),
                        "risk_capped_gross_pnl_sek": source.get("risk_capped_gross_pnl_sek", np.nan),
                        "risk_capped_cost_sek": source.get("risk_capped_cost_sek", np.nan),
                        "risk_capped_net_pnl_sek": source.get("risk_capped_net_pnl_sek", np.nan),
                    }
                )

            session_trade_rows = [row for row in trade_rows if row["date"] == date and row["contract_id"] == cid]
            session_candidate_rows = [row for row in candidate_rows if row["date"] == date and row["contract_id"] == cid]
            eligible_tickers = sorted(eligible["ticker"].astype(str).unique()) if not eligible.empty else []
            eligible_companies = int(eligible["company_id"].nunique()) if not eligible.empty else 0
            pit_pass = bool(eligible["taxonomy_point_in_time_pass"].map(_bool).all()) if not eligible.empty else True
            coverage_status = (
                "REGIME_NOT_APPLICABLE" if not regime_match
                else "NO_STATE_ELIGIBLE_TICKERS" if eligible.empty
                else "ELIGIBLE_NO_VALID_SETUP" if not any(row["setup_status"] == "VALID_SETUP" for row in session_candidate_rows)
                else "VALID_SETUP_NOT_TRIGGERED" if not session_trade_rows
                else "TRIGGERED_CLOSED"
            )
            session_rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "date": date,
                    "contract_id": cid,
                    "test_role": contract["test_role"],
                    "primary_regime_required": contract["primary_regime"],
                    "observed_primary_regime": observed_regime,
                    "regime_match": regime_match,
                    "cohort_id": contract["cohort_id"],
                    "eligible_ticker_rows": int(len(eligible)),
                    "eligible_independent_companies": eligible_companies,
                    "eligible_tickers": ";".join(eligible_tickers),
                    "valid_setup_rows": int(sum(row["setup_status"] == "VALID_SETUP" for row in session_candidate_rows)),
                    "selected_ideas": int(sum(_bool(row["selected_for_simulation"]) for row in session_candidate_rows)),
                    "triggered_trades": int(len(session_trade_rows)),
                    "equal_net_pnl_sek": float(sum(_num(row["equal_net_pnl_sek"], 0.0) for row in session_trade_rows)),
                    "risk_capped_net_pnl_sek": float(sum(_num(row["risk_capped_net_pnl_sek"], 0.0) for row in session_trade_rows)),
                    "cohort_signature": _cohort_signature(eligible),
                    "point_in_time_pass": pit_pass,
                    "coverage_status": coverage_status,
                }
            )

    sessions_df = pd.DataFrame(session_rows, columns=SESSION_COLUMNS)
    candidates_df = pd.DataFrame(candidate_rows, columns=CANDIDATE_COLUMNS)
    trades_df = pd.DataFrame(trade_rows, columns=TRADE_COLUMNS)
    legs_df = pd.DataFrame(leg_rows, columns=LEG_COLUMNS)
    performance = build_performance(registry, sessions_df, candidates_df, trades_df)
    comparisons = build_comparisons(sessions_df, trades_df)
    robustness = build_robustness(trades_df)
    multiple_testing = build_multiple_testing(performance)
    audit = build_audit(registry, sessions_df, candidates_df, trades_df, legs_df, comparisons)
    summary = build_summary(
        taxonomy, registry, sessions_df, candidates_df, trades_df, legs_df,
        performance, comparisons, multiple_testing, audit,
    )
    return (
        summary, registry, sessions_df, candidates_df, trades_df, legs_df,
        performance, comparisons, robustness, multiple_testing, audit,
    )


def run_state_filtered_experiment(
    taxonomy_file: Path = TAXONOMY_FILE,
    db_path: Path = INTRADAY_DB,
    static_file: Path = STATIC_FILE,
    characteristic_file: Path = CHARACTERISTIC_FILE,
    group_state_file: Path = GROUP_STATE_FILE,
):
    required = [taxonomy_file, static_file, characteristic_file, group_state_file]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required Step 8/9E outputs: " + ", ".join(str(path) for path in missing))
    taxonomy = pd.read_csv(taxonomy_file)
    prices = load_intraday_prices(db_path)
    static = pd.read_csv(static_file)
    characteristics = pd.read_csv(characteristic_file)
    group_states = pd.read_csv(group_state_file)
    return build_state_filtered_experiment(taxonomy, prices, static, characteristics, group_states)


def main() -> None:
    print("\n=== STEP 9G PRE-REGISTERED STATE-FILTERED CONTRACT EXPERIMENTS ===")
    print(f"Experiment       : {EXPERIMENT_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Router cutoff    : {LATEST_ROUTER_BAR_LABEL}")
    print(f"Execution starts : {EXECUTION_START}")
    print("Seven primary hypotheses and seven complement controls are fixed before results are generated.")
    print("Strategies are rerun from raw five-minute bars on filtered pre-entry cohorts; existing winning trades are not merely subsetted.")
    print("Date-level bootstrap intervals, paired cohort comparisons, robustness exclusions, and BH correction are diagnostic only.")
    print("No contract is optimized, promoted, or made router-active in this step.")

    outputs = run_state_filtered_experiment()
    paths = [
        SUMMARY_FILE, REGISTRY_FILE, SESSION_FILE, CANDIDATE_FILE, TRADE_FILE, LEG_FILE,
        PERFORMANCE_FILE, COMPARISON_FILE, ROBUSTNESS_FILE, MULTIPLE_TESTING_FILE, AUDIT_FILE,
    ]
    for dataframe, path in zip(outputs, paths):
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")

    result = outputs[0].iloc[0]
    print("\n=== STEP 9G STATE-FILTERED EXPERIMENT RESULT ===")
    print(f"Taxonomy sessions             : {int(result['taxonomy_sessions'])}")
    print(f"Registered primary/control    : {int(result['contracts_registered'])} ({int(result['primary_hypotheses'])}/{int(result['complement_controls'])})")
    print(f"Same-cohort comparisons       : {int(result['same_cohort_comparisons'])}")
    print(f"Regime-match session rows     : {int(result['regime_match_session_rows'])}/{int(result['session_contract_rows'])}")
    print(f"Eligible ticker rows          : {int(result['eligible_ticker_rows'])}")
    print(f"Valid/selected/trades         : {int(result['valid_setup_rows'])}/{int(result['selected_ideas'])}/{int(result['triggered_closed_trades'])}")
    print(f"Screenable contracts          : {int(result['screenable_contracts'])}/{int(result['contracts_registered'])}")
    print(f"Positive primary contracts    : {int(result['positive_net_primary_contracts'])}/{int(result['primary_hypotheses'])}")
    print(f"Positive bootstrap lower bound: {int(result['primary_contracts_with_positive_bootstrap_lower_bound'])}")
    print(f"Raw p<0.05 / BH q<0.10        : {int(result['primary_contracts_raw_p_below_0_05'])}/{int(result['primary_contracts_bh_q_below_0_10'])}")
    print(f"PIT pass contracts            : {int(result['point_in_time_pass_contracts'])}/{int(result['contracts_registered'])}")
    print(f"Execution invariant failures  : {int(result['execution_invariant_failures'])}")
    print(f"Equal/risk reconciliation max : {float(result['trade_leg_reconciliation_max_abs_diff_equal_notional_sek']):.12f} / {float(result['trade_leg_reconciliation_max_abs_diff_risk_capped_sek']):.12f} SEK")
    print(f"Strategies promoted           : {int(result['strategies_promoted'])}")
    print(f"Router active                 : {bool(result['router_active'])}")
    print(f"Classification                : {result['classification']}")
    print("Step 9G export complete. Results remain pre-registered discovery evidence only.")


if __name__ == "__main__":
    main()
