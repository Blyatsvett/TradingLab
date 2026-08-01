from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from pathlib import Path

import pandas as pd

from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as step9l


def _fake_batch() -> pd.DataFrame:
    return pd.DataFrame(
        [{"session_date": "2026-07-30", "primary_regime": "HIGH_VOL_REVERSAL", "regime_confidence": 0.5}]
    )


def _fake_decisions() -> pd.DataFrame:
    return pd.DataFrame(
        [{"ticker": "BOL.ST", "decision_action": "ELIGIBLE_FOR_EOD_TRIGGER_EVALUATION"}]
    )


def test_step9i_can_defer_sensitivity_without_changing_decision_seal(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(step9i, "_patched_base", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        step9i.base,
        "seal_morning_decisions",
        lambda **kwargs: (_fake_batch(), _fake_decisions(), True),
    )
    monkeypatch.setattr(
        step9i,
        "_build_core_regime_sensitivity",
        lambda *args, **kwargs: calls.append("build") or pd.DataFrame([{"company_id": "A"}]),
    )
    monkeypatch.setattr(step9i, "_seal_sensitivity_rows", lambda *args, **kwargs: calls.append("seal"))

    batches, decisions, inserted = step9i.seal_morning_decisions(
        target_date="2026-07-30",
        now=object(),
        prices=pd.DataFrame([{"date": "2026-07-30", "ticker": "BOL.ST"}]),
        ledger_db=tmp_path / "l.db",
        source_db=tmp_path / "prices.db",
        include_core_regime_sensitivity=False,
        export_outputs_after=False,
    )
    assert inserted is True
    assert len(batches) == 1 and len(decisions) == 1
    assert calls == []


def test_step9i_default_preserves_sensitivity_completion(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(step9i, "_patched_base", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        step9i.base,
        "seal_morning_decisions",
        lambda **kwargs: (_fake_batch(), _fake_decisions(), True),
    )
    monkeypatch.setattr(
        step9i,
        "_build_core_regime_sensitivity",
        lambda *args, **kwargs: calls.append("build") or pd.DataFrame([{"company_id": "A"}]),
    )
    monkeypatch.setattr(step9i, "_seal_sensitivity_rows", lambda *args, **kwargs: calls.append("seal"))
    step9i.seal_morning_decisions(
        target_date="2026-07-30",
        now=object(),
        prices=pd.DataFrame([{"date": "2026-07-30", "ticker": "BOL.ST"}]),
        ledger_db=tmp_path / "l.db",
        source_db=tmp_path / "prices.db",
        export_outputs_after=False,
    )
    assert calls == ["build", "seal"]


def test_deferred_completion_requires_one_sealed_batch_and_is_idempotent_boundary(monkeypatch, tmp_path: Path) -> None:
    ledger = tmp_path / "l.db"
    with sqlite3.connect(ledger) as con:
        con.execute(
            "CREATE TABLE shadow_decision_batches (session_date TEXT, primary_regime TEXT, regime_confidence REAL)"
        )
        con.execute(
            "INSERT INTO shadow_decision_batches VALUES (?, ?, ?)",
            ("2026-07-30", "HIGH_VOL_REVERSAL", 0.5),
        )
        con.commit()
    monkeypatch.setattr(step9i, "_ensure_ledger_schema", lambda con: None)
    expected = pd.DataFrame([{"company_id": "A"}])
    monkeypatch.setattr(step9i, "_build_core_regime_sensitivity", lambda *args, **kwargs: expected)
    sealed: list[int] = []
    monkeypatch.setattr(step9i, "_seal_sensitivity_rows", lambda path, frame: sealed.append(len(frame)))
    result = step9i.complete_core_regime_sensitivity(
        target_date="2026-07-30",
        prices=pd.DataFrame(),
        ledger_db=ledger,
    )
    assert result.equals(expected)
    assert sealed == [1]


def test_step9l_wrapper_forwards_deferred_flag(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(step9l, "_patched_step9l_v3_globals", lambda: nullcontext())

    def fake_seal(**kwargs):
        captured.update(kwargs)
        return _fake_batch(), _fake_decisions(), True

    monkeypatch.setattr(step9l.step9i, "seal_morning_decisions", fake_seal)
    step9l.seal_morning_decisions(
        target_date="2026-07-30",
        now=object(),
        prices=pd.DataFrame(),
        ledger_db=tmp_path / "l.db",
        source_db=tmp_path / "prices.db",
        export_outputs_after=False,
        include_core_regime_sensitivity=False,
    )
    assert captured["include_core_regime_sensitivity"] is False
