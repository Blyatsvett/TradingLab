"""Validate the Regime Trading canonical pipeline contract.

This check is intentionally stdlib-only so it can run before the project
virtual environment is available. It validates configuration, path ownership,
the research-only execution boundary, and the documented current entry points.
It does not require local market data or import third-party packages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CANONICAL_STAGES = ("step9i", "step9l", "step9s", "step9r", "step9t", "step9u", "step9v")
REQUIRED_ENTRY_POINTS = (
    "run_step9_full_live_morning_v2.ps1",
    "run_step9_full_tonight_preflight_v2.ps1",
    "run_step9_morning_v2_validation.ps1",
    "run_step9_morning_mock_fallback_v2.ps1",
    "run_step9i_v2_morning_shadow_router.ps1",
    "run_step9l_v3_morning_research_engine.ps1",
    "run_step9s_prospective_morning.ps1",
    "run_step9r_v1_prospective_shadow.ps1",
    "run_step9t_prospective_snapshot_v1.ps1",
    "run_step9u_prospective_selection_v1.ps1",
    "run_step9v_checkpoint_v1.ps1",
    "run_step9q_powerbi_snapshot.ps1",
    "run_step9kpi_read_only_evaluation_v1.ps1",
)
REQUIRED_DOCUMENTS = (
    "docs/ACTIVE_SYSTEM_GUIDE.md",
    "docs/REPRODUCIBILITY.md",
    "docs/DATA_SEPARATION_MAP.md",
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _project_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_canonical_pipeline(project_root: Path) -> list[str]:
    """Return contract violations for the canonical Regime Trading system."""

    project_root = project_root.resolve()
    errors: list[str] = []
    config_dir = project_root / "config"
    paths_file = config_dir / "paths.json"
    registry_file = config_dir / "stage_registry.json"

    if not paths_file.is_file():
        errors.append(f"Missing path configuration: {paths_file}")
        return errors
    if not registry_file.is_file():
        errors.append(f"Missing stage registry: {registry_file}")
        return errors

    paths = _load_json(paths_file)
    registry = _load_json(registry_file)
    data_root = _project_path(project_root, str(paths.get("data_dir", "data")))

    for key in ("market_source_dir", "reference_data_dir", "reconciliation_data_dir"):
        if key not in paths:
            errors.append(f"paths.json is missing {key!r}")
        elif not _inside(_project_path(project_root, str(paths[key])), data_root):
            errors.append(f"{key} must remain inside the project data tree")

    for key in ("shadow_output_dirs", "legacy_output_dirs", "freeze_dirs"):
        groups = paths.get(key, {})
        if not isinstance(groups, dict):
            errors.append(f"paths.json field {key!r} must be an object")
            continue
        for name, value in groups.items():
            if not _inside(_project_path(project_root, str(value)), data_root):
                errors.append(f"{key}.{name} must remain inside the project data tree")

    if registry.get("version") != 1:
        errors.append("stage_registry.json must use version 1")
    if registry.get("orders_enabled") is not False:
        errors.append("stage_registry.json must keep orders_enabled=false")
    if registry.get("router_active") is not False:
        errors.append("stage_registry.json must keep router_active=false")

    stage_order = tuple(registry.get("stage_order", ()))
    if stage_order != CANONICAL_STAGES:
        errors.append(f"stage_order must equal {CANONICAL_STAGES!r}")

    stages = registry.get("stages", {})
    ledgers = registry.get("ledger_paths", {})
    output_dirs = registry.get("output_dirs", {})
    if not isinstance(stages, dict) or not isinstance(ledgers, dict) or not isinstance(output_dirs, dict):
        errors.append("stage registry stages, ledger_paths, and output_dirs must be objects")
    else:
        for stage in CANONICAL_STAGES:
            definition = stages.get(stage)
            if not isinstance(definition, dict):
                errors.append(f"Missing stage definition: {stage}")
                continue
            ledger_key = definition.get("ledger")
            if ledger_key not in ledgers:
                errors.append(f"{stage} refers to missing ledger mapping {ledger_key!r}")
            if stage not in output_dirs:
                errors.append(f"{stage} has no output directory")

        for name, value in ledgers.items():
            resolved = _project_path(project_root, str(value))
            allowed = data_root / "ledgers"
            if name == "prices":
                allowed = data_root / "source" / "market"
            if not _inside(resolved, allowed):
                errors.append(f"ledger_paths.{name} must remain in {allowed.relative_to(project_root)}")

        for name, value in output_dirs.items():
            resolved = _project_path(project_root, str(value))
            if not _inside(resolved, data_root / "outputs"):
                errors.append(f"output_dirs.{name} must remain under data/outputs")

    expected_outputs = {
        "step9i": data_root / "outputs" / "shadow" / "step9i_v2",
        "step9l": data_root / "outputs" / "shadow" / "step9l_v3",
    }
    for stage, expected in expected_outputs.items():
        actual = _project_path(project_root, str(output_dirs.get(stage, "")))
        if actual != expected.resolve():
            errors.append(f"output_dirs.{stage} must be {expected.relative_to(project_root)}")

    for relative in REQUIRED_ENTRY_POINTS + REQUIRED_DOCUMENTS:
        if not (project_root / relative).is_file():
            errors.append(f"Missing canonical project file: {relative}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate_canonical_pipeline(args.project_root)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("CANONICAL PIPELINE CONTRACT: PASSED")
    print("STAGES: " + " -> ".join(CANONICAL_STAGES))
    print("RESEARCH-ONLY BOUNDARY: orders_enabled=false, router_active=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
