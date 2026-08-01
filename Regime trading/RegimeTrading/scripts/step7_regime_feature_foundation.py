from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, legacy_output_path
from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    GAP_RECOVERY_TICKERS,
    load_intraday_prices,
)


FEATURE_SET_ID = "REGIME_POINT_IN_TIME_FEATURES_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_REGIME_SYSTEM_RESEARCH"
DECISION_TIME = "09:45"
OPENING_BAR_LABEL = "09:30"
BAR_INTERVAL_MINUTES = 5
LATEST_ALLOWED_BAR_LABEL = "09:40"
EARLY_EXPECTED_LABELS = ("09:30", "09:35", "09:40")
MIN_CROSS_SECTION_TICKERS = 5
FULL_COVERAGE_THRESHOLD = 0.95

SUMMARY_FILE = legacy_output_path("regime_feature_foundation_summary.csv")
DAILY_FEATURES_FILE = legacy_output_path("regime_daily_features.csv")
DEFINITIONS_FILE = legacy_output_path("regime_feature_definitions.csv")
COMPLETENESS_FILE = legacy_output_path("regime_feature_completeness.csv")
AUDIT_FILE = legacy_output_path("regime_point_in_time_audit.csv")
V1_DAILY_FILE = legacy_output_path("regime_gap_recovery_daily.csv")

SUMMARY_COLUMNS = [
    "feature_set_id",
    "research_status",
    "decision_time",
    "bar_timestamp_convention",
    "latest_allowed_bar_label",
    "observed_sessions",
    "minimum_ready_sessions",
    "full_ready_sessions",
    "partial_sessions",
    "classifier_audit_rows",
    "classifier_audit_pass_rows",
    "classifier_audit_fail_rows",
    "point_in_time_leakage_rows",
    "available_now_feature_count",
    "planned_external_feature_count",
    "diagnostic_only_feature_count",
    "v1_diagnostic_joined_sessions",
    "first_session_date",
    "last_session_date",
    "classification",
]

DAILY_FEATURE_COLUMNS = [
    "feature_set_id",
    "research_status",
    "date",
    "decision_time",
    "bar_timestamp_convention",
    "latest_allowed_bar_label",
    "universe_ticker_count",
    "observed_ticker_count",
    "prior_close_ticker_count",
    "opening_ticker_count",
    "strict_cutoff_ticker_count",
    "valid_cross_section_ticker_count",
    "expected_early_bar_count_total",
    "observed_early_bar_count_total",
    "early_bar_coverage_rate",
    "max_early_source_timestamp",
    "max_early_source_information_time",
    "previous_session_date",
    "previous_session_max_source_timestamp",
    "previous_session_complete",
    "gap_up_breadth",
    "gap_down_breadth",
    "flat_gap_breadth",
    "mean_gap",
    "median_gap",
    "gap_std",
    "gap_q25",
    "gap_q75",
    "minimum_gap",
    "maximum_gap",
    "breadth_above_open_at_cutoff",
    "breadth_below_open_at_cutoff",
    "breadth_above_previous_close_at_cutoff",
    "mean_return_from_open",
    "median_return_from_open",
    "return_from_open_std",
    "return_from_open_q25",
    "return_from_open_q75",
    "minimum_return_from_open",
    "maximum_return_from_open",
    "cross_sectional_return_dispersion",
    "mean_opening_range_pct",
    "median_opening_range_pct",
    "opening_range_dispersion_pct",
    "mean_early_realized_volatility",
    "median_early_realized_volatility",
    "breadth_above_open_at_0935",
    "breadth_above_open_at_0940",
    "breadth_acceleration_0935_to_0940",
    "median_return_from_open_at_0935",
    "median_return_from_open_at_0940",
    "median_return_acceleration_0935_to_0940",
    "previous_session_equal_weight_return",
    "previous_session_median_return",
    "previous_session_positive_breadth",
    "previous_session_cross_sectional_dispersion",
    "prior_2_session_market_return",
    "prior_5_session_market_return",
    "prior_10_session_market_return",
    "prior_5_session_realized_volatility",
    "prior_10_session_realized_volatility",
    "prior_5_session_max_drawdown",
    "prior_10_session_max_drawdown",
    "previous_session_pct_above_5d_sma",
    "previous_session_pct_above_10d_sma",
    "consecutive_positive_sessions",
    "consecutive_negative_sessions",
    "minimum_regime_feature_ready",
    "full_regime_feature_ready",
    "feature_row_status",
    "point_in_time_safe",
    "v1_diagnostic_available",
    "v1_valid_candidates",
    "v1_triggered_candidates",
    "v1_completed_trades",
    "v1_realized_pnl_sek",
    "v1_account_return",
    "v1_diagnostic_after_session_only",
]

COMPLETENESS_COLUMNS = [
    "feature_set_id",
    "date",
    "early_session_status",
    "previous_session_status",
    "history_2_session_status",
    "history_5_session_status",
    "history_10_session_status",
    "v1_diagnostic_status",
    "available_model_feature_count",
    "total_model_feature_count",
    "missing_model_feature_count",
    "feature_completeness_rate",
    "minimum_regime_feature_ready",
    "full_regime_feature_ready",
    "feature_row_status",
    "excluded_or_partial_reason",
]

AUDIT_COLUMNS = [
    "feature_set_id",
    "date",
    "audit_group",
    "classifier_eligible",
    "source_scope",
    "max_source_timestamp",
    "max_source_information_time",
    "allowed_information_time",
    "point_in_time_pass",
    "audit_status",
    "rows_or_sessions_used",
    "notes",
]

DEFINITION_COLUMNS = [
    "feature_name",
    "feature_group",
    "description",
    "formula_or_method",
    "source",
    "source_availability",
    "decision_time_eligible",
    "point_in_time_rule",
    "current_status",
    "included_in_initial_classifier",
    "data_type",
]

MODEL_FEATURE_COLUMNS = [
    "gap_up_breadth",
    "gap_down_breadth",
    "mean_gap",
    "median_gap",
    "gap_std",
    "breadth_above_open_at_cutoff",
    "breadth_above_previous_close_at_cutoff",
    "mean_return_from_open",
    "median_return_from_open",
    "cross_sectional_return_dispersion",
    "median_opening_range_pct",
    "median_early_realized_volatility",
    "breadth_acceleration_0935_to_0940",
    "median_return_acceleration_0935_to_0940",
    "previous_session_equal_weight_return",
    "previous_session_positive_breadth",
    "previous_session_cross_sectional_dispersion",
    "prior_2_session_market_return",
    "prior_5_session_market_return",
    "prior_10_session_market_return",
    "prior_5_session_realized_volatility",
    "prior_10_session_realized_volatility",
    "prior_5_session_max_drawdown",
    "prior_10_session_max_drawdown",
    "previous_session_pct_above_5d_sma",
    "previous_session_pct_above_10d_sma",
    "consecutive_positive_sessions",
    "consecutive_negative_sessions",
]

MINIMUM_REQUIRED_FEATURE_COLUMNS = [
    "median_gap",
    "breadth_above_open_at_cutoff",
    "median_return_from_open",
    "cross_sectional_return_dispersion",
    "median_opening_range_pct",
    "previous_session_equal_weight_return",
    "previous_session_positive_breadth",
]

PLANNED_EXTERNAL_FEATURES = [
    (
        "omxs30_overnight_return",
        "MACRO_EXTERNAL",
        "OMXS30 move from the previous official close to the latest pre-decision quote.",
        "latest pre-decision index level / previous official close - 1",
        "External index feed",
    ),
    (
        "stoxx50_prior_session_return",
        "MACRO_EXTERNAL",
        "Previous completed session return for the Euro Stoxx 50.",
        "official close / previous official close - 1",
        "External index feed",
    ),
    (
        "sp500_prior_session_return",
        "MACRO_EXTERNAL",
        "Previous completed US session return known before the Stockholm open.",
        "official close / previous official close - 1",
        "External index feed",
    ),
    (
        "vix_prior_close",
        "MACRO_EXTERNAL",
        "Latest completed VIX close available before the decision time.",
        "official prior close",
        "External volatility feed",
    ),
    (
        "eursek_overnight_return",
        "MACRO_EXTERNAL",
        "Overnight EUR/SEK movement available before the decision time.",
        "latest pre-decision quote / prior reference quote - 1",
        "External FX feed",
    ),
    (
        "sweden_2y_yield_change_bps",
        "MACRO_EXTERNAL",
        "Change in the Swedish two-year government yield known before the decision time.",
        "latest eligible yield minus prior close, in basis points",
        "External rates feed",
    ),
    (
        "brent_overnight_return",
        "MACRO_EXTERNAL",
        "Overnight Brent crude return known before the decision time.",
        "latest pre-decision quote / prior close - 1",
        "External commodity feed",
    ),
    (
        "scheduled_macro_event_flag",
        "MACRO_CALENDAR",
        "Flag for a scheduled high-impact macro release relevant to the session.",
        "point-in-time calendar lookup using publication schedule only",
        "External economic calendar",
    ),
    (
        "central_bank_event_flag",
        "MACRO_CALENDAR",
        "Flag for a scheduled central-bank decision, minutes, or major speech.",
        "point-in-time calendar lookup using publication schedule only",
        "External central-bank calendar",
    ),
]


@dataclass(frozen=True)
class FeatureFoundationResult:
    summary: pd.DataFrame
    daily_features: pd.DataFrame
    definitions: pd.DataFrame
    completeness: pd.DataFrame
    audit: pd.DataFrame


def _clock(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.strftime("%H:%M")


def _safe_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if not values.empty else np.nan


def _safe_median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.median()) if not values.empty else np.nan


def _safe_std(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.std(ddof=0)) if not values.empty else np.nan


def _safe_quantile(series: pd.Series, q: float) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.quantile(q)) if not values.empty else np.nan


def _compound_return(values: Iterable[float]) -> float:
    series = pd.Series(list(values), dtype="float64").dropna()
    if series.empty:
        return np.nan
    return float((1.0 + series).prod() - 1.0)


def _max_drawdown(values: Iterable[float]) -> float:
    returns = pd.Series(list(values), dtype="float64").dropna()
    if returns.empty:
        return np.nan
    wealth = (1.0 + returns).cumprod()
    peaks = wealth.cummax()
    drawdowns = wealth / peaks - 1.0
    return float(drawdowns.min())


def _consecutive_sign(values: Iterable[float], positive: bool) -> int:
    count = 0
    for value in reversed(list(values)):
        if pd.isna(value):
            break
        matches = float(value) > 0 if positive else float(value) < 0
        if not matches:
            break
        count += 1
    return count


def _as_iso_timestamp(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _prepare_prices(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker", "date"])

    prepared = prices.copy()
    prepared["datetime"] = pd.to_datetime(prepared["datetime"], errors="coerce")
    prepared["ticker"] = prepared["ticker"].astype(str).str.strip()
    for column in ["open", "high", "low", "close"]:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    prepared = prepared[
        prepared["ticker"].isin(GAP_RECOVERY_TICKERS)
    ].dropna(subset=["datetime", "ticker", "high", "low", "close"])
    prepared["open"] = prepared["open"].where(prepared["open"].notna(), prepared["close"])
    prepared["date"] = prepared["datetime"].dt.date
    prepared = prepared.sort_values(["ticker", "datetime"]).drop_duplicates(
        subset=["ticker", "datetime"], keep="last"
    )
    return prepared.reset_index(drop=True)


def _build_daily_market_history(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if prices.empty:
        return pd.DataFrame(), pd.DataFrame()

    daily_ticker = (
        prices.groupby(["ticker", "date"], as_index=False)
        .agg(
            daily_open=("open", "first"),
            daily_close=("close", "last"),
            first_timestamp=("datetime", "min"),
            last_timestamp=("datetime", "max"),
        )
        .sort_values(["ticker", "date"])
        .reset_index(drop=True)
    )
    daily_ticker["previous_close"] = daily_ticker.groupby("ticker")["daily_close"].shift(1)
    daily_ticker["daily_return"] = daily_ticker["daily_close"] / daily_ticker["previous_close"] - 1.0
    daily_ticker["positive_daily_return"] = np.where(
        daily_ticker["daily_return"].notna(),
        (daily_ticker["daily_return"] > 0).astype(float),
        np.nan,
    )
    daily_ticker["session_complete_ticker"] = (
        pd.to_datetime(daily_ticker["last_timestamp"]).dt.strftime("%H:%M") >= "16:30"
    )

    for window in (5, 10):
        rolling = daily_ticker.groupby("ticker")["daily_close"].transform(
            lambda series: series.rolling(window, min_periods=window).mean()
        )
        daily_ticker[f"above_{window}d_sma"] = np.where(
            rolling.notna(),
            (daily_ticker["daily_close"] > rolling).astype(float),
            np.nan,
        )

    market_daily = (
        daily_ticker.groupby("date", as_index=False)
        .agg(
            equal_weight_return=("daily_return", "mean"),
            median_return=("daily_return", "median"),
            positive_breadth=("positive_daily_return", "mean"),
            cross_sectional_dispersion=("daily_return", lambda s: pd.to_numeric(s, errors="coerce").std(ddof=0)),
            ticker_count=("ticker", "nunique"),
            complete_ticker_count=("session_complete_ticker", "sum"),
            max_source_timestamp=("last_timestamp", "max"),
            pct_above_5d_sma=("above_5d_sma", "mean"),
            pct_above_10d_sma=("above_10d_sma", "mean"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    market_daily["session_complete"] = market_daily["complete_ticker_count"].eq(
        len(GAP_RECOVERY_TICKERS)
    )
    return daily_ticker, market_daily


def _build_early_ticker_features(prices: pd.DataFrame, daily_ticker: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()

    working = prices.copy()
    working["clock"] = _clock(working["datetime"])
    early = working[
        working["clock"].isin(EARLY_EXPECTED_LABELS)
    ].copy()
    if early.empty:
        return pd.DataFrame()

    prior = daily_ticker[["ticker", "date", "previous_close"]].copy()
    rows: list[dict[str, object]] = []

    for (ticker, session_date), group in early.groupby(["ticker", "date"], sort=True):
        group = group.sort_values("datetime").copy()
        by_clock = group.drop_duplicates("clock", keep="last").set_index("clock")
        opening = by_clock.loc[OPENING_BAR_LABEL] if OPENING_BAR_LABEL in by_clock.index else None
        cutoff = by_clock.loc[LATEST_ALLOWED_BAR_LABEL] if LATEST_ALLOWED_BAR_LABEL in by_clock.index else None
        if cutoff is None and not group.empty:
            cutoff = group.iloc[-1]

        opening_price = float(opening["open"]) if opening is not None and pd.notna(opening["open"]) else np.nan
        cutoff_close = float(cutoff["close"]) if cutoff is not None and pd.notna(cutoff["close"]) else np.nan
        previous_match = prior[(prior["ticker"] == ticker) & (prior["date"] == session_date)]
        previous_close = (
            float(previous_match.iloc[0]["previous_close"])
            if not previous_match.empty and pd.notna(previous_match.iloc[0]["previous_close"])
            else np.nan
        )

        closes = pd.to_numeric(group["close"], errors="coerce").dropna()
        close_returns = closes.pct_change().dropna()
        realized_vol = float(math.sqrt(float((close_returns ** 2).sum()))) if not close_returns.empty else 0.0

        close_0935 = (
            float(by_clock.loc["09:35", "close"])
            if "09:35" in by_clock.index and pd.notna(by_clock.loc["09:35", "close"])
            else np.nan
        )
        close_0940 = (
            float(by_clock.loc["09:40", "close"])
            if "09:40" in by_clock.index and pd.notna(by_clock.loc["09:40", "close"])
            else np.nan
        )

        max_label_timestamp = group["datetime"].max()
        rows.append(
            {
                "ticker": ticker,
                "date": session_date,
                "bar_count": int(group["clock"].nunique()),
                "has_exact_opening_bar": bool(OPENING_BAR_LABEL in by_clock.index),
                "has_exact_cutoff_bar": bool(LATEST_ALLOWED_BAR_LABEL in by_clock.index),
                "opening_price": opening_price,
                "cutoff_close": cutoff_close,
                "previous_close": previous_close,
                "gap": opening_price / previous_close - 1.0 if opening_price > 0 and previous_close > 0 else np.nan,
                "return_from_open": cutoff_close / opening_price - 1.0 if cutoff_close > 0 and opening_price > 0 else np.nan,
                "above_previous_close_at_cutoff": cutoff_close > previous_close if cutoff_close > 0 and previous_close > 0 else np.nan,
                "opening_range_pct": (
                    float(group["high"].max()) - float(group["low"].min())
                ) / opening_price if opening_price > 0 else np.nan,
                "early_realized_volatility": realized_vol,
                "return_from_open_0935": close_0935 / opening_price - 1.0 if close_0935 > 0 and opening_price > 0 else np.nan,
                "return_from_open_0940": close_0940 / opening_price - 1.0 if close_0940 > 0 and opening_price > 0 else np.nan,
                "max_source_timestamp": max_label_timestamp,
                "max_source_information_time": max_label_timestamp + pd.Timedelta(minutes=BAR_INTERVAL_MINUTES),
            }
        )

    return pd.DataFrame(rows)


def _build_v1_diagnostics(v1_daily: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "date",
        "v1_valid_candidates",
        "v1_triggered_candidates",
        "v1_completed_trades",
        "v1_realized_pnl_sek",
        "v1_account_return",
        "v1_diagnostic_available",
    ]
    if v1_daily is None or v1_daily.empty or "date" not in v1_daily.columns:
        return pd.DataFrame(columns=columns)

    frame = v1_daily.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    rename = {
        "valid_candidates": "v1_valid_candidates",
        "triggered_candidates": "v1_triggered_candidates",
        "completed_trades": "v1_completed_trades",
        "total_pnl_sek": "v1_realized_pnl_sek",
        "total_account_return": "v1_account_return",
    }
    frame = frame.rename(columns=rename)
    for column in columns[1:-1]:
        if column not in frame.columns:
            frame[column] = np.nan
    frame["v1_diagnostic_available"] = True
    return frame[columns].dropna(subset=["date"]).drop_duplicates("date", keep="last")


def _aggregate_early_features(
    early_ticker: pd.DataFrame,
    all_dates: list[object],
    market_daily: pd.DataFrame,
) -> pd.DataFrame:
    universe_count = len(GAP_RECOVERY_TICKERS)
    market_lookup = market_daily.set_index("date") if not market_daily.empty else pd.DataFrame()
    rows: list[dict[str, object]] = []

    for index, session_date in enumerate(all_dates):
        day = early_ticker[early_ticker["date"] == session_date].copy()
        valid = day.dropna(subset=["gap", "return_from_open"])
        prior_history = market_daily[market_daily["date"] < session_date].copy() if not market_daily.empty else pd.DataFrame()
        previous_row = prior_history.iloc[-1] if not prior_history.empty else None

        return_0935 = pd.to_numeric(day.get("return_from_open_0935", pd.Series(dtype=float)), errors="coerce")
        return_0940 = pd.to_numeric(day.get("return_from_open_0940", pd.Series(dtype=float)), errors="coerce")
        breadth_0935 = float((return_0935.dropna() > 0).mean()) if not return_0935.dropna().empty else np.nan
        breadth_0940 = float((return_0940.dropna() > 0).mean()) if not return_0940.dropna().empty else np.nan
        median_0935 = float(return_0935.dropna().median()) if not return_0935.dropna().empty else np.nan
        median_0940 = float(return_0940.dropna().median()) if not return_0940.dropna().empty else np.nan

        prior_returns = prior_history["equal_weight_return"].dropna().tolist() if not prior_history.empty else []
        prior_2 = prior_returns[-2:] if len(prior_returns) >= 2 else []
        prior_5 = prior_returns[-5:] if len(prior_returns) >= 5 else []
        prior_10 = prior_returns[-10:] if len(prior_returns) >= 10 else []

        expected_total = universe_count * len(EARLY_EXPECTED_LABELS)
        observed_total = int(day["bar_count"].sum()) if not day.empty else 0
        max_source = day["max_source_timestamp"].max() if not day.empty else pd.NaT
        max_info = day["max_source_information_time"].max() if not day.empty else pd.NaT

        row = {
            "feature_set_id": FEATURE_SET_ID,
            "research_status": RESEARCH_STATUS,
            "date": session_date,
            "decision_time": DECISION_TIME,
            "bar_timestamp_convention": "START_LABELLED_5_MINUTE_BARS",
            "latest_allowed_bar_label": LATEST_ALLOWED_BAR_LABEL,
            "universe_ticker_count": universe_count,
            "observed_ticker_count": int(day["ticker"].nunique()) if not day.empty else 0,
            "prior_close_ticker_count": int(day["previous_close"].notna().sum()) if not day.empty else 0,
            "opening_ticker_count": int(day["has_exact_opening_bar"].sum()) if not day.empty else 0,
            "strict_cutoff_ticker_count": int(day["has_exact_cutoff_bar"].sum()) if not day.empty else 0,
            "valid_cross_section_ticker_count": int(valid["ticker"].nunique()),
            "expected_early_bar_count_total": expected_total,
            "observed_early_bar_count_total": observed_total,
            "early_bar_coverage_rate": observed_total / expected_total if expected_total else np.nan,
            "max_early_source_timestamp": _as_iso_timestamp(max_source),
            "max_early_source_information_time": _as_iso_timestamp(max_info),
            "previous_session_date": str(previous_row["date"]) if previous_row is not None else "",
            "previous_session_max_source_timestamp": _as_iso_timestamp(previous_row["max_source_timestamp"]) if previous_row is not None else "",
            "previous_session_complete": bool(previous_row["session_complete"]) if previous_row is not None else False,
            "gap_up_breadth": float((valid["gap"] > 0).mean()) if not valid.empty else np.nan,
            "gap_down_breadth": float((valid["gap"] < 0).mean()) if not valid.empty else np.nan,
            "flat_gap_breadth": float((valid["gap"] == 0).mean()) if not valid.empty else np.nan,
            "mean_gap": _safe_mean(valid["gap"]),
            "median_gap": _safe_median(valid["gap"]),
            "gap_std": _safe_std(valid["gap"]),
            "gap_q25": _safe_quantile(valid["gap"], 0.25),
            "gap_q75": _safe_quantile(valid["gap"], 0.75),
            "minimum_gap": float(valid["gap"].min()) if not valid.empty else np.nan,
            "maximum_gap": float(valid["gap"].max()) if not valid.empty else np.nan,
            "breadth_above_open_at_cutoff": float((valid["return_from_open"] > 0).mean()) if not valid.empty else np.nan,
            "breadth_below_open_at_cutoff": float((valid["return_from_open"] < 0).mean()) if not valid.empty else np.nan,
            "breadth_above_previous_close_at_cutoff": _safe_mean(valid["above_previous_close_at_cutoff"].astype(float)) if not valid.empty else np.nan,
            "mean_return_from_open": _safe_mean(valid["return_from_open"]),
            "median_return_from_open": _safe_median(valid["return_from_open"]),
            "return_from_open_std": _safe_std(valid["return_from_open"]),
            "return_from_open_q25": _safe_quantile(valid["return_from_open"], 0.25),
            "return_from_open_q75": _safe_quantile(valid["return_from_open"], 0.75),
            "minimum_return_from_open": float(valid["return_from_open"].min()) if not valid.empty else np.nan,
            "maximum_return_from_open": float(valid["return_from_open"].max()) if not valid.empty else np.nan,
            "cross_sectional_return_dispersion": _safe_std(valid["return_from_open"]),
            "mean_opening_range_pct": _safe_mean(valid["opening_range_pct"]),
            "median_opening_range_pct": _safe_median(valid["opening_range_pct"]),
            "opening_range_dispersion_pct": _safe_std(valid["opening_range_pct"]),
            "mean_early_realized_volatility": _safe_mean(valid["early_realized_volatility"]),
            "median_early_realized_volatility": _safe_median(valid["early_realized_volatility"]),
            "breadth_above_open_at_0935": breadth_0935,
            "breadth_above_open_at_0940": breadth_0940,
            "breadth_acceleration_0935_to_0940": breadth_0940 - breadth_0935 if pd.notna(breadth_0935) and pd.notna(breadth_0940) else np.nan,
            "median_return_from_open_at_0935": median_0935,
            "median_return_from_open_at_0940": median_0940,
            "median_return_acceleration_0935_to_0940": median_0940 - median_0935 if pd.notna(median_0935) and pd.notna(median_0940) else np.nan,
            "previous_session_equal_weight_return": float(previous_row["equal_weight_return"]) if previous_row is not None and pd.notna(previous_row["equal_weight_return"]) else np.nan,
            "previous_session_median_return": float(previous_row["median_return"]) if previous_row is not None and pd.notna(previous_row["median_return"]) else np.nan,
            "previous_session_positive_breadth": float(previous_row["positive_breadth"]) if previous_row is not None and pd.notna(previous_row["positive_breadth"]) else np.nan,
            "previous_session_cross_sectional_dispersion": float(previous_row["cross_sectional_dispersion"]) if previous_row is not None and pd.notna(previous_row["cross_sectional_dispersion"]) else np.nan,
            "prior_2_session_market_return": _compound_return(prior_2) if len(prior_2) == 2 else np.nan,
            "prior_5_session_market_return": _compound_return(prior_5) if len(prior_5) == 5 else np.nan,
            "prior_10_session_market_return": _compound_return(prior_10) if len(prior_10) == 10 else np.nan,
            "prior_5_session_realized_volatility": float(np.std(prior_5, ddof=0)) if len(prior_5) == 5 else np.nan,
            "prior_10_session_realized_volatility": float(np.std(prior_10, ddof=0)) if len(prior_10) == 10 else np.nan,
            "prior_5_session_max_drawdown": _max_drawdown(prior_5) if len(prior_5) == 5 else np.nan,
            "prior_10_session_max_drawdown": _max_drawdown(prior_10) if len(prior_10) == 10 else np.nan,
            "previous_session_pct_above_5d_sma": float(previous_row["pct_above_5d_sma"]) if previous_row is not None and pd.notna(previous_row["pct_above_5d_sma"]) else np.nan,
            "previous_session_pct_above_10d_sma": float(previous_row["pct_above_10d_sma"]) if previous_row is not None and pd.notna(previous_row["pct_above_10d_sma"]) else np.nan,
            "consecutive_positive_sessions": _consecutive_sign(prior_returns, positive=True),
            "consecutive_negative_sessions": _consecutive_sign(prior_returns, positive=False),
        }
        rows.append(row)

    return pd.DataFrame(rows)


def build_point_in_time_audit(daily_features: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for row in daily_features.to_dict("records"):
        session_date = pd.Timestamp(row["date"])
        decision_timestamp = pd.Timestamp(f"{session_date.date()} {DECISION_TIME}:00")
        early_max = pd.to_datetime(row.get("max_early_source_timestamp"), errors="coerce")
        early_info = pd.to_datetime(row.get("max_early_source_information_time"), errors="coerce")
        early_pass = bool(pd.notna(early_info) and early_info <= decision_timestamp)
        rows.append(
            {
                "feature_set_id": FEATURE_SET_ID,
                "date": row["date"],
                "audit_group": "EARLY_SESSION_STRICT",
                "classifier_eligible": True,
                "source_scope": f"Five-minute bars labelled {OPENING_BAR_LABEL}-{LATEST_ALLOWED_BAR_LABEL}",
                "max_source_timestamp": _as_iso_timestamp(early_max),
                "max_source_information_time": _as_iso_timestamp(early_info),
                "allowed_information_time": _as_iso_timestamp(decision_timestamp),
                "point_in_time_pass": early_pass,
                "audit_status": "PASS" if early_pass else "FAIL_MISSING_OR_POST_CUTOFF_DATA",
                "rows_or_sessions_used": int(row.get("observed_early_bar_count_total", 0)),
                "notes": "Start-labelled bars are considered known five minutes after their label; the 09:45-labelled bar is excluded.",
            }
        )

        previous_max = pd.to_datetime(row.get("previous_session_max_source_timestamp"), errors="coerce")
        previous_available = pd.notna(previous_max)
        previous_pass = bool((not previous_available) or previous_max < decision_timestamp)
        previous_status = (
            "PASS"
            if previous_available and previous_max < decision_timestamp
            else "NOT_APPLICABLE_NO_PRIOR_SESSION"
            if not previous_available
            else "FAIL_FUTURE_SOURCE"
        )
        rows.append(
            {
                "feature_set_id": FEATURE_SET_ID,
                "date": row["date"],
                "audit_group": "PREVIOUS_AND_MULTI_SESSION_HISTORY",
                "classifier_eligible": True,
                "source_scope": "Only sessions strictly earlier than the current session",
                "max_source_timestamp": _as_iso_timestamp(previous_max),
                "max_source_information_time": _as_iso_timestamp(previous_max),
                "allowed_information_time": _as_iso_timestamp(decision_timestamp),
                "point_in_time_pass": previous_pass,
                "audit_status": previous_status,
                "rows_or_sessions_used": 10 if previous_available else 0,
                "notes": (
                    "Rolling history is sliced with date < current date before any feature is calculated. "
                    "The first observed session has no earlier source and is completeness-limited, not a point-in-time failure."
                ),
            }
        )

        rows.append(
            {
                "feature_set_id": FEATURE_SET_ID,
                "date": row["date"],
                "audit_group": "V1_OUTCOME_DIAGNOSTIC",
                "classifier_eligible": False,
                "source_scope": "Gap Recovery V1 daily outcome generated after the session",
                "max_source_timestamp": "",
                "max_source_information_time": "",
                "allowed_information_time": _as_iso_timestamp(decision_timestamp),
                "point_in_time_pass": True,
                "audit_status": "DIAGNOSTIC_ONLY_EXCLUDED_FROM_CLASSIFIER",
                "rows_or_sessions_used": 1 if bool(row.get("v1_diagnostic_available", False)) else 0,
                "notes": "Outcome columns may be used to evaluate regimes, never to classify the same day.",
            }
        )

    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def _build_definitions() -> pd.DataFrame:
    descriptions: dict[str, tuple[str, str, str]] = {
        "gap_up_breadth": ("OPENING_GAP", "Share of valid universe stocks opening above previous close.", "mean(open_09:30 > previous_close)"),
        "gap_down_breadth": ("OPENING_GAP", "Share of valid universe stocks opening below previous close.", "mean(open_09:30 < previous_close)"),
        "mean_gap": ("OPENING_GAP", "Cross-sectional mean opening gap.", "mean(open_09:30 / previous_close - 1)"),
        "median_gap": ("OPENING_GAP", "Cross-sectional median opening gap.", "median(open_09:30 / previous_close - 1)"),
        "gap_std": ("OPENING_GAP", "Cross-sectional standard deviation of opening gaps.", "population standard deviation of opening gaps"),
        "breadth_above_open_at_cutoff": ("EARLY_BREADTH", "Share of valid stocks above their 09:30 open at the strict cutoff.", "mean(close_09:40 > open_09:30)"),
        "breadth_above_previous_close_at_cutoff": ("EARLY_BREADTH", "Share above previous close at the strict cutoff.", "mean(close_09:40 > previous_close)"),
        "mean_return_from_open": ("EARLY_DIRECTION", "Mean return from the 09:30 open to the strict cutoff.", "mean(close_09:40 / open_09:30 - 1)"),
        "median_return_from_open": ("EARLY_DIRECTION", "Median return from the 09:30 open to the strict cutoff.", "median(close_09:40 / open_09:30 - 1)"),
        "cross_sectional_return_dispersion": ("EARLY_DISPERSION", "Dispersion of returns from open across the universe.", "population standard deviation of return_from_open"),
        "median_opening_range_pct": ("EARLY_VOLATILITY", "Median high-low range across bars known by the decision time.", "median((max_high_09:30_09:40 - min_low_09:30_09:40) / open_09:30)"),
        "median_early_realized_volatility": ("EARLY_VOLATILITY", "Median root-sum-square of consecutive early five-minute close returns.", "median(sqrt(sum(five_minute_return^2)))"),
        "breadth_acceleration_0935_to_0940": ("EARLY_DYNAMICS", "Change in breadth above open between the two last eligible bar labels.", "breadth_09:40 - breadth_09:35"),
        "median_return_acceleration_0935_to_0940": ("EARLY_DYNAMICS", "Change in median return from open between eligible checkpoints.", "median_return_09:40 - median_return_09:35"),
        "previous_session_equal_weight_return": ("PREVIOUS_SESSION", "Mean universe return during the immediately previous session.", "mean(previous_session_close / prior_close - 1)"),
        "previous_session_positive_breadth": ("PREVIOUS_SESSION", "Share of universe stocks with positive previous-session returns.", "mean(previous_session_return > 0)"),
        "previous_session_cross_sectional_dispersion": ("PREVIOUS_SESSION", "Cross-sectional dispersion during the previous session.", "population standard deviation of previous-session stock returns"),
        "prior_2_session_market_return": ("MULTI_SESSION_TREND", "Compounded equal-weight market return over the preceding two sessions.", "product(1 + equal_weight_return[-2:]) - 1"),
        "prior_5_session_market_return": ("MULTI_SESSION_TREND", "Compounded equal-weight market return over the preceding five sessions.", "product(1 + equal_weight_return[-5:]) - 1"),
        "prior_10_session_market_return": ("MULTI_SESSION_TREND", "Compounded equal-weight market return over the preceding ten sessions.", "product(1 + equal_weight_return[-10:]) - 1"),
        "prior_5_session_realized_volatility": ("MULTI_SESSION_VOLATILITY", "Population standard deviation of equal-weight returns over five previous sessions.", "std(equal_weight_return[-5:], ddof=0)"),
        "prior_10_session_realized_volatility": ("MULTI_SESSION_VOLATILITY", "Population standard deviation of equal-weight returns over ten previous sessions.", "std(equal_weight_return[-10:], ddof=0)"),
        "prior_5_session_max_drawdown": ("MULTI_SESSION_RISK", "Maximum drawdown of the equal-weight market path over five previous sessions.", "min(cumulative_wealth / running_peak - 1)"),
        "prior_10_session_max_drawdown": ("MULTI_SESSION_RISK", "Maximum drawdown of the equal-weight market path over ten previous sessions.", "min(cumulative_wealth / running_peak - 1)"),
        "previous_session_pct_above_5d_sma": ("MARKET_INTERNALS", "Share of stocks above their five-session moving average at the previous close.", "mean(previous_close > rolling_mean_5)"),
        "previous_session_pct_above_10d_sma": ("MARKET_INTERNALS", "Share above ten-session moving average at the previous close.", "mean(previous_close > rolling_mean_10)"),
        "consecutive_positive_sessions": ("MULTI_SESSION_STATE", "Number of consecutive positive equal-weight sessions ending yesterday.", "count consecutive equal_weight_return > 0 backwards from prior session"),
        "consecutive_negative_sessions": ("MULTI_SESSION_STATE", "Number of consecutive negative equal-weight sessions ending yesterday.", "count consecutive equal_weight_return < 0 backwards from prior session"),
    }

    rows: list[dict[str, object]] = []
    for feature_name in MODEL_FEATURE_COLUMNS:
        group, description, formula = descriptions.get(
            feature_name,
            ("INTERNAL_MARKET", feature_name.replace("_", " ").capitalize(), "Derived from eligible internal market data"),
        )
        source_availability = "BY_09:45" if group.startswith("EARLY") or group == "OPENING_GAP" else "BEFORE_CURRENT_SESSION"
        point_rule = (
            "Only 09:30, 09:35, and 09:40 start-labelled bars; their information time is no later than 09:45."
            if source_availability == "BY_09:45"
            else "Only observations with session date strictly earlier than the current date."
        )
        rows.append(
            {
                "feature_name": feature_name,
                "feature_group": group,
                "description": description,
                "formula_or_method": formula,
                "source": "Local Yahoo five-minute intraday database",
                "source_availability": source_availability,
                "decision_time_eligible": True,
                "point_in_time_rule": point_rule,
                "current_status": "AVAILABLE_NOW",
                "included_in_initial_classifier": True,
                "data_type": "numeric",
            }
        )

    diagnostic_features = [
        "v1_valid_candidates",
        "v1_triggered_candidates",
        "v1_completed_trades",
        "v1_realized_pnl_sek",
        "v1_account_return",
    ]
    for feature_name in diagnostic_features:
        rows.append(
            {
                "feature_name": feature_name,
                "feature_group": "V1_OUTCOME_DIAGNOSTIC",
                "description": "Gap Recovery V1 outcome joined only to evaluate future regime definitions.",
                "formula_or_method": "Read from the same-run Gap Recovery V1 daily output.",
                "source": "regime_gap_recovery_daily.csv",
                "source_availability": "AFTER_SESSION",
                "decision_time_eligible": False,
                "point_in_time_rule": "Never use this same-day outcome as a classifier input.",
                "current_status": "DIAGNOSTIC_ONLY",
                "included_in_initial_classifier": False,
                "data_type": "numeric",
            }
        )

    for name, group, description, method, source in PLANNED_EXTERNAL_FEATURES:
        rows.append(
            {
                "feature_name": name,
                "feature_group": group,
                "description": description,
                "formula_or_method": method,
                "source": source,
                "source_availability": "POINT_IN_TIME_SOURCE_REQUIRED",
                "decision_time_eligible": True,
                "point_in_time_rule": "Value and publication timestamp must both be no later than the daily decision time.",
                "current_status": "AFTER_DATA_EXPANSION",
                "included_in_initial_classifier": False,
                "data_type": "numeric_or_boolean",
            }
        )

    return pd.DataFrame(rows, columns=DEFINITION_COLUMNS)


def _apply_readiness_and_completeness(
    daily: pd.DataFrame,
    audit: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if daily.empty:
        return daily, pd.DataFrame(columns=COMPLETENESS_COLUMNS)

    classifier_audit = audit[audit["classifier_eligible"] == True].copy()  # noqa: E712
    audit_by_date = classifier_audit.groupby("date")["point_in_time_pass"].all().to_dict()

    completeness_rows: list[dict[str, object]] = []
    updated_rows: list[dict[str, object]] = []
    for record in daily.to_dict("records"):
        point_safe = bool(audit_by_date.get(record["date"], False))
        coverage = float(record.get("early_bar_coverage_rate", 0.0) or 0.0)
        valid_count = int(record.get("valid_cross_section_ticker_count", 0) or 0)
        opening_count = int(record.get("opening_ticker_count", 0) or 0)
        cutoff_count = int(record.get("strict_cutoff_ticker_count", 0) or 0)
        prior_count = int(record.get("prior_close_ticker_count", 0) or 0)

        minimum_values_present = all(pd.notna(record.get(column)) for column in MINIMUM_REQUIRED_FEATURE_COLUMNS)
        minimum_ready = bool(
            point_safe
            and coverage >= 0.75
            and valid_count >= MIN_CROSS_SECTION_TICKERS
            and opening_count >= MIN_CROSS_SECTION_TICKERS
            and cutoff_count >= MIN_CROSS_SECTION_TICKERS
            and prior_count >= MIN_CROSS_SECTION_TICKERS
            and minimum_values_present
        )
        full_history_present = all(pd.notna(record.get(column)) for column in [
            "prior_10_session_market_return",
            "prior_10_session_realized_volatility",
            "prior_10_session_max_drawdown",
            "previous_session_pct_above_10d_sma",
        ])
        full_ready = bool(
            minimum_ready
            and coverage >= FULL_COVERAGE_THRESHOLD
            and opening_count == len(GAP_RECOVERY_TICKERS)
            and cutoff_count == len(GAP_RECOVERY_TICKERS)
            and prior_count == len(GAP_RECOVERY_TICKERS)
            and full_history_present
        )

        available = sum(pd.notna(record.get(column)) for column in MODEL_FEATURE_COLUMNS)
        total = len(MODEL_FEATURE_COLUMNS)
        missing = total - available

        if not point_safe:
            status = "POINT_IN_TIME_AUDIT_FAILED"
            reason = "At least one classifier-eligible feature group failed its timestamp audit."
        elif valid_count < MIN_CROSS_SECTION_TICKERS:
            status = "INSUFFICIENT_CROSS_SECTION"
            reason = f"Only {valid_count} valid tickers; minimum is {MIN_CROSS_SECTION_TICKERS}."
        elif not minimum_ready:
            status = "PARTIAL"
            reason = "Early or previous-session inputs are incomplete."
        elif not full_ready:
            status = "MINIMUM_READY_HISTORY_BUILDING"
            reason = "Point-in-time safe and usable, but ten-session history or full-universe coverage is incomplete."
        else:
            status = "FULL_READY"
            reason = ""

        record["minimum_regime_feature_ready"] = minimum_ready
        record["full_regime_feature_ready"] = full_ready
        record["feature_row_status"] = status
        record["point_in_time_safe"] = point_safe
        updated_rows.append(record)

        early_status = "COMPLETE" if coverage >= FULL_COVERAGE_THRESHOLD and cutoff_count == len(GAP_RECOVERY_TICKERS) else "PARTIAL"
        previous_status = "AVAILABLE_COMPLETE" if bool(record.get("previous_session_complete")) else ("AVAILABLE_PARTIAL" if record.get("previous_session_date") else "UNAVAILABLE")
        completeness_rows.append(
            {
                "feature_set_id": FEATURE_SET_ID,
                "date": record["date"],
                "early_session_status": early_status,
                "previous_session_status": previous_status,
                "history_2_session_status": "AVAILABLE" if pd.notna(record.get("prior_2_session_market_return")) else "BUILDING",
                "history_5_session_status": "AVAILABLE" if pd.notna(record.get("prior_5_session_market_return")) else "BUILDING",
                "history_10_session_status": "AVAILABLE" if pd.notna(record.get("prior_10_session_market_return")) else "BUILDING",
                "v1_diagnostic_status": "AVAILABLE_DIAGNOSTIC_ONLY" if bool(record.get("v1_diagnostic_available")) else "UNAVAILABLE",
                "available_model_feature_count": available,
                "total_model_feature_count": total,
                "missing_model_feature_count": missing,
                "feature_completeness_rate": available / total if total else np.nan,
                "minimum_regime_feature_ready": minimum_ready,
                "full_regime_feature_ready": full_ready,
                "feature_row_status": status,
                "excluded_or_partial_reason": reason,
            }
        )

    updated = pd.DataFrame(updated_rows)
    for column in DAILY_FEATURE_COLUMNS:
        if column not in updated.columns:
            updated[column] = np.nan
    updated = updated[DAILY_FEATURE_COLUMNS]
    completeness = pd.DataFrame(completeness_rows, columns=COMPLETENESS_COLUMNS)
    return updated, completeness


def build_feature_foundation(
    prices: pd.DataFrame,
    v1_daily: pd.DataFrame | None = None,
) -> FeatureFoundationResult:
    prepared = _prepare_prices(prices)
    definitions = _build_definitions()

    if prepared.empty:
        empty_daily = pd.DataFrame(columns=DAILY_FEATURE_COLUMNS)
        empty_audit = pd.DataFrame(columns=AUDIT_COLUMNS)
        empty_completeness = pd.DataFrame(columns=COMPLETENESS_COLUMNS)
        summary = pd.DataFrame(
            [{
                "feature_set_id": FEATURE_SET_ID,
                "research_status": RESEARCH_STATUS,
                "decision_time": DECISION_TIME,
                "bar_timestamp_convention": "START_LABELLED_5_MINUTE_BARS",
                "latest_allowed_bar_label": LATEST_ALLOWED_BAR_LABEL,
                "observed_sessions": 0,
                "minimum_ready_sessions": 0,
                "full_ready_sessions": 0,
                "partial_sessions": 0,
                "classifier_audit_rows": 0,
                "classifier_audit_pass_rows": 0,
                "classifier_audit_fail_rows": 0,
                "point_in_time_leakage_rows": 0,
                "available_now_feature_count": int((definitions["current_status"] == "AVAILABLE_NOW").sum()),
                "planned_external_feature_count": int((definitions["current_status"] == "AFTER_DATA_EXPANSION").sum()),
                "diagnostic_only_feature_count": int((definitions["current_status"] == "DIAGNOSTIC_ONLY").sum()),
                "v1_diagnostic_joined_sessions": 0,
                "first_session_date": "",
                "last_session_date": "",
                "classification": "NO_INTRADAY_DATA",
            }],
            columns=SUMMARY_COLUMNS,
        )
        return FeatureFoundationResult(summary, empty_daily, definitions, empty_completeness, empty_audit)

    daily_ticker, market_daily = _build_daily_market_history(prepared)
    early_ticker = _build_early_ticker_features(prepared, daily_ticker)
    all_dates = sorted(prepared["date"].dropna().unique().tolist())
    daily = _aggregate_early_features(early_ticker, all_dates, market_daily)

    diagnostics = _build_v1_diagnostics(v1_daily)
    daily = daily.merge(diagnostics, on="date", how="left")
    daily["v1_diagnostic_available"] = daily["v1_diagnostic_available"].eq(True)
    daily["v1_diagnostic_after_session_only"] = True

    # Build the audit before readiness. V1 outcomes remain intentionally diagnostic-only.
    audit = build_point_in_time_audit(daily)
    daily, completeness = _apply_readiness_and_completeness(daily, audit)

    classifier_audit = audit[audit["classifier_eligible"] == True].copy()  # noqa: E712
    audit_pass = int(classifier_audit["point_in_time_pass"].sum()) if not classifier_audit.empty else 0
    audit_fail = int((~classifier_audit["point_in_time_pass"].astype(bool)).sum()) if not classifier_audit.empty else 0
    leakage_rows = int(
        (
            classifier_audit["point_in_time_pass"].eq(False)
            & classifier_audit["max_source_information_time"].astype(str).ne("")
        ).sum()
    ) if not classifier_audit.empty else 0

    classification = (
        "POINT_IN_TIME_FEATURE_FOUNDATION_READY"
        if leakage_rows == 0 and int(daily["minimum_regime_feature_ready"].sum()) > 0
        else "FEATURE_FOUNDATION_REQUIRES_REVIEW"
    )
    summary = pd.DataFrame(
        [{
            "feature_set_id": FEATURE_SET_ID,
            "research_status": RESEARCH_STATUS,
            "decision_time": DECISION_TIME,
            "bar_timestamp_convention": "START_LABELLED_5_MINUTE_BARS",
            "latest_allowed_bar_label": LATEST_ALLOWED_BAR_LABEL,
            "observed_sessions": len(daily),
            "minimum_ready_sessions": int(daily["minimum_regime_feature_ready"].sum()),
            "full_ready_sessions": int(daily["full_regime_feature_ready"].sum()),
            "partial_sessions": int((~daily["minimum_regime_feature_ready"].astype(bool)).sum()),
            "classifier_audit_rows": len(classifier_audit),
            "classifier_audit_pass_rows": audit_pass,
            "classifier_audit_fail_rows": audit_fail,
            "point_in_time_leakage_rows": leakage_rows,
            "available_now_feature_count": int((definitions["current_status"] == "AVAILABLE_NOW").sum()),
            "planned_external_feature_count": int((definitions["current_status"] == "AFTER_DATA_EXPANSION").sum()),
            "diagnostic_only_feature_count": int((definitions["current_status"] == "DIAGNOSTIC_ONLY").sum()),
            "v1_diagnostic_joined_sessions": int(daily["v1_diagnostic_available"].sum()),
            "first_session_date": str(daily["date"].min()) if not daily.empty else "",
            "last_session_date": str(daily["date"].max()) if not daily.empty else "",
            "classification": classification,
        }],
        columns=SUMMARY_COLUMNS,
    )

    return FeatureFoundationResult(summary, daily, definitions, completeness, audit)


def _read_v1_daily() -> pd.DataFrame:
    if not V1_DAILY_FILE.exists():
        return pd.DataFrame()
    return pd.read_csv(V1_DAILY_FILE)


def main() -> None:
    print("\n=== STEP 7 POINT-IN-TIME REGIME FEATURE FOUNDATION ===")
    print(f"Feature set       : {FEATURE_SET_ID}")
    print(f"Research status   : {RESEARCH_STATUS}")
    print(f"Decision time     : {DECISION_TIME}")
    print("Bar convention    : START_LABELLED_5_MINUTE_BARS")
    print(f"Latest used label : {LATEST_ALLOWED_BAR_LABEL}")
    print("The 09:45-labelled bar is excluded because it is not complete at 09:45.")
    print("V1 outcomes are joined for diagnostics only and cannot enter the classifier.")

    prices = load_intraday_prices(INTRADAY_DB)
    result = build_feature_foundation(prices, _read_v1_daily())

    export_csv_for_power_bi(result.summary, SUMMARY_FILE)
    export_csv_for_power_bi(result.daily_features, DAILY_FEATURES_FILE)
    export_csv_for_power_bi(result.definitions, DEFINITIONS_FILE)
    export_csv_for_power_bi(result.completeness, COMPLETENESS_FILE)
    export_csv_for_power_bi(result.audit, AUDIT_FILE)

    for path, frame in [
        (SUMMARY_FILE, result.summary),
        (DAILY_FEATURES_FILE, result.daily_features),
        (DEFINITIONS_FILE, result.definitions),
        (COMPLETENESS_FILE, result.completeness),
        (AUDIT_FILE, result.audit),
    ]:
        print(f"Saved {path.name}: {len(frame)} rows")

    summary = result.summary.iloc[0]
    print("\n=== STEP 7 FEATURE FOUNDATION RESULT ===")
    print(f"Observed sessions             : {int(summary['observed_sessions'])}")
    print(f"Minimum-ready sessions        : {int(summary['minimum_ready_sessions'])}")
    print(f"Full-ready sessions           : {int(summary['full_ready_sessions'])}")
    print(f"Partial sessions              : {int(summary['partial_sessions'])}")
    print(f"Classifier audit pass         : {int(summary['classifier_audit_pass_rows'])}/{int(summary['classifier_audit_rows'])}")
    print(f"Point-in-time leakage rows     : {int(summary['point_in_time_leakage_rows'])}")
    print(f"Available internal features   : {int(summary['available_now_feature_count'])}")
    print(f"Planned macro/external fields : {int(summary['planned_external_feature_count'])}")
    print(f"V1 diagnostic joined sessions : {int(summary['v1_diagnostic_joined_sessions'])}")
    print(f"Classification                : {summary['classification']}")
    print("Step 7 feature foundation export complete.")


if __name__ == "__main__":
    main()
