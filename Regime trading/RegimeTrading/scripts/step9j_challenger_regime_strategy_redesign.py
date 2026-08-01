from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.scripts import step9b_baseline_trade_generation as step9b
from RegimeTrading.scripts import step9d_regime_strategy_challenger_matrix as step9d
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_prospective_shadow_router as step9i


EXPERIMENT_ID = "STEP9J_CHALLENGER_REGIME_STRATEGY_REDESIGN_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_POST_HOC_REDESIGN_DISCOVERY_NOT_CONFIRMATORY"
CODE_VERSION = "STEP9J_REDESIGN_V1_LOCKED_2026_07_26"
LATEST_ROUTER_BAR_LABEL = "09:40"
EXECUTION_START = "09:45"
PULLBACK_CHALLENGER_ID = "ORB_BREAKOUT_PULLBACK_HOLD_1_5R_V1"

SOURCE_DB = step9i.SHADOW_INTRADAY_DB

REGISTRY_FILE = DATA_DIR / "step9j_challenger_registry.csv"
SESSION_FILE = DATA_DIR / "step9j_session_coverage.csv"
CANDIDATE_FILE = DATA_DIR / "step9j_challenger_candidates.csv"
TRADE_FILE = DATA_DIR / "step9j_challenger_trades.csv"
LEG_FILE = DATA_DIR / "step9j_challenger_trade_legs.csv"
PERFORMANCE_FILE = DATA_DIR / "step9j_challenger_performance.csv"
COMPARISON_FILE = DATA_DIR / "step9j_challenger_comparisons.csv"
ROBUSTNESS_FILE = DATA_DIR / "step9j_challenger_robustness.csv"
MULTIPLE_TESTING_FILE = DATA_DIR / "step9j_challenger_multiple_testing.csv"
AUDIT_FILE = DATA_DIR / "step9j_challenger_audit.csv"
DIAGNOSTIC_FILE = DATA_DIR / "step9j_trade_diagnostics.csv"
TIME_SPLIT_FILE = DATA_DIR / "step9j_time_split_performance.csv"
TICKER_FILE = DATA_DIR / "step9j_ticker_performance.csv"
SECTOR_FILE = DATA_DIR / "step9j_sector_performance.csv"
SUMMARY_FILE = DATA_DIR / "step9j_summary.csv"
TAXONOMY_FILE = DATA_DIR / "step9j_daily_taxonomy.csv"


PULLBACK_CHALLENGER = {
    "challenger_id": PULLBACK_CHALLENGER_ID,
    "strategy_family": "BREAKOUT_PULLBACK_CONTINUATION",
    "control_status": "CHALLENGER",
    "idea_type": "SINGLE",
    "hypothesis": "A close-confirmed opening-range break that retests and holds the broken boundary improves trend continuation quality.",
    "entry_model": "Close beyond strict 09:30-09:40 range, later retest-and-hold of the broken boundary, then next-bar open through 13:00.",
    "stop_model": "Strict early-range midpoint.",
    "target_model": "1.5R from actual entry.",
    "exit_cutoff": "16:30",
    "selection_model": "Rank absolute 09:40 return; use the frozen regime maximum concurrent ideas.",
    "direction_model": "EARLY_MOVE_DIRECTION_WITH_GROUP_ALIGNMENT",
    "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
    "diagnostic_source": "Redesign of underperforming TREND_UP range rejection; tests continuation after a confirmed retest rather than fading strength.",
    "ranking_eligible": True,
}


# Fixed before Step 9J results are viewed. These are redesign-discovery contracts,
# not replacements for Step 9I and never activate the router automatically.
CONTRACTS = [
    {
        "contract_id": "J_TU_ALIGNED_LEADER_CLOSE_ORB_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "TREND_UP",
        "base_challenger_id": "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1",
        "cohort_id": "J_TU_ALIGNED_EARLY_LEADER",
        "comparison_group": "J_TU_EXECUTION_REDESIGN",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "In TREND_UP, an early leader aligned with its sector continues after a close-confirmed opening-range break.",
        "economic_interpretation": "Join broad and stock-level strength instead of fading it.",
    },
    {
        "contract_id": "J_TU_ALIGNED_LEADER_PULLBACK_HOLD_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "TREND_UP",
        "base_challenger_id": PULLBACK_CHALLENGER_ID,
        "cohort_id": "J_TU_ALIGNED_EARLY_LEADER",
        "comparison_group": "J_TU_EXECUTION_REDESIGN",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "In TREND_UP, an aligned early leader performs better after a breakout retest holds than on the original range-rejection logic.",
        "economic_interpretation": "Require continuation structure and a controlled pullback before entry.",
    },
    {
        "contract_id": "J_TU_RANGE_REJECTION_FROZEN_REFERENCE_V1",
        "test_role": "EXECUTION_COMPARATOR",
        "primary_regime": "TREND_UP",
        "base_challenger_id": "RANGE_REJECTION_REVERSION_1_25R_V1",
        "cohort_id": "J_TU_ALL_COMPLETE_HOLDOUT",
        "comparison_group": "J_TU_FROZEN_REFERENCE",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "Frozen Step 9I trend-up range-rejection reference.",
        "economic_interpretation": "Context only; not a new primary hypothesis.",
    },
    {
        "contract_id": "J_VE_ALIGNED_CLOSE_ORB_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "VOLATILITY_EXPANSION",
        "base_challenger_id": "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1",
        "cohort_id": "J_VE_GROUP_ALIGNED",
        "comparison_group": "J_VE_EXECUTION_AND_ALIGNMENT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "During volatility expansion, group-aligned close-confirmed ORB is the preferred continuation execution.",
        "economic_interpretation": "Alignment selects direction; close confirmation reduces false breaks.",
    },
    {
        "contract_id": "J_VE_ALIGNED_EARLY_CONTINUATION_REFERENCE_V1",
        "test_role": "EXECUTION_COMPARATOR",
        "primary_regime": "VOLATILITY_EXPANSION",
        "base_challenger_id": "EARLY_MOVE_CONTINUATION_1_5R_V1",
        "cohort_id": "J_VE_GROUP_ALIGNED",
        "comparison_group": "J_VE_EXECUTION_AND_ALIGNMENT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "Frozen aligned early-continuation execution reference.",
        "economic_interpretation": "Same-cohort comparator for close-confirmed ORB.",
    },
    {
        "contract_id": "J_VE_CONTRARIAN_CLOSE_ORB_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "VOLATILITY_EXPANSION",
        "base_challenger_id": "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1",
        "cohort_id": "J_VE_GROUP_CONTRARIAN",
        "comparison_group": "J_VE_EXECUTION_AND_ALIGNMENT",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "CONTRARIAN_TO_GROUP",
        "hypothesis": "Close confirmation alone should not rescue continuation when the stock conflicts with its sector.",
        "economic_interpretation": "Tests whether alignment remains essential under the redesigned execution.",
    },
    {
        "contract_id": "J_RLV_ALL_LAGGARD_DELAYED_REVERSAL_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "J_RLV_ALL_EARLY_LAGGARDS",
        "comparison_group": "J_RLV_VOLATILITY_SIMPLIFICATION",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "The core quiet-market reversal effect belongs to early laggards generally, not only the high-relative-volatility subset.",
        "economic_interpretation": "Simplify the rule if the laggard state carries most of the signal.",
    },
    {
        "contract_id": "J_RLV_HIGH_VOL_LAGGARD_REFERENCE_V1",
        "test_role": "EXECUTION_COMPARATOR",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "J_RLV_HIGH_VOL_LAGGARDS",
        "comparison_group": "J_RLV_VOLATILITY_SIMPLIFICATION",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "HIGH_RELATIVE_VOL",
        "sector_alignment_states": "ANY",
        "hypothesis": "Frozen high-relative-volatility delayed-reversal reference.",
        "economic_interpretation": "Benchmark for the broader laggard rule.",
    },
    {
        "contract_id": "J_RLV_NOT_HIGH_VOL_LAGGARD_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "J_RLV_NOT_HIGH_VOL_LAGGARDS",
        "comparison_group": "J_RLV_VOLATILITY_SIMPLIFICATION",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "LOW_RELATIVE_VOL|MEDIUM_RELATIVE_VOL",
        "sector_alignment_states": "ANY",
        "hypothesis": "Complement to the high-relative-volatility laggard reference.",
        "economic_interpretation": "Tests whether lower relative volatility still contains reversal value.",
    },
    {
        "contract_id": "J_RLV_CONTRARIAN_LAGGARD_DELAYED_REVERSAL_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "J_RLV_LAGGARD_CONTRARIAN_TO_GROUP",
        "comparison_group": "J_RLV_IDIOSYNCRATIC_VS_GROUP_WEAKNESS",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "CONTRARIAN_TO_GROUP",
        "hypothesis": "A quiet-market laggard is more reversible when its weakness is idiosyncratic rather than shared by its sector.",
        "economic_interpretation": "Isolated dislocation should mean-revert more readily than broad sector weakness.",
    },
    {
        "contract_id": "J_RLV_ALIGNED_LAGGARD_DELAYED_REVERSAL_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "J_RLV_LAGGARD_ALIGNED_WITH_GROUP",
        "comparison_group": "J_RLV_IDIOSYNCRATIC_VS_GROUP_WEAKNESS",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "Complement control for idiosyncratic laggard reversal.",
        "economic_interpretation": "Sector-confirmed weakness may be less suitable for reversal.",
    },
]

CONTRACT_BY_ID = {row["contract_id"]: row for row in CONTRACTS}

COMPARISONS = [
    (
        "J_TU_PULLBACK_MINUS_CLOSE_ORB",
        "J_TU_ALIGNED_LEADER_PULLBACK_HOLD_V1",
        "J_TU_ALIGNED_LEADER_CLOSE_ORB_V1",
        "SAME_COHORT_STRATEGY",
    ),
    (
        "J_VE_CLOSE_ORB_MINUS_EARLY_CONTINUATION",
        "J_VE_ALIGNED_CLOSE_ORB_V1",
        "J_VE_ALIGNED_EARLY_CONTINUATION_REFERENCE_V1",
        "SAME_COHORT_STRATEGY",
    ),
    (
        "J_VE_ALIGNED_MINUS_CONTRARIAN_CLOSE_ORB",
        "J_VE_ALIGNED_CLOSE_ORB_V1",
        "J_VE_CONTRARIAN_CLOSE_ORB_CONTROL_V1",
        "STATE_COMPLEMENT",
    ),
    (
        "J_RLV_HIGH_MINUS_NOT_HIGH_VOL",
        "J_RLV_HIGH_VOL_LAGGARD_REFERENCE_V1",
        "J_RLV_NOT_HIGH_VOL_LAGGARD_CONTROL_V1",
        "STATE_COMPLEMENT",
    ),
    (
        "J_RLV_CONTRARIAN_MINUS_ALIGNED_LAGGARD",
        "J_RLV_CONTRARIAN_LAGGARD_DELAYED_REVERSAL_V1",
        "J_RLV_ALIGNED_LAGGARD_DELAYED_REVERSAL_CONTROL_V1",
        "STATE_COMPLEMENT",
    ),
]


SUMMARY_COLUMNS = [
    "experiment_id",
    "research_status",
    "code_version",
    "requested_start_date",
    "requested_end_date",
    "effective_start_date",
    "effective_end_date",
    "taxonomy_sessions",
    "contracts_registered",
    "primary_hypotheses",
    "completed_challenger_trades",
    "locked_reference_trades_diagnosed",
    "positive_primary_contracts",
    "primary_contracts_with_positive_late_half_pnl",
    "audit_pass",
    "strategies_promoted",
    "router_active",
    "classification",
]


DIAGNOSTIC_COLUMNS = [
    "experiment_id",
    "design_source",
    "contract_id",
    "test_role",
    "date",
    "primary_regime",
    "ticker",
    "company_id",
    "broad_sector",
    "direction",
    "ticker_relative_state",
    "volatility_bucket",
    "sector_direction_alignment",
    "entry_time",
    "entry_clock",
    "entry_time_bucket",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_time",
    "exit_reason",
    "risk_pct_at_entry",
    "early_range_pct",
    "initial_move_pct",
    "entry_extension_from_midpoint_pct",
    "mfe_pct",
    "mae_pct",
    "mfe_r",
    "mae_r",
    "r_multiple_achieved",
    "risk_capped_net_pnl_sek",
    "point_in_time_pass",
]


def _bool(value: Any) -> bool:
    return step9g._bool(value)


def _num(value: Any, default: float = np.nan) -> float:
    return step9g._num(value, default)


def _date_strings(prices: pd.DataFrame, start_date: str, end_date: str) -> list[str]:
    if prices.empty:
        return []
    dates = pd.Series(prices["date"].astype(str).unique(), dtype="string")
    return sorted(dates[dates.between(start_date, end_date)].dropna().astype(str).tolist())


def build_daily_taxonomy(prices: pd.DataFrame, start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    for session_date in _date_strings(prices, start_date, end_date):
        try:
            row, _, _ = step9i.build_current_regime(prices, session_date)
            payload = row.to_dict()
            payload["date"] = session_date
            rows.append(payload)
        except (step9i.ShadowDataNotReady, ValueError) as exc:
            skips.append({"date": session_date, "skip_reason": str(exc)})
    taxonomy = pd.DataFrame(rows)
    if not taxonomy.empty:
        taxonomy["date"] = taxonomy["date"].astype(str)
    return taxonomy, pd.DataFrame(skips, columns=["date", "skip_reason"])


def _pullback_hold_candidates(
    session: dict,
    challenger: dict,
    states: pd.DataFrame,
    bars_lookup: dict[tuple[str, str], pd.DataFrame],
    trades: list[dict],
    legs: list[dict],
) -> list[dict]:
    date = str(session["date"])
    rows: list[dict] = []
    max_ideas = int(_num(session.get("research_max_concurrent_ideas"), 2))
    direction_bias = str(session.get("direction_bias", "NEUTRAL"))

    for state in states.sort_values("ticker").to_dict("records"):
        ticker = str(state["ticker"])
        candidate = step9d._base_candidate(session, challenger, f"{date}|{PULLBACK_CHALLENGER_ID}|{ticker}", "SINGLE")
        step9d._add_state(candidate, state)
        candidate["setup_status"] = "VALID_SETUP"
        invalid: list[str] = []
        early_open = _num(state.get("early_open"))
        close_0940 = _num(state.get("close_0940"), _num(state.get("cutoff_close")))
        previous_close = _num(state.get("previous_close"))
        early_range_pct = _num(state.get("early_range_pct"))
        initial_move = close_0940 / early_open - 1.0 if early_open > 0 else np.nan
        side = "LONG" if initial_move > 0 else "SHORT" if initial_move < 0 else ""
        candidate["direction"] = side
        candidate["ranking_metric"] = abs(initial_move) if np.isfinite(initial_move) else np.nan
        candidate["mechanical_interpretation"] = "BREAKOUT_RETEST_HOLD_NEXT_BAR_1_5R"
        if not np.isfinite(initial_move) or abs(initial_move) < 0.0010:
            invalid.append("EARLY_MOVE_BELOW_0_10_PERCENT")
        if not side:
            invalid.append("NO_EARLY_DIRECTION")
        if side and not step9d._direction_allowed(side, direction_bias):
            invalid.append("NOT_ALIGNED_WITH_SESSION_DIRECTION_BIAS")
        if side == "LONG" and np.isfinite(previous_close) and close_0940 <= previous_close:
            invalid.append("LONG_NOT_ABOVE_PREVIOUS_CLOSE")
        if side == "SHORT" and np.isfinite(previous_close) and close_0940 >= previous_close:
            invalid.append("SHORT_NOT_BELOW_PREVIOUS_CLOSE")
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
        bars = bars_lookup.get((date, str(candidate["ticker"])), pd.DataFrame())
        if bars.empty:
            candidate["trigger_status"] = "NO_EXECUTABLE_BARS"
            continue
        side = str(candidate["direction"])
        boundary = _num(candidate["early_high"]) if side == "LONG" else _num(candidate["early_low"])
        breakout_window = step9d._bars_between(bars, "09:45", "11:55")
        breakout_time: pd.Timestamp | None = None
        for _, bar in breakout_window.iterrows():
            close = _num(bar.get("close"))
            if (side == "LONG" and close > boundary) or (side == "SHORT" and close < boundary):
                breakout_time = pd.Timestamp(bar["datetime"])
                break
        if breakout_time is None:
            candidate["trigger_status"] = "NOT_TRIGGERED"
            continue

        retest_window = bars[
            (bars["datetime"] > breakout_time)
            & (bars["datetime"].dt.strftime("%H:%M") <= "12:55")
        ].sort_values("datetime")
        signal_bar = None
        previous_close_value = np.nan
        for _, bar in retest_window.iterrows():
            close = _num(bar.get("close"))
            if side == "LONG":
                held = _num(bar.get("low")) <= boundary and close > boundary
                resumed = not np.isfinite(previous_close_value) or close > previous_close_value
            else:
                held = _num(bar.get("high")) >= boundary and close < boundary
                resumed = not np.isfinite(previous_close_value) or close < previous_close_value
            if held and resumed:
                signal_bar = bar
                break
            previous_close_value = close
        if signal_bar is None:
            candidate["trigger_status"] = "BREAKOUT_WITHOUT_RETEST_HOLD"
            continue
        next_bar = step9d._next_bar_after(bars, pd.Timestamp(signal_bar["datetime"]))
        if next_bar is None or step9d._clock(next_bar["datetime"]) > "13:00":
            candidate["trigger_status"] = "RETEST_HOLD_TOO_LATE"
            continue

        entry_time = pd.Timestamp(next_bar["datetime"])
        entry_price = _num(next_bar.get("open"), _num(next_bar.get("close")))
        stop_price = _num(candidate["early_midpoint"])
        risk = entry_price - stop_price if side == "LONG" else stop_price - entry_price
        target_price = entry_price + 1.5 * risk if side == "LONG" else entry_price - 1.5 * risk
        if not (np.isfinite(entry_price) and np.isfinite(stop_price) and np.isfinite(target_price)) or risk <= 0:
            candidate["trigger_status"] = "INVALID_TRIGGER_LEVELS"
            candidate["invalid_reason"] = "NONPOSITIVE_OR_NONFINITE_RISK"
            continue
        candidate["signal_time"] = step9d._iso(pd.Timestamp(signal_bar["datetime"]) + pd.Timedelta(minutes=step9d.BAR_INTERVAL_MINUTES))
        execution = step9d._directional_execution(
            bars=bars,
            side=side,
            entry_time=entry_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            exit_cutoff="16:30",
        )
        if execution is None:
            candidate["trigger_status"] = "NO_EXECUTABLE_BARS"
            continue
        step9d._append_single_trade(
            candidate,
            session,
            challenger,
            execution,
            side,
            entry_time,
            entry_price,
            stop_price,
            target_price,
            trades,
            legs,
        )
    return rows


@contextmanager
def _patched_step9j_engine():
    names = [
        "EXPERIMENT_ID",
        "RESEARCH_STATUS",
        "CONTRACTS",
        "CONTRACT_BY_ID",
        "COMPARISONS",
        "CHALLENGER_BY_ID",
        "_single_candidates_for_challenger",
        "_intended_side",
    ]
    old = {name: getattr(step9g, name) for name in names}
    challenger_map = dict(step9g.CHALLENGER_BY_ID)
    challenger_map[PULLBACK_CHALLENGER_ID] = PULLBACK_CHALLENGER
    original_dispatch = step9g._single_candidates_for_challenger
    original_intended_side = step9g._intended_side

    def dispatch(session, challenger, states, bars_lookup, trades, legs):
        if challenger["challenger_id"] == PULLBACK_CHALLENGER_ID:
            return _pullback_hold_candidates(session, challenger, states, bars_lookup, trades, legs)
        return original_dispatch(session, challenger, states, bars_lookup, trades, legs)

    def intended_side(base_challenger_id: str, row: pd.Series | dict) -> str:
        if base_challenger_id == PULLBACK_CHALLENGER_ID:
            early_open = _num(row.get("early_open"))
            close_0940 = _num(row.get("close_0940"), _num(row.get("cutoff_close")))
            if early_open > 0 and np.isfinite(close_0940):
                move = close_0940 / early_open - 1.0
                return "LONG" if move > 0 else "SHORT" if move < 0 else ""
            return ""
        return original_intended_side(base_challenger_id, row)

    try:
        step9g.EXPERIMENT_ID = EXPERIMENT_ID
        step9g.RESEARCH_STATUS = RESEARCH_STATUS
        step9g.CONTRACTS = CONTRACTS
        step9g.CONTRACT_BY_ID = CONTRACT_BY_ID
        step9g.COMPARISONS = COMPARISONS
        step9g.CHALLENGER_BY_ID = challenger_map
        step9g._single_candidates_for_challenger = dispatch
        step9g._intended_side = intended_side
        yield
    finally:
        for name, value in old.items():
            setattr(step9g, name, value)


def _full_context(prices: pd.DataFrame, end_date: str):
    return step9i._full_holdout_context(prices, end_date)


def _profit_factor(values: Iterable[float]) -> float:
    return step9g._profit_factor(values)


def _phase_map(dates: list[str]) -> dict[str, str]:
    if not dates:
        return {}
    midpoint = max(1, len(dates) // 2)
    return {date: "EARLY_HALF" if idx < midpoint else "LATE_HALF" for idx, date in enumerate(dates)}


def build_trade_diagnostics(
    trades: pd.DataFrame,
    prices: pd.DataFrame,
    taxonomy_dates: set[str],
    design_source: str,
) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=DIAGNOSTIC_COLUMNS)
    daily_reference = step9b.build_daily_reference(prices)
    with step9i._patched_holdout_tickers():
        states, bars_lookup = step9b.build_market_state(prices, daily_reference, taxonomy_dates)
    state_columns = [
        "date",
        "ticker",
        "early_range_pct",
        "early_open",
        "early_midpoint",
        "close_0940",
        "cutoff_close",
    ]
    state_lookup = states[state_columns].copy()
    state_lookup["date"] = state_lookup["date"].astype(str)
    merged = trades.copy()
    merged["date"] = merged["date"].astype(str)
    merged = merged.merge(state_lookup, on=["date", "ticker"], how="left", validate="many_to_one")
    rows: list[dict[str, Any]] = []
    for trade in merged.to_dict("records"):
        entry_time = pd.Timestamp(trade["entry_time"])
        exit_time = pd.Timestamp(trade["exit_time"])
        bars = bars_lookup.get((str(trade["date"]), str(trade["ticker"])), pd.DataFrame())
        scan = bars[(bars["datetime"] > entry_time) & (bars["datetime"] <= exit_time)].copy() if not bars.empty else bars
        entry_price = _num(trade.get("entry_price"))
        side = str(trade.get("direction", ""))
        if scan.empty or entry_price <= 0:
            mfe = np.nan
            mae = np.nan
        elif side == "LONG":
            mfe = float(pd.to_numeric(scan["high"], errors="coerce").max() / entry_price - 1.0)
            mae = float(pd.to_numeric(scan["low"], errors="coerce").min() / entry_price - 1.0)
        else:
            lows = pd.to_numeric(scan["low"], errors="coerce")
            highs = pd.to_numeric(scan["high"], errors="coerce")
            mfe = float(entry_price / lows.min() - 1.0) if lows.min() > 0 else np.nan
            mae = float(entry_price / highs.max() - 1.0) if highs.max() > 0 else np.nan
        risk_pct = _num(trade.get("risk_pct_at_entry"))
        midpoint = _num(trade.get("early_midpoint"))
        early_open = _num(trade.get("early_open"))
        close_0940 = _num(trade.get("close_0940"), _num(trade.get("cutoff_close")))
        initial_move = close_0940 / early_open - 1.0 if early_open > 0 else np.nan
        extension = entry_price / midpoint - 1.0 if midpoint > 0 else np.nan
        entry_clock = entry_time.strftime("%H:%M")
        if entry_clock < "10:00":
            time_bucket = "09:45-09:59"
        elif entry_clock < "11:00":
            time_bucket = "10:00-10:59"
        elif entry_clock < "12:00":
            time_bucket = "11:00-11:59"
        else:
            time_bucket = "12:00+"
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "design_source": design_source,
                "contract_id": trade.get("contract_id", ""),
                "test_role": trade.get("test_role", ""),
                "date": str(trade.get("date", "")),
                "primary_regime": trade.get("primary_regime", ""),
                "ticker": trade.get("ticker", ""),
                "company_id": trade.get("company_id", ""),
                "broad_sector": trade.get("broad_sector", ""),
                "direction": side,
                "ticker_relative_state": trade.get("ticker_relative_state", ""),
                "volatility_bucket": trade.get("volatility_bucket", ""),
                "sector_direction_alignment": trade.get("sector_direction_alignment", ""),
                "entry_time": trade.get("entry_time", ""),
                "entry_clock": entry_clock,
                "entry_time_bucket": time_bucket,
                "entry_price": entry_price,
                "stop_price": _num(trade.get("stop_price")),
                "target_price": _num(trade.get("target_price")),
                "exit_time": trade.get("exit_time", ""),
                "exit_reason": trade.get("exit_reason", ""),
                "risk_pct_at_entry": risk_pct,
                "early_range_pct": _num(trade.get("early_range_pct")),
                "initial_move_pct": initial_move,
                "entry_extension_from_midpoint_pct": extension,
                "mfe_pct": mfe,
                "mae_pct": mae,
                "mfe_r": mfe / risk_pct if risk_pct > 0 and np.isfinite(mfe) else np.nan,
                "mae_r": mae / risk_pct if risk_pct > 0 and np.isfinite(mae) else np.nan,
                "r_multiple_achieved": _num(trade.get("r_multiple_achieved")),
                "risk_capped_net_pnl_sek": _num(trade.get("risk_capped_net_pnl_sek"), 0.0),
                "point_in_time_pass": _bool(trade.get("point_in_time_pass")),
            }
        )
    return pd.DataFrame(rows, columns=DIAGNOSTIC_COLUMNS)


def build_group_performance(trades: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    columns = group_columns + [
        "trades",
        "sessions",
        "companies",
        "sectors",
        "net_pnl_risk_capped_sek",
        "average_pnl_per_trade_sek",
        "win_rate",
        "profit_factor",
    ]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for keys, group in trades.groupby(group_columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        pnl = pd.to_numeric(group["risk_capped_net_pnl_sek"], errors="coerce").fillna(0.0)
        rows.append(
            {
                **dict(zip(group_columns, keys)),
                "trades": int(len(group)),
                "sessions": int(group["date"].nunique()),
                "companies": int(group["company_id"].replace("", np.nan).nunique()),
                "sectors": int(group["broad_sector"].replace("", np.nan).nunique()),
                "net_pnl_risk_capped_sek": float(pnl.sum()),
                "average_pnl_per_trade_sek": float(pnl.mean()),
                "win_rate": float((pnl > 0).mean()),
                "profit_factor": _profit_factor(pnl),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_time_split_performance(trades: pd.DataFrame, taxonomy_dates: list[str]) -> pd.DataFrame:
    phases = _phase_map(taxonomy_dates)
    frame = trades.copy()
    if frame.empty:
        return build_group_performance(frame, ["contract_id", "test_role", "primary_regime", "phase"])
    frame["phase"] = frame["date"].astype(str).map(phases).fillna("OUTSIDE_SPLIT")
    result = build_group_performance(frame, ["contract_id", "test_role", "primary_regime", "phase"])
    result["interpretation"] = "Descriptive chronological stability only; both halves were visible before redesign and neither is confirmatory."
    return result


def enrich_performance(performance: pd.DataFrame, trades: pd.DataFrame, diagnostics: pd.DataFrame) -> pd.DataFrame:
    result = performance.copy()
    extras: list[dict[str, Any]] = []
    for contract in CONTRACTS:
        cid = contract["contract_id"]
        group = trades[trades["contract_id"].eq(cid)]
        diag = diagnostics[(diagnostics["contract_id"].eq(cid)) & diagnostics["design_source"].eq("STEP9J_CHALLENGER")]
        extras.append(
            {
                "contract_id": cid,
                "independent_sectors": int(group["broad_sector"].replace("", np.nan).nunique()) if not group.empty else 0,
                "median_mfe_r": float(pd.to_numeric(diag["mfe_r"], errors="coerce").median()) if not diag.empty else np.nan,
                "median_mae_r": float(pd.to_numeric(diag["mae_r"], errors="coerce").median()) if not diag.empty else np.nan,
                "median_entry_clock": str(diag["entry_clock"].sort_values().iloc[len(diag) // 2]) if not diag.empty else "",
                "research_status": RESEARCH_STATUS,
                "promotion_eligible": False,
                "router_active": False,
            }
        )
    return result.merge(pd.DataFrame(extras), on="contract_id", how="left", validate="one_to_one")


def build_summary(
    start_date: str,
    end_date: str,
    taxonomy: pd.DataFrame,
    trades: pd.DataFrame,
    locked_trades: pd.DataFrame,
    performance: pd.DataFrame,
    time_split: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    dates = sorted(taxonomy["date"].astype(str).unique()) if not taxonomy.empty else []
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")].copy()
    late = time_split[
        time_split["test_role"].eq("PRIMARY_HYPOTHESIS") & time_split["phase"].eq("LATE_HALF")
    ]
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
        "contracts_registered": len(CONTRACTS),
        "primary_hypotheses": int(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in CONTRACTS)),
        "completed_challenger_trades": int(len(trades)),
        "locked_reference_trades_diagnosed": int(len(locked_trades)),
        "positive_primary_contracts": int(primary["net_pnl_risk_capped_sek"].gt(0).sum()) if not primary.empty else 0,
        "primary_contracts_with_positive_late_half_pnl": int(late["net_pnl_risk_capped_sek"].gt(0).sum()) if not late.empty else 0,
        "audit_pass": audit_pass,
        "strategies_promoted": 0,
        "router_active": False,
        "classification": "STEP9J_REDESIGN_DISCOVERY_COMPLETE_NOT_CONFIRMATORY" if audit_pass else "STEP9J_AUDIT_REVIEW_REQUIRED",
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_step9j(
    prices: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    taxonomy, taxonomy_skips = build_daily_taxonomy(prices, start_date, end_date)
    if taxonomy.empty:
        raise ValueError("No point-in-time-ready taxonomy sessions are available in the requested window.")
    effective_end = str(taxonomy["date"].max())
    static, holdout, characteristics, group_states = _full_context(prices, effective_end)
    # Keep all available prior holdout history through the effective end date.
    # The taxonomy limits evaluated sessions, while prior bars remain necessary for
    # previous-close and shifted point-in-time characteristics on the first session.
    with _patched_step9j_engine():
        challenger_core = step9g.build_state_filtered_experiment(
            taxonomy, holdout, static, characteristics, group_states
        )
    (
        _core_summary,
        registry,
        sessions,
        candidates,
        trades,
        legs,
        performance,
        comparisons,
        robustness,
        multiple,
        audit,
    ) = challenger_core

    with step9h._patched_step9g_globals():
        locked_core = step9g.build_state_filtered_experiment(
            taxonomy, holdout, static, characteristics, group_states
        )
    locked_trades = locked_core[4]

    taxonomy_dates = set(taxonomy["date"].astype(str))
    challenger_diagnostics = build_trade_diagnostics(
        trades, holdout, taxonomy_dates, "STEP9J_CHALLENGER"
    )
    locked_diagnostics = build_trade_diagnostics(
        locked_trades, holdout, taxonomy_dates, "LOCKED_STEP9I_REFERENCE"
    )
    diagnostics = pd.concat([challenger_diagnostics, locked_diagnostics], ignore_index=True)

    performance = enrich_performance(performance, trades, diagnostics)
    multiple = multiple.copy()
    if not multiple.empty:
        multiple["multiplicity_family"] = "FIVE_PRE_REGISTERED_STEP9J_PRIMARY_HYPOTHESES"
        multiple["interpretation"] = "Post-hoc redesign discovery only; no p-value or q-value can promote a strategy."

    taxonomy_dates_sorted = sorted(taxonomy["date"].astype(str).unique())
    time_split = build_time_split_performance(trades, taxonomy_dates_sorted)
    ticker_performance = build_group_performance(
        trades,
        ["contract_id", "test_role", "primary_regime", "ticker", "company_id", "broad_sector"],
    )
    sector_performance = build_group_performance(
        trades,
        ["contract_id", "test_role", "primary_regime", "broad_sector"],
    )

    summary = build_summary(
        start_date,
        end_date,
        taxonomy,
        trades,
        locked_trades,
        performance,
        time_split,
        audit,
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
        "diagnostics": diagnostics,
        "time_split": time_split,
        "ticker_performance": ticker_performance,
        "sector_performance": sector_performance,
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
        "diagnostics": DIAGNOSTIC_FILE,
        "time_split": TIME_SPLIT_FILE,
        "ticker_performance": TICKER_FILE,
        "sector_performance": SECTOR_FILE,
        "summary": SUMMARY_FILE,
    }
    for key, path in paths.items():
        export_csv_for_power_bi(outputs[key], path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step 9J challenger regime-strategy redesign research.")
    parser.add_argument("--start-date", default="2026-05-25")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = step9i.load_shadow_prices(args.source_db)
    if prices.empty:
        raise SystemExit(f"No intraday prices found in {args.source_db}.")
    outputs = run_step9j(prices, args.start_date, args.end_date)
    export_outputs(outputs)
    summary = outputs["summary"].iloc[0]
    performance = outputs["performance"]
    print("\n=== STEP 9J CHALLENGER REGIME-STRATEGY REDESIGN ===")
    print(f"Experiment       : {EXPERIMENT_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Requested window : {args.start_date} through {args.end_date}")
    print(f"Effective window : {summary['effective_start_date']} through {summary['effective_end_date']}")
    print(f"Taxonomy sessions: {int(summary['taxonomy_sessions'])}")
    print(f"Contracts        : {int(summary['contracts_registered'])} ({int(summary['primary_hypotheses'])} primaries)")
    print(f"Challenger trades: {int(summary['completed_challenger_trades'])}")
    print(f"Locked diagnostics: {int(summary['locked_reference_trades_diagnosed'])}")
    print(f"Audit pass       : {bool(summary['audit_pass'])}")
    print(f"Classification   : {summary['classification']}")
    print("\nPrimary challenger snapshot:")
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")][
        ["contract_id", "trades", "sessions_with_trades", "net_pnl_risk_capped_sek", "profit_factor_risk_capped"]
    ]
    if primary.empty:
        print("  No primary trades were generated.")
    else:
        print(primary.to_string(index=False))
    print("\nUse step9j_challenger_performance.csv, step9j_challenger_comparisons.csv, and step9j_trade_diagnostics.csv for review.")
    print("Step 9I remains frozen; Step 9J cannot activate the router or count as confirmatory evidence.")


if __name__ == "__main__":
    main()
