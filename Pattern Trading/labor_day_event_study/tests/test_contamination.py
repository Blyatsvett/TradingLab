import pandas as pd
import pytest

from labor_day.calendar import (
    build_labor_day_calendars,
)

from labor_day.contamination import (
    assign_events_to_sessions,
    build_nyse_schedule,
    build_session_contamination_matrix,
    build_window_contamination_summary,
    map_events_to_labor_day,
)


@pytest.fixture(scope="module")
def event_sessions() -> pd.DataFrame:
    _, sessions = build_labor_day_calendars(
        start_year=2026,
        end_year=2026,
        pre_sessions=20,
        post_sessions=20,
    )

    return sessions


@pytest.fixture(scope="module")
def nyse_schedule() -> pd.DataFrame:
    return build_nyse_schedule(
        "2026-08-20",
        "2026-09-20",
    )


@pytest.fixture(scope="module")
def windows() -> dict[str, dict[str, int]]:
    return {
        "immediate_preholiday": {
            "start": -2,
            "end": -1,
        },
        "first_postholiday_week": {
            "start": 1,
            "end": 5,
        },
        "complete_cycle": {
            "start": -5,
            "end": 5,
        },
    }


def make_event(
    event_id: str,
    event_date: str,
    event_time_et: str,
    tier: str = "tier_1",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": event_id,
                "event_date": event_date,
                "event_time_et": event_time_et,
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "synthetic_test",
                "event_type": "test_event",
                "event_name": event_id,
                "tier": tier,
                "verification_status": (
                    "synthetic"
                ),
                "source_url": "",
                "notes": "",
            }
        ]
    )


def test_premarket_release_maps_to_same_session(
    nyse_schedule,
    event_sessions,
    windows,
) -> None:
    event = make_event(
        "premarket_payrolls",
        "2026-09-04",
        "08:30",
    )

    assigned = assign_events_to_sessions(
        event,
        nyse_schedule,
    )

    mapped = map_events_to_labor_day(
        assigned,
        event_sessions,
        windows,
    )

    assert (
        assigned.loc[0, "timing_class"]
        == "premarket"
    )

    assert (
        assigned.loc[
            0,
            "assigned_session_date",
        ]
        == "2026-09-04"
    )

    assert mapped.loc[0, "event_time"] == -1

    assert (
        "immediate_preholiday"
        in mapped.loc[
            0,
            "window_memberships",
        ]
    )


def test_after_close_release_maps_to_next_session(
    nyse_schedule,
    event_sessions,
    windows,
) -> None:
    event = make_event(
        "after_close_release",
        "2026-09-04",
        "16:30",
    )

    assigned = assign_events_to_sessions(
        event,
        nyse_schedule,
    )

    mapped = map_events_to_labor_day(
        assigned,
        event_sessions,
        windows,
    )

    assert (
        assigned.loc[0, "timing_class"]
        == "after_close"
    )

    assert (
        assigned.loc[
            0,
            "assigned_session_date",
        ]
        == "2026-09-08"
    )

    assert mapped.loc[0, "event_time"] == 1


def test_weekend_release_maps_to_first_postholiday_session(
    nyse_schedule,
    event_sessions,
    windows,
) -> None:
    event = make_event(
        "weekend_release",
        "2026-09-06",
        "12:00",
    )

    assigned = assign_events_to_sessions(
        event,
        nyse_schedule,
    )

    mapped = map_events_to_labor_day(
        assigned,
        event_sessions,
        windows,
    )

    assert (
        assigned.loc[0, "timing_class"]
        == "non_trading_day"
    )

    assert (
        assigned.loc[
            0,
            "assigned_session_date",
        ]
        == "2026-09-08"
    )

    assert mapped.loc[0, "event_time"] == 1


def test_intraday_release_maps_to_same_session(
    nyse_schedule,
    event_sessions,
    windows,
) -> None:
    event = make_event(
        "intraday_release",
        "2026-09-09",
        "10:00",
        tier="tier_2",
    )

    assigned = assign_events_to_sessions(
        event,
        nyse_schedule,
    )

    mapped = map_events_to_labor_day(
        assigned,
        event_sessions,
        windows,
    )

    assert (
        assigned.loc[0, "timing_class"]
        == "intraday"
    )

    assert (
        assigned.loc[
            0,
            "assigned_session_date",
        ]
        == "2026-09-09"
    )

    assert mapped.loc[0, "event_time"] == 2

    assert bool(
        mapped.loc[0, "is_tier_2"]
    )


def test_missing_time_is_retained_with_low_confidence(
    nyse_schedule,
) -> None:
    event = make_event(
        "unknown_time",
        "2026-09-04",
        "",
    )

    assigned = assign_events_to_sessions(
        event,
        nyse_schedule,
    )

    assert (
        assigned.loc[0, "timing_class"]
        == "unknown_time"
    )

    assert (
        assigned.loc[
            0,
            "assignment_confidence",
        ]
        == "low"
    )

    assert (
        assigned.loc[
            0,
            "assigned_session_date",
        ]
        == "2026-09-04"
    )


def test_session_and_window_contamination_flags(
    nyse_schedule,
    event_sessions,
    windows,
) -> None:
    events = pd.concat(
        [
            make_event(
                "tier1_s_minus_1",
                "2026-09-04",
                "08:30",
                tier="tier_1",
            ),
            make_event(
                "tier2_s_plus_2",
                "2026-09-09",
                "10:00",
                tier="tier_2",
            ),
        ],
        ignore_index=True,
    )

    assigned = assign_events_to_sessions(
        events,
        nyse_schedule,
    )

    mapped = map_events_to_labor_day(
        assigned,
        event_sessions,
        windows,
    )

    matrix = build_session_contamination_matrix(
        event_sessions,
        mapped,
    )

    summary = build_window_contamination_summary(
        matrix,
        windows,
    )

    s_minus_1 = matrix.loc[
        matrix["event_time"] == -1
    ].iloc[0]

    s_plus_2 = matrix.loc[
        matrix["event_time"] == 2
    ].iloc[0]

    assert bool(
        s_minus_1[
            "primary_contamination"
        ]
    )

    assert bool(
        s_plus_2["secondary_only"]
    )

    immediate = summary.loc[
        summary["window_name"]
        == "immediate_preholiday"
    ].iloc[0]

    postweek = summary.loc[
        summary["window_name"]
        == "first_postholiday_week"
    ].iloc[0]

    assert bool(
        immediate["primary_contaminated"]
    )

    assert not bool(
        immediate["secondary_contaminated"]
    )

    assert bool(
        postweek["secondary_contaminated"]
    )