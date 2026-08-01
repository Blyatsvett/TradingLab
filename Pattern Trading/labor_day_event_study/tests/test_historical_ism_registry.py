from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

ISM_CALENDAR_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "ism_release_calendar_1998_2025.csv"
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

ISM_EVENT_TYPES = {
    "ism_manufacturing",
    "ism_services",
}

EXPECTED_YEARS = set(
    range(1998, 2026)
)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        encoding="utf-8-sig",
    )


def historical_ism_registry() -> pd.DataFrame:
    registry = read_csv(
        REGISTRY_PATH
    )

    dates = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )

    return registry.loc[
        registry["source"]
        .astype(str)
        .str.upper()
        .eq("ISM")
        & registry["event_type"].isin(
            ISM_EVENT_TYPES
        )
        & dates.dt.year.between(
            1998,
            2025,
        )
    ].copy()


def historical_ism_mappings() -> pd.DataFrame:
    mapped = read_csv(
        MAPPED_EVENTS_PATH
    )

    return mapped.loc[
        mapped["event_type"].isin(
            ISM_EVENT_TYPES
        )
        & mapped["event_year"].between(
            1998,
            2025,
        )
    ].copy()


def test_historical_ism_calendar_exists() -> None:
    assert ISM_CALENDAR_PATH.exists()


def test_historical_ism_calendar_is_complete() -> None:
    calendar = read_csv(
        ISM_CALENDAR_PATH
    )

    dates = pd.to_datetime(
        calendar["release_date"],
        errors="raise",
    )

    assert len(calendar) == 168
    assert not calendar[
        "event_id"
    ].duplicated().any()

    assert dates.dt.year.min() == 1998
    assert dates.dt.year.max() == 2025

    assert (
        calendar["event_type"]
        .eq("ism_manufacturing")
        .sum()
        == 84
    )

    assert (
        calendar["event_type"]
        .eq("ism_services")
        .sum()
        == 84
    )

    assert calendar[
        "release_time_et"
    ].eq("10:00").all()


def test_registry_contains_all_historical_ism_rows() -> None:
    historical = (
        historical_ism_registry()
    )

    assert len(historical) == 168

    assert historical[
        "verification_status"
    ].eq(
        "official_rule_derived"
    ).all()

    assert historical[
        "tier"
    ].eq(
        "tier_1"
    ).all()

    assert historical[
        "event_time_et"
    ].eq(
        "10:00"
    ).all()


def test_2026_scheduled_ism_rows_are_preserved() -> None:
    registry = read_csv(
        REGISTRY_PATH
    )

    dates = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )

    forward_rows = registry.loc[
        registry["source"]
        .astype(str)
        .str.upper()
        .eq("ISM")
        & registry["event_type"].isin(
            ISM_EVENT_TYPES
        )
        & dates.dt.year.eq(2026)
    ]

    assert set(
        forward_rows["event_type"]
    ) == ISM_EVENT_TYPES

    assert forward_rows[
        "verification_status"
    ].eq(
        "official_schedule"
    ).all()


def test_every_historical_year_has_manufacturing_mapping() -> None:
    mapped = (
        historical_ism_mappings()
    )

    manufacturing_years = set(
        mapped.loc[
            mapped["event_type"].eq(
                "ism_manufacturing"
            ),
            "event_year",
        ].astype(int)
    )

    assert (
        manufacturing_years
        == EXPECTED_YEARS
    )


def test_every_historical_year_has_services_mapping() -> None:
    mapped = (
        historical_ism_mappings()
    )

    services_years = set(
        mapped.loc[
            mapped["event_type"].eq(
                "ism_services"
            ),
            "event_year",
        ].astype(int)
    )

    assert (
        services_years
        == EXPECTED_YEARS
    )


def test_every_year_has_one_september_release_per_series() -> None:
    mapped = (
        historical_ism_mappings()
    )

    event_dates = pd.to_datetime(
        mapped["event_date"],
        errors="raise",
    )

    september = mapped.loc[
        event_dates.dt.month.eq(9)
    ].copy()

    counts = september.groupby(
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
                "ism_manufacturing",
            ),
            0,
        ) == 1

        assert counts.get(
            (
                event_year,
                "ism_services",
            ),
            0,
        ) == 1


def test_historical_ism_mappings_have_no_event_zero() -> None:
    mapped = (
        historical_ism_mappings()
    )

    assert not mapped[
        "event_time"
    ].eq(0).any()