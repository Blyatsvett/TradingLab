from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "tools/verify_and_freeze_step9s_historical_replay_v1.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("step9s_freeze_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_historical_outputs_pass_full_audit_and_freeze(tmp_path: Path) -> None:
    module = _load_module()
    result = module.audit_and_freeze(PROJECT_ROOT, tmp_path)
    assert result["sessions"] == 60
    assert result["regimes"] == 9
    assert result["natural_trades"] == 59
    assert result["mandatory_coverage_trades"] == 60
    assert result["complete_trade_coverage_rate"] == 1.0
    assert result["blocking_checks_passed"] == result["blocking_checks"]
    assert result["protected_files_byte_for_byte_unchanged"] is True
    assert result["router_active"] is False
    assert result["orders_sent"] is False
    assert Path(result["manifest_path"]).is_file()
    assert Path(result["summary_path"]).is_file()


def test_freeze_id_is_deterministic_for_identical_outputs(tmp_path: Path) -> None:
    module = _load_module()
    first = module.audit_and_freeze(PROJECT_ROOT, tmp_path)
    second = module.audit_and_freeze(PROJECT_ROOT, tmp_path)
    assert first["freeze_id"] == second["freeze_id"]
    assert first["artifact_set_sha256"] == second["artifact_set_sha256"]
    assert first["freeze_directory"] == second["freeze_directory"]
