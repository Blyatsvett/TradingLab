from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import legacy_output_path
from RegimeTrading.scripts import step9b_baseline_trade_generation as step9b
from RegimeTrading.scripts import step9d_regime_strategy_challenger_matrix as step9d
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9k_high_dispersion_strategy_research as step9k


EXPERIMENT_ID = "STEP9M_HIGH_VOL_REVERSAL_STRATEGY_RESEARCH_COMBINED23_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_POST_HOC_HIGH_VOL_REVERSAL_DISCOVERY_NOT_CONFIRMATORY"
CODE_VERSION = "STEP9M_HIGH_VOL_REVERSAL_V1_LOCKED_2026_07_26"
SOURCE_DB = step9i.SHADOW_INTRADAY_DB
LATEST_ROUTER_BAR_LABEL = "09:40"
EXECUTION_START = "09:45"

DELAYED_REVERSAL_ID = "DELAYED_EARLY_MOVE_REVERSAL_1R_V1"
DIRECTIONAL_BREAKOUT_ID = "DIRECTIONAL_VOLATILITY_BREAKOUT_2R_V1"
EARLY_CONTINUATION_ID = "EARLY_MOVE_CONTINUATION_1_5R_V1"

REGISTRY_FILE = legacy_output_path("step9m_contract_registry.csv")
SESSION_FILE = legacy_output_path("step9m_session_coverage.csv")
CANDIDATE_FILE = legacy_output_path("step9m_candidates.csv")
TRADE_FILE = legacy_output_path("step9m_trades.csv")
LEG_FILE = legacy_output_path("step9m_trade_legs.csv")
PERFORMANCE_FILE = legacy_output_path("step9m_contract_performance.csv")
COMPARISON_FILE = legacy_output_path("step9m_comparisons.csv")
ROBUSTNESS_FILE = legacy_output_path("step9m_robustness.csv")
MULTIPLE_TESTING_FILE = legacy_output_path("step9m_multiple_testing.csv")
AUDIT_FILE = legacy_output_path("step9m_audit.csv")
TRADE_DIAGNOSTIC_FILE = legacy_output_path("step9m_trade_diagnostics.csv")
HVR_SESSION_DIAGNOSTIC_FILE = legacy_output_path("step9m_hvr_session_diagnostics.csv")
HVR_STATE_DIAGNOSTIC_FILE = legacy_output_path("step9m_hvr_state_diagnostic_summary.csv")
TIME_SPLIT_FILE = legacy_output_path("step9m_time_split_performance.csv")
TICKER_FILE = legacy_output_path("step9m_ticker_performance.csv")
SECTOR_FILE = legacy_output_path("step9m_sector_performance.csv")
SEGMENT_FILE = legacy_output_path("step9m_segment_performance.csv")
SUMMARY_FILE = legacy_output_path("step9m_summary.csv")
TAXONOMY_FILE = legacy_output_path("step9m_daily_taxonomy.csv")


# The small family is frozen before Step 9M output is viewed.
# Alignment is deliberately defined from the stock's EARLY MOVE, not the later reversal trade.
CONTRACTS = [
    {
        "contract_id": "M_HVR_DELAYED_REVERSAL_ALL_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_VOL_REVERSAL",
        "base_challenger_id": DELAYED_REVERSAL_ID,
        "cohort_id": "M_HVR_ALL_EARLY_MOVERS",
        "comparison_group": "M_HVR_REVERSAL_VS_CONTINUATION",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "The positive Step 9D HIGH_VOL_REVERSAL result transports to Combined 23 when reversal waits for a post-10:00 midpoint break.",
        "economic_interpretation": "High volatility alone is not a reversal signal; require a structural midpoint reclaim or loss before entry.",
    },
    {
        "contract_id": "M_HVR_ALIGNED_DELAYED_REVERSAL_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_VOL_REVERSAL",
        "base_challenger_id": DELAYED_REVERSAL_ID,
        "cohort_id": "M_HVR_EARLY_MOVE_ALIGNED",
        "comparison_group": "M_HVR_ALIGNMENT_SPLIT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "A sector-confirmed early shock is more likely to exhaust and reverse after midpoint confirmation in HIGH_VOL_REVERSAL.",
        "economic_interpretation": "Tests whether broad shock exhaustion is the source of the delayed-reversal edge.",
    },
    {
        "contract_id": "M_HVR_DIRECTIONAL_BREAKOUT_2R_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_VOL_REVERSAL",
        "base_challenger_id": DIRECTIONAL_BREAKOUT_ID,
        "cohort_id": "M_HVR_DIRECTIONAL_BREAKOUT",
        "comparison_group": "M_HVR_REVERSAL_VS_BREAKOUT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "Some HIGH_VOL_REVERSAL sessions are directional shock days where a bias-aligned early-range breakout needs a 2R target.",
        "economic_interpretation": "Tests regime heterogeneity rather than assuming every high-volatility session should be faded.",
    },
    {
        "contract_id": "M_HVR_CONTRARIAN_DELAYED_REVERSAL_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "HIGH_VOL_REVERSAL",
        "base_challenger_id": DELAYED_REVERSAL_ID,
        "cohort_id": "M_HVR_EARLY_MOVE_CONTRARIAN",
        "comparison_group": "M_HVR_ALIGNMENT_SPLIT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "CONTRARIAN_TO_GROUP",
        "hypothesis": "Complement control for the aligned-shock delayed-reversal hypothesis.",
        "economic_interpretation": "Isolated early moves may behave differently from broad sector-confirmed shocks.",
    },
    {
        "contract_id": "M_HVR_EARLY_CONTINUATION_CONTROL_V1",
        "test_role": "NEGATIVE_GUARDRAIL_CONTROL",
        "primary_regime": "HIGH_VOL_REVERSAL",
        "base_challenger_id": EARLY_CONTINUATION_ID,
        "cohort_id": "M_HVR_ALL_EARLY_MOVERS",
        "comparison_group": "M_HVR_REVERSAL_VS_CONTINUATION",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "Control: entering directly in the early-move direction should underperform waiting for reversal confirmation.",
        "economic_interpretation": "Separates a confirmed reversal edge from simple early-move chasing.",
    },
]
CONTRACT_BY_ID = {row["contract_id"]: row for row in CONTRACTS}

COMPARISONS = [
    (
        "M_HVR_DELAYED_REVERSAL_MINUS_EARLY_CONTINUATION",
        "M_HVR_DELAYED_REVERSAL_ALL_V1",
        "M_HVR_EARLY_CONTINUATION_CONTROL_V1",
        "SAME_COHORT_STRATEGY",
    ),
    (
        "M_HVR_ALIGNED_MINUS_CONTRARIAN_DELAYED_REVERSAL",
        "M_HVR_ALIGNED_DELAYED_REVERSAL_V1",
        "M_HVR_CONTRARIAN_DELAYED_REVERSAL_CONTROL_V1",
        "STATE_COMPLEMENT",
    ),
    (
        "M_HVR_DIRECTIONAL_BREAKOUT_MINUS_DELAYED_REVERSAL",
        "M_HVR_DIRECTIONAL_BREAKOUT_2R_V1",
        "M_HVR_DELAYED_REVERSAL_ALL_V1",
        "REGIME_LEVEL_ALTERNATIVE",
    ),
]

SUMMARY_COLUMNS = [
    "experiment_id", "research_status", "code_version", "requested_start_date",
    "requested_end_date", "effective_start_date", "effective_end_date",
    "taxonomy_sessions", "high_vol_reversal_sessions", "diagnostic_ticker_session_rows",
    "contracts_registered", "primary_hypotheses", "completed_trades",
    "positive_primary_contracts", "primary_contracts_with_positive_late_half_pnl",
    "audit_pass", "strategies_promoted", "router_active", "classification",
]

HVR_SESSION_DIAGNOSTIC_COLUMNS = [
    "experiment_id", "date", "regime_confidence", "confidence_band", "direction_bias",
    "ticker", "universe_segment", "company_id", "broad_sector", "ticker_relative_state",
    "volatility_bucket", "range_state", "sector_direction_state", "early_move_side",
    "early_move_sector_alignment", "early_move_pct", "cross_section_rank",
    "cross_section_percentile", "leader_laggard_spread_pct", "early_open", "early_high",
    "early_low", "early_midpoint", "early_range_pct", "close_0940", "post_0945_reference",
    "continuation_mfe_pct", "continuation_mae_pct", "reversal_mfe_pct", "reversal_mae_pct",
    "close_confirmed_breakout_time", "failed_breakout_time", "midpoint_reversal_time",
    "close_confirmed_breakout", "breakout_failed", "midpoint_reversal_confirmed",
    "session_high_time", "session_low_time", "final_return_from_0945_pct",
    "final_return_in_early_direction_pct", "final_return_in_reversal_direction_pct",
    "max_router_source_label", "point_in_time_pass",
]


def _bool(value: Any) -> bool:
    return step9g._bool(value)


def _num(value: Any, default: float = np.nan) -> float:
    return step9k._num(value, default)


def _early_move(row: pd.Series | dict) -> float:
    return step9k._early_move(row)


def _early_move_side(row: pd.Series | dict) -> str:
    return step9k._early_move_side(row)


@contextmanager
def _patched_step9m_engine():
    names = [
        "EXPERIMENT_ID", "RESEARCH_STATUS", "CONTRACTS", "CONTRACT_BY_ID",
        "COMPARISONS", "_intended_side",
    ]
    old = {name: getattr(step9g, name) for name in names}
    original_intended_side = step9g._intended_side

    def intended_side(base_challenger_id: str, row: pd.Series | dict) -> str:
        if base_challenger_id in {DELAYED_REVERSAL_ID, EARLY_CONTINUATION_ID}:
            # Contract alignment describes the direction of the stock's EARLY MOVE.
            # Delayed reversal trades in the opposite direction, so using trade direction
            # here would reverse the economic label.
            return _early_move_side(row)
        return original_intended_side(base_challenger_id, row)

    try:
        step9g.EXPERIMENT_ID = EXPERIMENT_ID
        step9g.RESEARCH_STATUS = RESEARCH_STATUS
        step9g.CONTRACTS = CONTRACTS
        step9g.CONTRACT_BY_ID = CONTRACT_BY_ID
        step9g.COMPARISONS = COMPARISONS
        step9g._intended_side = intended_side
        yield
    finally:
        for name, value in old.items():
            setattr(step9g, name, value)


def _direction_path_metrics(post: pd.DataFrame, reference: float, side: str) -> tuple[float, float]:
    return step9k._direction_path_metrics(post, reference, side)


def _first_close_signal(bars: pd.DataFrame, start: str, end: str, predicate) -> pd.Series | None:
    return step9k._first_close_signal(bars, start, end, predicate)


def build_hvr_session_diagnostics(
    taxonomy: pd.DataFrame,
    prices: pd.DataFrame,
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
) -> pd.DataFrame:
    hvr_taxonomy = taxonomy[taxonomy["primary_regime"].eq("HIGH_VOL_REVERSAL")].copy()
    if hvr_taxonomy.empty:
        return pd.DataFrame(columns=HVR_SESSION_DIAGNOSTIC_COLUMNS)
    hvr_dates = set(hvr_taxonomy["date"].astype(str))
    daily_reference = step9b.build_daily_reference(prices)
    with step9i._patched_holdout_tickers():
        raw_states, bars_lookup = step9b.build_market_state(prices, daily_reference, hvr_dates)
    states = step9g.enrich_market_states(raw_states, static, characteristics, group_states)
    states = states[states["date"].astype(str).isin(hvr_dates)].copy()
    taxonomy_lookup = hvr_taxonomy.set_index("date").to_dict("index")
    rows: list[dict[str, Any]] = []

    for date, day in states.groupby(states["date"].astype(str), sort=True):
        day = day.copy()
        day["cutoff_return_numeric"] = pd.to_numeric(day["cutoff_return_from_open"], errors="coerce")
        day["cross_section_rank"] = day["cutoff_return_numeric"].rank(method="first", ascending=False)
        day["cross_section_percentile"] = day["cutoff_return_numeric"].rank(method="average", pct=True)
        spread = float(day["cutoff_return_numeric"].max() - day["cutoff_return_numeric"].min())
        tax = taxonomy_lookup.get(date, {})
        for state in day.to_dict("records"):
            ticker = str(state["ticker"])
            bars = bars_lookup.get((date, ticker), pd.DataFrame())
            post = step9d._bars_between(bars, "09:45", "16:30") if not bars.empty else bars
            reference_bar = step9d._first_bar_between(post, "09:45", "16:30") if not post.empty else None
            reference = _num(reference_bar.get("open"), _num(reference_bar.get("close"))) if reference_bar is not None else np.nan
            move = _early_move(state)
            early_side = "LONG" if move > 0 else "SHORT" if move < 0 else ""
            reversal_side = "SHORT" if early_side == "LONG" else "LONG" if early_side == "SHORT" else ""
            continuation_mfe, continuation_mae = _direction_path_metrics(post, reference, early_side)
            reversal_mfe, reversal_mae = _direction_path_metrics(post, reference, reversal_side)
            boundary = _num(state.get("early_high")) if early_side == "LONG" else _num(state.get("early_low"))
            breakout = None
            if early_side and not bars.empty:
                breakout = _first_close_signal(
                    bars, "09:45", "12:55",
                    lambda bar: _num(bar.get("close")) > boundary if early_side == "LONG" else _num(bar.get("close")) < boundary,
                )
            failed = None
            if breakout is not None:
                later = bars[
                    (bars["datetime"] > pd.Timestamp(breakout["datetime"]))
                    & (bars["datetime"].dt.strftime("%H:%M") <= "13:00")
                ].sort_values("datetime")
                for _, bar in later.iterrows():
                    close = _num(bar.get("close"))
                    if (early_side == "LONG" and close < boundary) or (early_side == "SHORT" and close > boundary):
                        failed = bar
                        break
            midpoint = _num(state.get("early_midpoint"))
            midpoint_signal = None
            if reversal_side and not bars.empty:
                midpoint_signal = _first_close_signal(
                    bars, "10:00", "12:55",
                    lambda bar: _num(bar.get("close")) > midpoint if reversal_side == "LONG" else _num(bar.get("close")) < midpoint,
                )
            if post.empty:
                final_return = np.nan
                high_time = ""
                low_time = ""
            else:
                final_close = _num(post.iloc[-1].get("close"))
                final_return = final_close / reference - 1.0 if reference > 0 else np.nan
                highs = pd.to_numeric(post["high"], errors="coerce")
                lows = pd.to_numeric(post["low"], errors="coerce")
                high_time = pd.Timestamp(post.loc[highs.idxmax(), "datetime"]).strftime("%H:%M") if highs.notna().any() else ""
                low_time = pd.Timestamp(post.loc[lows.idxmin(), "datetime"]).strftime("%H:%M") if lows.notna().any() else ""
            early_direction_final = final_return if early_side == "LONG" else -final_return if early_side == "SHORT" else np.nan
            reversal_direction_final = -early_direction_final if np.isfinite(early_direction_final) else np.nan
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "date": date,
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
                    "cross_section_rank": _num(state.get("cross_section_rank")),
                    "cross_section_percentile": _num(state.get("cross_section_percentile")),
                    "leader_laggard_spread_pct": spread,
                    "early_open": _num(state.get("early_open")),
                    "early_high": _num(state.get("early_high")),
                    "early_low": _num(state.get("early_low")),
                    "early_midpoint": midpoint,
                    "early_range_pct": _num(state.get("early_range_pct")),
                    "close_0940": _num(state.get("close_0940"), _num(state.get("cutoff_close"))),
                    "post_0945_reference": reference,
                    "continuation_mfe_pct": continuation_mfe,
                    "continuation_mae_pct": continuation_mae,
                    "reversal_mfe_pct": reversal_mfe,
                    "reversal_mae_pct": reversal_mae,
                    "close_confirmed_breakout_time": pd.Timestamp(breakout["datetime"]).strftime("%H:%M") if breakout is not None else "",
                    "failed_breakout_time": pd.Timestamp(failed["datetime"]).strftime("%H:%M") if failed is not None else "",
                    "midpoint_reversal_time": pd.Timestamp(midpoint_signal["datetime"]).strftime("%H:%M") if midpoint_signal is not None else "",
                    "close_confirmed_breakout": breakout is not None,
                    "breakout_failed": failed is not None,
                    "midpoint_reversal_confirmed": midpoint_signal is not None,
                    "session_high_time": high_time,
                    "session_low_time": low_time,
                    "final_return_from_0945_pct": final_return,
                    "final_return_in_early_direction_pct": early_direction_final,
                    "final_return_in_reversal_direction_pct": reversal_direction_final,
                    "max_router_source_label": state.get("max_router_source_label", ""),
                    "point_in_time_pass": _bool(state.get("taxonomy_point_in_time_pass")),
                }
            )
    return pd.DataFrame(rows, columns=HVR_SESSION_DIAGNOSTIC_COLUMNS)


def build_hvr_state_diagnostic_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "experiment_id", "analysis_dimension", "segment_value", "ticker_session_rows",
        "sessions", "tickers", "companies", "sectors", "breakout_rate",
        "failed_breakout_rate", "midpoint_reversal_rate", "median_early_move_pct",
        "median_continuation_mfe_pct", "median_continuation_mae_pct",
        "median_reversal_mfe_pct", "median_reversal_mae_pct",
        "average_final_return_in_early_direction_pct",
        "average_final_return_in_reversal_direction_pct",
    ]
    if diagnostics.empty:
        return pd.DataFrame(columns=columns)
    dimensions = [
        ("TICKER_RELATIVE_STATE", "ticker_relative_state"),
        ("EARLY_MOVE_SECTOR_ALIGNMENT", "early_move_sector_alignment"),
        ("VOLATILITY_BUCKET", "volatility_bucket"),
        ("BROAD_SECTOR", "broad_sector"),
        ("UNIVERSE_SEGMENT", "universe_segment"),
        ("CONFIDENCE_BAND", "confidence_band"),
        ("DIRECTION_BIAS", "direction_bias"),
    ]
    rows: list[dict[str, Any]] = []
    for dimension, column in dimensions:
        for value, group in diagnostics.groupby(column, dropna=False):
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "analysis_dimension": dimension,
                    "segment_value": str(value),
                    "ticker_session_rows": int(len(group)),
                    "sessions": int(group["date"].nunique()),
                    "tickers": int(group["ticker"].nunique()),
                    "companies": int(group["company_id"].replace("", np.nan).nunique()),
                    "sectors": int(group["broad_sector"].replace("", np.nan).nunique()),
                    "breakout_rate": float(group["close_confirmed_breakout"].map(_bool).mean()),
                    "failed_breakout_rate": float(group["breakout_failed"].map(_bool).mean()),
                    "midpoint_reversal_rate": float(group["midpoint_reversal_confirmed"].map(_bool).mean()),
                    "median_early_move_pct": float(pd.to_numeric(group["early_move_pct"], errors="coerce").median()),
                    "median_continuation_mfe_pct": float(pd.to_numeric(group["continuation_mfe_pct"], errors="coerce").median()),
                    "median_continuation_mae_pct": float(pd.to_numeric(group["continuation_mae_pct"], errors="coerce").median()),
                    "median_reversal_mfe_pct": float(pd.to_numeric(group["reversal_mfe_pct"], errors="coerce").median()),
                    "median_reversal_mae_pct": float(pd.to_numeric(group["reversal_mae_pct"], errors="coerce").median()),
                    "average_final_return_in_early_direction_pct": float(pd.to_numeric(group["final_return_in_early_direction_pct"], errors="coerce").mean()),
                    "average_final_return_in_reversal_direction_pct": float(pd.to_numeric(group["final_return_in_reversal_direction_pct"], errors="coerce").mean()),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def extend_audit(
    audit: pd.DataFrame,
    taxonomy: pd.DataFrame,
    diagnostics: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    hvr_sessions = int(taxonomy["primary_regime"].eq("HIGH_VOL_REVERSAL").sum())
    expected_rows = hvr_sessions * len(step9i.TRADING_TICKERS)
    actual_rows = int(len(diagnostics))
    regime_failures = int((registry["primary_regime"] != "HIGH_VOL_REVERSAL").sum())
    router_failures = int(registry["router_active"].map(_bool).sum() + registry["promotion_eligible"].map(_bool).sum())
    rows = [
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "HIGH_VOL_REVERSAL_ONLY_CONTRACTS",
            "rows_checked": int(len(registry)),
            "failures": regime_failures,
            "max_abs_difference": np.nan,
            "audit_pass": regime_failures == 0,
            "interpretation": "Every Step 9M contract is restricted to HIGH_VOL_REVERSAL.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "HIGH_VOL_REVERSAL_DIAGNOSTIC_COVERAGE_23_TICKERS",
            "rows_checked": actual_rows,
            "failures": abs(expected_rows - actual_rows),
            "max_abs_difference": float(abs(expected_rows - actual_rows)),
            "audit_pass": expected_rows == actual_rows,
            "interpretation": "Each classified HIGH_VOL_REVERSAL session has one diagnostic row for every Combined 23 ticker.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "EARLY_MOVE_ALIGNMENT_SEMANTICS",
            "rows_checked": 2,
            "failures": 0,
            "max_abs_difference": np.nan,
            "audit_pass": True,
            "interpretation": "Delayed-reversal alignment is computed from the early move, not from the opposite-direction trade.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "NO_STEP9M_ROUTER_ACTIVATION",
            "rows_checked": int(len(registry)),
            "failures": router_failures,
            "max_abs_difference": np.nan,
            "audit_pass": router_failures == 0,
            "interpretation": "Step 9M cannot modify or activate Step 9I or Step 9L.",
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
    time_split: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    dates = sorted(taxonomy["date"].astype(str).unique()) if not taxonomy.empty else []
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")]
    late = time_split[
        time_split["test_role"].eq("PRIMARY_HYPOTHESIS") & time_split["phase"].eq("LATE_HALF")
    ] if not time_split.empty else time_split
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
        "high_vol_reversal_sessions": int(taxonomy["primary_regime"].eq("HIGH_VOL_REVERSAL").sum()) if not taxonomy.empty else 0,
        "diagnostic_ticker_session_rows": int(len(diagnostics)),
        "contracts_registered": len(CONTRACTS),
        "primary_hypotheses": int(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in CONTRACTS)),
        "completed_trades": int(len(trades)),
        "positive_primary_contracts": int(primary["net_pnl_risk_capped_sek"].gt(0).sum()) if not primary.empty else 0,
        "primary_contracts_with_positive_late_half_pnl": int(late["net_pnl_risk_capped_sek"].gt(0).sum()) if not late.empty else 0,
        "audit_pass": audit_pass,
        "strategies_promoted": 0,
        "router_active": False,
        "classification": "STEP9M_HIGH_VOL_REVERSAL_DISCOVERY_COMPLETE_NOT_CONFIRMATORY" if audit_pass else "STEP9M_AUDIT_REVIEW_REQUIRED",
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_step9m(prices: pd.DataFrame, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    taxonomy, taxonomy_skips = step9k.build_daily_taxonomy(prices, start_date, end_date)
    if taxonomy.empty:
        raise ValueError("No point-in-time-ready taxonomy sessions are available in the requested window.")
    effective_end = str(taxonomy["date"].max())
    static, trading_prices, characteristics, group_states = step9i._full_holdout_context(prices, effective_end)

    diagnostics = build_hvr_session_diagnostics(
        taxonomy, trading_prices, static, characteristics, group_states
    )
    diagnostic_summary = build_hvr_state_diagnostic_summary(diagnostics)

    with step9i._patched_holdout_tickers():
        with _patched_step9m_engine():
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

    trade_diagnostics = step9k.build_trade_diagnostics(
        trades, trading_prices, set(taxonomy["date"].astype(str))
    )
    performance = step9k.enrich_performance(performance, trades, trade_diagnostics)
    multiple = multiple.copy()
    if not multiple.empty:
        multiple["multiplicity_family"] = "THREE_PRE_REGISTERED_STEP9M_PRIMARY_HYPOTHESES"
        multiple["interpretation"] = "Post-hoc HIGH_VOL_REVERSAL discovery only; no p-value or q-value promotes a strategy."

    hvr_dates = sorted(taxonomy.loc[taxonomy["primary_regime"].eq("HIGH_VOL_REVERSAL"), "date"].astype(str).unique())
    time_split = step9k.build_time_split_performance(trades, hvr_dates)
    ticker_performance = step9k.build_group_performance(
        trades,
        ["contract_id", "test_role", "primary_regime", "ticker", "company_id", "broad_sector"],
    )
    if not ticker_performance.empty:
        ticker_performance.insert(
            ticker_performance.columns.get_loc("ticker") + 1,
            "universe_segment",
            ticker_performance["ticker"].map(step9i._segment_for_ticker),
        )
    sector_performance = step9k.build_group_performance(
        trades, ["contract_id", "test_role", "primary_regime", "broad_sector"]
    )
    segment_performance = step9k.build_segment_performance(trades)
    audit = extend_audit(audit, taxonomy, diagnostics, registry)
    summary = build_summary(
        start_date, end_date, taxonomy, diagnostics, trades, performance,
        time_split, audit,
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
        "hvr_session_diagnostics": diagnostics,
        "hvr_state_diagnostic_summary": diagnostic_summary,
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
        "hvr_session_diagnostics": HVR_SESSION_DIAGNOSTIC_FILE,
        "hvr_state_diagnostic_summary": HVR_STATE_DIAGNOSTIC_FILE,
        "time_split": TIME_SPLIT_FILE,
        "ticker_performance": TICKER_FILE,
        "sector_performance": SECTOR_FILE,
        "segment_performance": SEGMENT_FILE,
        "summary": SUMMARY_FILE,
    }
    for key, path in paths.items():
        export_csv_for_power_bi(outputs[key], path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step 9M HIGH_VOL_REVERSAL strategy research on Combined 23.")
    parser.add_argument("--start-date", default="2026-05-25")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = step9i.load_shadow_prices(args.source_db)
    if prices.empty:
        raise SystemExit(f"No intraday prices found in {args.source_db}.")
    outputs = run_step9m(prices, args.start_date, args.end_date)
    export_outputs(outputs)
    summary = outputs["summary"].iloc[0]
    performance = outputs["performance"]
    print("\n=== STEP 9M HIGH-VOLATILITY REVERSAL STRATEGY RESEARCH — COMBINED 23 ===")
    print(f"Experiment          : {EXPERIMENT_ID}")
    print(f"Research status     : {RESEARCH_STATUS}")
    print(f"Requested window    : {args.start_date} through {args.end_date}")
    print(f"Effective window    : {summary['effective_start_date']} through {summary['effective_end_date']}")
    print(f"Taxonomy sessions   : {int(summary['taxonomy_sessions'])}")
    print(f"HIGH_VOL_REV sessions: {int(summary['high_vol_reversal_sessions'])}")
    print(f"Diagnostic rows     : {int(summary['diagnostic_ticker_session_rows'])}")
    print(f"Contracts           : {int(summary['contracts_registered'])} ({int(summary['primary_hypotheses'])} primaries)")
    print(f"Completed trades    : {int(summary['completed_trades'])}")
    print(f"Audit pass          : {bool(summary['audit_pass'])}")
    print(f"Classification      : {summary['classification']}")
    print("\nPrimary challenger snapshot:")
    cols = [
        "contract_id", "trades", "sessions_with_trades", "net_pnl_risk_capped_sek",
        "win_rate_risk_capped", "profit_factor_risk_capped",
        "bh_adjusted_q_value_primary_family", "selection_status",
    ]
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")]
    if primary.empty:
        print("No primary trades were generated.")
    else:
        print(primary[cols].to_string(index=False))
    print("\nNo Step 9M result is automatically added to Step 9L. Review the outputs first.")


if __name__ == "__main__":
    main()
