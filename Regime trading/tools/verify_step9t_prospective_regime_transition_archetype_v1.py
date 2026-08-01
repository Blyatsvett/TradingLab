from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path
from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as step9t


STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now(value: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(STOCKHOLM)
    else:
        timestamp = timestamp.tz_convert(STOCKHOLM)
    return timestamp.to_pydatetime()


def main() -> None:
    protected = [
        DATA_DIR / "step9i_shadow_intraday_prices.db",
        resolve_stage_path("step9i"),
        resolve_stage_path("step9l"),
        resolve_stage_path("step9r_research"),
        resolve_stage_path("step9r"),
        resolve_stage_output_dir("step9t") / "step9t_summary.csv",
        resolve_stage_output_dir("step9t") / "step9t_session_transitions.csv",
        resolve_stage_output_dir("step9t") / "step9t_ticker_archetypes.csv",
        resolve_stage_output_dir("step9t") / "step9t_ticker_outcomes.csv",
        step9t.DEFAULT_FREEZE_MANIFEST,
        PROJECT_ROOT / "RegimeTrading" / "scripts" / "step9i_v2_core5_plus_holdout18_shadow_router.py",
        PROJECT_ROOT / "RegimeTrading" / "scripts" / "step9l_v3_selected_strategy_shadow_engine.py",
        PROJECT_ROOT / "RegimeTrading" / "scripts" / "step9r_v1_candidate_ranking_research.py",
        PROJECT_ROOT / "RegimeTrading" / "scripts" / "step9s_prospective_contingency_shadow_v1.py",
        PROJECT_ROOT / "RegimeTrading" / "scripts" / "step9t_regime_transition_archetype_research_v1.py",
    ]
    missing = [path for path in protected if not path.is_file()]
    if missing:
        raise AssertionError(f"Protected verification files are missing: {missing}")
    before = {path: _hash(path) for path in protected}
    real_ledger = step9t.DEFAULT_LEDGER_DB
    real_ledger_before = _hash(real_ledger) if real_ledger.is_file() else None

    freeze = step9t._historical_freeze_provenance()
    assert freeze["freeze_id"] == "92b274cb24cad391"
    assert freeze["artifact_set_sha256"] == (
        "92b274cb24cad391324b4023e20c9f9830544f6c63e87b73846ff757ff986aa1"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ledger = root / "step9t_prospective_verifier.db"
        exports = root / "exports"

        batches, archetypes, morning_inserted = step9t.seal_morning_snapshot(
            session_date="2026-07-28",
            now=_now("2026-07-28 09:48:00+02:00"),
            ledger_db=ledger,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        assert morning_inserted is True
        batch = batches.iloc[0]
        assert batch["source_regime"] == "TREND_DOWN"
        assert batch["transition_state"] == "WEAKNESS_PERSISTING"
        assert int(batch["valid_ticker_count"]) == 28
        assert len(archetypes) == 29
        assert archetypes["max_source_label_used"].fillna("").le("09:45").all()
        sand = archetypes[archetypes["ticker"].eq("SAND.ST")].iloc[0]
        assert sand["primary_archetype"] == "BEARISH_CONTINUATION_SHORT"

        second_batches, second_archetypes, morning_inserted_2 = step9t.seal_morning_snapshot(
            session_date="2026-07-28",
            now=_now("2026-07-28 10:15:00+02:00"),
            ledger_db=ledger,
            allow_late=True,
            simulated_clock=True,
            export_outputs_after=False,
        )
        assert morning_inserted_2 is False
        assert second_batches.iloc[0]["batch_payload_hash"] == batch["batch_payload_hash"]
        assert sorted(second_archetypes["ticker_row_id"]) == sorted(archetypes["ticker_row_id"])

        outcome_batches, outcomes, eod_inserted = step9t.evaluate_eod(
            session_date="2026-07-28",
            now=_now("2026-07-28 18:00:00+02:00"),
            ledger_db=ledger,
            allow_early=True,
            export_outputs_after=False,
        )
        assert eod_inserted is True
        outcome_batch = outcome_batches.iloc[0]
        assert len(outcomes) == 29
        assert int(outcome_batch["directional_outcomes"]) == 22
        assert int(outcome_batch["zero_outcomes"]) == 6
        assert int(outcome_batch["incomplete_outcomes"]) == 1
        assert abs(
            float(outcome_batch["net_standardized_directional_pnl_sek"])
            - (-67.719900026773)
        ) < 1e-9

        frozen = pd.read_csv(
            DATA_DIR
            / "step9t_regime_transition_archetype_research_v1"
            / "step9t_ticker_outcomes.csv"
        )
        frozen = frozen[frozen["session_date"].astype(str).eq("2026-07-28")]
        merged = outcomes.merge(frozen, on="ticker", suffixes=("_prospective", "_frozen"))
        assert len(merged) == 29
        assert (
            merged["primary_archetype_prospective"]
            == merged["primary_archetype_frozen"]
        ).all()
        assert (merged["direction_prospective"] == merged["direction_frozen"]).all()
        assert (
            merged["outcome_status_prospective"] == merged["outcome_status_frozen"]
        ).all()
        differences = np.abs(
            merged["net_pnl_sek_prospective"] - merged["net_pnl_sek_frozen"]
        )
        assert float(np.nanmax(differences)) < 1e-9

        second_outcome_batches, second_outcomes, eod_inserted_2 = step9t.evaluate_eod(
            session_date="2026-07-28",
            now=_now("2026-07-28 19:00:00+02:00"),
            ledger_db=ledger,
            allow_early=True,
            export_outputs_after=False,
        )
        assert eod_inserted_2 is False
        assert (
            second_outcome_batches.iloc[0]["outcome_payload_hash"]
            == outcome_batch["outcome_payload_hash"]
        )
        assert sorted(second_outcomes["outcome_id"]) == sorted(outcomes["outcome_id"])

        step9t.export_outputs(ledger, exports)
        audit = step9t.audit_ledger(ledger)
        assert bool(audit["passed"].all())

        with closing(sqlite3.connect(ledger)) as connection:
            try:
                connection.execute(
                    "UPDATE step9t_prospective_batches SET source_regime='RECOVERY'"
                )
            except sqlite3.IntegrityError as exc:
                assert "IMMUTABLE_STEP9T_PROSPECTIVE_UPDATE_FORBIDDEN" in str(exc)
            else:
                raise AssertionError("Step 9T immutable update trigger did not fire.")
            connection.rollback()
            try:
                connection.execute("DELETE FROM step9t_prospective_ticker_outcomes")
            except sqlite3.IntegrityError as exc:
                assert "IMMUTABLE_STEP9T_PROSPECTIVE_DELETE_FORBIDDEN" in str(exc)
            else:
                raise AssertionError("Step 9T immutable delete trigger did not fire.")
            connection.rollback()

    after = {path: _hash(path) for path in protected}
    assert after == before
    if real_ledger_before is None:
        assert not real_ledger.exists()
    else:
        assert _hash(real_ledger) == real_ledger_before

    print("STEP9T_PROSPECTIVE_V1_VERIFICATION: PASSED")
    print(f"HISTORICAL_FREEZE_ID: {freeze['freeze_id']}")
    print(f"HISTORICAL_ARTIFACT_SET: {freeze['artifact_set_sha256']}")
    print("JULY28_OPENING_REGIME: TREND_DOWN")
    print("JULY28_0948_TRANSITION: WEAKNESS_PERSISTING")
    print("JULY28_TICKER_ARCHETYPES: 29 / 28 COMPLETE")
    print("JULY28_TICKER_OUTCOMES: 29")
    print("JULY28_DIRECTIONAL_OUTCOMES: 22")
    print("JULY28_NET_STANDARDIZED_DIRECTIONAL_PNL_SEK: -67.719900")
    print("MORNING_IDEMPOTENCY: PASSED")
    print("EOD_IDEMPOTENCY: PASSED")
    print("IMMUTABLE_LEDGER_TRIGGERS: PASSED")
    print("PROTECTED REAL FILES: BYTE-FOR-BYTE UNCHANGED")
    print("REAL PROSPECTIVE LEDGER: UNCHANGED / NOT CREATED")
    print("SELECTION ACTIVE: FALSE")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
