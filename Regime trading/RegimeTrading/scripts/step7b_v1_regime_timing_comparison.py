from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, legacy_output_path
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    FAVORABLE_REGIMES,
    build_candidates_and_trades,
    build_daily_reference,
    calculate_early_market_regime,
    classify_early_regime,
    load_intraday_prices,
)
from RegimeTrading.scripts.v1_validation_portfolio import simulate_portfolio


COMPARISON_ID = "V1_REGIME_TIMING_STRICT_0940_VS_LEGACY_0945"
RESEARCH_STATUS = "SIMULATION_ONLY_POINT_IN_TIME_RECONCILIATION"
BAR_TIMESTAMP_CONVENTION = "START_LABELLED_5_MINUTE_BARS"
DECISION_TIME = "09:45"
STRICT_LATEST_LABEL = "09:40"
LEGACY_LATEST_LABEL = "09:45"

SUMMARY_FILE = legacy_output_path("regime_v1_timing_comparison_summary.csv")
DAILY_FILE = legacy_output_path("regime_v1_timing_comparison_daily.csv")
CANDIDATE_FILE = legacy_output_path("regime_v1_timing_comparison_candidates.csv")
TRADE_FILE = legacy_output_path("regime_v1_timing_comparison_trades.csv")

SUMMARY_COLUMNS = [
    "comparison_id",
    "research_status",
    "bar_timestamp_convention",
    "decision_time",
    "strict_latest_label",
    "legacy_latest_label",
    "observed_sessions",
    "comparison_eligible_sessions",
    "regime_label_match_sessions",
    "regime_label_match_rate",
    "changed_regime_label_sessions",
    "favorable_gate_match_sessions",
    "favorable_gate_match_rate",
    "changed_favorable_gate_sessions",
    "candidate_rows_compared",
    "candidate_action_match_rows",
    "candidate_action_match_rate",
    "changed_candidate_action_rows",
    "legacy_triggered_trade_rows",
    "strict_triggered_trade_rows",
    "common_triggered_trade_rows",
    "legacy_only_triggered_trade_rows",
    "strict_only_triggered_trade_rows",
    "legacy_portfolio_realized_pnl_sek",
    "strict_portfolio_realized_pnl_sek",
    "strict_minus_legacy_pnl_sek",
    "legacy_selected_closed_trades",
    "strict_selected_closed_trades",
    "legacy_selected_open_trades",
    "strict_selected_open_trades",
    "classification",
]

DAILY_COLUMNS = [
    "comparison_id",
    "date",
    "comparison_eligible",
    "legacy_sample_size",
    "strict_sample_size",
    "legacy_breadth_above_open",
    "strict_breadth_above_open",
    "breadth_difference_strict_minus_legacy",
    "legacy_median_return_from_open",
    "strict_median_return_from_open",
    "median_return_difference_strict_minus_legacy",
    "legacy_positive_gap_breadth",
    "strict_positive_gap_breadth",
    "legacy_median_gap",
    "strict_median_gap",
    "legacy_regime",
    "strict_regime",
    "regime_label_match",
    "legacy_favorable",
    "strict_favorable",
    "favorable_gate_match",
    "candidate_rows",
    "candidate_action_mismatches",
    "legacy_triggered_trades",
    "strict_triggered_trades",
    "legacy_trade_pnl_sek_unconstrained",
    "strict_trade_pnl_sek_unconstrained",
    "daily_status",
]

CANDIDATE_COLUMNS = [
    "comparison_id",
    "date",
    "ticker",
    "comparison_eligible",
    "legacy_regime",
    "strict_regime",
    "regime_label_match",
    "legacy_favorable",
    "strict_favorable",
    "favorable_gate_match",
    "legacy_candidate_status",
    "strict_candidate_status",
    "legacy_action_class",
    "strict_action_class",
    "trading_action_match",
    "legacy_invalid_reason",
    "strict_invalid_reason",
    "legacy_entry_time",
    "strict_entry_time",
    "entry_time_match",
    "legacy_entry_trigger",
    "strict_entry_trigger",
    "entry_trigger_difference",
    "legacy_stop_price",
    "strict_stop_price",
    "stop_price_difference",
    "legacy_target_price",
    "strict_target_price",
    "target_price_difference",
    "legacy_would_cross_entry_anyway",
    "strict_would_cross_entry_anyway",
    "regime_gate_changed",
    "timing_change_material_to_candidate",
]

TRADE_COLUMNS = [
    "comparison_id",
    "date",
    "ticker",
    "legacy_trade_present",
    "strict_trade_present",
    "trade_presence_match",
    "legacy_entry_time",
    "strict_entry_time",
    "entry_time_match",
    "legacy_exit_time",
    "strict_exit_time",
    "exit_time_match",
    "legacy_exit_reason",
    "strict_exit_reason",
    "exit_reason_match",
    "legacy_pnl_sek",
    "strict_pnl_sek",
    "pnl_difference_strict_minus_legacy",
    "legacy_regime",
    "strict_regime",
]


def _calculate_regime_at_label(
    prices: pd.DataFrame,
    daily_reference: pd.DataFrame,
    latest_label: str,
) -> pd.DataFrame:
    """Replicate frozen V1 regime inputs with only the latest bar label changed."""
    output_columns = [
        "date",
        "sample_size",
        "breadth_above_open",
        "median_return_from_open",
        "positive_gap_breadth",
        "median_gap",
        "early_market_regime",
        "favorable_regime",
    ]
    if prices.empty or daily_reference.empty:
        return pd.DataFrame(columns=output_columns)

    clocks = prices["datetime"].dt.strftime("%H:%M")
    cutoff = prices[clocks.le(latest_label)].copy()
    if cutoff.empty:
        return pd.DataFrame(columns=output_columns)

    cutoff_last = (
        cutoff.groupby(["ticker", "date"], as_index=False)
        .agg(cutoff_price=("close", "last"))
    )
    regime_input = cutoff_last.merge(
        daily_reference[["ticker", "date", "open_price", "previous_close"]],
        on=["ticker", "date"],
        how="left",
    )
    regime_input = regime_input.dropna(
        subset=["cutoff_price", "open_price", "previous_close"]
    )
    regime_input = regime_input[
        (regime_input["cutoff_price"] > 0)
        & (regime_input["open_price"] > 0)
        & (regime_input["previous_close"] > 0)
    ].copy()
    if regime_input.empty:
        return pd.DataFrame(columns=output_columns)

    regime_input["return_from_open"] = (
        regime_input["cutoff_price"] / regime_input["open_price"] - 1.0
    )
    regime_input["gap"] = (
        regime_input["open_price"] / regime_input["previous_close"] - 1.0
    )
    regime_input["above_open"] = regime_input["return_from_open"] > 0
    regime_input["positive_gap"] = regime_input["gap"] >= 0

    regime = (
        regime_input.groupby("date", as_index=False)
        .agg(
            sample_size=("ticker", "nunique"),
            breadth_above_open=("above_open", "mean"),
            median_return_from_open=("return_from_open", "median"),
            positive_gap_breadth=("positive_gap", "mean"),
            median_gap=("gap", "median"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    regime["early_market_regime"] = regime.apply(
        lambda row: classify_early_regime(
            sample_size=int(row["sample_size"]),
            breadth_above_open=float(row["breadth_above_open"]),
            median_return_from_open=float(row["median_return_from_open"]),
            positive_gap_breadth=float(row["positive_gap_breadth"]),
            median_gap=float(row["median_gap"]),
        ),
        axis=1,
    )
    regime["favorable_regime"] = regime["early_market_regime"].isin(
        FAVORABLE_REGIMES
    )
    return regime[output_columns]


def _action_class(status: object) -> str:
    value = str(status or "").strip().upper()
    if value.startswith("TRIGGERED"):
        return "TRADE_TRIGGERED"
    if value in {"NOT_TRIGGERED", "MONITORING"}:
        return "SETUP_ELIGIBLE_NO_TRIGGER"
    if value.startswith("WAITING"):
        return "PROVISIONAL_WAITING"
    if value == "INVALID":
        return "REJECTED"
    return "UNKNOWN"


def _bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if pd.isna(value):
        return False
    return bool(value)


def _num(value: object) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else np.nan


def _equal_numeric(left: object, right: object, tolerance: float = 1e-10) -> bool:
    left_num = _num(left)
    right_num = _num(right)
    if pd.isna(left_num) and pd.isna(right_num):
        return True
    if pd.isna(left_num) or pd.isna(right_num):
        return False
    return bool(abs(left_num - right_num) <= tolerance)


def _portfolio_metric(result, column: str, default: float = 0.0) -> float:
    if result.summary.empty or column not in result.summary.columns:
        return default
    value = pd.to_numeric(result.summary.iloc[0][column], errors="coerce")
    return float(value) if pd.notna(value) else default


def build_candidate_comparison(
    legacy_candidates: pd.DataFrame,
    strict_candidates: pd.DataFrame,
    daily: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["date", "ticker"]
    legacy = legacy_candidates.copy()
    strict = strict_candidates.copy()
    legacy["date"] = legacy["date"].astype(str)
    strict["date"] = strict["date"].astype(str)

    keep = [
        "date",
        "ticker",
        "candidate_status",
        "invalid_reason",
        "entry_time",
        "entry_trigger",
        "stop_price",
        "target_price",
        "would_cross_entry_anyway",
    ]
    merged = legacy[keep].merge(
        strict[keep],
        on=keys,
        how="outer",
        suffixes=("_legacy", "_strict"),
    )

    daily_lookup = daily.set_index("date").to_dict("index") if not daily.empty else {}
    rows: list[dict[str, object]] = []
    for row in merged.to_dict("records"):
        date = str(row["date"])
        day = daily_lookup.get(date, {})
        legacy_status = str(row.get("candidate_status_legacy", ""))
        strict_status = str(row.get("candidate_status_strict", ""))
        legacy_action = _action_class(legacy_status)
        strict_action = _action_class(strict_status)
        action_match = legacy_action == strict_action
        legacy_favorable = _bool(day.get("legacy_favorable"))
        strict_favorable = _bool(day.get("strict_favorable"))
        gate_changed = legacy_favorable != strict_favorable

        rows.append(
            {
                "comparison_id": COMPARISON_ID,
                "date": date,
                "ticker": row["ticker"],
                "comparison_eligible": _bool(day.get("comparison_eligible")),
                "legacy_regime": day.get("legacy_regime", ""),
                "strict_regime": day.get("strict_regime", ""),
                "regime_label_match": _bool(day.get("regime_label_match")),
                "legacy_favorable": legacy_favorable,
                "strict_favorable": strict_favorable,
                "favorable_gate_match": legacy_favorable == strict_favorable,
                "legacy_candidate_status": legacy_status,
                "strict_candidate_status": strict_status,
                "legacy_action_class": legacy_action,
                "strict_action_class": strict_action,
                "trading_action_match": action_match,
                "legacy_invalid_reason": str(row.get("invalid_reason_legacy", "") or ""),
                "strict_invalid_reason": str(row.get("invalid_reason_strict", "") or ""),
                "legacy_entry_time": str(row.get("entry_time_legacy", "") or ""),
                "strict_entry_time": str(row.get("entry_time_strict", "") or ""),
                "entry_time_match": str(row.get("entry_time_legacy", "") or "") == str(row.get("entry_time_strict", "") or ""),
                "legacy_entry_trigger": _num(row.get("entry_trigger_legacy")),
                "strict_entry_trigger": _num(row.get("entry_trigger_strict")),
                "entry_trigger_difference": _num(row.get("entry_trigger_strict")) - _num(row.get("entry_trigger_legacy")),
                "legacy_stop_price": _num(row.get("stop_price_legacy")),
                "strict_stop_price": _num(row.get("stop_price_strict")),
                "stop_price_difference": _num(row.get("stop_price_strict")) - _num(row.get("stop_price_legacy")),
                "legacy_target_price": _num(row.get("target_price_legacy")),
                "strict_target_price": _num(row.get("target_price_strict")),
                "target_price_difference": _num(row.get("target_price_strict")) - _num(row.get("target_price_legacy")),
                "legacy_would_cross_entry_anyway": _bool(row.get("would_cross_entry_anyway_legacy")),
                "strict_would_cross_entry_anyway": _bool(row.get("would_cross_entry_anyway_strict")),
                "regime_gate_changed": gate_changed,
                "timing_change_material_to_candidate": bool(gate_changed and not action_match),
            }
        )

    result = pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)
    if not result.empty:
        result = result.sort_values(["date", "ticker"]).reset_index(drop=True)
    return result


def build_trade_comparison(
    legacy_trades: pd.DataFrame,
    strict_trades: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["date", "ticker"]
    legacy = legacy_trades.copy()
    strict = strict_trades.copy()
    for frame in (legacy, strict):
        if not frame.empty:
            frame["date"] = frame["date"].astype(str)

    keep = [
        "date",
        "ticker",
        "entry_time",
        "exit_time",
        "exit_reason",
        "pnl_sek",
        "early_market_regime",
    ]
    legacy = legacy[keep] if not legacy.empty else pd.DataFrame(columns=keep)
    strict = strict[keep] if not strict.empty else pd.DataFrame(columns=keep)
    merged = legacy.merge(
        strict,
        on=keys,
        how="outer",
        suffixes=("_legacy", "_strict"),
        indicator=True,
    )

    rows: list[dict[str, object]] = []
    for row in merged.to_dict("records"):
        legacy_present = row.get("_merge") in {"both", "left_only"}
        strict_present = row.get("_merge") in {"both", "right_only"}
        legacy_entry = str(row.get("entry_time_legacy", "") or "")
        strict_entry = str(row.get("entry_time_strict", "") or "")
        legacy_exit = str(row.get("exit_time_legacy", "") or "")
        strict_exit = str(row.get("exit_time_strict", "") or "")
        legacy_reason = str(row.get("exit_reason_legacy", "") or "")
        strict_reason = str(row.get("exit_reason_strict", "") or "")
        legacy_pnl = _num(row.get("pnl_sek_legacy")) if legacy_present else 0.0
        strict_pnl = _num(row.get("pnl_sek_strict")) if strict_present else 0.0
        if pd.isna(legacy_pnl):
            legacy_pnl = 0.0
        if pd.isna(strict_pnl):
            strict_pnl = 0.0

        rows.append(
            {
                "comparison_id": COMPARISON_ID,
                "date": str(row["date"]),
                "ticker": row["ticker"],
                "legacy_trade_present": legacy_present,
                "strict_trade_present": strict_present,
                "trade_presence_match": legacy_present == strict_present,
                "legacy_entry_time": legacy_entry,
                "strict_entry_time": strict_entry,
                "entry_time_match": legacy_entry == strict_entry,
                "legacy_exit_time": legacy_exit,
                "strict_exit_time": strict_exit,
                "exit_time_match": legacy_exit == strict_exit,
                "legacy_exit_reason": legacy_reason,
                "strict_exit_reason": strict_reason,
                "exit_reason_match": legacy_reason == strict_reason,
                "legacy_pnl_sek": legacy_pnl,
                "strict_pnl_sek": strict_pnl,
                "pnl_difference_strict_minus_legacy": strict_pnl - legacy_pnl,
                "legacy_regime": str(row.get("early_market_regime_legacy", "") or ""),
                "strict_regime": str(row.get("early_market_regime_strict", "") or ""),
            }
        )

    result = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    if not result.empty:
        result = result.sort_values(["date", "ticker"]).reset_index(drop=True)
    return result


def build_daily_comparison(
    legacy_regime: pd.DataFrame,
    strict_regime: pd.DataFrame,
    candidate_detail: pd.DataFrame,
    legacy_trades: pd.DataFrame,
    strict_trades: pd.DataFrame,
    observed_dates: list[str],
) -> pd.DataFrame:
    legacy = legacy_regime.copy().rename(
        columns={column: f"legacy_{column}" for column in legacy_regime.columns if column != "date"}
    )
    strict = strict_regime.copy().rename(
        columns={column: f"strict_{column}" for column in strict_regime.columns if column != "date"}
    )
    base = pd.DataFrame({"date": observed_dates})
    base["date"] = base["date"].astype(str)
    for frame in (legacy, strict):
        if not frame.empty:
            frame["date"] = frame["date"].astype(str)
    merged = base.merge(legacy, on="date", how="left").merge(strict, on="date", how="left")

    candidate_daily = pd.DataFrame()
    if not candidate_detail.empty:
        candidate_daily = (
            candidate_detail.groupby("date", as_index=False)
            .agg(
                candidate_rows=("ticker", "count"),
                candidate_action_mismatches=("trading_action_match", lambda s: int((~s.astype(bool)).sum())),
            )
        )

    def _trade_daily(trades: pd.DataFrame, prefix: str) -> pd.DataFrame:
        if trades.empty:
            return pd.DataFrame(columns=["date", f"{prefix}_triggered_trades", f"{prefix}_trade_pnl_sek_unconstrained"])
        frame = trades.copy()
        frame["date"] = frame["date"].astype(str)
        frame["pnl_sek"] = pd.to_numeric(frame["pnl_sek"], errors="coerce").fillna(0.0)
        return (
            frame.groupby("date", as_index=False)
            .agg(
                **{
                    f"{prefix}_triggered_trades": ("ticker", "count"),
                    f"{prefix}_trade_pnl_sek_unconstrained": ("pnl_sek", "sum"),
                }
            )
        )

    merged = merged.merge(candidate_daily, on="date", how="left")
    merged = merged.merge(_trade_daily(legacy_trades, "legacy"), on="date", how="left")
    merged = merged.merge(_trade_daily(strict_trades, "strict"), on="date", how="left")

    rows: list[dict[str, object]] = []
    for row in merged.to_dict("records"):
        legacy_sample = _num(row.get("legacy_sample_size"))
        strict_sample = _num(row.get("strict_sample_size"))
        eligible = bool(pd.notna(legacy_sample) and pd.notna(strict_sample) and legacy_sample >= 5 and strict_sample >= 5)
        legacy_regime_label = str(row.get("legacy_early_market_regime", "") or "")
        strict_regime_label = str(row.get("strict_early_market_regime", "") or "")
        label_match = legacy_regime_label == strict_regime_label
        legacy_favorable = _bool(row.get("legacy_favorable_regime"))
        strict_favorable = _bool(row.get("strict_favorable_regime"))
        gate_match = legacy_favorable == strict_favorable
        candidate_mismatches = int(_num(row.get("candidate_action_mismatches")) if pd.notna(_num(row.get("candidate_action_mismatches"))) else 0)

        if not eligible:
            daily_status = "NOT_COMPARISON_ELIGIBLE"
        elif label_match and gate_match and candidate_mismatches == 0:
            daily_status = "IDENTICAL"
        elif gate_match and candidate_mismatches == 0:
            daily_status = "LABEL_CHANGED_NO_TRADING_IMPACT"
        else:
            daily_status = "TRADING_IMPACT"

        rows.append(
            {
                "comparison_id": COMPARISON_ID,
                "date": str(row["date"]),
                "comparison_eligible": eligible,
                "legacy_sample_size": legacy_sample,
                "strict_sample_size": strict_sample,
                "legacy_breadth_above_open": _num(row.get("legacy_breadth_above_open")),
                "strict_breadth_above_open": _num(row.get("strict_breadth_above_open")),
                "breadth_difference_strict_minus_legacy": _num(row.get("strict_breadth_above_open")) - _num(row.get("legacy_breadth_above_open")),
                "legacy_median_return_from_open": _num(row.get("legacy_median_return_from_open")),
                "strict_median_return_from_open": _num(row.get("strict_median_return_from_open")),
                "median_return_difference_strict_minus_legacy": _num(row.get("strict_median_return_from_open")) - _num(row.get("legacy_median_return_from_open")),
                "legacy_positive_gap_breadth": _num(row.get("legacy_positive_gap_breadth")),
                "strict_positive_gap_breadth": _num(row.get("strict_positive_gap_breadth")),
                "legacy_median_gap": _num(row.get("legacy_median_gap")),
                "strict_median_gap": _num(row.get("strict_median_gap")),
                "legacy_regime": legacy_regime_label,
                "strict_regime": strict_regime_label,
                "regime_label_match": label_match,
                "legacy_favorable": legacy_favorable,
                "strict_favorable": strict_favorable,
                "favorable_gate_match": gate_match,
                "candidate_rows": int(_num(row.get("candidate_rows")) if pd.notna(_num(row.get("candidate_rows"))) else 0),
                "candidate_action_mismatches": candidate_mismatches,
                "legacy_triggered_trades": int(_num(row.get("legacy_triggered_trades")) if pd.notna(_num(row.get("legacy_triggered_trades"))) else 0),
                "strict_triggered_trades": int(_num(row.get("strict_triggered_trades")) if pd.notna(_num(row.get("strict_triggered_trades"))) else 0),
                "legacy_trade_pnl_sek_unconstrained": _num(row.get("legacy_trade_pnl_sek_unconstrained")) if pd.notna(_num(row.get("legacy_trade_pnl_sek_unconstrained"))) else 0.0,
                "strict_trade_pnl_sek_unconstrained": _num(row.get("strict_trade_pnl_sek_unconstrained")) if pd.notna(_num(row.get("strict_trade_pnl_sek_unconstrained"))) else 0.0,
                "daily_status": daily_status,
            }
        )

    return pd.DataFrame(rows, columns=DAILY_COLUMNS).sort_values("date").reset_index(drop=True)


def build_summary(
    daily: pd.DataFrame,
    candidate_detail: pd.DataFrame,
    trade_detail: pd.DataFrame,
    legacy_portfolio,
    strict_portfolio,
) -> pd.DataFrame:
    eligible_daily = daily[daily["comparison_eligible"] == True].copy()  # noqa: E712
    eligible_candidates = candidate_detail[candidate_detail["comparison_eligible"] == True].copy()  # noqa: E712

    observed_sessions = len(daily)
    comparison_sessions = len(eligible_daily)
    label_matches = int(eligible_daily["regime_label_match"].astype(bool).sum()) if comparison_sessions else 0
    gate_matches = int(eligible_daily["favorable_gate_match"].astype(bool).sum()) if comparison_sessions else 0
    candidate_rows = len(eligible_candidates)
    action_matches = int(eligible_candidates["trading_action_match"].astype(bool).sum()) if candidate_rows else 0

    legacy_count = int(trade_detail["legacy_trade_present"].astype(bool).sum()) if not trade_detail.empty else 0
    strict_count = int(trade_detail["strict_trade_present"].astype(bool).sum()) if not trade_detail.empty else 0
    common_count = int((trade_detail["legacy_trade_present"].astype(bool) & trade_detail["strict_trade_present"].astype(bool)).sum()) if not trade_detail.empty else 0
    legacy_only = int((trade_detail["legacy_trade_present"].astype(bool) & ~trade_detail["strict_trade_present"].astype(bool)).sum()) if not trade_detail.empty else 0
    strict_only = int((~trade_detail["legacy_trade_present"].astype(bool) & trade_detail["strict_trade_present"].astype(bool)).sum()) if not trade_detail.empty else 0

    legacy_pnl = _portfolio_metric(legacy_portfolio, "total_realized_pnl_sek")
    strict_pnl = _portfolio_metric(strict_portfolio, "total_realized_pnl_sek")
    pnl_difference = strict_pnl - legacy_pnl
    changed_actions = candidate_rows - action_matches
    changed_gates = comparison_sessions - gate_matches
    changed_labels = comparison_sessions - label_matches

    if changed_actions == 0 and abs(pnl_difference) <= 1e-9:
        if changed_labels == 0:
            classification = "STRICT_0940_AND_LEGACY_0945_IDENTICAL"
        else:
            classification = "LABEL_DIFFERENCES_NO_TRADING_IMPACT"
    elif changed_gates == 0 and abs(pnl_difference) <= 1e-9:
        classification = "NON_GATE_DIAGNOSTIC_DIFFERENCES_NO_PORTFOLIO_IMPACT"
    elif abs(pnl_difference) <= 5.0 and changed_actions <= max(2, int(candidate_rows * 0.01)):
        classification = "LIMITED_V1_TIMING_IMPACT_VERSIONED_FIX_RECOMMENDED"
    else:
        classification = "MATERIAL_V1_TIMING_IMPACT_VERSIONED_FIX_REQUIRED"

    row = {
        "comparison_id": COMPARISON_ID,
        "research_status": RESEARCH_STATUS,
        "bar_timestamp_convention": BAR_TIMESTAMP_CONVENTION,
        "decision_time": DECISION_TIME,
        "strict_latest_label": STRICT_LATEST_LABEL,
        "legacy_latest_label": LEGACY_LATEST_LABEL,
        "observed_sessions": observed_sessions,
        "comparison_eligible_sessions": comparison_sessions,
        "regime_label_match_sessions": label_matches,
        "regime_label_match_rate": label_matches / comparison_sessions if comparison_sessions else np.nan,
        "changed_regime_label_sessions": changed_labels,
        "favorable_gate_match_sessions": gate_matches,
        "favorable_gate_match_rate": gate_matches / comparison_sessions if comparison_sessions else np.nan,
        "changed_favorable_gate_sessions": changed_gates,
        "candidate_rows_compared": candidate_rows,
        "candidate_action_match_rows": action_matches,
        "candidate_action_match_rate": action_matches / candidate_rows if candidate_rows else np.nan,
        "changed_candidate_action_rows": changed_actions,
        "legacy_triggered_trade_rows": legacy_count,
        "strict_triggered_trade_rows": strict_count,
        "common_triggered_trade_rows": common_count,
        "legacy_only_triggered_trade_rows": legacy_only,
        "strict_only_triggered_trade_rows": strict_only,
        "legacy_portfolio_realized_pnl_sek": legacy_pnl,
        "strict_portfolio_realized_pnl_sek": strict_pnl,
        "strict_minus_legacy_pnl_sek": pnl_difference,
        "legacy_selected_closed_trades": int(_portfolio_metric(legacy_portfolio, "selected_closed_trades")),
        "strict_selected_closed_trades": int(_portfolio_metric(strict_portfolio, "selected_closed_trades")),
        "legacy_selected_open_trades": int(_portfolio_metric(legacy_portfolio, "selected_open_trades")),
        "strict_selected_open_trades": int(_portfolio_metric(strict_portfolio, "selected_open_trades")),
        "classification": classification,
    }
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def run_comparison(db_path: Path = INTRADAY_DB):
    prices = load_intraday_prices(db_path)
    daily_reference = build_daily_reference(prices)

    # Call the frozen implementation for the legacy side. This protects the
    # comparison against accidental drift from the historical V1 definition.
    legacy_regime = calculate_early_market_regime(prices, daily_reference)
    strict_regime = _calculate_regime_at_label(
        prices,
        daily_reference,
        latest_label=STRICT_LATEST_LABEL,
    )

    legacy_candidates, legacy_trades = build_candidates_and_trades(
        prices,
        daily_reference,
        legacy_regime,
    )
    strict_candidates, strict_trades = build_candidates_and_trades(
        prices,
        daily_reference,
        strict_regime,
    )

    observed_dates = sorted(prices["date"].astype(str).unique().tolist()) if not prices.empty else []

    # Build a provisional daily frame first so candidate comparison can inherit
    # the regime labels and comparison-eligibility flag.
    legacy_daily = legacy_regime.copy().rename(
        columns={column: f"legacy_{column}" for column in legacy_regime.columns if column != "date"}
    )
    strict_daily = strict_regime.copy().rename(
        columns={column: f"strict_{column}" for column in strict_regime.columns if column != "date"}
    )
    provisional = pd.DataFrame({"date": observed_dates})
    for frame in (legacy_daily, strict_daily):
        if not frame.empty:
            frame["date"] = frame["date"].astype(str)
    provisional = provisional.merge(legacy_daily, on="date", how="left").merge(strict_daily, on="date", how="left")
    provisional["comparison_eligible"] = (
        pd.to_numeric(provisional.get("legacy_sample_size"), errors="coerce").ge(5)
        & pd.to_numeric(provisional.get("strict_sample_size"), errors="coerce").ge(5)
    )
    provisional["legacy_regime"] = provisional.get("legacy_early_market_regime", "")
    provisional["strict_regime"] = provisional.get("strict_early_market_regime", "")
    provisional["regime_label_match"] = provisional["legacy_regime"].fillna("") == provisional["strict_regime"].fillna("")
    legacy_favorable_series = provisional.get(
        "legacy_favorable_regime",
        pd.Series(False, index=provisional.index, dtype="boolean"),
    )
    strict_favorable_series = provisional.get(
        "strict_favorable_regime",
        pd.Series(False, index=provisional.index, dtype="boolean"),
    )
    provisional["legacy_favorable"] = legacy_favorable_series.astype("boolean").fillna(False).astype(bool)
    provisional["strict_favorable"] = strict_favorable_series.astype("boolean").fillna(False).astype(bool)

    candidate_detail = build_candidate_comparison(
        legacy_candidates,
        strict_candidates,
        provisional[[
            "date",
            "comparison_eligible",
            "legacy_regime",
            "strict_regime",
            "regime_label_match",
            "legacy_favorable",
            "strict_favorable",
        ]],
    )
    trade_detail = build_trade_comparison(legacy_trades, strict_trades)
    daily = build_daily_comparison(
        legacy_regime,
        strict_regime,
        candidate_detail,
        legacy_trades,
        strict_trades,
        observed_dates,
    )

    legacy_portfolio = simulate_portfolio(legacy_trades)
    strict_portfolio = simulate_portfolio(strict_trades)
    summary = build_summary(
        daily,
        candidate_detail,
        trade_detail,
        legacy_portfolio,
        strict_portfolio,
    )
    return summary, daily, candidate_detail, trade_detail


def export_outputs(summary, daily, candidate_detail, trade_detail) -> None:
    exports = [
        (summary, SUMMARY_FILE),
        (daily, DAILY_FILE),
        (candidate_detail, CANDIDATE_FILE),
        (trade_detail, TRADE_FILE),
    ]
    for frame, path in exports:
        export_csv_for_power_bi(frame, path)
        print(f"Saved {path.name}: {len(frame)} rows")


def main() -> None:
    print("\n=== STEP 7B V1 REGIME TIMING COMPARISON ===")
    print(f"Comparison       : {COMPARISON_ID}")
    print(f"Decision time    : {DECISION_TIME}")
    print(f"Strict input     : labels through {STRICT_LATEST_LABEL}")
    print(f"Legacy V1 input  : labels through {LEGACY_LATEST_LABEL}")
    print("Frozen V1 is not modified; the strict implementation is a shadow comparison only.")

    summary, daily, candidates, trades = run_comparison()
    export_outputs(summary, daily, candidates, trades)

    row = summary.iloc[0]
    eligible = int(row["comparison_eligible_sessions"])
    label_match_rate = float(row["regime_label_match_rate"]) if pd.notna(row["regime_label_match_rate"]) else np.nan
    gate_match_rate = float(row["favorable_gate_match_rate"]) if pd.notna(row["favorable_gate_match_rate"]) else np.nan
    action_match_rate = float(row["candidate_action_match_rate"]) if pd.notna(row["candidate_action_match_rate"]) else np.nan

    print("\n=== STEP 7B REGIME TIMING RESULT ===")
    print(f"Observed sessions            : {int(row['observed_sessions'])}")
    print(f"Comparison-eligible sessions : {eligible}")
    print(f"Regime label match           : {label_match_rate:.2%}" if pd.notna(label_match_rate) else "Regime label match           : not available")
    print(f"Changed regime labels        : {int(row['changed_regime_label_sessions'])}")
    print(f"Favorable gate match         : {gate_match_rate:.2%}" if pd.notna(gate_match_rate) else "Favorable gate match         : not available")
    print(f"Changed favorable gates      : {int(row['changed_favorable_gate_sessions'])}")
    print(f"Candidate action match       : {action_match_rate:.2%}" if pd.notna(action_match_rate) else "Candidate action match       : not available")
    print(f"Changed candidate actions    : {int(row['changed_candidate_action_rows'])}")
    print(f"Legacy / strict trades       : {int(row['legacy_triggered_trade_rows'])}/{int(row['strict_triggered_trade_rows'])}")
    print(f"Legacy portfolio PnL         : {float(row['legacy_portfolio_realized_pnl_sek']):.2f} SEK")
    print(f"Strict portfolio PnL         : {float(row['strict_portfolio_realized_pnl_sek']):.2f} SEK")
    print(f"Strict minus legacy PnL      : {float(row['strict_minus_legacy_pnl_sek']):.2f} SEK")
    print(f"Classification               : {row['classification']}")
    print("Step 7B timing comparison export complete.")


if __name__ == "__main__":
    main()
