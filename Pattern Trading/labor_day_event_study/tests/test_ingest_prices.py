from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from labor_day.ingest_prices import (
    NORMALIZED_COLUMNS,
    RAW_COLUMNS,
    REQUEST_PARAMETERS,
    SOURCE_NAME,
    SUPPORTED_YFINANCE_VERSION,
    PriceIngestionError,
    build_normalized_prices,
    canonicalize_download_frame,
    default_exclusive_end_date,
    download_with_retries,
    find_cached_artifact,
    ingest_prices,
    normalized_rows_from_artifact,
    request_identity,
    request_payload,
    safe_filename_component,
    sha256_file,
    validate_date_range,
    validate_yfinance_version,
    write_cache_artifact,
)


def provider_frame(
    *,
    offset: float = 0.0,
    multiindex: bool = False,
    tz: str | None = None,
) -> pd.DataFrame:
    index = pd.date_range(
        "2020-08-28",
        periods=3,
        freq="B",
        tz=tz,
        name="Date",
    )
    frame = pd.DataFrame(
        {
            "Open": [10.0 + offset, 11.0 + offset, 12.0 + offset],
            "High": [11.0 + offset, 12.0 + offset, 13.0 + offset],
            "Low": [9.0 + offset, 10.0 + offset, 11.0 + offset],
            "Close": [10.5 + offset, 11.5 + offset, 12.5 + offset],
            "Adj Close": [10.4 + offset, 11.4 + offset, 12.4 + offset],
            "Volume": [100, 200, 300],
            "Dividends": [0.0, 0.2, 0.0],
            "Stock Splits": [0.0, 0.0, 2.0],
            "Capital Gains": [0.0, 0.0, 0.0],
        },
        index=index,
    )
    if multiindex:
        frame.columns = pd.MultiIndex.from_tuples(
            [(column, "SPY") for column in frame.columns]
        )
    return frame


def mini_universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "AAA", "provider_symbol": "AAA"},
            {"ticker": "BBB", "provider_symbol": "BBB"},
        ]
    )


def write_universe_file(path: Path) -> None:
    path.write_text("ticker,provider_symbol\nAAA,AAA\nBBB,BBB\n")


def silent(_: str) -> None:
    return None


def test_default_end_uses_new_york_date() -> None:
    instant = datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc)
    assert default_exclusive_end_date(instant) == "2026-07-23"


def test_date_range_validation() -> None:
    validate_date_range("1997-01-01", "2026-07-23")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        validate_date_range("01-01-1997", "2026-07-23")
    with pytest.raises(ValueError, match="must precede"):
        validate_date_range("2026-07-23", "2026-07-23")


def test_yfinance_version_is_pinned() -> None:
    validate_yfinance_version(SUPPORTED_YFINANCE_VERSION)
    with pytest.raises(PriceIngestionError, match="requires"):
        validate_yfinance_version("0.2.66")


def test_request_parameters_are_frozen() -> None:
    assert REQUEST_PARAMETERS == {
        "interval": "1d",
        "auto_adjust": False,
        "back_adjust": False,
        "repair": False,
        "actions": True,
        "threads": False,
        "ignore_tz": False,
        "keepna": True,
        "prepost": False,
        "rounding": False,
        "multi_level_index": False,
    }


def test_request_identity_is_deterministic_and_sensitive() -> None:
    kwargs = {
        "ticker": "SPY",
        "provider_symbol": "SPY",
        "start": "1997-01-01",
        "end": "2026-07-23",
        "provider_version": SUPPORTED_YFINANCE_VERSION,
    }
    first = request_identity(**kwargs)
    second = request_identity(**kwargs)
    assert first == second
    assert len(first) == 20

    changed = dict(kwargs)
    changed["end"] = "2026-07-24"
    assert request_identity(**changed) != first


def test_request_payload_records_exclusive_end() -> None:
    payload = request_payload(
        ticker="SPY",
        provider_symbol="SPY",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
    )
    assert payload["end_exclusive"] == "2026-07-23"
    assert payload["parameters"]["auto_adjust"] is False
    assert payload["parameters"]["actions"] is True


def test_safe_filename_component() -> None:
    assert safe_filename_component("BRK.B") == "BRK.B"
    assert safe_filename_component("A/B C") == "A_B_C"
    with pytest.raises(ValueError, match="blank"):
        safe_filename_component("   ")


def test_standard_provider_frame_is_canonicalized() -> None:
    raw = canonicalize_download_frame(provider_frame())
    assert list(raw.columns) == RAW_COLUMNS
    assert len(raw) == 3
    assert raw["dividend"].tolist() == [0.0, 0.2, 0.0]
    assert raw["split"].tolist() == [0.0, 0.0, 2.0]


def test_multiindex_provider_columns_are_supported() -> None:
    raw = canonicalize_download_frame(
        provider_frame(multiindex=True)
    )
    assert list(raw.columns) == RAW_COLUMNS
    assert raw["adjusted_close"].tolist() == [10.4, 11.4, 12.4]


def test_timezone_aware_sessions_are_preserved() -> None:
    raw = canonicalize_download_frame(
        provider_frame(tz="America/New_York")
    )
    assert raw["session_datetime"].str.contains("-04:00").all()


def test_optional_actions_are_filled_with_zero() -> None:
    frame = provider_frame().drop(
        columns=["Dividends", "Stock Splits", "Capital Gains"]
    )
    raw = canonicalize_download_frame(frame)
    assert raw["dividend"].eq(0.0).all()
    assert raw["split"].eq(0.0).all()
    assert raw["capital_gain"].eq(0.0).all()


def test_empty_provider_frame_is_rejected() -> None:
    with pytest.raises(PriceIngestionError, match="no price rows"):
        canonicalize_download_frame(pd.DataFrame())


def test_missing_required_provider_column_is_rejected() -> None:
    frame = provider_frame().drop(columns="Adj Close")
    with pytest.raises(PriceIngestionError, match="adjusted_close"):
        canonicalize_download_frame(frame)


def test_duplicate_provider_session_is_rejected() -> None:
    frame = provider_frame()
    frame.index = [frame.index[0], frame.index[0], frame.index[2]]
    with pytest.raises(PriceIngestionError, match="duplicate sessions"):
        canonicalize_download_frame(frame)


def test_download_retries_then_succeeds() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky(symbol: str, start: str, end: str, timeout: float) -> pd.DataFrame:
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("temporary")
        return provider_frame()

    result = download_with_retries(
        provider_symbol="SPY",
        start="1997-01-01",
        end="2026-07-23",
        timeout=30,
        max_attempts=3,
        download_func=flaky,
        sleep_func=sleeps.append,
    )
    assert len(result) == 3
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_download_retry_failure_is_consolidated() -> None:
    def broken(symbol: str, start: str, end: str, timeout: float) -> pd.DataFrame:
        raise RuntimeError("down")

    with pytest.raises(PriceIngestionError, match="after 2 attempt"):
        download_with_retries(
            provider_symbol="SPY",
            start="1997-01-01",
            end="2026-07-23",
            timeout=30,
            max_attempts=2,
            download_func=broken,
            sleep_func=lambda _: None,
        )


def test_cache_artifact_is_content_addressed_and_reusable(
    tmp_path: Path,
) -> None:
    raw = canonicalize_download_frame(provider_frame())
    request = request_payload(
        ticker="SPY",
        provider_symbol="SPY",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
    )
    identity = request_identity(
        ticker="SPY",
        provider_symbol="SPY",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
    )
    artifact = write_cache_artifact(
        cache_dir=tmp_path,
        ticker="SPY",
        provider_symbol="SPY",
        request_hash=identity,
        request=request,
        raw=raw,
        retrieved_utc="2026-07-23T10:00:00+00:00",
    )
    assert artifact.raw_path.exists()
    assert artifact.metadata_path.exists()
    assert sha256_file(artifact.raw_path) == artifact.raw_sha256

    reused = find_cached_artifact(
        cache_dir=tmp_path,
        ticker="SPY",
        request_hash=identity,
    )
    assert reused is not None
    assert reused.cache_status == "reused"
    assert reused.raw_sha256 == artifact.raw_sha256


def test_changed_content_creates_a_new_cache_artifact(
    tmp_path: Path,
) -> None:
    request = request_payload(
        ticker="SPY",
        provider_symbol="SPY",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
    )
    identity = request_identity(
        ticker="SPY",
        provider_symbol="SPY",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
    )
    first = write_cache_artifact(
        cache_dir=tmp_path,
        ticker="SPY",
        provider_symbol="SPY",
        request_hash=identity,
        request=request,
        raw=canonicalize_download_frame(provider_frame()),
        retrieved_utc="2026-07-23T10:00:00+00:00",
    )
    second = write_cache_artifact(
        cache_dir=tmp_path,
        ticker="SPY",
        provider_symbol="SPY",
        request_hash=identity,
        request=request,
        raw=canonicalize_download_frame(provider_frame(offset=1.0)),
        retrieved_utc="2026-07-23T11:00:00+00:00",
    )
    assert first.raw_path != second.raw_path
    assert len(list(tmp_path.glob("*.csv"))) == 2


def test_normalized_rows_include_provenance(tmp_path: Path) -> None:
    raw = canonicalize_download_frame(provider_frame())
    request = request_payload(
        ticker="SPY",
        provider_symbol="SPY",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
    )
    identity = request_identity(
        ticker="SPY",
        provider_symbol="SPY",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
    )
    artifact = write_cache_artifact(
        cache_dir=tmp_path,
        ticker="SPY",
        provider_symbol="SPY",
        request_hash=identity,
        request=request,
        raw=raw,
        retrieved_utc="2026-07-23T10:00:00+00:00",
    )
    normalized = normalized_rows_from_artifact(artifact)
    assert list(normalized.columns) == NORMALIZED_COLUMNS
    assert normalized["ticker"].eq("SPY").all()
    assert normalized["source"].eq(SOURCE_NAME).all()
    assert normalized["raw_sha256"].eq(artifact.raw_sha256).all()
    assert normalized["session_date"].tolist() == [
        "2020-08-28",
        "2020-08-31",
        "2020-09-01",
    ]


def test_build_normalized_prices_sorts_tickers(tmp_path: Path) -> None:
    artifacts = []
    for ticker, offset in [("BBB", 1.0), ("AAA", 0.0)]:
        request = request_payload(
            ticker=ticker,
            provider_symbol=ticker,
            start="1997-01-01",
            end="2026-07-23",
            provider_version=SUPPORTED_YFINANCE_VERSION,
        )
        identity = request_identity(
            ticker=ticker,
            provider_symbol=ticker,
            start="1997-01-01",
            end="2026-07-23",
            provider_version=SUPPORTED_YFINANCE_VERSION,
        )
        artifacts.append(
            write_cache_artifact(
                cache_dir=tmp_path,
                ticker=ticker,
                provider_symbol=ticker,
                request_hash=identity,
                request=request,
                raw=canonicalize_download_frame(
                    provider_frame(offset=offset)
                ),
                retrieved_utc="2026-07-23T10:00:00+00:00",
            )
        )
    prices = build_normalized_prices(artifacts)
    assert prices["ticker"].tolist()[:3] == ["AAA"] * 3
    assert prices["ticker"].tolist()[3:] == ["BBB"] * 3


def test_full_ingestion_writes_output_and_manifest(
    tmp_path: Path,
) -> None:
    universe_path = tmp_path / "universe.csv"
    write_universe_file(universe_path)
    calls: list[str] = []

    def downloader(symbol: str, start: str, end: str, timeout: float) -> pd.DataFrame:
        calls.append(symbol)
        return provider_frame(offset=0 if symbol == "AAA" else 10)

    result = ingest_prices(
        universe_path=universe_path,
        universe=mini_universe(),
        cache_dir=tmp_path / "cache",
        output_path=tmp_path / "daily_prices.csv",
        manifest_path=tmp_path / "manifest.json",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
        download_func=downloader,
        sleep_func=lambda _: None,
        request_delay=0,
        log_func=silent,
    )

    assert calls == ["AAA", "BBB"]
    assert len(result.prices) == 6
    assert result.manifest["status"] == "PASS"
    assert result.manifest["output"]["rows"] == 6
    assert result.manifest["row_counts_by_ticker"] == {
        "AAA": 3,
        "BBB": 3,
    }
    assert (tmp_path / "daily_prices.csv").exists()
    assert (tmp_path / "manifest.json").exists()
    assert result.manifest["output"]["sha256"] == sha256_file(
        tmp_path / "daily_prices.csv"
    )


def test_second_run_reuses_cache_without_downloading(
    tmp_path: Path,
) -> None:
    universe_path = tmp_path / "universe.csv"
    write_universe_file(universe_path)
    calls: list[str] = []

    def downloader(symbol: str, start: str, end: str, timeout: float) -> pd.DataFrame:
        calls.append(symbol)
        return provider_frame()

    kwargs = dict(
        universe_path=universe_path,
        universe=mini_universe(),
        cache_dir=tmp_path / "cache",
        output_path=tmp_path / "daily_prices.csv",
        manifest_path=tmp_path / "manifest.json",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
        download_func=downloader,
        sleep_func=lambda _: None,
        request_delay=0,
        log_func=silent,
    )
    first = ingest_prices(**kwargs)
    first_hash = sha256_file(tmp_path / "daily_prices.csv")
    second = ingest_prices(**kwargs)
    second_hash = sha256_file(tmp_path / "daily_prices.csv")

    assert calls == ["AAA", "BBB"]
    assert first_hash == second_hash
    assert all(
        artifact.cache_status == "reused"
        for artifact in second.artifacts
    )
    assert first.prices.equals(second.prices)


def test_refresh_downloads_again_and_retains_old_cache(
    tmp_path: Path,
) -> None:
    universe_path = tmp_path / "universe.csv"
    write_universe_file(universe_path)
    generation = {"value": 0}

    def downloader(symbol: str, start: str, end: str, timeout: float) -> pd.DataFrame:
        return provider_frame(offset=float(generation["value"]))

    kwargs = dict(
        universe_path=universe_path,
        universe=mini_universe(),
        cache_dir=tmp_path / "cache",
        output_path=tmp_path / "daily_prices.csv",
        manifest_path=tmp_path / "manifest.json",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
        download_func=downloader,
        sleep_func=lambda _: None,
        request_delay=0,
        log_func=silent,
    )
    ingest_prices(**kwargs)
    generation["value"] = 5
    refreshed = ingest_prices(**kwargs, refresh=True)

    assert all(
        artifact.cache_status == "downloaded"
        for artifact in refreshed.artifacts
    )
    assert len(list((tmp_path / "cache").glob("*.csv"))) == 4


def test_failure_manifest_is_written_and_successful_cache_retained(
    tmp_path: Path,
) -> None:
    universe_path = tmp_path / "universe.csv"
    write_universe_file(universe_path)

    def downloader(symbol: str, start: str, end: str, timeout: float) -> pd.DataFrame:
        if symbol == "BBB":
            raise RuntimeError("provider unavailable")
        return provider_frame()

    with pytest.raises(PriceIngestionError, match="1 ticker"):
        ingest_prices(
            universe_path=universe_path,
            universe=mini_universe(),
            cache_dir=tmp_path / "cache",
            output_path=tmp_path / "daily_prices.csv",
            manifest_path=tmp_path / "manifest.json",
            start="1997-01-01",
            end="2026-07-23",
            provider_version=SUPPORTED_YFINANCE_VERSION,
            download_func=downloader,
            sleep_func=lambda _: None,
            request_delay=0,
            max_attempts=2,
            log_func=silent,
        )

    manifest = json.loads(
        (tmp_path / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "FAIL"
    assert manifest["output"]["written"] is False
    assert len(manifest["failures"]) == 1
    assert manifest["failures"][0]["ticker"] == "BBB"
    assert "AAA" in manifest["raw_artifacts"]
    assert len(list((tmp_path / "cache").glob("AAA__*.csv"))) == 1


def test_missing_universe_columns_are_rejected(tmp_path: Path) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text("ticker\nAAA\n")
    with pytest.raises(PriceIngestionError, match="provider_symbol"):
        ingest_prices(
            universe_path=universe_path,
            universe=pd.DataFrame([{"ticker": "AAA"}]),
            cache_dir=tmp_path / "cache",
            output_path=tmp_path / "out.csv",
            manifest_path=tmp_path / "manifest.json",
            start="1997-01-01",
            end="2026-07-23",
            provider_version=SUPPORTED_YFINANCE_VERSION,
            download_func=lambda *args: provider_frame(),
            sleep_func=lambda _: None,
            request_delay=0,
            log_func=silent,
        )


def test_duplicate_universe_ticker_is_rejected(tmp_path: Path) -> None:
    universe_path = tmp_path / "universe.csv"
    write_universe_file(universe_path)
    duplicated = pd.DataFrame(
        [
            {"ticker": "AAA", "provider_symbol": "AAA"},
            {"ticker": "AAA", "provider_symbol": "AAA"},
        ]
    )
    with pytest.raises(PriceIngestionError, match="duplicate"):
        ingest_prices(
            universe_path=universe_path,
            universe=duplicated,
            cache_dir=tmp_path / "cache",
            output_path=tmp_path / "out.csv",
            manifest_path=tmp_path / "manifest.json",
            start="1997-01-01",
            end="2026-07-23",
            provider_version=SUPPORTED_YFINANCE_VERSION,
            download_func=lambda *args: provider_frame(),
            sleep_func=lambda _: None,
            request_delay=0,
            log_func=silent,
        )


def test_invalid_runtime_arguments_are_rejected(tmp_path: Path) -> None:
    universe_path = tmp_path / "universe.csv"
    write_universe_file(universe_path)
    common = dict(
        universe_path=universe_path,
        universe=mini_universe(),
        cache_dir=tmp_path / "cache",
        output_path=tmp_path / "out.csv",
        manifest_path=tmp_path / "manifest.json",
        start="1997-01-01",
        end="2026-07-23",
        provider_version=SUPPORTED_YFINANCE_VERSION,
        download_func=lambda *args: provider_frame(),
        sleep_func=lambda _: None,
        log_func=silent,
    )
    with pytest.raises(ValueError, match="timeout"):
        ingest_prices(**common, timeout=0, request_delay=0)
    with pytest.raises(ValueError, match="request_delay"):
        ingest_prices(**common, request_delay=-1)
    with pytest.raises(ValueError, match="max_attempts"):
        ingest_prices(**common, max_attempts=0, request_delay=0)
