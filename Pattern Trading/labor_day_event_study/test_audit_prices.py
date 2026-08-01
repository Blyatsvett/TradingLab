from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from labor_day.audit_prices import (
    ADJUSTMENT_FACTOR_JUMP_THRESHOLD,
    EVENT_POST_SESSIONS,
    EVENT_PRE_SESSIONS,
    ESTIMATION_REQUIRED_SESSIONS,
    FORWARD_YEAR,
    ISSUE_COLUMNS,
    PRICE_COLUMNS,
    PriceQualityAuditError,
    build_event_coverage,
    build_event_session_grid,
    build_ticker_coverage,
    finalize_issues,
    first_monday_in_september,
    issue_counts,
    prepare_prices,
    run_price_quality_audit,
    sha256_file,
    xnys_session_dates,
)


UNIVERSE_COLUMNS = [
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

YEAR_PANEL_COLUMNS = [
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


def make_universe(
    *,
    ticker: str = "VLO",
    analysis_start_year: int = 1998,
    continuity_status: str = "continuous",
    predecessor_symbols: str = "",
) -> pd.DataFrame:
    rows = [
        {
            "ticker": "SPY",
            "provider_symbol": "SPY",
            "instrument_name": "SPY",
            "hypothesis": "generic_control",
            "subindustry": "broad_market",
            "role": "market_benchmark",
            "analysis_tier": "core",
            "security_type": "etf",
            "exchange": "NYSE_ARCA",
            "currency": "USD",
            "primary_benchmark": "",
            "fallback_benchmark": "",
            "analysis_start_year": "1998",
            "analysis_end_year": "",
            "discovery_eligible": "true",
            "validation_eligible": "true",
            "forward_eligible": "true",
            "continuity_status": "continuous",
            "predecessor_symbols": "",
            "source_url": "https://example.com/spy",
            "notes": "Synthetic benchmark.",
        },
        {
            "ticker": ticker,
            "provider_symbol": ticker,
            "instrument_name": ticker,
            "hypothesis": "refining_gasoline",
            "subindustry": "independent_refiner",
            "role": "hypothesis_stock",
            "analysis_tier": "core",
            "security_type": "common_stock",
            "exchange": "NYSE",
            "currency": "USD",
            "primary_benchmark": "SPY",
            "fallback_benchmark": "SPY",
            "analysis_start_year": str(analysis_start_year),
            "analysis_end_year": "",
            "discovery_eligible": "true",
            "validation_eligible": "true",
            "forward_eligible": "true",
            "continuity_status": continuity_status,
            "predecessor_symbols": predecessor_symbols,
            "source_url": f"https://example.com/{ticker.lower()}",
            "notes": "Synthetic stock.",
        },
    ]
    return pd.DataFrame(rows, columns=UNIVERSE_COLUMNS)


def make_year_panel(
    *,
    ticker: str = "VLO",
    years: tuple[int, ...] = (1998,),
    continuity_status: str = "continuous",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year in years:
        sample = (
            "discovery"
            if year <= 2014
            else "validation"
            if year <= 2025
            else "forward"
        )
        rows.extend(
            [
                {
                    "event_year": str(year),
                    "sample": sample,
                    "ticker": "SPY",
                    "provider_symbol": "SPY",
                    "instrument_name": "SPY",
                    "hypothesis": "generic_control",
                    "subindustry": "broad_market",
                    "role": "market_benchmark",
                    "analysis_tier": "core",
                    "resolved_benchmark": "",
                    "benchmark_resolution": "none",
                    "eligible_group_members": "0",
                    "equal_weight": "",
                    "continuity_status": "continuous",
                },
                {
                    "event_year": str(year),
                    "sample": sample,
                    "ticker": ticker,
                    "provider_symbol": ticker,
                    "instrument_name": ticker,
                    "hypothesis": "refining_gasoline",
                    "subindustry": "independent_refiner",
                    "role": "hypothesis_stock",
                    "analysis_tier": "core",
                    "resolved_benchmark": "SPY",
                    "benchmark_resolution": "primary",
                    "eligible_group_members": "1",
                    "equal_weight": "1.0",
                    "continuity_status": continuity_status,
                },
            ]
        )
    return pd.DataFrame(rows, columns=YEAR_PANEL_COLUMNS)


def make_prices(
    *,
    tickers: tuple[str, ...] = ("SPY", "VLO"),
    start: str = "1997-01-02",
    end: str = "1998-10-30",
) -> pd.DataFrame:
    sessions = xnys_session_dates(start, end)
    rows: list[dict[str, object]] = []

    for ticker_index, ticker in enumerate(tickers):
        for index, session in enumerate(sessions):
            close = 100.0 + ticker_index * 10 + index * 0.01
            rows.append(
                {
                    "ticker": ticker,
                    "provider_symbol": ticker,
                    "session_date": session.date().isoformat(),
                    "open": close - 0.25,
                    "high": close + 0.50,
                    "low": close - 0.50,
                    "close": close,
                    "adjusted_close": close,
                    "volume": 1_000_000 + index,
                    "dividend": 0,
                    "split": 0,
                    "retrieved_utc": (
                        "2026-07-23T21:00:00+00:00"
                    ),
                    "source": "Yahoo Finance via yfinance",
                    "source_file": (
                        f"data/raw/prices/yahoo/{ticker}.csv"
                    ),
                    "request_hash": "a" * 20,
                    "raw_sha256": "b" * 64,
                }
            )

    return pd.DataFrame(rows, columns=PRICE_COLUMNS)


def write_fixture_files(
    tmp_path: Path,
    *,
    prices: pd.DataFrame,
    universe: pd.DataFrame,
    panel: pd.DataFrame,
    manifest_status: str = "PASS",
) -> dict[str, Path]:
    paths = {
        "prices": tmp_path / "daily_prices.csv",
        "universe": tmp_path / "labor_day_universe.csv",
        "panel": tmp_path / "labor_day_universe_by_year.csv",
        "price_manifest": tmp_path / "daily_prices_manifest.json",
        "ticker_output": tmp_path / "price_coverage_by_ticker.csv",
        "event_output": tmp_path / "price_coverage_by_event_year.csv",
        "issues_output": tmp_path / "price_quality_issues.csv",
        "audit_manifest": tmp_path / "price_quality_audit.json",
    }

    prices.to_csv(paths["prices"], index=False)
    universe.to_csv(paths["universe"], index=False)
    panel.to_csv(paths["panel"], index=False)

    manifest = {
        "status": manifest_status,
        "output": {
            "sha256": sha256_file(paths["prices"]),
            "rows": len(prices),
        },
        "universe": {
            "sha256": sha256_file(paths["universe"]),
        },
    }
    paths["price_manifest"].write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return paths


def test_first_monday_in_september() -> None:
    assert first_monday_in_september(1998).isoformat() == (
        "1998-09-07"
    )
    assert first_monday_in_september(2026).isoformat() == (
        "2026-09-07"
    )


def test_event_grid_has_frozen_shape_and_no_zero() -> None:
    grid = build_event_session_grid()
    assert len(grid) == 29 * 40
    assert not grid["event_time"].eq(0).any()
    assert grid.groupby("event_year").size().eq(40).all()


def test_event_grid_has_20_sessions_each_side() -> None:
    grid = build_event_session_grid(
        start_year=1998,
        end_year=1998,
    )
    assert (grid["event_time"] < 0).sum() == EVENT_PRE_SESSIONS
    assert (grid["event_time"] > 0).sum() == EVENT_POST_SESSIONS
    assert grid["event_time"].min() == -20
    assert grid["event_time"].max() == 20


def test_prepare_clean_prices_has_no_structural_issues() -> None:
    prepared, issues, counts = prepare_prices(
        make_prices(),
        make_universe(),
    )
    assert not prepared.empty
    assert issues == []
    assert counts["SPY"]["impossible_ohlc_rows"] == 0
    assert counts["VLO"]["invalid_adjustment_factor_rows"] == 0


def test_duplicate_session_is_critical() -> None:
    prices = make_prices()
    duplicate = pd.concat(
        [prices, prices.iloc[[0]]],
        ignore_index=True,
    )
    _, issues, _ = prepare_prices(
        duplicate,
        make_universe(),
    )
    assert any(
        issue["issue_code"] == "duplicate_ticker_session"
        and issue["severity"] == "critical"
        for issue in issues
    )


def test_invalid_numeric_field_is_critical() -> None:
    prices = make_prices()
    prices["close"] = prices["close"].astype(object)
    prices.loc[0, "close"] = "bad"
    _, issues, counts = prepare_prices(
        prices,
        make_universe(),
    )
    assert counts["SPY"]["invalid_numeric_rows"] == 1
    assert any(
        issue["issue_code"] == "invalid_numeric_price_field"
        for issue in issues
    )


def test_nonpositive_price_is_critical() -> None:
    prices = make_prices()
    prices.loc[0, "open"] = 0
    _, issues, counts = prepare_prices(
        prices,
        make_universe(),
    )
    assert counts["SPY"]["nonpositive_price_rows"] == 1
    assert any(
        issue["issue_code"] == "nonpositive_price"
        for issue in issues
    )


def test_negative_volume_is_critical() -> None:
    prices = make_prices()
    prices.loc[0, "volume"] = -1
    _, issues, counts = prepare_prices(
        prices,
        make_universe(),
    )
    assert counts["SPY"]["negative_volume_rows"] == 1
    assert any(
        issue["issue_code"] == "negative_volume"
        for issue in issues
    )


def test_impossible_ohlc_is_critical() -> None:
    prices = make_prices()
    prices.loc[0, "high"] = 1
    _, issues, counts = prepare_prices(
        prices,
        make_universe(),
    )
    assert counts["SPY"]["impossible_ohlc_rows"] == 1
    assert any(
        issue["issue_code"] == "impossible_ohlc_relationship"
        for issue in issues
    )


def test_invalid_adjustment_factor_is_critical() -> None:
    prices = make_prices()
    prices.loc[0, "adjusted_close"] = 0
    _, issues, counts = prepare_prices(
        prices,
        make_universe(),
    )
    assert counts["SPY"]["invalid_adjustment_factor_rows"] == 1
    assert any(
        issue["issue_code"] == "invalid_adjustment_factor"
        for issue in issues
    )


def test_extreme_adjusted_return_is_warning() -> None:
    prices = make_prices()
    vlo_indices = prices.index[prices["ticker"].eq("VLO")]
    prices.loc[vlo_indices[10], "adjusted_close"] = 500
    _, issues, counts = prepare_prices(
        prices,
        make_universe(),
    )
    assert counts["VLO"]["extreme_adjusted_return_rows"] >= 1
    assert any(
        issue["issue_code"] == "extreme_adjusted_return"
        and issue["severity"] == "warning"
        for issue in issues
    )


def test_adjustment_factor_jump_without_action_is_warning() -> None:
    prices = make_prices()
    vlo_indices = prices.index[prices["ticker"].eq("VLO")]
    target = vlo_indices[10]
    prices.loc[target, "adjusted_close"] = (
        float(prices.loc[target, "close"])
        * (1 + ADJUSTMENT_FACTOR_JUMP_THRESHOLD + 0.10)
    )
    _, issues, counts = prepare_prices(
        prices,
        make_universe(),
    )
    assert (
        counts["VLO"][
            "adjustment_factor_jump_without_action_rows"
        ]
        >= 1
    )
    assert any(
        issue["issue_code"]
        == "adjustment_factor_jump_without_action"
        for issue in issues
    )


def test_complete_event_coverage_has_40_common_sessions() -> None:
    prices, issues, _ = prepare_prices(
        make_prices(),
        make_universe(),
    )
    result = build_event_coverage(
        prices=prices,
        year_panel=make_year_panel(),
        event_grid=build_event_session_grid(),
        issues=issues,
    )
    vlo = result.loc[result["ticker"].eq("VLO")].iloc[0]
    assert vlo["common_event_sessions"] == 40
    assert vlo["missing_common_event_sessions"] == 0
    assert vlo["event_coverage_status"] == "complete"


def test_missing_historical_event_session_is_critical() -> None:
    raw = make_prices()
    grid = build_event_session_grid(
        start_year=1998,
        end_year=1998,
    )
    missing_date = grid.iloc[10]["session_date"]
    raw = raw.loc[
        ~(
            raw["ticker"].eq("VLO")
            & raw["session_date"].eq(missing_date)
        )
    ].copy()

    prices, issues, _ = prepare_prices(raw, make_universe())
    result = build_event_coverage(
        prices=prices,
        year_panel=make_year_panel(),
        event_grid=build_event_session_grid(),
        issues=issues,
    )

    vlo = result.loc[result["ticker"].eq("VLO")].iloc[0]
    assert vlo["missing_ticker_event_sessions"] == 1
    assert vlo["event_coverage_status"] == (
        "missing_ticker_event_sessions"
    )
    assert any(
        issue["issue_code"] == "missing_historical_event_sessions"
        and issue["severity"] == "critical"
        for issue in issues
    )


def test_short_estimation_history_is_warning() -> None:
    raw = make_prices(start="1998-03-23")
    prices, issues, _ = prepare_prices(raw, make_universe())
    result = build_event_coverage(
        prices=prices,
        year_panel=make_year_panel(),
        event_grid=build_event_session_grid(),
        issues=issues,
    )

    vlo = result.loc[result["ticker"].eq("VLO")].iloc[0]
    assert vlo["missing_common_event_sessions"] == 0
    assert vlo["common_estimation_sessions"] < (
        ESTIMATION_REQUIRED_SESSIONS
    )
    assert vlo["event_coverage_status"] == (
        "complete_event_short_estimation"
    )
    assert any(
        issue["issue_code"] == "insufficient_estimation_history"
        for issue in issues
    )


def test_forward_row_is_pending_before_event_completes() -> None:
    prices, issues, _ = prepare_prices(
        make_prices(),
        make_universe(),
    )
    result = build_event_coverage(
        prices=prices,
        year_panel=make_year_panel(years=(FORWARD_YEAR,)),
        event_grid=build_event_session_grid(),
        issues=issues,
    )
    assert result["event_coverage_status"].eq(
        "forward_pending"
    ).all()
    assert not any(
        issue["event_year"] == FORWARD_YEAR
        and issue["severity"] == "critical"
        for issue in issues
    )


def test_missing_session_inside_observed_span_is_warning() -> None:
    raw = make_prices()
    middle_date = raw.loc[
        raw["ticker"].eq("VLO"),
        "session_date",
    ].iloc[100]
    raw = raw.loc[
        ~(
            raw["ticker"].eq("VLO")
            & raw["session_date"].eq(middle_date)
        )
    ].copy()

    prices, issues, counts = prepare_prices(
        raw,
        make_universe(),
    )
    event_coverage = build_event_coverage(
        prices=prices,
        year_panel=make_year_panel(),
        event_grid=build_event_session_grid(),
        issues=issues,
    )
    coverage = build_ticker_coverage(
        prices=prices,
        universe=make_universe(),
        event_coverage=event_coverage,
        quality_counts=counts,
        issues=issues,
    )

    vlo = coverage.loc[coverage["ticker"].eq("VLO")].iloc[0]
    assert vlo["missing_xnys_sessions"] == 1
    assert any(
        issue["issue_code"]
        == "missing_sessions_inside_observed_span"
        for issue in issues
    )


def test_policy_start_before_first_complete_year_is_critical() -> None:
    raw = make_prices(
        start="1999-01-04",
        end="1999-10-29",
    )
    prices, issues, counts = prepare_prices(
        raw,
        make_universe(),
    )
    event_coverage = build_event_coverage(
        prices=prices,
        year_panel=make_year_panel(years=(1998, 1999)),
        event_grid=build_event_session_grid(),
        issues=issues,
    )
    coverage = build_ticker_coverage(
        prices=prices,
        universe=make_universe(),
        event_coverage=event_coverage,
        quality_counts=counts,
        issues=issues,
    )

    vlo = coverage.loc[coverage["ticker"].eq("VLO")].iloc[0]
    assert vlo["first_event_complete_year"] == 1999
    assert vlo["incomplete_historical_event_years"] == 1
    assert any(
        issue["issue_code"]
        == "policy_start_precedes_complete_price_history"
        and issue["severity"] == "critical"
        for issue in issues
    )


def test_predecessor_continuity_creates_warning() -> None:
    universe = make_universe(
        continuity_status="predecessor_continuity",
        predecessor_symbols="HFC",
    )
    prices, issues, counts = prepare_prices(
        make_prices(),
        universe,
    )
    event_coverage = build_event_coverage(
        prices=prices,
        year_panel=make_year_panel(
            continuity_status="predecessor_continuity"
        ),
        event_grid=build_event_session_grid(),
        issues=issues,
    )
    build_ticker_coverage(
        prices=prices,
        universe=universe,
        event_coverage=event_coverage,
        quality_counts=counts,
        issues=issues,
    )

    assert any(
        issue["issue_code"]
        == "predecessor_continuity_manual_review"
        and issue["severity"] == "warning"
        for issue in issues
    )


def test_current_public_era_prepolicy_history_is_info() -> None:
    universe = make_universe(
        analysis_start_year=2000,
        continuity_status="current_public_era",
    )
    panel = make_year_panel(years=(2000,))
    prices, issues, counts = prepare_prices(
        make_prices(),
        universe,
    )
    event_coverage = build_event_coverage(
        prices=prices,
        year_panel=panel,
        event_grid=build_event_session_grid(),
        issues=issues,
    )
    build_ticker_coverage(
        prices=prices,
        universe=universe,
        event_coverage=event_coverage,
        quality_counts=counts,
        issues=issues,
    )

    assert any(
        issue["issue_code"] == "prepolicy_provider_history_present"
        and issue["severity"] == "info"
        for issue in issues
    )


def test_finalize_issues_sorts_by_severity() -> None:
    issues = [
        {
            "severity": "info",
            "issue_code": "z",
            "ticker": "",
            "event_year": "",
            "session_date": "",
            "count": 1,
            "detail": "info",
        },
        {
            "severity": "critical",
            "issue_code": "a",
            "ticker": "",
            "event_year": "",
            "session_date": "",
            "count": 1,
            "detail": "critical",
        },
        {
            "severity": "warning",
            "issue_code": "b",
            "ticker": "",
            "event_year": "",
            "session_date": "",
            "count": 1,
            "detail": "warning",
        },
    ]
    frame = finalize_issues(issues)
    assert list(frame.columns) == ISSUE_COLUMNS
    assert frame["severity"].tolist() == [
        "critical",
        "warning",
        "info",
    ]


def test_issue_counts_include_zero_categories() -> None:
    frame = pd.DataFrame(
        [
            {
                "severity": "warning",
                "issue_code": "x",
                "ticker": "",
                "event_year": "",
                "session_date": "",
                "count": 1,
                "detail": "x",
            }
        ],
        columns=ISSUE_COLUMNS,
    )
    assert issue_counts(frame) == {
        "critical": 0,
        "warning": 1,
        "info": 0,
    }


def test_run_audit_writes_all_outputs(tmp_path: Path) -> None:
    paths = write_fixture_files(
        tmp_path,
        prices=make_prices(),
        universe=make_universe(),
        panel=make_year_panel(),
    )

    result = run_price_quality_audit(
        prices_path=paths["prices"],
        universe_path=paths["universe"],
        year_panel_path=paths["panel"],
        price_manifest_path=paths["price_manifest"],
        ticker_coverage_path=paths["ticker_output"],
        event_coverage_path=paths["event_output"],
        issues_path=paths["issues_output"],
        audit_manifest_path=paths["audit_manifest"],
        fail_on_critical=True,
    )

    assert paths["ticker_output"].exists()
    assert paths["event_output"].exists()
    assert paths["issues_output"].exists()
    assert paths["audit_manifest"].exists()
    assert result.manifest["status"] in {
        "PASS",
        "PASS_WITH_WARNINGS",
    }
    assert result.manifest["summary"]["tickers"] == 2
    assert result.manifest["summary"]["event_year_rows"] == 2


def test_manifest_hash_mismatch_is_critical(
    tmp_path: Path,
) -> None:
    paths = write_fixture_files(
        tmp_path,
        prices=make_prices(),
        universe=make_universe(),
        panel=make_year_panel(),
    )
    manifest = json.loads(
        paths["price_manifest"].read_text(encoding="utf-8")
    )
    manifest["output"]["sha256"] = "0" * 64
    paths["price_manifest"].write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    result = run_price_quality_audit(
        prices_path=paths["prices"],
        universe_path=paths["universe"],
        year_panel_path=paths["panel"],
        price_manifest_path=paths["price_manifest"],
        ticker_coverage_path=paths["ticker_output"],
        event_coverage_path=paths["event_output"],
        issues_path=paths["issues_output"],
        audit_manifest_path=paths["audit_manifest"],
        fail_on_critical=False,
    )

    assert result.manifest["status"] == "FAIL"
    assert "price_manifest_output_hash_mismatch" in set(
        result.issues["issue_code"]
    )


def test_failure_outputs_are_written_before_raise(
    tmp_path: Path,
) -> None:
    prices = make_prices()
    grid = build_event_session_grid(
        start_year=1998,
        end_year=1998,
    )
    missing_date = grid.iloc[0]["session_date"]
    prices = prices.loc[
        ~(
            prices["ticker"].eq("VLO")
            & prices["session_date"].eq(missing_date)
        )
    ].copy()

    paths = write_fixture_files(
        tmp_path,
        prices=prices,
        universe=make_universe(),
        panel=make_year_panel(),
    )

    with pytest.raises(
        PriceQualityAuditError,
        match="critical issues",
    ):
        run_price_quality_audit(
            prices_path=paths["prices"],
            universe_path=paths["universe"],
            year_panel_path=paths["panel"],
            price_manifest_path=paths["price_manifest"],
            ticker_coverage_path=paths["ticker_output"],
            event_coverage_path=paths["event_output"],
            issues_path=paths["issues_output"],
            audit_manifest_path=paths["audit_manifest"],
            fail_on_critical=True,
        )

    assert paths["ticker_output"].exists()
    assert paths["event_output"].exists()
    assert paths["issues_output"].exists()
    assert paths["audit_manifest"].exists()

    manifest = json.loads(
        paths["audit_manifest"].read_text(encoding="utf-8")
    )
    assert manifest["status"] == "FAIL"


def test_allow_critical_returns_failed_audit(
    tmp_path: Path,
) -> None:
    prices = make_prices()
    prices.loc[0, "volume"] = -1
    paths = write_fixture_files(
        tmp_path,
        prices=prices,
        universe=make_universe(),
        panel=make_year_panel(),
    )

    result = run_price_quality_audit(
        prices_path=paths["prices"],
        universe_path=paths["universe"],
        year_panel_path=paths["panel"],
        price_manifest_path=paths["price_manifest"],
        ticker_coverage_path=paths["ticker_output"],
        event_coverage_path=paths["event_output"],
        issues_path=paths["issues_output"],
        audit_manifest_path=paths["audit_manifest"],
        fail_on_critical=False,
    )

    assert result.manifest["status"] == "FAIL"
    assert (
        result.manifest["summary"]["issue_counts"]["critical"]
        >= 1
    )
