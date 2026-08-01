from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PRICE_ARCHIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "bls_price_index_releases_1998_2025.csv"
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

PRICE_EVENT_TYPES = {
    "cpi",
    "ppi",
}

EXPECTED_YEARS = set(
    range(1998, 2026)
)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        encoding="utf-8-sig",
    )


def historical_price_registry() -> pd.DataFrame:
    registry = read_csv(
        REGISTRY_PATH
    )

    event_dates = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )

    return registry.loc[
        registry["source"]
        .astype(str)
        .str.upper()
        .eq("BLS")
        & registry["event_type"].isin(
            PRICE_EVENT_TYPES
        )
        & event_dates.dt.year.between(
            1998,
            2025,
        )
    ].copy()


def historical_price_mappings() -> pd.DataFrame:
    mapped = read_csv(
        MAPPED_EVENTS_PATH
    )

    mapped["event_year"] = pd.to_numeric(
        mapped["event_year"],
        errors="raise",
    ).astype(int)

    mapped["event_time"] = pd.to_numeric(
        mapped["event_time"],
        errors="raise",
    ).astype(int)

    return mapped.loc[
        mapped["event_type"].isin(
            PRICE_EVENT_TYPES
        )
        & mapped["event_year"].between(
            1998,
            2025,
        )
    ].copy()


def test_price_index_archive_exists() -> None:
    assert PRICE_ARCHIVE_PATH.exists()


def test_price_index_archive_is_complete() -> None:
    archive = read_csv(
        PRICE_ARCHIVE_PATH
    )

    assert len(archive) == 669

    assert (
        archive["series"]
        .eq("cpi")
        .sum()
        == 335
    )

    assert (
        archive["series"]
        .eq("ppi")
        .sum()
        == 334
    )

    assert not archive[
        "event_id"
    ].duplicated().any()

    assert archive[
        "release_time_et"
    ].eq("08:30").all()

    assert archive[
        "verification_status"
    ].eq("official_archive").all()


def test_registry_contains_all_historical_price_rows() -> None:
    historical = (
        historical_price_registry()
    )

    assert len(historical) == 669

    assert (
        historical["event_type"]
        .eq("cpi")
        .sum()
        == 335
    )

    assert (
        historical["event_type"]
        .eq("ppi")
        .sum()
        == 334
    )

    assert historical[
        "tier"
    ].eq("tier_1").all()

    assert historical[
        "verification_status"
    ].eq("official_archive").all()

    assert historical[
        "event_time_et"
    ].eq("08:30").all()


def test_2026_scheduled_price_rows_are_preserved() -> None:
    registry = read_csv(
        REGISTRY_PATH
    )

    expected_events = {
        "BLS_CPI_2026_09_11": (
            "consumer_price_index"
        ),
        "BLS_PPI_2026_09_10": (
            "producer_price_index"
        ),
    }

    forward_rows = registry.loc[
        registry["event_id"].isin(
            expected_events
        )
    ].copy()

    assert set(
        forward_rows["event_id"]
    ) == set(
        expected_events
    )

    actual_event_types = dict(
        zip(
            forward_rows["event_id"],
            forward_rows["event_type"],
        )
    )

    assert (
        actual_event_types
        == expected_events
    )

    assert forward_rows[
        "verification_status"
    ].eq(
        "official_schedule"
    ).all()

    assert forward_rows[
        "event_date"
    ].isin(
        {
            "2026-09-10",
            "2026-09-11",
        }
    ).all()


def test_price_mapping_counts_are_complete() -> None:
    mapped = (
        historical_price_mappings()
    )

    assert len(mapped) == 112

    assert (
        mapped["event_type"]
        .eq("cpi")
        .sum()
        == 56
    )

    assert (
        mapped["event_type"]
        .eq("ppi")
        .sum()
        == 56
    )


def test_every_year_has_two_mappings_per_series() -> None:
    mapped = (
        historical_price_mappings()
    )

    counts = mapped.groupby(
        [
            "event_year",
            "event_type",
        ]
    ).size()

    for event_year in range(
        1998,
        2026,
    ):
        assert counts.get(
            (
                event_year,
                "cpi",
            ),
            0,
        ) == 2

        assert counts.get(
            (
                event_year,
                "ppi",
            ),
            0,
        ) == 2


def test_every_year_has_one_pre_and_one_post_release() -> None:
    mapped = (
        historical_price_mappings()
    )

    grouped = mapped.groupby(
        [
            "event_year",
            "event_type",
        ]
    )

    for (
        _event_year,
        _event_type,
    ), group in grouped:
        event_times = group[
            "event_time"
        ]

        assert (
            event_times < 0
        ).sum() == 1

        assert (
            event_times > 0
        ).sum() == 1


def test_price_releases_avoid_immediate_preholiday_window() -> None:
    mapped = (
        historical_price_mappings()
    )

    assert not mapped[
        "event_time"
    ].between(
        -5,
        -1,
    ).any()

    assert not mapped[
        "event_time"
    ].eq(0).any()


def test_price_releases_avoid_first_two_postholiday_sessions() -> None:
    mapped = (
        historical_price_mappings()
    )

    assert not mapped[
        "event_time"
    ].between(
        1,
        2,
    ).any()


def test_2001_ppi_maps_across_market_closure() -> None:
    mapped = (
        historical_price_mappings()
    )

    release = mapped.loc[
        mapped["event_id"].eq(
            "BLS_PPI_2001_09_14"
        )
    ]

    assert len(release) == 1

    row = release.iloc[0]

    assert row["event_date"] == "2001-09-14"
    assert row["session_date"] == "2001-09-17"
    assert int(row["event_time"]) == 6