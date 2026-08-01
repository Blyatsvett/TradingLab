from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, REFERENCE_DATA_DIR, legacy_output_path


EXPERIMENT_ID = "REGIME_SECTOR_TICKER_STRATEGY_EXPERIMENTS_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_HIERARCHICAL_DISCOVERY_NOT_ROUTER_ACTIVE"
MINIMUM_SCREENING_TRADES = 8
MINIMUM_SCREENING_SESSIONS = 4
MINIMUM_GROUP_COMPANIES = 2

TRADE_SOURCE_FILE = legacy_output_path("regime_challenger_trades.csv")
LEG_SOURCE_FILE = legacy_output_path("regime_challenger_trade_legs.csv")
STATIC_SOURCE_FILE = REFERENCE_DATA_DIR / "instrument_static_taxonomy.csv"
CHARACTERISTIC_SOURCE_FILE = REFERENCE_DATA_DIR / "instrument_point_in_time_characteristics.csv"
GROUP_SOURCE_FILE = REFERENCE_DATA_DIR / "instrument_group_daily_state.csv"

SUMMARY_FILE = legacy_output_path("regime_sector_strategy_summary.csv")
TRADE_CONTEXT_FILE = legacy_output_path("regime_sector_strategy_trade_context.csv")
LEG_CONTEXT_FILE = legacy_output_path("regime_sector_strategy_leg_context.csv")
SEGMENT_PERFORMANCE_FILE = legacy_output_path("regime_sector_strategy_segment_performance.csv")
PAIR_PERFORMANCE_FILE = legacy_output_path("regime_sector_strategy_pair_performance.csv")
EXCLUSION_ROBUSTNESS_FILE = legacy_output_path("regime_sector_strategy_exclusion_robustness.csv")
DIMENSION_AUDIT_FILE = legacy_output_path("regime_sector_strategy_dimension_audit.csv")
STATE_AUDIT_FILE = legacy_output_path("regime_sector_strategy_state_audit.csv")
RANKING_FILE = legacy_output_path("regime_sector_strategy_rankings.csv")

SUMMARY_COLUMNS = [
    "experiment_id", "research_status", "source_trades", "source_legs", "enriched_trades",
    "enriched_legs", "single_trades", "paired_trades", "independent_companies",
    "multi_company_broad_sectors", "multi_company_primary_peer_groups",
    "single_company_group_definitions", "redundant_group_dimensions",
    "low_discrimination_state_parameters", "same_company_pair_conflicts",
    "point_in_time_fail_trades", "point_in_time_fail_legs", "segment_performance_cells",
    "screenable_segment_cells", "positive_net_screenable_segment_cells", "pair_performance_cells",
    "exclusion_robustness_rows", "strategies_promoted", "router_active", "classification",
]

TRADE_CONTEXT_COLUMNS = [
    "experiment_id", "trade_id", "date", "primary_regime", "challenger_id", "strategy_family",
    "control_status", "idea_type", "direction", "ticker", "paired_ticker", "long_ticker",
    "short_ticker", "entry_time", "exit_time", "exit_reason", "equal_gross_pnl_sek", "equal_cost_sek",
    "equal_net_pnl_sek", "risk_capped_gross_pnl_sek", "risk_capped_cost_sek", "risk_capped_net_pnl_sek", "primary_company_id", "primary_company_name", "primary_broad_sector",
    "primary_economic_cluster", "primary_peer_group", "primary_ticker_relative_state",
    "primary_volatility_bucket", "primary_range_state", "primary_historical_tendency",
    "primary_sector_direction_state", "primary_sector_direction_alignment",
    "primary_group_evidence_tier", "long_company_id", "short_company_id", "long_broad_sector",
    "short_broad_sector", "long_primary_peer_group", "short_primary_peer_group",
    "pair_relationship", "pair_sector_route", "pair_peer_route", "independent_company_count_in_trade",
    "taxonomy_context_complete", "taxonomy_point_in_time_pass", "same_company_pair_conflict",
]

LEG_CONTEXT_COLUMNS = [
    "experiment_id", "trade_id", "leg_id", "date", "primary_regime", "challenger_id", "ticker",
    "side", "entry_time", "exit_time", "exit_reason", "equal_net_pnl_sek",
    "risk_capped_net_pnl_sek", "company_id", "company_name", "share_class_group",
    "company_observation_weight", "broad_sector", "industry_group", "economic_cluster",
    "primary_peer_group", "ticker_relative_state", "gap_state", "historical_tendency",
    "volatility_bucket", "range_state", "prior_history_sessions", "minimum_history_ready",
    "full_history_ready", "sector_independent_company_count", "relative_reference_used",
    "sector_direction_state", "sector_direction_alignment", "group_evidence_tier",
    "taxonomy_context_complete", "taxonomy_point_in_time_pass",
]

SEGMENT_PERFORMANCE_COLUMNS = [
    "experiment_id", "primary_regime", "challenger_id", "strategy_family", "control_status",
    "analysis_dimension", "segment_value", "evidence_scope", "static_independent_companies",
    "observed_independent_companies", "observed_tickers", "trades", "sessions_with_trades",
    "winning_trades_equal_notional", "win_rate_equal_notional", "gross_pnl_equal_notional_sek",
    "cost_equal_notional_sek", "net_pnl_equal_notional_sek", "profit_factor_equal_notional",
    "winning_trades_risk_capped", "win_rate_risk_capped", "gross_pnl_risk_capped_sek",
    "cost_risk_capped_sek", "net_pnl_risk_capped_sek", "average_net_pnl_risk_capped_sek",
    "median_net_pnl_risk_capped_sek", "profit_factor_risk_capped", "top_day_abs_pnl_share",
    "leave_one_day_out_profitable_share", "leave_one_day_out_min_pnl_sek", "sample_status",
    "generalization_status", "selection_status",
]

PAIR_PERFORMANCE_COLUMNS = [
    "experiment_id", "primary_regime", "challenger_id", "strategy_family", "control_status",
    "analysis_dimension", "segment_value", "trades", "sessions_with_trades",
    "independent_companies", "winning_trades_risk_capped", "win_rate_risk_capped",
    "gross_pnl_risk_capped_sek", "cost_risk_capped_sek", "net_pnl_risk_capped_sek",
    "average_net_pnl_risk_capped_sek", "profit_factor_risk_capped", "top_day_abs_pnl_share",
    "leave_one_day_out_profitable_share", "leave_one_day_out_min_pnl_sek", "sample_status",
    "selection_status",
]

EXCLUSION_COLUMNS = [
    "experiment_id", "primary_regime", "challenger_id", "strategy_family", "control_status",
    "exclusion_type", "excluded_value", "baseline_trades", "excluded_trades", "remaining_trades",
    "remaining_sessions", "baseline_net_pnl_risk_capped_sek", "remaining_net_pnl_risk_capped_sek",
    "pnl_change_after_exclusion_sek", "remaining_positive", "robustness_status",
]

DIMENSION_AUDIT_COLUMNS = [
    "experiment_id", "dimension_name", "dimension_role", "group_count", "multi_company_groups",
    "single_company_groups", "independent_companies", "partition_signature", "duplicate_of_dimension",
    "primary_screening_eligible", "interpretation_guardrail", "audit_status",
]

STATE_AUDIT_COLUMNS = [
    "experiment_id", "parameter_name", "eligible_rows", "category_count", "dominant_category",
    "dominant_category_rows", "dominant_share", "normalized_entropy", "discrimination_status",
    "router_active", "interpretation_guardrail",
]

RANKING_COLUMNS = [
    "experiment_id", "primary_regime", "challenger_id", "strategy_family", "analysis_dimension",
    "segment_value", "evidence_scope", "trades", "sessions_with_trades",
    "observed_independent_companies", "net_pnl_risk_capped_sek", "profit_factor_risk_capped",
    "leave_one_day_out_min_pnl_sek", "sample_status", "generalization_status",
    "rank_within_regime_challenger_dimension", "selection_status",
]

SINGLE_SEGMENT_DIMENSIONS = [
    ("BROAD_SECTOR", "primary_broad_sector"),
    ("PRIMARY_PEER_GROUP", "primary_peer_group"),
    ("COMPANY", "primary_company_id"),
    ("TICKER", "ticker"),
    ("TICKER_RELATIVE_STATE", "primary_ticker_relative_state"),
    ("VOLATILITY_BUCKET", "primary_volatility_bucket"),
    ("RANGE_STATE", "primary_range_state"),
    ("HISTORICAL_TENDENCY", "primary_historical_tendency"),
    ("SECTOR_DIRECTION_ALIGNMENT", "primary_sector_direction_alignment"),
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
    if losses == 0:
        return np.nan
    return gains / losses


def _concentration(frame: pd.DataFrame, pnl_column: str = "risk_capped_net_pnl_sek") -> tuple[float, float, float]:
    if frame.empty:
        return np.nan, np.nan, np.nan
    pnl = pd.to_numeric(frame[pnl_column], errors="coerce").fillna(0.0)
    total_abs = float(pnl.abs().sum())
    daily = frame.assign(_pnl=pnl).groupby("date", as_index=False)["_pnl"].sum()
    top_day_share = float(daily["_pnl"].abs().max() / total_abs) if total_abs > 0 and not daily.empty else np.nan
    baseline = float(pnl.sum())
    remaining = [baseline - float(value) for value in daily["_pnl"]]
    loo_share = float(np.mean([value > 0 for value in remaining])) if remaining else np.nan
    loo_min = float(min(remaining)) if remaining else np.nan
    return top_day_share, loo_share, loo_min


def _direction_alignment(side: str, group_direction: str) -> str:
    side = str(side).upper()
    direction = str(group_direction).upper()
    if direction not in {"UP", "DOWN"}:
        return "GROUP_MIXED_OR_UNAVAILABLE"
    if (side == "LONG" and direction == "UP") or (side == "SHORT" and direction == "DOWN"):
        return "ALIGNED_WITH_GROUP"
    return "CONTRARIAN_TO_GROUP"


def _partition_signature(static: pd.DataFrame, column: str) -> str:
    groups = []
    for _, group in static.groupby(column, sort=True):
        companies = sorted(set(group["company_id"].astype(str)))
        groups.append("+".join(companies))
    return "||".join(sorted(groups))


def _group_company_counts(static: pd.DataFrame, column: str) -> dict[str, int]:
    return static.groupby(column)["company_id"].nunique().astype(int).to_dict()


def enrich_leg_context(
    legs: pd.DataFrame,
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
) -> pd.DataFrame:
    legs = legs.copy()
    legs["date"] = legs["date"].astype(str)
    static = static.copy()
    characteristics = characteristics.copy()
    characteristics["date"] = characteristics["date"].astype(str)
    group_states = group_states.copy()
    group_states["date"] = group_states["date"].astype(str)

    static_columns = [
        "ticker", "company_id", "company_name", "share_class_group", "company_observation_weight",
        "broad_sector", "industry_group", "economic_cluster", "primary_peer_group",
    ]
    characteristic_columns = [
        "date", "ticker", "ticker_relative_state", "gap_state", "historical_tendency",
        "volatility_bucket", "range_state", "prior_history_sessions", "minimum_history_ready",
        "full_history_ready", "sector_independent_company_count", "relative_reference_used",
        "point_in_time_pass",
    ]
    enriched = legs.merge(static[static_columns], on="ticker", how="left", validate="many_to_one")
    enriched = enriched.merge(characteristics[characteristic_columns], on=["date", "ticker"], how="left", validate="many_to_one")

    sector_states = group_states[group_states["aggregation_level"].eq("BROAD_SECTOR")][
        ["date", "group_name", "group_direction_state", "group_peer_status", "point_in_time_pass"]
    ].rename(
        columns={
            "group_name": "broad_sector",
            "group_direction_state": "sector_direction_state",
            "group_peer_status": "sector_peer_status",
            "point_in_time_pass": "sector_state_point_in_time_pass",
        }
    )
    enriched = enriched.merge(sector_states, on=["date", "broad_sector"], how="left", validate="many_to_one")
    enriched["sector_direction_alignment"] = [
        _direction_alignment(side, direction)
        for side, direction in zip(enriched["side"], enriched["sector_direction_state"])
    ]
    enriched["group_evidence_tier"] = np.where(
        pd.to_numeric(enriched["sector_independent_company_count"], errors="coerce").fillna(0).ge(MINIMUM_GROUP_COMPANIES),
        "MULTI_COMPANY_SECTOR_CONTEXT",
        "SINGLE_COMPANY_PROXY_CONTEXT",
    )
    static_ok = enriched["company_id"].notna() & enriched["broad_sector"].notna()
    char_ok = enriched["ticker_relative_state"].notna()
    enriched["taxonomy_context_complete"] = static_ok & char_ok
    enriched["taxonomy_point_in_time_pass"] = (
        enriched["point_in_time_pass"].map(_bool)
        & enriched["sector_state_point_in_time_pass"].map(_bool)
    )
    enriched.insert(0, "experiment_id", EXPERIMENT_ID)
    return enriched.reindex(columns=LEG_CONTEXT_COLUMNS)


def enrich_trade_context(
    trades: pd.DataFrame,
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
) -> pd.DataFrame:
    trades = trades.copy()
    trades["date"] = trades["date"].astype(str)
    static = static.copy().set_index("ticker", drop=False)
    characteristics = characteristics.copy()
    characteristics["date"] = characteristics["date"].astype(str)
    char_lookup = characteristics.set_index(["date", "ticker"], drop=False)
    group_states = group_states.copy()
    group_states["date"] = group_states["date"].astype(str)
    sector_lookup = group_states[group_states["aggregation_level"].eq("BROAD_SECTOR")].set_index(["date", "group_name"])

    rows: list[dict] = []
    for source in trades.to_dict("records"):
        idea_type = str(source.get("idea_type", "SINGLE"))
        date = str(source.get("date", ""))
        primary_ticker = str(source.get("ticker", ""))
        long_ticker = str(source.get("long_ticker", "") or "")
        short_ticker = str(source.get("short_ticker", "") or "")
        if idea_type != "PAIR":
            long_ticker = primary_ticker if str(source.get("direction", "")).upper() == "LONG" else ""
            short_ticker = primary_ticker if str(source.get("direction", "")).upper() == "SHORT" else ""

        primary_static = static.loc[primary_ticker] if primary_ticker in static.index else pd.Series(dtype="object")
        primary_char = char_lookup.loc[(date, primary_ticker)] if (date, primary_ticker) in char_lookup.index else pd.Series(dtype="object")
        long_static = static.loc[long_ticker] if long_ticker in static.index else pd.Series(dtype="object")
        short_static = static.loc[short_ticker] if short_ticker in static.index else pd.Series(dtype="object")

        primary_sector = str(primary_static.get("broad_sector", ""))
        sector_state = sector_lookup.loc[(date, primary_sector)] if (date, primary_sector) in sector_lookup.index else pd.Series(dtype="object")
        primary_side = "LONG" if str(source.get("direction", "")).upper() == "LONG" else "SHORT" if str(source.get("direction", "")).upper() == "SHORT" else ""
        primary_alignment = _direction_alignment(primary_side, sector_state.get("group_direction_state", "")) if primary_side else "NOT_APPLICABLE_PAIR"

        long_company = str(long_static.get("company_id", ""))
        short_company = str(short_static.get("company_id", ""))
        long_sector = str(long_static.get("broad_sector", ""))
        short_sector = str(short_static.get("broad_sector", ""))
        long_peer = str(long_static.get("primary_peer_group", ""))
        short_peer = str(short_static.get("primary_peer_group", ""))
        same_company_conflict = bool(idea_type == "PAIR" and long_company and long_company == short_company)
        if idea_type != "PAIR":
            pair_relationship = "NOT_APPLICABLE_SINGLE"
            pair_sector_route = "NOT_APPLICABLE_SINGLE"
            pair_peer_route = "NOT_APPLICABLE_SINGLE"
            company_count = 1 if str(primary_static.get("company_id", "")) else 0
        else:
            pair_sector_route = f"{long_sector}->{short_sector}" if long_sector and short_sector else "UNKNOWN"
            pair_peer_route = f"{long_peer}->{short_peer}" if long_peer and short_peer else "UNKNOWN"
            if same_company_conflict:
                pair_relationship = "SAME_COMPANY_INVALID"
            elif long_sector and long_sector == short_sector:
                pair_relationship = "SAME_BROAD_SECTOR"
            elif long_peer and long_peer == short_peer:
                pair_relationship = "SAME_PRIMARY_PEER_GROUP"
            else:
                pair_relationship = "CROSS_GROUP"
            company_count = len({value for value in [long_company, short_company] if value})

        sector_company_count = _num(primary_char.get("sector_independent_company_count"), 0.0)
        evidence_tier = (
            "MULTI_COMPANY_SECTOR_CONTEXT"
            if sector_company_count >= MINIMUM_GROUP_COMPANIES
            else "SINGLE_COMPANY_PROXY_CONTEXT"
        )
        static_complete = bool(primary_static.get("company_id", "")) if idea_type != "PAIR" else bool(long_company and short_company)
        char_complete = _bool(primary_char.get("point_in_time_pass")) if idea_type != "PAIR" else True
        if idea_type == "PAIR":
            long_char = char_lookup.loc[(date, long_ticker)] if (date, long_ticker) in char_lookup.index else pd.Series(dtype="object")
            short_char = char_lookup.loc[(date, short_ticker)] if (date, short_ticker) in char_lookup.index else pd.Series(dtype="object")
            char_complete = _bool(long_char.get("point_in_time_pass")) and _bool(short_char.get("point_in_time_pass"))

        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "trade_id": source.get("trade_id", ""),
                "date": date,
                "primary_regime": source.get("primary_regime", ""),
                "challenger_id": source.get("challenger_id", ""),
                "strategy_family": source.get("strategy_family", ""),
                "control_status": source.get("control_status", ""),
                "idea_type": idea_type,
                "direction": source.get("direction", ""),
                "ticker": primary_ticker,
                "paired_ticker": source.get("paired_ticker", ""),
                "long_ticker": long_ticker,
                "short_ticker": short_ticker,
                "entry_time": source.get("entry_time", ""),
                "exit_time": source.get("exit_time", ""),
                "exit_reason": source.get("exit_reason", ""),
                "equal_gross_pnl_sek": _num(source.get("equal_gross_pnl_sek"), 0.0),
                "equal_cost_sek": _num(source.get("equal_cost_sek"), 0.0),
                "equal_net_pnl_sek": _num(source.get("equal_net_pnl_sek"), 0.0),
                "risk_capped_gross_pnl_sek": _num(source.get("risk_capped_gross_pnl_sek"), 0.0),
                "risk_capped_cost_sek": _num(source.get("risk_capped_cost_sek"), 0.0),
                "risk_capped_net_pnl_sek": _num(source.get("risk_capped_net_pnl_sek"), 0.0),
                "primary_company_id": primary_static.get("company_id", ""),
                "primary_company_name": primary_static.get("company_name", ""),
                "primary_broad_sector": primary_sector,
                "primary_economic_cluster": primary_static.get("economic_cluster", ""),
                "primary_peer_group": primary_static.get("primary_peer_group", ""),
                "primary_ticker_relative_state": primary_char.get("ticker_relative_state", ""),
                "primary_volatility_bucket": primary_char.get("volatility_bucket", ""),
                "primary_range_state": primary_char.get("range_state", ""),
                "primary_historical_tendency": primary_char.get("historical_tendency", ""),
                "primary_sector_direction_state": sector_state.get("group_direction_state", ""),
                "primary_sector_direction_alignment": primary_alignment,
                "primary_group_evidence_tier": evidence_tier,
                "long_company_id": long_company,
                "short_company_id": short_company,
                "long_broad_sector": long_sector,
                "short_broad_sector": short_sector,
                "long_primary_peer_group": long_peer,
                "short_primary_peer_group": short_peer,
                "pair_relationship": pair_relationship,
                "pair_sector_route": pair_sector_route,
                "pair_peer_route": pair_peer_route,
                "independent_company_count_in_trade": company_count,
                "taxonomy_context_complete": static_complete and char_complete,
                "taxonomy_point_in_time_pass": char_complete,
                "same_company_pair_conflict": same_company_conflict,
            }
        )
    return pd.DataFrame(rows, columns=TRADE_CONTEXT_COLUMNS)


def _static_scope_counts(static: pd.DataFrame, dimension: str, segment: str) -> int:
    if dimension == "BROAD_SECTOR":
        return int(static.loc[static["broad_sector"].eq(segment), "company_id"].nunique())
    if dimension == "PRIMARY_PEER_GROUP":
        return int(static.loc[static["primary_peer_group"].eq(segment), "company_id"].nunique())
    if dimension == "COMPANY":
        return 1
    if dimension == "TICKER":
        return 1
    return int(static["company_id"].nunique())


def _evidence_scope(dimension: str, static_companies: int) -> str:
    if dimension == "COMPANY":
        return "COMPANY_SPECIFIC_DISCOVERY"
    if dimension == "TICKER":
        return "TICKER_SPECIFIC_DISCOVERY"
    if dimension in {"BROAD_SECTOR", "PRIMARY_PEER_GROUP"}:
        return "MULTI_COMPANY_GROUP_DISCOVERY" if static_companies >= MINIMUM_GROUP_COMPANIES else "SINGLE_COMPANY_PROXY"
    return "POINT_IN_TIME_STATE_DISCOVERY"


def build_segment_performance(trade_context: pd.DataFrame, static: pd.DataFrame) -> pd.DataFrame:
    singles = trade_context[trade_context["idea_type"].eq("SINGLE")].copy()
    rows: list[dict] = []
    if singles.empty:
        return pd.DataFrame(columns=SEGMENT_PERFORMANCE_COLUMNS)
    for dimension, source_column in SINGLE_SEGMENT_DIMENSIONS:
        usable = singles[singles[source_column].notna() & singles[source_column].astype(str).ne("")].copy()
        for keys, cell in usable.groupby(["primary_regime", "challenger_id", source_column], sort=True):
            regime, challenger_id, segment = keys
            strategy_family = str(cell["strategy_family"].iloc[0])
            control_status = str(cell["control_status"].iloc[0])
            static_companies = _static_scope_counts(static, dimension, str(segment))
            observed_companies = int(cell["primary_company_id"].replace("", np.nan).nunique())
            observed_tickers = int(cell["ticker"].replace("", np.nan).nunique())
            equal_pnl = pd.to_numeric(cell["equal_net_pnl_sek"], errors="coerce").fillna(0.0)
            risk_pnl = pd.to_numeric(cell["risk_capped_net_pnl_sek"], errors="coerce").fillna(0.0)
            equal_gross = pd.to_numeric(cell["equal_gross_pnl_sek"], errors="coerce").fillna(0.0)
            equal_cost = pd.to_numeric(cell["equal_cost_sek"], errors="coerce").fillna(0.0)
            risk_gross = pd.to_numeric(cell["risk_capped_gross_pnl_sek"], errors="coerce").fillna(0.0)
            risk_cost = pd.to_numeric(cell["risk_capped_cost_sek"], errors="coerce").fillna(0.0)
            top_share, loo_share, loo_min = _concentration(cell)
            enough_basic = len(cell) >= MINIMUM_SCREENING_TRADES and cell["date"].nunique() >= MINIMUM_SCREENING_SESSIONS
            enough_companies = observed_companies >= MINIMUM_GROUP_COMPANIES
            scope = _evidence_scope(dimension, static_companies)
            if dimension in {"BROAD_SECTOR", "PRIMARY_PEER_GROUP"} and static_companies < MINIMUM_GROUP_COMPANIES:
                sample_status = "SINGLE_COMPANY_PROXY_NOT_SCREENABLE_AS_GROUP"
                generalization = "TICKER_OR_COMPANY_EVIDENCE_ONLY"
            elif dimension in {"BROAD_SECTOR", "PRIMARY_PEER_GROUP", "TICKER_RELATIVE_STATE", "VOLATILITY_BUCKET", "RANGE_STATE", "HISTORICAL_TENDENCY", "SECTOR_DIRECTION_ALIGNMENT"} and not enough_companies:
                sample_status = "INSUFFICIENT_INDEPENDENT_COMPANY_COVERAGE"
                generalization = "INSUFFICIENT_COMPANY_DIVERSITY"
            elif enough_basic:
                sample_status = "SCREENABLE_HIERARCHICAL_DISCOVERY"
                generalization = "ENTITY_SPECIFIC_ONLY" if dimension in {"COMPANY", "TICKER"} else "MULTI_COMPANY_DISCOVERY_ONLY"
            else:
                sample_status = "INSUFFICIENT_SAMPLE"
                generalization = "ENTITY_SPECIFIC_ONLY" if dimension in {"COMPANY", "TICKER"} else "DISCOVERY_SAMPLE_TOO_SMALL"
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "primary_regime": regime,
                    "challenger_id": challenger_id,
                    "strategy_family": strategy_family,
                    "control_status": control_status,
                    "analysis_dimension": dimension,
                    "segment_value": segment,
                    "evidence_scope": scope,
                    "static_independent_companies": static_companies,
                    "observed_independent_companies": observed_companies,
                    "observed_tickers": observed_tickers,
                    "trades": len(cell),
                    "sessions_with_trades": int(cell["date"].nunique()),
                    "winning_trades_equal_notional": int((equal_pnl > 0).sum()),
                    "win_rate_equal_notional": float((equal_pnl > 0).mean()) if len(cell) else np.nan,
                    "gross_pnl_equal_notional_sek": float(equal_gross.sum()),
                    "cost_equal_notional_sek": float(equal_cost.sum()),
                    "net_pnl_equal_notional_sek": float(equal_pnl.sum()),
                    "profit_factor_equal_notional": _profit_factor(equal_pnl),
                    "winning_trades_risk_capped": int((risk_pnl > 0).sum()),
                    "win_rate_risk_capped": float((risk_pnl > 0).mean()) if len(cell) else np.nan,
                    "gross_pnl_risk_capped_sek": float(risk_gross.sum()),
                    "cost_risk_capped_sek": float(risk_cost.sum()),
                    "net_pnl_risk_capped_sek": float(risk_pnl.sum()),
                    "average_net_pnl_risk_capped_sek": float(risk_pnl.mean()),
                    "median_net_pnl_risk_capped_sek": float(risk_pnl.median()),
                    "profit_factor_risk_capped": _profit_factor(risk_pnl),
                    "top_day_abs_pnl_share": top_share,
                    "leave_one_day_out_profitable_share": loo_share,
                    "leave_one_day_out_min_pnl_sek": loo_min,
                    "sample_status": sample_status,
                    "generalization_status": generalization,
                    "selection_status": "DISCOVERY_ONLY_NO_SELECTION",
                }
            )
    return pd.DataFrame(rows, columns=SEGMENT_PERFORMANCE_COLUMNS)


def build_pair_performance(trade_context: pd.DataFrame) -> pd.DataFrame:
    pairs = trade_context[trade_context["idea_type"].eq("PAIR")].copy()
    rows: list[dict] = []
    for dimension, column in [
        ("PAIR_RELATIONSHIP", "pair_relationship"),
        ("PAIR_SECTOR_ROUTE", "pair_sector_route"),
        ("PAIR_PEER_ROUTE", "pair_peer_route"),
    ]:
        for keys, cell in pairs.groupby(["primary_regime", "challenger_id", column], sort=True):
            regime, challenger_id, segment = keys
            pnl = pd.to_numeric(cell["risk_capped_net_pnl_sek"], errors="coerce").fillna(0.0)
            gross = pd.to_numeric(cell["risk_capped_gross_pnl_sek"], errors="coerce").fillna(0.0)
            costs = pd.to_numeric(cell["risk_capped_cost_sek"], errors="coerce").fillna(0.0)
            top_share, loo_share, loo_min = _concentration(cell)
            companies = set(cell["long_company_id"].dropna().astype(str)) | set(cell["short_company_id"].dropna().astype(str))
            companies.discard("")
            enough = len(cell) >= MINIMUM_SCREENING_TRADES and cell["date"].nunique() >= MINIMUM_SCREENING_SESSIONS and len(companies) >= MINIMUM_GROUP_COMPANIES
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "primary_regime": regime,
                    "challenger_id": challenger_id,
                    "strategy_family": str(cell["strategy_family"].iloc[0]),
                    "control_status": str(cell["control_status"].iloc[0]),
                    "analysis_dimension": dimension,
                    "segment_value": segment,
                    "trades": len(cell),
                    "sessions_with_trades": int(cell["date"].nunique()),
                    "independent_companies": len(companies),
                    "winning_trades_risk_capped": int((pnl > 0).sum()),
                    "win_rate_risk_capped": float((pnl > 0).mean()) if len(cell) else np.nan,
                    "gross_pnl_risk_capped_sek": float(gross.sum()),
                    "cost_risk_capped_sek": float(costs.sum()),
                    "net_pnl_risk_capped_sek": float(pnl.sum()),
                    "average_net_pnl_risk_capped_sek": float(pnl.mean()),
                    "profit_factor_risk_capped": _profit_factor(pnl),
                    "top_day_abs_pnl_share": top_share,
                    "leave_one_day_out_profitable_share": loo_share,
                    "leave_one_day_out_min_pnl_sek": loo_min,
                    "sample_status": "SCREENABLE_HIERARCHICAL_DISCOVERY" if enough else "INSUFFICIENT_SAMPLE",
                    "selection_status": "DISCOVERY_ONLY_NO_SELECTION",
                }
            )
    return pd.DataFrame(rows, columns=PAIR_PERFORMANCE_COLUMNS)


def build_exclusion_robustness(trade_context: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for (regime, challenger_id), cell in trade_context.groupby(["primary_regime", "challenger_id"], sort=True):
        baseline = float(pd.to_numeric(cell["risk_capped_net_pnl_sek"], errors="coerce").fillna(0.0).sum())
        strategy_family = str(cell["strategy_family"].iloc[0])
        control_status = str(cell["control_status"].iloc[0])
        company_sets = cell.apply(
            lambda row: {value for value in [row["primary_company_id"], row["long_company_id"], row["short_company_id"]] if value},
            axis=1,
        )
        sector_sets = cell.apply(
            lambda row: {value for value in [row["primary_broad_sector"], row["long_broad_sector"], row["short_broad_sector"]] if value},
            axis=1,
        )
        for exclusion_type, sets in [("COMPANY", company_sets), ("BROAD_SECTOR", sector_sets)]:
            universe = sorted(set().union(*sets.tolist())) if len(sets) else []
            for excluded in universe:
                mask = sets.map(lambda values: excluded in values)
                remaining = cell[~mask]
                remaining_pnl = float(pd.to_numeric(remaining["risk_capped_net_pnl_sek"], errors="coerce").fillna(0.0).sum())
                enough = len(remaining) >= MINIMUM_SCREENING_TRADES and remaining["date"].nunique() >= MINIMUM_SCREENING_SESSIONS
                rows.append(
                    {
                        "experiment_id": EXPERIMENT_ID,
                        "primary_regime": regime,
                        "challenger_id": challenger_id,
                        "strategy_family": strategy_family,
                        "control_status": control_status,
                        "exclusion_type": exclusion_type,
                        "excluded_value": excluded,
                        "baseline_trades": len(cell),
                        "excluded_trades": int(mask.sum()),
                        "remaining_trades": len(remaining),
                        "remaining_sessions": int(remaining["date"].nunique()),
                        "baseline_net_pnl_risk_capped_sek": baseline,
                        "remaining_net_pnl_risk_capped_sek": remaining_pnl,
                        "pnl_change_after_exclusion_sek": remaining_pnl - baseline,
                        "remaining_positive": remaining_pnl > 0,
                        "robustness_status": "SCREENABLE_AFTER_EXCLUSION" if enough else "INSUFFICIENT_AFTER_EXCLUSION",
                    }
                )
    return pd.DataFrame(rows, columns=EXCLUSION_COLUMNS)


def build_dimension_audit(static: pd.DataFrame) -> pd.DataFrame:
    configs = [
        ("BROAD_SECTOR", "broad_sector", "PRIMARY_BUSINESS_CLASSIFICATION"),
        ("ECONOMIC_CLUSTER", "economic_cluster", "MACRO_EXPOSURE_HYPOTHESIS"),
        ("PRIMARY_PEER_GROUP", "primary_peer_group", "CROSS_SECTOR_OR_INDUSTRY_PEER_HYPOTHESIS"),
    ]
    signatures = {name: _partition_signature(static, column) for name, column, _ in configs}
    rows = []
    for name, column, role in configs:
        counts = static.groupby(column)["company_id"].nunique()
        duplicate = ""
        for other_name, _, _ in configs:
            if other_name != name and signatures[other_name] == signatures[name]:
                if name == "ECONOMIC_CLUSTER" and other_name == "BROAD_SECTOR":
                    duplicate = other_name
                    break
        primary_eligible = not bool(duplicate)
        if name == "BROAD_SECTOR":
            guardrail = "Only groups with at least two independent companies are sector evidence; singleton sectors remain ticker proxies."
        elif name == "ECONOMIC_CLUSTER":
            guardrail = "Do not count as independent evidence when its company partition duplicates broad sector in the current universe."
        else:
            guardrail = "Peer groups are hypotheses; same-group results still require leave-one-company-out robustness."
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "dimension_name": name,
                "dimension_role": role,
                "group_count": int(counts.size),
                "multi_company_groups": int((counts >= MINIMUM_GROUP_COMPANIES).sum()),
                "single_company_groups": int((counts < MINIMUM_GROUP_COMPANIES).sum()),
                "independent_companies": int(static["company_id"].nunique()),
                "partition_signature": signatures[name],
                "duplicate_of_dimension": duplicate,
                "primary_screening_eligible": primary_eligible,
                "interpretation_guardrail": guardrail,
                "audit_status": "DESCRIPTIVE_REDUNDANT_CURRENT_UNIVERSE" if duplicate else "READY_WITH_GROUP_SIZE_GUARDRAILS",
            }
        )
    return pd.DataFrame(rows, columns=DIMENSION_AUDIT_COLUMNS)


def _normalized_entropy(counts: pd.Series) -> float:
    counts = pd.to_numeric(counts, errors="coerce").fillna(0.0)
    counts = counts[counts > 0]
    if len(counts) <= 1:
        return 0.0
    probabilities = counts / counts.sum()
    entropy = -float((probabilities * np.log(probabilities)).sum())
    return entropy / float(np.log(len(counts)))


def build_state_audit(characteristics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    configs = [
        ("TICKER_RELATIVE_STATE", "ticker_relative_state", False),
        ("VOLATILITY_BUCKET", "volatility_bucket", True),
        ("RANGE_STATE", "range_state", True),
        ("HISTORICAL_TENDENCY", "historical_tendency", True),
    ]
    for name, column, require_history in configs:
        frame = characteristics.copy()
        if require_history:
            frame = frame[frame["minimum_history_ready"].map(_bool)]
        values = frame[column].replace("", np.nan).dropna().astype(str)
        counts = values.value_counts()
        eligible = int(counts.sum())
        dominant = str(counts.index[0]) if not counts.empty else ""
        dominant_rows = int(counts.iloc[0]) if not counts.empty else 0
        share = float(dominant_rows / eligible) if eligible else np.nan
        entropy = _normalized_entropy(counts)
        if pd.isna(share):
            status = "NO_ELIGIBLE_ROWS"
        elif share > 0.80:
            status = "LOW_DISCRIMINATION_REVIEW_REQUIRED"
        elif share > 0.65:
            status = "CONCENTRATED_MONITOR"
        else:
            status = "BALANCED_ENOUGH_FOR_DISCOVERY"
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "parameter_name": name,
                "eligible_rows": eligible,
                "category_count": int(len(counts)),
                "dominant_category": dominant,
                "dominant_category_rows": dominant_rows,
                "dominant_share": share,
                "normalized_entropy": entropy,
                "discrimination_status": status,
                "router_active": False,
                "interpretation_guardrail": "Descriptive discovery segment only; concentrated parameters require revised definitions before router use.",
            }
        )
    return pd.DataFrame(rows, columns=STATE_AUDIT_COLUMNS)


def build_rankings(segment_performance: pd.DataFrame) -> pd.DataFrame:
    if segment_performance.empty:
        return pd.DataFrame(columns=RANKING_COLUMNS)
    screenable = segment_performance[segment_performance["sample_status"].eq("SCREENABLE_HIERARCHICAL_DISCOVERY")].copy()
    screenable["rank_within_regime_challenger_dimension"] = screenable.groupby(
        ["primary_regime", "challenger_id", "analysis_dimension"]
    )["net_pnl_risk_capped_sek"].rank(method="dense", ascending=False)
    screenable["selection_status"] = "DISCOVERY_ONLY_NO_SELECTION"
    return screenable.reindex(columns=RANKING_COLUMNS).sort_values(
        ["primary_regime", "challenger_id", "analysis_dimension", "rank_within_regime_challenger_dimension", "segment_value"]
    ).reset_index(drop=True)


def build_summary(
    trades: pd.DataFrame,
    legs: pd.DataFrame,
    trade_context: pd.DataFrame,
    leg_context: pd.DataFrame,
    static: pd.DataFrame,
    segment_performance: pd.DataFrame,
    pair_performance: pd.DataFrame,
    exclusion: pd.DataFrame,
    dimension_audit: pd.DataFrame,
    state_audit: pd.DataFrame,
) -> pd.DataFrame:
    broad_counts = static.groupby("broad_sector")["company_id"].nunique()
    peer_counts = static.groupby("primary_peer_group")["company_id"].nunique()
    all_group_counts = pd.concat(
        [
            static.groupby("broad_sector")["company_id"].nunique(),
            static.groupby("economic_cluster")["company_id"].nunique(),
            static.groupby("primary_peer_group")["company_id"].nunique(),
        ]
    )
    same_company_conflicts = int(trade_context["same_company_pair_conflict"].map(_bool).sum())
    trade_pit_fail = int((~trade_context["taxonomy_point_in_time_pass"].map(_bool)).sum())
    leg_pit_fail = int((~leg_context["taxonomy_point_in_time_pass"].map(_bool)).sum())
    redundant = int(dimension_audit["duplicate_of_dimension"].astype(str).ne("").sum())
    low_disc = int(state_audit["discrimination_status"].eq("LOW_DISCRIMINATION_REVIEW_REQUIRED").sum())
    complete = (
        len(trade_context) == len(trades)
        and len(leg_context) == len(legs)
        and same_company_conflicts == 0
        and trade_pit_fail == 0
        and leg_pit_fail == 0
    )
    classification = (
        "SECTOR_TICKER_EXPERIMENT_FOUNDATION_READY_FOR_HIERARCHICAL_REVIEW"
        if complete
        else "SECTOR_TICKER_EXPERIMENT_FOUNDATION_REQUIRES_MECHANICAL_REVIEW"
    )
    screenable = segment_performance[segment_performance["sample_status"].eq("SCREENABLE_HIERARCHICAL_DISCOVERY")]
    return pd.DataFrame(
        [
            {
                "experiment_id": EXPERIMENT_ID,
                "research_status": RESEARCH_STATUS,
                "source_trades": len(trades),
                "source_legs": len(legs),
                "enriched_trades": len(trade_context),
                "enriched_legs": len(leg_context),
                "single_trades": int(trade_context["idea_type"].eq("SINGLE").sum()),
                "paired_trades": int(trade_context["idea_type"].eq("PAIR").sum()),
                "independent_companies": int(static["company_id"].nunique()),
                "multi_company_broad_sectors": int((broad_counts >= MINIMUM_GROUP_COMPANIES).sum()),
                "multi_company_primary_peer_groups": int((peer_counts >= MINIMUM_GROUP_COMPANIES).sum()),
                "single_company_group_definitions": int((all_group_counts < MINIMUM_GROUP_COMPANIES).sum()),
                "redundant_group_dimensions": redundant,
                "low_discrimination_state_parameters": low_disc,
                "same_company_pair_conflicts": same_company_conflicts,
                "point_in_time_fail_trades": trade_pit_fail,
                "point_in_time_fail_legs": leg_pit_fail,
                "segment_performance_cells": len(segment_performance),
                "screenable_segment_cells": len(screenable),
                "positive_net_screenable_segment_cells": int(screenable["net_pnl_risk_capped_sek"].gt(0).sum()),
                "pair_performance_cells": len(pair_performance),
                "exclusion_robustness_rows": len(exclusion),
                "strategies_promoted": 0,
                "router_active": False,
                "classification": classification,
            }
        ],
        columns=SUMMARY_COLUMNS,
    )


def build_outputs(
    trades: pd.DataFrame,
    legs: pd.DataFrame,
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
):
    trade_context = enrich_trade_context(trades, static, characteristics, group_states)
    leg_context = enrich_leg_context(legs, static, characteristics, group_states)
    segment_performance = build_segment_performance(trade_context, static)
    pair_performance = build_pair_performance(trade_context)
    exclusion = build_exclusion_robustness(trade_context)
    dimension_audit = build_dimension_audit(static)
    state_audit = build_state_audit(characteristics)
    rankings = build_rankings(segment_performance)
    summary = build_summary(
        trades, legs, trade_context, leg_context, static, segment_performance,
        pair_performance, exclusion, dimension_audit, state_audit,
    )
    return (
        summary, trade_context, leg_context, segment_performance, pair_performance,
        exclusion, dimension_audit, state_audit, rankings,
    )


def run_experiments(
    trade_file: Path = TRADE_SOURCE_FILE,
    leg_file: Path = LEG_SOURCE_FILE,
    static_file: Path = STATIC_SOURCE_FILE,
    characteristic_file: Path = CHARACTERISTIC_SOURCE_FILE,
    group_file: Path = GROUP_SOURCE_FILE,
):
    required = [trade_file, leg_file, static_file, characteristic_file, group_file]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required Step 9D/9E outputs: " + ", ".join(str(path) for path in missing))
    return build_outputs(
        pd.read_csv(trade_file),
        pd.read_csv(leg_file),
        pd.read_csv(static_file),
        pd.read_csv(characteristic_file),
        pd.read_csv(group_file),
    )


def main() -> None:
    print("\n=== STEP 9F REGIME × STRATEGY × SECTOR/TICKER EXPERIMENTS ===")
    print(f"Experiment       : {EXPERIMENT_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print("Step 9D trades remain frozen; this step adds hierarchical sector, company, ticker, and state diagnostics.")
    print("Single-company groups are proxies, redundant dimensions are not double-counted, and no router rule is activated.")

    outputs = run_experiments()
    paths = [
        SUMMARY_FILE, TRADE_CONTEXT_FILE, LEG_CONTEXT_FILE, SEGMENT_PERFORMANCE_FILE,
        PAIR_PERFORMANCE_FILE, EXCLUSION_ROBUSTNESS_FILE, DIMENSION_AUDIT_FILE,
        STATE_AUDIT_FILE, RANKING_FILE,
    ]
    for dataframe, path in zip(outputs, paths):
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")

    result = outputs[0].iloc[0]
    print("\n=== STEP 9F SECTOR/TICKER EXPERIMENT RESULT ===")
    print(f"Source / enriched trades      : {int(result['source_trades'])}/{int(result['enriched_trades'])}")
    print(f"Source / enriched legs        : {int(result['source_legs'])}/{int(result['enriched_legs'])}")
    print(f"Single / paired trades        : {int(result['single_trades'])}/{int(result['paired_trades'])}")
    print(f"Independent companies         : {int(result['independent_companies'])}")
    print(f"Multi-company sectors / peers : {int(result['multi_company_broad_sectors'])}/{int(result['multi_company_primary_peer_groups'])}")
    print(f"Singleton group definitions   : {int(result['single_company_group_definitions'])}")
    print(f"Redundant group dimensions    : {int(result['redundant_group_dimensions'])}")
    print(f"Low-discrimination parameters : {int(result['low_discrimination_state_parameters'])}")
    print(f"Same-company pair conflicts   : {int(result['same_company_pair_conflicts'])}")
    print(f"PIT fail trades / legs        : {int(result['point_in_time_fail_trades'])}/{int(result['point_in_time_fail_legs'])}")
    print(f"Segment/screenable cells      : {int(result['segment_performance_cells'])}/{int(result['screenable_segment_cells'])}")
    print(f"Positive screenable cells     : {int(result['positive_net_screenable_segment_cells'])}")
    print(f"Strategies promoted           : {int(result['strategies_promoted'])}")
    print(f"Classification                : {result['classification']}")
    print("Step 9F export complete. Results are hierarchical discovery evidence only.")


if __name__ == "__main__":
    main()
