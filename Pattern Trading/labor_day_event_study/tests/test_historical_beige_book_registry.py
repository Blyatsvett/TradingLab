from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

BEIGE_BOOK_ARCHIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "beige_book_releases_1998_2025.csv"
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
    / "macro_events_before_historical_beige_book.csv"
)

MAPPED_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_event_map.csv"
)

EXPECTED_YEARS = set(
    range(1998, 2026)
)

EXPECTED_VERIFICATION_STATUS = (
    "official_archive_date_standard_time"
)


def load_beige_book_archive() -> pd.DataFrame:
    archive = pd.read_csv(
        BEIGE_BOOK_ARCHIVE_PATH,
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


def test_historical_beige_book_archive_exists() -> None:
    assert BEIGE_BOOK_ARCHIVE_PATH.exists(), (
        "Historical Beige Book archive is missing. Run "
        "`python -m labor_day.ingest_beige_book_releases`."
    )


def test_historical_beige_book_archive_is_complete() -> None:
    archive = load_beige_book_archive()

    assert len(archive) == 224
    assert archive["event_id"].nunique() == 224
    assert archive["release_date"].nunique() == 224

    counts_by_year = (
        archive.groupby(
            archive["release_date"].dt.year
        )
        .size()
        .to_dict()
    )

    assert set(counts_by_year) == EXPECTED_YEARS
    assert set(counts_by_year.values()) == {8}


def test_historical_beige_book_time_classification() -> None:
    archive = load_beige_book_archive()

    assert archive["release_time_et"].eq(
        "14:00"
    ).all()

    assert archive["event_timezone"].eq(
        "America/New_York"
    ).all()

    assert archive["verification_status"].eq(
        EXPECTED_VERIFICATION_STATUS
    ).all()

    assert archive["time_source"].eq(
        "official_federal_reserve_standard_release_time"
    ).all()


def test_known_historical_archive_exceptions_are_present() -> None:
    archive = load_beige_book_archive()

    september_2003 = archive.loc[
        archive["release_date"].eq(
            pd.Timestamp("2003-09-03")
        )
    ]

    assert len(september_2003) == 1
    assert september_2003.iloc[0][
        "report_url"
    ].endswith(
        "/20030903/default.htm"
    )
    assert "omits this entry" in september_2003.iloc[0][
        "notes"
    ]

    october_2006 = archive.loc[
        archive["release_date"].eq(
            pd.Timestamp("2006-10-12")
        )
    ]

    assert len(october_2006) == 1
    assert october_2006.iloc[0][
        "release_date"
    ].weekday() == 3


def test_only_documented_release_is_non_wednesday() -> None:
    archive = load_beige_book_archive()

    non_wednesday_dates = set(
        archive.loc[
            archive["release_date"].dt.weekday.ne(2),
            "release_date",
        ].dt.strftime(
            "%Y-%m-%d"
        )
    )

    assert non_wednesday_dates == {
        "2006-10-12"
    }


def test_registry_contains_all_historical_beige_book_rows() -> None:
    archive = load_beige_book_archive()
    registry = load_macro_registry()

    historical_registry = registry.loc[
        registry["event_type"].eq(
            "beige_book"
        )
        & registry["event_date"].dt.year.between(
            1998,
            2025,
        )
    ]

    assert set(archive["event_id"]) == set(
        historical_registry["event_id"]
    )

    assert historical_registry[
        "event_time_et"
    ].eq(
        "14:00"
    ).all()

    assert historical_registry[
        "tier"
    ].eq(
        "tier_2"
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
        "Pre-Beige-Book registry backup is missing."
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


def test_historical_beige_book_mapping_count_is_stable() -> None:
    mapped = load_mapped_events()

    historical_beige_book = mapped.loc[
        mapped["event_type"].eq(
            "beige_book"
        )
        & mapped["event_year"].between(
            1998,
            2025,
        )
    ]

    assert len(
        historical_beige_book
    ) == 31

    assert historical_beige_book[
        "event_id"
    ].nunique() == 31


def test_historical_beige_book_mapping_span_is_complete() -> None:
    mapped = load_mapped_events()

    historical_beige_book = mapped.loc[
        mapped["event_type"].eq(
            "beige_book"
        )
        & mapped["event_year"].between(
            1998,
            2025,
        )
    ]

    covered_years = set(
        historical_beige_book["event_year"]
    )

    assert min(
        covered_years
    ) == 1998
    assert max(
        covered_years
    ) == 2025


def test_historical_beige_book_mappings_have_no_event_zero() -> None:
    mapped = load_mapped_events()

    historical_beige_book = mapped.loc[
        mapped["event_type"].eq(
            "beige_book"
        )
        & mapped["event_year"].between(
            1998,
            2025,
        )
    ]

    assert not historical_beige_book.empty
    assert not historical_beige_book[
        "event_time"
    ].eq(
        0
    ).any()

    assert historical_beige_book[
        "event_time"
    ].between(
        -20,
        20,
    ).all()
