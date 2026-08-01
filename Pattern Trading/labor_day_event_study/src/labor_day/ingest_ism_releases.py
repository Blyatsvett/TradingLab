from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pandas as pd
import pandas_market_calendars as mcal

from labor_day.contamination import load_macro_events


PROJECT_ROOT = Path(__file__).resolve().parents[2]

OFFICIAL_CALENDAR_URL = (
    "https://www.ismworld.org/"
    "supply-management-news-and-reports/"
    "reports/rob-report-calendar/"
)

DEFAULT_MACRO_REGISTRY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events.csv"
)

DEFAULT_ISM_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "ism_release_calendar_1998_2025.csv"
)

DEFAULT_MANIFEST_OUTPUT = (
    PROJECT_ROOT
    / "manifests"
    / "ism_release_calendar_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_ism.csv"
)

MACRO_COLUMNS = [
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
]

ISM_OUTPUT_COLUMNS = [
    "event_id",
    "release_date",
    "release_time_et",
    "event_timezone",
    "series",
    "event_type",
    "reference_month",
    "reference_year",
    "release_business_day",
    "calendar_rule",
    "verification_status",
    "source_url",
    "notes",
]

ISM_EVENT_TYPES = {
    "ism_manufacturing",
    "ism_services",
}

DEFAULT_RELEASE_MONTHS = (
    8,
    9,
    10,
)

EXPECTED_DEFAULT_ROW_COUNT = 168

SERVICES_FIRST_AVAILABLE = date(
    1998,
    6,
    1,
)

SERIES_RULES = {
    "manufacturing": {
        "event_type": "ism_manufacturing",
        "event_id_prefix": "ISM_MANUFACTURING",
        "release_business_day": 1,
        "calendar_rule": (
            "First NYSE business session of the month"
        ),
    },
    "services": {
        "event_type": "ism_services",
        "event_id_prefix": "ISM_SERVICES",
        "release_business_day": 3,
        "calendar_rule": (
            "Third NYSE business session of the month"
        ),
    },
}


def previous_month(
    year: int,
    month: int,
) -> tuple[int, int]:
    """Return the year and month immediately before a release month."""
    if month == 1:
        return year - 1, 12

    return year, month - 1


def normalize_release_months(
    release_months: Iterable[int],
) -> tuple[int, ...]:
    """Validate and normalize requested release months."""
    months = tuple(
        sorted(
            {
                int(month)
                for month in release_months
            }
        )
    )

    if not months:
        raise ValueError(
            "At least one release month is required."
        )

    invalid = [
        month
        for month in months
        if month < 1 or month > 12
    ]

    if invalid:
        raise ValueError(
            "Invalid release months: "
            + ", ".join(
                str(month)
                for month in invalid
            )
        )

    return months


@lru_cache(maxsize=None)
def get_nyse_sessions_for_month(
    year: int,
    month: int,
) -> tuple[date, ...]:
    """
    Return all NYSE session dates in a calendar month.

    Results are cached because the same month is used repeatedly during
    generation, validation, and testing.
    """
    if month < 1 or month > 12:
        raise ValueError(
            f"Invalid month: {month}"
        )

    nyse = mcal.get_calendar(
        "NYSE"
    )

    final_day = calendar.monthrange(
        year,
        month,
    )[1]

    start_date = date(
        year,
        month,
        1,
    )

    end_date = date(
        year,
        month,
        final_day,
    )

    schedule = nyse.schedule(
        start_date=start_date,
        end_date=end_date,
    )

    sessions = tuple(
        timestamp.date()
        for timestamp in schedule.index
    )

    if len(sessions) < 3:
        raise RuntimeError(
            "Fewer than three NYSE sessions were found "
            f"for {year}-{month:02d}."
        )

    return sessions


def services_available(
    release_year: int,
    release_month: int,
) -> bool:
    """Return whether the Services report existed by this month."""
    release_month_start = date(
        release_year,
        release_month,
        1,
    )

    return (
        release_month_start
        >= SERVICES_FIRST_AVAILABLE
    )


def generate_ism_release_calendar(
    start_year: int = 1998,
    end_year: int = 2025,
    release_months: Iterable[int] = DEFAULT_RELEASE_MONTHS,
) -> pd.DataFrame:
    """
    Generate historical ISM release dates from declared release rules.

    Manufacturing uses the first NYSE business session.
    Services uses the third NYSE business session.
    """
    if start_year > end_year:
        raise ValueError(
            "start_year cannot exceed end_year."
        )

    months = normalize_release_months(
        release_months
    )

    rows: list[dict[str, object]] = []

    for release_year in range(
        start_year,
        end_year + 1,
    ):
        for release_month in months:
            sessions = (
                get_nyse_sessions_for_month(
                    release_year,
                    release_month,
                )
            )

            reference_year, reference_month = (
                previous_month(
                    release_year,
                    release_month,
                )
            )

            for series, rule in SERIES_RULES.items():
                if (
                    series == "services"
                    and not services_available(
                        release_year,
                        release_month,
                    )
                ):
                    continue

                business_day_number = int(
                    rule["release_business_day"]
                )

                release_date = sessions[
                    business_day_number - 1
                ]

                event_id = (
                    f"{rule['event_id_prefix']}_"
                    f"{release_date:%Y_%m_%d}"
                )

                reference_month_name = (
                    calendar.month_name[
                        reference_month
                    ]
                )

                rows.append(
                    {
                        "event_id": event_id,
                        "release_date": (
                            release_date.isoformat()
                        ),
                        "release_time_et": "10:00",
                        "event_timezone": (
                            "America/New_York"
                        ),
                        "series": series,
                        "event_type": (
                            rule["event_type"]
                        ),
                        "reference_month": (
                            reference_month_name
                        ),
                        "reference_year": (
                            reference_year
                        ),
                        "release_business_day": (
                            business_day_number
                        ),
                        "calendar_rule": (
                            rule["calendar_rule"]
                        ),
                        "verification_status": (
                            "official_rule_derived"
                        ),
                        "source_url": (
                            OFFICIAL_CALENDAR_URL
                        ),
                        "notes": (
                            "Release date derived from the "
                            "declared ISM release-calendar rule "
                            "using the NYSE session calendar. "
                            "No PMI index values were imported."
                        ),
                    }
                )

    output = pd.DataFrame(
        rows,
        columns=ISM_OUTPUT_COLUMNS,
    )

    output.sort_values(
        [
            "release_date",
            "series",
            "event_id",
        ],
        inplace=True,
    )

    output.reset_index(
        drop=True,
        inplace=True,
    )

    return output


def validate_ism_calendar(
    ism_calendar: pd.DataFrame,
    start_year: int,
    end_year: int,
    release_months: Iterable[int],
) -> None:
    """Validate generated dates against the declared ISM rules."""
    missing_columns = set(
        ISM_OUTPUT_COLUMNS
    ).difference(
        ism_calendar.columns
    )

    if missing_columns:
        raise ValueError(
            "ISM calendar is missing columns: "
            + ", ".join(
                sorted(missing_columns)
            )
        )

    if ism_calendar.empty:
        raise ValueError(
            "Generated ISM calendar is empty."
        )

    if ism_calendar[
        "event_id"
    ].duplicated().any():
        duplicated = ism_calendar.loc[
            ism_calendar[
                "event_id"
            ].duplicated(
                keep=False
            ),
            "event_id",
        ].tolist()

        raise ValueError(
            "Duplicate ISM event IDs: "
            + ", ".join(
                sorted(
                    set(duplicated)
                )
            )
        )

    release_dates = pd.to_datetime(
        ism_calendar["release_date"],
        errors="coerce",
    )

    if release_dates.isna().any():
        raise ValueError(
            "ISM calendar contains invalid release dates."
        )

    if not ism_calendar[
        "release_time_et"
    ].eq("10:00").all():
        raise ValueError(
            "All ISM releases must use 10:00 ET."
        )

    if not ism_calendar[
        "event_timezone"
    ].eq(
        "America/New_York"
    ).all():
        raise ValueError(
            "Unexpected ISM event timezone."
        )

    if not ism_calendar[
        "verification_status"
    ].eq(
        "official_rule_derived"
    ).all():
        raise ValueError(
            "Unexpected ISM verification status."
        )

    for row in ism_calendar.itertuples(
        index=False
    ):
        release_date = pd.Timestamp(
            row.release_date
        ).date()

        sessions = (
            get_nyse_sessions_for_month(
                release_date.year,
                release_date.month,
            )
        )

        expected_release_date = sessions[
            int(
                row.release_business_day
            )
            - 1
        ]

        if (
            release_date
            != expected_release_date
        ):
            raise ValueError(
                "ISM rule mismatch for "
                f"{row.event_id}: "
                f"expected {expected_release_date}, "
                f"found {release_date}."
            )

        expected_reference_year, expected_reference_month = (
            previous_month(
                release_date.year,
                release_date.month,
            )
        )

        expected_reference_month_name = (
            calendar.month_name[
                expected_reference_month
            ]
        )

        if (
            row.reference_month
            != expected_reference_month_name
            or int(
                row.reference_year
            )
            != expected_reference_year
        ):
            raise ValueError(
                "Reference-period mismatch for "
                f"{row.event_id}."
            )

    normalized_months = normalize_release_months(
        release_months
    )

    if (
        start_year == 1998
        and end_year == 2025
        and normalized_months
        == DEFAULT_RELEASE_MONTHS
        and len(ism_calendar)
        != EXPECTED_DEFAULT_ROW_COUNT
    ):
        raise ValueError(
            "Expected "
            f"{EXPECTED_DEFAULT_ROW_COUNT} "
            "ISM releases for August-October "
            "1998-2025, but generated "
            f"{len(ism_calendar)}."
        )

    known_dates = {
        (
            "ism_manufacturing",
            "2020-09-01",
        ),
        (
            "ism_services",
            "2020-09-03",
        ),
        (
            "ism_manufacturing",
            "2024-09-03",
        ),
        (
            "ism_services",
            "2024-09-05",
        ),
        (
            "ism_manufacturing",
            "2025-09-02",
        ),
        (
            "ism_services",
            "2025-09-04",
        ),
    }

    generated_pairs = set(
        zip(
            ism_calendar[
                "event_type"
            ],
            ism_calendar[
                "release_date"
            ],
        )
    )

    applicable_known_dates = {
        pair
        for pair in known_dates
        if (
            start_year
            <= int(
                pair[1][0:4]
            )
            <= end_year
            and int(
                pair[1][5:7]
            )
            in normalized_months
        )
    }

    missing_known_dates = (
        applicable_known_dates
        - generated_pairs
    )

    if missing_known_dates:
        formatted = [
            f"{event_type}: {release_date}"
            for event_type, release_date
            in sorted(
                missing_known_dates
            )
        ]

        raise ValueError(
            "Known ISM release dates are missing: "
            + "; ".join(formatted)
        )


def build_macro_rows(
    ism_calendar: pd.DataFrame,
) -> pd.DataFrame:
    """Convert generated ISM dates to the project macro schema."""
    rows: list[dict[str, str]] = []

    for row in ism_calendar.itertuples(
        index=False
    ):
        reference_period = (
            f"{row.reference_month} "
            f"{int(row.reference_year)}"
        )

        if (
            row.event_type
            == "ism_manufacturing"
        ):
            event_name = (
                "ISM Manufacturing release for "
                f"{reference_period}"
            )

        elif (
            row.event_type
            == "ism_services"
        ):
            event_name = (
                "ISM Services release for "
                f"{reference_period}"
            )

        else:
            raise ValueError(
                "Unexpected ISM event type: "
                f"{row.event_type}"
            )

        rows.append(
            {
                "event_id": row.event_id,
                "event_date": (
                    row.release_date
                ),
                "event_time_et": "10:00",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "ISM",
                "event_type": (
                    row.event_type
                ),
                "event_name": event_name,
                "tier": "tier_1",
                "verification_status": (
                    "official_rule_derived"
                ),
                "source_url": (
                    row.source_url
                ),
                "notes": (
                    "Date derived from the declared ISM "
                    f"rule: {row.calendar_rule}. "
                    "NYSE sessions determine business-day "
                    "ordering. No PMI values were imported."
                ),
            }
        )

    macro_rows = pd.DataFrame(
        rows,
        columns=MACRO_COLUMNS,
    )

    if macro_rows[
        "event_id"
    ].duplicated().any():
        raise ValueError(
            "Generated duplicate ISM macro event IDs."
        )

    return macro_rows


def merge_macro_registry(
    existing: pd.DataFrame,
    historical_rows: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """
    Idempotently replace historical ISM rows.

    Scheduled 2026 releases and non-ISM events are preserved.
    """
    registry = existing.copy()

    missing_columns = set(
        MACRO_COLUMNS
    ).difference(
        registry.columns
    )

    if missing_columns:
        raise ValueError(
            "Existing registry is missing columns: "
            + ", ".join(
                sorted(missing_columns)
            )
        )

    registry_dates = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )

    replace_mask = (
        registry["source"]
        .astype(str)
        .str.upper()
        .eq("ISM")
        & registry["event_type"]
        .astype(str)
        .isin(
            ISM_EVENT_TYPES
        )
        & registry_dates.dt.year.between(
            start_year,
            end_year,
        )
    )

    retained = registry.loc[
        ~replace_mask,
        MACRO_COLUMNS,
    ].copy()

    merged = pd.concat(
        [
            retained,
            historical_rows[
                MACRO_COLUMNS
            ],
        ],
        ignore_index=True,
    )

    merged.sort_values(
        [
            "event_date",
            "event_time_et",
            "event_type",
            "event_id",
        ],
        inplace=True,
    )

    merged.reset_index(
        drop=True,
        inplace=True,
    )

    duplicated_ids = merged.loc[
        merged[
            "event_id"
        ].duplicated(
            keep=False
        ),
        "event_id",
    ].tolist()

    if duplicated_ids:
        raise ValueError(
            "Duplicate event IDs after ISM merge: "
            + ", ".join(
                sorted(
                    set(duplicated_ids)
                )
            )
        )

    return merged


def atomic_write_csv(
    dataframe: pd.DataFrame,
    path: Path,
) -> None:
    """Write a CSV using a temporary file."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    dataframe.to_csv(
        temporary_path,
        index=False,
        encoding="utf-8",
    )

    temporary_path.replace(
        path
    )


def write_manifest(
    path: Path,
    ism_calendar: pd.DataFrame,
    start_year: int,
    end_year: int,
    release_months: Iterable[int],
    output_path: Path,
) -> None:
    """Write reproducibility metadata for the rule-derived calendar."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    csv_bytes = ism_calendar.to_csv(
        index=False
    ).encode(
        "utf-8"
    )

    try:
        relative_output = str(
            output_path.resolve().relative_to(
                PROJECT_ROOT.resolve()
            )
        )

    except ValueError:
        relative_output = str(
            output_path.resolve()
        )

    manifest = {
        "dataset": (
            "Historical ISM Manufacturing and "
            "Services release dates"
        ),
        "generation_method": (
            "Declared ISM release rules applied "
            "to the NYSE session calendar"
        ),
        "verification_status": (
            "official_rule_derived"
        ),
        "official_source_url": (
            OFFICIAL_CALENDAR_URL
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "start_year": start_year,
        "end_year": end_year,
        "release_months": list(
            normalize_release_months(
                release_months
            )
        ),
        "row_count": int(
            len(ism_calendar)
        ),
        "minimum_release_date": (
            ism_calendar[
                "release_date"
            ].min()
        ),
        "maximum_release_date": (
            ism_calendar[
                "release_date"
            ].max()
        ),
        "release_time_et": "10:00",
        "manufacturing_rule": (
            "First NYSE business session"
        ),
        "services_rule": (
            "Third NYSE business session"
        ),
        "generated_csv_sha256": (
            hashlib.sha256(
                csv_bytes
            ).hexdigest()
        ),
        "output_path": relative_output,
        "contains_pmi_values": False,
    }

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(
        path
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate historical ISM Manufacturing "
            "and Services release dates."
        )
    )

    parser.add_argument(
        "--start-year",
        type=int,
        default=1998,
    )

    parser.add_argument(
        "--end-year",
        type=int,
        default=2025,
    )

    parser.add_argument(
        "--release-months",
        type=int,
        nargs="+",
        default=list(
            DEFAULT_RELEASE_MONTHS
        ),
    )

    parser.add_argument(
        "--macro-registry",
        type=Path,
        default=DEFAULT_MACRO_REGISTRY,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_ISM_OUTPUT,
    )

    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_OUTPUT,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    release_months = (
        normalize_release_months(
            args.release_months
        )
    )

    existing_registry = load_macro_events(
        args.macro_registry
    )

    ism_calendar = (
        generate_ism_release_calendar(
            start_year=args.start_year,
            end_year=args.end_year,
            release_months=release_months,
        )
    )

    validate_ism_calendar(
        ism_calendar=ism_calendar,
        start_year=args.start_year,
        end_year=args.end_year,
        release_months=release_months,
    )

    historical_rows = build_macro_rows(
        ism_calendar
    )

    merged_registry = merge_macro_registry(
        existing=existing_registry,
        historical_rows=historical_rows,
        start_year=args.start_year,
        end_year=args.end_year,
    )

    if not DEFAULT_BACKUP_PATH.exists():
        DEFAULT_BACKUP_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            args.macro_registry,
            DEFAULT_BACKUP_PATH,
        )

    atomic_write_csv(
        ism_calendar,
        args.output,
    )

    atomic_write_csv(
        merged_registry,
        args.macro_registry,
    )

    write_manifest(
        path=args.manifest_output,
        ism_calendar=ism_calendar,
        start_year=args.start_year,
        end_year=args.end_year,
        release_months=release_months,
        output_path=args.output,
    )

    manufacturing_count = int(
        ism_calendar[
            "event_type"
        ].eq(
            "ism_manufacturing"
        ).sum()
    )

    services_count = int(
        ism_calendar[
            "event_type"
        ].eq(
            "ism_services"
        ).sum()
    )

    print(
        "Historical ISM release calendar generated."
    )

    print(
        "Verification method: official_rule_derived"
    )

    print(
        f"Calendar rows: {len(ism_calendar)}"
    )

    print(
        "Manufacturing rows: "
        f"{manufacturing_count}"
    )

    print(
        "Services rows: "
        f"{services_count}"
    )

    print(
        "Registry rows before: "
        f"{len(existing_registry)}"
    )

    print(
        "Historical rows inserted: "
        f"{len(historical_rows)}"
    )

    print(
        "Registry rows after: "
        f"{len(merged_registry)}"
    )

    print(
        f"Calendar output: {args.output}"
    )

    print(
        f"Registry: {args.macro_registry}"
    )

    print(
        f"Manifest: {args.manifest_output}"
    )


if __name__ == "__main__":
    main()