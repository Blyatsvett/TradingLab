import pandas as pd

from labor_day.ingest_ism_releases import (
    MACRO_COLUMNS,
    build_macro_rows,
    generate_ism_release_calendar,
    get_nyse_sessions_for_month,
    merge_macro_registry,
    previous_month,
    validate_ism_calendar,
)


def test_previous_month_rolls_back_year() -> None:
    assert previous_month(
        2025,
        1,
    ) == (
        2024,
        12,
    )

    assert previous_month(
        2025,
        9,
    ) == (
        2025,
        8,
    )


def test_generate_2020_september_dates() -> None:
    calendar = (
        generate_ism_release_calendar(
            start_year=2020,
            end_year=2020,
            release_months=[9],
        )
    )

    manufacturing = calendar.loc[
        calendar["event_type"].eq(
            "ism_manufacturing"
        )
    ].iloc[0]

    services = calendar.loc[
        calendar["event_type"].eq(
            "ism_services"
        )
    ].iloc[0]

    assert (
        manufacturing["release_date"]
        == "2020-09-01"
    )

    assert (
        services["release_date"]
        == "2020-09-03"
    )


def test_generate_2024_labor_day_shift() -> None:
    calendar = (
        generate_ism_release_calendar(
            start_year=2024,
            end_year=2024,
            release_months=[9],
        )
    )

    manufacturing = calendar.loc[
        calendar["event_type"].eq(
            "ism_manufacturing"
        )
    ].iloc[0]

    services = calendar.loc[
        calendar["event_type"].eq(
            "ism_services"
        )
    ].iloc[0]

    assert (
        manufacturing["release_date"]
        == "2024-09-03"
    )

    assert (
        services["release_date"]
        == "2024-09-05"
    )


def test_default_calendar_has_expected_rows() -> None:
    calendar = (
        generate_ism_release_calendar()
    )

    assert len(calendar) == 168

    assert (
        calendar["event_type"]
        .eq(
            "ism_manufacturing"
        )
        .sum()
        == 84
    )

    assert (
        calendar["event_type"]
        .eq(
            "ism_services"
        )
        .sum()
        == 84
    )


def test_calendar_uses_first_and_third_nyse_sessions() -> None:
    calendar = (
        generate_ism_release_calendar(
            start_year=2001,
            end_year=2001,
            release_months=[9],
        )
    )

    sessions = (
        get_nyse_sessions_for_month(
            2001,
            9,
        )
    )

    manufacturing = calendar.loc[
        calendar["event_type"].eq(
            "ism_manufacturing"
        )
    ].iloc[0]

    services = calendar.loc[
        calendar["event_type"].eq(
            "ism_services"
        )
    ].iloc[0]

    assert (
        manufacturing["release_date"]
        == sessions[0].isoformat()
    )

    assert (
        services["release_date"]
        == sessions[2].isoformat()
    )


def test_macro_rows_use_project_schema() -> None:
    calendar = (
        generate_ism_release_calendar(
            start_year=2020,
            end_year=2020,
            release_months=[9],
        )
    )

    macro_rows = build_macro_rows(
        calendar
    )

    assert list(
        macro_rows.columns
    ) == MACRO_COLUMNS

    assert len(macro_rows) == 2

    assert macro_rows[
        "event_time_et"
    ].eq(
        "10:00"
    ).all()

    assert macro_rows[
        "tier"
    ].eq(
        "tier_1"
    ).all()

    assert macro_rows[
        "verification_status"
    ].eq(
        "official_rule_derived"
    ).all()


def test_registry_merge_is_idempotent_and_preserves_2026() -> None:
    existing = pd.DataFrame(
        [
            {
                "event_id": (
                    "OLD_ISM_2020"
                ),
                "event_date": (
                    "2020-09-01"
                ),
                "event_time_et": "10:00",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "ISM",
                "event_type": (
                    "ism_manufacturing"
                ),
                "event_name": (
                    "Old historical row"
                ),
                "tier": "tier_1",
                "verification_status": (
                    "old"
                ),
                "source_url": "",
                "notes": "",
            },
            {
                "event_id": (
                    "ISM_MANUFACTURING_2026_09_01"
                ),
                "event_date": (
                    "2026-09-01"
                ),
                "event_time_et": "10:00",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "ISM",
                "event_type": (
                    "ism_manufacturing"
                ),
                "event_name": (
                    "Scheduled 2026 event"
                ),
                "tier": "tier_1",
                "verification_status": (
                    "official_schedule"
                ),
                "source_url": "",
                "notes": "",
            },
            {
                "event_id": "OTHER_EVENT",
                "event_date": (
                    "2020-09-02"
                ),
                "event_time_et": "08:30",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "BLS",
                "event_type": "other",
                "event_name": "Other event",
                "tier": "tier_2",
                "verification_status": (
                    "official"
                ),
                "source_url": "",
                "notes": "",
            },
        ],
        columns=MACRO_COLUMNS,
    )

    generated = (
        generate_ism_release_calendar(
            start_year=2020,
            end_year=2020,
            release_months=[9],
        )
    )

    historical_rows = build_macro_rows(
        generated
    )

    merged_once = merge_macro_registry(
        existing=existing,
        historical_rows=historical_rows,
        start_year=2020,
        end_year=2020,
    )

    merged_twice = merge_macro_registry(
        existing=merged_once,
        historical_rows=historical_rows,
        start_year=2020,
        end_year=2020,
    )

    assert (
        "OLD_ISM_2020"
        not in set(
            merged_once["event_id"]
        )
    )

    assert (
        "ISM_MANUFACTURING_2026_09_01"
        in set(
            merged_once["event_id"]
        )
    )

    assert (
        "OTHER_EVENT"
        in set(
            merged_once["event_id"]
        )
    )

    pd.testing.assert_frame_equal(
        merged_once,
        merged_twice,
    )


def test_generated_event_ids_are_unique() -> None:
    calendar = (
        generate_ism_release_calendar()
    )

    assert not calendar[
        "event_id"
    ].duplicated().any()


def test_generated_calendar_passes_validation() -> None:
    calendar = (
        generate_ism_release_calendar()
    )

    validate_ism_calendar(
        ism_calendar=calendar,
        start_year=1998,
        end_year=2025,
        release_months=[
            8,
            9,
            10,
        ],
    )