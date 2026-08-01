from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "bls_empsit_archive_1998_2025.csv"
)

REGISTRY_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events.csv"
)

MAPPED_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_event_map.csv"
)


def test_historical_empsit_archive_exists() -> None:
    assert ARCHIVE_PATH.exists()


def test_historical_empsit_archive_is_complete() -> None:
    archive = pd.read_csv(
        ARCHIVE_PATH,
        encoding="utf-8-sig",
    )

    dates = pd.to_datetime(
        archive["release_date"],
        errors="raise",
    )

    assert len(archive) == 335
    assert not archive["release_date"].duplicated().any()

    assert dates.dt.year.min() == 1998
    assert dates.dt.year.max() == 2025

    assert archive[
        "release_time_et"
    ].eq("08:30").all()


def test_registry_has_no_duplicate_event_ids() -> None:
    registry = pd.read_csv(
        REGISTRY_PATH,
        encoding="utf-8-sig",
    )

    assert not registry[
        "event_id"
    ].duplicated().any()


def test_registry_contains_all_historical_empsit_rows() -> None:
    registry = pd.read_csv(
        REGISTRY_PATH,
        encoding="utf-8-sig",
    )

    dates = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )

    historical = registry.loc[
        registry["event_type"].eq(
            "employment_situation"
        )
        & dates.dt.year.between(
            1998,
            2025,
        )
    ]

    assert len(historical) == 335

    assert historical[
        "verification_status"
    ].eq("official_archive").all()

    assert historical[
        "tier"
    ].eq("tier_1").all()


def test_2026_scheduled_empsit_is_preserved() -> None:
    registry = pd.read_csv(
        REGISTRY_PATH,
        encoding="utf-8-sig",
    )

    forward_event = registry.loc[
        registry["event_id"].eq(
            "BLS_EMPSIT_2026_09_04"
        )
    ]

    assert len(forward_event) == 1

    row = forward_event.iloc[0]

    assert row["event_date"] == "2026-09-04"
    assert row["event_time_et"] == "08:30"
    assert (
        row["verification_status"]
        == "official_schedule"
    )


def test_every_historical_labor_day_has_empsit_mapping() -> None:
    mapped = pd.read_csv(
        MAPPED_EVENTS_PATH,
        encoding="utf-8-sig",
    )

    historical = mapped.loc[
        mapped["event_type"].eq(
            "employment_situation"
        )
        & mapped["event_year"].between(
            1998,
            2025,
        )
    ]

    expected_years = set(
        range(1998, 2026)
    )

    actual_years = set(
        historical["event_year"]
        .astype(int)
    )

    assert actual_years == expected_years

    assert len(historical) >= len(
        expected_years
    )


def test_historical_empsit_mapping_has_no_event_zero() -> None:
    mapped = pd.read_csv(
        MAPPED_EVENTS_PATH,
        encoding="utf-8-sig",
    )

    historical = mapped.loc[
        mapped["event_type"].eq(
            "employment_situation"
        )
        & mapped["event_year"].between(
            1998,
            2025,
        )
    ]

    assert not historical[
        "event_time"
    ].eq(0).any()