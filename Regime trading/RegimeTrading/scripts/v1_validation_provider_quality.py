from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.core.nasdaq_config import (
    NASDAQ_YAHOO_BAR_COMPARISON_CSV,
    NASDAQ_YAHOO_DECISION_COMPARISON_CSV,
)
from RegimeTrading.core.paths import DATA_DIR, LEGACY_OUTPUT_DIRS
from RegimeTrading.scripts import research_regime_aware_gap_recovery as gap


VALIDATION_STEP = "V1_VALIDATION_STEP_5_PROVIDER_QUALITY"
VALIDATION_STATUS = "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION"

OUTPUT_DIR = LEGACY_OUTPUT_DIRS["v1_validation"]
OUTPUT_SUMMARY = OUTPUT_DIR / "v1_validation_provider_quality_summary.csv"
OUTPUT_SESSION_DETAIL = OUTPUT_DIR / "v1_validation_provider_session_detail.csv"
OUTPUT_DAILY = OUTPUT_DIR / "v1_validation_provider_daily_summary.csv"
OUTPUT_MISMATCH = OUTPUT_DIR / "v1_validation_provider_mismatch_detail.csv"

REGIME_MIN_COVERAGE_RATE = 0.75
ENTRY_MIN_COVERAGE_RATE = 0.95
EOD_MIN_COVERAGE_RATE = 0.95
PRICE_AGREEMENT_MIN_RATE = 0.95

PHASES = {
    "regime": (gap.OPENING_RANGE_START, gap.REGIME_CUTOFF_TIME),
    "entry": (gap.ENTRY_WINDOW_START, gap.ENTRY_WINDOW_END),
    "full": (gap.OPENING_RANGE_START, gap.EOD_EXIT_TIME),
}

SUMMARY_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "source_decision_detail_present",
    "source_bar_comparison_present",
    "comparison_dates",
    "ticker_day_rows",
    "complete_eod_dates",
    "incomplete_dates",
    "setup_quality_eligible_rows",
    "final_trigger_quality_eligible_rows",
    "outcome_quality_eligible_rows",
    "setup_validity_match_rate",
    "trading_action_match_rate",
    "exact_diagnostic_match_rate",
    "entry_trigger_within_1bp_rate",
    "stop_price_within_1bp_rate",
    "current_trigger_state_match_rate",
    "final_trigger_decision_match_rate",
    "exit_reason_match_rate",
    "stage_appropriate_high_quality_rows",
    "stage_appropriate_high_quality_rate",
    "full_window_provider_overlap_rate",
    "full_window_ohlc_within_1bp_rate",
    "mismatch_rows",
    "critical_mismatch_rows",
    "provider_quality_classification",
    "generated_at_utc",
]

SESSION_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "date",
    "ticker",
    "sector_group",
    "comparison_stage",
    "expected_regime_bars",
    "expected_entry_bars",
    "expected_full_bars",
    "yahoo_regime_bars",
    "nasdaq_regime_bars",
    "both_regime_bars",
    "yahoo_entry_bars",
    "nasdaq_entry_bars",
    "both_entry_bars",
    "yahoo_full_bars",
    "nasdaq_full_bars",
    "both_full_bars",
    "yahoo_regime_coverage_rate",
    "nasdaq_regime_coverage_rate",
    "both_regime_coverage_rate",
    "yahoo_entry_coverage_rate",
    "nasdaq_entry_coverage_rate",
    "both_entry_coverage_rate",
    "yahoo_full_coverage_rate",
    "nasdaq_full_coverage_rate",
    "both_full_coverage_rate",
    "regime_ohlc_within_1bp_rate",
    "entry_ohlc_within_1bp_rate",
    "full_ohlc_within_1bp_rate",
    "yahoo_has_0930_bar",
    "nasdaq_has_0930_bar",
    "yahoo_has_0945_bar",
    "nasdaq_has_0945_bar",
    "yahoo_has_1300_bar",
    "nasdaq_has_1300_bar",
    "yahoo_has_1630_bar",
    "nasdaq_has_1630_bar",
    "setup_quality_gate_both",
    "regime_quality_gate_both",
    "entry_quality_gate_both",
    "eod_quality_gate_both",
    "stage_appropriate_bar_quality_pass",
    "setup_comparable",
    "trigger_final_comparable",
    "outcome_comparable",
    "yahoo_decision_class",
    "nasdaq_decision_class",
    "yahoo_invalid_reason",
    "nasdaq_invalid_reason",
    "yahoo_trading_action",
    "nasdaq_trading_action",
    "setup_validity_match",
    "trading_action_match",
    "exact_diagnostic_match",
    "invalid_reason_match",
    "entry_trigger_within_1bp",
    "stop_price_within_1bp",
    "current_trigger_state_match",
    "final_trigger_decision_match",
    "exit_reason_match",
    "quality_eligible_setup",
    "quality_eligible_final_trigger",
    "quality_eligible_outcome",
    "provider_quality_grade",
    "quality_reason",
    "generated_at_utc",
]

DAILY_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "date",
    "ticker_day_rows",
    "setup_ready_rows",
    "final_trigger_ready_rows",
    "final_outcome_ready_rows",
    "stage_appropriate_high_quality_rows",
    "setup_quality_eligible_rows",
    "trading_action_match_rate",
    "exact_diagnostic_match_rate",
    "all_research_tickers_present",
    "complete_eod_for_all_tickers",
    "daily_quality_status",
    "generated_at_utc",
]

MISMATCH_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "date",
    "ticker",
    "comparison_stage",
    "severity",
    "issue_type",
    "issue_detail",
    "yahoo_decision_class",
    "nasdaq_decision_class",
    "yahoo_invalid_reason",
    "nasdaq_invalid_reason",
    "generated_at_utc",
]


@dataclass(frozen=True)
class ProviderQualityResult:
    summary: pd.DataFrame
    session_detail: pd.DataFrame
    daily: pd.DataFrame
    mismatch_detail: pd.DataFrame


def now_utc_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bool_value(value) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    return frame[column].map(_bool_value).astype(bool)


def _safe_rate(frame: pd.DataFrame, column: str, mask: pd.Series | None = None) -> float:
    if column not in frame.columns:
        return np.nan
    selected = frame if mask is None else frame[mask]
    if selected.empty:
        return np.nan
    return float(_bool_series(selected, column).mean())


def _clock_range(session_date: str, start_clock: str, end_clock: str) -> pd.DatetimeIndex:
    return pd.date_range(
        f"{session_date} {start_clock}",
        f"{session_date} {end_clock}",
        freq="5min",
    )


def _decision_action(decision_class) -> str:
    text = "" if decision_class is None or pd.isna(decision_class) else str(decision_class)
    if text == "INVALID":
        return "NO_TRADE_INVALID_SETUP"
    if text in {"WAITING", "MISSING", ""}:
        return "NOT_FINAL_WAITING_FOR_DATA"
    if text == "VALID_NOT_TRIGGERED":
        return "NO_ENTRY_YET"
    if text in {"TRIGGERED_OPEN", "TRIGGERED_CLOSED"}:
        return "ENTRY_TRIGGERED"
    return "UNKNOWN"


def _setup_valid(decision_class) -> bool:
    text = "" if decision_class is None or pd.isna(decision_class) else str(decision_class)
    return text not in {"INVALID", "WAITING", "MISSING", ""}


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _prepare_bar_comparison(bar_comparison: pd.DataFrame) -> pd.DataFrame:
    if bar_comparison.empty:
        return bar_comparison.copy()
    bars = bar_comparison.copy()
    bars["datetime"] = pd.to_datetime(bars.get("datetime"), errors="coerce").dt.floor("5min")
    bars = bars.dropna(subset=["datetime", "ticker"])
    bars["date"] = bars["datetime"].dt.strftime("%Y-%m-%d")
    bars["ticker"] = bars["ticker"].astype(str).str.strip()
    for column in ["has_nasdaq_bar", "has_yahoo_bar", "has_both", "ohlc_within_1bp"]:
        bars[column] = _bool_series(bars, column)
    return bars.sort_values(["date", "ticker", "datetime"]).reset_index(drop=True)


def _prepare_decision_detail(decision_detail: pd.DataFrame) -> pd.DataFrame:
    if decision_detail.empty:
        return decision_detail.copy()
    detail = decision_detail.copy()
    detail["date"] = detail["date"].astype(str)
    detail["ticker"] = detail["ticker"].astype(str).str.strip()
    return detail.sort_values(["date", "ticker"]).reset_index(drop=True)


def _keys_from_sources(
    decision_detail: pd.DataFrame,
    bar_comparison: pd.DataFrame,
) -> pd.DataFrame:
    key_frames: list[pd.DataFrame] = []
    if not decision_detail.empty:
        columns = [column for column in ["date", "ticker", "sector_group"] if column in decision_detail]
        key_frames.append(decision_detail[columns].copy())
    if not bar_comparison.empty:
        key_frames.append(bar_comparison[["date", "ticker"]].copy())
    if not key_frames:
        return pd.DataFrame(columns=["date", "ticker", "sector_group"])
    keys = pd.concat(key_frames, ignore_index=True, sort=False)
    if "sector_group" not in keys:
        keys["sector_group"] = ""
    keys["sector_group"] = keys["sector_group"].fillna("")
    keys = (
        keys.sort_values(["date", "ticker", "sector_group"], ascending=[True, True, False])
        .drop_duplicates(["date", "ticker"], keep="first")
        .reset_index(drop=True)
    )
    return keys[["date", "ticker", "sector_group"]]


def _phase_metrics(
    bars: pd.DataFrame,
    session_date: str,
    phase: str,
) -> dict:
    start_clock, end_clock = PHASES[phase]
    expected = _clock_range(session_date, start_clock, end_clock)
    expected_set = set(expected)
    if bars.empty:
        selected = bars.copy()
    else:
        selected = bars[bars["datetime"].isin(expected_set)].copy()

    yahoo_count = int(selected.loc[selected["has_yahoo_bar"], "datetime"].nunique())
    nasdaq_count = int(selected.loc[selected["has_nasdaq_bar"], "datetime"].nunique())
    both_count = int(selected.loc[selected["has_both"], "datetime"].nunique())
    expected_count = int(len(expected))
    both = selected[selected["has_both"]]
    ohlc_rate = (
        float(both["ohlc_within_1bp"].mean()) if not both.empty else np.nan
    )
    return {
        f"expected_{phase}_bars": expected_count,
        f"yahoo_{phase}_bars": yahoo_count,
        f"nasdaq_{phase}_bars": nasdaq_count,
        f"both_{phase}_bars": both_count,
        f"yahoo_{phase}_coverage_rate": yahoo_count / expected_count,
        f"nasdaq_{phase}_coverage_rate": nasdaq_count / expected_count,
        f"both_{phase}_coverage_rate": both_count / expected_count,
        f"{phase}_ohlc_within_1bp_rate": ohlc_rate,
    }


def _has_provider_bar(bars: pd.DataFrame, session_date: str, clock: str, provider: str) -> bool:
    timestamp = pd.Timestamp(f"{session_date} {clock}")
    column = f"has_{provider}_bar"
    if bars.empty or column not in bars:
        return False
    return bool(((bars["datetime"] == timestamp) & bars[column]).any())


def build_session_detail(
    decision_detail: pd.DataFrame,
    bar_comparison: pd.DataFrame,
) -> pd.DataFrame:
    decisions = _prepare_decision_detail(decision_detail)
    bars = _prepare_bar_comparison(bar_comparison)
    keys = _keys_from_sources(decisions, bars)
    if keys.empty:
        return pd.DataFrame(columns=SESSION_COLUMNS)

    decision_lookup = decisions.set_index(["date", "ticker"], drop=False) if not decisions.empty else None
    rows: list[dict] = []
    generated = now_utc_text()

    for key in keys.itertuples(index=False):
        session_date = str(key.date)
        ticker = str(key.ticker)
        ticker_bars = bars[(bars["date"].eq(session_date)) & (bars["ticker"].eq(ticker))]
        row: dict = {
            "strategy_id": gap.STRATEGY_ID,
            "validation_step": VALIDATION_STEP,
            "validation_status": VALIDATION_STATUS,
            "date": session_date,
            "ticker": ticker,
            "sector_group": str(getattr(key, "sector_group", "") or ""),
            "generated_at_utc": generated,
        }
        for phase in PHASES:
            row.update(_phase_metrics(ticker_bars, session_date, phase))

        for clock_key, clock in [("0930", "09:30"), ("0945", "09:45"), ("1300", "13:00"), ("1630", "16:30")]:
            row[f"yahoo_has_{clock_key}_bar"] = _has_provider_bar(ticker_bars, session_date, clock, "yahoo")
            row[f"nasdaq_has_{clock_key}_bar"] = _has_provider_bar(ticker_bars, session_date, clock, "nasdaq")

        row["setup_quality_gate_both"] = bool(
            row["yahoo_has_0930_bar"] and row["nasdaq_has_0930_bar"]
        )
        row["regime_quality_gate_both"] = bool(
            row["setup_quality_gate_both"]
            and row["yahoo_has_0945_bar"]
            and row["nasdaq_has_0945_bar"]
            and row["yahoo_regime_coverage_rate"] >= REGIME_MIN_COVERAGE_RATE
            and row["nasdaq_regime_coverage_rate"] >= REGIME_MIN_COVERAGE_RATE
        )
        row["entry_quality_gate_both"] = bool(
            row["regime_quality_gate_both"]
            and row["yahoo_has_1300_bar"]
            and row["nasdaq_has_1300_bar"]
            and row["yahoo_entry_coverage_rate"] >= ENTRY_MIN_COVERAGE_RATE
            and row["nasdaq_entry_coverage_rate"] >= ENTRY_MIN_COVERAGE_RATE
        )
        row["eod_quality_gate_both"] = bool(
            row["entry_quality_gate_both"]
            and row["yahoo_has_1630_bar"]
            and row["nasdaq_has_1630_bar"]
            and row["yahoo_full_coverage_rate"] >= EOD_MIN_COVERAGE_RATE
            and row["nasdaq_full_coverage_rate"] >= EOD_MIN_COVERAGE_RATE
        )

        if row["eod_quality_gate_both"]:
            row["comparison_stage"] = "FINAL_OUTCOME_READY"
            overlap_rate = row["both_full_coverage_rate"]
            price_rate = row["full_ohlc_within_1bp_rate"]
        elif row["entry_quality_gate_both"]:
            row["comparison_stage"] = "FINAL_TRIGGER_READY"
            overlap_rate = row["both_entry_coverage_rate"]
            price_rate = row["entry_ohlc_within_1bp_rate"]
        elif row["regime_quality_gate_both"]:
            row["comparison_stage"] = "LIVE_SETUP_READY"
            overlap_rate = row["both_regime_coverage_rate"]
            price_rate = row["regime_ohlc_within_1bp_rate"]
        else:
            row["comparison_stage"] = "INCOMPLETE"
            overlap_rate = row["both_regime_coverage_rate"]
            price_rate = row["regime_ohlc_within_1bp_rate"]

        row["stage_appropriate_bar_quality_pass"] = bool(
            row["comparison_stage"] != "INCOMPLETE"
            and overlap_rate >= PRICE_AGREEMENT_MIN_RATE
            and pd.notna(price_rate)
            and float(price_rate) >= PRICE_AGREEMENT_MIN_RATE
        )

        decision = None
        if decision_lookup is not None and (session_date, ticker) in decision_lookup.index:
            selected = decision_lookup.loc[(session_date, ticker)]
            decision = selected.iloc[0] if isinstance(selected, pd.DataFrame) else selected

        def decision_value(column: str, default=np.nan):
            if decision is None or column not in decision.index:
                return default
            return decision[column]

        row["setup_comparable"] = _bool_value(decision_value("setup_comparable", False))
        row["trigger_final_comparable"] = _bool_value(decision_value("trigger_final_comparable", False))
        row["outcome_comparable"] = _bool_value(decision_value("outcome_comparable", False))
        row["yahoo_decision_class"] = decision_value("yahoo_decision_class", "")
        row["nasdaq_decision_class"] = decision_value("nasdaq_decision_class", "")
        row["yahoo_invalid_reason"] = decision_value("yahoo_invalid_reason", "")
        row["nasdaq_invalid_reason"] = decision_value("nasdaq_invalid_reason", "")
        row["yahoo_trading_action"] = _decision_action(row["yahoo_decision_class"])
        row["nasdaq_trading_action"] = _decision_action(row["nasdaq_decision_class"])
        row["setup_validity_match"] = bool(
            row["setup_comparable"]
            and _setup_valid(row["yahoo_decision_class"])
            == _setup_valid(row["nasdaq_decision_class"])
        )
        row["trading_action_match"] = bool(
            row["setup_comparable"]
            and row["yahoo_trading_action"] == row["nasdaq_trading_action"]
        )
        row["exact_diagnostic_match"] = _bool_value(
            decision_value("overall_current_decision_match", False)
        )
        for column in [
            "invalid_reason_match",
            "entry_trigger_within_1bp",
            "stop_price_within_1bp",
            "current_trigger_state_match",
            "final_trigger_decision_match",
            "exit_reason_match",
        ]:
            row[column] = _bool_value(decision_value(column, False))

        row["quality_eligible_setup"] = bool(
            row["regime_quality_gate_both"] and row["setup_comparable"]
        )
        row["quality_eligible_final_trigger"] = bool(
            row["entry_quality_gate_both"] and row["trigger_final_comparable"]
        )
        row["quality_eligible_outcome"] = bool(
            row["eod_quality_gate_both"] and row["outcome_comparable"]
        )

        reasons: list[str] = []
        if row["comparison_stage"] == "INCOMPLETE":
            reasons.append("PROVIDER_SESSION_INCOMPLETE")
        if row["comparison_stage"] != "INCOMPLETE" and not row["stage_appropriate_bar_quality_pass"]:
            reasons.append("BAR_COVERAGE_OR_PRICE_AGREEMENT_BELOW_GATE")
        if row["quality_eligible_setup"] and not row["trading_action_match"]:
            reasons.append("TRADING_ACTION_MISMATCH")
        if row["quality_eligible_setup"] and row["trading_action_match"] and not row["exact_diagnostic_match"]:
            reasons.append("DIAGNOSTIC_DETAIL_MISMATCH")
        if row["quality_eligible_final_trigger"] and not row["final_trigger_decision_match"]:
            reasons.append("FINAL_TRIGGER_MISMATCH")
        if row["quality_eligible_outcome"] and not row["exit_reason_match"]:
            reasons.append("OUTCOME_MISMATCH")

        if row["comparison_stage"] == "FINAL_OUTCOME_READY" and row["stage_appropriate_bar_quality_pass"]:
            row["provider_quality_grade"] = "A_FINAL_OUTCOME_READY"
        elif row["comparison_stage"] == "FINAL_TRIGGER_READY" and row["stage_appropriate_bar_quality_pass"]:
            row["provider_quality_grade"] = "B_FINAL_TRIGGER_READY"
        elif row["comparison_stage"] == "LIVE_SETUP_READY" and row["stage_appropriate_bar_quality_pass"]:
            row["provider_quality_grade"] = "C_LIVE_SETUP_READY"
        elif row["comparison_stage"] == "INCOMPLETE":
            row["provider_quality_grade"] = "D_INCOMPLETE"
        else:
            row["provider_quality_grade"] = "D_QUALITY_GATE_FAIL"
        row["quality_reason"] = "|".join(reasons) if reasons else "QUALITY_GATES_PASS"
        rows.append(row)

    result = pd.DataFrame(rows)
    for column in SESSION_COLUMNS:
        if column not in result:
            result[column] = np.nan
    return result[SESSION_COLUMNS].sort_values(["date", "ticker"]).reset_index(drop=True)


def build_daily(session_detail: pd.DataFrame) -> pd.DataFrame:
    if session_detail.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    rows: list[dict] = []
    generated = now_utc_text()
    expected_tickers = len(gap.GAP_RECOVERY_TICKERS)
    for session_date, frame in session_detail.groupby("date", sort=True):
        setup_eligible = _bool_series(frame, "quality_eligible_setup")
        high_quality = _bool_series(frame, "stage_appropriate_bar_quality_pass")
        exact = _bool_series(frame, "exact_diagnostic_match")
        action = _bool_series(frame, "trading_action_match")
        rows.append(
            {
                "strategy_id": gap.STRATEGY_ID,
                "validation_step": VALIDATION_STEP,
                "validation_status": VALIDATION_STATUS,
                "date": str(session_date),
                "ticker_day_rows": int(len(frame)),
                "setup_ready_rows": int(frame["comparison_stage"].isin(["LIVE_SETUP_READY", "FINAL_TRIGGER_READY", "FINAL_OUTCOME_READY"]).sum()),
                "final_trigger_ready_rows": int(frame["comparison_stage"].isin(["FINAL_TRIGGER_READY", "FINAL_OUTCOME_READY"]).sum()),
                "final_outcome_ready_rows": int(frame["comparison_stage"].eq("FINAL_OUTCOME_READY").sum()),
                "stage_appropriate_high_quality_rows": int(high_quality.sum()),
                "setup_quality_eligible_rows": int(setup_eligible.sum()),
                "trading_action_match_rate": float(action[setup_eligible].mean()) if setup_eligible.any() else np.nan,
                "exact_diagnostic_match_rate": float(exact[setup_eligible].mean()) if setup_eligible.any() else np.nan,
                "all_research_tickers_present": int(frame["ticker"].nunique()) == expected_tickers,
                "complete_eod_for_all_tickers": bool(
                    int(frame["ticker"].nunique()) == expected_tickers
                    and _bool_series(frame, "eod_quality_gate_both").all()
                ),
                "daily_quality_status": "COMPLETE_FINAL_SESSION" if (
                    int(frame["ticker"].nunique()) == expected_tickers
                    and _bool_series(frame, "eod_quality_gate_both").all()
                ) else "PARTIAL_OR_INCOMPLETE_SESSION",
                "generated_at_utc": generated,
            }
        )
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def build_mismatch_detail(session_detail: pd.DataFrame) -> pd.DataFrame:
    if session_detail.empty:
        return pd.DataFrame(columns=MISMATCH_COLUMNS)
    rows: list[dict] = []
    generated = now_utc_text()
    for item in session_detail.itertuples(index=False):
        issues: list[tuple[str, str, str]] = []
        if item.comparison_stage == "INCOMPLETE":
            issues.append(("WARNING", "SESSION_INCOMPLETE", "One or both providers failed the stage-completeness gate."))
        elif not bool(item.stage_appropriate_bar_quality_pass):
            issues.append(("WARNING", "BAR_QUALITY_GATE_FAIL", "Stage-appropriate overlap or OHLC agreement was below 95%."))
        if bool(item.quality_eligible_setup) and not bool(item.trading_action_match):
            issues.append(("CRITICAL", "TRADING_ACTION_MISMATCH", "Yahoo and Nasdaq imply different operational actions."))
        if bool(item.quality_eligible_setup) and bool(item.trading_action_match) and not bool(item.exact_diagnostic_match):
            issues.append(("INFO", "DIAGNOSTIC_DETAIL_MISMATCH", "Operational action matches, but an underlying diagnostic label or detail differs."))
        if bool(item.quality_eligible_final_trigger) and not bool(item.final_trigger_decision_match):
            issues.append(("CRITICAL", "FINAL_TRIGGER_MISMATCH", "Completed entry-window trigger decisions differ."))
        if bool(item.quality_eligible_outcome) and not bool(item.exit_reason_match):
            issues.append(("CRITICAL", "OUTCOME_MISMATCH", "Final exit outcomes differ."))

        for severity, issue_type, detail in issues:
            rows.append(
                {
                    "strategy_id": gap.STRATEGY_ID,
                    "validation_step": VALIDATION_STEP,
                    "validation_status": VALIDATION_STATUS,
                    "date": item.date,
                    "ticker": item.ticker,
                    "comparison_stage": item.comparison_stage,
                    "severity": severity,
                    "issue_type": issue_type,
                    "issue_detail": detail,
                    "yahoo_decision_class": item.yahoo_decision_class,
                    "nasdaq_decision_class": item.nasdaq_decision_class,
                    "yahoo_invalid_reason": getattr(item, "yahoo_invalid_reason", ""),
                    "nasdaq_invalid_reason": getattr(item, "nasdaq_invalid_reason", ""),
                    "generated_at_utc": generated,
                }
            )
    return pd.DataFrame(rows, columns=MISMATCH_COLUMNS)


def _classification(
    ticker_day_rows: int,
    complete_eod_dates: int,
    action_rate: float,
    exact_rate: float,
    high_quality_rate: float,
) -> str:
    if ticker_day_rows == 0:
        return "NO_PROVIDER_COMPARISON_DATA"
    if pd.isna(action_rate):
        return "INSUFFICIENT_QUALITY_ELIGIBLE_DECISIONS"
    strong = (
        action_rate >= 0.99
        and (pd.isna(exact_rate) or exact_rate >= 0.90)
        and (pd.isna(high_quality_rate) or high_quality_rate >= 0.90)
    )
    if strong and complete_eod_dates >= 10:
        return "PROVIDER_ALIGNMENT_PASS"
    if strong:
        return "EARLY_STRONG_ALIGNMENT_MORE_COMPLETE_SESSIONS_REQUIRED"
    if action_rate >= 0.95:
        return "TRADING_ACTIONS_ALIGNED_REVIEW_QUALITY_DETAILS"
    return "PROVIDER_ALIGNMENT_REVIEW_REQUIRED"


def build_summary(
    session_detail: pd.DataFrame,
    daily: pd.DataFrame,
    mismatch_detail: pd.DataFrame,
    source_decision_detail_present: bool,
    source_bar_comparison_present: bool,
) -> pd.DataFrame:
    if session_detail.empty:
        row = {column: np.nan for column in SUMMARY_COLUMNS}
        row.update(
            {
                "strategy_id": gap.STRATEGY_ID,
                "validation_step": VALIDATION_STEP,
                "validation_status": VALIDATION_STATUS,
                "source_decision_detail_present": source_decision_detail_present,
                "source_bar_comparison_present": source_bar_comparison_present,
                "comparison_dates": 0,
                "ticker_day_rows": 0,
                "complete_eod_dates": 0,
                "incomplete_dates": 0,
                "mismatch_rows": 0,
                "critical_mismatch_rows": 0,
                "provider_quality_classification": "NO_PROVIDER_COMPARISON_DATA",
                "generated_at_utc": now_utc_text(),
            }
        )
        return pd.DataFrame([row], columns=SUMMARY_COLUMNS)

    setup = _bool_series(session_detail, "quality_eligible_setup")
    final_trigger = _bool_series(session_detail, "quality_eligible_final_trigger")
    outcome = _bool_series(session_detail, "quality_eligible_outcome")
    high_quality = _bool_series(session_detail, "stage_appropriate_bar_quality_pass")
    eod_complete_dates = int(_bool_series(daily, "complete_eod_for_all_tickers").sum()) if not daily.empty else 0
    comparison_dates = int(session_detail["date"].nunique())
    action_rate = _safe_rate(session_detail, "trading_action_match", setup)
    exact_rate = _safe_rate(session_detail, "exact_diagnostic_match", setup)
    high_quality_rate = float(high_quality.mean()) if len(high_quality) else np.nan

    full_both = float(session_detail["both_full_bars"].sum())
    full_expected = float(session_detail["expected_full_bars"].sum())
    full_overlap_rate = full_both / full_expected if full_expected else np.nan
    full_price_rows = session_detail["full_ohlc_within_1bp_rate"].dropna()
    full_price_rate = float(full_price_rows.mean()) if not full_price_rows.empty else np.nan

    row = {
        "strategy_id": gap.STRATEGY_ID,
        "validation_step": VALIDATION_STEP,
        "validation_status": VALIDATION_STATUS,
        "source_decision_detail_present": source_decision_detail_present,
        "source_bar_comparison_present": source_bar_comparison_present,
        "comparison_dates": comparison_dates,
        "ticker_day_rows": int(len(session_detail)),
        "complete_eod_dates": eod_complete_dates,
        "incomplete_dates": comparison_dates - eod_complete_dates,
        "setup_quality_eligible_rows": int(setup.sum()),
        "final_trigger_quality_eligible_rows": int(final_trigger.sum()),
        "outcome_quality_eligible_rows": int(outcome.sum()),
        "setup_validity_match_rate": _safe_rate(session_detail, "setup_validity_match", setup),
        "trading_action_match_rate": action_rate,
        "exact_diagnostic_match_rate": exact_rate,
        "entry_trigger_within_1bp_rate": _safe_rate(session_detail, "entry_trigger_within_1bp", setup),
        "stop_price_within_1bp_rate": _safe_rate(session_detail, "stop_price_within_1bp", setup),
        "current_trigger_state_match_rate": _safe_rate(
            session_detail,
            "current_trigger_state_match",
            setup & session_detail["yahoo_decision_class"].isin(["VALID_NOT_TRIGGERED", "TRIGGERED_OPEN", "TRIGGERED_CLOSED"]),
        ),
        "final_trigger_decision_match_rate": _safe_rate(session_detail, "final_trigger_decision_match", final_trigger),
        "exit_reason_match_rate": _safe_rate(session_detail, "exit_reason_match", outcome),
        "stage_appropriate_high_quality_rows": int(high_quality.sum()),
        "stage_appropriate_high_quality_rate": high_quality_rate,
        "full_window_provider_overlap_rate": full_overlap_rate,
        "full_window_ohlc_within_1bp_rate": full_price_rate,
        "mismatch_rows": int(len(mismatch_detail)),
        "critical_mismatch_rows": int((mismatch_detail.get("severity", pd.Series(dtype=str)) == "CRITICAL").sum()),
        "provider_quality_classification": _classification(
            len(session_detail), eod_complete_dates, action_rate, exact_rate, high_quality_rate
        ),
        "generated_at_utc": now_utc_text(),
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def build_validation_step5(
    decision_detail: pd.DataFrame,
    bar_comparison: pd.DataFrame,
    source_decision_detail_present: bool = True,
    source_bar_comparison_present: bool = True,
) -> ProviderQualityResult:
    session_detail = build_session_detail(decision_detail, bar_comparison)
    daily = build_daily(session_detail)
    mismatch_detail = build_mismatch_detail(session_detail)
    summary = build_summary(
        session_detail,
        daily,
        mismatch_detail,
        source_decision_detail_present,
        source_bar_comparison_present,
    )
    return ProviderQualityResult(summary, session_detail, daily, mismatch_detail)


def main() -> None:
    print("\n=== V1 RESEARCH VALIDATION SUITE - STEP 5 ===")
    print("Module          : Nasdaq/Yahoo provider quality and completeness gates")
    print(f"Strategy        : {gap.STRATEGY_ID}")
    print(f"Decision source : {NASDAQ_YAHOO_DECISION_COMPARISON_CSV}")
    print(f"Bar source      : {NASDAQ_YAHOO_BAR_COMPARISON_CSV}")
    print("V1 research input remains Yahoo and is not changed.")

    decision_exists = NASDAQ_YAHOO_DECISION_COMPARISON_CSV.exists()
    bars_exist = NASDAQ_YAHOO_BAR_COMPARISON_CSV.exists()
    decisions = _load_csv(NASDAQ_YAHOO_DECISION_COMPARISON_CSV)
    bars = _load_csv(NASDAQ_YAHOO_BAR_COMPARISON_CSV)
    result = build_validation_step5(decisions, bars, decision_exists, bars_exist)

    result.summary.to_csv(OUTPUT_SUMMARY, index=False)
    result.session_detail.to_csv(OUTPUT_SESSION_DETAIL, index=False)
    result.daily.to_csv(OUTPUT_DAILY, index=False)
    result.mismatch_detail.to_csv(OUTPUT_MISMATCH, index=False)

    print(f"Saved {OUTPUT_SUMMARY.name}: {len(result.summary)} rows")
    print(f"Saved {OUTPUT_SESSION_DETAIL.name}: {len(result.session_detail)} rows")
    print(f"Saved {OUTPUT_DAILY.name}: {len(result.daily)} rows")
    print(f"Saved {OUTPUT_MISMATCH.name}: {len(result.mismatch_detail)} rows")

    summary = result.summary.iloc[0]
    print("\n=== PROVIDER QUALITY RESULT ===")
    print(f"Comparison dates              : {int(summary['comparison_dates'])}")
    print(f"Ticker-day rows               : {int(summary['ticker_day_rows'])}")
    print(f"Complete EOD dates            : {int(summary['complete_eod_dates'])}")
    for label, column in [
        ("Trading-action match", "trading_action_match_rate"),
        ("Exact diagnostic match", "exact_diagnostic_match_rate"),
        ("Stage high-quality rate", "stage_appropriate_high_quality_rate"),
        ("Final trigger match", "final_trigger_decision_match_rate"),
        ("Exit reason match", "exit_reason_match_rate"),
    ]:
        value = summary[column]
        print(f"{label:<30}: " + (f"{float(value):.2%}" if pd.notna(value) else "not available"))
    print(f"Critical mismatch rows        : {int(summary['critical_mismatch_rows'])}")
    print(f"Classification                : {summary['provider_quality_classification']}")
    print("Step 5 validation export complete.")


if __name__ == "__main__":
    main()
