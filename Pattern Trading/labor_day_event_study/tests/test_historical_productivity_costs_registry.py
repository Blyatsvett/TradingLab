from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "productivity_costs_releases_1998_2025.csv"
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
    / "macro_events_before_historical_productivity_costs.csv"
)

MAPPED_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_event_map.csv"
)

EXPECTED_ARCHIVE_ROWS = 222
EXPECTED_PRELIMINARY_ROWS = 111
EXPECTED_REVISED_ROWS = 111
EXPECTED_0830_ROWS = 208
EXPECTED_1000_ROWS = 14
EXPECTED_REFERENCE_START = "1997-Q4"
EXPECTED_REFERENCE_END = "2025-Q2"
EXPECTED_FIRST_RELEASE_DATE = "1998-02-10"
EXPECTED_LAST_RELEASE_DATE = "2025-09-04"
EXPECTED_HISTORICAL_MAPPED_EVENTS = 53
EXPECTED_EVENT_TYPE = "productivity_costs"
EXPECTED_VERIFICATION_STATUS = "official_release_page_exact_time"
EXPECTED_TIME_SOURCE = "official_bls_release_header"


def load_archive() -> pd.DataFrame:
    archive = pd.read_csv(
        ARCHIVE_PATH,
        dtype=str,
        keep_default_na=False,
    )
    archive["release_date"] = pd.to_datetime(
        archive["release_date"],
        errors="raise",
    )
    return archive


def load_registry(
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


def historical_productivity_mappings() -> pd.DataFrame:
    archive = load_archive()
    mapped = load_mapped_events()
    archive_ids = set(archive["event_id"].astype(str))

    return mapped.loc[
        mapped["event_id"].astype(str).isin(archive_ids)
    ].copy()


def quarter_index(reference_period: str) -> int:
    year_text, quarter_text = reference_period.split("-Q")
    return int(year_text) * 4 + int(quarter_text) - 1


def expected_reference_stage_pairs() -> list[tuple[str, str]]:
    first = quarter_index(EXPECTED_REFERENCE_START)
    last = quarter_index(EXPECTED_REFERENCE_END)

    pairs: list[tuple[str, str]] = []
    for value in range(first, last + 1):
        year, zero_based_quarter = divmod(value, 4)
        reference_period = f"{year:04d}-Q{zero_based_quarter + 1}"
        pairs.extend(
            [
                (reference_period, "preliminary"),
                (reference_period, "revised"),
            ]
        )
    return pairs


def test_historical_productivity_archive_exists() -> None:
    assert ARCHIVE_PATH.exists(), (
        "Historical Productivity and Costs archive is missing. Run "
        "`python -m labor_day.ingest_productivity_costs_releases`."
    )


def test_historical_productivity_archive_is_complete() -> None:
    archive = load_archive()

    assert len(archive) == EXPECTED_ARCHIVE_ROWS
    assert archive["event_id"].nunique() == EXPECTED_ARCHIVE_ROWS
    assert not archive.duplicated(
        ["reference_period", "release_stage"]
    ).any()

    actual_pairs = sorted(
        zip(
            archive["reference_period"],
            archive["release_stage"],
        ),
        key=lambda pair: (
            quarter_index(pair[0]),
            pair[1],
        ),
    )
    expected_pairs = sorted(
        expected_reference_stage_pairs(),
        key=lambda pair: (
            quarter_index(pair[0]),
            pair[1],
        ),
    )

    assert actual_pairs == expected_pairs


def test_reference_and_publication_span_is_stable() -> None:
    archive = load_archive()

    ordered = archive.sort_values(
        ["release_date", "release_stage", "event_id"]
    )

    assert ordered.iloc[0]["reference_period"] == EXPECTED_REFERENCE_START
    assert ordered.iloc[-1]["reference_period"] == EXPECTED_REFERENCE_END

    assert archive["release_date"].min().strftime(
        "%Y-%m-%d"
    ) == EXPECTED_FIRST_RELEASE_DATE
    assert archive["release_date"].max().strftime(
        "%Y-%m-%d"
    ) == EXPECTED_LAST_RELEASE_DATE


def test_release_stage_counts_are_stable() -> None:
    archive = load_archive()
    counts = archive["release_stage"].value_counts().to_dict()

    assert counts == {
        "preliminary": EXPECTED_PRELIMINARY_ROWS,
        "revised": EXPECTED_REVISED_ROWS,
    }


def test_publication_year_counts_are_stable() -> None:
    archive = load_archive()
    counts = (
        archive.groupby(archive["release_date"].dt.year)
        .size()
        .to_dict()
    )

    assert set(counts) == set(range(1998, 2026))

    for year in range(1998, 2025):
        assert counts[year] == 8

    assert counts[2025] == 6


def test_release_time_distribution_is_stable() -> None:
    archive = load_archive()
    counts = archive["release_time_et"].value_counts().to_dict()

    assert counts == {
        "08:30": EXPECTED_0830_ROWS,
        "10:00": EXPECTED_1000_ROWS,
    }

    assert archive["event_timezone"].eq(
        "America/New_York"
    ).all()
    assert archive["verification_status"].eq(
        EXPECTED_VERIFICATION_STATUS
    ).all()
    assert archive["time_source"].eq(
        EXPECTED_TIME_SOURCE
    ).all()


def test_documented_1999_filename_date_anomaly_is_preserved() -> None:
    archive = load_archive()

    row = archive.loc[
        archive["release_url"].str.endswith(
            "/prod2_11151999.txt"
        )
    ]

    assert len(row) == 1
    assert row.iloc[0]["release_date"].strftime(
        "%Y-%m-%d"
    ) == "1999-11-12"
    assert row.iloc[0]["reference_period"] == "1999-Q3"
    assert row.iloc[0]["release_stage"] == "preliminary"
    assert "filename" in row.iloc[0]["notes"].lower()
    assert "header" in row.iloc[0]["notes"].lower()


def test_registry_contains_exact_historical_archive() -> None:
    archive = load_archive()
    registry = load_registry()

    historical_registry = registry.loc[
        registry["event_type"].eq(EXPECTED_EVENT_TYPE)
        & registry["event_date"].dt.year.between(
            1998,
            2025,
        )
    ]

    assert len(historical_registry) == EXPECTED_ARCHIVE_ROWS
    assert set(historical_registry["event_id"]) == set(
        archive["event_id"]
    )

    assert historical_registry["source"].eq("BLS").all()
    assert historical_registry["event_name"].eq(
        "Productivity and Costs"
    ).all()
    assert historical_registry["tier"].eq("tier_1").all()
    assert historical_registry["verification_status"].eq(
        EXPECTED_VERIFICATION_STATUS
    ).all()


def test_registry_has_no_duplicate_event_ids() -> None:
    registry = load_registry()

    duplicated = registry.loc[
        registry["event_id"].duplicated(keep=False),
        "event_id",
    ].tolist()

    assert duplicated == []


def test_all_preimport_2026_rows_are_preserved() -> None:
    assert PRE_IMPORT_REGISTRY_PATH.exists(), (
        "Pre-Productivity registry backup is missing."
    )

    before = load_registry(PRE_IMPORT_REGISTRY_PATH)
    after = load_registry()

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


def test_historical_productivity_mapping_count_is_stable() -> None:
    historical = historical_productivity_mappings()

    assert len(historical) == EXPECTED_HISTORICAL_MAPPED_EVENTS
    assert (
        historical["event_id"].nunique()
        == EXPECTED_HISTORICAL_MAPPED_EVENTS
    )


def test_historical_productivity_mapping_span_is_stable() -> None:
    historical = historical_productivity_mappings()

    assert not historical.empty
    assert historical["event_year"].min() == 1998
    assert historical["event_year"].max() == 2025


def test_historical_productivity_mappings_are_inside_event_grid() -> None:
    historical = historical_productivity_mappings()

    assert not historical.empty
    assert not historical["event_time"].eq(0).any()
    assert historical["event_time"].between(
        -20,
        20,
    ).all()
