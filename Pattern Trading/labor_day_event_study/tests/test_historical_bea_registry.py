from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BEA_ARCHIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "bea_gdp_pio_releases_1998_2025.csv"
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
    / "macro_events_before_historical_bea.csv"
)

MAPPED_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_event_map.csv"
)

BEA_EVENT_TYPES = {
    "gdp",
    "personal_income_outlays",
}


def load_bea_archive() -> pd.DataFrame:
    archive = pd.read_csv(
        BEA_ARCHIVE_PATH,
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


def test_historical_bea_archive_exists() -> None:
    assert BEA_ARCHIVE_PATH.exists(), (
        "Historical BEA archive is missing. Run "
        "`python -m labor_day.ingest_bea_releases`."
    )


def test_historical_bea_archive_is_complete() -> None:
    archive = load_bea_archive()

    assert len(archive) == 659
    assert archive["event_id"].nunique() == 659

    assert archive["series"].value_counts().to_dict() == {
        "gdp": 332,
        "personal_income_outlays": 327,
    }

    assert archive["release_date"].dt.year.min() == 1998
    assert archive["release_date"].dt.year.max() == 2025


def test_every_historical_year_contains_both_bea_series() -> None:
    archive = load_bea_archive()

    for year in range(1998, 2026):
        year_series = set(
            archive.loc[
                archive["release_date"].dt.year.eq(year),
                "series",
            ]
        )
        assert year_series == BEA_EVENT_TYPES, (
            f"Unexpected BEA series coverage for {year}: "
            f"{sorted(year_series)}"
        )


def test_historical_bea_time_quality_counts() -> None:
    archive = load_bea_archive()

    exact_mask = archive["verification_status"].eq(
        "official_release_page_exact_time"
    )
    exact_count = int(exact_mask.sum())
    date_only_count = int((~exact_mask).sum())

    assert exact_count == 653
    assert date_only_count == 6
    assert exact_count + date_only_count == 659

    exact_times = (
        archive.loc[exact_mask, "release_time_et"]
        .astype(str)
        .str.strip()
    )
    date_only_times = (
        archive.loc[~exact_mask, "release_time_et"]
        .astype(str)
        .str.strip()
    )

    assert exact_times.ne("").all()
    assert date_only_times.eq("").all()

    assert set(
        archive.loc[
            ~exact_mask,
            "verification_status",
        ]
    ).issubset(
        {
            "official_release_page_date_only",
            "official_archive_date_only",
        }
    )


def test_registry_contains_all_historical_bea_rows() -> None:
    archive = load_bea_archive()
    registry = load_macro_registry()

    historical_registry = registry.loc[
        registry["event_type"].isin(BEA_EVENT_TYPES)
        & registry["event_date"].dt.year.between(1998, 2025)
    ]

    assert set(archive["event_id"]) == set(
        historical_registry["event_id"]
    )


def test_registry_has_no_duplicate_event_ids() -> None:
    registry = load_macro_registry()

    duplicated = registry.loc[
        registry["event_id"].duplicated(keep=False),
        "event_id",
    ].tolist()

    assert duplicated == []


def test_all_preimport_2026_rows_are_preserved() -> None:
    assert PRE_IMPORT_REGISTRY_PATH.exists(), (
        "Pre-BEA registry backup is missing."
    )

    before = load_macro_registry(
        PRE_IMPORT_REGISTRY_PATH
    )
    after = load_macro_registry()

    before_2026 = before.loc[
        before["event_date"].dt.year.eq(2026)
    ]
    after_2026_ids = set(
        after.loc[
            after["event_date"].dt.year.eq(2026),
            "event_id",
        ]
    )

    assert not before_2026.empty
    assert set(before_2026["event_id"]).issubset(
        after_2026_ids
    )


def test_historical_bea_mapping_count_is_stable() -> None:
    mapped = load_mapped_events()

    historical_bea = mapped.loc[
        mapped["event_type"].isin(BEA_EVENT_TYPES)
        & mapped["event_year"].between(1998, 2025)
    ]

    assert len(historical_bea) == 111
    assert set(historical_bea["event_type"]) == (
        BEA_EVENT_TYPES
    )


def test_bea_mapping_coverage_is_broad() -> None:
    mapped = load_mapped_events()

    historical_bea = mapped.loc[
        mapped["event_type"].isin(BEA_EVENT_TYPES)
        & mapped["event_year"].between(1998, 2025)
    ]

    # Every Labor Day year should contain at least one BEA release
    # inside the ±20-session window. Individual series need not
    # appear every year because their monthly/quarterly release dates
    # can legitimately fall outside that fixed window.
    assert set(historical_bea["event_year"]) == set(
        range(1998, 2026)
    )

    years_by_series = (
        historical_bea.groupby("event_type")["event_year"]
        .nunique()
        .to_dict()
    )

    assert set(years_by_series) == BEA_EVENT_TYPES
    assert all(
        covered_years >= 20
        for covered_years in years_by_series.values()
    )


def test_historical_bea_mappings_have_no_event_zero() -> None:
    mapped = load_mapped_events()

    historical_bea = mapped.loc[
        mapped["event_type"].isin(BEA_EVENT_TYPES)
        & mapped["event_year"].between(1998, 2025)
    ]

    assert not historical_bea.empty
    assert not historical_bea["event_time"].eq(0).any()
    assert historical_bea["event_time"].between(
        -20,
        20,
    ).all()