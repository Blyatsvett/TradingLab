from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
import pandas_market_calendars as mcal
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MACRO_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events.csv"
)

DEFAULT_EVENT_SESSIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_event_sessions.csv"
)

DEFAULT_WINDOWS_PATH = (
    PROJECT_ROOT
    / "config"
    / "event_windows.yaml"
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

MARKET_TIMEZONE = "America/New_York"


REQUIRED_MACRO_COLUMNS = {
    "event_id",
    "event_date",
    "event_time_et",
    "event_timezone",
    "source",
    "event_type",
    "event_name",
    "tier",
    "verification_status",
    "source_url",
    "notes",
}


ASSIGNMENT_COLUMNS = [
    "event_timestamp_et",
    "timing_class",
    "assignment_rule",
    "assignment_confidence",
    "assigned_session_date",
    "assigned_market_open_et",
    "assigned_market_close_et",
]


def normalize_schedule_index(
    schedule: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize NYSE session labels to timezone-naive dates."""
    normalized = schedule.copy()
    index = pd.DatetimeIndex(normalized.index)

    if index.tz is not None:
        index = index.tz_convert(
            MARKET_TIMEZONE
        ).tz_localize(None)

    normalized.index = index.normalize()
    normalized.index.name = "session_date"

    return normalized


def build_nyse_schedule(
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """Return the NYSE schedule covering the requested dates."""
    nyse = mcal.get_calendar("NYSE")

    schedule = nyse.schedule(
        start_date=pd.Timestamp(
            start_date
        ).date().isoformat(),
        end_date=pd.Timestamp(
            end_date
        ).date().isoformat(),
    )

    if schedule.empty:
        raise RuntimeError(
            "NYSE schedule is empty for the requested range."
        )

    return normalize_schedule_index(schedule)


def load_macro_events(
    path: Path = DEFAULT_MACRO_EVENTS_PATH,
) -> pd.DataFrame:
    """Load and validate the raw macro-event registry."""
    if not path.exists():
        raise FileNotFoundError(
            f"Macro-event file not found: {path}"
        )

    events = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )

    missing_columns = REQUIRED_MACRO_COLUMNS.difference(
        events.columns
    )

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))

        raise ValueError(
            f"Macro-event file is missing columns: {missing}"
        )

    events = events.copy()
    events.columns = [
        column.strip()
        for column in events.columns
    ]

    for column in events.columns:
        events[column] = (
            events[column]
            .astype(str)
            .str.strip()
        )

    if events.empty:
        return events

    if (events["event_id"] == "").any():
        raise ValueError(
            "Every macro event must have a non-empty event_id."
        )

    duplicated_ids = events.loc[
        events["event_id"].duplicated(keep=False),
        "event_id",
    ].tolist()

    if duplicated_ids:
        raise ValueError(
            "Duplicate macro event_id values: "
            + ", ".join(sorted(set(duplicated_ids)))
        )

    parsed_dates = pd.to_datetime(
        events["event_date"],
        errors="coerce",
    )

    if parsed_dates.isna().any():
        bad_ids = events.loc[
            parsed_dates.isna(),
            "event_id",
        ].tolist()

        raise ValueError(
            "Invalid event_date for event_id values: "
            + ", ".join(bad_ids)
        )

    events["event_date"] = parsed_dates.dt.strftime(
        "%Y-%m-%d"
    )

    events["tier"] = (
        events["tier"]
        .str.lower()
        .str.replace("-", "_", regex=False)
        .str.replace(" ", "_", regex=False)
    )

    allowed_tiers = {
        "tier_1",
        "tier_2",
    }

    invalid_tiers = sorted(
        set(events["tier"]) - allowed_tiers
    )

    if invalid_tiers:
        raise ValueError(
            "Unsupported macro tiers: "
            + ", ".join(invalid_tiers)
        )

    events.loc[
        events["event_timezone"] == "",
        "event_timezone",
    ] = MARKET_TIMEZONE

    return events


def load_event_session_calendar(
    path: Path = DEFAULT_EVENT_SESSIONS_PATH,
) -> pd.DataFrame:
    """Load the canonical Labor Day event-session calendar."""
    if not path.exists():
        raise FileNotFoundError(
            f"Event-session calendar not found: {path}"
        )

    sessions = pd.read_csv(
        path,
        encoding="utf-8-sig",
    )

    required = {
        "event_year",
        "sample",
        "holiday_date",
        "session_date",
        "event_time",
        "event_session",
    }

    missing = required.difference(sessions.columns)

    if missing:
        raise ValueError(
            "Event-session calendar is missing columns: "
            + ", ".join(sorted(missing))
        )

    sessions = sessions.copy()

    sessions["event_year"] = (
        sessions["event_year"].astype(int)
    )

    sessions["event_time"] = (
        sessions["event_time"].astype(int)
    )

    sessions["session_date"] = pd.to_datetime(
        sessions["session_date"],
        errors="raise",
    ).dt.strftime("%Y-%m-%d")

    if (sessions["event_time"] == 0).any():
        raise ValueError(
            "Event-session calendar may not contain "
            "event time zero."
        )

    return sessions


def load_event_windows(
    path: Path = DEFAULT_WINDOWS_PATH,
) -> dict[str, dict[str, int]]:
    """Load and validate preregistered discovery windows."""
    if not path.exists():
        raise FileNotFoundError(
            f"Event-window config not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
    ) as handle:
        config: dict[str, Any] = (
            yaml.safe_load(handle) or {}
        )

    raw_windows = config.get("discovery_windows")

    if not isinstance(raw_windows, dict):
        raise ValueError(
            "No discovery_windows found in config."
        )

    if not raw_windows:
        raise ValueError(
            "No discovery_windows found in config."
        )

    windows: dict[str, dict[str, int]] = {}

    for name, definition in raw_windows.items():
        if not isinstance(definition, dict):
            raise ValueError(
                f"Window {name!r} must be a mapping."
            )

        try:
            start = int(definition["start"])
            end = int(definition["end"])

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                f"Window {name!r} requires integer "
                "start and end values."
            ) from exc

        if start > end:
            raise ValueError(
                f"Window {name!r} has start greater "
                "than end."
            )

        windows[str(name)] = {
            "start": start,
            "end": end,
        }

    return windows


def _next_session(
    session_index: pd.DatetimeIndex,
    date_value: pd.Timestamp,
) -> pd.Timestamp:
    candidates = session_index[
        session_index > date_value
    ]

    if len(candidates) == 0:
        raise RuntimeError(
            "No NYSE session exists after "
            f"{date_value.date().isoformat()}."
        )

    return pd.Timestamp(candidates[0])


def _parse_event_timestamp(
    event_date: str,
    event_time_et: str,
    event_timezone: str,
) -> pd.Timestamp:
    timestamp_text = (
        f"{event_date} {event_time_et}"
    )

    try:
        timestamp = pd.Timestamp(timestamp_text)

    except ValueError as exc:
        raise ValueError(
            f"Invalid event timestamp: {timestamp_text!r}"
        ) from exc

    try:
        timestamp = timestamp.tz_localize(
            event_timezone
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid or ambiguous timezone "
            f"{event_timezone!r} for timestamp "
            f"{timestamp_text!r}."
        ) from exc

    return timestamp.tz_convert(
        MARKET_TIMEZONE
    )


def assign_events_to_sessions(
    events: pd.DataFrame,
    schedule: pd.DataFrame,
) -> pd.DataFrame:
    """
    Assign each release to the NYSE session that can first trade it.

    Premarket and intraday releases map to the same session.

    Releases at or after the regular close map to the next
    NYSE session.

    Events on non-trading days also map to the next session.
    """
    assigned = events.copy()

    if assigned.empty:
        for column in ASSIGNMENT_COLUMNS:
            assigned[column] = pd.Series(
                dtype="object"
            )

        return assigned

    schedule = normalize_schedule_index(schedule)
    session_index = pd.DatetimeIndex(
        schedule.index
    )

    rows: list[dict[str, object]] = []

    for row in assigned.to_dict(
        orient="records"
    ):
        event_date = pd.Timestamp(
            row["event_date"]
        ).normalize()

        event_time = str(
            row.get("event_time_et", "")
        ).strip()

        event_timezone = (
            str(
                row.get(
                    "event_timezone",
                    "",
                )
            ).strip()
            or MARKET_TIMEZONE
        )

        is_trading_day = (
            event_date in session_index
        )

        event_timestamp_et = ""

        if event_time == "":
            assignment_confidence = "low"

            if is_trading_day:
                assigned_session = event_date
                timing_class = "unknown_time"

                assignment_rule = (
                    "same_session_unknown_time"
                )

            else:
                assigned_session = _next_session(
                    session_index,
                    event_date,
                )

                timing_class = (
                    "non_trading_day_unknown_time"
                )

                assignment_rule = (
                    "next_session_non_trading_day"
                )

        else:
            event_timestamp = _parse_event_timestamp(
                event_date=row["event_date"],
                event_time_et=event_time,
                event_timezone=event_timezone,
            )

            event_timestamp_et = (
                event_timestamp.isoformat()
            )

            assignment_confidence = "high"

            if not is_trading_day:
                assigned_session = _next_session(
                    session_index,
                    event_date,
                )

                timing_class = "non_trading_day"

                assignment_rule = (
                    "next_session_non_trading_day"
                )

            else:
                schedule_row = schedule.loc[
                    event_date
                ]

                market_open_et = pd.Timestamp(
                    schedule_row["market_open"]
                ).tz_convert(MARKET_TIMEZONE)

                market_close_et = pd.Timestamp(
                    schedule_row["market_close"]
                ).tz_convert(MARKET_TIMEZONE)

                if event_timestamp < market_open_et:
                    assigned_session = event_date
                    timing_class = "premarket"

                    assignment_rule = (
                        "same_session_before_open"
                    )

                elif event_timestamp < market_close_et:
                    assigned_session = event_date
                    timing_class = "intraday"

                    assignment_rule = (
                        "same_session_intraday"
                    )

                else:
                    assigned_session = _next_session(
                        session_index,
                        event_date,
                    )

                    timing_class = "after_close"

                    assignment_rule = (
                        "next_session_after_close"
                    )

        assigned_schedule_row = schedule.loc[
            assigned_session
        ]

        assigned_market_open_et = pd.Timestamp(
            assigned_schedule_row["market_open"]
        ).tz_convert(MARKET_TIMEZONE)

        assigned_market_close_et = pd.Timestamp(
            assigned_schedule_row["market_close"]
        ).tz_convert(MARKET_TIMEZONE)

        output_row = dict(row)

        output_row.update(
            {
                "event_timestamp_et": (
                    event_timestamp_et
                ),
                "timing_class": timing_class,
                "assignment_rule": assignment_rule,
                "assignment_confidence": (
                    assignment_confidence
                ),
                "assigned_session_date": (
                    assigned_session
                    .date()
                    .isoformat()
                ),
                "assigned_market_open_et": (
                    assigned_market_open_et
                    .isoformat()
                ),
                "assigned_market_close_et": (
                    assigned_market_close_et
                    .isoformat()
                ),
            }
        )

        rows.append(output_row)

    return pd.DataFrame(rows)


def _window_memberships(
    event_time: int,
    windows: dict[str, dict[str, int]],
) -> str:
    memberships = [
        name
        for name, definition in windows.items()
        if (
            definition["start"]
            <= event_time
            <= definition["end"]
        )
    ]

    return ";".join(memberships)


def map_events_to_labor_day(
    assigned_events: pd.DataFrame,
    event_sessions: pd.DataFrame,
    windows: dict[str, dict[str, int]],
) -> pd.DataFrame:
    """Map assigned macro events into Labor Day event time."""
    if assigned_events.empty:
        columns = [
            *assigned_events.columns,
            *[
                column
                for column in event_sessions.columns
                if column
                not in assigned_events.columns
            ],
            "is_tier_1",
            "is_tier_2",
            "window_memberships",
        ]

        return pd.DataFrame(columns=columns)

    events = assigned_events.copy()
    sessions = event_sessions.copy()

    events["_assigned_session_key"] = (
        pd.to_datetime(
            events["assigned_session_date"],
            errors="raise",
        ).dt.normalize()
    )

    sessions["_session_key"] = (
        pd.to_datetime(
            sessions["session_date"],
            errors="raise",
        ).dt.normalize()
    )

    mapped = events.merge(
        sessions,
        left_on="_assigned_session_key",
        right_on="_session_key",
        how="inner",
        validate="many_to_many",
        suffixes=("", "_labor_day"),
    )

    mapped.drop(
        columns=[
            "_assigned_session_key",
            "_session_key",
        ],
        inplace=True,
    )

    if mapped.empty:
        mapped["is_tier_1"] = pd.Series(
            dtype=bool
        )

        mapped["is_tier_2"] = pd.Series(
            dtype=bool
        )

        mapped["window_memberships"] = pd.Series(
            dtype=str
        )

        return mapped

    mapped["is_tier_1"] = (
        mapped["tier"].eq("tier_1")
    )

    mapped["is_tier_2"] = (
        mapped["tier"].eq("tier_2")
    )

    mapped["window_memberships"] = (
        mapped["event_time"].map(
            lambda value: _window_memberships(
                int(value),
                windows,
            )
        )
    )

    mapped.sort_values(
        [
            "event_year",
            "event_time",
            "event_id",
        ],
        inplace=True,
    )

    mapped.reset_index(
        drop=True,
        inplace=True,
    )

    return mapped


def _join_unique(
    values: pd.Series,
) -> str:
    cleaned = {
        str(value).strip()
        for value in values
        if str(value).strip()
        not in {
            "",
            "nan",
            "None",
        }
    }

    return ";".join(sorted(cleaned))


def build_session_contamination_matrix(
    event_sessions: pd.DataFrame,
    mapped_events: pd.DataFrame,
) -> pd.DataFrame:
    """
    Create one contamination row for every Labor Day session.
    """
    base_columns = [
        "event_year",
        "sample",
        "holiday_date",
        "session_date",
        "event_time",
        "event_session",
        "event_side",
        "is_s_minus_1",
        "is_s_plus_1",
    ]

    available_base_columns = [
        column
        for column in base_columns
        if column in event_sessions.columns
    ]

    matrix = event_sessions[
        available_base_columns
    ].copy()

    if mapped_events.empty:
        matrix["event_count"] = 0
        matrix["tier_1_count"] = 0
        matrix["tier_2_count"] = 0
        matrix["event_ids"] = ""
        matrix["event_names"] = ""
        matrix["event_types"] = ""
        matrix["event_tiers"] = ""

    else:
        aggregate = (
            mapped_events.groupby(
                [
                    "event_year",
                    "session_date",
                ],
                as_index=False,
            )
            .agg(
                event_count=(
                    "event_id",
                    "size",
                ),
                tier_1_count=(
                    "is_tier_1",
                    "sum",
                ),
                tier_2_count=(
                    "is_tier_2",
                    "sum",
                ),
                event_ids=(
                    "event_id",
                    _join_unique,
                ),
                event_names=(
                    "event_name",
                    _join_unique,
                ),
                event_types=(
                    "event_type",
                    _join_unique,
                ),
                event_tiers=(
                    "tier",
                    _join_unique,
                ),
            )
        )

        matrix = matrix.merge(
            aggregate,
            on=[
                "event_year",
                "session_date",
            ],
            how="left",
            validate="one_to_one",
        )

        for column in [
            "event_count",
            "tier_1_count",
            "tier_2_count",
        ]:
            matrix[column] = (
                matrix[column]
                .fillna(0)
                .astype(int)
            )

        for column in [
            "event_ids",
            "event_names",
            "event_types",
            "event_tiers",
        ]:
            matrix[column] = (
                matrix[column]
                .fillna("")
            )

    matrix["primary_contamination"] = (
        matrix["tier_1_count"].gt(0)
    )

    matrix["secondary_contamination"] = (
        matrix["tier_2_count"].gt(0)
    )

    matrix["secondary_only"] = (
        matrix["secondary_contamination"]
        & ~matrix["primary_contamination"]
    )

    matrix.sort_values(
        [
            "event_year",
            "event_time",
        ],
        inplace=True,
    )

    matrix.reset_index(
        drop=True,
        inplace=True,
    )

    return matrix


def build_window_contamination_summary(
    session_matrix: pd.DataFrame,
    windows: dict[str, dict[str, int]],
) -> pd.DataFrame:
    """
    Summarize contamination for each event year and window.
    """
    rows: list[dict[str, object]] = []

    for event_year, year_data in (
        session_matrix.groupby(
            "event_year",
            sort=True,
        )
    ):
        sample = str(
            year_data["sample"].iloc[0]
        )

        for window_name, definition in windows.items():
            start = definition["start"]
            end = definition["end"]

            in_window = year_data[
                year_data["event_time"].between(
                    start,
                    end,
                )
            ]

            tier_1_count = int(
                in_window["tier_1_count"].sum()
            )

            tier_2_count = int(
                in_window["tier_2_count"].sum()
            )

            rows.append(
                {
                    "event_year": int(event_year),
                    "sample": sample,
                    "window_name": window_name,
                    "window_start": start,
                    "window_end": end,
                    "session_count": int(
                        len(in_window)
                    ),
                    "tier_1_event_count": (
                        tier_1_count
                    ),
                    "tier_2_event_count": (
                        tier_2_count
                    ),
                    "primary_contaminated": (
                        tier_1_count > 0
                    ),
                    "secondary_contaminated": (
                        tier_2_count > 0
                    ),
                    "event_names": _join_unique(
                        in_window["event_names"]
                    ),
                }
            )

    summary = pd.DataFrame(rows)

    summary.sort_values(
        [
            "event_year",
            "window_start",
            "window_end",
            "window_name",
        ],
        inplace=True,
    )

    summary.reset_index(
        drop=True,
        inplace=True,
    )

    return summary


def write_outputs(
    assigned_events: pd.DataFrame,
    mapped_events: pd.DataFrame,
    session_matrix: pd.DataFrame,
    window_summary: pd.DataFrame,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    """Write all macro-contamination outputs."""
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = {
        "assigned_events": (
            output_dir
            / "macro_events_assigned.csv"
        ),
        "mapped_events": (
            output_dir
            / "labor_day_macro_event_map.csv"
        ),
        "session_matrix": (
            output_dir
            / "labor_day_contamination_matrix.csv"
        ),
        "window_summary": (
            output_dir
            / "labor_day_window_contamination.csv"
        ),
    }

    assigned_events.to_csv(
        paths["assigned_events"],
        index=False,
    )

    mapped_events.to_csv(
        paths["mapped_events"],
        index=False,
    )

    session_matrix.to_csv(
        paths["session_matrix"],
        index=False,
    )

    window_summary.to_csv(
        paths["window_summary"],
        index=False,
    )

    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Map macroeconomic announcements "
            "into Labor Day event time."
        )
    )

    parser.add_argument(
        "--macro-events",
        type=Path,
        default=DEFAULT_MACRO_EVENTS_PATH,
    )

    parser.add_argument(
        "--event-sessions",
        type=Path,
        default=DEFAULT_EVENT_SESSIONS_PATH,
    )

    parser.add_argument(
        "--event-windows",
        type=Path,
        default=DEFAULT_WINDOWS_PATH,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    events = load_macro_events(
        args.macro_events
    )

    event_sessions = load_event_session_calendar(
        args.event_sessions
    )

    windows = load_event_windows(
        args.event_windows
    )

    if events.empty:
        assigned_events = assign_events_to_sessions(
            events=events,
            schedule=pd.DataFrame(),
        )

    else:
        event_dates = pd.to_datetime(
            events["event_date"]
        )

        schedule = build_nyse_schedule(
            start_date=(
                event_dates.min()
                - pd.Timedelta(days=7)
            ),
            end_date=(
                event_dates.max()
                + pd.Timedelta(days=14)
            ),
        )

        assigned_events = assign_events_to_sessions(
            events=events,
            schedule=schedule,
        )

    mapped_events = map_events_to_labor_day(
        assigned_events=assigned_events,
        event_sessions=event_sessions,
        windows=windows,
    )

    session_matrix = (
        build_session_contamination_matrix(
            event_sessions=event_sessions,
            mapped_events=mapped_events,
        )
    )

    window_summary = (
        build_window_contamination_summary(
            session_matrix=session_matrix,
            windows=windows,
        )
    )

    paths = write_outputs(
        assigned_events=assigned_events,
        mapped_events=mapped_events,
        session_matrix=session_matrix,
        window_summary=window_summary,
        output_dir=args.output_dir,
    )

    print(
        "Labor Day contamination outputs generated."
    )

    print(
        f"Macro events loaded: {len(events)}"
    )

    print(
        "Events mapped into ±20 sessions: "
        f"{len(mapped_events)}"
    )

    print(
        f"Session matrix rows: {len(session_matrix)}"
    )

    print(
        f"Window summary rows: {len(window_summary)}"
    )

    for label, path in paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()