from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TRADE_ARCHIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "international_trade_releases_1998_2025.csv"
)

MACRO_REGISTRY_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events.csv"
)

PRE_IMPORT_REGISTRY_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_international_trade.csv"
)

MAPPED_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_event_map.csv"
)

EXPECTED_REFERENCE_START = "1997-11"
EXPECTED_REFERENCE_END = "2025-09"
EXPECTED_ARCHIVE_ROWS = 335
EXPECTED_HISTORICAL_MAPPED_EVENTS = 48

EXPECTED_CENSUS_FALLBACKS = {
    "2006-06": (
        "2006-08-10",
        "https://www.census.gov/foreign-trade/"
        "Press-Release/ft900/ft900_0606.pdf",
    ),
    "2006-12": (
        "2007-02-13",
        "https://www.census.gov/foreign-trade/"
        "Press-Release/ft900/ft900_0612.pdf",
    ),
    "2008-06": (
        "2008-08-12",
        "https://www.census.gov/foreign-trade/"
        "Press-Release/ft900/ft900_0806.pdf",
    ),
    "2011-04": (
        "2011-06-09",
        "https://www.census.gov/foreign-trade/"
        "Press-Release/ft900/ft900_1104.pdf",
    ),
    "2012-04": (
        "2012-06-08",
        "https://www.census.gov/foreign-trade/"
        "Press-Release/ft900/ft900_1204.pdf",
    ),
    "2013-04": (
        "2013-06-04",
        "https://www.census.gov/foreign-trade/"
        "Press-Release/ft900/ft900_1304.pdf",
    ),
}


def load_trade_archive() -> pd.DataFrame:
    archive = pd.read_csv(
        TRADE_ARCHIVE_PATH,
        dtype=str,
        keep_default_na=False,
    )
    archive["release_date"] = pd.to_datetime(
        archive["release_date"],
        errors="raise",
    )
    return archive


def load_macro_registry(
    path: Path = MACRO_REGISTRY_PATH,
) -> pd.DataFrame:
    registry = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
    )
    registry["event_date"] = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )
    return registry


def load_mapped_events() -> pd.DataFrame:
    mapped = pd.read_csv(
        MAPPED_EVENTS_PATH,
        dtype=str,
        keep_default_na=False,
    )
    mapped["event_time"] = pd.to_numeric(
        mapped["event_time"],
        errors="raise",
    ).astype(int)
    mapped["event_year"] = pd.to_numeric(
        mapped["event_year"],
        errors="raise",
    ).astype(int)
    return mapped


def historical_trade_mappings() -> pd.DataFrame:
    archive = load_trade_archive()
    mapped = load_mapped_events()

    historical_ids = set(
        archive["event_id"].astype(str)
    )

    return mapped.loc[
        mapped["event_id"].astype(str).isin(
            historical_ids
        )
    ].copy()


def test_historical_international_trade_archive_exists() -> None:
    assert TRADE_ARCHIVE_PATH.exists(), (
        "Historical international-trade archive is missing. Run "
        "`python -m labor_day.ingest_international_trade_releases`."
    )


def test_historical_international_trade_archive_is_complete() -> None:
    archive = load_trade_archive()

    assert len(archive) == EXPECTED_ARCHIVE_ROWS
    assert archive["event_id"].nunique() == EXPECTED_ARCHIVE_ROWS
    assert archive["reference_period"].nunique() == EXPECTED_ARCHIVE_ROWS

    ordered_periods = sorted(
        archive["reference_period"].tolist()
    )

    assert ordered_periods[0] == EXPECTED_REFERENCE_START
    assert ordered_periods[-1] == EXPECTED_REFERENCE_END

    expected_periods = [
        str(period)
        for period in pd.period_range(
            EXPECTED_REFERENCE_START,
            EXPECTED_REFERENCE_END,
            freq="M",
        )
    ]

    assert ordered_periods == expected_periods


def test_publication_year_counts_are_stable() -> None:
    archive = load_trade_archive()

    counts = (
        archive.groupby(
            archive["release_date"].dt.year
        )
        .size()
        .to_dict()
    )

    assert set(counts) == set(range(1998, 2026))

    for year in range(1998, 2025):
        assert counts[year] == 12

    assert counts[2025] == 11


def test_all_releases_have_exact_0830_time_verification() -> None:
    archive = load_trade_archive()

    assert archive["release_time_et"].eq(
        "08:30"
    ).all()

    assert archive["event_timezone"].eq(
        "America/New_York"
    ).all()

    assert archive["verification_status"].eq(
        "official_release_page_exact_time"
    ).all()

    assert set(archive["time_source"]) == {
        "official_bea_release_page",
        "official_census_ft900_pdf",
    }

    assert archive["time_source"].eq(
        "official_census_ft900_pdf"
    ).sum() == 6


def test_documented_census_fallbacks_are_exact() -> None:
    archive = load_trade_archive()

    fallback_rows = archive.loc[
        archive["time_source"].eq(
            "official_census_ft900_pdf"
        )
    ]

    assert set(
        fallback_rows["reference_period"]
    ) == set(EXPECTED_CENSUS_FALLBACKS)

    for reference_period, (
        expected_date,
        expected_url,
    ) in EXPECTED_CENSUS_FALLBACKS.items():
        row = fallback_rows.loc[
            fallback_rows["reference_period"].eq(
                reference_period
            )
        ]

        assert len(row) == 1
        assert row.iloc[0]["release_date"].strftime(
            "%Y-%m-%d"
        ) == expected_date
        assert row.iloc[0]["release_url"] == expected_url


def test_every_release_uses_an_approved_official_source() -> None:
    archive = load_trade_archive()

    expected_census_urls = {
        values[1]
        for values in EXPECTED_CENSUS_FALLBACKS.values()
    }

    for row in archive.itertuples(index=False):
        parsed = urlparse(row.release_url)
        host = parsed.netloc.lower()

        if host in {"bea.gov", "www.bea.gov"}:
            assert (
                parsed.path.startswith("/news/")
                or parsed.path.startswith("/index.php/news/")
            )
            continue

        assert host in {"census.gov", "www.census.gov"}
        assert row.release_url in expected_census_urls
        assert (
            row.reference_period
            in EXPECTED_CENSUS_FALLBACKS
        )


def test_registry_contains_exact_historical_trade_archive() -> None:
    archive = load_trade_archive()
    registry = load_macro_registry()

    historical_registry = registry.loc[
        registry["event_type"].eq(
            "international_trade"
        )
        & registry["event_date"].dt.year.between(
            1998,
            2025,
        )
    ]

    assert len(historical_registry) == EXPECTED_ARCHIVE_ROWS
    assert set(historical_registry["event_id"]) == set(
        archive["event_id"]
    )

    assert historical_registry["event_time_et"].eq(
        "08:30"
    ).all()
    assert historical_registry["event_timezone"].eq(
        "America/New_York"
    ).all()
    assert historical_registry["source"].eq(
        "Census/BEA"
    ).all()
    assert historical_registry["tier"].eq(
        "tier_1"
    ).all()
    assert historical_registry["verification_status"].eq(
        "official_release_page_exact_time"
    ).all()


def test_registry_has_no_duplicate_event_ids() -> None:
    registry = load_macro_registry()

    duplicated = registry.loc[
        registry["event_id"].duplicated(
            keep=False
        ),
        "event_id",
    ].tolist()

    assert duplicated == []


def test_all_preimport_2026_rows_are_preserved() -> None:
    assert PRE_IMPORT_REGISTRY_PATH.exists(), (
        "Pre-international-trade registry backup is missing."
    )

    before = load_macro_registry(
        PRE_IMPORT_REGISTRY_PATH
    )
    after = load_macro_registry()

    before_2026 = before.loc[
        before["event_date"].dt.year.eq(
            2026
        )
    ]

    after_2026_ids = set(
        after.loc[
            after["event_date"].dt.year.eq(
                2026
            ),
            "event_id",
        ]
    )

    assert not before_2026.empty
    assert set(
        before_2026["event_id"]
    ).issubset(
        after_2026_ids
    )


def test_historical_trade_mapping_count_is_stable() -> None:
    historical = historical_trade_mappings()

    assert len(historical) == EXPECTED_HISTORICAL_MAPPED_EVENTS
    assert (
        historical["event_id"].nunique()
        == EXPECTED_HISTORICAL_MAPPED_EVENTS
    )


def test_historical_trade_mapping_span_is_stable() -> None:
    historical = historical_trade_mappings()

    assert not historical.empty
    assert historical["event_year"].min() == 1998
    assert historical["event_year"].max() == 2025


def test_historical_trade_mappings_are_inside_event_grid() -> None:
    historical = historical_trade_mappings()

    assert not historical.empty
    assert not historical["event_time"].eq(0).any()
    assert historical["event_time"].between(
        -20,
        20,
    ).all()
