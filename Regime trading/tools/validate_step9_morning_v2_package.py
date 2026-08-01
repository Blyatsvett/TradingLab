from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


class PackageValidationError(RuntimeError):
    pass


REQUIRED_FILES = {
    "RegimeTrading/scripts/step9_morning_v2_stage_runner.py",
    "config/step9_morning_v2_runtime_manifest.json",
    "register_step9_morning_v2_tasks.ps1",
    "run_step9_full_live_morning_v2.ps1",
    "run_step9_full_tonight_preflight_v2.ps1",
    "run_step9_morning_mock_fallback_v2.ps1",
    "run_step9_morning_v2_validation.ps1",
    "tests/test_step9_morning_v2_install_contract.py",
    "tests/test_step9_morning_v2_support.py",
    "tests/fixtures/step9_morning_v2_20260730_prices.csv",
    "tests/fixtures/step9_morning_v2_20260730_prices.manifest.json",
    "tools/step9_morning_v2_support.py",
    "tools/validate_step9_morning_v2_package.py",
    "STEP9_FULL_LIVE_MORNING_ORCHESTRATOR_V2_README.md",
}

REQUIRED_RUNTIME_CLOSURE = {
    "RegimeTrading/scripts/step9_morning_v2_stage_runner.py",
    "run_step9_full_live_morning_v2.ps1",
    "run_step9_full_tonight_preflight_v2.ps1",
    "run_step9_morning_mock_fallback_v2.ps1",
    "run_step9_morning_v2_validation.ps1",
    "register_step9_morning_v2_tasks.ps1",
    "tools/step9_morning_v2_support.py",
    "data/archives/freezes/step9s_historical_contingency_replay_v1/freeze_v1/9b045fb10e196a38/step9s_historical_output_freeze_summary.json",
    "data/archives/freezes/step9u_historical_contingency_selector_v1/freeze_8042ad803be28ccf/STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1_FREEZE_MANIFEST.json",
}

FORBIDDEN_SUFFIXES = {
    ".wal",
    ".shm",
    ".journal",
    ".exe",
    ".dll",
    ".pyd",
    ".pyc",
}

SQLITE_ARTIFACT_PATTERN = re.compile(
    r"\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$",
    flags=re.IGNORECASE,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise PackageValidationError(f"Unsafe package path: {relative}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PackageValidationError(
            f"Package path escapes the payload root: {relative}"
        ) from exc
    return resolved


def validate(payload_root: Path, manifest_path: Path) -> dict[str, Any]:
    payload_root = payload_root.resolve()
    manifest_path = manifest_path.resolve()
    if not payload_root.is_dir():
        raise PackageValidationError(f"Payload root is missing: {payload_root}")
    if not manifest_path.is_file():
        raise PackageValidationError(f"Package manifest is missing: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise PackageValidationError("Package manifest contains no files.")

    listed = set(str(item).replace("\\", "/") for item in files)
    missing_required = sorted(REQUIRED_FILES - listed)
    if missing_required:
        raise PackageValidationError(
            "Required payload files are not listed: " + ", ".join(missing_required)
        )

    actual = {
        path.relative_to(payload_root).as_posix()
        for path in payload_root.rglob("*")
        if path.is_file() and path.resolve() != manifest_path
    }
    if actual != listed:
        missing = sorted(listed - actual)
        extra = sorted(actual - listed)
        raise PackageValidationError(
            f"Package inventory mismatch. Missing={missing}; unlisted={extra}"
        )

    python_files: list[str] = []
    powershell_files: list[str] = []
    json_files: list[str] = []
    for relative, expected_hash in sorted(files.items()):
        normalized = str(relative).replace("\\", "/")
        path = safe_path(payload_root, normalized)
        suffix = path.suffix.lower()
        if (
            suffix in FORBIDDEN_SUFFIXES
            or SQLITE_ARTIFACT_PATTERN.search(path.name)
            or normalized.lower().startswith("data/")
        ):
            raise PackageValidationError(
                f"Forbidden binary, ledger, or data artifact in payload: {normalized}"
            )
        if sha256(path) != str(expected_hash).lower():
            raise PackageValidationError(f"Payload hash mismatch: {normalized}")

        if suffix == ".py":
            source = path.read_text(encoding="utf-8-sig")
            compile(source, str(path), "exec", dont_inherit=True)
            python_files.append(normalized)
        elif suffix == ".ps1":
            raw = path.read_bytes()
            if any(byte > 127 for byte in raw):
                raise PackageValidationError(
                    f"PowerShell file must be ASCII-safe for Windows PowerShell 5.1: "
                    f"{normalized}"
                )
            powershell_files.append(normalized)
        elif suffix == ".json":
            json.loads(path.read_text(encoding="utf-8-sig"))
            json_files.append(normalized)

    runtime_manifest = json.loads(
        (payload_root / "config" / "step9_morning_v2_runtime_manifest.json").read_text(
            encoding="utf-8-sig"
        )
    )
    runtime_files = runtime_manifest.get("files")
    if not isinstance(runtime_files, dict) or len(runtime_files) < 35:
        raise PackageValidationError(
            "Runtime compatibility manifest does not cover the audited dependency closure."
        )
    runtime_names = {
        str(relative).replace("\\", "/") for relative in runtime_files
    }
    missing_runtime = sorted(REQUIRED_RUNTIME_CLOSURE - runtime_names)
    if missing_runtime:
        raise PackageValidationError(
            "Runtime compatibility manifest omits required V2 dependencies: "
            + ", ".join(missing_runtime)
        )

    return {
        "status": "STEP9_MORNING_V2_PACKAGE_VALIDATION_PASSED",
        "package_id": str(manifest.get("package_id", "")),
        "payload_files": len(files),
        "python_files_compiled": len(python_files),
        "powershell_files_ascii_safe": len(powershell_files),
        "json_files_parsed": len(json_files),
        "runtime_dependencies_covered": len(runtime_files),
        "contains_database_or_ledger": False,
        "router_active": False,
        "orders_enabled": False,
    }


def write_json(payload: dict[str, Any], path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temp, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the self-contained Step 9 Morning V2 payload."
    )
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = validate(args.payload_root, args.manifest)
    write_json(payload, args.json_out)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
