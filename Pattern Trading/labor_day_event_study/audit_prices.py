from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import exchange_calendars as xcals
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PRICES_PATH = (
    PROJECT_ROOT / "data" / "processed" / "daily_prices.csv"
)
DEFAULT_UNIVERSE_PATH = (
    PROJECT_ROOT / "config" / "labor_day_universe.csv"
)
DEFAULT_YEAR_PANEL_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_universe_by_year.csv"
)
DEFAULT_PRICE_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests" / "daily_prices_manifest.json"
)

DEFAULT_TICKER_COVERAGE_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "price_coverage_by_ticker.csv"
)
DEFAULT_EVENT_COVERAGE_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "price_coverage_by_event_year.csv"
)
DEFAULT_ISSUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "price_quality_issues.csv"
)
DEFAULT_AUDIT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "price_quality_audit.json"
)

STUDY_START_YEAR = 1998
DISCOVERY_END_YEAR = 2014
VALIDATION_START_YEAR = 2015
VALIDATION_END_YEAR = 2025
FORWARD_YEAR = 2026

EVENT_PRE_SESSIONS = 20
EVENT_POST_SESSIONS = 20
ESTIMATION_REQUIRED_SESSIONS = 126
EXTREME_ADJUSTED_RETURN_THRESHOLD = 0.50
UNADJUSTED_JUMP_THRESHOLD = 0.50
ADJUSTMENT_FACTOR_JUMP_THRESHOLD = 0.20

PRICE_COLUMNS = [
    "ticker",
    "provider_symbol",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "dividend",
    "split",
    "retrieved_utc",
    "source",
    "source_file",
    "request_hash",
    "raw_sha256",
]

UNIVERSE_REQUIRED_COLUMNS = [
    "ticker",
    "provider_symbol",
    "instrument_name",
    "hypothesis",
    "subindustry",
    "role",
    "analysis_tier",
    "security_type",
    "exchange",
    "currency",
    "primary_benchmark",
    "fallback_benchmark",
    "analysis_start_year",
    "analysis_end_year",
    "discovery_eligible",
    "validation_eligible",
    "forward_eligible",
    "continuity_status",
    "predecessor_symbols",
    "source_url",
    "notes",
]

YEAR_PANEL_REQUIRED_COLUMNS = [
    "event_year",
    "sample",
    "ticker",
    "provider_symbol",
    "instrument_name",
    "hypothesis",
    "subindustry",
    "role",
    "analysis_tier",
    "resolved_benchmark",
    "benchmark_resolution",
    "eligible_group_members",
    "equal_weight",
    "continuity_status",
]

ISSUE_COLUMNS = [
    "severity",
    "issue_code",
    "ticker",
    "event_year",
    "session_date",
    "count",
    "detail",
]

TICKER_COVERAGE_COLUMNS = [
    "ticker",
    "provider_symbol",
    "instrument_name",
    "hypothesis",
    "role",
    "analysis_tier",
    "continuity_status",
    "policy_start_year",
    "policy_end_year",
    "observed_first_session",
    "observed_last_session",
    "observed_rows",
    "expected_xnys_sessions",
    "missing_xnys_sessions",
    "unexpected_non_xnys_sessions",
    "coverage_ratio",
    "duplicate_sessions",
    "invalid_numeric_rows",
    "nonpositive_price_rows",
    "negative_volume_rows",
    "impossible_ohlc_rows",
    "invalid_adjustment_factor_rows",
    "extreme_adjusted_return_rows",
    "unadjusted_jump_without_split_rows",
    "adjustment_factor_jump_without_action_rows",
    "eligible_historical_event_years",
    "complete_historical_event_years",
    "incomplete_historical_event_years",
    "first_event_complete_year",
    "first_estimation_ready_year",
    "recommended_analysis_start_year",
    "ticker_status",
]

EVENT_COVERAGE_COLUMNS = [
    "event_year",
    "sample",
    "ticker",
    "provider_symbol",
    "instrument_name",
    "hypothesis",
    "role",
    "analysis_tier",
    "continuity_status",
    "resolved_benchmark",
    "benchmark_resolution",
    "labor_day_date",
    "required_start_session",
    "required_end_session",
    "expected_event_sessions",
    "ticker_event_sessions",
    "benchmark_event_sessions",
    "common_event_sessions",
    "missing_ticker_event_sessions",
    "missing_benchmark_event_sessions",
    "missing_common_event_sessions",
    "estimation_required_sessions",
    "ticker_estimation_sessions",
    "benchmark_estimation_sessions",
    "common_estimation_sessions",
    "estimation_shortfall_sessions",
    "event_coverage_status",
]

SEVERITY_ORDER = {
    "critical": 0,
    "warning": 1,
    "info": 2,
}


class PriceQualityAuditError(RuntimeError):
    """Raised after outputs are written when critical issues remain."""


@dataclass(frozen=True)
class AuditResult:
    ticker_coverage: pd.DataFrame
    event_coverage: pd.DataFrame
    issues: pd.DataFrame
    manifest: dict[str, object]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_csv(dataframe: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    dataframe.to_csv(temporary, index=False, encoding="utf-8")
    temporary.replace(path)


def atomic_write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def first_monday_in_september(year: int) -> date:
    current = date(year, 9, 1)
    while current.weekday() != 0:
        current += timedelta(days=1)
    return current


def sample_for_year(year: int) -> str:
    if STUDY_START_YEAR <= year <= DISCOVERY_END_YEAR:
        return "discovery"
    if VALIDATION_START_YEAR <= year <= VALIDATION_END_YEAR:
        return "validation"
    if year == FORWARD_YEAR:
        return "forward"
    raise ValueError(f"Year outside frozen study range: {year}")


def _require_columns(
    dataframe: pd.DataFrame,
    required: list[str],
    label: str,
) -> None:
    missing = sorted(set(required).difference(dataframe.columns))
    if missing:
        raise PriceQualityAuditError(
            f"{label} is missing required columns: {missing}"
        )


def load_inputs(
    *,
    prices_path: Path = DEFAULT_PRICES_PATH,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    year_panel_path: Path = DEFAULT_YEAR_PANEL_PATH,
    price_manifest_path: Path = DEFAULT_PRICE_MANIFEST_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    for path in [
        prices_path,
        universe_path,
        year_panel_path,
        price_manifest_path,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    prices = pd.read_csv(
        prices_path,
        dtype=str,
        keep_default_na=False,
    )
    universe = pd.read_csv(
        universe_path,
        dtype=str,
        keep_default_na=False,
    )
    year_panel = pd.read_csv(
        year_panel_path,
        dtype=str,
        keep_default_na=False,
    )
    manifest = json.loads(
        price_manifest_path.read_text(encoding="utf-8")
    )

    _require_columns(prices, PRICE_COLUMNS, "daily_prices.csv")
    _require_columns(
        universe,
        UNIVERSE_REQUIRED_COLUMNS,
        "labor_day_universe.csv",
    )
    _require_columns(
        year_panel,
        YEAR_PANEL_REQUIRED_COLUMNS,
        "labor_day_universe_by_year.csv",
    )

    return prices, universe, year_panel, manifest


def xnys_session_dates(
    start: str | date | pd.Timestamp,
    end: str | date | pd.Timestamp,
) -> pd.DatetimeIndex:
    calendar = xcals.get_calendar("XNYS", start="1990-01-01", end="2030-12-31")
    sessions = calendar.sessions_in_range(
        pd.Timestamp(start),
        pd.Timestamp(end),
    )
    return pd.DatetimeIndex(sessions).normalize()


def build_event_session_grid(
    *,
    start_year: int = STUDY_START_YEAR,
    end_year: int = FORWARD_YEAR,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for year in range(start_year, end_year + 1):
        holiday = first_monday_in_september(year)
        sessions = xnys_session_dates(
            holiday - timedelta(days=60),
            holiday + timedelta(days=60),
        )
        holiday_ts = pd.Timestamp(holiday)

        pre = sessions[sessions < holiday_ts][
            -EVENT_PRE_SESSIONS:
        ]
        post = sessions[sessions > holiday_ts][
            :EVENT_POST_SESSIONS
        ]

        if len(pre) != EVENT_PRE_SESSIONS:
            raise PriceQualityAuditError(
                f"Could not resolve {EVENT_PRE_SESSIONS} pre-event "
                f"sessions for {year}."
            )
        if len(post) != EVENT_POST_SESSIONS:
            raise PriceQualityAuditError(
                f"Could not resolve {EVENT_POST_SESSIONS} post-event "
                f"sessions for {year}."
            )

        for offset, session in zip(
            range(-EVENT_PRE_SESSIONS, 0),
            pre,
            strict=True,
        ):
            rows.append(
                {
                    "event_year": year,
                    "sample": sample_for_year(year),
                    "labor_day_date": holiday.isoformat(),
                    "event_time": offset,
                    "session_date": session.date().isoformat(),
                }
            )

        for offset, session in zip(
            range(1, EVENT_POST_SESSIONS + 1),
            post,
            strict=True,
        ):
            rows.append(
                {
                    "event_year": year,
                    "sample": sample_for_year(year),
                    "labor_day_date": holiday.isoformat(),
                    "event_time": offset,
                    "session_date": session.date().isoformat(),
                }
            )

    grid = pd.DataFrame(rows)
    grid.sort_values(
        ["event_year", "event_time"],
        inplace=True,
    )
    grid.reset_index(drop=True, inplace=True)

    if len(grid) != (
        (end_year - start_year + 1)
        * (EVENT_PRE_SESSIONS + EVENT_POST_SESSIONS)
    ):
        raise PriceQualityAuditError(
            "Event-session grid row count is inconsistent."
        )

    if grid.duplicated(["event_year", "event_time"]).any():
        raise PriceQualityAuditError(
            "Duplicate event-year/event-time rows in grid."
        )

    return grid


def _issue(
    issues: list[dict[str, object]],
    *,
    severity: str,
    code: str,
    ticker: str = "",
    event_year: int | str = "",
    session_date: str = "",
    count: int = 1,
    detail: str,
) -> None:
    issues.append(
        {
            "severity": severity,
            "issue_code": code,
            "ticker": ticker,
            "event_year": event_year,
            "session_date": session_date,
            "count": int(count),
            "detail": detail,
        }
    )


def _date_examples(values: Iterable[str], limit: int = 8) -> str:
    unique = sorted(set(str(value) for value in values))
    shown = unique[:limit]
    suffix = "" if len(unique) <= limit else ", ..."
    return ", ".join(shown) + suffix


def prepare_prices(
    raw_prices: pd.DataFrame,
    universe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, object]], dict[str, dict[str, int]]]:
    issues: list[dict[str, object]] = []
    prices = raw_prices.copy()

    universe_tickers = set(universe["ticker"])
    price_tickers = set(prices["ticker"])

    unknown = sorted(price_tickers.difference(universe_tickers))
    for ticker in unknown:
        _issue(
            issues,
            severity="critical",
            code="unknown_price_ticker",
            ticker=ticker,
            count=int(prices["ticker"].eq(ticker).sum()),
            detail="Ticker appears in daily prices but not in the frozen universe.",
        )

    missing = sorted(universe_tickers.difference(price_tickers))
    for ticker in missing:
        _issue(
            issues,
            severity="critical",
            code="universe_ticker_missing_prices",
            ticker=ticker,
            detail="Frozen universe ticker has no normalized price rows.",
        )

    duplicate_mask = prices.duplicated(
        ["ticker", "session_date"],
        keep=False,
    )
    if duplicate_mask.any():
        for ticker, group in prices.loc[
            duplicate_mask
        ].groupby("ticker"):
            _issue(
                issues,
                severity="critical",
                code="duplicate_ticker_session",
                ticker=str(ticker),
                count=len(group),
                detail=(
                    "Duplicate ticker/session rows: "
                    + _date_examples(group["session_date"])
                ),
            )

    parsed_dates = pd.to_datetime(
        prices["session_date"],
        format="%Y-%m-%d",
        errors="coerce",
    )
    invalid_date_mask = parsed_dates.isna()
    if invalid_date_mask.any():
        for ticker, group in prices.loc[
            invalid_date_mask
        ].groupby("ticker"):
            _issue(
                issues,
                severity="critical",
                code="invalid_session_date",
                ticker=str(ticker),
                count=len(group),
                detail=(
                    "Invalid session dates: "
                    + _date_examples(group["session_date"])
                ),
            )
    prices["_session"] = parsed_dates

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "dividend",
        "split",
    ]
    for column in numeric_columns:
        prices[f"_{column}"] = pd.to_numeric(
            prices[column],
            errors="coerce",
        )

    invalid_numeric_any = prices[
        [f"_{column}" for column in numeric_columns]
    ].isna().any(axis=1)
    if invalid_numeric_any.any():
        for ticker, group in prices.loc[
            invalid_numeric_any
        ].groupby("ticker"):
            _issue(
                issues,
                severity="critical",
                code="invalid_numeric_price_field",
                ticker=str(ticker),
                count=len(group),
                detail=(
                    "Rows contain nonnumeric or missing required numeric fields. "
                    "Examples: "
                    + _date_examples(group["session_date"])
                ),
            )

    positive_columns = [
        "_open",
        "_high",
        "_low",
        "_close",
        "_adjusted_close",
    ]
    nonpositive_mask = prices[positive_columns].le(0).any(axis=1)
    if nonpositive_mask.any():
        for ticker, group in prices.loc[
            nonpositive_mask
        ].groupby("ticker"):
            _issue(
                issues,
                severity="critical",
                code="nonpositive_price",
                ticker=str(ticker),
                count=len(group),
                detail=(
                    "One or more OHLC/adjusted-close values are nonpositive. "
                    "Examples: "
                    + _date_examples(group["session_date"])
                ),
            )

    negative_volume_mask = prices["_volume"].lt(0)
    if negative_volume_mask.any():
        for ticker, group in prices.loc[
            negative_volume_mask
        ].groupby("ticker"):
            _issue(
                issues,
                severity="critical",
                code="negative_volume",
                ticker=str(ticker),
                count=len(group),
                detail=(
                    "Negative volume values. Examples: "
                    + _date_examples(group["session_date"])
                ),
            )

    impossible_ohlc_mask = (
        prices["_high"].lt(prices["_low"])
        | prices["_high"].lt(prices["_open"])
        | prices["_high"].lt(prices["_close"])
        | prices["_low"].gt(prices["_open"])
        | prices["_low"].gt(prices["_close"])
    )
    if impossible_ohlc_mask.any():
        for ticker, group in prices.loc[
            impossible_ohlc_mask
        ].groupby("ticker"):
            _issue(
                issues,
                severity="critical",
                code="impossible_ohlc_relationship",
                ticker=str(ticker),
                count=len(group),
                detail=(
                    "OHLC relationship is impossible. Examples: "
                    + _date_examples(group["session_date"])
                ),
            )

    prices["_adjustment_factor"] = (
        prices["_adjusted_close"] / prices["_close"]
    )
    invalid_adjustment_mask = (
        ~np.isfinite(prices["_adjustment_factor"])
        | prices["_adjustment_factor"].le(0)
    )
    if invalid_adjustment_mask.any():
        for ticker, group in prices.loc[
            invalid_adjustment_mask
        ].groupby("ticker"):
            _issue(
                issues,
                severity="critical",
                code="invalid_adjustment_factor",
                ticker=str(ticker),
                count=len(group),
                detail=(
                    "adjusted_close / close is nonpositive or non-finite. "
                    "Examples: "
                    + _date_examples(group["session_date"])
                ),
            )

    quality_counts: dict[str, dict[str, int]] = {}
    for ticker, group in prices.groupby("ticker", sort=True):
        ordered = group.sort_values("_session").copy()

        adjusted_return = ordered["_adjusted_close"].pct_change(
            fill_method=None
        )
        raw_return = ordered["_close"].pct_change(fill_method=None)
        factor_change = ordered["_adjustment_factor"].pct_change(
            fill_method=None
        )

        extreme_adjusted = adjusted_return.abs().gt(
            EXTREME_ADJUSTED_RETURN_THRESHOLD
        )
        unadjusted_jump = (
            raw_return.abs().gt(UNADJUSTED_JUMP_THRESHOLD)
            & ordered["_split"].eq(0)
        )
        factor_jump = (
            factor_change.abs().gt(
                ADJUSTMENT_FACTOR_JUMP_THRESHOLD
            )
            & ordered["_split"].eq(0)
            & ordered["_dividend"].eq(0)
        )

        if extreme_adjusted.any():
            dates = ordered.loc[
                extreme_adjusted,
                "session_date",
            ]
            _issue(
                issues,
                severity="warning",
                code="extreme_adjusted_return",
                ticker=str(ticker),
                count=int(extreme_adjusted.sum()),
                detail=(
                    f"Absolute adjusted-close return exceeded "
                    f"{EXTREME_ADJUSTED_RETURN_THRESHOLD:.0%}. "
                    f"Examples: {_date_examples(dates)}"
                ),
            )

        if unadjusted_jump.any():
            dates = ordered.loc[
                unadjusted_jump,
                "session_date",
            ]
            _issue(
                issues,
                severity="warning",
                code="unadjusted_jump_without_split",
                ticker=str(ticker),
                count=int(unadjusted_jump.sum()),
                detail=(
                    f"Absolute raw-close return exceeded "
                    f"{UNADJUSTED_JUMP_THRESHOLD:.0%} without a split. "
                    f"Examples: {_date_examples(dates)}"
                ),
            )

        if factor_jump.any():
            dates = ordered.loc[
                factor_jump,
                "session_date",
            ]
            _issue(
                issues,
                severity="warning",
                code="adjustment_factor_jump_without_action",
                ticker=str(ticker),
                count=int(factor_jump.sum()),
                detail=(
                    f"Adjustment factor changed by more than "
                    f"{ADJUSTMENT_FACTOR_JUMP_THRESHOLD:.0%} without "
                    f"a recorded dividend or split. "
                    f"Examples: {_date_examples(dates)}"
                ),
            )

        quality_counts[str(ticker)] = {
            "duplicate_sessions": int(
                ordered.duplicated("session_date", keep=False).sum()
            ),
            "invalid_numeric_rows": int(
                ordered[
                    [f"_{column}" for column in numeric_columns]
                ].isna().any(axis=1).sum()
            ),
            "nonpositive_price_rows": int(
                ordered[positive_columns].le(0).any(axis=1).sum()
            ),
            "negative_volume_rows": int(
                ordered["_volume"].lt(0).sum()
            ),
            "impossible_ohlc_rows": int(
                (
                    ordered["_high"].lt(ordered["_low"])
                    | ordered["_high"].lt(ordered["_open"])
                    | ordered["_high"].lt(ordered["_close"])
                    | ordered["_low"].gt(ordered["_open"])
                    | ordered["_low"].gt(ordered["_close"])
                ).sum()
            ),
            "invalid_adjustment_factor_rows": int(
                (
                    ~np.isfinite(ordered["_adjustment_factor"])
                    | ordered["_adjustment_factor"].le(0)
                ).sum()
            ),
            "extreme_adjusted_return_rows": int(
                extreme_adjusted.sum()
            ),
            "unadjusted_jump_without_split_rows": int(
                unadjusted_jump.sum()
            ),
            "adjustment_factor_jump_without_action_rows": int(
                factor_jump.sum()
            ),
        }

    return prices, issues, quality_counts


def _session_set(
    prices: pd.DataFrame,
    ticker: str,
) -> set[str]:
    return set(
        prices.loc[
            prices["ticker"].eq(ticker)
            & prices["_session"].notna(),
            "session_date",
        ]
    )


def _estimation_dates_for_event(
    required_start_session: str,
) -> list[str]:
    start_ts = pd.Timestamp(required_start_session)
    calendar = xcals.get_calendar("XNYS", start="1990-01-01", end="2030-12-31")
    previous = calendar.sessions_window(
        start_ts,
        -(ESTIMATION_REQUIRED_SESSIONS + 1),
    )
    previous = previous[previous < start_ts]
    dates = previous[-ESTIMATION_REQUIRED_SESSIONS:]
    if len(dates) != ESTIMATION_REQUIRED_SESSIONS:
        raise PriceQualityAuditError(
            "Could not build frozen estimation window before "
            f"{required_start_session}."
        )
    return [value.date().isoformat() for value in dates]


def build_event_coverage(
    *,
    prices: pd.DataFrame,
    year_panel: pd.DataFrame,
    event_grid: pd.DataFrame,
    issues: list[dict[str, object]],
) -> pd.DataFrame:
    panel = year_panel.copy()
    panel["event_year"] = pd.to_numeric(
        panel["event_year"],
        errors="raise",
    ).astype(int)

    price_sets = {
        ticker: _session_set(prices, ticker)
        for ticker in sorted(set(prices["ticker"]))
    }

    grid_by_year: dict[int, dict[str, object]] = {}
    for year, group in event_grid.groupby("event_year"):
        ordered = group.sort_values("event_time")
        event_dates = ordered["session_date"].tolist()
        grid_by_year[int(year)] = {
            "labor_day_date": ordered[
                "labor_day_date"
            ].iloc[0],
            "required_start_session": event_dates[0],
            "required_end_session": event_dates[-1],
            "event_dates": event_dates,
            "estimation_dates": _estimation_dates_for_event(
                event_dates[0]
            ),
        }

    rows: list[dict[str, object]] = []

    spy_sessions = prices.loc[
        prices["ticker"].eq("SPY")
        & prices["_session"].notna(),
        "_session",
    ]
    latest_spy_session = (
        spy_sessions.max()
        if not spy_sessions.empty
        else pd.NaT
    )

    for item in panel.itertuples(index=False):
        year = int(item.event_year)
        grid = grid_by_year[year]
        event_dates = list(grid["event_dates"])
        estimation_dates = list(grid["estimation_dates"])

        ticker_dates = price_sets.get(item.ticker, set())

        benchmark = str(item.resolved_benchmark).strip()
        if benchmark:
            benchmark_dates = price_sets.get(benchmark, set())
        else:
            benchmark_dates = set(event_dates) | set(
                estimation_dates
            )

        ticker_event = set(event_dates).intersection(ticker_dates)
        benchmark_event = set(event_dates).intersection(
            benchmark_dates
        )
        common_event = ticker_event.intersection(benchmark_event)

        ticker_estimation = set(estimation_dates).intersection(
            ticker_dates
        )
        benchmark_estimation = set(
            estimation_dates
        ).intersection(benchmark_dates)
        common_estimation = ticker_estimation.intersection(
            benchmark_estimation
        )

        missing_ticker = len(event_dates) - len(ticker_event)
        missing_benchmark = len(event_dates) - len(
            benchmark_event
        )
        missing_common = len(event_dates) - len(common_event)
        estimation_shortfall = (
            ESTIMATION_REQUIRED_SESSIONS
            - len(common_estimation)
        )

        forward_is_pending = (
            year == FORWARD_YEAR
            and (
                pd.isna(latest_spy_session)
                or latest_spy_session
                < pd.Timestamp(grid["required_end_session"])
            )
        )

        if forward_is_pending:
            status = "forward_pending"
        elif missing_ticker > 0:
            status = "missing_ticker_event_sessions"
            _issue(
                issues,
                severity="critical",
                code="missing_historical_event_sessions",
                ticker=item.ticker,
                event_year=year,
                count=missing_ticker,
                detail=(
                    f"Eligible ticker is missing {missing_ticker} of "
                    f"{len(event_dates)} required ±20 Labor Day sessions."
                ),
            )
        elif missing_benchmark > 0:
            status = "missing_benchmark_event_sessions"
            _issue(
                issues,
                severity="critical",
                code="missing_historical_benchmark_sessions",
                ticker=item.ticker,
                event_year=year,
                count=missing_benchmark,
                detail=(
                    f"Resolved benchmark {benchmark} is missing "
                    f"{missing_benchmark} required event sessions."
                ),
            )
        elif estimation_shortfall > 0:
            status = "complete_event_short_estimation"
            _issue(
                issues,
                severity="warning",
                code="insufficient_estimation_history",
                ticker=item.ticker,
                event_year=year,
                count=estimation_shortfall,
                detail=(
                    f"Event window is complete, but only "
                    f"{len(common_estimation)} of "
                    f"{ESTIMATION_REQUIRED_SESSIONS} common "
                    f"ticker/benchmark estimation sessions are available."
                ),
            )
        else:
            status = "complete"

        rows.append(
            {
                "event_year": year,
                "sample": item.sample,
                "ticker": item.ticker,
                "provider_symbol": item.provider_symbol,
                "instrument_name": item.instrument_name,
                "hypothesis": item.hypothesis,
                "role": item.role,
                "analysis_tier": item.analysis_tier,
                "continuity_status": item.continuity_status,
                "resolved_benchmark": benchmark,
                "benchmark_resolution": (
                    item.benchmark_resolution
                ),
                "labor_day_date": grid["labor_day_date"],
                "required_start_session": (
                    grid["required_start_session"]
                ),
                "required_end_session": (
                    grid["required_end_session"]
                ),
                "expected_event_sessions": len(event_dates),
                "ticker_event_sessions": len(ticker_event),
                "benchmark_event_sessions": len(
                    benchmark_event
                ),
                "common_event_sessions": len(common_event),
                "missing_ticker_event_sessions": missing_ticker,
                "missing_benchmark_event_sessions": (
                    missing_benchmark
                ),
                "missing_common_event_sessions": missing_common,
                "estimation_required_sessions": (
                    ESTIMATION_REQUIRED_SESSIONS
                ),
                "ticker_estimation_sessions": len(
                    ticker_estimation
                ),
                "benchmark_estimation_sessions": len(
                    benchmark_estimation
                ),
                "common_estimation_sessions": len(
                    common_estimation
                ),
                "estimation_shortfall_sessions": max(
                    estimation_shortfall,
                    0,
                ),
                "event_coverage_status": status,
            }
        )

    result = pd.DataFrame(
        rows,
        columns=EVENT_COVERAGE_COLUMNS,
    )
    result.sort_values(
        ["event_year", "hypothesis", "ticker"],
        inplace=True,
    )
    result.reset_index(drop=True, inplace=True)

    if result.duplicated(["event_year", "ticker"]).any():
        raise PriceQualityAuditError(
            "Duplicate event-year/ticker rows in price coverage."
        )

    return result


def build_ticker_coverage(
    *,
    prices: pd.DataFrame,
    universe: pd.DataFrame,
    event_coverage: pd.DataFrame,
    quality_counts: dict[str, dict[str, int]],
    issues: list[dict[str, object]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for item in universe.itertuples(index=False):
        ticker_rows = prices.loc[
            prices["ticker"].eq(item.ticker)
            & prices["_session"].notna()
        ].sort_values("_session")

        if ticker_rows.empty:
            first_session = ""
            last_session = ""
            observed_rows = 0
            expected_count = 0
            missing_sessions: set[str] = set()
            unexpected_sessions: set[str] = set()
            coverage_ratio = 0.0
        else:
            first_session = ticker_rows[
                "session_date"
            ].iloc[0]
            last_session = ticker_rows[
                "session_date"
            ].iloc[-1]
            observed_rows = len(ticker_rows)

            expected = {
                value.date().isoformat()
                for value in xnys_session_dates(
                    first_session,
                    last_session,
                )
            }
            observed = set(ticker_rows["session_date"])
            missing_sessions = expected.difference(observed)
            unexpected_sessions = observed.difference(expected)
            expected_count = len(expected)
            coverage_ratio = (
                (expected_count - len(missing_sessions))
                / expected_count
                if expected_count
                else 0.0
            )

            if missing_sessions:
                _issue(
                    issues,
                    severity="warning",
                    code="missing_sessions_inside_observed_span",
                    ticker=item.ticker,
                    count=len(missing_sessions),
                    detail=(
                        "XNYS sessions missing between observed first "
                        "and last dates. Examples: "
                        + _date_examples(missing_sessions)
                    ),
                )

            if unexpected_sessions:
                _issue(
                    issues,
                    severity="critical",
                    code="non_xnys_session_present",
                    ticker=item.ticker,
                    count=len(unexpected_sessions),
                    detail=(
                        "Price rows occur on dates not recognized as "
                        "XNYS sessions. Examples: "
                        + _date_examples(unexpected_sessions)
                    ),
                )

        ticker_event = event_coverage.loc[
            event_coverage["ticker"].eq(item.ticker)
            & event_coverage["event_year"].le(
                VALIDATION_END_YEAR
            )
        ].copy()

        eligible_historical = len(ticker_event)
        complete_event_mask = ticker_event[
            "missing_common_event_sessions"
        ].eq(0)
        complete_historical = int(complete_event_mask.sum())
        incomplete_historical = (
            eligible_historical - complete_historical
        )

        complete_years = ticker_event.loc[
            complete_event_mask,
            "event_year",
        ].astype(int)

        estimation_ready_years = ticker_event.loc[
            complete_event_mask
            & ticker_event[
                "estimation_shortfall_sessions"
            ].eq(0),
            "event_year",
        ].astype(int)

        first_complete = (
            int(complete_years.min())
            if not complete_years.empty
            else ""
        )
        first_estimation_ready = (
            int(estimation_ready_years.min())
            if not estimation_ready_years.empty
            else ""
        )

        policy_start_year = int(item.analysis_start_year)
        policy_end_year = (
            int(item.analysis_end_year)
            if str(item.analysis_end_year).strip()
            else FORWARD_YEAR
        )

        if first_complete == "":
            recommended_start: int | str = ""
        elif first_estimation_ready != "":
            recommended_start = max(
                policy_start_year,
                int(first_estimation_ready),
            )
        else:
            recommended_start = max(
                policy_start_year,
                int(first_complete),
            )

        if (
            first_complete != ""
            and int(first_complete) > policy_start_year
        ):
            _issue(
                issues,
                severity="critical",
                code="policy_start_precedes_complete_price_history",
                ticker=item.ticker,
                event_year=policy_start_year,
                count=int(first_complete) - policy_start_year,
                detail=(
                    f"Universe admits {item.ticker} from "
                    f"{policy_start_year}, but its first complete "
                    f"historical ±20 event year is {first_complete}. "
                    f"Recommended conservative start: "
                    f"{recommended_start}."
                ),
            )

        if item.continuity_status == "predecessor_continuity":
            _issue(
                issues,
                severity="warning",
                code="predecessor_continuity_manual_review",
                ticker=item.ticker,
                detail=(
                    f"Provider history may include predecessor symbol(s) "
                    f"{item.predecessor_symbols}. Verify economic-equity "
                    f"continuity and adjustment factors before final use."
                ),
            )

        if (
            item.continuity_status == "current_public_era"
            and first_session
            and pd.Timestamp(first_session).year
            < policy_start_year
        ):
            _issue(
                issues,
                severity="info",
                code="prepolicy_provider_history_present",
                ticker=item.ticker,
                session_date=first_session,
                detail=(
                    f"Provider series begins before the frozen "
                    f"current-public-era start year {policy_start_year}. "
                    f"Rows before the policy start remain cached but are "
                    f"ineligible for the event study."
                ),
            )

        counts = quality_counts.get(
            item.ticker,
            {
                "duplicate_sessions": 0,
                "invalid_numeric_rows": 0,
                "nonpositive_price_rows": 0,
                "negative_volume_rows": 0,
                "impossible_ohlc_rows": 0,
                "invalid_adjustment_factor_rows": 0,
                "extreme_adjusted_return_rows": 0,
                "unadjusted_jump_without_split_rows": 0,
                "adjustment_factor_jump_without_action_rows": 0,
            },
        )

        critical_local = (
            counts["duplicate_sessions"]
            + counts["invalid_numeric_rows"]
            + counts["nonpositive_price_rows"]
            + counts["negative_volume_rows"]
            + counts["impossible_ohlc_rows"]
            + counts["invalid_adjustment_factor_rows"]
            + len(unexpected_sessions)
            + incomplete_historical
        )

        warning_local = (
            len(missing_sessions)
            + counts["extreme_adjusted_return_rows"]
            + counts["unadjusted_jump_without_split_rows"]
            + counts[
                "adjustment_factor_jump_without_action_rows"
            ]
            + int(
                item.continuity_status
                == "predecessor_continuity"
            )
        )

        if critical_local:
            ticker_status = "FAIL"
        elif warning_local:
            ticker_status = "PASS_WITH_WARNINGS"
        else:
            ticker_status = "PASS"

        rows.append(
            {
                "ticker": item.ticker,
                "provider_symbol": item.provider_symbol,
                "instrument_name": item.instrument_name,
                "hypothesis": item.hypothesis,
                "role": item.role,
                "analysis_tier": item.analysis_tier,
                "continuity_status": item.continuity_status,
                "policy_start_year": policy_start_year,
                "policy_end_year": policy_end_year,
                "observed_first_session": first_session,
                "observed_last_session": last_session,
                "observed_rows": observed_rows,
                "expected_xnys_sessions": expected_count,
                "missing_xnys_sessions": len(
                    missing_sessions
                ),
                "unexpected_non_xnys_sessions": len(
                    unexpected_sessions
                ),
                "coverage_ratio": round(
                    float(coverage_ratio),
                    10,
                ),
                **counts,
                "eligible_historical_event_years": (
                    eligible_historical
                ),
                "complete_historical_event_years": (
                    complete_historical
                ),
                "incomplete_historical_event_years": (
                    incomplete_historical
                ),
                "first_event_complete_year": first_complete,
                "first_estimation_ready_year": (
                    first_estimation_ready
                ),
                "recommended_analysis_start_year": (
                    recommended_start
                ),
                "ticker_status": ticker_status,
            }
        )

    result = pd.DataFrame(
        rows,
        columns=TICKER_COVERAGE_COLUMNS,
    )
    result.sort_values("ticker", inplace=True)
    result.reset_index(drop=True, inplace=True)
    return result


def finalize_issues(
    issues: list[dict[str, object]],
) -> pd.DataFrame:
    dataframe = pd.DataFrame(
        issues,
        columns=ISSUE_COLUMNS,
    )
    if dataframe.empty:
        return dataframe

    dataframe["_severity_order"] = dataframe[
        "severity"
    ].map(SEVERITY_ORDER)
    dataframe["_year_sort"] = pd.to_numeric(
        dataframe["event_year"],
        errors="coerce",
    ).fillna(9999)
    dataframe.sort_values(
        [
            "_severity_order",
            "issue_code",
            "ticker",
            "_year_sort",
            "session_date",
        ],
        inplace=True,
    )
    dataframe.drop(
        columns=["_severity_order", "_year_sort"],
        inplace=True,
    )
    dataframe.reset_index(drop=True, inplace=True)
    return dataframe


def issue_counts(
    issues: pd.DataFrame,
) -> dict[str, int]:
    counts = {
        "critical": 0,
        "warning": 0,
        "info": 0,
    }
    if issues.empty:
        return counts

    observed = issues["severity"].value_counts()
    for severity in counts:
        counts[severity] = int(observed.get(severity, 0))
    return counts


def build_manifest(
    *,
    prices_path: Path,
    universe_path: Path,
    year_panel_path: Path,
    price_manifest_path: Path,
    ticker_coverage_path: Path,
    event_coverage_path: Path,
    issues_path: Path,
    ticker_coverage: pd.DataFrame,
    event_coverage: pd.DataFrame,
    issues: pd.DataFrame,
) -> dict[str, object]:
    counts = issue_counts(issues)

    if counts["critical"] > 0:
        status = "FAIL"
    elif counts["warning"] > 0:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"

    event_status_counts = (
        event_coverage["event_coverage_status"]
        .value_counts()
        .sort_index()
        .astype(int)
        .to_dict()
    )
    ticker_status_counts = (
        ticker_coverage["ticker_status"]
        .value_counts()
        .sort_index()
        .astype(int)
        .to_dict()
    )

    return {
        "artifact": "Labor Day price quality and historical coverage audit",
        "schema_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "study_range": {
            "start_year": STUDY_START_YEAR,
            "discovery_end_year": DISCOVERY_END_YEAR,
            "validation_start_year": VALIDATION_START_YEAR,
            "validation_end_year": VALIDATION_END_YEAR,
            "forward_year": FORWARD_YEAR,
        },
        "audit_policy": {
            "exchange_calendar": "XNYS",
            "event_pre_sessions": EVENT_PRE_SESSIONS,
            "event_post_sessions": EVENT_POST_SESSIONS,
            "estimation_required_sessions": (
                ESTIMATION_REQUIRED_SESSIONS
            ),
            "extreme_adjusted_return_threshold": (
                EXTREME_ADJUSTED_RETURN_THRESHOLD
            ),
            "unadjusted_jump_threshold": (
                UNADJUSTED_JUMP_THRESHOLD
            ),
            "adjustment_factor_jump_threshold": (
                ADJUSTMENT_FACTOR_JUMP_THRESHOLD
            ),
        },
        "inputs": {
            "daily_prices": {
                "path": str(prices_path.resolve()),
                "sha256": sha256_file(prices_path),
            },
            "universe": {
                "path": str(universe_path.resolve()),
                "sha256": sha256_file(universe_path),
            },
            "year_panel": {
                "path": str(year_panel_path.resolve()),
                "sha256": sha256_file(year_panel_path),
            },
            "daily_prices_manifest": {
                "path": str(price_manifest_path.resolve()),
                "sha256": sha256_file(price_manifest_path),
            },
        },
        "outputs": {
            "ticker_coverage": {
                "path": str(ticker_coverage_path.resolve()),
                "sha256": sha256_file(ticker_coverage_path),
                "rows": len(ticker_coverage),
            },
            "event_coverage": {
                "path": str(event_coverage_path.resolve()),
                "sha256": sha256_file(event_coverage_path),
                "rows": len(event_coverage),
            },
            "issues": {
                "path": str(issues_path.resolve()),
                "sha256": sha256_file(issues_path),
                "rows": len(issues),
            },
        },
        "summary": {
            "tickers": len(ticker_coverage),
            "event_year_rows": len(event_coverage),
            "issue_counts": counts,
            "ticker_status_counts": ticker_status_counts,
            "event_coverage_status_counts": (
                event_status_counts
            ),
            "historical_incomplete_rows": int(
                event_coverage.loc[
                    event_coverage["event_year"].le(
                        VALIDATION_END_YEAR
                    ),
                    "missing_common_event_sessions",
                ].gt(0).sum()
            ),
            "historical_short_estimation_rows": int(
                event_coverage.loc[
                    event_coverage["event_year"].le(
                        VALIDATION_END_YEAR
                    ),
                    "estimation_shortfall_sessions",
                ].gt(0).sum()
            ),
            "forward_pending_rows": int(
                event_coverage[
                    "event_coverage_status"
                ].eq("forward_pending").sum()
            ),
        },
    }


def run_price_quality_audit(
    *,
    prices_path: Path = DEFAULT_PRICES_PATH,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    year_panel_path: Path = DEFAULT_YEAR_PANEL_PATH,
    price_manifest_path: Path = DEFAULT_PRICE_MANIFEST_PATH,
    ticker_coverage_path: Path = DEFAULT_TICKER_COVERAGE_PATH,
    event_coverage_path: Path = DEFAULT_EVENT_COVERAGE_PATH,
    issues_path: Path = DEFAULT_ISSUES_PATH,
    audit_manifest_path: Path = DEFAULT_AUDIT_MANIFEST_PATH,
    fail_on_critical: bool = True,
) -> AuditResult:
    raw_prices, universe, year_panel, price_manifest = load_inputs(
        prices_path=prices_path,
        universe_path=universe_path,
        year_panel_path=year_panel_path,
        price_manifest_path=price_manifest_path,
    )

    provenance_issues: list[dict[str, object]] = []
    current_price_hash = sha256_file(prices_path)
    current_universe_hash = sha256_file(universe_path)

    manifest_price_hash = str(
        price_manifest.get("output", {}).get("sha256", "")
    )
    if manifest_price_hash != current_price_hash:
        _issue(
            provenance_issues,
            severity="critical",
            code="price_manifest_output_hash_mismatch",
            detail=(
                "daily_prices.csv hash does not match the frozen "
                "daily-prices manifest."
            ),
        )

    manifest_universe_hash = str(
        price_manifest.get("universe", {}).get("sha256", "")
    )
    if manifest_universe_hash != current_universe_hash:
        _issue(
            provenance_issues,
            severity="critical",
            code="price_manifest_universe_hash_mismatch",
            detail=(
                "Current universe hash does not match the universe "
                "used by the daily-prices manifest."
            ),
        )

    manifest_rows = price_manifest.get("output", {}).get("rows")
    if manifest_rows != len(raw_prices):
        _issue(
            provenance_issues,
            severity="critical",
            code="price_manifest_row_count_mismatch",
            count=abs(int(manifest_rows or 0) - len(raw_prices)),
            detail=(
                f"Manifest rows={manifest_rows}; "
                f"daily_prices.csv rows={len(raw_prices)}."
            ),
        )

    if price_manifest.get("status") != "PASS":
        _issue(
            provenance_issues,
            severity="critical",
            code="daily_price_manifest_not_pass",
            detail=(
                "The upstream daily-price ingestion manifest is not PASS."
            ),
        )

    prepared, issues, quality_counts = prepare_prices(
        raw_prices,
        universe,
    )
    issues = provenance_issues + issues
    event_grid = build_event_session_grid()
    event_coverage = build_event_coverage(
        prices=prepared,
        year_panel=year_panel,
        event_grid=event_grid,
        issues=issues,
    )
    ticker_coverage = build_ticker_coverage(
        prices=prepared,
        universe=universe,
        event_coverage=event_coverage,
        quality_counts=quality_counts,
        issues=issues,
    )
    issue_frame = finalize_issues(issues)

    atomic_write_csv(
        ticker_coverage,
        ticker_coverage_path,
    )
    atomic_write_csv(
        event_coverage,
        event_coverage_path,
    )
    atomic_write_csv(issue_frame, issues_path)

    manifest = build_manifest(
        prices_path=prices_path,
        universe_path=universe_path,
        year_panel_path=year_panel_path,
        price_manifest_path=price_manifest_path,
        ticker_coverage_path=ticker_coverage_path,
        event_coverage_path=event_coverage_path,
        issues_path=issues_path,
        ticker_coverage=ticker_coverage,
        event_coverage=event_coverage,
        issues=issue_frame,
    )
    atomic_write_json(manifest, audit_manifest_path)

    if (
        fail_on_critical
        and manifest["summary"]["issue_counts"]["critical"] > 0
    ):
        raise PriceQualityAuditError(
            "Price-quality audit found critical issues. "
            f"Outputs were written; inspect {issues_path}."
        )

    return AuditResult(
        ticker_coverage=ticker_coverage,
        event_coverage=event_coverage,
        issues=issue_frame,
        manifest=manifest,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit normalized daily prices for structural quality, "
            "XNYS-session coverage, Labor Day event coverage, "
            "benchmark overlap, and continuity policy."
        )
    )
    parser.add_argument(
        "--prices",
        type=Path,
        default=DEFAULT_PRICES_PATH,
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=DEFAULT_UNIVERSE_PATH,
    )
    parser.add_argument(
        "--year-panel",
        type=Path,
        default=DEFAULT_YEAR_PANEL_PATH,
    )
    parser.add_argument(
        "--price-manifest",
        type=Path,
        default=DEFAULT_PRICE_MANIFEST_PATH,
    )
    parser.add_argument(
        "--ticker-output",
        type=Path,
        default=DEFAULT_TICKER_COVERAGE_PATH,
    )
    parser.add_argument(
        "--event-output",
        type=Path,
        default=DEFAULT_EVENT_COVERAGE_PATH,
    )
    parser.add_argument(
        "--issues-output",
        type=Path,
        default=DEFAULT_ISSUES_PATH,
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_AUDIT_MANIFEST_PATH,
    )
    parser.add_argument(
        "--allow-critical",
        action="store_true",
        help=(
            "Write a FAIL audit without raising after critical issues. "
            "Useful for the first diagnostic run."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_price_quality_audit(
        prices_path=args.prices,
        universe_path=args.universe,
        year_panel_path=args.year_panel,
        price_manifest_path=args.price_manifest,
        ticker_coverage_path=args.ticker_output,
        event_coverage_path=args.event_output,
        issues_path=args.issues_output,
        audit_manifest_path=args.manifest_output,
        fail_on_critical=not args.allow_critical,
    )

    summary = result.manifest["summary"]
    counts = summary["issue_counts"]

    print("Labor Day price-quality audit generated.")
    print(f"Status: {result.manifest['status']}")
    print(f"Tickers audited: {summary['tickers']}")
    print(
        "Event-year coverage rows: "
        f"{summary['event_year_rows']}"
    )
    print(
        "Issues: "
        f"critical={counts['critical']}, "
        f"warning={counts['warning']}, "
        f"info={counts['info']}"
    )
    print(
        "Historical incomplete event rows: "
        f"{summary['historical_incomplete_rows']}"
    )
    print(
        "Historical short-estimation rows: "
        f"{summary['historical_short_estimation_rows']}"
    )
    print(
        "Forward-pending rows: "
        f"{summary['forward_pending_rows']}"
    )
    print(
        f"Ticker coverage: {args.ticker_output.resolve()}"
    )
    print(
        f"Event coverage: {args.event_output.resolve()}"
    )
    print(
        f"Issues: {args.issues_output.resolve()}"
    )
    print(
        f"Manifest: {args.manifest_output.resolve()}"
    )


if __name__ == "__main__":
    main()
