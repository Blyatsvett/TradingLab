from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as step9t
from RegimeTrading.scripts import step9u_prospective_contingency_selector_v1 as step9u
from tools import check_step9tu_morning_readiness_v1 as safety

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _now(value: str) -> datetime:
    return pd.Timestamp(value).tz_convert(STOCKHOLM).to_pydatetime()


def test_readiness_reproduces_july28_contract() -> None:
    payload = safety.compute_readiness("2026-07-28", require_unsealed=False)
    assert payload["source_regime"] == "TREND_DOWN"
    assert payload["transition_state"] == "WEAKNESS_PERSISTING"
    assert payload["ticker_rows"] == 29
    assert payload["directional_candidates"] == 22
    assert payload["selectable_candidates"] == 0
    assert payload["selected_count"] == 0
    assert payload["selected_tickers"] == []


def test_readiness_is_read_only_for_real_prospective_ledgers() -> None:
    before_t = step9t.DEFAULT_LEDGER_DB.read_bytes() if step9t.DEFAULT_LEDGER_DB.is_file() else None
    before_u = step9u.DEFAULT_LEDGER_DB.read_bytes() if step9u.DEFAULT_LEDGER_DB.is_file() else None
    safety.compute_readiness("2026-07-28", require_unsealed=False)
    after_t = step9t.DEFAULT_LEDGER_DB.read_bytes() if step9t.DEFAULT_LEDGER_DB.is_file() else None
    after_u = step9u.DEFAULT_LEDGER_DB.read_bytes() if step9u.DEFAULT_LEDGER_DB.is_file() else None
    assert after_t == before_t
    assert after_u == before_u


def test_readiness_refuses_existing_session() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "step9t.db"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE step9t_prospective_batches(session_date TEXT)")
            connection.execute("INSERT INTO step9t_prospective_batches VALUES ('2026-07-28')")
            connection.commit()
        with pytest.raises(safety.MorningSafetyError, match="already sealed"):
            safety.compute_readiness(
                "2026-07-28",
                step9t_ledger_db=path,
                step9u_ledger_db=Path(temp_dir) / "step9u.db",
                require_unsealed=True,
            )


def test_preview_and_temporary_seal_are_identical() -> None:
    preview = safety.compute_readiness("2026-07-28", require_unsealed=False)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ledger_t = root / "step9t.db"
        ledger_u = root / "step9u.db"
        step9t.seal_morning_snapshot(
            session_date="2026-07-28",
            now=_now("2026-07-28 09:48:00+02:00"),
            ledger_db=ledger_t,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        step9u.seal_morning_selection(
            session_date="2026-07-28",
            now=_now("2026-07-28 09:48:10+02:00"),
            step9t_ledger_db=ledger_t,
            ledger_db=ledger_u,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        result = safety.verify_sealed(
            "2026-07-28", preview, step9t_ledger_db=ledger_t, step9u_ledger_db=ledger_u
        )
        assert result["status"] == "SEALED_AND_VERIFIED"
        assert result["directional_candidates"] == 22
        assert result["selected_count"] == 0
        assert result["step9t_audit_passed"] > 0
        assert result["step9u_audit_passed"] > 0


def test_verify_sealed_rejects_preview_mismatch() -> None:
    preview = safety.compute_readiness("2026-07-28", require_unsealed=False)
    preview["morning_price_snapshot_hash"] = "0" * 64
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ledger_t = root / "step9t.db"
        ledger_u = root / "step9u.db"
        step9t.seal_morning_snapshot(
            session_date="2026-07-28",
            now=_now("2026-07-28 09:48:00+02:00"),
            ledger_db=ledger_t,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        step9u.seal_morning_selection(
            session_date="2026-07-28",
            now=_now("2026-07-28 09:48:10+02:00"),
            step9t_ledger_db=ledger_t,
            ledger_db=ledger_u,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        with pytest.raises(safety.MorningSafetyError, match="morning_price_snapshot_hash"):
            safety.verify_sealed(
                "2026-07-28", preview, step9t_ledger_db=ledger_t, step9u_ledger_db=ledger_u
            )


def test_json_output_is_stable_and_safe(tmp_path: Path) -> None:
    payload = safety.compute_readiness("2026-07-28", require_unsealed=False)
    target = tmp_path / "preview.json"
    safety._write_json(payload, target)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["status"] == "READY_FOR_POINT_IN_TIME_SEAL"
    assert loaded["mandatory_control_active"] is False
    assert loaded["router_active"] is False
    assert loaded["orders_enabled"] is False
