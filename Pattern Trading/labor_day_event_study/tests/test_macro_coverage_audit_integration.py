from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
SERIES_YEAR_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "macro_coverage_by_series_year.csv"
)
EVENT_TYPE_SUMMARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "macro_coverage_event_type_summary.csv"
)
YEAR_SUMMARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_coverage_by_year.csv"
)
WINDOW_SUMMARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_coverage_by_window.csv"
)
ISSUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "macro_coverage_gaps.csv"
)
MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "macro_coverage_audit.json"
)

EXPECTED_REGISTRY_ROWS = 3113
EXPECTED_MAPPED_EVENTS = 571
EXPECTED_EVENT_TYPES = 18
EXPECTED_AUDIT_YEARS = 29
EXPECTED_WINDOWS = 7
EXPECTED_SERIES_YEAR_ROWS = 522
EXPECTED_WINDOW_ROWS = 203
EXPECTED_WARNING_ROWS = 6

EXPECTED_BY_YEAR: dict[int, tuple[int, int, int]] = {
    1998: (20, 5, 5),
    1999: (18, 5, 5),
    2000: (19, 5, 5),
    2001: (23, 6, 6),
    2002: (19, 6, 6),
    2003: (17, 6, 5),
    2004: (21, 9, 8),
    2005: (21, 8, 7),
    2006: (21, 7, 6),
    2007: (23, 7, 6),
    2008: (22, 7, 6),
    2009: (23, 7, 6),
    2010: (21, 8, 7),
    2011: (21, 8, 7),
    2012: (20, 7, 6),
    2013: (20, 8, 7),
    2014: (20, 8, 7),
    2015: (21, 8, 7),
    2016: (19, 8, 7),
    2017: (19, 8, 7),
    2018: (19, 7, 7),
    2019: (19, 8, 7),
    2020: (21, 9, 8),
    2021: (19, 8, 7),
    2022: (18, 7, 6),
    2023: (18, 9, 8),
    2024: (18, 9, 8),
    2025: (19, 9, 8),
    2026: (12, 9, 5),
}


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
    )


def read_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_int(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="raise").astype(int)


def as_bool(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip().str.lower()
    assert normalized.isin({"true", "false"}).all()
    return normalized.eq("true")


def test_phase0d11_outputs_exist() -> None:
    for path in [
        REGISTRY_PATH,
        MAPPED_EVENTS_PATH,
        SERIES_YEAR_PATH,
        EVENT_TYPE_SUMMARY_PATH,
        YEAR_SUMMARY_PATH,
        WINDOW_SUMMARY_PATH,
        ISSUES_PATH,
        MANIFEST_PATH,
    ]:
        assert path.exists(), f"Missing Phase 0D11 artifact: {path}"


def test_manifest_has_frozen_phase0d11_status_and_counts() -> None:
    manifest = read_manifest()

    assert manifest["audit_name"] == "Labor Day macro coverage audit"
    assert manifest["audit_version"] == "1.0.0"
    assert manifest["status"] == "PASS_WITH_WARNINGS"

    assert (
        manifest["inputs"]["macro_registry"]["rows"]
        == EXPECTED_REGISTRY_ROWS
    )
    assert (
        manifest["inputs"]["mapped_events"]["rows_in_audit_sample"]
        == EXPECTED_MAPPED_EVENTS
    )

    assert manifest["row_counts"] == {
        "event_type_summary": EXPECTED_EVENT_TYPES,
        "issues": EXPECTED_WARNING_ROWS,
        "series_year": EXPECTED_SERIES_YEAR_ROWS,
        "window_summary": EXPECTED_WINDOW_ROWS,
        "year_summary": EXPECTED_AUDIT_YEARS,
    }

    assert manifest["issue_counts"] == {
        "critical": 0,
        "warning": EXPECTED_WARNING_ROWS,
        "info": 0,
    }


def test_manifest_input_hashes_match_current_inputs() -> None:
    manifest = read_manifest()

    assert (
        manifest["inputs"]["macro_registry"]["sha256"]
        == sha256_file(REGISTRY_PATH)
    )
    assert (
        manifest["inputs"]["mapped_events"]["sha256"]
        == sha256_file(MAPPED_EVENTS_PATH)
    )


def test_manifest_output_hashes_match_current_outputs() -> None:
    manifest = read_manifest()
    expected_paths = {
        SERIES_YEAR_PATH.name: SERIES_YEAR_PATH,
        EVENT_TYPE_SUMMARY_PATH.name: EVENT_TYPE_SUMMARY_PATH,
        YEAR_SUMMARY_PATH.name: YEAR_SUMMARY_PATH,
        WINDOW_SUMMARY_PATH.name: WINDOW_SUMMARY_PATH,
        ISSUES_PATH.name: ISSUES_PATH,
    }

    assert set(manifest["outputs"]) == set(expected_paths)

    for filename, path in expected_paths.items():
        assert (
            manifest["outputs"][filename]["sha256"]
            == sha256_file(path)
        )


def test_issue_file_contains_only_six_missing_time_warnings() -> None:
    issues = read_csv(ISSUES_PATH)

    assert len(issues) == EXPECTED_WARNING_ROWS
    assert issues["severity"].eq("warning").all()
    assert issues["issue_code"].eq(
        "mapped_event_missing_release_time"
    ).all()
    assert issues["scope"].eq("mapped_events").all()
    assert issues["event_id"].nunique() == EXPECTED_WARNING_ROWS
    assert issues["event_type"].str.strip().ne("").all()
    assert issues["event_year"].str.fullmatch(r"\d{4}").all()


def test_series_year_panel_is_complete_and_unique() -> None:
    coverage = read_csv(SERIES_YEAR_PATH)
    coverage["event_year"] = as_int(coverage["event_year"])

    assert len(coverage) == EXPECTED_SERIES_YEAR_ROWS
    assert coverage["event_type"].nunique() == EXPECTED_EVENT_TYPES
    assert set(coverage["event_year"]) == set(range(1998, 2027))
    assert not coverage.duplicated(
        ["event_type", "event_year"]
    ).any()

    rows_per_type = coverage.groupby("event_type").size()
    assert rows_per_type.eq(EXPECTED_AUDIT_YEARS).all()


def test_no_series_has_an_internal_observed_span_gap() -> None:
    coverage = read_csv(SERIES_YEAR_PATH)
    summary = read_csv(EVENT_TYPE_SUMMARY_PATH)

    assert not coverage["coverage_status"].eq(
        "gap_inside_observed_span"
    ).any()

    assert len(summary) == EXPECTED_EVENT_TYPES
    assert summary["event_type"].nunique() == EXPECTED_EVENT_TYPES
    assert as_int(summary["internal_gap_count"]).eq(0).all()
    assert summary["internal_gap_years"].eq("").all()


def test_event_type_summary_reconciles_to_registry_and_mapping_totals() -> None:
    summary = read_csv(EVENT_TYPE_SUMMARY_PATH)

    assert as_int(summary["registry_events"]).sum() == (
        EXPECTED_REGISTRY_ROWS
    )
    assert as_int(summary["mapped_events"]).sum() == (
        EXPECTED_MAPPED_EVENTS
    )

    assert (
        as_int(summary["known_time_events"])
        + as_int(summary["missing_time_events"])
    ).sum() == EXPECTED_REGISTRY_ROWS


def test_year_panel_has_frozen_sample_boundaries() -> None:
    years = read_csv(YEAR_SUMMARY_PATH)
    years["event_year"] = as_int(years["event_year"])

    assert len(years) == EXPECTED_AUDIT_YEARS
    assert years["event_year"].tolist() == list(range(1998, 2027))
    assert not years["event_year"].duplicated().any()

    sample_counts = years["sample"].value_counts().to_dict()
    assert sample_counts == {
        "discovery": 17,
        "validation": 11,
        "forward": 1,
    }

    assert years.loc[
        years["event_year"].between(1998, 2014),
        "sample",
    ].eq("discovery").all()
    assert years.loc[
        years["event_year"].between(2015, 2025),
        "sample",
    ].eq("validation").all()
    assert years.loc[
        years["event_year"].eq(2026),
        "sample",
    ].eq("forward").all()


def test_year_panel_matches_observed_phase0d11_counts() -> None:
    years = read_csv(YEAR_SUMMARY_PATH)
    years["event_year"] = as_int(years["event_year"])

    actual = {
        int(row.event_year): (
            int(row.mapped_events),
            int(row.complete_events),
            int(row.complete_tier_1_events),
        )
        for row in years.itertuples(index=False)
    }

    assert actual == EXPECTED_BY_YEAR


def test_year_panel_reconciles_mapped_and_complete_totals() -> None:
    years = read_csv(YEAR_SUMMARY_PATH)

    assert as_int(years["mapped_events"]).sum() == (
        EXPECTED_MAPPED_EVENTS
    )
    assert as_int(years["complete_events"]).sum() == 216
    assert as_int(years["complete_tier_1_events"]).sum() == 190
    assert as_int(years["missing_time_events"]).sum() == (
        EXPECTED_WARNING_ROWS
    )
    assert as_int(years["known_time_events"]).sum() == (
        EXPECTED_MAPPED_EVENTS - EXPECTED_WARNING_ROWS
    )


def test_no_complete_window_is_clean_or_tier1_clean() -> None:
    years = read_csv(YEAR_SUMMARY_PATH)

    assert not as_bool(years["complete_clean"]).any()
    assert not as_bool(years["complete_tier_1_clean"]).any()

    manifest = read_manifest()
    assert manifest["clean_window_counts"]["complete"] == 0
    assert (
        manifest["tier_1_clean_window_counts"]["complete"]
        == 0
    )


def test_window_panel_is_complete_unique_and_reconciled() -> None:
    windows = read_csv(WINDOW_SUMMARY_PATH)
    windows["event_year"] = as_int(windows["event_year"])

    assert len(windows) == EXPECTED_WINDOW_ROWS
    assert windows["window_name"].nunique() == EXPECTED_WINDOWS
    assert not windows.duplicated(
        ["event_year", "window_name"]
    ).any()

    rows_per_year = windows.groupby("event_year").size()
    assert rows_per_year.eq(EXPECTED_WINDOWS).all()

    complete = windows.loc[
        windows["window_name"].eq("complete")
    ].copy()

    assert len(complete) == EXPECTED_AUDIT_YEARS
    assert as_int(complete["event_count"]).sum() == 216
    assert as_int(complete["tier_1_events"]).sum() == 190
    assert as_bool(complete["contaminated"]).all()
    assert as_bool(complete["tier_1_contaminated"]).all()


def test_complete_window_panel_matches_year_summary() -> None:
    years = read_csv(YEAR_SUMMARY_PATH)
    windows = read_csv(WINDOW_SUMMARY_PATH)

    complete = windows.loc[
        windows["window_name"].eq("complete"),
        [
            "event_year",
            "event_count",
            "tier_1_events",
            "contaminated",
            "tier_1_contaminated",
        ],
    ].copy()

    complete.rename(
        columns={
            "event_count": "window_complete_events",
            "tier_1_events": "window_complete_tier_1_events",
        },
        inplace=True,
    )

    merged = years.merge(
        complete,
        on="event_year",
        how="inner",
        validate="one_to_one",
    )

    assert len(merged) == EXPECTED_AUDIT_YEARS
    assert as_int(merged["complete_events"]).equals(
        as_int(merged["window_complete_events"])
    )
    assert as_int(merged["complete_tier_1_events"]).equals(
        as_int(merged["window_complete_tier_1_events"])
    )
    assert (
        ~as_bool(merged["complete_clean"])
    ).equals(as_bool(merged["contaminated"]))
    assert (
        ~as_bool(merged["complete_tier_1_clean"])
    ).equals(as_bool(merged["tier_1_contaminated"]))


def test_mapped_source_reconciles_to_audit_sample() -> None:
    mapped = read_csv(MAPPED_EVENTS_PATH)
    mapped["event_year"] = as_int(mapped["event_year"])
    mapped["event_time"] = as_int(mapped["event_time"])

    audit_sample = mapped.loc[
        mapped["event_year"].between(1998, 2026)
    ].copy()

    assert len(audit_sample) == EXPECTED_MAPPED_EVENTS
    assert audit_sample["event_id"].nunique() == (
        EXPECTED_MAPPED_EVENTS
    )
    assert audit_sample["event_time"].between(-20, 20).all()
    assert audit_sample["event_time"].ne(0).all()