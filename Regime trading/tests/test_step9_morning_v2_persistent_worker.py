from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "RegimeTrading" / "scripts" / "step9_morning_v2_persistent_worker.py"
SPEC = importlib.util.spec_from_file_location("step9_morning_v2_persistent_worker_test", MODULE_PATH)
assert SPEC and SPEC.loader
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(root: Path, *, stage: str = "step9l", mode: str = "validation") -> dict[str, object]:
    source = root / "data" / "v2_validation" / "iteration_1" / "snapshots" / "prices_0940.db"
    ledger = root / "data" / "v2_validation" / "iteration_1" / "ledgers" / "l.db"
    source.parent.mkdir(parents=True, exist_ok=True)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"frozen-snapshot")
    return {
        "protocol": worker.PROTOCOL,
        "request_id": "validation_1_step9l_12345678",
        "stage": stage,
        "mode": mode,
        "session_date": "2026-07-30",
        "as_of": "2026-07-30T09:45:20+02:00",
        "allow_late_reconstruction": True,
        "defer_core_regime_sensitivity": stage == "step9l",
        "source_db": source.relative_to(root).as_posix(),
        "ledger_db": ledger.relative_to(root).as_posix(),
        "source_sha256": _hash(source),
        "router_active": False,
        "orders_enabled": False,
    }


def test_validation_request_is_hash_pinned_and_root_bounded(tmp_path: Path) -> None:
    request = _request(tmp_path)
    namespace = worker._validate_request(
        request=request,
        stage="step9l",
        mode="validation",
        root=tmp_path.resolve(),
    )
    assert namespace.date == "2026-07-30"
    assert namespace.allow_late_reconstruction is True
    assert namespace.source_db.is_file()
    assert namespace.ledger_db.parent.is_dir()
    assert namespace.source_sha256 == request["source_sha256"]


def test_validation_request_rejects_hash_mismatch(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["source_sha256"] = "0" * 64
    with pytest.raises(worker.PersistentWorkerError, match="hash mismatch"):
        worker._validate_request(
            request=request,
            stage="step9l",
            mode="validation",
            root=tmp_path.resolve(),
        )


def test_live_request_rejects_late_reconstruction(tmp_path: Path) -> None:
    source = (
        tmp_path
        / "data"
        / "step9_morning_v2_snapshots"
        / "2026-08-03"
        / "prices_through_0940.db"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"live-snapshot")
    request = {
        "protocol": worker.PROTOCOL,
        "request_id": "live_20260803_step9l_12345678",
        "stage": "step9l",
        "mode": "live",
        "session_date": "2026-08-03",
        "as_of": "",
        "allow_late_reconstruction": True,
        "defer_core_regime_sensitivity": True,
        "source_db": source.relative_to(tmp_path).as_posix(),
        "ledger_db": "data/ledgers/prospective/step9l_v3_selected_strategy_shadow_ledger.db",
        "source_sha256": _hash(source),
        "router_active": False,
        "orders_enabled": False,
    }
    with pytest.raises(worker.PersistentWorkerError, match="cannot allow late"):
        worker._validate_request(
            request=request,
            stage="step9l",
            mode="live",
            root=tmp_path.resolve(),
        )


def test_request_rejects_router_or_order_activation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["router_active"] = True
    with pytest.raises(worker.PersistentWorkerError, match="routing"):
        worker._validate_request(
            request=request,
            stage="step9l",
            mode="validation",
            root=tmp_path.resolve(),
        )


def test_step9l_request_requires_sensitivity_deferral(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["defer_core_regime_sensitivity"] = False
    with pytest.raises(worker.PersistentWorkerError, match="requires deadline-path"):
        worker._validate_request(
            request=request,
            stage="step9l",
            mode="validation",
            root=tmp_path.resolve(),
        )


def test_step9i_request_rejects_step9l_sensitivity_deferral(tmp_path: Path) -> None:
    request = _request(tmp_path, stage="step9i")
    request["defer_core_regime_sensitivity"] = True
    with pytest.raises(worker.PersistentWorkerError, match="Step 9I worker cannot defer"):
        worker._validate_request(
            request=request,
            stage="step9i",
            mode="validation",
            root=tmp_path.resolve(),
        )
