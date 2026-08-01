from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

JOLTS_ARCHIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "jolts_releases_2004_2025.csv"
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
    / "macro_events_before_historical_jolts.csv"
)

MAPPED_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_event_map.csv"
)


def load_jolts_archive() -> pd.DataFrame:
    archive = pd.read_csv(
        JOLTS_ARCHIVE_PATH,
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


def test_historical_jolts_archive_exists() -> None:
    assert JOLTS_ARCHIVE_PATH.exists(), (
        "Historical JOLTS archive is missing. Run "
        "`python -m labor_day.ingest_jolts_releases`."
    )


def test_historical_jolts_archive_is_complete() -> None:
    archive = load_jolts_archive()

    assert len(archive) == 260
    assert archive["event_id"].nunique() == 260
    assert archive["reference_period"].nunique() == 260

    assert archive["release_date"].dt.year.min() == 2004
    assert archive["release_date"].dt.year.max() == 2025

    assert archive["reference_period"].min() == "2004-02"
    assert not archive["reference_period"].lt("2004-02").any()


def test_historical_jolts_reference_periods_are_unique() -> None:
    archive = load_jolts_archive()

    duplicated = archive.loc[
        archive["reference_period"].duplicated(keep=False),
        "reference_period",
    ].tolist()

    assert duplicated == []


def test_historical_jolts_time_quality_is_consistent() -> None:
    archive = load_jolts_archive()

    exact_mask = archive["verification_status"].eq(
        "official_release_page_exact_time"
    )
    date_only_mask = archive["verification_status"].eq(
        "official_release_page_date_only"
    )

    assert (exact_mask | date_only_mask).all()
    assert int(exact_mask.sum() + date_only_mask.sum()) == 260

    exact_times = (
        archive.loc[exact_mask, "release_time_et"]
        .astype(str)
        .str.strip()
    )
    date_only_times = (
        archive.loc[date_only_mask, "release_time_et"]
        .astype(str)
        .str.strip()
    )

    assert exact_times.ne("").all()
    assert date_only_times.eq("").all()


def test_registry_contains_all_historical_jolts_rows() -> None:
    archive = load_jolts_archive()
    registry = load_macro_registry()

    historical_registry = registry.loc[
        registry["event_type"].eq("jolts")
        & registry["event_date"].dt.year.between(2004, 2025)
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
        "Pre-JOLTS registry backup is missing."
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


def test_historical_jolts_mapping_count_is_stable() -> None:
    mapped = load_mapped_events()

    historical_jolts = mapped.loc[
        mapped["event_type"].eq("jolts")
        & mapped["event_year"].between(2004, 2025)
    ]

    assert len(historical_jolts) == 40


def test_historical_jolts_mapping_coverage_is_broad() -> None:
    mapped = load_mapped_events()

    historical_jolts = mapped.loc[
        mapped["event_type"].eq("jolts")
        & mapped["event_year"].between(2004, 2025)
    ]

    covered_years = set(
        historical_jolts["event_year"]
    )

    # JOLTS is monthly, but publication dates can legitimately move
    # outside a fixed ±20-session Labor Day window. Require broad
    # historical coverage without assuming every year must map.
    assert len(covered_years) >= 18
    assert min(covered_years) >= 2004
    assert max(covered_years) <= 2025


def test_historical_jolts_mappings_have_no_event_zero() -> None:
    mapped = load_mapped_events()

    historical_jolts = mapped.loc[
        mapped["event_type"].eq("jolts")
        & mapped["event_year"].between(2004, 2025)
    ]

    assert not historical_jolts.empty
    assert not historical_jolts["event_time"].eq(0).any()
    assert historical_jolts["event_time"].between(
        -20,
        20,
    ).all()
