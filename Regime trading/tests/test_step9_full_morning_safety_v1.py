from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_step9_full_morning_chain_v1",
    ROOT / "tools" / "check_step9_full_morning_chain_v1.py",
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _make_db(path: Path, sql: str, rows: list[tuple]) -> None:
    with sqlite3.connect(path) as con:
        con.executescript(sql)
        if rows:
            placeholders = ",".join("?" for _ in rows[0])
            con.executemany(f"INSERT INTO t VALUES ({placeholders})", rows)
        con.commit()


def test_single_accepts_zero_or_one() -> None:
    assert mod._single([], "x") is None
    assert mod._single([{"a": 1}], "x") == {"a": 1}


def test_single_rejects_duplicates() -> None:
    with pytest.raises(mod.FullMorningSafetyError):
        mod._single([{"a": 1}, {"a": 2}], "x")


def test_rows_is_read_only_and_filters_session(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE batches(session_date TEXT, value INTEGER)")
        con.executemany("INSERT INTO batches VALUES (?,?)", [("2026-07-30", 1), ("2026-07-31", 2)])
        con.commit()
    rows = mod._rows(db, "batches", "2026-07-30")
    assert rows == [{"session_date": "2026-07-30", "value": 1}]


def test_missing_table_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    with sqlite3.connect(db):
        pass
    assert mod._rows(db, "missing", "2026-07-30") == []


def test_readme_distinguishes_step9s_and_step9u_controls() -> None:
    text = (ROOT / "STEP9_FULL_MORNING_SAFETY_V1_README.md").read_text(encoding="utf-8")
    assert "Step 9S has exactly one mandatory benchmark/control plan" in text
    assert "Step 9U has no mandatory control" in text


def test_live_wrapper_uses_project_venv_and_no_late_reconstruction() -> None:
    text = (ROOT / "run_step9_full_live_morning_v1.ps1").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "allow-late-reconstruction" not in text.lower()
    assert "run_step9tu_live_morning_v1.ps1" in text
    assert "FAILED_RETRY_ONLY_STEP9Q" in text
