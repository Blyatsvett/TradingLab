import calendar
import pandas as pd


def black_friday_date(year: int) -> pd.Timestamp:
    """Return Black Friday: the day after the fourth Thursday in November."""
    cal = calendar.Calendar()
    thursdays = [
        day for day in cal.itermonthdates(year, 11)
        if day.month == 11 and day.weekday() == calendar.THURSDAY
    ]
    thanksgiving = thursdays[3]
    return pd.Timestamp(thanksgiving) + pd.Timedelta(days=1)


def build_event_calendar(start_year: int, end_year: int) -> pd.DataFrame:
    rows = [
        {
            "event_name": "Black Friday",
            "event_year": year,
            "event_date": black_friday_date(year),
        }
        for year in range(start_year, end_year + 1)
    ]
    return pd.DataFrame(rows)
