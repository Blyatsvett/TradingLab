from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from RegimeTrading.core.stage_registry import PROJECT_ROOT, resolve_stage_path

PROTOCOL = "STEP9_MORNING_V2_PERSISTENT_WORKER_V1"
READY_STATUS = "STEP9_MORNING_V2_PERSISTENT_WORKER_READY"
SUCCESS_STATUS = "STEP9_MORNING_V2_PERSISTENT_WORKER_STAGE_PASSED"
FAILURE_STATUS = "STEP9_MORNING_V2_PERSISTENT_WORKER_STAGE_FAILED"
SESSION_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STAGE_MODULES = {
    "step9i": "RegimeTrading.scripts.step9i_v2_core5_plus_holdout18_shadow_router",
    "step9l": "RegimeTrading.scripts.step9l_v3_selected_strategy_shadow_engine",
}
LIVE_LEDGERS = {
    "step9i": resolve_stage_path("step9i"),
    "step9l": resolve_stage_path("step9l"),
}


class PersistentWorkerError(RuntimeError):
    """Fail-closed worker protocol error."""


def _write_json_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_under_root(root: Path, raw: object, label: str) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise PersistentWorkerError(f"Worker request is missing {label}.")
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not _is_within(resolved, root):
        raise PersistentWorkerError(f"Worker request {label} escaped project root: {resolved}")
    return resolved


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _validate_module_location(module: object, root: Path, label: str) -> str:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise PersistentWorkerError(f"{label} has no import path.")
    resolved = Path(module_file).resolve()
    if not _is_within(resolved, root):
        raise PersistentWorkerError(f"{label} import escaped project root: {resolved}")
    return str(resolved)


def _load_request(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersistentWorkerError(f"Worker request JSON is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise PersistentWorkerError("Worker request JSON must contain an object.")
    return payload


def _validate_request(
    *,
    request: dict[str, Any],
    stage: str,
    mode: str,
    root: Path,
) -> SimpleNamespace:
    if request.get("protocol") != PROTOCOL:
        raise PersistentWorkerError("Worker request protocol does not match.")
    if request.get("stage") != stage:
        raise PersistentWorkerError("Worker request stage does not match worker stage.")
    if request.get("mode") != mode:
        raise PersistentWorkerError("Worker request mode does not match worker mode.")
    request_id = str(request.get("request_id", "")).strip()
    if not request_id or not re.fullmatch(r"[A-Za-z0-9_.-]{8,128}", request_id):
        raise PersistentWorkerError("Worker request ID is invalid.")
    session_date = str(request.get("session_date", "")).strip()
    if not SESSION_DATE_PATTERN.fullmatch(session_date):
        raise PersistentWorkerError("Worker request session date is invalid.")
    if bool(request.get("router_active", True)):
        raise PersistentWorkerError("Worker request attempted to activate routing.")
    if bool(request.get("orders_enabled", True)):
        raise PersistentWorkerError("Worker request attempted to enable orders.")

    source_db = _resolve_under_root(root, request.get("source_db"), "source_db")
    ledger_db = _resolve_under_root(root, request.get("ledger_db"), "ledger_db")
    if not source_db.is_file():
        raise PersistentWorkerError(f"Worker source database is missing: {source_db}")
    expected_hash = str(request.get("source_sha256", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise PersistentWorkerError("Worker request source SHA-256 is invalid.")
    actual_hash = _sha256(source_db)
    if actual_hash != expected_hash:
        raise PersistentWorkerError(
            f"Worker source hash mismatch: expected={expected_hash} actual={actual_hash}"
        )

    allow_late = bool(request.get("allow_late_reconstruction", False))
    defer_sensitivity = bool(request.get("defer_core_regime_sensitivity", False))
    if stage == "step9i" and defer_sensitivity:
        raise PersistentWorkerError(
            "Step 9I worker cannot defer Step 9L sensitivity diagnostics."
        )
    if stage == "step9l" and not defer_sensitivity:
        raise PersistentWorkerError(
            "Step 9L worker requires deadline-path sensitivity deferral."
        )
    as_of = str(request.get("as_of", "")).strip()
    source_relative = _relative_posix(source_db, root)
    ledger_relative = _relative_posix(ledger_db, root)

    if mode == "live":
        expected_source = (
            Path("data")
            / "step9_morning_v2_snapshots"
            / session_date
            / "prices_through_0940.db"
        ).as_posix()
        expected_ledger = LIVE_LEDGERS[stage].relative_to(PROJECT_ROOT).as_posix()
        if source_relative.lower() != expected_source.lower():
            raise PersistentWorkerError(
                f"Live worker source path is not canonical: {source_relative}"
            )
        if ledger_relative.lower() != expected_ledger.lower():
            raise PersistentWorkerError(
                f"Live worker ledger path is not canonical: {ledger_relative}"
            )
        if allow_late:
            raise PersistentWorkerError("Live worker cannot allow late reconstruction.")
        if as_of:
            raise PersistentWorkerError("Live worker cannot use a simulated clock.")
    else:
        validation_root = (root / "data" / "v2_validation").resolve()
        if not _is_within(source_db, validation_root):
            raise PersistentWorkerError("Validation worker source is outside v2_validation.")
        if not _is_within(ledger_db, validation_root):
            raise PersistentWorkerError("Validation worker ledger is outside v2_validation.")
        if not allow_late:
            raise PersistentWorkerError(
                "Validation worker requires explicit late-reconstruction permission."
            )
        if not as_of:
            raise PersistentWorkerError("Validation worker requires a simulated clock.")

    ledger_db.parent.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        date=session_date,
        as_of=as_of,
        allow_late_reconstruction=allow_late,
        source_db=source_db,
        ledger_db=ledger_db,
        json_out=None,
        request_id=request_id,
        source_sha256=actual_hash,
        defer_core_regime_sensitivity=defer_sensitivity,
    )


def _wait_for_request(path: Path, timeout_seconds: float, poll_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(poll_seconds)
    raise PersistentWorkerError(
        f"Worker request was not released within {timeout_seconds:.1f} seconds: {path}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persistent, pre-imported Step 9I/9L Morning V2 worker."
    )
    parser.add_argument("--stage", choices=sorted(STAGE_MODULES), required=True)
    parser.add_argument("--mode", choices=("live", "validation"), required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--ready-json", type=Path, required=True)
    parser.add_argument("--request-json", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--request-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-milliseconds", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.project_root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Project root is missing: {root}")
    if not _is_within(args.ready_json.resolve(), root):
        raise SystemExit("Worker ready JSON must be inside project root.")
    if not _is_within(args.request_json.resolve(), root):
        raise SystemExit("Worker request JSON must be inside project root.")
    if not _is_within(args.result_json.resolve(), root):
        raise SystemExit("Worker result JSON must be inside project root.")
    if args.request_json.exists() or args.result_json.exists() or args.ready_json.exists():
        raise SystemExit("Worker protocol paths must not exist before worker startup.")
    if args.request_timeout_seconds <= 0:
        raise SystemExit("Worker request timeout must be positive.")
    if args.poll_milliseconds < 20 or args.poll_milliseconds > 1000:
        raise SystemExit("Worker poll interval must be between 20 and 1000 ms.")

    started_monotonic = time.monotonic()
    try:
        from RegimeTrading.scripts import step9_morning_v2_stage_runner as runner

        target_module = __import__(STAGE_MODULES[args.stage], fromlist=["*"])
        runner_path = _validate_module_location(runner, root, "stage runner")
        target_path = _validate_module_location(target_module, root, args.stage)
        ready_payload = {
            "protocol": PROTOCOL,
            "status": READY_STATUS,
            "stage": args.stage,
            "mode": args.mode,
            "worker_pid": os.getpid(),
            "project_root": str(root),
            "runner_path": runner_path,
            "target_module_path": target_path,
            "ready_seconds": round(time.monotonic() - started_monotonic, 3),
            "router_active": False,
            "orders_enabled": False,
        }
        _write_json_atomic(ready_payload, args.ready_json)

        _wait_for_request(
            args.request_json,
            timeout_seconds=args.request_timeout_seconds,
            poll_seconds=args.poll_milliseconds / 1000.0,
        )
        request = _load_request(args.request_json)
        namespace = _validate_request(
            request=request,
            stage=args.stage,
            mode=args.mode,
            root=root,
        )
        released_monotonic = time.monotonic()
        handler = runner._step9i if args.stage == "step9i" else runner._step9l
        stage_payload = handler(namespace)
        result = dict(stage_payload)
        result.update(
            {
                "protocol": PROTOCOL,
                "status": SUCCESS_STATUS,
                "mode": args.mode,
                "request_id": namespace.request_id,
                "source_sha256": namespace.source_sha256,
                "worker_pid": os.getpid(),
                "worker_ready_seconds": ready_payload["ready_seconds"],
                "released_stage_seconds": round(
                    time.monotonic() - released_monotonic, 3
                ),
                "router_active": False,
                "orders_enabled": False,
            }
        )
        _write_json_atomic(result, args.result_json)
        print(json.dumps(result, indent=2, sort_keys=True))
    except BaseException as exc:
        failure = {
            "protocol": PROTOCOL,
            "status": FAILURE_STATUS,
            "stage": args.stage,
            "mode": args.mode,
            "worker_pid": os.getpid(),
            "error": f"{type(exc).__name__}: {exc}",
            "router_active": False,
            "orders_enabled": False,
        }
        try:
            _write_json_atomic(failure, args.result_json)
        except BaseException:
            pass
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
