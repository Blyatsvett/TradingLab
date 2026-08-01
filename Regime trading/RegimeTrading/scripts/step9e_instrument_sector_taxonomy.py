from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, REFERENCE_DATA_DIR, legacy_output_path
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    GAP_RECOVERY_TICKERS,
    build_daily_reference,
    load_intraday_prices,
)


TAXONOMY_ID = "INSTRUMENT_SECTOR_TICKER_TAXONOMY_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_FOUNDATION_NOT_ROUTER_ACTIVE"
DECISION_TIME = "09:45"
LATEST_ALLOWED_BAR_LABEL = "09:40"
HISTORY_WINDOW = 20
MINIMUM_HISTORY_SESSIONS = 5
RELATIVE_STATE_THRESHOLD = 0.0020
EARLY_MOVE_MINIMUM = 0.0010
RANGE_EXPANSION_RATIO = 1.25
RANGE_COMPRESSION_RATIO = 0.75

SUMMARY_FILE = legacy_output_path("instrument_taxonomy_summary.csv")
STATIC_FILE = REFERENCE_DATA_DIR / "instrument_static_taxonomy.csv"
DEFINITION_FILE = REFERENCE_DATA_DIR / "instrument_characteristic_definitions.csv"
CHARACTERISTIC_FILE = REFERENCE_DATA_DIR / "instrument_point_in_time_characteristics.csv"
GROUP_STATE_FILE = REFERENCE_DATA_DIR / "instrument_group_daily_state.csv"
COMPLETENESS_FILE = legacy_output_path("instrument_taxonomy_completeness.csv")
CONSTRAINT_FILE = REFERENCE_DATA_DIR / "instrument_relationship_constraints.csv"
AUDIT_FILE = legacy_output_path("instrument_taxonomy_audit.csv")


# Stable metadata is deliberately versioned and manually reviewed. It is descriptive
# research metadata, not a trading signal and not an attempt to reproduce a commercial
# classification provider exactly.
STATIC_INSTRUMENTS = [
    {
        "ticker": "ALFA.ST",
        "company_id": "ALFA_LAVAL",
        "company_name": "Alfa Laval AB",
        "share_class_group": "ALFA_LAVAL",
        "share_class": "ORDINARY",
        "broad_sector": "INDUSTRIALS",
        "industry_group": "INDUSTRIAL_MACHINERY",
        "economic_cluster": "INDUSTRIAL_CYCLICAL_EXPORT",
        "primary_peer_group": "INDUSTRIAL_ENGINEERING",
        "cyclical_profile": "HIGH",
        "rate_sensitivity": "MEDIUM",
        "commodity_sensitivity": "MEDIUM",
        "export_sensitivity": "HIGH",
        "defensive_profile": "LOW",
        "regulatory_sensitivity": "LOW",
        "idiosyncratic_event_sensitivity": "MEDIUM",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "alfalaval.com",
    },
    {
        "ticker": "ATCO-A.ST",
        "company_id": "ATLAS_COPCO",
        "company_name": "Atlas Copco AB",
        "share_class_group": "ATLAS_COPCO",
        "share_class": "A",
        "broad_sector": "INDUSTRIALS",
        "industry_group": "INDUSTRIAL_MACHINERY",
        "economic_cluster": "INDUSTRIAL_CYCLICAL_EXPORT",
        "primary_peer_group": "INDUSTRIAL_ENGINEERING",
        "cyclical_profile": "HIGH",
        "rate_sensitivity": "MEDIUM",
        "commodity_sensitivity": "LOW",
        "export_sensitivity": "HIGH",
        "defensive_profile": "LOW",
        "regulatory_sensitivity": "LOW",
        "idiosyncratic_event_sensitivity": "MEDIUM",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "atlascopcogroup.com",
    },
    {
        "ticker": "ATCO-B.ST",
        "company_id": "ATLAS_COPCO",
        "company_name": "Atlas Copco AB",
        "share_class_group": "ATLAS_COPCO",
        "share_class": "B",
        "broad_sector": "INDUSTRIALS",
        "industry_group": "INDUSTRIAL_MACHINERY",
        "economic_cluster": "INDUSTRIAL_CYCLICAL_EXPORT",
        "primary_peer_group": "INDUSTRIAL_ENGINEERING",
        "cyclical_profile": "HIGH",
        "rate_sensitivity": "MEDIUM",
        "commodity_sensitivity": "LOW",
        "export_sensitivity": "HIGH",
        "defensive_profile": "LOW",
        "regulatory_sensitivity": "LOW",
        "idiosyncratic_event_sensitivity": "MEDIUM",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "atlascopcogroup.com",
    },
    {
        "ticker": "AZN.ST",
        "company_id": "ASTRAZENECA",
        "company_name": "AstraZeneca PLC",
        "share_class_group": "ASTRAZENECA",
        "share_class": "ORDINARY",
        "broad_sector": "HEALTH_CARE",
        "industry_group": "BIOPHARMACEUTICALS",
        "economic_cluster": "HEALTHCARE_DEFENSIVE_GLOBAL",
        "primary_peer_group": "DEFENSIVE_GLOBAL_HEALTHCARE",
        "cyclical_profile": "LOW",
        "rate_sensitivity": "LOW",
        "commodity_sensitivity": "LOW",
        "export_sensitivity": "HIGH",
        "defensive_profile": "HIGH",
        "regulatory_sensitivity": "HIGH",
        "idiosyncratic_event_sensitivity": "HIGH",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "astrazeneca.com",
    },
    {
        "ticker": "BOL.ST",
        "company_id": "BOLIDEN",
        "company_name": "Boliden AB",
        "share_class_group": "BOLIDEN",
        "share_class": "ORDINARY",
        "broad_sector": "MATERIALS",
        "industry_group": "METALS_AND_MINING",
        "economic_cluster": "MATERIALS_COMMODITY_CYCLICAL",
        "primary_peer_group": "EXPORT_CYCLICALS",
        "cyclical_profile": "HIGH",
        "rate_sensitivity": "MEDIUM",
        "commodity_sensitivity": "HIGH",
        "export_sensitivity": "HIGH",
        "defensive_profile": "LOW",
        "regulatory_sensitivity": "MEDIUM",
        "idiosyncratic_event_sensitivity": "MEDIUM",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "boliden.com",
    },
    {
        "ticker": "ERIC-B.ST",
        "company_id": "ERICSSON",
        "company_name": "Telefonaktiebolaget LM Ericsson",
        "share_class_group": "ERICSSON",
        "share_class": "B",
        "broad_sector": "INFORMATION_TECHNOLOGY",
        "industry_group": "COMMUNICATIONS_EQUIPMENT",
        "economic_cluster": "TECHNOLOGY_EXPORT_CYCLICAL",
        "primary_peer_group": "EXPORT_CYCLICALS",
        "cyclical_profile": "MEDIUM",
        "rate_sensitivity": "MEDIUM",
        "commodity_sensitivity": "LOW",
        "export_sensitivity": "HIGH",
        "defensive_profile": "LOW",
        "regulatory_sensitivity": "MEDIUM",
        "idiosyncratic_event_sensitivity": "HIGH",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "ericsson.com",
    },
    {
        "ticker": "EVO.ST",
        "company_id": "EVOLUTION",
        "company_name": "Evolution AB",
        "share_class_group": "EVOLUTION",
        "share_class": "ORDINARY",
        "broad_sector": "CONSUMER_DISCRETIONARY",
        "industry_group": "B2B_ONLINE_GAMING_TECHNOLOGY",
        "economic_cluster": "DIGITAL_CONSUMER_REGULATED_GROWTH",
        "primary_peer_group": "DIGITAL_GROWTH",
        "cyclical_profile": "MEDIUM",
        "rate_sensitivity": "MEDIUM",
        "commodity_sensitivity": "LOW",
        "export_sensitivity": "HIGH",
        "defensive_profile": "LOW",
        "regulatory_sensitivity": "HIGH",
        "idiosyncratic_event_sensitivity": "HIGH",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "evolution.com",
    },
    {
        "ticker": "SAND.ST",
        "company_id": "SANDVIK",
        "company_name": "Sandvik AB",
        "share_class_group": "SANDVIK",
        "share_class": "ORDINARY",
        "broad_sector": "INDUSTRIALS",
        "industry_group": "INDUSTRIAL_ENGINEERING_AND_MINING_TECH",
        "economic_cluster": "INDUSTRIAL_CYCLICAL_EXPORT",
        "primary_peer_group": "INDUSTRIAL_ENGINEERING",
        "cyclical_profile": "HIGH",
        "rate_sensitivity": "MEDIUM",
        "commodity_sensitivity": "MEDIUM",
        "export_sensitivity": "HIGH",
        "defensive_profile": "LOW",
        "regulatory_sensitivity": "LOW",
        "idiosyncratic_event_sensitivity": "MEDIUM",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "sandvik.com",
    },
    {
        "ticker": "SEB-A.ST",
        "company_id": "SEB",
        "company_name": "Skandinaviska Enskilda Banken AB",
        "share_class_group": "SEB",
        "share_class": "A",
        "broad_sector": "FINANCIALS",
        "industry_group": "BANKS",
        "economic_cluster": "FINANCIAL_RATE_SENSITIVE",
        "primary_peer_group": "SWEDISH_BANKS",
        "cyclical_profile": "MEDIUM",
        "rate_sensitivity": "HIGH",
        "commodity_sensitivity": "LOW",
        "export_sensitivity": "MEDIUM",
        "defensive_profile": "MEDIUM",
        "regulatory_sensitivity": "HIGH",
        "idiosyncratic_event_sensitivity": "MEDIUM",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "sebgroup.com",
    },
    {
        "ticker": "SHB-A.ST",
        "company_id": "HANDELSBANKEN",
        "company_name": "Svenska Handelsbanken AB",
        "share_class_group": "HANDELSBANKEN",
        "share_class": "A",
        "broad_sector": "FINANCIALS",
        "industry_group": "BANKS",
        "economic_cluster": "FINANCIAL_RATE_SENSITIVE",
        "primary_peer_group": "SWEDISH_BANKS",
        "cyclical_profile": "MEDIUM",
        "rate_sensitivity": "HIGH",
        "commodity_sensitivity": "LOW",
        "export_sensitivity": "LOW",
        "defensive_profile": "MEDIUM",
        "regulatory_sensitivity": "HIGH",
        "idiosyncratic_event_sensitivity": "MEDIUM",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "handelsbanken.com",
    },
    {
        "ticker": "SWED-A.ST",
        "company_id": "SWEDBANK",
        "company_name": "Swedbank AB",
        "share_class_group": "SWEDBANK",
        "share_class": "A",
        "broad_sector": "FINANCIALS",
        "industry_group": "BANKS",
        "economic_cluster": "FINANCIAL_RATE_SENSITIVE",
        "primary_peer_group": "SWEDISH_BANKS",
        "cyclical_profile": "MEDIUM",
        "rate_sensitivity": "HIGH",
        "commodity_sensitivity": "LOW",
        "export_sensitivity": "LOW",
        "defensive_profile": "MEDIUM",
        "regulatory_sensitivity": "HIGH",
        "idiosyncratic_event_sensitivity": "MEDIUM",
        "liquidity_assumption": "CORE_LARGE_CAP",
        "shortability_assumption": "RESEARCH_ASSUMED_SHORTABLE",
        "classification_source_domain": "swedbank.com",
    },
]

STATIC_COLUMNS = [
    "taxonomy_id", "research_status", "ticker", "company_id", "company_name",
    "share_class_group", "share_class", "company_observation_weight", "broad_sector",
    "industry_group", "economic_cluster", "primary_peer_group", "cyclical_profile",
    "rate_sensitivity", "commodity_sensitivity", "export_sensitivity", "defensive_profile",
    "regulatory_sensitivity", "idiosyncratic_event_sensitivity", "liquidity_assumption",
    "liquidity_data_status", "shortability_assumption", "classification_method",
    "classification_source_domain", "classification_review_date", "metadata_valid_from",
    "metadata_valid_to", "router_active",
]

SUMMARY_COLUMNS = [
    "taxonomy_id", "research_status", "decision_time", "latest_allowed_bar_label",
    "history_window_sessions", "minimum_history_sessions", "configured_tickers",
    "observed_tickers", "independent_companies", "broad_sectors", "industry_groups",
    "economic_clusters", "primary_peer_groups", "observed_sessions", "characteristic_rows",
    "minimum_history_ready_rows", "full_history_ready_rows", "group_state_rows",
    "single_company_group_state_rows", "static_mapping_complete", "company_weight_audit_pass",
    "point_in_time_audit_rows", "point_in_time_audit_pass_rows", "point_in_time_audit_fail_rows",
    "future_source_rows", "duplicate_company_share_class_conflicts", "router_active",
    "classification",
]

DEFINITION_COLUMNS = [
    "parameter_name", "parameter_group", "description", "formula_or_method", "source_scope",
    "point_in_time_rule", "default_parameter", "interpretation_guardrail", "current_status",
]

CHARACTERISTIC_COLUMNS = [
    "taxonomy_id", "date", "ticker", "company_id", "company_name", "share_class_group",
    "company_observation_weight", "broad_sector", "industry_group", "economic_cluster",
    "primary_peer_group", "decision_time", "latest_allowed_bar_label", "previous_close",
    "open_price", "cutoff_close", "opening_gap_pct", "cutoff_return_from_open",
    "early_range_pct", "market_return_from_open_company_weighted", "sector_return_from_open_company_weighted",
    "economic_cluster_return_from_open_company_weighted", "sector_independent_company_count",
    "economic_cluster_independent_company_count", "sector_relative_return",
    "economic_cluster_relative_return", "market_relative_return", "relative_reference_used",
    "relative_return_used", "ticker_relative_state", "gap_state", "prior_history_sessions",
    "prior_history_max_date", "prior_20d_daily_return_mean", "prior_20d_daily_volatility",
    "prior_20d_average_daily_range_pct", "prior_20d_average_early_range_pct",
    "prior_20d_average_absolute_gap_pct", "prior_20d_gap_volatility", "prior_20d_momentum_return",
    "prior_20d_beta_to_company_weighted_market", "prior_20d_correlation_to_company_weighted_market",
    "prior_20d_early_move_followthrough_rate", "prior_20d_early_move_reversal_rate",
    "prior_20d_early_move_observations", "historical_tendency", "volatility_percentile_cross_section",
    "volatility_bucket", "range_state", "minimum_history_ready", "full_history_ready",
    "max_same_day_source_label", "point_in_time_pass", "characteristic_status",
]

GROUP_STATE_COLUMNS = [
    "taxonomy_id", "date", "decision_time", "aggregation_level", "group_name", "ticker_count",
    "independent_company_count", "observed_ticker_count", "effective_company_weight",
    "mean_gap_company_weighted", "median_gap", "positive_gap_breadth_company_weighted",
    "mean_return_from_open_company_weighted", "median_return_from_open", "breadth_above_open_company_weighted",
    "cross_sectional_return_dispersion", "mean_early_range_pct_company_weighted",
    "market_return_from_open_company_weighted", "group_relative_return_vs_market",
    "group_direction_state", "group_peer_status", "max_same_day_source_label", "point_in_time_pass",
]

COMPLETENESS_COLUMNS = [
    "taxonomy_id", "date", "ticker", "static_metadata_complete", "early_data_complete",
    "previous_close_available", "prior_history_sessions", "minimum_history_ready", "full_history_ready",
    "sector_independent_company_count", "economic_cluster_independent_company_count",
    "same_company_symbol_count", "company_weight", "point_in_time_pass", "completeness_status",
    "excluded_or_partial_reason",
]

CONSTRAINT_COLUMNS = [
    "taxonomy_id", "constraint_id", "constraint_scope", "rule_definition", "default_parameter",
    "rationale", "enforcement_status", "future_use",
]

AUDIT_COLUMNS = [
    "taxonomy_id", "audit_date", "ticker", "audit_group", "source_scope", "max_source_date",
    "max_source_label", "allowed_source_date_rule", "allowed_source_label", "point_in_time_pass",
    "audit_status", "notes",
]


DEFINITIONS = [
    {
        "parameter_name": "company_observation_weight",
        "parameter_group": "STATIC_ENTITY_CONTROL",
        "description": "Weight that prevents multiple listed share classes from counting as multiple independent companies.",
        "formula_or_method": "1 divided by configured ticker symbols for the same company_id.",
        "source_scope": "Versioned static metadata",
        "point_in_time_rule": "Known before the research session and unchanged inside this taxonomy version.",
        "default_parameter": "ATCO-A and ATCO-B each receive 0.50; single-symbol companies receive 1.00.",
        "interpretation_guardrail": "This is an aggregation weight, not a portfolio allocation recommendation.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
    {
        "parameter_name": "broad_sector",
        "parameter_group": "STATIC_BUSINESS_CLASSIFICATION",
        "description": "High-level economic business grouping used to test whether regime-strategy results differ across sectors.",
        "formula_or_method": "Manually versioned classification from official company business descriptions.",
        "source_scope": "Official company descriptions reviewed for this research version",
        "point_in_time_rule": "Static metadata is frozen for the historical research window; later reclassifications require a new version.",
        "default_parameter": "Six broad sectors in the current 11-symbol universe.",
        "interpretation_guardrail": "Single-company sectors cannot independently establish a sector effect.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
    {
        "parameter_name": "economic_cluster",
        "parameter_group": "STATIC_BUSINESS_CLASSIFICATION",
        "description": "Cross-sector grouping by broad macro sensitivity rather than formal exchange sector.",
        "formula_or_method": "Manually assigned from business model, cyclicality, rates, commodities, export exposure and defensiveness.",
        "source_scope": "Versioned research metadata",
        "point_in_time_rule": "Frozen within taxonomy version.",
        "default_parameter": "Examples include FINANCIAL_RATE_SENSITIVE and INDUSTRIAL_CYCLICAL_EXPORT.",
        "interpretation_guardrail": "Economic clusters are hypotheses to test, not claims of identical company exposure.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
    {
        "parameter_name": "prior_20d_daily_volatility",
        "parameter_group": "PRIOR_ONLY_TICKER_CHARACTERISTIC",
        "description": "Recent variability of the ticker's completed open-to-close daily returns.",
        "formula_or_method": "Sample standard deviation of up to 20 completed sessions before the current date.",
        "source_scope": "Intraday OHLC aggregated to completed sessions",
        "point_in_time_rule": "Current session and later sessions are excluded.",
        "default_parameter": "20 prior sessions; minimum 5 for readiness.",
        "interpretation_guardrail": "Short windows are descriptive and unstable; bucket labels are relative to the current universe.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
    {
        "parameter_name": "prior_20d_beta_to_company_weighted_market",
        "parameter_group": "PRIOR_ONLY_TICKER_CHARACTERISTIC",
        "description": "Sensitivity of a ticker's completed daily return to the company-weighted research-universe return.",
        "formula_or_method": "Covariance(ticker, market) divided by variance(market) over matched prior sessions.",
        "source_scope": "Completed prior-session OHLC",
        "point_in_time_rule": "Only dates strictly earlier than the classified session are used.",
        "default_parameter": "20 prior sessions; minimum 5 matched returns.",
        "interpretation_guardrail": "This is a universe beta, not beta to OMX Stockholm or a tradable market index.",
        "current_status": "ACTIVE_WITH_INTERNAL_MARKET_PROXY",
    },
    {
        "parameter_name": "prior_20d_early_move_followthrough_rate",
        "parameter_group": "PRIOR_ONLY_BEHAVIORAL_CHARACTERISTIC",
        "description": "Historical tendency for a meaningful 09:40 move to finish the session in the same direction.",
        "formula_or_method": "Share of prior sessions where sign(09:40 return from open) equals sign(close/open), conditional on absolute early move >= 0.10%.",
        "source_scope": "Completed prior sessions",
        "point_in_time_rule": "The current session outcome is never used.",
        "default_parameter": "20-session lookback; 0.10% minimum early move.",
        "interpretation_guardrail": "A high rate does not imply that every continuation entry is profitable after entry timing and costs.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
    {
        "parameter_name": "prior_20d_early_move_reversal_rate",
        "parameter_group": "PRIOR_ONLY_BEHAVIORAL_CHARACTERISTIC",
        "description": "Historical tendency for a meaningful 09:40 move to finish the session in the opposite direction.",
        "formula_or_method": "Share of prior sessions where sign(09:40 return from open) differs from sign(close/open), conditional on absolute early move >= 0.10%.",
        "source_scope": "Completed prior sessions",
        "point_in_time_rule": "The current session outcome is never used.",
        "default_parameter": "20-session lookback; 0.10% minimum early move.",
        "interpretation_guardrail": "Followthrough and reversal rates exclude flat outcomes and are descriptive, not optimized signals.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
    {
        "parameter_name": "ticker_relative_state",
        "parameter_group": "SAME_DAY_POINT_IN_TIME_STATE",
        "description": "Whether the ticker leads, lags or tracks a peer reference at the 09:45 decision point.",
        "formula_or_method": "Sector-relative return when at least two independent companies exist; otherwise economic-cluster-relative; otherwise market-relative. Leader/laggard threshold is +/-0.20%.",
        "source_scope": "Bars labelled through 09:40",
        "point_in_time_rule": "No same-day bar later than 09:40 may influence the state.",
        "default_parameter": "+/-0.20% relative return threshold.",
        "interpretation_guardrail": "The threshold is a pre-registered baseline and must not be tuned from Step 9F winners without a new version.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
    {
        "parameter_name": "range_state",
        "parameter_group": "SAME_DAY_VERSUS_PRIOR_STATE",
        "description": "Whether the current strict early range is compressed or expanded relative to the ticker's own history.",
        "formula_or_method": "Current 09:30-09:40 range divided by prior-20-session average early range.",
        "source_scope": "Current bars through 09:40 plus completed prior sessions",
        "point_in_time_rule": "Current-day input ends at 09:40; historical denominator excludes the current day.",
        "default_parameter": "Expanded >=1.25x; compressed <=0.75x; otherwise normal.",
        "interpretation_guardrail": "Unavailable until minimum prior history exists.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
    {
        "parameter_name": "group_direction_state",
        "parameter_group": "SAME_DAY_GROUP_STATE",
        "description": "Direction of a sector, economic cluster or peer group at the decision point.",
        "formula_or_method": "UP when weighted mean return >=0.10% and weighted breadth above open >=60%; DOWN when mean <=-0.10% and breadth <=40%; otherwise MIXED.",
        "source_scope": "Company-weighted bars through 09:40",
        "point_in_time_rule": "No same-day source later than 09:40.",
        "default_parameter": "0.10% return and 60/40 breadth thresholds.",
        "interpretation_guardrail": "Single-company groups are labelled as proxies and cannot prove a group-level pattern.",
        "current_status": "ACTIVE_FOUNDATION_PARAMETER",
    },
]

CONSTRAINTS = [
    {
        "constraint_id": "ONE_SHARE_CLASS_PER_COMPANY",
        "constraint_scope": "BASKET_AND_PORTFOLIO",
        "rule_definition": "A strategy basket may contain at most one listed share class from the same company_id.",
        "default_parameter": "Maximum 1 ticker per company_id",
        "rationale": "Prevents Atlas Copco A and B from consuming two slots or doubling one economic exposure.",
        "enforcement_status": "DEFINED_NOT_YET_APPLIED_TO_STEP9D_CONTROL",
        "future_use": "Mandatory in Step 9F sector/ticker experiments and later shared-account routing.",
    },
    {
        "constraint_id": "NO_SAME_COMPANY_PAIR",
        "constraint_scope": "PAIR_CONSTRUCTION",
        "rule_definition": "Long and short legs must have different company_id values.",
        "default_parameter": "Different company_id required",
        "rationale": "A share-class spread is a separate arbitrage hypothesis and should not contaminate sector relative-value tests.",
        "enforcement_status": "DEFINED_FOR_STEP9F",
        "future_use": "Pair candidate validation.",
    },
    {
        "constraint_id": "COMPANY_WEIGHTED_GROUP_AGGREGATION",
        "constraint_scope": "FEATURE_AGGREGATION",
        "rule_definition": "Each independent company contributes total weight 1.0 across all listed share classes.",
        "default_parameter": "Sum of company_observation_weight per company = 1.0",
        "rationale": "Prevents multi-class issuers from distorting market, sector and cluster breadth or returns.",
        "enforcement_status": "ENFORCED_IN_STEP9E",
        "future_use": "All market and group state calculations.",
    },
    {
        "constraint_id": "SINGLE_COMPANY_GROUP_IS_PROXY",
        "constraint_scope": "INTERPRETATION",
        "rule_definition": "A sector or cluster with fewer than two independent companies is labelled a single-company proxy.",
        "default_parameter": "Minimum 2 independent companies for peer-group inference",
        "rationale": "Avoids describing company-specific behavior as a sector effect.",
        "enforcement_status": "ENFORCED_IN_OUTPUT_LABELS",
        "future_use": "Step 9F screening and sample warnings.",
    },
    {
        "constraint_id": "STATIC_LIQUIDITY_IS_NOT_MEASURED_LIQUIDITY",
        "constraint_scope": "DATA_QUALITY",
        "rule_definition": "Current liquidity grouping is an explicit static assumption because reliable historical volume and spreads are absent.",
        "default_parameter": "STATIC_ASSUMPTION_ONLY",
        "rationale": "Prevents an unsupported liquidity proxy from being treated as observed fact.",
        "enforcement_status": "ENFORCED_IN_METADATA",
        "future_use": "Replace with prior turnover and spread data when available.",
    },
    {
        "constraint_id": "NO_ROUTER_USE_IN_STEP9E",
        "constraint_scope": "RESEARCH_GOVERNANCE",
        "rule_definition": "Step 9E creates descriptive features only and may not alter historical Step 9D trades or promote a strategy.",
        "default_parameter": "router_active=False",
        "rationale": "Separates foundation construction from strategy discovery and prevents silent retroactive changes.",
        "enforcement_status": "ENFORCED",
        "future_use": "Step 9F consumes a frozen Step 9E version.",
    },
]


def _num(value, default=np.nan) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clock(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values).dt.strftime("%H:%M")


def _normalize_source_label(value) -> str:
    """Return a stable HH:MM-like label or an empty string for missing data."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _max_valid_source_label(values: pd.Series) -> str:
    """Return the latest non-missing source label without comparing strings to NaN."""
    labels = values.map(_normalize_source_label)
    labels = labels[labels.ne("")]
    return str(labels.max()) if not labels.empty else ""


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return np.nan
    return float(np.average(values[valid].astype(float), weights=weights[valid].astype(float)))


def build_static_taxonomy() -> pd.DataFrame:
    static = pd.DataFrame(STATIC_INSTRUMENTS).copy()
    counts = static.groupby("company_id")["ticker"].transform("count")
    static["company_observation_weight"] = 1.0 / counts.astype(float)
    static.insert(0, "research_status", RESEARCH_STATUS)
    static.insert(0, "taxonomy_id", TAXONOMY_ID)
    static["liquidity_data_status"] = "STATIC_ASSUMPTION_ONLY_NO_RELIABLE_VOLUME_OR_SPREAD"
    static["classification_method"] = "MANUALLY_VERSIONED_RESEARCH_METADATA_FROM_OFFICIAL_BUSINESS_DESCRIPTIONS"
    static["classification_review_date"] = "2026-07-24"
    static["metadata_valid_from"] = "2026-01-01"
    static["metadata_valid_to"] = ""
    static["router_active"] = False
    return static[STATIC_COLUMNS].sort_values("ticker").reset_index(drop=True)


def _daily_input(prices: pd.DataFrame, static: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    p = prices[prices["ticker"].isin(static["ticker"])].copy()
    p["clock"] = _clock(p["datetime"])
    p = p.sort_values(["ticker", "date", "datetime"])

    daily = (
        p.groupby(["ticker", "date"], as_index=False)
        .agg(
            open_price=("open", "first"),
            daily_high=("high", "max"),
            daily_low=("low", "min"),
            daily_close=("close", "last"),
        )
    )
    daily = daily.sort_values(["ticker", "date"]).reset_index(drop=True)
    daily["previous_close"] = daily.groupby("ticker")["daily_close"].shift(1)

    early = p[p["clock"].le(LATEST_ALLOWED_BAR_LABEL)].copy()
    early = early[early["clock"].ge("09:30")]
    early_agg = (
        early.groupby(["ticker", "date"], as_index=False)
        .agg(
            cutoff_close=("close", "last"),
            early_high=("high", "max"),
            early_low=("low", "min"),
            max_same_day_source_label=("clock", "max"),
            early_bar_count=("clock", "nunique"),
        )
    )
    daily = daily.merge(early_agg, on=["ticker", "date"], how="left")
    daily["daily_return"] = daily["daily_close"] / daily["open_price"] - 1.0
    daily["daily_range_pct"] = (daily["daily_high"] - daily["daily_low"]) / daily["open_price"]
    daily["opening_gap_pct"] = daily["open_price"] / daily["previous_close"] - 1.0
    daily["cutoff_return_from_open"] = daily["cutoff_close"] / daily["open_price"] - 1.0
    daily["early_range_pct"] = (daily["early_high"] - daily["early_low"]) / daily["open_price"]
    daily = daily.merge(
        static[[
            "ticker", "company_id", "company_name", "share_class_group", "company_observation_weight",
            "broad_sector", "industry_group", "economic_cluster", "primary_peer_group",
        ]],
        on="ticker",
        how="left",
    )
    return daily.sort_values(["date", "ticker"]).reset_index(drop=True)


def _company_weighted_market_returns(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, frame in daily.groupby("date", sort=True):
        rows.append(
            {
                "date": date,
                "market_daily_return": _weighted_mean(frame["daily_return"], frame["company_observation_weight"]),
                "market_early_return": _weighted_mean(frame["cutoff_return_from_open"], frame["company_observation_weight"]),
            }
        )
    return pd.DataFrame(rows)


def _prior_characteristics(
    row: pd.Series,
    daily: pd.DataFrame,
    market_returns: pd.DataFrame,
    history_window: int,
    minimum_history: int,
) -> dict:
    ticker = row["ticker"]
    date = row["date"]
    prior = daily[(daily["ticker"].eq(ticker)) & (daily["date"] < date)].tail(history_window).copy()
    history_count = int(len(prior))
    result = {
        "prior_history_sessions": history_count,
        "prior_history_max_date": prior["date"].max() if history_count else "",
        "prior_20d_daily_return_mean": np.nan,
        "prior_20d_daily_volatility": np.nan,
        "prior_20d_average_daily_range_pct": np.nan,
        "prior_20d_average_early_range_pct": np.nan,
        "prior_20d_average_absolute_gap_pct": np.nan,
        "prior_20d_gap_volatility": np.nan,
        "prior_20d_momentum_return": np.nan,
        "prior_20d_beta_to_company_weighted_market": np.nan,
        "prior_20d_correlation_to_company_weighted_market": np.nan,
        "prior_20d_early_move_followthrough_rate": np.nan,
        "prior_20d_early_move_reversal_rate": np.nan,
        "prior_20d_early_move_observations": 0,
        "historical_tendency": "NOT_READY",
        "minimum_history_ready": history_count >= minimum_history,
        "full_history_ready": history_count >= history_window,
    }
    if history_count < minimum_history:
        return result

    result["prior_20d_daily_return_mean"] = float(prior["daily_return"].mean())
    result["prior_20d_daily_volatility"] = float(prior["daily_return"].std(ddof=1)) if history_count > 1 else 0.0
    result["prior_20d_average_daily_range_pct"] = float(prior["daily_range_pct"].mean())
    result["prior_20d_average_early_range_pct"] = float(prior["early_range_pct"].mean())
    result["prior_20d_average_absolute_gap_pct"] = float(prior["opening_gap_pct"].abs().mean())
    result["prior_20d_gap_volatility"] = float(prior["opening_gap_pct"].std(ddof=1)) if history_count > 1 else 0.0
    result["prior_20d_momentum_return"] = float(np.prod(1.0 + prior["daily_return"].fillna(0.0)) - 1.0)

    matched = prior[["date", "daily_return"]].merge(market_returns, on="date", how="inner").dropna()
    if len(matched) >= minimum_history:
        market_var = float(matched["market_daily_return"].var(ddof=1))
        if market_var > 0:
            covariance = float(matched[["daily_return", "market_daily_return"]].cov().iloc[0, 1])
            result["prior_20d_beta_to_company_weighted_market"] = covariance / market_var
        if matched["daily_return"].std(ddof=1) > 0 and matched["market_daily_return"].std(ddof=1) > 0:
            result["prior_20d_correlation_to_company_weighted_market"] = float(
                matched["daily_return"].corr(matched["market_daily_return"])
            )

    eligible = prior[
        prior["cutoff_return_from_open"].abs().ge(EARLY_MOVE_MINIMUM)
        & prior["daily_return"].abs().gt(0)
    ].copy()
    if not eligible.empty:
        early_sign = np.sign(eligible["cutoff_return_from_open"].astype(float))
        close_sign = np.sign(eligible["daily_return"].astype(float))
        follow = early_sign.eq(close_sign)
        reverse = early_sign.eq(-close_sign)
        result["prior_20d_early_move_observations"] = int(len(eligible))
        result["prior_20d_early_move_followthrough_rate"] = float(follow.mean())
        result["prior_20d_early_move_reversal_rate"] = float(reverse.mean())
        if result["prior_20d_early_move_followthrough_rate"] >= 0.60:
            result["historical_tendency"] = "CONTINUATION_PRONE"
        elif result["prior_20d_early_move_reversal_rate"] >= 0.60:
            result["historical_tendency"] = "REVERSAL_PRONE"
        else:
            result["historical_tendency"] = "MIXED"
    else:
        result["historical_tendency"] = "INSUFFICIENT_MEANINGFUL_EARLY_MOVES"
    return result


def _group_weighted_return(frame: pd.DataFrame, group_column: str) -> pd.Series:
    result = pd.Series(index=frame.index, dtype=float)
    for _, group in frame.groupby(group_column, dropna=False):
        value = _weighted_mean(group["cutoff_return_from_open"], group["company_observation_weight"])
        result.loc[group.index] = value
    return result


def _group_independent_count(frame: pd.DataFrame, group_column: str) -> pd.Series:
    return frame.groupby(group_column)["company_id"].transform("nunique").astype(int)


def build_point_in_time_characteristics(
    prices: pd.DataFrame,
    static: pd.DataFrame | None = None,
    history_window: int = HISTORY_WINDOW,
    minimum_history: int = MINIMUM_HISTORY_SESSIONS,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    static = build_static_taxonomy() if static is None else static.copy()
    daily = _daily_input(prices, static)
    if daily.empty:
        return (
            pd.DataFrame(columns=CHARACTERISTIC_COLUMNS),
            pd.DataFrame(columns=GROUP_STATE_COLUMNS),
            pd.DataFrame(columns=COMPLETENESS_COLUMNS),
            pd.DataFrame(columns=AUDIT_COLUMNS),
        )

    market_returns = _company_weighted_market_returns(daily)
    daily = daily.merge(market_returns[["date", "market_early_return"]], on="date", how="left")
    daily["sector_early_return"] = daily.groupby("date", group_keys=False).apply(
        lambda day: _group_weighted_return(day, "broad_sector"), include_groups=False
    ).reset_index(level=0, drop=True)
    daily["cluster_early_return"] = daily.groupby("date", group_keys=False).apply(
        lambda day: _group_weighted_return(day, "economic_cluster"), include_groups=False
    ).reset_index(level=0, drop=True)
    daily["sector_company_count"] = daily.groupby("date", group_keys=False).apply(
        lambda day: _group_independent_count(day, "broad_sector"), include_groups=False
    ).reset_index(level=0, drop=True)
    daily["cluster_company_count"] = daily.groupby("date", group_keys=False).apply(
        lambda day: _group_independent_count(day, "economic_cluster"), include_groups=False
    ).reset_index(level=0, drop=True)

    characteristic_rows = []
    audit_rows = []
    completeness_rows = []
    for _, row in daily.iterrows():
        prior = _prior_characteristics(row, daily, market_returns, history_window, minimum_history)
        sector_relative = (
            _num(row["cutoff_return_from_open"]) - _num(row["sector_early_return"])
            if int(row["sector_company_count"]) >= 2
            else np.nan
        )
        cluster_relative = (
            _num(row["cutoff_return_from_open"]) - _num(row["cluster_early_return"])
            if int(row["cluster_company_count"]) >= 2
            else np.nan
        )
        market_relative = _num(row["cutoff_return_from_open"]) - _num(row["market_early_return"])
        if int(row["sector_company_count"]) >= 2:
            reference = "BROAD_SECTOR"
            relative_used = sector_relative
        elif int(row["cluster_company_count"]) >= 2:
            reference = "ECONOMIC_CLUSTER"
            relative_used = cluster_relative
        else:
            reference = "COMPANY_WEIGHTED_MARKET_FALLBACK"
            relative_used = market_relative

        if pd.isna(relative_used):
            relative_state = "NOT_AVAILABLE"
        elif relative_used >= RELATIVE_STATE_THRESHOLD:
            relative_state = "EARLY_LEADER"
        elif relative_used <= -RELATIVE_STATE_THRESHOLD:
            relative_state = "EARLY_LAGGARD"
        else:
            relative_state = "EARLY_NEUTRAL"

        gap = _num(row["opening_gap_pct"])
        gap_state = "GAP_UNKNOWN"
        if pd.notna(gap):
            if gap >= 0.001:
                gap_state = "POSITIVE_GAP"
            elif gap <= -0.001:
                gap_state = "NEGATIVE_GAP"
            else:
                gap_state = "FLAT_GAP"

        prior_early_range = _num(prior["prior_20d_average_early_range_pct"])
        current_range = _num(row["early_range_pct"])
        if not bool(prior["minimum_history_ready"]) or pd.isna(prior_early_range) or prior_early_range <= 0:
            range_state = "NOT_READY"
        else:
            ratio = current_range / prior_early_range
            if ratio >= RANGE_EXPANSION_RATIO:
                range_state = "RANGE_EXPANDED"
            elif ratio <= RANGE_COMPRESSION_RATIO:
                range_state = "RANGE_COMPRESSED"
            else:
                range_state = "RANGE_NORMAL"

        same_day_label = _normalize_source_label(row.get("max_same_day_source_label"))
        prior_max = prior["prior_history_max_date"]
        prior_safe = prior_max == "" or pd.Timestamp(prior_max).date() < pd.Timestamp(row["date"]).date()
        label_safe = bool(same_day_label) and same_day_label <= LATEST_ALLOWED_BAR_LABEL
        pit_pass = bool(prior_safe and label_safe)
        early_complete = bool(int(_num(row.get("early_bar_count"), 0)) >= 3 and pd.notna(row["cutoff_close"]))
        prev_available = bool(pd.notna(row["previous_close"]))
        static_complete = bool(pd.notna(row["company_id"]) and pd.notna(row["broad_sector"]))
        if pit_pass and static_complete and early_complete and prior["minimum_history_ready"]:
            char_status = "MINIMUM_READY"
        elif pit_pass and static_complete and early_complete:
            char_status = "CURRENT_STATE_READY_HISTORY_PARTIAL"
        else:
            char_status = "INCOMPLETE_REVIEW_REQUIRED"

        item = {
            "taxonomy_id": TAXONOMY_ID,
            "date": row["date"],
            "ticker": row["ticker"],
            "company_id": row["company_id"],
            "company_name": row["company_name"],
            "share_class_group": row["share_class_group"],
            "company_observation_weight": row["company_observation_weight"],
            "broad_sector": row["broad_sector"],
            "industry_group": row["industry_group"],
            "economic_cluster": row["economic_cluster"],
            "primary_peer_group": row["primary_peer_group"],
            "decision_time": DECISION_TIME,
            "latest_allowed_bar_label": LATEST_ALLOWED_BAR_LABEL,
            "previous_close": row["previous_close"],
            "open_price": row["open_price"],
            "cutoff_close": row["cutoff_close"],
            "opening_gap_pct": row["opening_gap_pct"],
            "cutoff_return_from_open": row["cutoff_return_from_open"],
            "early_range_pct": row["early_range_pct"],
            "market_return_from_open_company_weighted": row["market_early_return"],
            "sector_return_from_open_company_weighted": row["sector_early_return"],
            "economic_cluster_return_from_open_company_weighted": row["cluster_early_return"],
            "sector_independent_company_count": int(row["sector_company_count"]),
            "economic_cluster_independent_company_count": int(row["cluster_company_count"]),
            "sector_relative_return": sector_relative,
            "economic_cluster_relative_return": cluster_relative,
            "market_relative_return": market_relative,
            "relative_reference_used": reference,
            "relative_return_used": relative_used,
            "ticker_relative_state": relative_state,
            "gap_state": gap_state,
            **prior,
            "volatility_percentile_cross_section": np.nan,
            "volatility_bucket": "NOT_READY",
            "range_state": range_state,
            "max_same_day_source_label": same_day_label,
            "point_in_time_pass": pit_pass,
            "characteristic_status": char_status,
        }
        characteristic_rows.append(item)

        reason = []
        if not static_complete:
            reason.append("STATIC_METADATA_MISSING")
        if not early_complete:
            reason.append("STRICT_EARLY_BARS_INCOMPLETE")
        if not prev_available:
            reason.append("PREVIOUS_CLOSE_MISSING")
        if not prior["minimum_history_ready"]:
            reason.append("MINIMUM_PRIOR_HISTORY_NOT_AVAILABLE")
        if not pit_pass:
            reason.append("POINT_IN_TIME_AUDIT_FAIL")
        completeness_rows.append(
            {
                "taxonomy_id": TAXONOMY_ID,
                "date": row["date"],
                "ticker": row["ticker"],
                "static_metadata_complete": static_complete,
                "early_data_complete": early_complete,
                "previous_close_available": prev_available,
                "prior_history_sessions": prior["prior_history_sessions"],
                "minimum_history_ready": prior["minimum_history_ready"],
                "full_history_ready": prior["full_history_ready"],
                "sector_independent_company_count": int(row["sector_company_count"]),
                "economic_cluster_independent_company_count": int(row["cluster_company_count"]),
                "same_company_symbol_count": int(static[static["company_id"].eq(row["company_id"])]["ticker"].nunique()),
                "company_weight": row["company_observation_weight"],
                "point_in_time_pass": pit_pass,
                "completeness_status": char_status,
                "excluded_or_partial_reason": "|".join(reason) if reason else "NONE",
            }
        )
        audit_rows.append(
            {
                "taxonomy_id": TAXONOMY_ID,
                "audit_date": row["date"],
                "ticker": row["ticker"],
                "audit_group": "TICKER_POINT_IN_TIME_CHARACTERISTICS",
                "source_scope": "CURRENT_STRICT_EARLY_AND_PRIOR_COMPLETED_SESSIONS",
                "max_source_date": prior_max,
                "max_source_label": same_day_label,
                "allowed_source_date_rule": "HISTORICAL_SOURCE_DATE_STRICTLY_BEFORE_CURRENT_DATE",
                "allowed_source_label": LATEST_ALLOWED_BAR_LABEL,
                "point_in_time_pass": pit_pass,
                "audit_status": "PASS" if pit_pass else "FAIL",
                "notes": "Current-day features stop at 09:40; historical tendencies exclude current date.",
            }
        )

    characteristics = pd.DataFrame(characteristic_rows, columns=CHARACTERISTIC_COLUMNS)
    for date, index in characteristics.groupby("date").groups.items():
        vol = characteristics.loc[index, "prior_20d_daily_volatility"]
        valid = vol.notna()
        if valid.any():
            ranks = vol[valid].rank(pct=True, method="average")
            characteristics.loc[ranks.index, "volatility_percentile_cross_section"] = ranks
            characteristics.loc[ranks.index[ranks.le(1/3)], "volatility_bucket"] = "LOW_RELATIVE_VOL"
            characteristics.loc[ranks.index[ranks.gt(1/3) & ranks.lt(2/3)], "volatility_bucket"] = "MEDIUM_RELATIVE_VOL"
            characteristics.loc[ranks.index[ranks.ge(2/3)], "volatility_bucket"] = "HIGH_RELATIVE_VOL"

    group_states = build_group_daily_state(daily)
    completeness = pd.DataFrame(completeness_rows, columns=COMPLETENESS_COLUMNS)
    audit = pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS)
    return characteristics, group_states, completeness, audit


def build_group_daily_state(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, day in daily.groupby("date", sort=True):
        market_return = _weighted_mean(day["cutoff_return_from_open"], day["company_observation_weight"])
        for level, column in [
            ("BROAD_SECTOR", "broad_sector"),
            ("ECONOMIC_CLUSTER", "economic_cluster"),
            ("PRIMARY_PEER_GROUP", "primary_peer_group"),
        ]:
            for name, group in day.groupby(column, sort=True):
                weights = group["company_observation_weight"]
                mean_return = _weighted_mean(group["cutoff_return_from_open"], weights)
                breadth = _weighted_mean(group["cutoff_return_from_open"].gt(0).astype(float), weights)
                company_count = int(group["company_id"].nunique())
                if pd.notna(mean_return) and mean_return >= 0.001 and breadth >= 0.60:
                    direction = "UP"
                elif pd.notna(mean_return) and mean_return <= -0.001 and breadth <= 0.40:
                    direction = "DOWN"
                else:
                    direction = "MIXED"
                max_source_label = _max_valid_source_label(group["max_same_day_source_label"])
                rows.append(
                    {
                        "taxonomy_id": TAXONOMY_ID,
                        "date": date,
                        "decision_time": DECISION_TIME,
                        "aggregation_level": level,
                        "group_name": name,
                        "ticker_count": int(group["ticker"].nunique()),
                        "independent_company_count": company_count,
                        "observed_ticker_count": int(group["cutoff_close"].notna().sum()),
                        "effective_company_weight": float(weights[group["cutoff_close"].notna()].sum()),
                        "mean_gap_company_weighted": _weighted_mean(group["opening_gap_pct"], weights),
                        "median_gap": float(group["opening_gap_pct"].median()) if group["opening_gap_pct"].notna().any() else np.nan,
                        "positive_gap_breadth_company_weighted": _weighted_mean(group["opening_gap_pct"].gt(0).astype(float), weights),
                        "mean_return_from_open_company_weighted": mean_return,
                        "median_return_from_open": float(group["cutoff_return_from_open"].median()),
                        "breadth_above_open_company_weighted": breadth,
                        "cross_sectional_return_dispersion": float(group["cutoff_return_from_open"].std(ddof=0)) if len(group) > 1 else 0.0,
                        "mean_early_range_pct_company_weighted": _weighted_mean(group["early_range_pct"], weights),
                        "market_return_from_open_company_weighted": market_return,
                        "group_relative_return_vs_market": mean_return - market_return if pd.notna(mean_return) and pd.notna(market_return) else np.nan,
                        "group_direction_state": direction,
                        "group_peer_status": "PEER_GROUP_READY" if company_count >= 2 else "SINGLE_COMPANY_PROXY",
                        "max_same_day_source_label": max_source_label,
                        "point_in_time_pass": bool(max_source_label) and max_source_label <= LATEST_ALLOWED_BAR_LABEL,
                    }
                )
    return pd.DataFrame(rows, columns=GROUP_STATE_COLUMNS)


def build_summary(
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    configured = set(static["ticker"])
    observed = set(characteristics["ticker"]) if not characteristics.empty else set()
    company_weight_sums = static.groupby("company_id")["company_observation_weight"].sum()
    weight_pass = bool(np.allclose(company_weight_sums.values, 1.0, atol=1e-12))
    duplicate_conflicts = int(
        static.groupby(["company_id", "share_class"])["ticker"].nunique().gt(1).sum()
    )
    static_mapping_complete = configured == set(GAP_RECOVERY_TICKERS) and observed.issubset(configured)
    audit_pass = int(audit["point_in_time_pass"].fillna(False).sum()) if not audit.empty else 0
    audit_rows = int(len(audit))
    future_source_rows = int((~audit["point_in_time_pass"].fillna(False)).sum()) if not audit.empty else 0
    mechanical_pass = bool(
        static_mapping_complete
        and weight_pass
        and duplicate_conflicts == 0
        and future_source_rows == 0
        and len(static) == len(GAP_RECOVERY_TICKERS)
    )
    classification = (
        "INSTRUMENT_TAXONOMY_READY_FOR_SECTOR_STRATEGY_EXPERIMENTS"
        if mechanical_pass
        else "INSTRUMENT_TAXONOMY_GAPS_REQUIRE_REVIEW"
    )
    summary = pd.DataFrame(
        [
            {
                "taxonomy_id": TAXONOMY_ID,
                "research_status": RESEARCH_STATUS,
                "decision_time": DECISION_TIME,
                "latest_allowed_bar_label": LATEST_ALLOWED_BAR_LABEL,
                "history_window_sessions": HISTORY_WINDOW,
                "minimum_history_sessions": MINIMUM_HISTORY_SESSIONS,
                "configured_tickers": len(static),
                "observed_tickers": len(observed),
                "independent_companies": static["company_id"].nunique(),
                "broad_sectors": static["broad_sector"].nunique(),
                "industry_groups": static["industry_group"].nunique(),
                "economic_clusters": static["economic_cluster"].nunique(),
                "primary_peer_groups": static["primary_peer_group"].nunique(),
                "observed_sessions": characteristics["date"].nunique() if not characteristics.empty else 0,
                "characteristic_rows": len(characteristics),
                "minimum_history_ready_rows": int(characteristics["minimum_history_ready"].fillna(False).sum()) if not characteristics.empty else 0,
                "full_history_ready_rows": int(characteristics["full_history_ready"].fillna(False).sum()) if not characteristics.empty else 0,
                "group_state_rows": len(group_states),
                "single_company_group_state_rows": int(group_states["group_peer_status"].eq("SINGLE_COMPANY_PROXY").sum()) if not group_states.empty else 0,
                "static_mapping_complete": static_mapping_complete,
                "company_weight_audit_pass": weight_pass,
                "point_in_time_audit_rows": audit_rows,
                "point_in_time_audit_pass_rows": audit_pass,
                "point_in_time_audit_fail_rows": audit_rows - audit_pass,
                "future_source_rows": future_source_rows,
                "duplicate_company_share_class_conflicts": duplicate_conflicts,
                "router_active": False,
                "classification": classification,
            }
        ],
        columns=SUMMARY_COLUMNS,
    )
    return summary


def build_outputs(prices: pd.DataFrame) -> tuple[pd.DataFrame, ...]:
    static = build_static_taxonomy()
    characteristics, group_states, completeness, audit = build_point_in_time_characteristics(prices, static)
    definitions = pd.DataFrame(DEFINITIONS, columns=DEFINITION_COLUMNS)
    constraints = pd.DataFrame(
        [{"taxonomy_id": TAXONOMY_ID, **row} for row in CONSTRAINTS],
        columns=CONSTRAINT_COLUMNS,
    )
    summary = build_summary(static, characteristics, group_states, audit)
    return summary, static, definitions, characteristics, group_states, completeness, constraints, audit


def main() -> None:
    print("\n=== STEP 9E INSTRUMENT, SECTOR AND TICKER-CHARACTERISTIC TAXONOMY ===")
    print(f"Taxonomy         : {TAXONOMY_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Decision time    : {DECISION_TIME}")
    print(f"Latest bar label : {LATEST_ALLOWED_BAR_LABEL}")
    print("Static business classifications are versioned research metadata.")
    print("Dynamic characteristics use only bars through 09:40 and completed prior sessions.")
    print("This step does not alter Step 9D trades, select strategies, or activate router rules.")

    prices = load_intraday_prices(INTRADAY_DB)
    outputs = build_outputs(prices)
    files = [
        SUMMARY_FILE, STATIC_FILE, DEFINITION_FILE, CHARACTERISTIC_FILE, GROUP_STATE_FILE,
        COMPLETENESS_FILE, CONSTRAINT_FILE, AUDIT_FILE,
    ]
    for dataframe, path in zip(outputs, files):
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")

    summary = outputs[0].iloc[0]
    print("\n=== STEP 9E INSTRUMENT TAXONOMY RESULT ===")
    print(f"Configured / observed tickers : {int(summary['configured_tickers'])}/{int(summary['observed_tickers'])}")
    print(f"Independent companies         : {int(summary['independent_companies'])}")
    print(f"Sectors / clusters / peers    : {int(summary['broad_sectors'])}/{int(summary['economic_clusters'])}/{int(summary['primary_peer_groups'])}")
    print(f"Observed sessions             : {int(summary['observed_sessions'])}")
    print(f"Point-in-time rows            : {int(summary['point_in_time_audit_pass_rows'])}/{int(summary['point_in_time_audit_rows'])}")
    print(f"Minimum/full history rows     : {int(summary['minimum_history_ready_rows'])}/{int(summary['full_history_ready_rows'])}")
    print(f"Company-weight audit pass     : {bool(summary['company_weight_audit_pass'])}")
    print(f"Future-source rows            : {int(summary['future_source_rows'])}")
    print(f"Router active                 : {bool(summary['router_active'])}")
    print(f"Classification                : {summary['classification']}")
    print("Step 9E export complete. Step 9F may consume this frozen taxonomy for structured sector/ticker experiments.")


if __name__ == "__main__":
    main()
