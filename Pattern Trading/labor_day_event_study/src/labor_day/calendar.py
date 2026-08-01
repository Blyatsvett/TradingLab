from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"


def labor_day_date(year: int) -> date:
    """Return US Labor Day: the first Monday in September."""
    if year < 1900:
        raise ValueError("Year must be 1900 or later.")

    september_first = date(year, 9, 1)
    days_until_monday = (7 - september_first.weekday()) % 7

    return september_first + timedelta(days=days_until_monday)


def sample_label(year: int) -> str:
    """Assign the project's chronological research sample."""
    if 1998 <= year <= 2014:
        return "discovery"

    if 2015 <= year <= 2025:
        return "validation"

    if year >= 2026:
        return "forward"

    return "pre_sample"


def event_session_label(event_time: int) -> str:
    """Convert an event-time integer to a readable label."""
    if event_time == 0:
        raise ValueError(
            "Labor Day is not a trading session; event time zero is prohibited."
        )

    return f"S{event_time:+d}"


def normalize_schedule_index(schedule: pd.DataFrame) -> pd.DataFrame:
    """Normalize exchange session labels to timezone-naive dates."""
    normalized = schedule.copy()
    index = pd.DatetimeIndex(normalized.index)

    if index.tz is not None:
        index = index.tz_convert("America/New_York").tz_localize(None)

    normalized.index = index.normalize()
    normalized.index.name = "session_date"

    return normalized


def timestamp_to_iso(value: object) -> str:
    """Convert a pandas-compatible timestamp to ISO-8601 text."""
    return pd.Timestamp(value).isoformat()


def build_labor_day_calendars(
    start_year: int = 1998,
    end_year: int = 2035,
    pre_sessions: int = 20,
    post_sessions: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build the annual Labor Day summary and event-time session calendar.

    Event time deliberately skips zero:

    - S-1 is the final NYSE session before Labor Day.
    - S+1 is the first NYSE session after Labor Day.
    """
    if start_year > end_year:
        raise ValueError("start_year cannot be greater than end_year.")

    if pre_sessions < 1 or post_sessions < 1:
        raise ValueError("pre_sessions and post_sessions must be positive.")

    first_holiday = pd.Timestamp(labor_day_date(start_year))
    final_holiday = pd.Timestamp(labor_day_date(end_year))

    calendar_start = first_holiday - pd.Timedelta(days=60)
    calendar_end = final_holiday + pd.Timedelta(days=60)

    nyse = mcal.get_calendar("NYSE")

    schedule = nyse.schedule(
        start_date=calendar_start.date().isoformat(),
        end_date=calendar_end.date().isoformat(),
    )

    schedule = normalize_schedule_index(schedule)
    all_sessions = pd.DatetimeIndex(schedule.index)

    annual_rows: list[dict[str, object]] = []
    session_rows: list[dict[str, object]] = []

    for year in range(start_year, end_year + 1):
        holiday = pd.Timestamp(labor_day_date(year))

        available_pre = all_sessions[all_sessions < holiday]
        available_post = all_sessions[all_sessions > holiday]

        if len(available_pre) < pre_sessions:
            raise RuntimeError(
                f"Insufficient pre-event sessions for Labor Day {year}."
            )

        if len(available_post) < post_sessions:
            raise RuntimeError(
                f"Insufficient post-event sessions for Labor Day {year}."
            )

        selected_pre = available_pre[-pre_sessions:]
        selected_post = available_post[:post_sessions]

        s_minus_1 = selected_pre[-1]
        s_plus_1 = selected_post[0]

        holiday_is_session = holiday in all_sessions

        if holiday_is_session:
            raise RuntimeError(
                f"NYSE calendar incorrectly treats Labor Day {year} as open."
            )

        annual_rows.append(
            {
                "event_year": year,
                "sample": sample_label(year),
                "holiday_name": "US Labor Day",
                "holiday_date": holiday.date().isoformat(),
                "holiday_weekday": holiday.day_name(),
                "s_minus_1_date": s_minus_1.date().isoformat(),
                "s_minus_1_weekday": s_minus_1.day_name(),
                "s_plus_1_date": s_plus_1.date().isoformat(),
                "s_plus_1_weekday": s_plus_1.day_name(),
                "pre_holiday_calendar_gap_days": (
                    holiday - s_minus_1
                ).days,
                "post_holiday_calendar_gap_days": (
                    s_plus_1 - holiday
                ).days,
                "closed_calendar_days": (
                    s_plus_1 - s_minus_1
                ).days - 1,
                "holiday_is_trading_session": holiday_is_session,
                "event_definition": "first Monday in September",
                "exchange_calendar": "NYSE",
            }
        )

        event_sessions = [
            *zip(range(-pre_sessions, 0), selected_pre, strict=True),
            *zip(
                range(1, post_sessions + 1),
                selected_post,
                strict=True,
            ),
        ]

        for event_time, session_date in event_sessions:
            schedule_row = schedule.loc[session_date]

            market_open_utc = pd.Timestamp(schedule_row["market_open"])
            market_close_utc = pd.Timestamp(schedule_row["market_close"])

            market_open_et = market_open_utc.tz_convert(
                "America/New_York"
            )
            market_close_et = market_close_utc.tz_convert(
                "America/New_York"
            )

            session_rows.append(
                {
                    "event_year": year,
                    "sample": sample_label(year),
                    "holiday_date": holiday.date().isoformat(),
                    "session_date": session_date.date().isoformat(),
                    "session_weekday": session_date.day_name(),
                    "event_time": event_time,
                    "event_session": event_session_label(event_time),
                    "event_side": (
                        "pre_holiday"
                        if event_time < 0
                        else "post_holiday"
                    ),
                    "is_s_minus_1": event_time == -1,
                    "is_s_plus_1": event_time == 1,
                    "market_open_utc": timestamp_to_iso(
                        market_open_utc
                    ),
                    "market_close_utc": timestamp_to_iso(
                        market_close_utc
                    ),
                    "market_open_et": timestamp_to_iso(
                        market_open_et
                    ),
                    "market_close_et": timestamp_to_iso(
                        market_close_et
                    ),
                }
            )

    annual_calendar = pd.DataFrame(annual_rows).sort_values(
        "event_year"
    )

    session_calendar = pd.DataFrame(session_rows).sort_values(
        ["event_year", "event_time"]
    )

    annual_calendar.reset_index(drop=True, inplace=True)
    session_calendar.reset_index(drop=True, inplace=True)

    return annual_calendar, session_calendar


def write_calendars(
    annual_calendar: pd.DataFrame,
    session_calendar: pd.DataFrame,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    """Write canonical calendar datasets to CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)

    annual_path = output_dir / "labor_day_event_calendar.csv"
    session_path = output_dir / "labor_day_event_sessions.csv"

    annual_calendar.to_csv(annual_path, index=False)
    session_calendar.to_csv(session_path, index=False)

    return annual_path, session_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the canonical Labor Day event calendar."
    )

    parser.add_argument("--start-year", type=int, default=1998)
    parser.add_argument("--end-year", type=int, default=2035)
    parser.add_argument("--pre-sessions", type=int, default=20)
    parser.add_argument("--post-sessions", type=int, default=20)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    annual_calendar, session_calendar = build_labor_day_calendars(
        start_year=args.start_year,
        end_year=args.end_year,
        pre_sessions=args.pre_sessions,
        post_sessions=args.post_sessions,
    )

    annual_path, session_path = write_calendars(
        annual_calendar=annual_calendar,
        session_calendar=session_calendar,
    )

    print("Labor Day calendars generated successfully.")
    print(f"Annual calendar:  {annual_path}")
    print(f"Session calendar: {session_path}")
    print(f"Events generated: {len(annual_calendar)}")
    print(f"Session rows:     {len(session_calendar)}")

    forward_2026 = annual_calendar[
        annual_calendar["event_year"] == 2026
    ]

    if not forward_2026.empty:
        print("\n2026 forward event:")
        print(forward_2026.to_string(index=False))


if __name__ == "__main__":
    main()