from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, legacy_output_path


TAXONOMY_ID = "PROVISIONAL_EXHAUSTIVE_REGIME_TAXONOMY_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_REGIME_SYSTEM_RESEARCH"
DECISION_TIME = "09:45"
LATEST_ALLOWED_BAR_LABEL = "09:40"
BAR_TIMESTAMP_CONVENTION = "START_LABELLED_5_MINUTE_BARS"
PRIOR_PERCENTILE_WINDOW = 20
PRIOR_PERCENTILE_MIN_HISTORY = 5

FEATURE_FILE = legacy_output_path("regime_daily_features.csv")
TIMING_SUMMARY_FILE = legacy_output_path("regime_v1_timing_comparison_summary.csv")
TIMING_DAILY_FILE = legacy_output_path("regime_v1_timing_comparison_daily.csv")

SUMMARY_FILE = legacy_output_path("regime_taxonomy_summary.csv")
DAILY_FILE = DATA_DIR / "regime_daily_taxonomy.csv"
DEFINITIONS_FILE = legacy_output_path("regime_taxonomy_definitions.csv")
DISTRIBUTION_FILE = legacy_output_path("regime_taxonomy_distribution.csv")
TRANSITIONS_FILE = legacy_output_path("regime_taxonomy_transitions.csv")

REGIMES = (
    "RECOVERY",
    "TREND_UP",
    "TREND_DOWN",
    "RANGE_LOW_VOL",
    "HIGH_VOL_REVERSAL",
    "HIGH_DISPERSION",
    "VOLATILITY_EXPANSION",
    "DEFENSIVE_MIXED",
    "DATA_LIMITED_DEFENSIVE",
)

SCORE_REGIMES = REGIMES[:-1]

SUMMARY_COLUMNS = [
    "taxonomy_id",
    "research_status",
    "decision_time",
    "latest_allowed_bar_label",
    "bar_timestamp_convention",
    "observed_sessions",
    "taxonomy_eligible_sessions",
    "data_limited_sessions",
    "sessions_with_active_response",
    "sessions_without_active_response",
    "no_trade_sessions",
    "regime_definition_count",
    "regimes_observed",
    "regimes_with_active_response",
    "median_regime_confidence",
    "low_confidence_sessions",
    "high_confidence_sessions",
    "point_in_time_safe_sessions",
    "strict_v1_version_required",
    "legacy_v1_router_eligible",
    "strict_minus_legacy_pnl_sek",
    "first_session_date",
    "last_session_date",
    "classification",
]

DAILY_COLUMNS = [
    "taxonomy_id",
    "research_status",
    "date",
    "decision_time",
    "latest_allowed_bar_label",
    "point_in_time_safe",
    "minimum_regime_feature_ready",
    "full_regime_feature_ready",
    "feature_row_status",
    "taxonomy_eligible",
    "data_quality_override",
    "prior_percentile_history_count",
    "early_volatility_prior_percentile",
    "opening_range_prior_percentile",
    "return_dispersion_prior_percentile",
    "gap_dispersion_prior_percentile",
    "direction_bias",
    "volatility_state",
    "dispersion_state",
    "gap_state",
    "recovery_score",
    "trend_up_score",
    "trend_down_score",
    "range_low_vol_score",
    "high_vol_reversal_score",
    "high_dispersion_score",
    "volatility_expansion_score",
    "defensive_mixed_score",
    "primary_regime",
    "secondary_regime",
    "primary_score",
    "secondary_score",
    "score_margin",
    "regime_confidence",
    "confidence_band",
    "classification_reason",
    "candidate_playbook",
    "candidate_basket_method",
    "portfolio_structure",
    "research_risk_multiplier",
    "research_max_concurrent_ideas",
    "response_status",
    "strict_v1_router_status",
    "strict_v1_regime_diagnostic",
    "strict_v1_favorable_diagnostic",
    "strict_v1_triggered_trades_diagnostic",
    "strict_v1_trade_pnl_sek_unconstrained_diagnostic",
    "diagnostics_used_for_classification",
]

DEFINITION_COLUMNS = [
    "taxonomy_id",
    "regime",
    "market_interpretation",
    "dominant_point_in_time_evidence",
    "candidate_playbook",
    "candidate_basket_method",
    "portfolio_structure",
    "research_risk_multiplier",
    "research_max_concurrent_ideas",
    "active_response_required",
    "validation_status",
    "strict_v1_requirement",
]

DISTRIBUTION_COLUMNS = [
    "taxonomy_id",
    "primary_regime",
    "session_count",
    "session_share",
    "average_confidence",
    "median_confidence",
    "high_confidence_sessions",
    "low_confidence_sessions",
    "up_bias_sessions",
    "down_bias_sessions",
    "neutral_bias_sessions",
    "strict_v1_triggered_trades_diagnostic",
    "strict_v1_trade_pnl_sek_unconstrained_diagnostic",
    "candidate_playbook",
    "research_risk_multiplier",
]

TRANSITION_COLUMNS = [
    "taxonomy_id",
    "from_regime",
    "to_regime",
    "transition_count",
    "from_regime_transition_count",
    "transition_probability",
    "average_to_regime_confidence",
]


@dataclass(frozen=True)
class ResponseDefinition:
    market_interpretation: str
    evidence: str
    playbook: str
    basket: str
    structure: str
    risk_multiplier: float
    max_ideas: int
    strict_v1_requirement: str


RESPONSE_DEFINITIONS: dict[str, ResponseDefinition] = {
    "RECOVERY": ResponseDefinition(
        "Broad negative opening pressure is being reclaimed by 09:45.",
        "Negative median gap and broad gap-down participation combined with improving early breadth, returns, or acceleration.",
        "STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH",
        "LIQUID_NEGATIVE_GAP_RECLAIM_CANDIDATES",
        "LONG_ONLY_RECOVERY_BASKET",
        1.00,
        2,
        "Required. Frozen legacy V1 timing is not router eligible.",
    ),
    "TREND_UP": ResponseDefinition(
        "The cross-section is moving broadly and persistently upward at normal-to-moderate volatility.",
        "Positive median return from open, broad participation above open, and non-negative early acceleration.",
        "TREND_UP_MOMENTUM_BREAKOUT_V1_RESEARCH",
        "TOP_RELATIVE_STRENGTH_LIQUID_LONGS",
        "LONG_ONLY_DIRECTIONAL_BASKET",
        1.00,
        2,
        "Not applicable.",
    ),
    "TREND_DOWN": ResponseDefinition(
        "The cross-section is moving broadly and persistently downward at normal-to-moderate volatility.",
        "Negative median return from open, broad participation below open, and non-positive early acceleration.",
        "TREND_DOWN_MOMENTUM_CONTINUATION_V1_RESEARCH",
        "BOTTOM_RELATIVE_STRENGTH_LIQUID_SHORTS",
        "SHORT_ONLY_DIRECTIONAL_BASKET",
        1.00,
        2,
        "Not applicable.",
    ),
    "RANGE_LOW_VOL": ResponseDefinition(
        "The market is balanced, directionless, and quiet relative to prior sessions.",
        "Neutral median return, balanced breadth, low opening range, low realized volatility, and low dispersion.",
        "RANGE_VWAP_REVERSION_V1_RESEARCH",
        "EXTREME_DEVIATION_FROM_VWAP_BASKET",
        "TWO_SIDED_MEAN_REVERSION",
        0.75,
        2,
        "Not applicable.",
    ),
    "HIGH_VOL_REVERSAL": ResponseDefinition(
        "A large early move is failing, changing sign, or retracing sharply by 09:45.",
        "High volatility/range together with a sign flip or strong retracement between the 09:35 and 09:40 observations.",
        "FAILED_BREAKOUT_REVERSAL_V1_RESEARCH",
        "FAILED_EARLY_EXTREME_REVERSAL_CANDIDATES",
        "DIRECTIONAL_REVERSAL_WITH_REDUCED_RISK",
        0.50,
        2,
        "Not applicable.",
    ),
    "HIGH_DISPERSION": ResponseDefinition(
        "Stocks are behaving very differently, reducing the value of a single market-direction bet.",
        "High cross-sectional return or gap dispersion with mixed directional breadth.",
        "CROSS_SECTIONAL_RELATIVE_VALUE_V1_RESEARCH",
        "LONG_STRONGEST_SHORT_WEAKEST_SECTOR_BALANCED",
        "MARKET_NEUTRAL_LONG_SHORT",
        0.75,
        2,
        "Not applicable.",
    ),
    "VOLATILITY_EXPANSION": ResponseDefinition(
        "The market is making a broad high-range directional expansion.",
        "High early realized volatility and opening range combined with strong directional return and breadth.",
        "CONFIRMED_VOLATILITY_BREAKOUT_V1_RESEARCH",
        "HIGH_RANGE_DIRECTIONALLY_CONFIRMED_LIQUID_BASKET",
        "DIRECTIONAL_OR_TWO_SIDED_BREAKOUT",
        0.65,
        2,
        "Not applicable.",
    ),
    "DEFENSIVE_MIXED": ResponseDefinition(
        "The market state is tradable but lacks a dominant directional or volatility signature.",
        "No specialist regime score dominates; evidence is conflicting or moderate across several dimensions.",
        "DEFENSIVE_MARKET_NEUTRAL_PAIRS_V1_RESEARCH",
        "SECTOR_BALANCED_LIQUID_RELATIVE_VALUE_PAIRS",
        "LOW_GROSS_MARKET_NEUTRAL",
        0.40,
        2,
        "Not applicable.",
    ),
    "DATA_LIMITED_DEFENSIVE": ResponseDefinition(
        "Required point-in-time inputs are incomplete, so the router uses the lowest-risk active research response.",
        "Minimum feature readiness or point-in-time safety gate is not satisfied.",
        "DATA_LIMITED_LIQUID_MARKET_NEUTRAL_V1_RESEARCH",
        "MOST_LIQUID_LOW_BETA_SECTOR_BALANCED_PAIRS",
        "MINIMUM_GROSS_MARKET_NEUTRAL",
        0.25,
        1,
        "Not applicable.",
    ),
}


def _num(value: object, default: float = np.nan) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else default


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if pd.isna(value):
        return False
    return bool(value)


def _clip01(value: float) -> float:
    if pd.isna(value):
        return 0.0
    return float(np.clip(value, 0.0, 1.0))


def _positive_scale(value: float, start: float, full: float) -> float:
    if pd.isna(value) or full <= start:
        return 0.0
    return _clip01((value - start) / (full - start))


def _negative_scale(value: float, start: float, full: float) -> float:
    if pd.isna(value):
        return 0.0
    return _positive_scale(-value, start, full)


def _neutral_score(value: float, full_neutral: float, zero_at: float) -> float:
    if pd.isna(value) or zero_at <= full_neutral:
        return 0.0
    absolute = abs(value)
    if absolute <= full_neutral:
        return 1.0
    return _clip01(1.0 - (absolute - full_neutral) / (zero_at - full_neutral))


def _balanced_breadth_score(value: float) -> float:
    if pd.isna(value):
        return 0.0
    return _clip01(1.0 - abs(value - 0.5) / 0.35)


def _prior_percentiles(
    frame: pd.DataFrame,
    column: str,
    window: int = PRIOR_PERCENTILE_WINDOW,
    min_history: int = PRIOR_PERCENTILE_MIN_HISTORY,
) -> tuple[pd.Series, pd.Series]:
    values = pd.to_numeric(frame[column], errors="coerce")
    percentiles: list[float] = []
    history_counts: list[int] = []
    for index, current in enumerate(values):
        history = values.iloc[max(0, index - window):index].dropna()
        history_counts.append(int(len(history)))
        if pd.isna(current) or len(history) < min_history:
            percentiles.append(0.5)
            continue
        below = float((history < current).sum())
        equal = float((history == current).sum())
        percentiles.append((below + 0.5 * equal) / len(history))
    return pd.Series(percentiles, index=frame.index), pd.Series(history_counts, index=frame.index)


def _direction_bias(median_return: float, breadth: float) -> str:
    if median_return >= 0.0005 and breadth >= 0.55:
        return "UP"
    if median_return <= -0.0005 and breadth <= 0.45:
        return "DOWN"
    return "NEUTRAL"


def _state_from_percentile(value: float) -> str:
    if value >= 0.75:
        return "HIGH"
    if value <= 0.25:
        return "LOW"
    return "NORMAL"


def _gap_state(median_gap: float, gap_up: float, gap_down: float, gap_dispersion_pct: float) -> str:
    if median_gap <= -0.003 and gap_down >= 0.55:
        return "BROAD_GAP_DOWN"
    if median_gap >= 0.003 and gap_up >= 0.55:
        return "BROAD_GAP_UP"
    if gap_dispersion_pct >= 0.75:
        return "MIXED_HIGH_DISPERSION_GAPS"
    return "MUTED_OR_MIXED_GAPS"


def _reversal_component(return_0935: float, return_0940: float) -> float:
    if pd.isna(return_0935) or pd.isna(return_0940):
        return 0.0
    initial_magnitude = abs(return_0935)
    if initial_magnitude < 0.0005:
        return 0.0
    sign_flip = np.sign(return_0935) != np.sign(return_0940) and return_0940 != 0
    if sign_flip:
        return 1.0
    if np.sign(return_0935) == np.sign(return_0940):
        retracement = 1.0 - abs(return_0940) / max(initial_magnitude, 1e-12)
        return _clip01(retracement / 0.70)
    return 0.0


def _classify_row(row: pd.Series) -> dict[str, object]:
    eligible = _bool(row.get("minimum_regime_feature_ready")) and _bool(row.get("point_in_time_safe"))
    if not eligible:
        response = RESPONSE_DEFINITIONS["DATA_LIMITED_DEFENSIVE"]
        return {
            "taxonomy_eligible": False,
            "data_quality_override": True,
            "direction_bias": "NEUTRAL",
            "volatility_state": "UNKNOWN",
            "dispersion_state": "UNKNOWN",
            "gap_state": "UNKNOWN",
            **{f"{regime.lower()}_score": 0.0 for regime in SCORE_REGIMES},
            "primary_regime": "DATA_LIMITED_DEFENSIVE",
            "secondary_regime": "DEFENSIVE_MIXED",
            "primary_score": 1.0,
            "secondary_score": 0.0,
            "score_margin": 1.0,
            "regime_confidence": 0.25,
            "confidence_band": "LOW",
            "classification_reason": "Minimum point-in-time feature readiness was not met; active defensive fallback assigned.",
            "candidate_playbook": response.playbook,
            "candidate_basket_method": response.basket,
            "portfolio_structure": response.structure,
            "research_risk_multiplier": response.risk_multiplier,
            "research_max_concurrent_ideas": response.max_ideas,
            "response_status": "ACTIVE_SIMULATION_RESPONSE_ASSIGNED",
        }

    breadth = _num(row.get("breadth_above_open_at_cutoff"), 0.5)
    median_return = _num(row.get("median_return_from_open"), 0.0)
    acceleration = _num(row.get("median_return_acceleration_0935_to_0940"), 0.0)
    median_gap = _num(row.get("median_gap"), 0.0)
    gap_up = _num(row.get("gap_up_breadth"), 0.0)
    gap_down = _num(row.get("gap_down_breadth"), 0.0)
    return_0935 = _num(row.get("median_return_from_open_at_0935"), 0.0)
    return_0940 = _num(row.get("median_return_from_open_at_0940"), 0.0)
    prior_5_return = _num(row.get("prior_5_session_market_return"), 0.0)

    p_vol = _num(row.get("early_volatility_prior_percentile"), 0.5)
    p_range = _num(row.get("opening_range_prior_percentile"), 0.5)
    p_disp = _num(row.get("return_dispersion_prior_percentile"), 0.5)
    p_gap_disp = _num(row.get("gap_dispersion_prior_percentile"), 0.5)

    up_breadth = _positive_scale(breadth, 0.50, 0.82)
    down_breadth = _positive_scale(1.0 - breadth, 0.50, 0.82)
    up_return = _positive_scale(median_return, 0.0002, 0.0035)
    down_return = _negative_scale(median_return, 0.0002, 0.0035)
    positive_acceleration = _positive_scale(acceleration, 0.0, 0.0020)
    negative_acceleration = _negative_scale(acceleration, 0.0, 0.0020)
    prior_up = _positive_scale(prior_5_return, 0.0, 0.03)
    prior_down = _negative_scale(prior_5_return, 0.0, 0.03)

    negative_gap = _negative_scale(median_gap, 0.001, 0.015)
    gap_down_participation = _positive_scale(gap_down, 0.45, 0.90)
    early_rebound = max(up_breadth, up_return)

    high_activity = max(p_vol, p_range)
    low_activity = 1.0 - max(p_vol, p_range)
    directional_strength = max(up_return, down_return)
    directional_breadth = max(up_breadth, down_breadth)
    reversal = _reversal_component(return_0935, return_0940)
    balanced = _balanced_breadth_score(breadth)
    neutral_return = _neutral_score(median_return, 0.00025, 0.0020)

    recovery_score = _clip01(
        0.28 * negative_gap
        + 0.18 * gap_down_participation
        + 0.25 * early_rebound
        + 0.16 * positive_acceleration
        + 0.13 * (1.0 - min(1.0, p_disp))
    )
    trend_up_score = _clip01(
        0.42 * up_breadth
        + 0.36 * up_return
        + 0.14 * positive_acceleration
        + 0.08 * prior_up
    )
    trend_down_score = _clip01(
        0.42 * down_breadth
        + 0.36 * down_return
        + 0.14 * negative_acceleration
        + 0.08 * prior_down
    )
    range_low_vol_score = _clip01(
        0.26 * low_activity
        + 0.24 * neutral_return
        + 0.20 * balanced
        + 0.18 * (1.0 - p_disp)
        + 0.12 * (1.0 - p_gap_disp)
    )
    high_vol_reversal_score = _clip01(
        0.38 * high_activity
        + 0.42 * reversal
        + 0.12 * balanced
        + 0.08 * max(positive_acceleration, negative_acceleration)
    )
    high_dispersion_score = _clip01(
        0.58 * p_disp
        + 0.22 * p_gap_disp
        + 0.20 * balanced
    )
    volatility_expansion_score = _clip01(
        0.30 * p_vol
        + 0.25 * p_range
        + 0.25 * directional_strength
        + 0.20 * directional_breadth
    )

    specialist_scores = {
        "RECOVERY": recovery_score,
        "TREND_UP": trend_up_score,
        "TREND_DOWN": trend_down_score,
        "RANGE_LOW_VOL": range_low_vol_score,
        "HIGH_VOL_REVERSAL": high_vol_reversal_score,
        "HIGH_DISPERSION": high_dispersion_score,
        "VOLATILITY_EXPANSION": volatility_expansion_score,
    }
    strongest_specialist = max(specialist_scores.values())
    conflict = 1.0 - abs(up_breadth - down_breadth)
    defensive_mixed_score = _clip01(0.20 + 0.55 * (1.0 - strongest_specialist) + 0.25 * conflict)
    scores = {**specialist_scores, "DEFENSIVE_MIXED": defensive_mixed_score}

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    primary_regime, primary_score = ranked[0]
    secondary_regime, secondary_score = ranked[1]

    # Recovery is economically distinct and receives a transparent close-score priority.
    if (
        recovery_score >= 0.55
        and primary_regime != "RECOVERY"
        and primary_score - recovery_score <= 0.08
    ):
        secondary_regime, secondary_score = primary_regime, primary_score
        primary_regime, primary_score = "RECOVERY", recovery_score

    margin = max(0.0, primary_score - secondary_score)
    completeness_factor = 1.0 if _bool(row.get("full_regime_feature_ready")) else 0.85
    confidence = _clip01((0.60 * primary_score + 0.40 * min(1.0, margin / 0.25)) * completeness_factor)
    if confidence >= 0.70:
        confidence_band = "HIGH"
    elif confidence >= 0.45:
        confidence_band = "MEDIUM"
    else:
        confidence_band = "LOW"

    direction = _direction_bias(median_return, breadth)
    response = RESPONSE_DEFINITIONS[primary_regime]
    reason = (
        f"{primary_regime} had the highest point-in-time score ({primary_score:.3f}); "
        f"runner-up {secondary_regime} scored {secondary_score:.3f}. "
        f"Direction={direction}, volatility={_state_from_percentile(max(p_vol, p_range))}, "
        f"dispersion={_state_from_percentile(p_disp)}."
    )

    return {
        "taxonomy_eligible": True,
        "data_quality_override": False,
        "direction_bias": direction,
        "volatility_state": _state_from_percentile(max(p_vol, p_range)),
        "dispersion_state": _state_from_percentile(p_disp),
        "gap_state": _gap_state(median_gap, gap_up, gap_down, p_gap_disp),
        "recovery_score": recovery_score,
        "trend_up_score": trend_up_score,
        "trend_down_score": trend_down_score,
        "range_low_vol_score": range_low_vol_score,
        "high_vol_reversal_score": high_vol_reversal_score,
        "high_dispersion_score": high_dispersion_score,
        "volatility_expansion_score": volatility_expansion_score,
        "defensive_mixed_score": defensive_mixed_score,
        "primary_regime": primary_regime,
        "secondary_regime": secondary_regime,
        "primary_score": primary_score,
        "secondary_score": secondary_score,
        "score_margin": margin,
        "regime_confidence": confidence,
        "confidence_band": confidence_band,
        "classification_reason": reason,
        "candidate_playbook": response.playbook,
        "candidate_basket_method": response.basket,
        "portfolio_structure": response.structure,
        "research_risk_multiplier": response.risk_multiplier,
        "research_max_concurrent_ideas": response.max_ideas,
        "response_status": "ACTIVE_SIMULATION_RESPONSE_ASSIGNED",
    }


def build_daily_taxonomy(features: pd.DataFrame, timing_daily: pd.DataFrame | None = None) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    frame = features.copy()
    frame["date"] = frame["date"].astype(str)
    frame = frame.sort_values("date").reset_index(drop=True)

    p_vol, history_count = _prior_percentiles(frame, "median_early_realized_volatility")
    p_range, _ = _prior_percentiles(frame, "median_opening_range_pct")
    p_disp, _ = _prior_percentiles(frame, "cross_sectional_return_dispersion")
    p_gap_disp, _ = _prior_percentiles(frame, "gap_std")
    frame["prior_percentile_history_count"] = history_count
    frame["early_volatility_prior_percentile"] = p_vol
    frame["opening_range_prior_percentile"] = p_range
    frame["return_dispersion_prior_percentile"] = p_disp
    frame["gap_dispersion_prior_percentile"] = p_gap_disp

    if timing_daily is not None and not timing_daily.empty:
        timing = timing_daily.copy()
        timing["date"] = timing["date"].astype(str)
        timing = timing[[
            "date",
            "strict_regime",
            "strict_favorable",
            "strict_triggered_trades",
            "strict_trade_pnl_sek_unconstrained",
        ]].rename(
            columns={
                "strict_regime": "strict_v1_regime_diagnostic",
                "strict_favorable": "strict_v1_favorable_diagnostic",
                "strict_triggered_trades": "strict_v1_triggered_trades_diagnostic",
                "strict_trade_pnl_sek_unconstrained": "strict_v1_trade_pnl_sek_unconstrained_diagnostic",
            }
        )
        frame = frame.merge(timing, on="date", how="left")

    rows: list[dict[str, object]] = []
    for _, source in frame.iterrows():
        classified = _classify_row(source)
        primary_regime = str(classified["primary_regime"])
        strict_router_status = (
            "STRICT_V2_CANDIDATE_REQUIRED"
            if primary_regime == "RECOVERY"
            else "NOT_APPLICABLE_TO_PRIMARY_REGIME"
        )
        row = {
            "taxonomy_id": TAXONOMY_ID,
            "research_status": RESEARCH_STATUS,
            "date": str(source["date"]),
            "decision_time": DECISION_TIME,
            "latest_allowed_bar_label": LATEST_ALLOWED_BAR_LABEL,
            "point_in_time_safe": _bool(source.get("point_in_time_safe")),
            "minimum_regime_feature_ready": _bool(source.get("minimum_regime_feature_ready")),
            "full_regime_feature_ready": _bool(source.get("full_regime_feature_ready")),
            "feature_row_status": str(source.get("feature_row_status", "")),
            "prior_percentile_history_count": int(_num(source.get("prior_percentile_history_count"), 0)),
            "early_volatility_prior_percentile": _num(source.get("early_volatility_prior_percentile"), 0.5),
            "opening_range_prior_percentile": _num(source.get("opening_range_prior_percentile"), 0.5),
            "return_dispersion_prior_percentile": _num(source.get("return_dispersion_prior_percentile"), 0.5),
            "gap_dispersion_prior_percentile": _num(source.get("gap_dispersion_prior_percentile"), 0.5),
            **classified,
            "strict_v1_router_status": strict_router_status,
            "strict_v1_regime_diagnostic": str(source.get("strict_v1_regime_diagnostic", "") or ""),
            "strict_v1_favorable_diagnostic": _bool(source.get("strict_v1_favorable_diagnostic")),
            "strict_v1_triggered_trades_diagnostic": int(_num(source.get("strict_v1_triggered_trades_diagnostic"), 0)),
            "strict_v1_trade_pnl_sek_unconstrained_diagnostic": _num(source.get("strict_v1_trade_pnl_sek_unconstrained_diagnostic"), 0.0),
            "diagnostics_used_for_classification": False,
        }
        rows.append(row)

    return pd.DataFrame(rows, columns=DAILY_COLUMNS).sort_values("date").reset_index(drop=True)


def build_definitions() -> pd.DataFrame:
    rows = []
    for regime in REGIMES:
        definition = RESPONSE_DEFINITIONS[regime]
        rows.append(
            {
                "taxonomy_id": TAXONOMY_ID,
                "regime": regime,
                "market_interpretation": definition.market_interpretation,
                "dominant_point_in_time_evidence": definition.evidence,
                "candidate_playbook": definition.playbook,
                "candidate_basket_method": definition.basket,
                "portfolio_structure": definition.structure,
                "research_risk_multiplier": definition.risk_multiplier,
                "research_max_concurrent_ideas": definition.max_ideas,
                "active_response_required": True,
                "validation_status": "PROVISIONAL_SIMULATION_CANDIDATE_NOT_VALIDATED",
                "strict_v1_requirement": definition.strict_v1_requirement,
            }
        )
    return pd.DataFrame(rows, columns=DEFINITION_COLUMNS)


def build_distribution(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(columns=DISTRIBUTION_COLUMNS)
    total = len(daily)
    rows = []
    for regime, group in daily.groupby("primary_regime", sort=False):
        definition = RESPONSE_DEFINITIONS[str(regime)]
        direction_counts = group["direction_bias"].value_counts()
        rows.append(
            {
                "taxonomy_id": TAXONOMY_ID,
                "primary_regime": regime,
                "session_count": len(group),
                "session_share": len(group) / total,
                "average_confidence": pd.to_numeric(group["regime_confidence"], errors="coerce").mean(),
                "median_confidence": pd.to_numeric(group["regime_confidence"], errors="coerce").median(),
                "high_confidence_sessions": int((group["confidence_band"] == "HIGH").sum()),
                "low_confidence_sessions": int((group["confidence_band"] == "LOW").sum()),
                "up_bias_sessions": int(direction_counts.get("UP", 0)),
                "down_bias_sessions": int(direction_counts.get("DOWN", 0)),
                "neutral_bias_sessions": int(direction_counts.get("NEUTRAL", 0)),
                "strict_v1_triggered_trades_diagnostic": int(pd.to_numeric(group["strict_v1_triggered_trades_diagnostic"], errors="coerce").fillna(0).sum()),
                "strict_v1_trade_pnl_sek_unconstrained_diagnostic": pd.to_numeric(group["strict_v1_trade_pnl_sek_unconstrained_diagnostic"], errors="coerce").fillna(0).sum(),
                "candidate_playbook": definition.playbook,
                "research_risk_multiplier": definition.risk_multiplier,
            }
        )
    return pd.DataFrame(rows, columns=DISTRIBUTION_COLUMNS).sort_values(
        ["session_count", "primary_regime"], ascending=[False, True]
    ).reset_index(drop=True)


def build_transitions(daily: pd.DataFrame) -> pd.DataFrame:
    if len(daily) < 2:
        return pd.DataFrame(columns=TRANSITION_COLUMNS)
    ordered = daily.sort_values("date").copy()
    ordered["from_regime"] = ordered["primary_regime"].shift(1)
    ordered["to_regime"] = ordered["primary_regime"]
    transition_rows = ordered.dropna(subset=["from_regime"]).copy()
    grouped = (
        transition_rows.groupby(["from_regime", "to_regime"], as_index=False)
        .agg(
            transition_count=("date", "count"),
            average_to_regime_confidence=("regime_confidence", "mean"),
        )
    )
    totals = grouped.groupby("from_regime")["transition_count"].transform("sum")
    grouped["taxonomy_id"] = TAXONOMY_ID
    grouped["from_regime_transition_count"] = totals
    grouped["transition_probability"] = grouped["transition_count"] / totals
    return grouped[TRANSITION_COLUMNS].sort_values(
        ["from_regime", "transition_count", "to_regime"], ascending=[True, False, True]
    ).reset_index(drop=True)


def _timing_summary_values() -> tuple[bool, bool, float]:
    if not TIMING_SUMMARY_FILE.exists():
        return True, False, np.nan
    summary = pd.read_csv(TIMING_SUMMARY_FILE)
    if summary.empty:
        return True, False, np.nan
    row = summary.iloc[0]
    classification = str(row.get("classification", ""))
    strict_required = "VERSIONED_FIX_REQUIRED" in classification
    difference = _num(row.get("strict_minus_legacy_pnl_sek"), np.nan)
    return strict_required, False, difference


def build_summary(daily: pd.DataFrame, definitions: pd.DataFrame) -> pd.DataFrame:
    strict_required, legacy_eligible, strict_difference = _timing_summary_values()
    observed = len(daily)
    active = int((daily["response_status"] == "ACTIVE_SIMULATION_RESPONSE_ASSIGNED").sum()) if observed else 0
    no_response = observed - active
    no_trade = int(daily["candidate_playbook"].astype(str).str.contains("NO_TRADE", case=False, na=False).sum()) if observed else 0
    data_limited = int((daily["primary_regime"] == "DATA_LIMITED_DEFENSIVE").sum()) if observed else 0
    taxonomy_eligible = int(daily["taxonomy_eligible"].astype(bool).sum()) if observed else 0
    regimes_observed = int(daily["primary_regime"].nunique()) if observed else 0
    point_safe = int(daily["point_in_time_safe"].astype(bool).sum()) if observed else 0

    if observed and no_response == 0 and no_trade == 0:
        classification = "PROVISIONAL_EXHAUSTIVE_TAXONOMY_READY_WITH_ACTIVE_RESPONSE_EVERY_SESSION"
    else:
        classification = "TAXONOMY_INCOMPLETE_REVIEW_REQUIRED"

    row = {
        "taxonomy_id": TAXONOMY_ID,
        "research_status": RESEARCH_STATUS,
        "decision_time": DECISION_TIME,
        "latest_allowed_bar_label": LATEST_ALLOWED_BAR_LABEL,
        "bar_timestamp_convention": BAR_TIMESTAMP_CONVENTION,
        "observed_sessions": observed,
        "taxonomy_eligible_sessions": taxonomy_eligible,
        "data_limited_sessions": data_limited,
        "sessions_with_active_response": active,
        "sessions_without_active_response": no_response,
        "no_trade_sessions": no_trade,
        "regime_definition_count": len(definitions),
        "regimes_observed": regimes_observed,
        "regimes_with_active_response": int(definitions["active_response_required"].astype(bool).sum()),
        "median_regime_confidence": pd.to_numeric(daily["regime_confidence"], errors="coerce").median() if observed else np.nan,
        "low_confidence_sessions": int((daily["confidence_band"] == "LOW").sum()) if observed else 0,
        "high_confidence_sessions": int((daily["confidence_band"] == "HIGH").sum()) if observed else 0,
        "point_in_time_safe_sessions": point_safe,
        "strict_v1_version_required": strict_required,
        "legacy_v1_router_eligible": legacy_eligible,
        "strict_minus_legacy_pnl_sek": strict_difference,
        "first_session_date": daily["date"].min() if observed else "",
        "last_session_date": daily["date"].max() if observed else "",
        "classification": classification,
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_taxonomy(
    feature_file: Path = FEATURE_FILE,
    timing_daily_file: Path = TIMING_DAILY_FILE,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not feature_file.exists():
        raise FileNotFoundError(f"Missing Step 7 feature file: {feature_file}")
    features = pd.read_csv(feature_file)
    timing_daily = pd.read_csv(timing_daily_file) if timing_daily_file.exists() else pd.DataFrame()
    daily = build_daily_taxonomy(features, timing_daily)
    definitions = build_definitions()
    distribution = build_distribution(daily)
    transitions = build_transitions(daily)
    summary = build_summary(daily, definitions)
    return summary, daily, definitions, distribution, transitions


def main() -> None:
    print("\n=== STEP 8 PROVISIONAL EXHAUSTIVE REGIME TAXONOMY ===")
    print(f"Taxonomy         : {TAXONOMY_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Decision time    : {DECISION_TIME}")
    print(f"Latest bar label : {LATEST_ALLOWED_BAR_LABEL}")
    print("Every observed session receives one active simulation response.")
    print("Frozen legacy V1 is not eligible for the future router; recovery uses a strict point-in-time V2 research candidate.")

    summary, daily, definitions, distribution, transitions = run_taxonomy()
    outputs = [
        (summary, SUMMARY_FILE),
        (daily, DAILY_FILE),
        (definitions, DEFINITIONS_FILE),
        (distribution, DISTRIBUTION_FILE),
        (transitions, TRANSITIONS_FILE),
    ]
    for dataframe, path in outputs:
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")

    result = summary.iloc[0]
    print("\n=== STEP 8 REGIME TAXONOMY RESULT ===")
    print(f"Observed sessions             : {int(result['observed_sessions'])}")
    print(f"Taxonomy-eligible sessions    : {int(result['taxonomy_eligible_sessions'])}")
    print(f"Data-limited defensive days   : {int(result['data_limited_sessions'])}")
    print(f"Active-response sessions      : {int(result['sessions_with_active_response'])}/{int(result['observed_sessions'])}")
    print(f"No-trade sessions             : {int(result['no_trade_sessions'])}")
    print(f"Regime definitions            : {int(result['regime_definition_count'])}")
    print(f"Regimes observed              : {int(result['regimes_observed'])}")
    print(f"Median regime confidence      : {float(result['median_regime_confidence']):.2%}")
    print(f"Strict V1 version required    : {bool(result['strict_v1_version_required'])}")
    print(f"Legacy V1 router eligible     : {bool(result['legacy_v1_router_eligible'])}")
    print(f"Classification                : {result['classification']}")
    print("Step 8 taxonomy export complete.")


if __name__ == "__main__":
    main()
