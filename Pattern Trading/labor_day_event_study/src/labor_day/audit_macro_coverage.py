from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_REGISTRY_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events.csv"
)
DEFAULT_MAPPED_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_event_map.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests" / "macro_coverage_audit.json"
)

DEFAULT_START_YEAR = 1998
DEFAULT_END_YEAR = 2025
DEFAULT_FORWARD_YEAR = 2026

REGISTRY_REQUIRED_COLUMNS = [
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

MAPPED_REQUIRED_COLUMNS = [
    "event_id",
    "event_year",
    "event_time",
]

ISSUE_COLUMNS = [
    "severity",
    "issue_code",
    "scope",
    "event_id",
    "event_type",
    "event_year",
    "detail",
]

TIME_PATTERN = r"(?:[01]\d|2[0-3]):[0-5]\d"

WINDOWS: dict[str, tuple[int, int]] = {
    "early": (-15, -6),
    "demand_build_up": (-10, -2),
    "final_week": (-5, -1),
    "immediate": (-2, -1),
    "first_postweek": (1, 5),
    "unwind": (1, 10),
    "complete": (-5, 5),
}

SERIES_YEAR_COLUMNS = [
    "event_type",
    "event_year",
    "sample",
    "observed_span_start",
    "observed_span_end",
    "registry_events",
    "mapped_events",
    "known_time_events",
    "verified_exact_time_events",
    "missing_time_events",
    "tier_1_events",
    "tier_2_events",
    "source_count",
    "coverage_status",
]

EVENT_TYPE_SUMMARY_COLUMNS = [
    "event_type",
    "first_event_date",
    "last_event_date",
    "observed_span_start",
    "observed_span_end",
    "registry_events",
    "observed_years",
    "internal_gap_count",
    "internal_gap_years",
    "mapped_events",
    "mapped_years",
    "known_time_events",
    "verified_exact_time_events",
    "missing_time_events",
    "tiers",
    "sources",
]

WINDOW_SUMMARY_COLUMNS = [
    "event_year",
    "sample",
    "window_name",
    "window_start",
    "window_end",
    "event_count",
    "unique_event_types",
    "tier_1_events",
    "tier_2_events",
    "known_time_events",
    "verified_exact_time_events",
    "missing_time_events",
    "contaminated",
    "tier_1_contaminated",
    "event_types",
    "event_ids",
]

YEAR_BASE_COLUMNS = [
    "event_year",
    "sample",
    "mapped_events",
    "unique_event_types",
    "tier_1_events",
    "tier_2_events",
    "known_time_events",
    "verified_exact_time_events",
    "missing_time_events",
    "preholiday_events",
    "postholiday_events",
]


class CoverageAuditError(RuntimeError):
    """Raised when the macro-coverage audit finds structural corruption."""


@dataclass(frozen=True)
class AuditPaths:
    series_year: Path
    event_type_summary: Path
    year_summary: Path
    window_summary: Path
    issues: Path
    manifest: Path


def sample_for_year(
    year: int,
    *,
    discovery_end: int = 2014,
    validation_end: int = 2025,
    forward_year: int = 2026,
) -> str:
    if year <= discovery_end:
        return "discovery"
    if year <= validation_end:
        return "validation"
    if year == forward_year:
        return "forward"
    return "outside_sample"


def audit_years(
    *,
    start_year: int,
    end_year: int,
    forward_year: int,
) -> list[int]:
    if start_year > end_year:
        raise ValueError("start_year must not exceed end_year.")
    if forward_year <= end_year:
        raise ValueError("forward_year must be later than end_year.")
    return list(range(start_year, end_year + 1)) + [forward_year]


def event_is_in_window(
    event_time: int,
    window_name: str,
) -> bool:
    if window_name not in WINDOWS:
        raise KeyError(f"Unknown window: {window_name}")
    start, end = WINDOWS[window_name]
    return start <= event_time <= end and event_time != 0


def _require_columns(
    dataframe: pd.DataFrame,
    required: Iterable[str],
    *,
    label: str,
) -> None:
    missing = sorted(set(required).difference(dataframe.columns))
    if missing:
        raise ValueError(
            f"{label} is missing required columns: "
            + ", ".join(missing)
        )


def _read_csv(path: Path, *, label: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
    )


def load_registry(path: Path) -> pd.DataFrame:
    registry = _read_csv(path, label="Macro registry")
    _require_columns(
        registry,
        REGISTRY_REQUIRED_COLUMNS,
        label="Macro registry",
    )

    registry = registry.copy()
    registry["_event_date"] = pd.to_datetime(
        registry["event_date"],
        errors="coerce",
    )
    registry["_event_year"] = registry["_event_date"].dt.year.astype(
        "Int64"
    )
    return registry


def load_mapped_events(path: Path) -> pd.DataFrame:
    mapped = _read_csv(path, label="Mapped macro events")
    _require_columns(
        mapped,
        MAPPED_REQUIRED_COLUMNS,
        label="Mapped macro events",
    )

    mapped = mapped.copy()
    mapped["_event_year"] = pd.to_numeric(
        mapped["event_year"],
        errors="coerce",
    ).astype("Int64")
    mapped["_event_time"] = pd.to_numeric(
        mapped["event_time"],
        errors="coerce",
    ).astype("Int64")
    return mapped


def _issue(
    *,
    severity: str,
    issue_code: str,
    scope: str,
    event_id: str = "",
    event_type: str = "",
    event_year: str | int = "",
    detail: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "issue_code": issue_code,
        "scope": scope,
        "event_id": str(event_id),
        "event_type": str(event_type),
        "event_year": str(event_year),
        "detail": detail,
    }


def collect_input_issues(
    registry: pd.DataFrame,
    mapped: pd.DataFrame,
    *,
    start_year: int,
    end_year: int,
    forward_year: int,
) -> pd.DataFrame:
    issues: list[dict[str, str]] = []
    valid_years = set(
        audit_years(
            start_year=start_year,
            end_year=end_year,
            forward_year=forward_year,
        )
    )

    def display_year(row: pd.Series) -> str | int:
        value = row.get("_event_year", pd.NA)
        return "" if pd.isna(value) else int(value)

    duplicate_registry = registry.loc[
        registry["event_id"].duplicated(keep=False)
    ]
    for _, row in duplicate_registry.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="duplicate_registry_event_id",
                scope="registry",
                event_id=row["event_id"],
                event_type=row["event_type"],
                event_year=display_year(row),
                detail="event_id appears more than once in macro_events.csv",
            )
        )

    invalid_dates = registry.loc[registry["_event_date"].isna()]
    for _, row in invalid_dates.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="invalid_registry_event_date",
                scope="registry",
                event_id=row["event_id"],
                event_type=row["event_type"],
                detail=f"Could not parse event_date={row['event_date']!r}",
            )
        )

    nonblank_time = registry["event_time_et"].astype(str).str.strip().ne("")
    valid_time = registry["event_time_et"].astype(str).str.fullmatch(
        TIME_PATTERN
    )
    invalid_times = registry.loc[nonblank_time & ~valid_time]
    for _, row in invalid_times.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="invalid_registry_event_time",
                scope="registry",
                event_id=row["event_id"],
                event_type=row["event_type"],
                event_year=display_year(row),
                detail=(
                    "event_time_et must be blank or HH:MM; "
                    f"found {row['event_time_et']!r}"
                ),
            )
        )

    missing_timezone = registry.loc[
        nonblank_time
        & registry["event_timezone"].astype(str).str.strip().eq("")
    ]
    for _, row in missing_timezone.iterrows():
        issues.append(
            _issue(
                severity="warning",
                issue_code="known_time_missing_timezone",
                scope="registry",
                event_id=row["event_id"],
                event_type=row["event_type"],
                event_year=display_year(row),
                detail="Known release time has no event_timezone.",
            )
        )

    historical = registry.loc[
        registry["_event_year"].between(start_year, end_year)
    ]

    for column, issue_code in [
        ("source_url", "historical_missing_source_url"),
        (
            "verification_status",
            "historical_missing_verification_status",
        ),
    ]:
        missing = historical.loc[
            historical[column].astype(str).str.strip().eq("")
        ]
        for _, row in missing.iterrows():
            issues.append(
                _issue(
                    severity="warning",
                    issue_code=issue_code,
                    scope="registry",
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    event_year=display_year(row),
                    detail=f"Historical row has blank {column}.",
                )
            )

    duplicate_mapped = mapped.loc[
        mapped["event_id"].duplicated(keep=False)
    ]
    for _, row in duplicate_mapped.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="duplicate_mapped_event_id",
                scope="mapped_events",
                event_id=row["event_id"],
                event_year=display_year(row),
                detail=(
                    "event_id appears more than once in "
                    "labor_day_macro_event_map.csv"
                ),
            )
        )

    invalid_mapped_year = mapped.loc[mapped["_event_year"].isna()]
    for _, row in invalid_mapped_year.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="invalid_mapped_event_year",
                scope="mapped_events",
                event_id=row["event_id"],
                detail=f"Could not parse event_year={row['event_year']!r}",
            )
        )

    invalid_relative = mapped.loc[mapped["_event_time"].isna()]
    for _, row in invalid_relative.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="invalid_mapped_event_time",
                scope="mapped_events",
                event_id=row["event_id"],
                event_year=display_year(row),
                detail=f"Could not parse event_time={row['event_time']!r}",
            )
        )

    zero_relative = mapped.loc[mapped["_event_time"].eq(0)]
    for _, row in zero_relative.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="mapped_event_time_zero",
                scope="mapped_events",
                event_id=row["event_id"],
                event_year=display_year(row),
                detail="Labor Day is not a trading session; S0 is invalid.",
            )
        )

    outside_grid = mapped.loc[
        mapped["_event_time"].notna()
        & ~mapped["_event_time"].between(-20, 20)
    ]
    for _, row in outside_grid.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="mapped_event_outside_grid",
                scope="mapped_events",
                event_id=row["event_id"],
                event_year=display_year(row),
                detail=(
                    "Mapped event_time is outside the supported "
                    "[-20,+20] session grid."
                ),
            )
        )

    registry_ids = set(registry["event_id"].astype(str))
    unknown = mapped.loc[
        ~mapped["event_id"].astype(str).isin(registry_ids)
    ]
    for _, row in unknown.iterrows():
        issues.append(
            _issue(
                severity="critical",
                issue_code="mapped_event_missing_from_registry",
                scope="mapped_events",
                event_id=row["event_id"],
                event_year=display_year(row),
                detail=(
                    "Mapped event_id does not exist in macro_events.csv"
                ),
            )
        )

    out_of_audit_sample = mapped.loc[
        mapped["_event_year"].notna()
        & ~mapped["_event_year"].astype(int).isin(valid_years)
    ]
    if not out_of_audit_sample.empty:
        counts = (
            out_of_audit_sample["_event_year"]
            .value_counts()
            .sort_index()
        )
        issues.append(
            _issue(
                severity="info",
                issue_code="mapped_rows_outside_audit_sample",
                scope="mapped_events",
                detail=(
                    "Mapped rows outside the 1998-2026 audit sample are "
                    "retained in the source map but excluded from audit "
                    "tables: "
                    + ", ".join(
                        f"{int(year)}={int(count)}"
                        for year, count in counts.items()
                    )
                ),
            )
        )

    issue_frame = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
    if issue_frame.empty:
        return pd.DataFrame(columns=ISSUE_COLUMNS)

    severity_order = {
        "critical": 0,
        "warning": 1,
        "info": 2,
    }
    issue_frame["_severity_order"] = issue_frame["severity"].map(
        severity_order
    )
    issue_frame.sort_values(
        [
            "_severity_order",
            "issue_code",
            "event_year",
            "event_type",
            "event_id",
        ],
        inplace=True,
    )
    issue_frame.drop(columns="_severity_order", inplace=True)
    issue_frame.reset_index(drop=True, inplace=True)
    return issue_frame

def prepare_mapped_events(
    registry: pd.DataFrame,
    mapped: pd.DataFrame,
    *,
    start_year: int,
    end_year: int,
    forward_year: int,
) -> pd.DataFrame:
    valid_years = set(
        audit_years(
            start_year=start_year,
            end_year=end_year,
            forward_year=forward_year,
        )
    )

    registry_metadata = registry[
        [
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
        ]
    ].drop_duplicates(
        subset=["event_id"],
        keep="first",
    ).copy()

    mapped_for_merge = mapped.drop_duplicates(
        subset=["event_id"],
        keep="first",
    ).copy()

    prepared = mapped_for_merge.merge(
        registry_metadata,
        on="event_id",
        how="left",
        validate="many_to_one",
        suffixes=("_mapped", ""),
    )

    prepared = prepared.loc[
        prepared["_event_year"].notna()
        & prepared["_event_year"].astype(int).isin(valid_years)
        & prepared["_event_time"].notna()
        & prepared["_event_time"].between(-20, 20)
        & prepared["_event_time"].ne(0)
        & prepared["event_type"].notna()
    ].copy()

    prepared["event_year"] = prepared["_event_year"].astype(int)
    prepared["event_time"] = prepared["_event_time"].astype(int)
    prepared["sample"] = prepared["event_year"].map(
        lambda year: sample_for_year(
            int(year),
            validation_end=end_year,
            forward_year=forward_year,
        )
    )
    prepared["_known_time"] = (
        prepared["event_time_et"]
        .astype(str)
        .str.fullmatch(TIME_PATTERN)
    )
    prepared["_verified_exact_time"] = (
        prepared["verification_status"]
        .astype(str)
        .str.contains("exact_time", case=False, na=False)
    )
    prepared["_tier_1"] = prepared["tier"].astype(str).eq("tier_1")
    prepared["_tier_2"] = prepared["tier"].astype(str).eq("tier_2")

    return prepared


def build_series_year_coverage(
    registry: pd.DataFrame,
    mapped: pd.DataFrame,
    *,
    start_year: int,
    end_year: int,
    forward_year: int,
) -> pd.DataFrame:
    years = audit_years(
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )
    registry_sample = registry.loc[
        registry["_event_year"].notna()
        & registry["_event_year"].astype(int).isin(years)
    ].copy()
    registry_sample["event_year"] = registry_sample[
        "_event_year"
    ].astype(int)

    event_types = sorted(
        value
        for value in registry_sample["event_type"].astype(str).unique()
        if value.strip()
    )

    rows: list[dict[str, object]] = []
    for event_type in event_types:
        series = registry_sample.loc[
            registry_sample["event_type"].eq(event_type)
        ]
        observed_years = sorted(series["event_year"].unique())
        span_start = int(min(observed_years))
        span_end = int(max(observed_years))

        for year in years:
            year_rows = series.loc[series["event_year"].eq(year)]
            mapped_rows = mapped.loc[
                mapped["event_type"].eq(event_type)
                & mapped["event_year"].eq(year)
            ]

            registry_count = len(year_rows)
            mapped_count = len(mapped_rows)

            if year < span_start or year > span_end:
                status = "outside_observed_span"
            elif registry_count == 0:
                status = "gap_inside_observed_span"
            elif mapped_count == 0:
                status = "covered_no_labor_day_overlap"
            else:
                status = "covered_with_labor_day_overlap"

            known_time = year_rows["event_time_et"].astype(
                str
            ).str.fullmatch(TIME_PATTERN)
            exact_time = year_rows["verification_status"].astype(
                str
            ).str.contains("exact_time", case=False, na=False)

            rows.append(
                {
                    "event_type": event_type,
                    "event_year": year,
                    "sample": sample_for_year(
                        year,
                        validation_end=end_year,
                        forward_year=forward_year,
                    ),
                    "observed_span_start": span_start,
                    "observed_span_end": span_end,
                    "registry_events": registry_count,
                    "mapped_events": mapped_count,
                    "known_time_events": int(known_time.sum()),
                    "verified_exact_time_events": int(
                        exact_time.sum()
                    ),
                    "missing_time_events": int(
                        registry_count - known_time.sum()
                    ),
                    "tier_1_events": int(
                        year_rows["tier"].eq("tier_1").sum()
                    ),
                    "tier_2_events": int(
                        year_rows["tier"].eq("tier_2").sum()
                    ),
                    "source_count": int(
                        year_rows.loc[
                            year_rows["source"].astype(str).str.strip().ne(""),
                            "source",
                        ].nunique()
                    ),
                    "coverage_status": status,
                }
            )

    return pd.DataFrame(rows, columns=SERIES_YEAR_COLUMNS)


def add_series_gap_issues(
    issues: pd.DataFrame,
    series_year: pd.DataFrame,
) -> pd.DataFrame:
    additions: list[dict[str, str]] = []
    gaps = series_year.loc[
        series_year["coverage_status"].eq(
            "gap_inside_observed_span"
        )
    ]

    for row in gaps.itertuples(index=False):
        additions.append(
            _issue(
                severity="warning",
                issue_code="series_year_gap_inside_observed_span",
                scope="series_year",
                event_type=row.event_type,
                event_year=row.event_year,
                detail=(
                    f"No registry rows exist for {row.event_type} in "
                    f"{row.event_year}, although its observed span is "
                    f"{row.observed_span_start}-{row.observed_span_end}."
                ),
            )
        )

    if not additions:
        return issues

    combined = pd.concat(
        [
            issues,
            pd.DataFrame(additions, columns=ISSUE_COLUMNS),
        ],
        ignore_index=True,
    )
    combined.sort_values(
        [
            "severity",
            "issue_code",
            "event_year",
            "event_type",
            "event_id",
        ],
        inplace=True,
    )
    combined.reset_index(drop=True, inplace=True)
    return combined


def build_event_type_summary(
    registry: pd.DataFrame,
    mapped: pd.DataFrame,
    series_year: pd.DataFrame,
    *,
    start_year: int,
    end_year: int,
    forward_year: int,
) -> pd.DataFrame:
    years = set(
        audit_years(
            start_year=start_year,
            end_year=end_year,
            forward_year=forward_year,
        )
    )
    registry_sample = registry.loc[
        registry["_event_year"].notna()
        & registry["_event_year"].astype(int).isin(years)
    ].copy()
    registry_sample["event_year"] = registry_sample[
        "_event_year"
    ].astype(int)

    rows: list[dict[str, object]] = []
    for event_type, series in registry_sample.groupby(
        "event_type",
        sort=True,
    ):
        if not str(event_type).strip():
            continue

        year_coverage = series_year.loc[
            series_year["event_type"].eq(event_type)
        ]
        gaps = year_coverage.loc[
            year_coverage["coverage_status"].eq(
                "gap_inside_observed_span"
            ),
            "event_year",
        ].astype(int).tolist()

        mapped_series = mapped.loc[
            mapped["event_type"].eq(event_type)
        ]
        known_time = series["event_time_et"].astype(
            str
        ).str.fullmatch(TIME_PATTERN)
        exact_time = series["verification_status"].astype(
            str
        ).str.contains("exact_time", case=False, na=False)

        event_dates = series["_event_date"].dropna()
        rows.append(
            {
                "event_type": event_type,
                "first_event_date": (
                    event_dates.min().strftime("%Y-%m-%d")
                    if not event_dates.empty
                    else ""
                ),
                "last_event_date": (
                    event_dates.max().strftime("%Y-%m-%d")
                    if not event_dates.empty
                    else ""
                ),
                "observed_span_start": int(series["event_year"].min()),
                "observed_span_end": int(series["event_year"].max()),
                "registry_events": len(series),
                "observed_years": int(series["event_year"].nunique()),
                "internal_gap_count": len(gaps),
                "internal_gap_years": ";".join(
                    str(year) for year in gaps
                ),
                "mapped_events": len(mapped_series),
                "mapped_years": int(
                    mapped_series["event_year"].nunique()
                ),
                "known_time_events": int(known_time.sum()),
                "verified_exact_time_events": int(
                    exact_time.sum()
                ),
                "missing_time_events": int(
                    len(series) - known_time.sum()
                ),
                "tiers": ";".join(
                    sorted(
                        value
                        for value in series["tier"].astype(
                            str
                        ).unique()
                        if value.strip()
                    )
                ),
                "sources": ";".join(
                    sorted(
                        value
                        for value in series["source"].astype(
                            str
                        ).unique()
                        if value.strip()
                    )
                ),
            }
        )

    return pd.DataFrame(
        rows,
        columns=EVENT_TYPE_SUMMARY_COLUMNS,
    )


def build_window_coverage(
    mapped: pd.DataFrame,
    *,
    start_year: int,
    end_year: int,
    forward_year: int,
) -> pd.DataFrame:
    years = audit_years(
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )
    rows: list[dict[str, object]] = []

    for year in years:
        year_rows = mapped.loc[mapped["event_year"].eq(year)]
        for window_name, (window_start, window_end) in WINDOWS.items():
            window_rows = year_rows.loc[
                year_rows["event_time"].between(
                    window_start,
                    window_end,
                )
            ]
            event_types = sorted(
                value
                for value in window_rows["event_type"].astype(
                    str
                ).unique()
                if value.strip()
            )
            event_ids = sorted(
                value
                for value in window_rows["event_id"].astype(
                    str
                ).unique()
                if value.strip()
            )

            rows.append(
                {
                    "event_year": year,
                    "sample": sample_for_year(
                        year,
                        validation_end=end_year,
                        forward_year=forward_year,
                    ),
                    "window_name": window_name,
                    "window_start": window_start,
                    "window_end": window_end,
                    "event_count": len(window_rows),
                    "unique_event_types": len(event_types),
                    "tier_1_events": int(
                        window_rows["_tier_1"].sum()
                    ),
                    "tier_2_events": int(
                        window_rows["_tier_2"].sum()
                    ),
                    "known_time_events": int(
                        window_rows["_known_time"].sum()
                    ),
                    "verified_exact_time_events": int(
                        window_rows["_verified_exact_time"].sum()
                    ),
                    "missing_time_events": int(
                        len(window_rows)
                        - window_rows["_known_time"].sum()
                    ),
                    "contaminated": bool(len(window_rows) > 0),
                    "tier_1_contaminated": bool(
                        window_rows["_tier_1"].any()
                    ),
                    "event_types": ";".join(event_types),
                    "event_ids": ";".join(event_ids),
                }
            )

    return pd.DataFrame(rows, columns=WINDOW_SUMMARY_COLUMNS)


def build_year_summary(
    mapped: pd.DataFrame,
    window_coverage: pd.DataFrame,
    *,
    start_year: int,
    end_year: int,
    forward_year: int,
) -> pd.DataFrame:
    years = audit_years(
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )

    rows: list[dict[str, object]] = []
    for year in years:
        year_rows = mapped.loc[mapped["event_year"].eq(year)]
        row: dict[str, object] = {
            "event_year": year,
            "sample": sample_for_year(
                year,
                validation_end=end_year,
                forward_year=forward_year,
            ),
            "mapped_events": len(year_rows),
            "unique_event_types": int(
                year_rows["event_type"].nunique()
            ),
            "tier_1_events": int(year_rows["_tier_1"].sum()),
            "tier_2_events": int(year_rows["_tier_2"].sum()),
            "known_time_events": int(
                year_rows["_known_time"].sum()
            ),
            "verified_exact_time_events": int(
                year_rows["_verified_exact_time"].sum()
            ),
            "missing_time_events": int(
                len(year_rows) - year_rows["_known_time"].sum()
            ),
            "preholiday_events": int(
                year_rows["event_time"].lt(0).sum()
            ),
            "postholiday_events": int(
                year_rows["event_time"].gt(0).sum()
            ),
        }

        year_windows = window_coverage.loc[
            window_coverage["event_year"].eq(year)
        ].set_index("window_name")

        for window_name in WINDOWS:
            window_row = year_windows.loc[window_name]
            event_count = int(window_row["event_count"])
            tier_1_count = int(window_row["tier_1_events"])
            row[f"{window_name}_events"] = event_count
            row[f"{window_name}_tier_1_events"] = tier_1_count
            row[f"{window_name}_clean"] = event_count == 0
            row[f"{window_name}_tier_1_clean"] = tier_1_count == 0

        rows.append(row)

    columns = YEAR_BASE_COLUMNS.copy()
    for window_name in WINDOWS:
        columns.extend(
            [
                f"{window_name}_events",
                f"{window_name}_tier_1_events",
                f"{window_name}_clean",
                f"{window_name}_tier_1_clean",
            ]
        )

    return pd.DataFrame(rows, columns=columns)


def add_mapped_time_warning_issues(
    issues: pd.DataFrame,
    mapped: pd.DataFrame,
) -> pd.DataFrame:
    missing = mapped.loc[~mapped["_known_time"]]
    if missing.empty:
        return issues

    additions = [
        _issue(
            severity="warning",
            issue_code="mapped_event_missing_release_time",
            scope="mapped_events",
            event_id=row.event_id,
            event_type=row.event_type,
            event_year=row.event_year,
            detail=(
                "Mapped release has no exact HH:MM time; contamination "
                "assignment should be treated as lower confidence."
            ),
        )
        for row in missing.itertuples(index=False)
    ]
    combined = pd.concat(
        [
            issues,
            pd.DataFrame(additions, columns=ISSUE_COLUMNS),
        ],
        ignore_index=True,
    )
    combined.sort_values(
        [
            "severity",
            "issue_code",
            "event_year",
            "event_type",
            "event_id",
        ],
        inplace=True,
    )
    combined.reset_index(drop=True, inplace=True)
    return combined


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_csv(
    dataframe: pd.DataFrame,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    dataframe.to_csv(
        temporary,
        index=False,
        encoding="utf-8",
    )
    temporary.replace(path)


def output_paths(
    *,
    output_dir: Path,
    manifest_path: Path,
) -> AuditPaths:
    return AuditPaths(
        series_year=output_dir / "macro_coverage_by_series_year.csv",
        event_type_summary=(
            output_dir / "macro_coverage_event_type_summary.csv"
        ),
        year_summary=(
            output_dir / "labor_day_macro_coverage_by_year.csv"
        ),
        window_summary=(
            output_dir / "labor_day_macro_coverage_by_window.csv"
        ),
        issues=output_dir / "macro_coverage_gaps.csv",
        manifest=manifest_path,
    )


def write_manifest(
    *,
    path: Path,
    registry_path: Path,
    mapped_path: Path,
    outputs: AuditPaths,
    start_year: int,
    end_year: int,
    forward_year: int,
    registry: pd.DataFrame,
    mapped: pd.DataFrame,
    series_year: pd.DataFrame,
    event_type_summary: pd.DataFrame,
    year_summary: pd.DataFrame,
    window_summary: pd.DataFrame,
    issues: pd.DataFrame,
) -> dict[str, object]:
    critical_count = int(issues["severity"].eq("critical").sum())
    warning_count = int(issues["severity"].eq("warning").sum())
    info_count = int(issues["severity"].eq("info").sum())

    if critical_count:
        status = "FAIL"
    elif warning_count:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"

    csv_outputs = [
        outputs.series_year,
        outputs.event_type_summary,
        outputs.year_summary,
        outputs.window_summary,
        outputs.issues,
    ]

    payload: dict[str, object] = {
        "audit_name": "Labor Day macro coverage audit",
        "audit_version": "1.0.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "audit_range": {
            "historical_start_year": start_year,
            "historical_end_year": end_year,
            "forward_year": forward_year,
        },
        "inputs": {
            "macro_registry": {
                "path": str(registry_path.resolve()),
                "sha256": sha256_file(registry_path),
                "rows": len(registry),
            },
            "mapped_events": {
                "path": str(mapped_path.resolve()),
                "sha256": sha256_file(mapped_path),
                "rows_in_audit_sample": len(mapped),
            },
        },
        "outputs": {
            output.name: {
                "path": str(output.resolve()),
                "sha256": sha256_file(output),
            }
            for output in csv_outputs
        },
        "row_counts": {
            "series_year": len(series_year),
            "event_type_summary": len(event_type_summary),
            "year_summary": len(year_summary),
            "window_summary": len(window_summary),
            "issues": len(issues),
        },
        "issue_counts": {
            "critical": critical_count,
            "warning": warning_count,
            "info": info_count,
        },
        "clean_window_counts": {
            window_name: int(
                year_summary[f"{window_name}_clean"].sum()
            )
            for window_name in WINDOWS
        },
        "tier_1_clean_window_counts": {
            window_name: int(
                year_summary[f"{window_name}_tier_1_clean"].sum()
            )
            for window_name in WINDOWS
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


def run_audit(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    mapped_path: Path = DEFAULT_MAPPED_EVENTS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    start_year: int = DEFAULT_START_YEAR,
    end_year: int = DEFAULT_END_YEAR,
    forward_year: int = DEFAULT_FORWARD_YEAR,
    strict_warnings: bool = False,
) -> dict[str, object]:
    audit_years(
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )

    registry = load_registry(registry_path)
    mapped_source = load_mapped_events(mapped_path)

    issues = collect_input_issues(
        registry,
        mapped_source,
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )

    prepared_mapped = prepare_mapped_events(
        registry,
        mapped_source,
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )

    series_year = build_series_year_coverage(
        registry,
        prepared_mapped,
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )
    issues = add_series_gap_issues(issues, series_year)

    event_type_summary = build_event_type_summary(
        registry,
        prepared_mapped,
        series_year,
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )

    window_summary = build_window_coverage(
        prepared_mapped,
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )

    year_summary = build_year_summary(
        prepared_mapped,
        window_summary,
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
    )

    issues = add_mapped_time_warning_issues(
        issues,
        prepared_mapped,
    )

    paths = output_paths(
        output_dir=output_dir,
        manifest_path=manifest_path,
    )
    atomic_write_csv(series_year, paths.series_year)
    atomic_write_csv(event_type_summary, paths.event_type_summary)
    atomic_write_csv(year_summary, paths.year_summary)
    atomic_write_csv(window_summary, paths.window_summary)
    atomic_write_csv(issues, paths.issues)

    manifest = write_manifest(
        path=paths.manifest,
        registry_path=registry_path,
        mapped_path=mapped_path,
        outputs=paths,
        start_year=start_year,
        end_year=end_year,
        forward_year=forward_year,
        registry=registry,
        mapped=prepared_mapped,
        series_year=series_year,
        event_type_summary=event_type_summary,
        year_summary=year_summary,
        window_summary=window_summary,
        issues=issues,
    )

    critical_count = int(
        manifest["issue_counts"]["critical"]  # type: ignore[index]
    )
    warning_count = int(
        manifest["issue_counts"]["warning"]  # type: ignore[index]
    )

    if critical_count:
        raise CoverageAuditError(
            "Macro-coverage audit found "
            f"{critical_count} critical issue(s). "
            f"Inspect {paths.issues}."
        )
    if strict_warnings and warning_count:
        raise CoverageAuditError(
            "Macro-coverage audit found "
            f"{warning_count} warning(s) under --strict-warnings. "
            f"Inspect {paths.issues}."
        )

    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit macro-registry completeness and Labor Day-window "
            "coverage."
        )
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
    )
    parser.add_argument(
        "--mapped-events",
        type=Path,
        default=DEFAULT_MAPPED_EVENTS_PATH,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
    )
    parser.add_argument(
        "--forward-year",
        type=int,
        default=DEFAULT_FORWARD_YEAR,
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Return a failing exit status when warnings are present.",
    )
    return parser.parse_args()


def _print_summary(
    manifest: dict[str, object],
    paths: AuditPaths,
) -> None:
    row_counts = manifest["row_counts"]
    issue_counts = manifest["issue_counts"]
    clean_counts = manifest["clean_window_counts"]
    tier_1_clean_counts = manifest[
        "tier_1_clean_window_counts"
    ]

    print("Labor Day macro-coverage audit generated.")
    print(f"Status: {manifest['status']}")
    print(
        "Registry rows: "
        f"{manifest['inputs']['macro_registry']['rows']}"  # type: ignore[index]
    )
    print(
        "Mapped events in audit sample: "
        f"{manifest['inputs']['mapped_events']['rows_in_audit_sample']}"  # type: ignore[index]
    )
    print(
        "Event types audited: "
        f"{row_counts['event_type_summary']}"  # type: ignore[index]
    )
    print(
        "Series-year rows: "
        f"{row_counts['series_year']}"  # type: ignore[index]
    )
    print(
        "Year-summary rows: "
        f"{row_counts['year_summary']}"  # type: ignore[index]
    )
    print(
        "Window-summary rows: "
        f"{row_counts['window_summary']}"  # type: ignore[index]
    )
    print(
        "Issues: "
        f"critical={issue_counts['critical']}, "  # type: ignore[index]
        f"warning={issue_counts['warning']}, "  # type: ignore[index]
        f"info={issue_counts['info']}"  # type: ignore[index]
    )
    print(
        "Complete-window clean years: "
        f"{clean_counts['complete']}"  # type: ignore[index]
    )
    print(
        "Complete-window tier-1-clean years: "
        f"{tier_1_clean_counts['complete']}"  # type: ignore[index]
    )
    print(f"series_year: {paths.series_year.resolve()}")
    print(
        "event_type_summary: "
        f"{paths.event_type_summary.resolve()}"
    )
    print(f"year_summary: {paths.year_summary.resolve()}")
    print(f"window_summary: {paths.window_summary.resolve()}")
    print(f"issues: {paths.issues.resolve()}")
    print(f"manifest: {paths.manifest.resolve()}")


def main() -> None:
    args = parse_args()
    paths = output_paths(
        output_dir=args.output_dir,
        manifest_path=args.manifest_output,
    )

    try:
        manifest = run_audit(
            registry_path=args.registry,
            mapped_path=args.mapped_events,
            output_dir=args.output_dir,
            manifest_path=args.manifest_output,
            start_year=args.start_year,
            end_year=args.end_year,
            forward_year=args.forward_year,
            strict_warnings=args.strict_warnings,
        )
    except CoverageAuditError:
        if paths.manifest.exists():
            manifest = json.loads(
                paths.manifest.read_text(encoding="utf-8")
            )
            _print_summary(manifest, paths)
        raise

    _print_summary(manifest, paths)


if __name__ == "__main__":
    main()
