from datetime import date

import pytest

from labor_day.calendar import (
    build_labor_day_calendars,
    labor_day_date,
)


@pytest.fixture(scope="module")
def calendars():
    return build_labor_day_calendars(
        start_year=1998,
        end_year=2035,
        pre_sessions=20,
        post_sessions=20,
    )


def test_labor_day_is_first_monday_in_september() -> None:
    for year in range(1998, 2036):
        holiday = labor_day_date(year)

        assert holiday.month == 9
        assert 1 <= holiday.day <= 7
        assert holiday.weekday() == 0


def test_known_labor_day_dates() -> None:
    assert labor_day_date(2024) == date(2024, 9, 2)
    assert labor_day_date(2025) == date(2025, 9, 1)
    assert labor_day_date(2026) == date(2026, 9, 7)


def test_labor_day_is_not_a_trading_session(calendars) -> None:
    annual_calendar, _ = calendars

    assert not annual_calendar[
        "holiday_is_trading_session"
    ].any()


def test_sessions_surround_holiday(calendars) -> None:
    annual_calendar, _ = calendars

    for row in annual_calendar.itertuples(index=False):
        assert row.s_minus_1_date < row.holiday_date
        assert row.s_plus_1_date > row.holiday_date


def test_event_time_has_no_zero(calendars) -> None:
    _, session_calendar = calendars

    assert 0 not in set(session_calendar["event_time"])


def test_each_year_has_complete_event_window(calendars) -> None:
    _, session_calendar = calendars

    expected_event_times = set(range(-20, 0)) | set(range(1, 21))

    for _, year_data in session_calendar.groupby("event_year"):
        assert len(year_data) == 40
        assert set(year_data["event_time"]) == expected_event_times


def test_event_sessions_are_unique(calendars) -> None:
    _, session_calendar = calendars

    duplicates = session_calendar.duplicated(
        subset=["event_year", "session_date"]
    )

    assert not duplicates.any()


def test_2026_forward_event(calendars) -> None:
    annual_calendar, _ = calendars

    row = annual_calendar.loc[
        annual_calendar["event_year"] == 2026
    ].iloc[0]

    assert row["sample"] == "forward"
    assert row["holiday_date"] == "2026-09-07"
    assert row["s_minus_1_date"] == "2026-09-04"
    assert row["s_plus_1_date"] == "2026-09-08"