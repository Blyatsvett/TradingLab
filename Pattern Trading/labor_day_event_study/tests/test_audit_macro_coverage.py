from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from labor_day.audit_macro_coverage import (
    CoverageAuditError,
    ISSUE_COLUMNS,
    WINDOWS,
    add_mapped_time_warning_issues,
    add_series_gap_issues,
    audit_years,
    build_event_type_summary,
    build_series_year_coverage,
    build_window_coverage,
    build_year_summary,
    collect_input_issues,
    event_is_in_window,
    load_mapped_events,
    load_registry,
    prepare_mapped_events,
    run_audit,
    sample_for_year,
)


def macro_row(
    *,
    event_id: str,
    event_date: str,
    event_type: str,
    event_time_et: str = "08:30",
    tier: str = "tier_1",
    verification_status: str = (
        "official_release_page_exact_time"
    ),
    source_url: str = "https://example.gov/release",
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "event_date": event_date,
        "event_time_et": event_time_et,
        "event_timezone": "America/New_York",
        "source": "Official agency",
        "event_type": event_type,
        "event_name": event_type.replace("_", " ").title(),
        "tier": tier,
        "verification_status": verification_status,
        "source_url": source_url,
        "notes": "Synthetic test row.",
    }


def mapped_row(
    *,
    event_id: str,
    event_year: int,
    event_time: int,
    event_type: str = "stale_map_value",
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "event_year": str(event_year),
        "sample": "stale_sample",
        "event_date": f"{event_year}-09-01",
        "event_time": str(event_time),
        "session_date": f"{event_year}-09-01",
        "event_type": event_type,
    }


def registry_frame() -> pd.DataFrame:
    rows = [
        macro_row(
            event_id="cpi_1998",
            event_date="1998-08-28",
            event_type="cpi",
        ),
        macro_row(
            event_id="jobs_1998",
            event_date="1998-09-04",
            event_type="employment_situation",
        ),
        macro_row(
            event_id="jobs_1999",
            event_date="1999-09-03",
            event_type="employment_situation",
            event_time_et="",
            verification_status="official_release_date_only",
        ),
        macro_row(
            event_id="cpi_2000",
            event_date="2000-09-12",
            event_type="cpi",
        ),
        macro_row(
            event_id="jolts_2004",
            event_date="2004-09-08",
            event_type="jolts",
            tier="tier_2",
        ),
        macro_row(
            event_id="forward_2026",
            event_date="2026-09-04",
            event_type="employment_situation",
        ),
    ]
    frame = pd.DataFrame(rows)
    frame["_event_date"] = pd.to_datetime(frame["event_date"])
    frame["_event_year"] = frame["_event_date"].dt.year.astype(
        "Int64"
    )
    return frame


def mapped_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            mapped_row(
                event_id="cpi_1998",
                event_year=1998,
                event_time=-4,
            ),
            mapped_row(
                event_id="jobs_1998",
                event_year=1998,
                event_time=-1,
            ),
            mapped_row(
                event_id="jobs_1999",
                event_year=1999,
                event_time=3,
            ),
            mapped_row(
                event_id="cpi_2000",
                event_year=2000,
                event_time=7,
            ),
            mapped_row(
                event_id="jolts_2004",
                event_year=2004,
                event_time=2,
            ),
            mapped_row(
                event_id="forward_2026",
                event_year=2026,
                event_time=-1,
            ),
        ]
    )
    frame["_event_year"] = pd.to_numeric(
        frame["event_year"]
    ).astype("Int64")
    frame["_event_time"] = pd.to_numeric(
        frame["event_time"]
    ).astype("Int64")
    return frame


def prepared_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    registry = registry_frame()
    mapped = prepare_mapped_events(
        registry,
        mapped_frame(),
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    return registry, mapped


def write_inputs(
    tmp_path: Path,
    *,
    registry: pd.DataFrame | None = None,
    mapped: pd.DataFrame | None = None,
) -> tuple[Path, Path]:
    registry_path = tmp_path / "macro_events.csv"
    mapped_path = tmp_path / "labor_day_macro_event_map.csv"

    registry_to_write = (
        registry_frame()
        if registry is None
        else registry.copy()
    )
    registry_to_write.drop(
        columns=["_event_date", "_event_year"],
        errors="ignore",
    ).to_csv(registry_path, index=False)

    mapped_to_write = (
        mapped_frame()
        if mapped is None
        else mapped.copy()
    )
    mapped_to_write.drop(
        columns=["_event_year", "_event_time"],
        errors="ignore",
    ).to_csv(mapped_path, index=False)

    return registry_path, mapped_path


def test_sample_labels_match_frozen_design() -> None:
    assert sample_for_year(1998) == "discovery"
    assert sample_for_year(2014) == "discovery"
    assert sample_for_year(2015) == "validation"
    assert sample_for_year(2025) == "validation"
    assert sample_for_year(2026) == "forward"
    assert sample_for_year(2027) == "outside_sample"


def test_audit_years_include_forward_year_once() -> None:
    years = audit_years(
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    assert years[0] == 1998
    assert years[-1] == 2026
    assert len(years) == 29


def test_audit_year_validation_rejects_bad_ranges() -> None:
    with pytest.raises(ValueError, match="start_year"):
        audit_years(
            start_year=2025,
            end_year=1998,
            forward_year=2026,
        )
    with pytest.raises(ValueError, match="forward_year"):
        audit_years(
            start_year=1998,
            end_year=2025,
            forward_year=2025,
        )


def test_window_membership_is_inclusive_and_overlapping() -> None:
    assert event_is_in_window(-4, "demand_build_up")
    assert event_is_in_window(-4, "final_week")
    assert event_is_in_window(-4, "complete")
    assert not event_is_in_window(-4, "immediate")
    assert event_is_in_window(5, "first_postweek")
    assert event_is_in_window(5, "unwind")
    assert event_is_in_window(5, "complete")
    assert not event_is_in_window(0, "complete")


def test_loaders_require_project_schema(tmp_path: Path) -> None:
    bad_registry = tmp_path / "bad_registry.csv"
    pd.DataFrame([{"event_id": "x"}]).to_csv(
        bad_registry,
        index=False,
    )
    with pytest.raises(ValueError, match="missing required columns"):
        load_registry(bad_registry)

    bad_mapped = tmp_path / "bad_mapped.csv"
    pd.DataFrame([{"event_id": "x"}]).to_csv(
        bad_mapped,
        index=False,
    )
    with pytest.raises(ValueError, match="missing required columns"):
        load_mapped_events(bad_mapped)


def test_prepare_mapped_uses_registry_metadata() -> None:
    registry, prepared = prepared_frames()

    cpi = prepared.loc[prepared["event_id"].eq("cpi_1998")].iloc[
        0
    ]
    assert cpi["event_type"] == "cpi"
    assert cpi["sample"] == "discovery"
    assert bool(cpi["_known_time"]) is True
    assert set(prepared["event_id"]).issubset(
        set(registry["event_id"])
    )


def test_duplicate_registry_id_is_critical() -> None:
    registry = pd.concat(
        [registry_frame(), registry_frame().iloc[[0]]],
        ignore_index=True,
    )
    issues = collect_input_issues(
        registry,
        mapped_frame(),
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    assert (
        issues["issue_code"]
        .eq("duplicate_registry_event_id")
        .any()
    )
    assert issues.loc[
        issues["issue_code"].eq("duplicate_registry_event_id"),
        "severity",
    ].eq("critical").all()


def test_unknown_mapped_event_is_critical() -> None:
    mapped = pd.concat(
        [
            mapped_frame(),
            pd.DataFrame(
                [
                    mapped_row(
                        event_id="unknown",
                        event_year=2001,
                        event_time=-2,
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    mapped["_event_year"] = pd.to_numeric(
        mapped["event_year"]
    ).astype("Int64")
    mapped["_event_time"] = pd.to_numeric(
        mapped["event_time"]
    ).astype("Int64")

    issues = collect_input_issues(
        registry_frame(),
        mapped,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    assert (
        issues["issue_code"]
        .eq("mapped_event_missing_from_registry")
        .any()
    )


def test_zero_and_outside_grid_are_critical() -> None:
    mapped = mapped_frame()
    mapped.loc[0, ["event_time", "_event_time"]] = ["0", 0]
    mapped.loc[1, ["event_time", "_event_time"]] = ["21", 21]

    issues = collect_input_issues(
        registry_frame(),
        mapped,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    codes = set(issues["issue_code"])
    assert "mapped_event_time_zero" in codes
    assert "mapped_event_outside_grid" in codes


def test_invalid_registry_clock_is_critical() -> None:
    registry = registry_frame()
    registry.loc[0, "event_time_et"] = "8:30"
    issues = collect_input_issues(
        registry,
        mapped_frame(),
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    assert "invalid_registry_event_time" in set(
        issues["issue_code"]
    )


def test_series_year_coverage_distinguishes_gap_and_no_overlap() -> None:
    registry, mapped = prepared_frames()
    coverage = build_series_year_coverage(
        registry,
        mapped,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )

    cpi_1999 = coverage.loc[
        coverage["event_type"].eq("cpi")
        & coverage["event_year"].eq(1999)
    ].iloc[0]
    assert cpi_1999["coverage_status"] == (
        "gap_inside_observed_span"
    )

    jobs_2000 = coverage.loc[
        coverage["event_type"].eq("employment_situation")
        & coverage["event_year"].eq(2000)
    ].iloc[0]
    assert jobs_2000["coverage_status"] == (
        "gap_inside_observed_span"
    )

    jolts_1998 = coverage.loc[
        coverage["event_type"].eq("jolts")
        & coverage["event_year"].eq(1998)
    ].iloc[0]
    assert jolts_1998["coverage_status"] == (
        "outside_observed_span"
    )


def test_series_gaps_become_warning_rows() -> None:
    registry, mapped = prepared_frames()
    coverage = build_series_year_coverage(
        registry,
        mapped,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    issues = add_series_gap_issues(
        pd.DataFrame(columns=ISSUE_COLUMNS),
        coverage,
    )
    assert (
        issues["issue_code"]
        .eq("series_year_gap_inside_observed_span")
        .any()
    )
    assert issues["severity"].eq("warning").all()


def test_event_type_summary_reports_internal_gap_years() -> None:
    registry, mapped = prepared_frames()
    coverage = build_series_year_coverage(
        registry,
        mapped,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    summary = build_event_type_summary(
        registry,
        mapped,
        coverage,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    cpi = summary.loc[summary["event_type"].eq("cpi")].iloc[0]
    assert cpi["registry_events"] == 2
    assert cpi["mapped_events"] == 2
    assert cpi["internal_gap_years"] == "1999"


def test_window_coverage_has_all_year_window_combinations() -> None:
    _, mapped = prepared_frames()
    coverage = build_window_coverage(
        mapped,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    assert len(coverage) == 29 * len(WINDOWS)
    assert not coverage.duplicated(
        ["event_year", "window_name"]
    ).any()


def test_window_coverage_preserves_overlapping_windows() -> None:
    _, mapped = prepared_frames()
    coverage = build_window_coverage(
        mapped,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    year_1998 = coverage.loc[
        coverage["event_year"].eq(1998)
    ].set_index("window_name")

    assert year_1998.loc["demand_build_up", "event_count"] == 1
    assert year_1998.loc["final_week", "event_count"] == 2
    assert year_1998.loc["immediate", "event_count"] == 1
    assert year_1998.loc["complete", "event_count"] == 2


def test_year_summary_contains_clean_and_tier1_clean_flags() -> None:
    _, mapped = prepared_frames()
    window_coverage = build_window_coverage(
        mapped,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )
    summary = build_year_summary(
        mapped,
        window_coverage,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )

    year_2001 = summary.loc[
        summary["event_year"].eq(2001)
    ].iloc[0]
    assert bool(year_2001["complete_clean"]) is True
    assert bool(year_2001["complete_tier_1_clean"]) is True

    year_1998 = summary.loc[
        summary["event_year"].eq(1998)
    ].iloc[0]
    assert bool(year_1998["complete_clean"]) is False
    assert year_1998["complete_events"] == 2


def test_missing_mapped_release_time_is_warning() -> None:
    _, mapped = prepared_frames()
    issues = add_mapped_time_warning_issues(
        pd.DataFrame(columns=ISSUE_COLUMNS),
        mapped,
    )
    warning = issues.loc[
        issues["event_id"].eq("jobs_1999")
    ]
    assert len(warning) == 1
    assert warning.iloc[0]["severity"] == "warning"
    assert warning.iloc[0]["issue_code"] == (
        "mapped_event_missing_release_time"
    )


def test_run_audit_writes_all_outputs_and_manifest(
    tmp_path: Path,
) -> None:
    registry_path, mapped_path = write_inputs(tmp_path)
    output_dir = tmp_path / "processed"
    manifest_path = tmp_path / "manifest.json"

    manifest = run_audit(
        registry_path=registry_path,
        mapped_path=mapped_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        start_year=1998,
        end_year=2025,
        forward_year=2026,
    )

    expected_files = {
        "macro_coverage_by_series_year.csv",
        "macro_coverage_event_type_summary.csv",
        "labor_day_macro_coverage_by_year.csv",
        "labor_day_macro_coverage_by_window.csv",
        "macro_coverage_gaps.csv",
    }
    assert {
        path.name for path in output_dir.iterdir()
    } == expected_files
    assert manifest_path.exists()
    loaded = json.loads(manifest_path.read_text())
    assert loaded["audit_version"] == "1.0.0"
    assert loaded["row_counts"]["year_summary"] == 29
    assert loaded["row_counts"]["window_summary"] == (
        29 * len(WINDOWS)
    )
    assert manifest["status"] == "PASS_WITH_WARNINGS"


def test_run_audit_writes_failure_manifest_before_raising(
    tmp_path: Path,
) -> None:
    registry = registry_frame()
    registry = pd.concat(
        [registry, registry.iloc[[0]]],
        ignore_index=True,
    )
    registry_path, mapped_path = write_inputs(
        tmp_path,
        registry=registry,
    )
    output_dir = tmp_path / "processed"
    manifest_path = tmp_path / "manifest.json"

    with pytest.raises(CoverageAuditError, match="critical"):
        run_audit(
            registry_path=registry_path,
            mapped_path=mapped_path,
            output_dir=output_dir,
            manifest_path=manifest_path,
            start_year=1998,
            end_year=2025,
            forward_year=2026,
        )

    loaded = json.loads(manifest_path.read_text())
    assert loaded["status"] == "FAIL"
    assert loaded["issue_counts"]["critical"] > 0
    assert (output_dir / "macro_coverage_gaps.csv").exists()


def test_strict_warnings_can_fail_without_changing_manifest_status(
    tmp_path: Path,
) -> None:
    registry_path, mapped_path = write_inputs(tmp_path)
    output_dir = tmp_path / "processed"
    manifest_path = tmp_path / "manifest.json"

    with pytest.raises(CoverageAuditError, match="strict-warnings"):
        run_audit(
            registry_path=registry_path,
            mapped_path=mapped_path,
            output_dir=output_dir,
            manifest_path=manifest_path,
            start_year=1998,
            end_year=2025,
            forward_year=2026,
            strict_warnings=True,
        )

    loaded = json.loads(manifest_path.read_text())
    assert loaded["status"] == "PASS_WITH_WARNINGS"
