from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, legacy_output_path
from RegimeTrading.scripts import step9b_baseline_trade_generation as step9b
from RegimeTrading.scripts import step9d_regime_strategy_challenger_matrix as step9d
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i


EXPERIMENT_ID = "STEP9K_HIGH_DISPERSION_STRATEGY_RESEARCH_COMBINED23_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_POST_HOC_HIGH_DISPERSION_DISCOVERY_NOT_CONFIRMATORY"
CODE_VERSION = "STEP9K_HIGH_DISPERSION_V1_LOCKED_2026_07_26"
LATEST_ROUTER_BAR_LABEL = "09:40"
EXECUTION_START = "09:45"
SOURCE_DB = step9i.SHADOW_INTRADAY_DB

FAILED_LEADER_REVERSAL_ID = "HD_FAILED_LEADER_REVERSAL_1R_V1"
LAGGARD_CATCHUP_ID = "HD_LAGGARD_MIDPOINT_CATCHUP_1R_V1"
LEADER_CLOSE_ORB_ID = "HD_LEADER_CLOSE_CONFIRMED_ORB_1R_V1"
EARLY_CONTINUATION_CONTROL_ID = "EARLY_MOVE_CONTINUATION_1_5R_V1"

REGISTRY_FILE = legacy_output_path("step9k_contract_registry.csv")
SESSION_FILE = legacy_output_path("step9k_session_coverage.csv")
CANDIDATE_FILE = legacy_output_path("step9k_candidates.csv")
TRADE_FILE = legacy_output_path("step9k_trades.csv")
LEG_FILE = legacy_output_path("step9k_trade_legs.csv")
PERFORMANCE_FILE = legacy_output_path("step9k_contract_performance.csv")
COMPARISON_FILE = legacy_output_path("step9k_comparisons.csv")
ROBUSTNESS_FILE = legacy_output_path("step9k_robustness.csv")
MULTIPLE_TESTING_FILE = legacy_output_path("step9k_multiple_testing.csv")
AUDIT_FILE = legacy_output_path("step9k_audit.csv")
TRADE_DIAGNOSTIC_FILE = legacy_output_path("step9k_trade_diagnostics.csv")
HD_SESSION_DIAGNOSTIC_FILE = legacy_output_path("step9k_hd_session_diagnostics.csv")
HD_STATE_DIAGNOSTIC_FILE = legacy_output_path("step9k_hd_state_diagnostic_summary.csv")
TIME_SPLIT_FILE = legacy_output_path("step9k_time_split_performance.csv")
TICKER_FILE = legacy_output_path("step9k_ticker_performance.csv")
SECTOR_FILE = legacy_output_path("step9k_sector_performance.csv")
SEGMENT_FILE = legacy_output_path("step9k_segment_performance.csv")
SUMMARY_FILE = legacy_output_path("step9k_summary.csv")
TAXONOMY_FILE = legacy_output_path("step9k_daily_taxonomy.csv")


FAILED_LEADER_REVERSAL = {
    "challenger_id": FAILED_LEADER_REVERSAL_ID,
    "strategy_family": "FAILED_BREAKOUT_REVERSAL",
    "control_status": "CHALLENGER",
    "idea_type": "SINGLE",
    "hypothesis": "An early leader in HIGH_DISPERSION reverses after a close-confirmed breakout fails and price closes back inside the opening range.",
    "entry_model": "First close beyond the strict 09:30-09:40 boundary, then first later close back inside; enter reversal at next-bar open through 13:00.",
    "stop_model": "Observed failed-breakout extreme known at the failure signal.",
    "target_model": "1.0R from actual entry.",
    "exit_cutoff": "16:30",
    "selection_model": "Rank absolute 09:40 move; maximum frozen regime ideas.",
    "direction_model": "OPPOSITE_EARLY_MOVE_AFTER_FAILED_BREAKOUT",
    "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
    "diagnostic_source": "Tests whether the frozen negative early-leader continuation result becomes a tradable confirmed reversal.",
    "ranking_eligible": True,
}

LAGGARD_CATCHUP = {
    "challenger_id": LAGGARD_CATCHUP_ID,
    "strategy_family": "CONFIRMED_LAGGARD_CATCHUP",
    "control_status": "CHALLENGER",
    "idea_type": "SINGLE",
    "hypothesis": "A HIGH_DISPERSION early laggard catches up after a post-10:00 close through the early midpoint.",
    "entry_model": "After 10:00, first close through the strict early midpoint against the initial move; enter next-bar open through 13:00.",
    "stop_model": "Strict early-session extreme against the reversal.",
    "target_model": "1.0R from actual entry.",
    "exit_cutoff": "16:30",
    "selection_model": "Rank absolute 09:40 move; maximum frozen regime ideas.",
    "direction_model": "OPPOSITE_EARLY_MOVE_AFTER_MIDPOINT_CONFIRMATION",
    "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
    "diagnostic_source": "Separates isolated laggard weakness from sector-confirmed weakness using the direction of the early move.",
    "ranking_eligible": True,
}

LEADER_CLOSE_ORB = {
    "challenger_id": LEADER_CLOSE_ORB_ID,
    "strategy_family": "OPENING_RANGE_CONTINUATION",
    "control_status": "CHALLENGER",
    "idea_type": "SINGLE",
    "hypothesis": "An early leader in HIGH_DISPERSION continues only after a completed close beyond the strict opening range.",
    "entry_model": "First completed close beyond the strict 09:30-09:40 range in the early-move direction; enter next-bar open through 13:00.",
    "stop_model": "Opposite strict early-range boundary.",
    "target_model": "1.0R from actual entry.",
    "exit_cutoff": "16:30",
    "selection_model": "Rank absolute 09:40 move; maximum frozen regime ideas.",
    "direction_model": "EARLY_MOVE_DIRECTION_AFTER_CLOSE_CONFIRMATION",
    "sizing_model": "DUAL_EQUAL_NOTIONAL_AND_FIXED_RISK_CAP",
    "diagnostic_source": "Tests whether the failed leader-continuation result was caused by early execution rather than continuation itself.",
    "ranking_eligible": True,
}


# Locked before Step 9K output is viewed. Step 9K is historical discovery only.
CONTRACTS = [
    {
        "contract_id": "K_HD_FAILED_LEADER_REVERSAL_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": FAILED_LEADER_REVERSAL_ID,
        "cohort_id": "K_HD_EARLY_LEADER",
        "comparison_group": "K_HD_LEADER_EXECUTION",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "A failed breakout converts a HIGH_DISPERSION early leader into a confirmed reversal trade.",
        "economic_interpretation": "Do not infer reversal from a bad continuation result; require an explicit failed-breakout signal.",
    },
    {
        "contract_id": "K_HD_CONTRARIAN_LAGGARD_CATCHUP_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": LAGGARD_CATCHUP_ID,
        "cohort_id": "K_HD_LAGGARD_EARLY_MOVE_CONTRARIAN",
        "comparison_group": "K_HD_LAGGARD_ALIGNMENT",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "CONTRARIAN_TO_GROUP",
        "hypothesis": "An early laggard whose initial move conflicts with its sector catches up after midpoint confirmation.",
        "economic_interpretation": "Isolated weakness should mean-revert more readily than sector-confirmed weakness.",
    },
    {
        "contract_id": "K_HD_LEADER_CLOSE_ORB_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": LEADER_CLOSE_ORB_ID,
        "cohort_id": "K_HD_EARLY_LEADER",
        "comparison_group": "K_HD_LEADER_EXECUTION",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "A HIGH_DISPERSION early leader continues only after close confirmation beyond the opening range.",
        "economic_interpretation": "Tests whether waiting for confirmation rescues leader continuation.",
    },
    {
        "contract_id": "K_HD_ALIGNED_LAGGARD_CATCHUP_CONTROL_V1",
        "test_role": "COMPLEMENT_CONTROL",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": LAGGARD_CATCHUP_ID,
        "cohort_id": "K_HD_LAGGARD_EARLY_MOVE_ALIGNED",
        "comparison_group": "K_HD_LAGGARD_ALIGNMENT",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "Complement control for the contrarian-laggard catch-up hypothesis.",
        "economic_interpretation": "Sector-confirmed weakness may be less suitable for a catch-up reversal.",
    },
    {
        "contract_id": "K_HD_LEADER_EARLY_CONTINUATION_FROZEN_CONTROL_V1",
        "test_role": "NEGATIVE_GUARDRAIL_CONTROL",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": EARLY_CONTINUATION_CONTROL_ID,
        "cohort_id": "K_HD_EARLY_LEADER",
        "comparison_group": "K_HD_LEADER_EXECUTION",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "Frozen negative control: HIGH_DISPERSION early leaders should not be chased with early continuation.",
        "economic_interpretation": "Exact conceptual control for the existing G1 avoidance finding.",
    },
]
CONTRACT_BY_ID = {row["contract_id"]: row for row in CONTRACTS}

COMPARISONS = [
    (
        "K_HD_FAILED_REVERSAL_MINUS_EARLY_CONTINUATION",
        "K_HD_FAILED_LEADER_REVERSAL_V1",
        "K_HD_LEADER_EARLY_CONTINUATION_FROZEN_CONTROL_V1",
        "SAME_COHORT_STRATEGY",
    ),
    (
        "K_HD_CLOSE_ORB_MINUS_EARLY_CONTINUATION",
        "K_HD_LEADER_CLOSE_ORB_V1",
        "K_HD_LEADER_EARLY_CONTINUATION_FROZEN_CONTROL_V1",
        "SAME_COHORT_STRATEGY",
    ),
    (
        "K_HD_FAILED_REVERSAL_MINUS_CLOSE_ORB",
        "K_HD_FAILED_LEADER_REVERSAL_V1",
        "K_HD_LEADER_CLOSE_ORB_V1",
        "SAME_COHORT_STRATEGY",
    ),
    (
        "K_HD_CONTRARIAN_MINUS_ALIGNED_LAGGARD",
        "K_HD_CONTRARIAN_LAGGARD_CATCHUP_V1",
        "K_HD_ALIGNED_LAGGARD_CATCHUP_CONTROL_V1",
        "STATE_COMPLEMENT",
    ),
]

SUMMARY_COLUMNS = [
    "experiment_id", "research_status", "code_version", "requested_start_date",
    "requested_end_date", "effective_start_date", "effective_end_date",
    "taxonomy_sessions", "high_dispersion_sessions", "diagnostic_ticker_session_rows",
    "contracts_registered", "primary_hypotheses", "completed_trades",
    "positive_primary_contracts", "primary_contracts_with_positive_late_half_pnl",
    "audit_pass", "strategies_promoted", "router_active", "classification",
]

TRADE_DIAGNOSTIC_COLUMNS = [
    "experiment_id", "contract_id", "test_role", "date", "primary_regime", "ticker",
    "universe_segment", "company_id", "broad_sector", "direction",
    "ticker_relative_state", "volatility_bucket", "sector_direction_alignment",
    "entry_time", "entry_clock", "entry_time_bucket", "entry_price", "stop_price",
    "target_price", "exit_time", "exit_reason", "risk_pct_at_entry", "early_range_pct",
    "initial_move_pct", "entry_extension_from_midpoint_pct", "mfe_pct", "mae_pct",
    "mfe_r", "mae_r", "r_multiple_achieved", "risk_capped_net_pnl_sek",
    "point_in_time_pass",
]

HD_SESSION_DIAGNOSTIC_COLUMNS = [
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


def _early_move(row: pd.Series | dict) -> float:
    early_open = _num(row.get("early_open"))
    close_0940 = _num(row.get("close_0940"), _num(row.get("cutoff_close")))
    return close_0940 / early_open - 1.0 if early_open > 0 and np.isfinite(close_0940) else np.nan


def _early_move_side(row: pd.Series | dict) -> str:
    move = _early_move(row)
    return "LONG" if move > 0 else "SHORT" if move < 0 else ""


def _candidate_base(session: dict, challenger: dict, state: dict) -> tuple[dict, float, str]:
    date = str(session["date"])
    ticker = str(state["ticker"])
    cid = challenger["challenger_id"]
    candidate = step9d._base_candidate(session, challenger, f"{date}|{cid}|{ticker}", "SINGLE")
    step9d._add_state(candidate, state)
    candidate["setup_status"] = "VALID_SETUP"
    move = _early_move(state)
    side = "LONG" if move > 0 else "SHORT" if move < 0 else ""
    candidate["ranking_metric"] = abs(move) if np.isfinite(move) else np.nan
    return candidate, move, side


def _finalize_single_trade(
    candidate: dict,
    session: dict,
    challenger: dict,
    bars: pd.DataFrame,
    side: str,
    signal_bar: pd.Series,
    entry_bar: pd.Series,
    stop_price: float,
    target_multiple: float,
    trades: list[dict],
    legs: list[dict],
) -> None:
    entry_time = pd.Timestamp(entry_bar["datetime"])
    entry_price = _num(entry_bar.get("open"), _num(entry_bar.get("close")))
    risk = entry_price - stop_price if side == "LONG" else stop_price - entry_price
    target_price = entry_price + target_multiple * risk if side == "LONG" else entry_price - target_multiple * risk
    if not (np.isfinite(entry_price) and np.isfinite(stop_price) and np.isfinite(target_price)) or risk <= 0:
        candidate["trigger_status"] = "INVALID_TRIGGER_LEVELS"
        candidate["invalid_reason"] = "NONPOSITIVE_OR_NONFINITE_RISK"
        return
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
        return
    step9d._append_single_trade(
        candidate, session, challenger, execution, side, entry_time, entry_price,
        stop_price, target_price, trades, legs,
    )


def _failed_leader_reversal_candidates(
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
    for state in states.sort_values("ticker").to_dict("records"):
        candidate, move, early_side = _candidate_base(session, challenger, state)
        candidate["direction"] = "SHORT" if early_side == "LONG" else "LONG" if early_side == "SHORT" else ""
        candidate["mechanical_interpretation"] = "FAILED_BREAKOUT_CLOSE_BACK_INSIDE_NEXT_BAR_REVERSAL_1R"
        invalid: list[str] = []
        if not np.isfinite(move) or abs(move) < 0.0010:
            invalid.append("EARLY_MOVE_BELOW_0_10_PERCENT")
        if not early_side:
            invalid.append("NO_EARLY_DIRECTION")
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
        reversal_side = str(candidate["direction"])
        early_side = "SHORT" if reversal_side == "LONG" else "LONG"
        boundary = _num(candidate["early_high"]) if early_side == "LONG" else _num(candidate["early_low"])
        breakout_bar = None
        for _, bar in step9d._bars_between(bars, "09:45", "12:25").iterrows():
            close = _num(bar.get("close"))
            if (early_side == "LONG" and close > boundary) or (early_side == "SHORT" and close < boundary):
                breakout_bar = bar
                break
        if breakout_bar is None:
            candidate["trigger_status"] = "NO_CLOSE_CONFIRMED_BREAKOUT"
            continue
        failure_bar = None
        post_breakout = bars[
            (bars["datetime"] > pd.Timestamp(breakout_bar["datetime"]))
            & (bars["datetime"].dt.strftime("%H:%M") <= "12:55")
        ].sort_values("datetime")
        for _, bar in post_breakout.iterrows():
            close = _num(bar.get("close"))
            if (early_side == "LONG" and close < boundary) or (early_side == "SHORT" and close > boundary):
                failure_bar = bar
                break
        if failure_bar is None:
            candidate["trigger_status"] = "BREAKOUT_DID_NOT_FAIL"
            continue
        next_bar = step9d._next_bar_after(bars, pd.Timestamp(failure_bar["datetime"]))
        if next_bar is None or step9d._clock(next_bar["datetime"]) > "13:00":
            candidate["trigger_status"] = "FAILED_BREAKOUT_TOO_LATE"
            continue
        known_window = bars[
            (bars["datetime"] >= pd.Timestamp(breakout_bar["datetime"]))
            & (bars["datetime"] <= pd.Timestamp(failure_bar["datetime"]))
        ]
        stop = (
            float(pd.to_numeric(known_window["high"], errors="coerce").max())
            if reversal_side == "SHORT"
            else float(pd.to_numeric(known_window["low"], errors="coerce").min())
        )
        _finalize_single_trade(
            candidate, session, challenger, bars, reversal_side, failure_bar,
            next_bar, stop, 1.0, trades, legs,
        )
    return rows


def _laggard_catchup_candidates(
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
    for state in states.sort_values("ticker").to_dict("records"):
        candidate, move, early_side = _candidate_base(session, challenger, state)
        reversal_side = "SHORT" if early_side == "LONG" else "LONG" if early_side == "SHORT" else ""
        candidate["direction"] = reversal_side
        candidate["mechanical_interpretation"] = "POST_1000_MIDPOINT_CATCHUP_NEXT_BAR_1R"
        invalid: list[str] = []
        if not np.isfinite(move) or abs(move) < 0.0010:
            invalid.append("EARLY_MOVE_BELOW_0_10_PERCENT")
        if not reversal_side:
            invalid.append("NO_EARLY_DIRECTION")
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
        signal_bar = None
        midpoint = _num(candidate["early_midpoint"])
        for _, bar in step9d._bars_between(bars, "10:00", "12:55").iterrows():
            close = _num(bar.get("close"))
            if (side == "LONG" and close > midpoint) or (side == "SHORT" and close < midpoint):
                signal_bar = bar
                break
        if signal_bar is None:
            candidate["trigger_status"] = "MIDPOINT_CATCHUP_NOT_CONFIRMED"
            continue
        next_bar = step9d._next_bar_after(bars, pd.Timestamp(signal_bar["datetime"]))
        if next_bar is None or step9d._clock(next_bar["datetime"]) > "13:00":
            candidate["trigger_status"] = "MIDPOINT_CONFIRMATION_TOO_LATE"
            continue
        stop = _num(candidate["early_low"]) if side == "LONG" else _num(candidate["early_high"])
        _finalize_single_trade(
            candidate, session, challenger, bars, side, signal_bar, next_bar,
            stop, 1.0, trades, legs,
        )
    return rows


def _leader_close_orb_candidates(
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
    for state in states.sort_values("ticker").to_dict("records"):
        candidate, move, side = _candidate_base(session, challenger, state)
        candidate["direction"] = side
        candidate["mechanical_interpretation"] = "EARLY_LEADER_CLOSE_CONFIRMED_ORB_NEXT_BAR_1R"
        invalid: list[str] = []
        if not np.isfinite(move) or abs(move) < 0.0010:
            invalid.append("EARLY_MOVE_BELOW_0_10_PERCENT")
        if not side:
            invalid.append("NO_EARLY_DIRECTION")
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
        boundary = _num(candidate["early_high"]) if side == "LONG" else _num(candidate["early_low"])
        signal_bar = None
        for _, bar in step9d._bars_between(bars, "09:45", "12:55").iterrows():
            close = _num(bar.get("close"))
            if (side == "LONG" and close > boundary) or (side == "SHORT" and close < boundary):
                signal_bar = bar
                break
        if signal_bar is None:
            candidate["trigger_status"] = "NO_CLOSE_CONFIRMED_BREAKOUT"
            continue
        next_bar = step9d._next_bar_after(bars, pd.Timestamp(signal_bar["datetime"]))
        if next_bar is None or step9d._clock(next_bar["datetime"]) > "13:00":
            candidate["trigger_status"] = "BREAKOUT_CONFIRMATION_TOO_LATE"
            continue
        stop = _num(candidate["early_low"]) if side == "LONG" else _num(candidate["early_high"])
        _finalize_single_trade(
            candidate, session, challenger, bars, side, signal_bar, next_bar,
            stop, 1.0, trades, legs,
        )
    return rows


@contextmanager
def _patched_step9k_engine():
    names = [
        "EXPERIMENT_ID", "RESEARCH_STATUS", "CONTRACTS", "CONTRACT_BY_ID",
        "COMPARISONS", "CHALLENGER_BY_ID", "_single_candidates_for_challenger",
        "_intended_side",
    ]
    old = {name: getattr(step9g, name) for name in names}
    challenger_map = dict(step9g.CHALLENGER_BY_ID)
    challenger_map.update(
        {
            FAILED_LEADER_REVERSAL_ID: FAILED_LEADER_REVERSAL,
            LAGGARD_CATCHUP_ID: LAGGARD_CATCHUP,
            LEADER_CLOSE_ORB_ID: LEADER_CLOSE_ORB,
        }
    )
    original_dispatch = step9g._single_candidates_for_challenger
    original_intended_side = step9g._intended_side

    def dispatch(session, challenger, states, bars_lookup, trades, legs):
        cid = challenger["challenger_id"]
        if cid == FAILED_LEADER_REVERSAL_ID:
            return _failed_leader_reversal_candidates(session, challenger, states, bars_lookup, trades, legs)
        if cid == LAGGARD_CATCHUP_ID:
            return _laggard_catchup_candidates(session, challenger, states, bars_lookup, trades, legs)
        if cid == LEADER_CLOSE_ORB_ID:
            return _leader_close_orb_candidates(session, challenger, states, bars_lookup, trades, legs)
        return original_dispatch(session, challenger, states, bars_lookup, trades, legs)

    def intended_side(base_challenger_id: str, row: pd.Series | dict) -> str:
        if base_challenger_id in {FAILED_LEADER_REVERSAL_ID, LAGGARD_CATCHUP_ID, LEADER_CLOSE_ORB_ID}:
            # Alignment in Step 9K intentionally describes the stock's EARLY MOVE,
            # not the later reversal trade. This keeps "contrarian laggard" literal.
            return _early_move_side(row)
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


def _profit_factor(values: Iterable[float]) -> float:
    return step9g._profit_factor(values)


def _phase_map(dates: list[str]) -> dict[str, str]:
    if not dates:
        return {}
    midpoint = max(1, len(dates) // 2)
    return {date: "EARLY_HALF" if idx < midpoint else "LATE_HALF" for idx, date in enumerate(dates)}


def _direction_path_metrics(post: pd.DataFrame, reference: float, side: str) -> tuple[float, float]:
    if post.empty or reference <= 0 or side not in {"LONG", "SHORT"}:
        return np.nan, np.nan
    highs = pd.to_numeric(post["high"], errors="coerce")
    lows = pd.to_numeric(post["low"], errors="coerce")
    if side == "LONG":
        return float(highs.max() / reference - 1.0), float(lows.min() / reference - 1.0)
    low_min = lows.min()
    high_max = highs.max()
    mfe = float(reference / low_min - 1.0) if low_min > 0 else np.nan
    mae = float(reference / high_max - 1.0) if high_max > 0 else np.nan
    return mfe, mae


def _first_close_signal(bars: pd.DataFrame, start: str, end: str, predicate) -> pd.Series | None:
    for _, bar in step9d._bars_between(bars, start, end).iterrows():
        if predicate(bar):
            return bar
    return None


def build_hd_session_diagnostics(
    taxonomy: pd.DataFrame,
    prices: pd.DataFrame,
    static: pd.DataFrame,
    characteristics: pd.DataFrame,
    group_states: pd.DataFrame,
) -> pd.DataFrame:
    hd_taxonomy = taxonomy[taxonomy["primary_regime"].eq("HIGH_DISPERSION")].copy()
    if hd_taxonomy.empty:
        return pd.DataFrame(columns=HD_SESSION_DIAGNOSTIC_COLUMNS)
    hd_dates = set(hd_taxonomy["date"].astype(str))
    daily_reference = step9b.build_daily_reference(prices)
    with step9i._patched_holdout_tickers():
        raw_states, bars_lookup = step9b.build_market_state(prices, daily_reference, hd_dates)
    states = step9g.enrich_market_states(raw_states, static, characteristics, group_states)
    states = states[states["date"].astype(str).isin(hd_dates)].copy()
    taxonomy_lookup = hd_taxonomy.set_index("date").to_dict("index")
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
                    bars,
                    "09:45",
                    "12:55",
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
                    bars,
                    "10:00",
                    "12:55",
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
    return pd.DataFrame(rows, columns=HD_SESSION_DIAGNOSTIC_COLUMNS)


def build_hd_state_diagnostic_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
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


def build_trade_diagnostics(
    trades: pd.DataFrame,
    prices: pd.DataFrame,
    taxonomy_dates: set[str],
) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=TRADE_DIAGNOSTIC_COLUMNS)
    daily_reference = step9b.build_daily_reference(prices)
    with step9i._patched_holdout_tickers():
        states, bars_lookup = step9b.build_market_state(prices, daily_reference, taxonomy_dates)
    state_columns = ["date", "ticker", "early_range_pct", "early_open", "early_midpoint", "close_0940", "cutoff_close"]
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
        mfe, mae = _direction_path_metrics(scan, entry_price, side)
        risk_pct = _num(trade.get("risk_pct_at_entry"))
        midpoint = _num(trade.get("early_midpoint"))
        initial_move = _early_move(trade)
        extension = entry_price / midpoint - 1.0 if midpoint > 0 else np.nan
        entry_clock = entry_time.strftime("%H:%M")
        time_bucket = "09:45-09:59" if entry_clock < "10:00" else "10:00-10:59" if entry_clock < "11:00" else "11:00-11:59" if entry_clock < "12:00" else "12:00+"
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "contract_id": trade.get("contract_id", ""),
                "test_role": trade.get("test_role", ""),
                "date": str(trade.get("date", "")),
                "primary_regime": trade.get("primary_regime", ""),
                "ticker": trade.get("ticker", ""),
                "universe_segment": step9i._segment_for_ticker(str(trade.get("ticker", ""))),
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
    return pd.DataFrame(rows, columns=TRADE_DIAGNOSTIC_COLUMNS)


def build_group_performance(trades: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    columns = group_columns + [
        "trades", "sessions", "companies", "sectors", "net_pnl_risk_capped_sek",
        "average_pnl_per_trade_sek", "win_rate", "profit_factor",
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


def build_time_split_performance(trades: pd.DataFrame, hd_dates: list[str]) -> pd.DataFrame:
    phases = _phase_map(hd_dates)
    frame = trades.copy()
    if frame.empty:
        return build_group_performance(frame, ["contract_id", "test_role", "primary_regime", "phase"])
    frame["phase"] = frame["date"].astype(str).map(phases).fillna("OUTSIDE_SPLIT")
    result = build_group_performance(frame, ["contract_id", "test_role", "primary_regime", "phase"])
    result["interpretation"] = "Descriptive chronological stability only; both halves were visible before Step 9K and neither is confirmatory."
    return result


def enrich_performance(performance: pd.DataFrame, trades: pd.DataFrame, diagnostics: pd.DataFrame) -> pd.DataFrame:
    extras: list[dict[str, Any]] = []
    for contract in CONTRACTS:
        cid = contract["contract_id"]
        group = trades[trades["contract_id"].eq(cid)]
        diag = diagnostics[diagnostics["contract_id"].eq(cid)]
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
    return performance.merge(pd.DataFrame(extras), on="contract_id", how="left", validate="one_to_one")


def build_segment_performance(trades: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for segment, tickers in (
        ("CORE_5", step9i.CORE_TICKERS),
        ("HOLDOUT_18", step9i.HOLDOUT_ONLY_TICKERS),
        ("COMBINED_23", step9i.TRADING_TICKERS),
    ):
        subset = trades[trades["ticker"].isin(tickers)].copy() if not trades.empty else trades.copy()
        perf = build_group_performance(subset, ["contract_id", "test_role", "primary_regime"])
        perf.insert(1, "universe_segment", segment)
        frames.append(perf)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def extend_audit(
    audit: pd.DataFrame,
    taxonomy: pd.DataFrame,
    hd_diagnostics: pd.DataFrame,
    registry: pd.DataFrame,
) -> pd.DataFrame:
    hd_sessions = int(taxonomy["primary_regime"].eq("HIGH_DISPERSION").sum())
    expected_rows = hd_sessions * len(step9i.TRADING_TICKERS)
    rows = [
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "HIGH_DISPERSION_ONLY_CONTRACTS",
            "rows_checked": len(registry),
            "failures": int((~registry["primary_regime"].eq("HIGH_DISPERSION")).sum()),
            "max_abs_difference": np.nan,
            "audit_pass": bool(registry["primary_regime"].eq("HIGH_DISPERSION").all()),
            "interpretation": "Every Step 9K contract is restricted to HIGH_DISPERSION.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "HIGH_DISPERSION_DIAGNOSTIC_COVERAGE_23_TICKERS",
            "rows_checked": expected_rows,
            "failures": abs(expected_rows - len(hd_diagnostics)),
            "max_abs_difference": np.nan,
            "audit_pass": len(hd_diagnostics) == expected_rows,
            "interpretation": "Each classified HIGH_DISPERSION session has one diagnostic row for every Combined 23 ticker.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "FROZEN_NEGATIVE_CONTROL_PRESENT",
            "rows_checked": 1,
            "failures": 0 if "K_HD_LEADER_EARLY_CONTINUATION_FROZEN_CONTROL_V1" in set(registry["contract_id"]) else 1,
            "max_abs_difference": np.nan,
            "audit_pass": "K_HD_LEADER_EARLY_CONTINUATION_FROZEN_CONTROL_V1" in set(registry["contract_id"]),
            "interpretation": "The existing early-leader continuation guardrail is retained as the frozen negative control.",
        },
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "NO_STEP9K_ROUTER_ACTIVATION",
            "rows_checked": len(registry),
            "failures": int(registry["router_active"].map(_bool).sum() + registry["promotion_eligible"].map(_bool).sum()),
            "max_abs_difference": np.nan,
            "audit_pass": not registry["router_active"].map(_bool).any() and not registry["promotion_eligible"].map(_bool).any(),
            "interpretation": "Step 9K cannot modify or activate the frozen Step 9I V2 engine.",
        },
    ]
    return pd.concat([audit, pd.DataFrame(rows)], ignore_index=True)


def build_summary(
    start_date: str,
    end_date: str,
    taxonomy: pd.DataFrame,
    hd_diagnostics: pd.DataFrame,
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
        "high_dispersion_sessions": int(taxonomy["primary_regime"].eq("HIGH_DISPERSION").sum()) if not taxonomy.empty else 0,
        "diagnostic_ticker_session_rows": int(len(hd_diagnostics)),
        "contracts_registered": len(CONTRACTS),
        "primary_hypotheses": int(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in CONTRACTS)),
        "completed_trades": int(len(trades)),
        "positive_primary_contracts": int(primary["net_pnl_risk_capped_sek"].gt(0).sum()) if not primary.empty else 0,
        "primary_contracts_with_positive_late_half_pnl": int(late["net_pnl_risk_capped_sek"].gt(0).sum()) if not late.empty else 0,
        "audit_pass": audit_pass,
        "strategies_promoted": 0,
        "router_active": False,
        "classification": "STEP9K_HIGH_DISPERSION_DISCOVERY_COMPLETE_NOT_CONFIRMATORY" if audit_pass else "STEP9K_AUDIT_REVIEW_REQUIRED",
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_step9k(prices: pd.DataFrame, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    taxonomy, taxonomy_skips = build_daily_taxonomy(prices, start_date, end_date)
    if taxonomy.empty:
        raise ValueError("No point-in-time-ready taxonomy sessions are available in the requested window.")
    effective_end = str(taxonomy["date"].max())
    static, trading_prices, characteristics, group_states = step9i._full_holdout_context(prices, effective_end)

    hd_diagnostics = build_hd_session_diagnostics(
        taxonomy, trading_prices, static, characteristics, group_states
    )
    hd_state_summary = build_hd_state_diagnostic_summary(hd_diagnostics)

    with step9i._patched_holdout_tickers():
        with _patched_step9k_engine():
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

    trade_diagnostics = build_trade_diagnostics(
        trades, trading_prices, set(taxonomy["date"].astype(str))
    )
    performance = enrich_performance(performance, trades, trade_diagnostics)
    multiple = multiple.copy()
    if not multiple.empty:
        multiple["multiplicity_family"] = "THREE_PRE_REGISTERED_STEP9K_PRIMARY_HYPOTHESES"
        multiple["interpretation"] = "Post-hoc HIGH_DISPERSION discovery only; no p-value or q-value promotes a strategy."

    hd_dates = sorted(taxonomy.loc[taxonomy["primary_regime"].eq("HIGH_DISPERSION"), "date"].astype(str).unique())
    time_split = build_time_split_performance(trades, hd_dates)
    ticker_performance = build_group_performance(
        trades,
        ["contract_id", "test_role", "primary_regime", "ticker", "company_id", "broad_sector"],
    )
    if not ticker_performance.empty:
        ticker_performance.insert(
            ticker_performance.columns.get_loc("ticker") + 1,
            "universe_segment",
            ticker_performance["ticker"].map(step9i._segment_for_ticker),
        )
    sector_performance = build_group_performance(
        trades, ["contract_id", "test_role", "primary_regime", "broad_sector"]
    )
    segment_performance = build_segment_performance(trades)
    audit = extend_audit(audit, taxonomy, hd_diagnostics, registry)
    summary = build_summary(
        start_date, end_date, taxonomy, hd_diagnostics, trades, performance,
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
        "hd_session_diagnostics": hd_diagnostics,
        "hd_state_diagnostic_summary": hd_state_summary,
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
        "hd_session_diagnostics": HD_SESSION_DIAGNOSTIC_FILE,
        "hd_state_diagnostic_summary": HD_STATE_DIAGNOSTIC_FILE,
        "time_split": TIME_SPLIT_FILE,
        "ticker_performance": TICKER_FILE,
        "sector_performance": SECTOR_FILE,
        "segment_performance": SEGMENT_FILE,
        "summary": SUMMARY_FILE,
    }
    for key, path in paths.items():
        export_csv_for_power_bi(outputs[key], path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step 9K HIGH_DISPERSION strategy research on Combined 23.")
    parser.add_argument("--start-date", default="2026-05-25")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = step9i.load_shadow_prices(args.source_db)
    if prices.empty:
        raise SystemExit(f"No intraday prices found in {args.source_db}.")
    outputs = run_step9k(prices, args.start_date, args.end_date)
    export_outputs(outputs)
    summary = outputs["summary"].iloc[0]
    performance = outputs["performance"]
    print("\n=== STEP 9K HIGH DISPERSION STRATEGY RESEARCH — COMBINED 23 ===")
    print(f"Experiment          : {EXPERIMENT_ID}")
    print(f"Research status     : {RESEARCH_STATUS}")
    print(f"Requested window    : {args.start_date} through {args.end_date}")
    print(f"Effective window    : {summary['effective_start_date']} through {summary['effective_end_date']}")
    print(f"Taxonomy sessions   : {int(summary['taxonomy_sessions'])}")
    print(f"HIGH_DISP sessions  : {int(summary['high_dispersion_sessions'])}")
    print(f"Diagnostic rows     : {int(summary['diagnostic_ticker_session_rows'])}")
    print(f"Contracts           : {int(summary['contracts_registered'])} ({int(summary['primary_hypotheses'])} primaries)")
    print(f"Completed trades    : {int(summary['completed_trades'])}")
    print(f"Audit pass          : {bool(summary['audit_pass'])}")
    print(f"Classification      : {summary['classification']}")
    print("\nPrimary challenger snapshot:")
    primary = performance[performance["test_role"].eq("PRIMARY_HYPOTHESIS")][
        ["contract_id", "trades", "sessions_with_trades", "net_pnl_risk_capped_sek", "profit_factor_risk_capped"]
    ]
    print("  No primary trades were generated." if primary.empty else primary.to_string(index=False))
    print("\nStep 9I V2 remains frozen and untouched. Step 9K is historical, post-hoc, and cannot activate a router.")
    print("Review step9k_contract_performance.csv, step9k_comparisons.csv, step9k_hd_session_diagnostics.csv, and step9k_audit.csv first.")


if __name__ == "__main__":
    main()
