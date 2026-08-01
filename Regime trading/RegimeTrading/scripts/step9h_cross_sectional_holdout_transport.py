from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, MARKET_SOURCE_DIR, legacy_output_path
from RegimeTrading.scripts.research_regime_aware_gap_recovery import load_intraday_prices
from RegimeTrading.scripts import step9b_baseline_trade_generation as step9b
from RegimeTrading.scripts import step9e_instrument_sector_taxonomy as step9e
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g


EXPERIMENT_ID = "LOCKED_CROSS_SECTIONAL_HOLDOUT_TRANSPORT_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_LOCKED_CROSS_SECTIONAL_HOLDOUT_NOT_ROUTER_ACTIVE"
HOLDOUT_LOCK_VERSION = "STOCKHOLM_HOLDOUT_UNIVERSE_V1_LOCKED_2026_07_24"
HOLDOUT_DB = MARKET_SOURCE_DIR / "step9h_holdout_intraday_prices.db"
TAXONOMY_FILE = legacy_output_path("regime_daily_taxonomy.csv")
DISCOVERY_PERFORMANCE_FILE = legacy_output_path("regime_state_filtered_performance.csv")

MIN_CONFIRMATORY_TRADES = 20
MIN_CONFIRMATORY_SESSIONS = 10
MIN_CONFIRMATORY_COMPANIES = 8
MIN_CONFIRMATORY_SECTORS = 3
COMPANY_BOOTSTRAP_ITERATIONS = 5000
RANDOM_SEED = 9173

SUMMARY_FILE = legacy_output_path("regime_holdout_transport_summary.csv")
UNIVERSE_FILE = legacy_output_path("regime_holdout_universe_registry.csv")
DATA_COVERAGE_FILE = legacy_output_path("regime_holdout_data_coverage.csv")
CHARACTERISTIC_FILE = legacy_output_path("regime_holdout_point_in_time_characteristics.csv")
GROUP_STATE_FILE = legacy_output_path("regime_holdout_group_daily_state.csv")
REGISTRY_FILE = legacy_output_path("regime_holdout_contract_registry.csv")
SESSION_FILE = legacy_output_path("regime_holdout_session_coverage.csv")
CANDIDATE_FILE = legacy_output_path("regime_holdout_candidates.csv")
TRADE_FILE = legacy_output_path("regime_holdout_trades.csv")
LEG_FILE = legacy_output_path("regime_holdout_trade_legs.csv")
PERFORMANCE_FILE = legacy_output_path("regime_holdout_performance.csv")
COMPARISON_FILE = legacy_output_path("regime_holdout_comparisons.csv")
ROBUSTNESS_FILE = legacy_output_path("regime_holdout_robustness.csv")
MULTIPLE_TESTING_FILE = legacy_output_path("regime_holdout_multiple_testing.csv")
AUDIT_FILE = legacy_output_path("regime_holdout_audit.csv")


# Locked before any Step 9H outcomes are observed. The list deliberately expands
# the cross-section across industries while excluding all ten discovery companies.
HOLDOUT_INSTRUMENTS = [
    dict(ticker="ABB.ST", company_id="ABB", company_name="ABB Ltd", share_class_group="ABB", share_class="REGISTERED", broad_sector="INDUSTRIALS", industry_group="ELECTRIFICATION_AND_AUTOMATION", economic_cluster="INDUSTRIAL_CYCLICAL_EXPORT", primary_peer_group="LARGE_INDUSTRIALS", cyclical_profile="HIGH", rate_sensitivity="MEDIUM", commodity_sensitivity="LOW", export_sensitivity="HIGH", defensive_profile="LOW", regulatory_sensitivity="LOW", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="abb.com"),
    dict(ticker="ASSA-B.ST", company_id="ASSA_ABLOY", company_name="ASSA ABLOY AB", share_class_group="ASSA_ABLOY", share_class="B", broad_sector="INDUSTRIALS", industry_group="BUILDING_PRODUCTS", economic_cluster="INDUSTRIAL_CYCLICAL_EXPORT", primary_peer_group="LARGE_INDUSTRIALS", cyclical_profile="MEDIUM", rate_sensitivity="MEDIUM", commodity_sensitivity="LOW", export_sensitivity="HIGH", defensive_profile="MEDIUM", regulatory_sensitivity="LOW", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="assaabloy.com"),
    dict(ticker="VOLV-B.ST", company_id="VOLVO_GROUP", company_name="AB Volvo", share_class_group="VOLVO_GROUP", share_class="B", broad_sector="INDUSTRIALS", industry_group="COMMERCIAL_VEHICLES", economic_cluster="INDUSTRIAL_CYCLICAL_EXPORT", primary_peer_group="LARGE_INDUSTRIALS", cyclical_profile="HIGH", rate_sensitivity="MEDIUM", commodity_sensitivity="MEDIUM", export_sensitivity="HIGH", defensive_profile="LOW", regulatory_sensitivity="MEDIUM", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="volvogroup.com"),
    dict(ticker="SKF-B.ST", company_id="SKF", company_name="AB SKF", share_class_group="SKF", share_class="B", broad_sector="INDUSTRIALS", industry_group="INDUSTRIAL_COMPONENTS", economic_cluster="INDUSTRIAL_CYCLICAL_EXPORT", primary_peer_group="LARGE_INDUSTRIALS", cyclical_profile="HIGH", rate_sensitivity="MEDIUM", commodity_sensitivity="MEDIUM", export_sensitivity="HIGH", defensive_profile="LOW", regulatory_sensitivity="LOW", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="skf.com"),
    dict(ticker="NDA-SE.ST", company_id="NORDEA", company_name="Nordea Bank Abp", share_class_group="NORDEA", share_class="ORDINARY", broad_sector="FINANCIALS", industry_group="BANKS", economic_cluster="FINANCIAL_RATE_SENSITIVE", primary_peer_group="NORDIC_BANKS", cyclical_profile="MEDIUM", rate_sensitivity="HIGH", commodity_sensitivity="LOW", export_sensitivity="MEDIUM", defensive_profile="MEDIUM", regulatory_sensitivity="HIGH", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="nordea.com"),
    dict(ticker="INVE-B.ST", company_id="INVESTOR_AB", company_name="Investor AB", share_class_group="INVESTOR_AB", share_class="B", broad_sector="FINANCIALS", industry_group="INVESTMENT_COMPANIES", economic_cluster="DIVERSIFIED_EQUITY_HOLDINGS", primary_peer_group="INVESTMENT_HOLDINGS", cyclical_profile="MEDIUM", rate_sensitivity="MEDIUM", commodity_sensitivity="LOW", export_sensitivity="HIGH", defensive_profile="MEDIUM", regulatory_sensitivity="MEDIUM", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="investorab.com"),
    dict(ticker="SOBI.ST", company_id="SOBI", company_name="Swedish Orphan Biovitrum AB", share_class_group="SOBI", share_class="ORDINARY", broad_sector="HEALTH_CARE", industry_group="BIOPHARMACEUTICALS", economic_cluster="HEALTHCARE_DEFENSIVE_GLOBAL", primary_peer_group="SWEDISH_HEALTHCARE", cyclical_profile="LOW", rate_sensitivity="LOW", commodity_sensitivity="LOW", export_sensitivity="HIGH", defensive_profile="HIGH", regulatory_sensitivity="HIGH", idiosyncratic_event_sensitivity="HIGH", liquidity_assumption="LARGE_MID_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="sobi.com"),
    dict(ticker="GETI-B.ST", company_id="GETINGE", company_name="Getinge AB", share_class_group="GETINGE", share_class="B", broad_sector="HEALTH_CARE", industry_group="MEDICAL_TECHNOLOGY", economic_cluster="HEALTHCARE_DEFENSIVE_GLOBAL", primary_peer_group="SWEDISH_HEALTHCARE", cyclical_profile="LOW", rate_sensitivity="LOW", commodity_sensitivity="LOW", export_sensitivity="HIGH", defensive_profile="HIGH", regulatory_sensitivity="HIGH", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="LARGE_MID_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="getinge.com"),
    dict(ticker="ESSITY-B.ST", company_id="ESSITY", company_name="Essity AB", share_class_group="ESSITY", share_class="B", broad_sector="CONSUMER_STAPLES", industry_group="PERSONAL_CARE_AND_HYGIENE", economic_cluster="DEFENSIVE_CONSUMER_HEALTH", primary_peer_group="DEFENSIVE_CONSUMER", cyclical_profile="LOW", rate_sensitivity="LOW", commodity_sensitivity="MEDIUM", export_sensitivity="HIGH", defensive_profile="HIGH", regulatory_sensitivity="MEDIUM", idiosyncratic_event_sensitivity="LOW", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="essity.com"),
    dict(ticker="HM-B.ST", company_id="H_AND_M", company_name="H & M Hennes & Mauritz AB", share_class_group="H_AND_M", share_class="B", broad_sector="CONSUMER_DISCRETIONARY", industry_group="APPAREL_RETAIL", economic_cluster="CONSUMER_CYCLICAL_GLOBAL", primary_peer_group="CONSUMER_CYCLICALS", cyclical_profile="HIGH", rate_sensitivity="MEDIUM", commodity_sensitivity="MEDIUM", export_sensitivity="HIGH", defensive_profile="LOW", regulatory_sensitivity="MEDIUM", idiosyncratic_event_sensitivity="HIGH", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="hmgroup.com"),
    dict(ticker="ELUX-B.ST", company_id="ELECTROLUX", company_name="AB Electrolux", share_class_group="ELECTROLUX", share_class="B", broad_sector="CONSUMER_DISCRETIONARY", industry_group="HOUSEHOLD_APPLIANCES", economic_cluster="CONSUMER_CYCLICAL_GLOBAL", primary_peer_group="CONSUMER_CYCLICALS", cyclical_profile="HIGH", rate_sensitivity="HIGH", commodity_sensitivity="MEDIUM", export_sensitivity="HIGH", defensive_profile="LOW", regulatory_sensitivity="MEDIUM", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="LARGE_MID_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="electroluxgroup.com"),
    dict(ticker="TEL2-B.ST", company_id="TELE2", company_name="Tele2 AB", share_class_group="TELE2", share_class="B", broad_sector="COMMUNICATION_SERVICES", industry_group="TELECOM_OPERATORS", economic_cluster="DOMESTIC_DEFENSIVE_TELECOM", primary_peer_group="TELECOM_OPERATORS", cyclical_profile="LOW", rate_sensitivity="MEDIUM", commodity_sensitivity="LOW", export_sensitivity="LOW", defensive_profile="HIGH", regulatory_sensitivity="HIGH", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="tele2.com"),
    dict(ticker="TELIA.ST", company_id="TELIA", company_name="Telia Company AB", share_class_group="TELIA", share_class="ORDINARY", broad_sector="COMMUNICATION_SERVICES", industry_group="TELECOM_OPERATORS", economic_cluster="DOMESTIC_DEFENSIVE_TELECOM", primary_peer_group="TELECOM_OPERATORS", cyclical_profile="LOW", rate_sensitivity="MEDIUM", commodity_sensitivity="LOW", export_sensitivity="LOW", defensive_profile="HIGH", regulatory_sensitivity="HIGH", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="teliacompany.com"),
    dict(ticker="HEXA-B.ST", company_id="HEXAGON", company_name="Hexagon AB", share_class_group="HEXAGON", share_class="B", broad_sector="INFORMATION_TECHNOLOGY", industry_group="INDUSTRIAL_SOFTWARE_AND_SENSORS", economic_cluster="TECHNOLOGY_EXPORT_CYCLICAL", primary_peer_group="TECH_EXPORT", cyclical_profile="MEDIUM", rate_sensitivity="MEDIUM", commodity_sensitivity="LOW", export_sensitivity="HIGH", defensive_profile="LOW", regulatory_sensitivity="LOW", idiosyncratic_event_sensitivity="HIGH", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="hexagon.com"),
    dict(ticker="SSAB-A.ST", company_id="SSAB", company_name="SSAB AB", share_class_group="SSAB", share_class="A", broad_sector="MATERIALS", industry_group="STEEL", economic_cluster="MATERIALS_COMMODITY_CYCLICAL", primary_peer_group="METALS_AND_MATERIALS", cyclical_profile="HIGH", rate_sensitivity="MEDIUM", commodity_sensitivity="HIGH", export_sensitivity="HIGH", defensive_profile="LOW", regulatory_sensitivity="HIGH", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="ssab.com"),
    dict(ticker="SCA-B.ST", company_id="SCA", company_name="Svenska Cellulosa Aktiebolaget SCA", share_class_group="SCA", share_class="B", broad_sector="MATERIALS", industry_group="FOREST_PRODUCTS", economic_cluster="MATERIALS_COMMODITY_CYCLICAL", primary_peer_group="METALS_AND_MATERIALS", cyclical_profile="MEDIUM", rate_sensitivity="MEDIUM", commodity_sensitivity="HIGH", export_sensitivity="HIGH", defensive_profile="MEDIUM", regulatory_sensitivity="HIGH", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="CORE_LARGE_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="sca.com"),
    dict(ticker="CAST.ST", company_id="CASTELLUM", company_name="Castellum AB", share_class_group="CASTELLUM", share_class="ORDINARY", broad_sector="REAL_ESTATE", industry_group="COMMERCIAL_REAL_ESTATE", economic_cluster="REAL_ESTATE_RATE_SENSITIVE", primary_peer_group="SWEDISH_REAL_ESTATE", cyclical_profile="MEDIUM", rate_sensitivity="HIGH", commodity_sensitivity="LOW", export_sensitivity="LOW", defensive_profile="MEDIUM", regulatory_sensitivity="MEDIUM", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="LARGE_MID_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="castellum.com"),
    dict(ticker="FABG.ST", company_id="FABEGE", company_name="Fabege AB", share_class_group="FABEGE", share_class="ORDINARY", broad_sector="REAL_ESTATE", industry_group="COMMERCIAL_REAL_ESTATE", economic_cluster="REAL_ESTATE_RATE_SENSITIVE", primary_peer_group="SWEDISH_REAL_ESTATE", cyclical_profile="MEDIUM", rate_sensitivity="HIGH", commodity_sensitivity="LOW", export_sensitivity="LOW", defensive_profile="MEDIUM", regulatory_sensitivity="MEDIUM", idiosyncratic_event_sensitivity="MEDIUM", liquidity_assumption="LARGE_MID_CAP", shortability_assumption="RESEARCH_ASSUMED_SHORTABLE", classification_source_domain="fabege.se"),
]


# Three fixed confirmatory primaries, one exact execution comparator, two state
# complements, and two negative guardrails. No contract may be added after data review.
CONTRACTS = [
    dict(contract_id="H_TU_RANGE_REJECTION_V1", test_role="PRIMARY_HYPOTHESIS", primary_regime="TREND_UP", base_challenger_id="RANGE_REJECTION_REVERSION_1_25R_V1", cohort_id="H_TU_ALL_HOLDOUT", comparison_group="H_TU_RANGE_REJECTION", ticker_relative_states="ANY", volatility_buckets="ANY", sector_alignment_states="ANY", hypothesis="TREND_UP supports range-rejection entries across unseen companies.", economic_interpretation="Supportive market environment with stock-level rejection rather than breakout chasing."),
    dict(contract_id="H_VE_ALIGNED_EARLY_CONTINUATION_V1", test_role="PRIMARY_HYPOTHESIS", primary_regime="VOLATILITY_EXPANSION", base_challenger_id="EARLY_MOVE_CONTINUATION_1_5R_V1", cohort_id="H_VE_GROUP_ALIGNED", comparison_group="H_VE_ALIGNMENT", ticker_relative_states="ANY", volatility_buckets="ANY", sector_alignment_states="ALIGNED_WITH_GROUP", hypothesis="During volatility expansion, an early move confirmed by its group continues in unseen companies.", economic_interpretation="Cross-sectional confirmation validates the directional move."),
    dict(contract_id="H_RLV_LAGGARD_HIGH_REL_VOL_DELAYED_REVERSAL_V1", test_role="PRIMARY_HYPOTHESIS", primary_regime="RANGE_LOW_VOL", base_challenger_id="DELAYED_EARLY_MOVE_REVERSAL_1R_V1", cohort_id="H_RLV_LAGGARD_DELAYED_REV", comparison_group="H_RLV_HIGH_VS_NOT_HIGH", ticker_relative_states="EARLY_LAGGARD", volatility_buckets="HIGH_RELATIVE_VOL", sector_alignment_states="ANY", hypothesis="A high-relative-volatility laggard reverses after delayed confirmation in a quiet market.", economic_interpretation="Idiosyncratic dislocation inside a quiet broad environment."),
    dict(contract_id="H_VE_CONTRARIAN_EARLY_CONTINUATION_CONTROL_V1", test_role="COMPLEMENT_CONTROL", primary_regime="VOLATILITY_EXPANSION", base_challenger_id="EARLY_MOVE_CONTINUATION_1_5R_V1", cohort_id="H_VE_GROUP_CONTRARIAN", comparison_group="H_VE_ALIGNMENT", ticker_relative_states="ANY", volatility_buckets="ANY", sector_alignment_states="CONTRARIAN_TO_GROUP", hypothesis="Complement to group-aligned volatility-expansion continuation.", economic_interpretation="Tests whether continuation fails without group confirmation."),
    dict(contract_id="H_RLV_LAGGARD_NOT_HIGH_VOL_DELAYED_REVERSAL_CONTROL_V1", test_role="COMPLEMENT_CONTROL", primary_regime="RANGE_LOW_VOL", base_challenger_id="DELAYED_EARLY_MOVE_REVERSAL_1R_V1", cohort_id="H_RLV_LAGGARD_DELAYED_REV", comparison_group="H_RLV_HIGH_VS_NOT_HIGH", ticker_relative_states="EARLY_LAGGARD", volatility_buckets="LOW_RELATIVE_VOL|MEDIUM_RELATIVE_VOL", sector_alignment_states="ANY", hypothesis="Complement to the high-relative-volatility delayed-reversal contract.", economic_interpretation="Tests whether high relative volatility is the separating condition."),
    dict(contract_id="H_VE_ALIGNED_CLOSE_CONFIRMED_ORB_COMPARATOR_V1", test_role="EXECUTION_COMPARATOR", primary_regime="VOLATILITY_EXPANSION", base_challenger_id="ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1", cohort_id="H_VE_GROUP_ALIGNED", comparison_group="H_VE_EXECUTION", ticker_relative_states="ANY", volatility_buckets="ANY", sector_alignment_states="ALIGNED_WITH_GROUP", hypothesis="Same-cohort execution comparator for aligned volatility expansion.", economic_interpretation="Tests whether later close confirmation improves transportability."),
    dict(contract_id="H_HD_EARLY_LEADER_CONTINUATION_GUARDRAIL_V1", test_role="NEGATIVE_GUARDRAIL", primary_regime="HIGH_DISPERSION", base_challenger_id="EARLY_MOVE_CONTINUATION_1_5R_V1", cohort_id="H_HD_EARLY_LEADER", comparison_group="H_NEGATIVE_GUARDRAILS", ticker_relative_states="EARLY_LEADER", volatility_buckets="ANY", sector_alignment_states="ANY", hypothesis="Early leaders during high dispersion should not be chased with continuation.", economic_interpretation="Transport test of a negative risk-exclusion rule."),
    dict(contract_id="H_RLV_ALIGNED_RANGE_REJECTION_GUARDRAIL_V1", test_role="NEGATIVE_GUARDRAIL", primary_regime="RANGE_LOW_VOL", base_challenger_id="RANGE_REJECTION_REVERSION_1_25R_V1", cohort_id="H_RLV_ALIGNED", comparison_group="H_NEGATIVE_GUARDRAILS", ticker_relative_states="ANY", volatility_buckets="ANY", sector_alignment_states="ALIGNED_WITH_GROUP", hypothesis="Range rejection aligned with the group should be avoided in range-low-volatility sessions.", economic_interpretation="Transport test of a negative risk-exclusion rule."),
]
CONTRACT_BY_ID = {row["contract_id"]: row for row in CONTRACTS}
COMPARISONS = [
    ("H_VE_ALIGNED_MINUS_CONTRARIAN", "H_VE_ALIGNED_EARLY_CONTINUATION_V1", "H_VE_CONTRARIAN_EARLY_CONTINUATION_CONTROL_V1", "STATE_COMPLEMENT"),
    ("H_RLV_HIGH_MINUS_NOT_HIGH_VOL", "H_RLV_LAGGARD_HIGH_REL_VOL_DELAYED_REVERSAL_V1", "H_RLV_LAGGARD_NOT_HIGH_VOL_DELAYED_REVERSAL_CONTROL_V1", "STATE_COMPLEMENT"),
    ("H_VE_EARLY_CONT_MINUS_CLOSE_ORB", "H_VE_ALIGNED_EARLY_CONTINUATION_V1", "H_VE_ALIGNED_CLOSE_CONFIRMED_ORB_COMPARATOR_V1", "SAME_COHORT_STRATEGY"),
]


PERFORMANCE_EXTRA_COLUMNS = [
    "independent_sectors", "company_cluster_bootstrap_ci_lower_95_sek",
    "company_cluster_bootstrap_ci_upper_95_sek", "company_cluster_bootstrap_probability_positive",
    "minimum_confirmatory_trades", "minimum_confirmatory_sessions", "minimum_confirmatory_companies",
    "minimum_confirmatory_sectors", "confirmatory_sample_ready", "transport_evidence_status",
    "universe_role", "holdout_lock_version",
]


def _bool(value: object) -> bool:
    return step9g._bool(value)


STRICT_EARLY_LABELS = {"09:30", "09:35", "09:40"}


def _strict_early_complete_keys(prices: pd.DataFrame) -> pd.DataFrame:
    """Return ticker-days containing every locked router-input bar label."""
    if prices.empty:
        return pd.DataFrame(columns=["date", "ticker"])
    frame = prices.copy()
    frame["date"] = frame["date"].astype(str)
    frame["clock"] = pd.to_datetime(frame["datetime"]).dt.strftime("%H:%M")
    early = frame[frame["clock"].isin(STRICT_EARLY_LABELS)].copy()
    rows = []
    for (date, ticker), group in early.groupby(["date", "ticker"], sort=True):
        if STRICT_EARLY_LABELS.issubset(set(group["clock"])):
            rows.append({"date": str(date), "ticker": str(ticker)})
    return pd.DataFrame(rows, columns=["date", "ticker"])


def _optional_text(value) -> str:
    """Return clean text while treating pandas missing scalars as absent."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def _future_source_violation(row: pd.Series) -> bool:
    current_date = pd.Timestamp(row.get("audit_date")).date()
    prior_text = _optional_text(row.get("max_source_date"))
    prior_future = False
    if prior_text:
        prior_future = pd.Timestamp(prior_text).date() >= current_date
    label = _optional_text(row.get("max_source_label"))
    allowed = _optional_text(row.get("allowed_source_label")) or step9e.LATEST_ALLOWED_BAR_LABEL
    label_future = bool(label) and label > allowed
    return bool(prior_future or label_future)


def build_holdout_static() -> pd.DataFrame:
    original_instruments = step9e.STATIC_INSTRUMENTS
    original_taxonomy = step9e.TAXONOMY_ID
    original_status = step9e.RESEARCH_STATUS
    try:
        step9e.STATIC_INSTRUMENTS = HOLDOUT_INSTRUMENTS
        step9e.TAXONOMY_ID = "INSTRUMENT_SECTOR_TICKER_TAXONOMY_V1_HOLDOUT_EXTENSION"
        step9e.RESEARCH_STATUS = RESEARCH_STATUS
        static = step9e.build_static_taxonomy()
    finally:
        step9e.STATIC_INSTRUMENTS = original_instruments
        step9e.TAXONOMY_ID = original_taxonomy
        step9e.RESEARCH_STATUS = original_status
    static["universe_role"] = "CROSS_SECTIONAL_HOLDOUT"
    static["holdout_lock_version"] = HOLDOUT_LOCK_VERSION
    static["locked_before_results"] = True
    static["discovery_company_overlap"] = False
    return static


def load_holdout_prices(db_path: Path = HOLDOUT_DB) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker", "date"])
    try:
        return load_intraday_prices(db_path)
    except Exception:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker", "date"])


def build_data_coverage(prices: pd.DataFrame, static: pd.DataFrame, taxonomy: pd.DataFrame) -> pd.DataFrame:
    taxonomy_dates = set(taxonomy["date"].astype(str)) if not taxonomy.empty else set()
    rows = []
    for item in static.to_dict("records"):
        ticker = item["ticker"]
        frame = prices[prices["ticker"].eq(ticker)].copy() if not prices.empty else pd.DataFrame()
        if not frame.empty:
            frame["date_str"] = frame["date"].astype(str)
            frame["clock"] = pd.to_datetime(frame["datetime"]).dt.strftime("%H:%M")
            sessions = int(frame["date_str"].nunique())
            overlap = frame[frame["date_str"].isin(taxonomy_dates)]
            overlap_sessions = int(overlap["date_str"].nunique())
            early_counts = overlap[overlap["clock"].between("09:30", "09:40")].groupby("date_str")["clock"].nunique()
            early_complete = int((early_counts >= 3).sum())
            first_dt = str(frame["datetime"].min())
            last_dt = str(frame["datetime"].max())
        else:
            sessions = overlap_sessions = early_complete = 0
            first_dt = last_dt = ""
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            "holdout_lock_version": HOLDOUT_LOCK_VERSION,
            "ticker": ticker,
            "company_id": item["company_id"],
            "broad_sector": item["broad_sector"],
            "bars": int(len(frame)),
            "observed_sessions": sessions,
            "taxonomy_overlap_sessions": overlap_sessions,
            "strict_early_complete_overlap_sessions": early_complete,
            "first_datetime": first_dt,
            "last_datetime": last_dt,
            "data_present": not frame.empty,
            "minimum_history_possible": sessions >= step9e.MINIMUM_HISTORY_SESSIONS + 1,
            "coverage_status": "READY_FOR_TRANSPORT_CALCULATION" if early_complete >= 5 else "DATA_ACCUMULATION_REQUIRED",
        })
    return pd.DataFrame(rows)


def _company_cluster_bootstrap(trades: pd.DataFrame, iterations: int = COMPANY_BOOTSTRAP_ITERATIONS, seed: int = RANDOM_SEED) -> tuple[float, float, float]:
    if trades.empty or "company_id" not in trades:
        return np.nan, np.nan, np.nan
    company_pnl = trades.groupby("company_id")["risk_capped_net_pnl_sek"].sum().dropna()
    if company_pnl.empty:
        return np.nan, np.nan, np.nan
    values = company_pnl.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    sampled = values[rng.integers(0, len(values), size=(iterations, len(values)))].sum(axis=1)
    return float(np.quantile(sampled, 0.025)), float(np.quantile(sampled, 0.975)), float(np.mean(sampled > 0))


@contextmanager
def _patched_step9g_globals():
    names = ["EXPERIMENT_ID", "RESEARCH_STATUS", "CONTRACTS", "CONTRACT_BY_ID", "COMPARISONS"]
    old = {name: getattr(step9g, name) for name in names}
    original_step9b_tickers = list(step9b.GAP_RECOVERY_TICKERS)
    holdout_tickers = [row["ticker"] for row in HOLDOUT_INSTRUMENTS]
    try:
        step9g.EXPERIMENT_ID = EXPERIMENT_ID
        step9g.RESEARCH_STATUS = RESEARCH_STATUS
        step9g.CONTRACTS = CONTRACTS
        step9g.CONTRACT_BY_ID = CONTRACT_BY_ID
        step9g.COMPARISONS = COMPARISONS
        # build_market_state is imported from Step 9B and resolves its ticker
        # whitelist in the Step 9B module namespace. Temporarily inject the
        # locked holdout universe so unseen companies reach eligibility.
        step9b.GAP_RECOVERY_TICKERS = holdout_tickers
        yield
    finally:
        step9b.GAP_RECOVERY_TICKERS = original_step9b_tickers
        for name, value in old.items():
            setattr(step9g, name, value)


def _empty_core_outputs(static: pd.DataFrame):
    registry_rows = []
    for contract in CONTRACTS:
        challenger = step9g.CHALLENGER_BY_ID[contract["base_challenger_id"]]
        registry_rows.append({
            "experiment_id": EXPERIMENT_ID, **contract,
            "strategy_family": challenger["strategy_family"], "pre_registered": True,
            "router_active": False, "promotion_eligible": False,
        })
    registry = pd.DataFrame(registry_rows, columns=step9g.REGISTRY_COLUMNS)
    return (
        registry,
        pd.DataFrame(columns=step9g.SESSION_COLUMNS),
        pd.DataFrame(columns=step9g.CANDIDATE_COLUMNS),
        pd.DataFrame(columns=step9g.TRADE_COLUMNS),
        pd.DataFrame(columns=step9g.LEG_COLUMNS),
        pd.DataFrame(columns=step9g.PERFORMANCE_COLUMNS + PERFORMANCE_EXTRA_COLUMNS),
        pd.DataFrame(columns=step9g.COMPARISON_COLUMNS),
        pd.DataFrame(columns=step9g.ROBUSTNESS_COLUMNS),
        pd.DataFrame(columns=step9g.MULTIPLE_TESTING_COLUMNS),
        pd.DataFrame(columns=step9g.AUDIT_COLUMNS),
    )


def enrich_performance(performance: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    if performance.empty:
        return pd.DataFrame(columns=step9g.PERFORMANCE_COLUMNS + PERFORMANCE_EXTRA_COLUMNS)
    result = performance.copy()
    result["independent_sectors"] = 0
    result["company_cluster_bootstrap_ci_lower_95_sek"] = np.nan
    result["company_cluster_bootstrap_ci_upper_95_sek"] = np.nan
    result["company_cluster_bootstrap_probability_positive"] = np.nan
    for idx, row in result.iterrows():
        group = trades[trades["contract_id"].eq(row["contract_id"])] if not trades.empty else trades
        sectors = int(group["broad_sector"].replace("", np.nan).nunique()) if not group.empty else 0
        low, high, prob = _company_cluster_bootstrap(group, seed=RANDOM_SEED + idx)
        result.loc[idx, "independent_sectors"] = sectors
        result.loc[idx, "company_cluster_bootstrap_ci_lower_95_sek"] = low
        result.loc[idx, "company_cluster_bootstrap_ci_upper_95_sek"] = high
        result.loc[idx, "company_cluster_bootstrap_probability_positive"] = prob
    result["minimum_confirmatory_trades"] = MIN_CONFIRMATORY_TRADES
    result["minimum_confirmatory_sessions"] = MIN_CONFIRMATORY_SESSIONS
    result["minimum_confirmatory_companies"] = MIN_CONFIRMATORY_COMPANIES
    result["minimum_confirmatory_sectors"] = MIN_CONFIRMATORY_SECTORS
    result["confirmatory_sample_ready"] = (
        result["trades"].ge(MIN_CONFIRMATORY_TRADES)
        & result["sessions_with_trades"].ge(MIN_CONFIRMATORY_SESSIONS)
        & result["independent_companies"].ge(MIN_CONFIRMATORY_COMPANIES)
        & result["independent_sectors"].ge(MIN_CONFIRMATORY_SECTORS)
    )
    result["transport_evidence_status"] = np.select(
        [
            ~result["confirmatory_sample_ready"],
            result["test_role"].eq("NEGATIVE_GUARDRAIL") & result["net_pnl_risk_capped_sek"].lt(0),
            result["test_role"].eq("PRIMARY_HYPOTHESIS") & result["bh_adjusted_q_value_primary_family"].lt(0.10),
            result["test_role"].eq("PRIMARY_HYPOTHESIS") & result["net_pnl_risk_capped_sek"].gt(0),
        ],
        [
            "LOCKED_SAMPLE_ACCUMULATING",
            "NEGATIVE_GUARDRAIL_TRANSPORTS",
            "PRIMARY_BH_SIGNAL_CONFIRMATORY_REVIEW_ONLY",
            "PRIMARY_POSITIVE_NO_MULTIPLICITY_SIGNAL",
        ],
        default="NO_TRANSPORT_SIGNAL",
    )
    result["universe_role"] = "CROSS_SECTIONAL_HOLDOUT"
    result["holdout_lock_version"] = HOLDOUT_LOCK_VERSION
    return result[step9g.PERFORMANCE_COLUMNS + PERFORMANCE_EXTRA_COLUMNS]


def build_summary(
    static: pd.DataFrame,
    coverage: pd.DataFrame,
    taxonomy: pd.DataFrame,
    characteristics: pd.DataFrame,
    registry: pd.DataFrame,
    sessions: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    performance: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    observed = int(coverage["data_present"].map(_bool).sum()) if not coverage.empty else 0
    overlap_sessions = int(coverage["taxonomy_overlap_sessions"].max()) if not coverage.empty else 0
    audit_pass = bool(audit["audit_pass"].map(_bool).all()) if not audit.empty else True
    ready_contracts = int(performance["confirmatory_sample_ready"].map(_bool).sum()) if not performance.empty else 0
    if observed < MIN_CONFIRMATORY_COMPANIES or overlap_sessions < 5:
        classification = "HOLDOUT_DATA_COLLECTION_REQUIRED"
    elif ready_contracts == 0:
        classification = "LOCKED_HOLDOUT_SAMPLE_ACCUMULATING"
    elif audit_pass:
        classification = "CROSS_SECTIONAL_TRANSPORT_READY_FOR_CONFIRMATORY_REVIEW"
    else:
        classification = "CROSS_SECTIONAL_TRANSPORT_AUDIT_REVIEW_REQUIRED"
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")] if not performance.empty else performance
    return pd.DataFrame([{
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "holdout_lock_version": HOLDOUT_LOCK_VERSION,
        "configured_holdout_tickers": len(static),
        "configured_holdout_companies": int(static["company_id"].nunique()),
        "configured_holdout_sectors": int(static["broad_sector"].nunique()),
        "observed_holdout_tickers": observed,
        "taxonomy_sessions": int(taxonomy["date"].nunique()) if not taxonomy.empty else 0,
        "maximum_taxonomy_overlap_sessions": overlap_sessions,
        "point_in_time_characteristic_rows": int(len(characteristics)),
        "minimum_history_ready_rows": int(characteristics.get("minimum_history_ready", pd.Series(dtype=bool)).map(_bool).sum()) if not characteristics.empty else 0,
        "contracts_registered": int(len(registry)),
        "primary_hypotheses": int(registry["test_role"].eq("PRIMARY_HYPOTHESIS").sum()) if not registry.empty else 0,
        "session_contract_rows": int(len(sessions)),
        "eligible_ticker_rows": int(sessions.get("eligible_ticker_rows", pd.Series(dtype=float)).sum()) if not sessions.empty else 0,
        "valid_setup_rows": int(candidates.get("setup_status", pd.Series(dtype=str)).eq("VALID_SETUP").sum()) if not candidates.empty else 0,
        "triggered_closed_trades": int(len(trades)),
        "confirmatory_sample_ready_contracts": ready_contracts,
        "positive_primary_contracts": int(primary["net_pnl_risk_capped_sek"].gt(0).sum()) if not primary.empty else 0,
        "primary_bh_q_below_0_10": int(primary["bh_adjusted_q_value_primary_family"].lt(0.10).sum()) if not primary.empty else 0,
        "audit_pass": audit_pass,
        "strategies_promoted": 0,
        "router_active": False,
        "classification": classification,
    }])


def build_holdout_transport(
    taxonomy: pd.DataFrame,
    prices: pd.DataFrame,
    static: pd.DataFrame,
):
    coverage = build_data_coverage(prices, static, taxonomy)
    universe = static.copy()
    overlap_dates = set(taxonomy["date"].astype(str)) if not taxonomy.empty else set()
    if prices.empty:
        registry, sessions, candidates, trades, legs, performance, comparisons, robustness, multiple_testing, audit = _empty_core_outputs(static)
        characteristics = pd.DataFrame(columns=step9e.CHARACTERISTIC_COLUMNS)
        group_states = pd.DataFrame(columns=step9e.GROUP_STATE_COLUMNS)
    else:
        prices = prices[prices["ticker"].isin(static["ticker"])].copy()
        prices = prices[prices["date"].astype(str).isin(overlap_dates)].copy()
        if prices.empty:
            registry, sessions, candidates, trades, legs, performance, comparisons, robustness, multiple_testing, audit = _empty_core_outputs(static)
            characteristics = pd.DataFrame(columns=step9e.CHARACTERISTIC_COLUMNS)
            group_states = pd.DataFrame(columns=step9e.GROUP_STATE_COLUMNS)
        else:
            characteristics, _, _, taxonomy_audit = step9e.build_point_in_time_characteristics(prices, static)
            characteristics["date"] = characteristics["date"].astype(str)
            strict_keys = _strict_early_complete_keys(prices)
            execution_characteristics = characteristics.merge(
                strict_keys.assign(strict_early_complete=True),
                on=["date", "ticker"],
                how="inner",
                validate="one_to_one",
            ).drop(columns=["strict_early_complete"])

            # Sector confirmation is rebuilt from the same ticker-days that contain
            # the exact 09:30, 09:35 and 09:40 bars. Partial peers cannot influence
            # alignment states used by a locked contract.
            strict_daily = step9e._daily_input(prices, static)
            if not strict_daily.empty:
                strict_daily["date"] = strict_daily["date"].astype(str)
                strict_daily = strict_daily.merge(
                    strict_keys, on=["date", "ticker"], how="inner", validate="one_to_one"
                )
            group_states = (
                step9e.build_group_daily_state(strict_daily)
                if not strict_daily.empty
                else pd.DataFrame(columns=step9e.GROUP_STATE_COLUMNS)
            )

            valid_dates = sorted(set(taxonomy["date"].astype(str)).intersection(set(prices["date"].astype(str))))
            transport_taxonomy = taxonomy[taxonomy["date"].astype(str).isin(valid_dates)].copy()
            with _patched_step9g_globals():
                core = step9g.build_state_filtered_experiment(
                    transport_taxonomy, prices, static, execution_characteristics, group_states
                )
            _, registry, sessions, candidates, trades, legs, base_performance, comparisons, robustness, multiple_testing, audit = core
            performance = enrich_performance(base_performance, trades)
            if not multiple_testing.empty:
                multiple_testing = multiple_testing.copy()
                multiple_testing["multiplicity_family"] = "THREE_LOCKED_PRIMARY_HOLDOUT_CONTRACTS"
                multiple_testing["interpretation"] = (
                    "Locked cross-sectional holdout screen; neither raw nor adjusted significance promotes a strategy."
                )

            # Missing early labels are a completeness exclusion, not evidence of
            # look-ahead. Actual future-date or post-09:40 sources remain hard fails.
            future_fail = int(taxonomy_audit.apply(_future_source_violation, axis=1).sum()) if not taxonomy_audit.empty else 0
            all_keys = characteristics[["date", "ticker"]].copy()
            all_keys["date"] = all_keys["date"].astype(str)
            incomplete = all_keys.merge(strict_keys, on=["date", "ticker"], how="left", indicator=True)
            incomplete = incomplete[incomplete["_merge"].eq("left_only")][["date", "ticker"]]
            used_frames = []
            for frame in (candidates, trades):
                if not frame.empty:
                    keys = frame[["date", "ticker"]].copy()
                    keys["date"] = keys["date"].astype(str)
                    used_frames.append(keys)
            used_keys = (
                pd.concat(used_frames, ignore_index=True).drop_duplicates()
                if used_frames
                else pd.DataFrame(columns=["date", "ticker"])
            )
            incomplete_used = incomplete.merge(used_keys, on=["date", "ticker"], how="inner")
            audit = pd.concat([audit, pd.DataFrame([
                {
                    "experiment_id": EXPERIMENT_ID,
                    "audit_item": "HOLDOUT_TAXONOMY_FUTURE_LEAKAGE",
                    "rows_checked": len(taxonomy_audit),
                    "failures": future_fail,
                    "max_abs_difference": np.nan,
                    "audit_pass": future_fail == 0,
                    "interpretation": "Historical sources are strictly prior-date and same-day labels do not exceed 09:40; empty labels are handled as completeness exclusions.",
                },
                {
                    "experiment_id": EXPERIMENT_ID,
                    "audit_item": "HOLDOUT_STRICT_EARLY_COMPLETENESS_EXCLUSION",
                    "rows_checked": len(incomplete),
                    "failures": len(incomplete_used),
                    "max_abs_difference": np.nan,
                    "audit_pass": len(incomplete_used) == 0,
                    "interpretation": f"{len(incomplete)} ticker-days missing one or more exact 09:30/09:35/09:40 labels were excluded from contract eligibility and sector-state construction.",
                },
            ])], ignore_index=True)
    if performance.empty and not list(performance.columns):
        performance = pd.DataFrame(columns=step9g.PERFORMANCE_COLUMNS + PERFORMANCE_EXTRA_COLUMNS)
    summary = build_summary(static, coverage, taxonomy, characteristics, registry, sessions, candidates, trades, performance, audit)
    return (
        summary, universe, coverage, characteristics, group_states, registry, sessions,
        candidates, trades, legs, performance, comparisons, robustness, multiple_testing, audit,
    )


def run_holdout_transport(
    taxonomy_file: Path = TAXONOMY_FILE,
    holdout_db: Path = HOLDOUT_DB,
):
    if not taxonomy_file.exists():
        raise FileNotFoundError(f"Missing frozen Step 8 taxonomy: {taxonomy_file}")
    taxonomy = pd.read_csv(taxonomy_file)
    taxonomy["date"] = taxonomy["date"].astype(str)
    static = build_holdout_static()
    prices = load_holdout_prices(holdout_db)
    return build_holdout_transport(taxonomy, prices, static)


def main() -> None:
    print("\n=== STEP 9H LOCKED CROSS-SECTIONAL HOLDOUT TRANSPORT ===")
    print(f"Experiment       : {EXPERIMENT_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Universe lock    : {HOLDOUT_LOCK_VERSION}")
    print("Three primary contracts, fixed complements, one execution comparator, and two negative guardrails are locked before holdout outcomes.")
    print("The original regime taxonomy remains the market-environment source; holdout companies never redefine historical regimes.")
    print("The holdout database is separate from both production and the discovery database.")
    print("No parameter is optimized, no strategy is promoted, and incomplete data produces an accumulation status rather than a false conclusion.")

    outputs = run_holdout_transport()
    paths = [
        SUMMARY_FILE, UNIVERSE_FILE, DATA_COVERAGE_FILE, CHARACTERISTIC_FILE, GROUP_STATE_FILE,
        REGISTRY_FILE, SESSION_FILE, CANDIDATE_FILE, TRADE_FILE, LEG_FILE, PERFORMANCE_FILE,
        COMPARISON_FILE, ROBUSTNESS_FILE, MULTIPLE_TESTING_FILE, AUDIT_FILE,
    ]
    for dataframe, path in zip(outputs, paths):
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")

    summary = outputs[0].iloc[0]
    print("\n=== STEP 9H HOLDOUT TRANSPORT RESULT ===")
    print(f"Configured / observed tickers : {int(summary['configured_holdout_tickers'])}/{int(summary['observed_holdout_tickers'])}")
    print(f"Companies / sectors           : {int(summary['configured_holdout_companies'])}/{int(summary['configured_holdout_sectors'])}")
    print(f"Taxonomy / overlap sessions   : {int(summary['taxonomy_sessions'])}/{int(summary['maximum_taxonomy_overlap_sessions'])}")
    print(f"PIT characteristic rows       : {int(summary['point_in_time_characteristic_rows'])}")
    print(f"Contracts / primary           : {int(summary['contracts_registered'])}/{int(summary['primary_hypotheses'])}")
    print(f"Eligible rows / trades        : {int(summary['eligible_ticker_rows'])}/{int(summary['triggered_closed_trades'])}")
    print(f"Confirmatory-ready contracts  : {int(summary['confirmatory_sample_ready_contracts'])}")
    print(f"Strategies promoted           : {int(summary['strategies_promoted'])}")
    print(f"Router active                 : {bool(summary['router_active'])}")
    print(f"Classification                : {summary['classification']}")
    if summary["classification"] == "HOLDOUT_DATA_COLLECTION_REQUIRED":
        print("Next action: run .\\collect_step9h_holdout_data.ps1, then rerun this step. The collector upserts into a separate research-only database.")
    elif summary["classification"] == "LOCKED_HOLDOUT_SAMPLE_ACCUMULATING":
        print("The locked experiment is active, but the pre-declared company/session/trade thresholds are not yet met. Continue accumulating without changing rules.")
    else:
        print("The locked sample is large enough for controlled confirmatory review; results still do not activate the router.")


if __name__ == "__main__":
    main()
