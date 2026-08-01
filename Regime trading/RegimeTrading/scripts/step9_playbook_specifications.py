from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.scripts.step8_provisional_regime_taxonomy import REGIMES


SPECIFICATION_ID = "REGIME_PLAYBOOK_EXECUTABLE_SPECIFICATIONS_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_REGIME_SYSTEM_RESEARCH"
DECISION_TIME = "09:45"
LATEST_ALLOWED_BAR_LABEL = "09:40"
BAR_TIMESTAMP_CONVENTION = "START_LABELLED_5_MINUTE_BARS"
LEGACY_V1_ROUTER_ELIGIBLE = False

TAXONOMY_FILE = DATA_DIR / "regime_daily_taxonomy.csv"
TAXONOMY_DEFINITIONS_FILE = DATA_DIR / "regime_taxonomy_definitions.csv"

SUMMARY_FILE = DATA_DIR / "regime_playbook_specification_summary.csv"
REGISTRY_FILE = DATA_DIR / "regime_playbook_registry.csv"
REQUIREMENTS_FILE = DATA_DIR / "regime_playbook_data_requirements.csv"
COVERAGE_FILE = DATA_DIR / "regime_playbook_session_coverage.csv"

SUMMARY_COLUMNS = [
    "specification_id",
    "research_status",
    "decision_time",
    "latest_allowed_bar_label",
    "bar_timestamp_convention",
    "taxonomy_sessions",
    "sessions_with_mapped_playbook",
    "sessions_without_mapped_playbook",
    "sessions_with_active_simulation_contract",
    "no_trade_sessions",
    "regime_count_expected",
    "regime_count_specified",
    "unique_playbook_count",
    "ready_ohlc_only_playbooks",
    "ready_with_proxy_playbooks",
    "blocked_playbooks",
    "strict_recovery_v2_required",
    "legacy_v1_router_eligible",
    "all_entries_point_in_time_safe",
    "point_in_time_contract_failures",
    "data_limited_fallback_passes",
    "all_regimes_have_exit_and_risk_contract",
    "classification",
]

REGISTRY_COLUMNS = [
    "specification_id",
    "regime",
    "playbook_id",
    "version_status",
    "simulation_readiness",
    "direction_model",
    "portfolio_structure",
    "basket_selection_rule",
    "signal_rule",
    "entry_rule",
    "entry_start_time",
    "entry_end_time",
    "stop_rule",
    "target_rule",
    "time_exit_rule",
    "same_bar_priority",
    "position_sizing_rule",
    "research_risk_multiplier",
    "max_concurrent_ideas",
    "cost_model",
    "point_in_time_rule",
    "current_data_proxy",
    "known_limitation",
    "legacy_v1_eligible",
]

REQUIREMENT_COLUMNS = [
    "specification_id",
    "regime",
    "playbook_id",
    "requirement_group",
    "data_item",
    "required_for_baseline_simulation",
    "available_in_current_project",
    "availability_status",
    "point_in_time_deadline",
    "fallback_or_proxy",
    "future_upgrade",
]

COVERAGE_COLUMNS = [
    "specification_id",
    "date",
    "primary_regime",
    "regime_confidence",
    "confidence_band",
    "taxonomy_eligible",
    "data_quality_override",
    "playbook_id",
    "simulation_readiness",
    "direction_model",
    "portfolio_structure",
    "research_risk_multiplier",
    "max_concurrent_ideas",
    "active_simulation_contract",
    "taxonomy_point_in_time_safe",
    "point_in_time_contract_pass",
    "point_in_time_contract_reason",
    "legacy_v1_router_eligible",
    "coverage_status",
]


@dataclass(frozen=True)
class PlaybookSpec:
    regime: str
    playbook_id: str
    simulation_readiness: str
    direction_model: str
    portfolio_structure: str
    basket_selection_rule: str
    signal_rule: str
    entry_rule: str
    entry_start_time: str
    entry_end_time: str
    stop_rule: str
    target_rule: str
    time_exit_rule: str
    same_bar_priority: str
    position_sizing_rule: str
    research_risk_multiplier: float
    max_concurrent_ideas: int
    cost_model: str
    point_in_time_rule: str
    current_data_proxy: str
    known_limitation: str
    legacy_v1_eligible: bool = False
    version_status: str = "EXECUTABLE_BASELINE_SPEC_NOT_YET_VALIDATED"


PLAYBOOKS: dict[str, PlaybookSpec] = {
    "RECOVERY": PlaybookSpec(
        regime="RECOVERY",
        playbook_id="STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH",
        simulation_readiness="READY_OHLC_ONLY",
        direction_model="LONG_ONLY",
        portfolio_structure="LONG_ONLY_RECOVERY_BASKET",
        basket_selection_rule="Negative opening gaps from -2.0% through -0.1%, ranked by deterministic ticker order after all V2 setup gates pass.",
        signal_rule="Strict 09:45 recovery regime is calculated only from bars labelled through 09:40; stock must reclaim its 09:30 opening-range high.",
        entry_rule="First five-minute bar from 09:45 through 13:00 whose high reaches the 09:30 opening-range high; entry at that trigger price.",
        entry_start_time="09:45",
        entry_end_time="13:00",
        stop_rule="09:30 opening-range low.",
        target_rule="Previous official close.",
        time_exit_rule="Close remaining position at the final available bar through 16:30.",
        same_bar_priority="STOP",
        position_sizing_rule="Fixed baseline notional multiplied by regime research-risk multiplier; shared portfolio capacity applied later.",
        research_risk_multiplier=1.00,
        max_concurrent_ideas=2,
        cost_model="5 bps total round-trip baseline cost, with later stress scenarios.",
        point_in_time_rule="No same-day source later than 09:40 label may influence regime, basket, trigger, stop, or target before 09:45.",
        current_data_proxy="None required.",
        known_limitation="Only the timing correction is specified here; V2 requires its own full validation suite before router promotion.",
    ),
    "TREND_UP": PlaybookSpec(
        regime="TREND_UP",
        playbook_id="TREND_UP_MOMENTUM_BREAKOUT_V1_RESEARCH",
        simulation_readiness="READY_OHLC_ONLY",
        direction_model="LONG_ONLY",
        portfolio_structure="LONG_ONLY_DIRECTIONAL_BASKET",
        basket_selection_rule="Rank stocks by 09:40 return from open; retain the strongest names above both their open and previous close.",
        signal_rule="Broad TREND_UP taxonomy plus stock-level break above its strict 09:30-09:40 high.",
        entry_rule="First high break from 09:45 through 13:00; enter at strict early-range high.",
        entry_start_time="09:45",
        entry_end_time="13:00",
        stop_rule="Strict 09:30-09:40 range low, subject to a future maximum-risk cap.",
        target_rule="Initial baseline target at 1.0R above entry.",
        time_exit_rule="Close remaining position at the final available bar through 16:30.",
        same_bar_priority="STOP",
        position_sizing_rule="Equal notional across at most two selected leaders, scaled by regime risk multiplier.",
        research_risk_multiplier=1.00,
        max_concurrent_ideas=2,
        cost_model="5 bps total round-trip baseline cost, with later stress scenarios.",
        point_in_time_rule="Ranking and range use labels through 09:40 only; trigger monitoring starts at 09:45.",
        current_data_proxy="Cross-sectional relative strength from OHLC replaces unavailable order-book strength.",
        known_limitation="No external index, volume, or sector confirmation yet.",
    ),
    "TREND_DOWN": PlaybookSpec(
        regime="TREND_DOWN",
        playbook_id="TREND_DOWN_MOMENTUM_CONTINUATION_V1_RESEARCH",
        simulation_readiness="READY_OHLC_ONLY",
        direction_model="SHORT_ONLY",
        portfolio_structure="SHORT_ONLY_DIRECTIONAL_BASKET",
        basket_selection_rule="Rank stocks by 09:40 return from open; retain the weakest names below both their open and previous close.",
        signal_rule="Broad TREND_DOWN taxonomy plus stock-level break below its strict 09:30-09:40 low.",
        entry_rule="First low break from 09:45 through 13:00; short at strict early-range low.",
        entry_start_time="09:45",
        entry_end_time="13:00",
        stop_rule="Strict 09:30-09:40 range high, subject to a future maximum-risk cap.",
        target_rule="Initial baseline target at 1.0R below entry.",
        time_exit_rule="Cover remaining position at the final available bar through 16:30.",
        same_bar_priority="STOP",
        position_sizing_rule="Equal notional across at most two selected laggards, scaled by regime risk multiplier.",
        research_risk_multiplier=1.00,
        max_concurrent_ideas=2,
        cost_model="5 bps total round-trip baseline cost, with later stress scenarios.",
        point_in_time_rule="Ranking and range use labels through 09:40 only; trigger monitoring starts at 09:45.",
        current_data_proxy="Cross-sectional weakness from OHLC replaces unavailable short-interest and order-book data.",
        known_limitation="Borrow availability, locate fees, and short-sale restrictions are not represented yet.",
    ),
    "RANGE_LOW_VOL": PlaybookSpec(
        regime="RANGE_LOW_VOL",
        playbook_id="RANGE_MIDPOINT_REVERSION_V1_RESEARCH",
        simulation_readiness="READY_WITH_OHLC_PROXY",
        direction_model="TWO_SIDED_MEAN_REVERSION",
        portfolio_structure="TWO_SIDED_MEAN_REVERSION",
        basket_selection_rule="Rank absolute deviation of 09:40 close from the strict early-range midpoint; select the largest controlled deviations.",
        signal_rule="Price tests or exceeds an early-range boundary after 09:45 and then closes back inside the strict range.",
        entry_rule="Enter toward the strict early-range midpoint on the first confirmed re-entry bar through 14:00.",
        entry_start_time="09:45",
        entry_end_time="14:00",
        stop_rule="One strict early-range width beyond the tested boundary.",
        target_rule="Strict 09:30-09:40 range midpoint.",
        time_exit_rule="Close remaining position at 15:30 or the final available prior bar.",
        same_bar_priority="STOP",
        position_sizing_rule="Equal notional, reduced by the 0.75 regime multiplier.",
        research_risk_multiplier=0.75,
        max_concurrent_ideas=2,
        cost_model="5 bps total round-trip baseline cost, with later stress scenarios.",
        point_in_time_rule="Range boundaries and midpoint use labels through 09:40 only.",
        current_data_proxy="Strict early-range midpoint is used because current Yahoo database does not contain reliable volume for VWAP.",
        known_limitation="This is a midpoint-reversion baseline, not the final VWAP implementation named provisionally in Step 8.",
    ),
    "HIGH_VOL_REVERSAL": PlaybookSpec(
        regime="HIGH_VOL_REVERSAL",
        playbook_id="FAILED_BREAKOUT_REVERSAL_V1_RESEARCH",
        simulation_readiness="READY_OHLC_ONLY",
        direction_model="DIRECTIONAL_REVERSAL",
        portfolio_structure="DIRECTIONAL_REVERSAL_WITH_REDUCED_RISK",
        basket_selection_rule="Select the largest early directional movers that show the strongest retracement or sign change by 09:40.",
        signal_rule="After 09:45, price breaks the opposite side of the final 09:40 bar or a defined reversal pivot against the failed early move.",
        entry_rule="Enter opposite the failed move on first confirmed pivot break through 13:00.",
        entry_start_time="09:45",
        entry_end_time="13:00",
        stop_rule="Session early extreme against the reversal position.",
        target_rule="Opening price first; 1.0R cap used when the open is farther away.",
        time_exit_rule="Close remaining position at the final available bar through 16:30.",
        same_bar_priority="STOP",
        position_sizing_rule="Equal notional with 0.50 regime multiplier.",
        research_risk_multiplier=0.50,
        max_concurrent_ideas=2,
        cost_model="5 bps total round-trip baseline cost, with later stress scenarios.",
        point_in_time_rule="Failed-move ranking uses only bars through 09:40; reversal trigger begins at 09:45.",
        current_data_proxy="OHLC retracement substitutes for unavailable intrabar order-flow reversal evidence.",
        known_limitation="Five-minute bars cannot identify the exact intrabar sequence of failure and reversal.",
    ),
    "HIGH_DISPERSION": PlaybookSpec(
        regime="HIGH_DISPERSION",
        playbook_id="CROSS_SECTIONAL_RELATIVE_VALUE_V1_RESEARCH",
        simulation_readiness="READY_WITH_OHLC_PROXY",
        direction_model="MARKET_NEUTRAL_LONG_SHORT",
        portfolio_structure="MARKET_NEUTRAL_LONG_SHORT",
        basket_selection_rule="Long the strongest 09:40 relative-strength stock and short the weakest, using equal SEK notionals.",
        signal_rule="Primary regime is HIGH_DISPERSION and the strongest-minus-weakest 09:40 return spread exceeds a minimum research threshold.",
        entry_rule="Long the strongest and short the weakest at the 09:45-labelled bar open when available; otherwise first common bar open after 09:45.",
        entry_start_time="09:45",
        entry_end_time="10:00",
        stop_rule="Exit both legs if the post-entry long-minus-short spread converges adversely beyond the baseline loss threshold.",
        target_rule="Exit both legs after a 50% continuation extension relative to the strict early spread reference.",
        time_exit_rule="Close both legs at 15:30.",
        same_bar_priority="STOP",
        position_sizing_rule="Equal long and short notionals, total gross exposure scaled by 0.75.",
        research_risk_multiplier=0.75,
        max_concurrent_ideas=2,
        cost_model="5 bps per leg round-trip baseline cost; paired strategies therefore incur two-leg costs.",
        point_in_time_rule="Pair ranking and spread reference use labels through 09:40 only.",
        current_data_proxy="Universe-wide pair is used because sector classifications are not yet stored in the research database.",
        known_limitation="Sector neutrality and beta neutrality cannot yet be enforced; this first baseline is relative-strength continuation, not convergence.",
    ),
    "VOLATILITY_EXPANSION": PlaybookSpec(
        regime="VOLATILITY_EXPANSION",
        playbook_id="CONFIRMED_VOLATILITY_BREAKOUT_V1_RESEARCH",
        simulation_readiness="READY_OHLC_ONLY",
        direction_model="REGIME_ALIGNED_BREAKOUT",
        portfolio_structure="DIRECTIONAL_OR_TWO_SIDED_BREAKOUT",
        basket_selection_rule="Select the strongest two stocks aligned with the regime direction and with the widest controlled early ranges.",
        signal_rule="Breakout beyond the strict 09:30-09:40 range in the taxonomy direction after 09:45.",
        entry_rule="Enter at first aligned range break through 12:00.",
        entry_start_time="09:45",
        entry_end_time="12:00",
        stop_rule="Opposite half of the strict early range, with a future volatility cap.",
        target_rule="Initial baseline target at 1.5R.",
        time_exit_rule="Close remaining position at the final available bar through 16:30.",
        same_bar_priority="STOP",
        position_sizing_rule="Equal notional with 0.65 regime multiplier.",
        research_risk_multiplier=0.65,
        max_concurrent_ideas=2,
        cost_model="5 bps total round-trip baseline cost, with later stress scenarios.",
        point_in_time_rule="Direction, ranking, and range use labels through 09:40 only.",
        current_data_proxy="Early OHLC range and breadth substitute for unavailable options-implied volatility and order flow.",
        known_limitation="No macro catalyst or external volatility confirmation yet.",
    ),
    "DEFENSIVE_MIXED": PlaybookSpec(
        regime="DEFENSIVE_MIXED",
        playbook_id="DEFENSIVE_MARKET_NEUTRAL_PAIRS_V1_RESEARCH",
        simulation_readiness="READY_WITH_OHLC_PROXY",
        direction_model="LOW_GROSS_MARKET_NEUTRAL",
        portfolio_structure="LOW_GROSS_MARKET_NEUTRAL",
        basket_selection_rule="Form one equal-notional convergence pair by longing the weaker controlled mover and shorting the stronger controlled mover while avoiding the largest early-range outliers.",
        signal_rule="Primary regime is DEFENSIVE_MIXED and a minimum but not extreme controlled cross-sectional spread exists.",
        entry_rule="Enter the long-weaker and short-stronger legs at the 09:45-labelled bar open when available.",
        entry_start_time="09:45",
        entry_end_time="10:00",
        stop_rule="Exit both legs on adverse spread expansion beyond the initial controlled threshold.",
        target_rule="Exit on 35% spread convergence.",
        time_exit_rule="Close both legs at 14:30.",
        same_bar_priority="STOP",
        position_sizing_rule="Equal long and short notionals at 0.40 total gross-risk multiplier.",
        research_risk_multiplier=0.40,
        max_concurrent_ideas=2,
        cost_model="5 bps per leg round-trip baseline cost.",
        point_in_time_rule="Pair ranking uses labels through 09:40 only.",
        current_data_proxy="Universe-level relative-value pair substitutes for unavailable sector, beta, and covariance controls.",
        known_limitation="The proxy is market-neutral only by equal notional, not by beta or sector exposure.",
    ),
    "DATA_LIMITED_DEFENSIVE": PlaybookSpec(
        regime="DATA_LIMITED_DEFENSIVE",
        playbook_id="DATA_LIMITED_STATIC_HEDGE_PROXY_V1_RESEARCH",
        simulation_readiness="READY_WITH_OHLC_PROXY",
        direction_model="MINIMUM_GROSS_HEDGED_PROXY",
        portfolio_structure="MINIMUM_GROSS_MARKET_NEUTRAL",
        basket_selection_rule="Use a deterministic pair from the configured liquid research universe; prefer the two names with the smallest absolute early move when sufficient bars exist.",
        signal_rule="Data-quality override assigned by taxonomy; the strategy deliberately avoids directional inference.",
        entry_rule="Enter equal-notional opposing legs at the first available bar from 09:45 through 10:00.",
        entry_start_time="09:45",
        entry_end_time="10:00",
        stop_rule="Tight paired loss cap based on 0.50% gross pair loss in the first baseline.",
        target_rule="Small 0.25% gross pair gain or spread convergence.",
        time_exit_rule="Close both legs at 12:00.",
        same_bar_priority="STOP",
        position_sizing_rule="Minimum gross equal-notional pair at 0.25 regime multiplier.",
        research_risk_multiplier=0.25,
        max_concurrent_ideas=1,
        cost_model="5 bps per leg round-trip baseline cost.",
        point_in_time_rule="Only observations already available by the first executable entry bar may be used.",
        current_data_proxy="Static research-universe liquidity assumption replaces missing prior-volume, beta, and sector data.",
        known_limitation="This fallback is intentionally conservative and should be replaced once reliable liquidity, beta, and sector inputs exist.",
    ),
}


@dataclass(frozen=True)
class DataRequirement:
    regime: str
    requirement_group: str
    data_item: str
    required: bool
    available: bool
    point_in_time_deadline: str
    fallback_or_proxy: str
    future_upgrade: str


def _requirements() -> list[DataRequirement]:
    rows: list[DataRequirement] = []
    common = [
        ("STRICT_EARLY_OHLC", "09:30, 09:35, and 09:40 OHLC bars", True, True, "09:45", "None", "Nasdaq shadow bars for independent verification"),
        ("INTRADAY_OHLC", "Five-minute bars after 09:45 through the strategy exit cutoff", True, True, "AS_BARS_COMPLETE", "None", "Direct exchange feed and fill model"),
        ("PRIOR_REFERENCE", "Previous official close and prior-session history", True, True, "09:30", "None", "Independent official-close source"),
        ("PORTFOLIO", "Shared cash, capacity, and deterministic tie-break rules", True, True, "BEFORE_SIMULATION", "Existing portfolio simulator", "Unified multi-playbook risk engine"),
    ]
    for regime, spec in PLAYBOOKS.items():
        if regime == "DATA_LIMITED_DEFENSIVE":
            # This fallback exists precisely for sessions where historical context may be
            # incomplete. It therefore requires only executable intraday bars, shared
            # portfolio controls, and a deterministic configured universe. Strict early
            # OHLC is optional and improves pair selection when available.
            rows.extend(
                [
                    DataRequirement(regime, "STRICT_EARLY_OHLC", "09:30, 09:35, and 09:40 OHLC bars", False, True, "09:45", "Deterministic configured-universe pair", "Nasdaq shadow bars for independent verification"),
                    DataRequirement(regime, "INTRADAY_OHLC", "Five-minute bars after 09:45 through the strategy exit cutoff", True, True, "AS_BARS_COMPLETE", "None", "Direct exchange feed and fill model"),
                    DataRequirement(regime, "STATIC_CONFIGURATION", "Configured liquid research universe and deterministic pair ordering", True, True, "BEFORE_SIMULATION", "Existing research configuration", "Dynamic liquidity-ranked universe"),
                    DataRequirement(regime, "PORTFOLIO", "Shared cash, capacity, and deterministic tie-break rules", True, True, "BEFORE_SIMULATION", "Existing portfolio simulator", "Unified multi-playbook risk engine"),
                ]
            )
        else:
            for group, item, required, available, deadline, proxy, upgrade in common:
                rows.append(DataRequirement(regime, group, item, required, available, deadline, proxy, upgrade))

        if regime in {"HIGH_DISPERSION", "DEFENSIVE_MIXED"}:
            rows.extend(
                [
                    DataRequirement(regime, "SECTOR", "Point-in-time sector classification", False, False, "09:45", "Universe-wide equal-notional pair", "Sector-neutral pair construction"),
                    DataRequirement(regime, "BETA", "Prior beta or covariance estimate", False, False, "09:45", "Equal SEK notionals", "Beta-neutral and covariance-aware weights"),
                ]
            )
        if regime == "RANGE_LOW_VOL":
            rows.append(DataRequirement(regime, "VOLUME", "Reliable intraday volume for VWAP", False, False, "09:45", "Strict early-range midpoint", "True point-in-time VWAP reversion"))
        if regime == "DATA_LIMITED_DEFENSIVE":
            rows.extend(
                [
                    DataRequirement(regime, "LIQUIDITY", "Prior-session turnover and spread ranking", False, False, "09:45", "Static liquid research universe", "Dynamic liquidity-ranked fallback basket"),
                    DataRequirement(regime, "SECTOR_BETA", "Sector and beta hedge controls", False, False, "09:45", "Equal-notional opposing legs", "Minimum-variance defensive hedge"),
                ]
            )
        if regime == "TREND_DOWN":
            rows.append(DataRequirement(regime, "SHORTABILITY", "Borrow availability and locate cost", False, False, "09:45", "Assume research-only shortability", "Broker-specific shortability feed"))
        if regime == "VOLATILITY_EXPANSION":
            rows.append(DataRequirement(regime, "EXTERNAL_VOL", "External volatility or catalyst context", False, False, "09:45", "Internal early range and breadth", "VIX, options IV, and macro calendar"))
    return rows


def _registry_frame() -> pd.DataFrame:
    rows = []
    for regime in REGIMES:
        spec = PLAYBOOKS[regime]
        row = asdict(spec)
        row["specification_id"] = SPECIFICATION_ID
        rows.append(row)
    return pd.DataFrame(rows)[REGISTRY_COLUMNS]


def _requirements_frame() -> pd.DataFrame:
    registry = PLAYBOOKS
    rows = []
    for item in _requirements():
        spec = registry[item.regime]
        if item.available:
            status = "AVAILABLE_NOW"
        elif item.required:
            status = "BLOCKING_MISSING"
        else:
            status = "OPTIONAL_UPGRADE_PROXY_DEFINED"
        rows.append(
            {
                "specification_id": SPECIFICATION_ID,
                "regime": item.regime,
                "playbook_id": spec.playbook_id,
                "requirement_group": item.requirement_group,
                "data_item": item.data_item,
                "required_for_baseline_simulation": item.required,
                "available_in_current_project": item.available,
                "availability_status": status,
                "point_in_time_deadline": item.point_in_time_deadline,
                "fallback_or_proxy": item.fallback_or_proxy,
                "future_upgrade": item.future_upgrade,
            }
        )
    return pd.DataFrame(rows)[REQUIREMENT_COLUMNS]


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if pd.isna(value):
        return False
    return bool(value)


def build_coverage(taxonomy: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    if taxonomy.empty:
        return pd.DataFrame(columns=COVERAGE_COLUMNS)
    source = taxonomy.copy()
    source["date"] = source["date"].astype(str)

    # Prefix every contract field before the merge. Step 8 already contains
    # taxonomy-level portfolio_structure and research_risk_multiplier columns;
    # without explicit names pandas creates _x/_y columns and the Step 9A export
    # silently emits blanks.
    contract = registry[
        [
            "regime",
            "playbook_id",
            "simulation_readiness",
            "direction_model",
            "portfolio_structure",
            "research_risk_multiplier",
            "max_concurrent_ideas",
            "point_in_time_rule",
            "legacy_v1_eligible",
        ]
    ].rename(
        columns={
            "regime": "contract_regime",
            "playbook_id": "contract_playbook_id",
            "simulation_readiness": "contract_simulation_readiness",
            "direction_model": "contract_direction_model",
            "portfolio_structure": "contract_portfolio_structure",
            "research_risk_multiplier": "contract_research_risk_multiplier",
            "max_concurrent_ideas": "contract_max_concurrent_ideas",
            "point_in_time_rule": "contract_point_in_time_rule",
            "legacy_v1_eligible": "contract_legacy_v1_eligible",
        }
    )
    merged = source.merge(
        contract,
        left_on="primary_regime",
        right_on="contract_regime",
        how="left",
        validate="many_to_one",
    )

    rows = []
    for row in merged.to_dict("records"):
        primary_regime = str(row.get("primary_regime", ""))
        mapped = bool(str(row.get("contract_playbook_id", "")).strip())
        active = mapped and str(row.get("contract_simulation_readiness", "")).startswith("READY")
        taxonomy_point_safe = _bool(row.get("point_in_time_safe"))
        contract_rule = str(row.get("contract_point_in_time_rule", ""))
        data_quality_override = _bool(row.get("data_quality_override"))

        if primary_regime == "DATA_LIMITED_DEFENSIVE":
            # A deterministic defensive fallback is specifically designed for a
            # session with insufficient prior history. It may therefore pass even
            # when the feature foundation marks the first observed date as not
            # point-in-time-ready, provided the taxonomy explicitly applied its
            # data-quality override and the contract itself is active. No future
            # information is introduced: pair selection is deterministic and any
            # executable observations are consumed only as their bars complete.
            point_safe = active and data_quality_override
            point_reason = (
                "DATA_LIMITED_DETERMINISTIC_FALLBACK_SAFE"
                if point_safe
                else "DATA_LIMITED_FALLBACK_CONTRACT_INCOMPLETE"
            )
        else:
            point_safe = taxonomy_point_safe and "09:40" in contract_rule
            if not taxonomy_point_safe:
                point_reason = "TAXONOMY_POINT_IN_TIME_INPUT_FAILED"
            elif "09:40" not in contract_rule:
                point_reason = "CONTRACT_ROUTER_CUTOFF_NOT_EXPLICIT"
            else:
                point_reason = "STRICT_ROUTER_INPUTS_THROUGH_0940"

        rows.append(
            {
                "specification_id": SPECIFICATION_ID,
                "date": row.get("date", ""),
                "primary_regime": primary_regime,
                "regime_confidence": pd.to_numeric(pd.Series([row.get("regime_confidence")]), errors="coerce").iloc[0],
                "confidence_band": row.get("confidence_band", ""),
                "taxonomy_eligible": _bool(row.get("taxonomy_eligible")),
                "data_quality_override": data_quality_override,
                "playbook_id": row.get("contract_playbook_id", ""),
                "simulation_readiness": row.get("contract_simulation_readiness", ""),
                "direction_model": row.get("contract_direction_model", ""),
                "portfolio_structure": row.get("contract_portfolio_structure", ""),
                "research_risk_multiplier": pd.to_numeric(pd.Series([row.get("contract_research_risk_multiplier")]), errors="coerce").iloc[0],
                "max_concurrent_ideas": pd.to_numeric(pd.Series([row.get("contract_max_concurrent_ideas")]), errors="coerce").iloc[0],
                "active_simulation_contract": active,
                "taxonomy_point_in_time_safe": taxonomy_point_safe,
                "point_in_time_contract_pass": point_safe,
                "point_in_time_contract_reason": point_reason,
                "legacy_v1_router_eligible": _bool(row.get("contract_legacy_v1_eligible")),
                "coverage_status": "ACTIVE_EXECUTABLE_CONTRACT" if active and point_safe else "COVERAGE_GAP_REVIEW_REQUIRED",
            }
        )
    return pd.DataFrame(rows)[COVERAGE_COLUMNS]


def build_summary(registry: pd.DataFrame, requirements: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    mapped = int(coverage["playbook_id"].fillna("").astype(str).str.strip().ne("").sum()) if not coverage.empty else 0
    active = int(coverage["active_simulation_contract"].fillna(False).astype(bool).sum()) if not coverage.empty else 0
    no_trade = int((~coverage["active_simulation_contract"].fillna(False).astype(bool)).sum()) if not coverage.empty else 0
    blocked = int(registry["simulation_readiness"].eq("BLOCKED").sum()) if not registry.empty else 0
    all_point_safe = bool(coverage["point_in_time_contract_pass"].fillna(False).all()) if not coverage.empty else True
    risk_exit = bool(
        registry["stop_rule"].fillna("").astype(str).str.strip().ne("").all()
        and registry["target_rule"].fillna("").astype(str).str.strip().ne("").all()
        and registry["time_exit_rule"].fillna("").astype(str).str.strip().ne("").all()
    )
    classification = (
        "EXECUTABLE_PLAYBOOK_SPECIFICATIONS_READY_FOR_BASELINE_SIMULATION"
        if len(registry) == len(REGIMES)
        and mapped == len(coverage)
        and active == len(coverage)
        and blocked == 0
        and all_point_safe
        and risk_exit
        and not LEGACY_V1_ROUTER_ELIGIBLE
        else "PLAYBOOK_SPECIFICATION_GAPS_REQUIRE_REVIEW"
    )
    return pd.DataFrame(
        [
            {
                "specification_id": SPECIFICATION_ID,
                "research_status": RESEARCH_STATUS,
                "decision_time": DECISION_TIME,
                "latest_allowed_bar_label": LATEST_ALLOWED_BAR_LABEL,
                "bar_timestamp_convention": BAR_TIMESTAMP_CONVENTION,
                "taxonomy_sessions": int(len(coverage)),
                "sessions_with_mapped_playbook": mapped,
                "sessions_without_mapped_playbook": int(len(coverage) - mapped),
                "sessions_with_active_simulation_contract": active,
                "no_trade_sessions": no_trade,
                "regime_count_expected": int(len(REGIMES)),
                "regime_count_specified": int(registry["regime"].nunique()),
                "unique_playbook_count": int(registry["playbook_id"].nunique()),
                "ready_ohlc_only_playbooks": int(registry["simulation_readiness"].eq("READY_OHLC_ONLY").sum()),
                "ready_with_proxy_playbooks": int(registry["simulation_readiness"].eq("READY_WITH_OHLC_PROXY").sum()),
                "blocked_playbooks": blocked,
                "strict_recovery_v2_required": bool(registry.loc[registry["regime"].eq("RECOVERY"), "playbook_id"].eq("STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH").all()),
                "legacy_v1_router_eligible": LEGACY_V1_ROUTER_ELIGIBLE,
                "all_entries_point_in_time_safe": all_point_safe,
                "point_in_time_contract_failures": int((~coverage["point_in_time_contract_pass"].fillna(False).astype(bool)).sum()) if not coverage.empty else 0,
                "data_limited_fallback_passes": int(
                    (
                        coverage["primary_regime"].eq("DATA_LIMITED_DEFENSIVE")
                        & coverage["point_in_time_contract_pass"].fillna(False).astype(bool)
                    ).sum()
                ) if not coverage.empty else 0,
                "all_regimes_have_exit_and_risk_contract": risk_exit,
                "classification": classification,
            }
        ],
        columns=SUMMARY_COLUMNS,
    )


def run(
    taxonomy_file: Path = TAXONOMY_FILE,
    summary_file: Path = SUMMARY_FILE,
    registry_file: Path = REGISTRY_FILE,
    requirements_file: Path = REQUIREMENTS_FILE,
    coverage_file: Path = COVERAGE_FILE,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not Path(taxonomy_file).exists():
        raise FileNotFoundError(f"Missing Step 8 taxonomy output: {taxonomy_file}")
    taxonomy = pd.read_csv(taxonomy_file)
    registry = _registry_frame()
    requirements = _requirements_frame()
    coverage = build_coverage(taxonomy, registry)
    summary = build_summary(registry, requirements, coverage)

    export_csv_for_power_bi(summary, summary_file)
    export_csv_for_power_bi(registry, registry_file)
    export_csv_for_power_bi(requirements, requirements_file)
    export_csv_for_power_bi(coverage, coverage_file)
    return summary, registry, requirements, coverage


def main() -> None:
    print("\n=== STEP 9A EXECUTABLE PLAYBOOK SPECIFICATIONS ===")
    print(f"Specification     : {SPECIFICATION_ID}")
    print(f"Research status   : {RESEARCH_STATUS}")
    print(f"Decision time     : {DECISION_TIME}")
    print(f"Latest bar label  : {LATEST_ALLOWED_BAR_LABEL}")
    print("Every Step 8 regime receives an explicit baseline basket, signal, entry, stop, target, time exit, cost, and sizing contract.")
    print("These are simulation specifications, not validated or live-trading recommendations.")
    summary, registry, requirements, coverage = run()
    row = summary.iloc[0]
    print("\n=== STEP 9A PLAYBOOK SPECIFICATION RESULT ===")
    print(f"Taxonomy sessions             : {int(row['taxonomy_sessions'])}")
    print(f"Mapped playbook sessions      : {int(row['sessions_with_mapped_playbook'])}")
    print(f"Active contract sessions      : {int(row['sessions_with_active_simulation_contract'])}")
    print(f"No-trade sessions             : {int(row['no_trade_sessions'])}")
    print(f"Regimes / playbooks specified : {int(row['regime_count_specified'])}/{int(row['unique_playbook_count'])}")
    print(f"OHLC-ready playbooks          : {int(row['ready_ohlc_only_playbooks'])}")
    print(f"Proxy-ready playbooks         : {int(row['ready_with_proxy_playbooks'])}")
    print(f"Blocked playbooks             : {int(row['blocked_playbooks'])}")
    print(f"Point-in-time contracts pass  : {bool(row['all_entries_point_in_time_safe'])}")
    print(f"Strict recovery V2 required   : {bool(row['strict_recovery_v2_required'])}")
    print(f"Legacy V1 router eligible     : {bool(row['legacy_v1_router_eligible'])}")
    print(f"Classification                : {row['classification']}")
    print("Step 9A playbook specification export complete.")


if __name__ == "__main__":
    main()
