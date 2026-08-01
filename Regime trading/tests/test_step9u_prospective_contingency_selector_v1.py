from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.core.stage_registry import resolve_stage_path
from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as step9t
from RegimeTrading.scripts import step9u_prospective_contingency_selector_v1 as step9u


STOCKHOLM = ZoneInfo("Europe/Stockholm")
SOURCE_DB = DATA_DIR / "step9i_shadow_intraday_prices.db"
STEP9L_LEDGER = resolve_stage_path("step9l")


def _now(value: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(STOCKHOLM)
    return timestamp.tz_convert(STOCKHOLM).to_pydatetime()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_row(
    ticker: str,
    sector: str,
    archetype: str,
    early: float,
    last5: float,
    direction: str = "LONG",
) -> dict:
    return {
        "session_date": "2026-01-02",
        "ticker": ticker,
        "company_id": ticker,
        "broad_sector": sector,
        "universe_role": "HOLDOUT",
        "ticker_row_id": f"row-{ticker}",
        "row_payload_hash": f"hash-{ticker}",
        "morning_status": "MORNING_COMPLETE",
        "direction": direction,
        "primary_archetype": archetype,
        "early_return": early,
        "last5_return": last5,
        "point_in_time_pass": 1,
    }


def _source_batch(regime: str = "MIXED", transition: str = "MIXED_TRANSITION") -> dict:
    return {"source_regime": regime, "transition_state": transition}


def _build_step9t_lifecycle(ledger: Path) -> None:
    step9t.seal_morning_snapshot(
        session_date="2026-07-28",
        now=_now("2026-07-28 09:48:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        allow_late=True,
        simulated_clock=True,
        export_outputs_after=False,
    )


def test_config_is_shadow_only_and_freeze_pinned() -> None:
    assert step9u.CONFIG["router_active"] is False
    assert step9u.CONFIG["orders_enabled"] is False
    assert step9u.CONFIG["selection_active"] is True
    assert step9u.CONFIG["mandatory_control_active"] is False
    assert step9u.MAX_SELECTED_POSITIONS == 2
    assert step9u.MAX_POSITIONS_PER_SECTOR == 1
    freeze = step9u._historical_freeze_provenance()
    assert freeze["freeze_id"] == "8042ad803be28ccf"
    assert freeze["artifact_set_sha256"].startswith("8042ad803be28ccf")


def test_laggard_recovery_is_selectable() -> None:
    decision = step9u._policy_decision(
        {"source_regime": "TREND_DOWN", "transition_state": "MIXED_TRANSITION", "primary_archetype": "LAGGARD_RECOVERY_LONG", "early_return": -0.01, "last5_return": 0.003}
    )
    assert decision["selection_eligible"] == 1
    assert decision["rule_id"] == "LRL_AGGREGATE_PROMISING_V1"
    assert decision["signal_strength"] == pytest.approx(0.013)


def test_volatility_expansion_bullish_continuation_is_selectable() -> None:
    decision = step9u._policy_decision(
        {"source_regime": "VOLATILITY_EXPANSION", "transition_state": "BULLISH_CONTINUATION", "primary_archetype": "BULLISH_CONTINUATION_LONG", "early_return": 0.01, "last5_return": 0.002}
    )
    assert decision["selection_eligible"] == 1
    assert decision["rule_id"] == "VE_BCL_BACKOFF_CHALLENGER_V1"


def test_high_dispersion_mixed_bullish_continuation_is_blocked() -> None:
    decision = step9u._policy_decision(
        {"source_regime": "HIGH_DISPERSION", "transition_state": "MIXED_TRANSITION", "primary_archetype": "BULLISH_CONTINUATION_LONG", "early_return": 0.01, "last5_return": 0.002}
    )
    assert decision["selection_eligible"] == 0
    assert decision["policy_action"] == "BLOCKED_NEGATIVE_CONTROL"


def test_unfrozen_archetype_is_observation_only() -> None:
    decision = step9u._policy_decision(
        {"source_regime": "TREND_DOWN", "transition_state": "WEAKNESS_PERSISTING", "primary_archetype": "BEARISH_CONTINUATION_SHORT", "early_return": -0.01, "last5_return": -0.002}
    )
    assert decision["selection_eligible"] == 0
    assert decision["policy_action"] == "OBSERVATION_ONLY"


def test_ranking_and_sector_limit_are_deterministic() -> None:
    rows = [
        _source_row("AAA.ST", "INDUSTRIAL", "LAGGARD_RECOVERY_LONG", -0.02, 0.004),
        _source_row("BBB.ST", "INDUSTRIAL", "LAGGARD_RECOVERY_LONG", -0.01, 0.003),
        _source_row("CCC.ST", "TECH", "BULLISH_CONTINUATION_LONG", 0.012, 0.002),
    ]
    candidates = step9u.build_candidate_assignments(_source_batch("VOLATILITY_EXPANSION"), rows)
    selected = sorted([row for row in candidates if row["selected"]], key=lambda row: row["selected_rank"])
    assert [row["ticker"] for row in selected] == ["AAA.ST", "CCC.ST"]
    bbb = next(row for row in candidates if row["ticker"] == "BBB.ST")
    assert bbb["selection_reason"] == "SKIPPED_SECTOR_LIMIT"


def test_selection_never_uses_outcome_fields() -> None:
    row = _source_row("AAA.ST", "INDUSTRIAL", "LAGGARD_RECOVERY_LONG", -0.02, 0.004)
    row["net_pnl_sek"] = -999999.0
    candidate = step9u.build_candidate_assignments(_source_batch(), [row])[0]
    assert candidate["selected"] == 1
    assert "net_pnl_sek" not in candidate


def test_july28_morning_preserves_22_candidates_and_selects_zero(tmp_path: Path) -> None:
    step9t_ledger = tmp_path / "step9t.db"
    step9u_ledger = tmp_path / "step9u.db"
    _build_step9t_lifecycle(step9t_ledger)
    batches, candidates, inserted = step9u.seal_morning_selection(
        "2026-07-28", _now("2026-07-28 09:48:10+02:00"),
        step9t_ledger_db=step9t_ledger, ledger_db=step9u_ledger,
        allow_late=True, simulated_clock=True, export_outputs_after=False,
    )
    assert inserted is True
    assert len(candidates) == 22
    batch = batches.iloc[0]
    assert batch["source_regime"] == "TREND_DOWN"
    assert batch["transition_state"] == "WEAKNESS_PERSISTING"
    assert int(batch["selectable_candidate_rows"]) == 0
    assert int(batch["selected_count"]) == 0


def test_july28_morning_rerun_is_idempotent(tmp_path: Path) -> None:
    step9t_ledger = tmp_path / "step9t.db"
    step9u_ledger = tmp_path / "step9u.db"
    _build_step9t_lifecycle(step9t_ledger)
    first, rows1, inserted1 = step9u.seal_morning_selection(
        "2026-07-28", _now("2026-07-28 09:48:10+02:00"), step9t_ledger, step9u_ledger,
        allow_late=True, simulated_clock=True, export_outputs_after=False,
    )
    second, rows2, inserted2 = step9u.seal_morning_selection(
        "2026-07-28", _now("2026-07-28 10:10:00+02:00"), step9t_ledger, step9u_ledger,
        allow_late=True, simulated_clock=True, export_outputs_after=False,
    )
    assert inserted1 is True and inserted2 is False
    assert first.iloc[0]["batch_payload_hash"] == second.iloc[0]["batch_payload_hash"]
    assert sorted(rows1["candidate_id"]) == sorted(rows2["candidate_id"])


def test_new_morning_before_decision_time_fails(tmp_path: Path) -> None:
    step9t_ledger = tmp_path / "step9t.db"
    _build_step9t_lifecycle(step9t_ledger)
    with pytest.raises(step9u.SourceDataNotReady, match="not allowed before"):
        step9u.seal_morning_selection(
            "2026-07-28", _now("2026-07-28 09:47:59+02:00"), step9t_ledger, tmp_path / "u.db",
            allow_late=False, simulated_clock=False, export_outputs_after=False,
        )


def test_new_morning_after_deadline_fails(tmp_path: Path) -> None:
    step9t_ledger = tmp_path / "step9t.db"
    _build_step9t_lifecycle(step9t_ledger)
    with pytest.raises(step9u.SourceDataNotReady, match="deadline"):
        step9u.seal_morning_selection(
            "2026-07-28", _now("2026-07-28 09:50:00+02:00"), step9t_ledger, tmp_path / "u.db",
            allow_late=False, simulated_clock=False, export_outputs_after=False,
        )


def test_eod_requires_step9u_morning(tmp_path: Path) -> None:
    with pytest.raises(step9u.SourceDataNotReady, match="No sealed"):
        step9u.evaluate_eod(
            "2026-07-28", _now("2026-07-28 18:00:00+02:00"),
            step9t_ledger_db=tmp_path / "missing-step9t.db", ledger_db=tmp_path / "u.db",
            allow_early=True, export_outputs_after=False,
        )


def test_eod_requires_step9t_eod_batch(tmp_path: Path) -> None:
    step9t_ledger = tmp_path / "step9t.db"
    step9u_ledger = tmp_path / "step9u.db"
    _build_step9t_lifecycle(step9t_ledger)
    step9u.seal_morning_selection(
        "2026-07-28", _now("2026-07-28 09:48:10+02:00"), step9t_ledger, step9u_ledger,
        allow_late=True, simulated_clock=True, export_outputs_after=False,
    )
    with pytest.raises(step9u.SourceDataNotReady, match="Step 9T prospective EOD batch"):
        step9u.evaluate_eod(
            "2026-07-28", _now("2026-07-28 18:00:00+02:00"), step9t_ledger, step9u_ledger,
            allow_early=True, export_outputs_after=False,
        )


def test_july28_eod_preserves_all_candidates_and_zero_selected_pnl(tmp_path: Path) -> None:
    step9t_ledger = tmp_path / "step9t.db"
    step9u_ledger = tmp_path / "step9u.db"
    _build_step9t_lifecycle(step9t_ledger)
    step9u.seal_morning_selection(
        "2026-07-28", _now("2026-07-28 09:48:10+02:00"), step9t_ledger, step9u_ledger,
        allow_late=True, simulated_clock=True, export_outputs_after=False,
    )
    step9t.evaluate_eod(
        "2026-07-28", _now("2026-07-28 18:00:00+02:00"), ledger_db=step9t_ledger,
        allow_early=True, export_outputs_after=False,
    )
    batches, outcomes, inserted = step9u.evaluate_eod(
        "2026-07-28", _now("2026-07-28 18:05:00+02:00"), step9t_ledger, step9u_ledger,
        allow_early=True, export_outputs_after=False,
    )
    assert inserted is True
    assert len(outcomes) == 22
    batch = batches.iloc[0]
    assert int(batch["selected_outcomes"]) == 0
    assert float(batch["selected_net_pnl_sek"]) == 0.0
    assert float(batch["all_candidate_net_pnl_sek"]) == pytest.approx(-67.719900026773, abs=1e-9)


def test_eod_rerun_is_idempotent(tmp_path: Path) -> None:
    step9t_ledger = tmp_path / "step9t.db"
    step9u_ledger = tmp_path / "step9u.db"
    _build_step9t_lifecycle(step9t_ledger)
    step9u.seal_morning_selection(
        "2026-07-28", _now("2026-07-28 09:48:10+02:00"), step9t_ledger, step9u_ledger,
        allow_late=True, simulated_clock=True, export_outputs_after=False,
    )
    step9t.evaluate_eod("2026-07-28", _now("2026-07-28 18:00:00+02:00"), ledger_db=step9t_ledger, allow_early=True, export_outputs_after=False)
    first, rows1, inserted1 = step9u.evaluate_eod("2026-07-28", _now("2026-07-28 18:05:00+02:00"), step9t_ledger, step9u_ledger, allow_early=True, export_outputs_after=False)
    second, rows2, inserted2 = step9u.evaluate_eod("2026-07-28", _now("2026-07-28 19:00:00+02:00"), step9t_ledger, step9u_ledger, allow_early=True, export_outputs_after=False)
    assert inserted1 is True and inserted2 is False
    assert first.iloc[0]["outcome_payload_hash"] == second.iloc[0]["outcome_payload_hash"]
    assert sorted(rows1["step9u_outcome_id"]) == sorted(rows2["step9u_outcome_id"])


def test_immutable_triggers_and_audit_pass(tmp_path: Path) -> None:
    step9t_ledger = tmp_path / "step9t.db"
    step9u_ledger = tmp_path / "step9u.db"
    _build_step9t_lifecycle(step9t_ledger)
    step9u.seal_morning_selection(
        "2026-07-28", _now("2026-07-28 09:48:10+02:00"), step9t_ledger, step9u_ledger,
        allow_late=True, simulated_clock=True, export_outputs_after=False,
    )
    audit = step9u.audit_ledger(step9u_ledger)
    assert bool(audit["passed"].all())
    with closing(sqlite3.connect(step9u_ledger)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_STEP9U_PROSPECTIVE_UPDATE_FORBIDDEN"):
            connection.execute("UPDATE step9u_prospective_candidates SET selected=1")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_STEP9U_PROSPECTIVE_DELETE_FORBIDDEN"):
            connection.execute("DELETE FROM step9u_prospective_assignment_batches")
        connection.rollback()


def test_real_source_files_remain_unchanged(tmp_path: Path) -> None:
    protected = [SOURCE_DB, STEP9L_LEDGER, step9u.DEFAULT_FREEZE_MANIFEST]
    before = {path: _hash(path) for path in protected}
    step9t_ledger = tmp_path / "step9t.db"
    step9u_ledger = tmp_path / "step9u.db"
    _build_step9t_lifecycle(step9t_ledger)
    step9u.seal_morning_selection(
        "2026-07-28", _now("2026-07-28 09:48:10+02:00"), step9t_ledger, step9u_ledger,
        allow_late=True, simulated_clock=True, export_outputs_after=False,
    )
    assert before == {path: _hash(path) for path in protected}
