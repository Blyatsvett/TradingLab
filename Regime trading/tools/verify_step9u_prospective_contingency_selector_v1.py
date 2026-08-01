from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.core.stage_registry import resolve_stage_path
from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as step9t
from RegimeTrading.scripts import step9u_prospective_contingency_selector_v1 as step9u


STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now(value: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(STOCKHOLM)
    return timestamp.tz_convert(STOCKHOLM).to_pydatetime()


def main() -> None:
    protected = [
        DATA_DIR / "step9i_shadow_intraday_prices.db",
        DATA_DIR / "step9i_v2_shadow_ledger.db",
        DATA_DIR / "step9l_v3_selected_strategy_shadow_ledger.db",
        resolve_stage_path("step9r_research"),
        resolve_stage_path("step9r"),
        DATA_DIR / "step9u_historical_contingency_selector_v1" / "step9u_summary.csv",
        step9t.DEFAULT_FREEZE_MANIFEST,
        step9u.DEFAULT_FREEZE_MANIFEST,
        PROJECT_ROOT / "config" / "step9u_historical_contingency_selector_v1.json",
        PROJECT_ROOT / "RegimeTrading" / "scripts" / "step9s_prospective_contingency_shadow_v1.py",
        PROJECT_ROOT / "RegimeTrading" / "scripts" / "step9t_prospective_regime_transition_archetype_v1.py",
        PROJECT_ROOT / "RegimeTrading" / "scripts" / "step9u_historical_contingency_selector_v1.py",
    ]
    missing = [path for path in protected if not path.is_file()]
    if missing:
        raise AssertionError(f"Protected verification files are missing: {missing}")
    before = {path: _hash(path) for path in protected}
    real_ledger = step9u.DEFAULT_LEDGER_DB
    real_before = _hash(real_ledger) if real_ledger.is_file() else None
    freeze = step9u._historical_freeze_provenance()
    assert freeze["freeze_id"] == "8042ad803be28ccf"
    assert freeze["artifact_set_sha256"] == "8042ad803be28ccf76fa5ef14aebe80586b7e80cf4c065fc53193d07221a3615"

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        step9t_ledger = root / "step9t.db"
        step9u_ledger = root / "step9u.db"
        exports = root / "exports"

        step9t.seal_morning_snapshot(
            session_date="2026-07-28",
            now=_now("2026-07-28 09:48:00+02:00"),
            ledger_db=step9t_ledger,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        batches, candidates, morning_inserted = step9u.seal_morning_selection(
            session_date="2026-07-28",
            now=_now("2026-07-28 09:48:10+02:00"),
            step9t_ledger_db=step9t_ledger,
            ledger_db=step9u_ledger,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        assert morning_inserted is True
        batch = batches.iloc[0]
        assert batch["source_regime"] == "TREND_DOWN"
        assert batch["transition_state"] == "WEAKNESS_PERSISTING"
        assert len(candidates) == 22
        assert int(batch["selectable_candidate_rows"]) == 0
        assert int(batch["selected_count"]) == 0

        second_batches, second_candidates, morning_inserted_2 = step9u.seal_morning_selection(
            session_date="2026-07-28",
            now=_now("2026-07-28 10:00:00+02:00"),
            step9t_ledger_db=step9t_ledger,
            ledger_db=step9u_ledger,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        assert morning_inserted_2 is False
        assert second_batches.iloc[0]["batch_payload_hash"] == batch["batch_payload_hash"]
        assert sorted(second_candidates["candidate_id"]) == sorted(candidates["candidate_id"])

        step9t.evaluate_eod(
            session_date="2026-07-28",
            now=_now("2026-07-28 18:00:00+02:00"),
            ledger_db=step9t_ledger,
            allow_early=True,
            export_outputs_after=False,
        )
        outcome_batches, outcomes, eod_inserted = step9u.evaluate_eod(
            session_date="2026-07-28",
            now=_now("2026-07-28 18:05:00+02:00"),
            step9t_ledger_db=step9t_ledger,
            ledger_db=step9u_ledger,
            allow_early=True,
            export_outputs_after=False,
        )
        assert eod_inserted is True
        outcome_batch = outcome_batches.iloc[0]
        assert len(outcomes) == 22
        assert int(outcome_batch["selected_outcomes"]) == 0
        assert abs(float(outcome_batch["selected_net_pnl_sek"])) < 1e-12
        assert abs(float(outcome_batch["all_candidate_net_pnl_sek"]) - (-67.719900026773)) < 1e-9

        second_outcome_batches, second_outcomes, eod_inserted_2 = step9u.evaluate_eod(
            session_date="2026-07-28",
            now=_now("2026-07-28 19:00:00+02:00"),
            step9t_ledger_db=step9t_ledger,
            ledger_db=step9u_ledger,
            allow_early=True,
            export_outputs_after=False,
        )
        assert eod_inserted_2 is False
        assert second_outcome_batches.iloc[0]["outcome_payload_hash"] == outcome_batch["outcome_payload_hash"]
        assert sorted(second_outcomes["step9u_outcome_id"]) == sorted(outcomes["step9u_outcome_id"])

        step9u.export_outputs(step9u_ledger, exports)
        audit = step9u.audit_ledger(step9u_ledger)
        assert bool(audit["passed"].all())
        assert (exports / step9u.CANDIDATE_EXPORT).is_file()
        assert (exports / step9u.OUTCOME_EXPORT).is_file()

        with closing(sqlite3.connect(step9u_ledger)) as connection:
            try:
                connection.execute("UPDATE step9u_prospective_candidates SET selected=1")
            except sqlite3.IntegrityError as exc:
                assert "IMMUTABLE_STEP9U_PROSPECTIVE_UPDATE_FORBIDDEN" in str(exc)
            else:
                raise AssertionError("Step 9U immutable update trigger did not fire.")
            connection.rollback()
            try:
                connection.execute("DELETE FROM step9u_prospective_assignment_batches")
            except sqlite3.IntegrityError as exc:
                assert "IMMUTABLE_STEP9U_PROSPECTIVE_DELETE_FORBIDDEN" in str(exc)
            else:
                raise AssertionError("Step 9U immutable delete trigger did not fire.")
            connection.rollback()

    after = {path: _hash(path) for path in protected}
    assert after == before
    if real_before is None:
        assert not real_ledger.exists()
    else:
        assert _hash(real_ledger) == real_before

    print("STEP9U_PROSPECTIVE_SHADOW_V1_VERIFICATION: PASSED")
    print(f"HISTORICAL_FREEZE_ID: {freeze['freeze_id']}")
    print(f"HISTORICAL_ARTIFACT_SET: {freeze['artifact_set_sha256']}")
    print("JULY28_REGIME_TRANSITION: TREND_DOWN / WEAKNESS_PERSISTING")
    print("JULY28_DIRECTIONAL_CANDIDATES: 22")
    print("JULY28_SELECTABLE_SELECTED: 0 / 0")
    print("JULY28_ALL_CANDIDATE_OUTCOMES: 22 / -67.719900 SEK")
    print("JULY28_SELECTED_OUTCOMES: 0 / 0.000000 SEK")
    print("MORNING_IDEMPOTENCY: PASSED")
    print("EOD_IDEMPOTENCY: PASSED")
    print("ALL CANDIDATE OUTCOMES PRESERVED: PASSED")
    print("IMMUTABLE LEDGER TRIGGERS: PASSED")
    print("PROTECTED REAL FILES: BYTE-FOR-BYTE UNCHANGED")
    print("REAL STEP 9U PROSPECTIVE LEDGER: UNCHANGED / NOT CREATED")
    print("STEP 9S REMAINS FROZEN AND UNCHANGED")
    print("MANDATORY CONTROL ACTIVE: FALSE")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
