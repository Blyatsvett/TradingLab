from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

UNIVERSE_PATH = PROJECT_ROOT / "config" / "labor_day_universe.csv"
PRICES_PATH = (
    PROJECT_ROOT / "data" / "processed" / "daily_prices.csv"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests" / "daily_prices_manifest.json"
)

EXPECTED_SOURCE = "Yahoo Finance via yfinance"
EXPECTED_PROVIDER_VERSION = "1.5.1"
EXPECTED_START = "1997-01-01"
EXPECTED_END_EXCLUSIVE = "2026-07-23"
EXPECTED_OUTPUT_ROWS = 159_587
EXPECTED_OUTPUT_SHA256 = (
    "c86352e88e77a933a3921a7a054265332f7e1b74eaa82f2285477d82d0ec07ac"
)

EXPECTED_COLUMNS = [
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

EXPECTED_COVERAGE: dict[str, tuple[int, str, str]] = {
    "AN": (7434, "1997-01-02", "2026-07-22"),
    "BKNG": (6869, "1999-03-31", "2026-07-22"),
    "CCL": (7434, "1997-01-02", "2026-07-22"),
    "CHH": (7434, "1997-01-02", "2026-07-22"),
    "DAL": (4835, "2007-05-03", "2026-07-22"),
    "DINO": (7434, "1997-01-02", "2026-07-22"),
    "EXPE": (5283, "2005-07-21", "2026-07-22"),
    "GPI": (7224, "1997-10-30", "2026-07-22"),
    "HLT": (3169, "2013-12-12", "2026-07-22"),
    "IWM": (6576, "2000-05-26", "2026-07-22"),
    "KMX": (7411, "1997-02-04", "2026-07-22"),
    "LAD": (7434, "1997-01-02", "2026-07-22"),
    "LUV": (7434, "1997-01-02", "2026-07-22"),
    "MAR": (7127, "1998-03-23", "2026-07-22"),
    "MPC": (3790, "2011-06-24", "2026-07-22"),
    "PAG": (7434, "1997-01-02", "2026-07-22"),
    "PBF": (3420, "2012-12-13", "2026-07-22"),
    "PSX": (3589, "2012-04-12", "2026-07-22"),
    "RCL": (7434, "1997-01-02", "2026-07-22"),
    "SPY": (7434, "1997-01-02", "2026-07-22"),
    "UAL": (5146, "2006-02-06", "2026-07-22"),
    "VLO": (7434, "1997-01-02", "2026-07-22"),
    "XLE": (6936, "1998-12-22", "2026-07-22"),
    "XLU": (6936, "1998-12-22", "2026-07-22"),
    "XLY": (6936, "1998-12-22", "2026-07-22"),
}

HEX_20 = re.compile(r"^[0-9a-f]{20}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def read_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def read_prices() -> pd.DataFrame:
    return pd.read_csv(
        PRICES_PATH,
        dtype=str,
        keep_default_na=False,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def coverage_from_prices(
    prices: pd.DataFrame,
) -> dict[str, tuple[int, str, str]]:
    result: dict[str, tuple[int, str, str]] = {}
    for ticker, group in prices.groupby("ticker", sort=True):
        dates = group["session_date"].sort_values()
        result[str(ticker)] = (
            len(group),
            str(dates.iloc[0]),
            str(dates.iloc[-1]),
        )
    return result


def test_phase1b_production_artifacts_exist() -> None:
    for path in [
        UNIVERSE_PATH,
        PRICES_PATH,
        MANIFEST_PATH,
    ]:
        assert path.exists(), f"Missing Phase 1B artifact: {path}"


def test_manifest_has_frozen_success_contract() -> None:
    manifest = read_manifest()

    assert manifest["artifact"] == (
        "Labor Day normalized daily prices"
    )
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["status"] == "PASS"
    assert manifest["source"] == EXPECTED_SOURCE
    assert manifest["provider_library"] == "yfinance"
    assert (
        manifest["provider_version"]
        == EXPECTED_PROVIDER_VERSION
    )
    assert (
        manifest["supported_provider_version"]
        == EXPECTED_PROVIDER_VERSION
    )
    assert manifest["failures"] == []


def test_manifest_request_is_frozen() -> None:
    request = read_manifest()["request"]

    assert request["start"] == EXPECTED_START
    assert request["end_exclusive"] == EXPECTED_END_EXCLUSIVE
    assert request["parameters"] == {
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


def test_manifest_universe_hash_matches_current_universe() -> None:
    manifest = read_manifest()
    assert manifest["universe"]["sha256"] == sha256_file(
        UNIVERSE_PATH
    )


def test_normalized_output_hash_and_row_count_are_frozen() -> None:
    manifest = read_manifest()

    assert sha256_file(PRICES_PATH) == EXPECTED_OUTPUT_SHA256
    assert (
        manifest["output"]["sha256"]
        == EXPECTED_OUTPUT_SHA256
    )
    assert manifest["output"]["written"] is True
    assert manifest["output"]["rows"] == EXPECTED_OUTPUT_ROWS


def test_normalized_schema_is_exact_and_ordered() -> None:
    prices = read_prices()
    assert list(prices.columns) == EXPECTED_COLUMNS


def test_normalized_dataset_has_exact_ticker_coverage() -> None:
    prices = read_prices()

    assert len(prices) == EXPECTED_OUTPUT_ROWS
    assert prices["ticker"].nunique() == 25
    assert coverage_from_prices(prices) == EXPECTED_COVERAGE


def test_manifest_row_counts_match_frozen_coverage() -> None:
    manifest = read_manifest()
    expected_counts = {
        ticker: rows
        for ticker, (rows, _, _) in EXPECTED_COVERAGE.items()
    }

    assert manifest["row_counts_by_ticker"] == expected_counts
    assert sum(
        manifest["row_counts_by_ticker"].values()
    ) == EXPECTED_OUTPUT_ROWS


def test_dataset_is_unique_and_sorted_by_ticker_session() -> None:
    prices = read_prices()

    assert not prices.duplicated(
        ["ticker", "session_date"]
    ).any()

    sorted_keys = (
        prices[["ticker", "session_date"]]
        .sort_values(["ticker", "session_date"])
        .reset_index(drop=True)
    )
    actual_keys = prices[
        ["ticker", "session_date"]
    ].reset_index(drop=True)

    pd.testing.assert_frame_equal(
        actual_keys,
        sorted_keys,
        check_dtype=False,
    )


def test_dataset_date_span_matches_exclusive_request() -> None:
    prices = read_prices()

    parsed = pd.to_datetime(
        prices["session_date"],
        format="%Y-%m-%d",
        errors="raise",
    )

    assert parsed.min().date().isoformat() == "1997-01-02"
    assert parsed.max().date().isoformat() == "2026-07-22"
    assert (
        parsed.max().date().isoformat()
        < EXPECTED_END_EXCLUSIVE
    )
    assert prices.groupby("ticker")["session_date"].max().eq(
        "2026-07-22"
    ).all()


def test_provider_and_provenance_fields_are_complete() -> None:
    prices = read_prices()

    assert prices["provider_symbol"].str.strip().ne("").all()
    assert prices["retrieved_utc"].str.strip().ne("").all()
    assert prices["source"].eq(EXPECTED_SOURCE).all()
    assert prices["source_file"].str.strip().ne("").all()
    assert prices["request_hash"].map(
        lambda value: HEX_20.fullmatch(value) is not None
    ).all()
    assert prices["raw_sha256"].map(
        lambda value: HEX_64.fullmatch(value) is not None
    ).all()


def test_each_ticker_uses_one_raw_artifact_identity() -> None:
    prices = read_prices()

    per_ticker = prices.groupby("ticker").agg(
        provider_symbols=("provider_symbol", "nunique"),
        source_files=("source_file", "nunique"),
        request_hashes=("request_hash", "nunique"),
        raw_hashes=("raw_sha256", "nunique"),
        retrieval_times=("retrieved_utc", "nunique"),
    )

    assert per_ticker.eq(1).all().all()


def test_manifest_contains_25_reconciling_raw_artifacts() -> None:
    prices = read_prices()
    manifest = read_manifest()
    artifacts = manifest["raw_artifacts"]

    assert set(artifacts) == set(EXPECTED_COVERAGE)
    assert len(artifacts) == 25

    for ticker, metadata in artifacts.items():
        expected_rows, expected_first, expected_last = (
            EXPECTED_COVERAGE[ticker]
        )
        ticker_rows = prices.loc[
            prices["ticker"].eq(ticker)
        ]

        assert metadata["rows"] == expected_rows
        assert pd.Timestamp(
            metadata["first_session"]
        ).date().isoformat() == expected_first
        assert pd.Timestamp(
            metadata["last_session"]
        ).date().isoformat() == expected_last
        assert metadata["provider_symbol"] == (
            ticker_rows["provider_symbol"].iloc[0]
        )
        assert metadata["request_hash"] == (
            ticker_rows["request_hash"].iloc[0]
        )
        assert metadata["raw_sha256"] == (
            ticker_rows["raw_sha256"].iloc[0]
        )
        assert metadata["retrieved_utc"] == (
            ticker_rows["retrieved_utc"].iloc[0]
        )
        assert metadata["cache_status"] in {
            "downloaded",
            "reused",
        }


def test_raw_cache_files_exist_and_match_manifest_hashes() -> None:
    artifacts = read_manifest()["raw_artifacts"]

    for ticker, metadata in artifacts.items():
        raw_path = Path(metadata["raw_path"])
        metadata_path = Path(metadata["metadata_path"])

        assert raw_path.exists(), (
            f"Missing raw price cache for {ticker}: {raw_path}"
        )
        assert metadata_path.exists(), (
            f"Missing cache metadata for {ticker}: "
            f"{metadata_path}"
        )
        assert sha256_file(raw_path) == metadata["raw_sha256"]


def test_source_file_references_match_manifest_raw_paths() -> None:
    prices = read_prices()
    artifacts = read_manifest()["raw_artifacts"]

    for ticker, metadata in artifacts.items():
        raw_path = Path(metadata["raw_path"]).resolve()
        source_value = prices.loc[
            prices["ticker"].eq(ticker),
            "source_file",
        ].iloc[0]

        source_path = Path(source_value)
        if not source_path.is_absolute():
            source_path = PROJECT_ROOT / source_path

        assert source_path.resolve() == raw_path


def test_observed_continuity_review_cases_are_present() -> None:
    prices = read_prices()

    first_sessions = (
        prices.groupby("ticker")["session_date"].min().to_dict()
    )

    assert first_sessions["DINO"] == "1997-01-02"
    assert first_sessions["PAG"] == "1997-01-02"
    assert first_sessions["BKNG"] == "1999-03-31"

    # Expedia's current Yahoo series starts in 2005. Phase 1C must
    # reconcile this with the earlier Phase 1A eligibility policy.
    assert first_sessions["EXPE"] == "2005-07-21"