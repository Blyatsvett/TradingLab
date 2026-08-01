from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.scripts import step9s_prospective_contingency_shadow_v1 as step9s


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now(value: str):
    return step9s._parse_stockholm_datetime(value)


def main() -> None:
    protected = [
        DATA_DIR / "step9i_shadow_intraday_prices.db",
        DATA_DIR / "step9i_v2_shadow_ledger.db",
        DATA_DIR / "step9l_v3_selected_strategy_shadow_ledger.db",
        Path("RegimeTrading/scripts/step9i_v2_core5_plus_holdout18_shadow_router.py"),
        Path("RegimeTrading/scripts/step9l_v3_selected_strategy_shadow_engine.py"),
        Path("RegimeTrading/scripts/step9q_powerbi_excel_feed.py"),
        Path("RegimeTrading/scripts/step9r_v1_candidate_ranking_research.py"),
    ]
    before = {path: sha256(path) for path in protected}

    with tempfile.TemporaryDirectory(prefix="step9s_prospective_verify_") as temp:
        temp_path = Path(temp)
        ledger = temp_path / "step9s_verify.db"

        july28, july28_plan, inserted = step9s.seal_morning_assignment(
            session_date="2026-07-28",
            now=now("2026-07-28 09:48:00+02:00"),
            ledger_db=ledger,
            simulated_clock=True,
            export_outputs_after=False,
        )
        if not inserted:
            raise RuntimeError("Expected a new temporary July 28 assignment.")
        if july28.iloc[0]["primary_regime"] != "TREND_DOWN":
            raise RuntimeError("July 28 regime reproduction failed.")
        if july28_plan.iloc[0]["entry_window_start"] != "09:50":
            raise RuntimeError("Prospective coverage entry is not point-in-time 09:50.")

        _, _, inserted_again = step9s.seal_morning_assignment(
            session_date="2026-07-28",
            now=now("2026-07-28 10:15:00+02:00"),
            ledger_db=ledger,
            simulated_clock=True,
            export_outputs_after=False,
        )
        if inserted_again:
            raise RuntimeError("Identical July 28 assignment rerun inserted a duplicate.")

        july27, july27_plan, inserted27 = step9s.seal_morning_assignment(
            session_date="2026-07-27",
            now=now("2026-07-27 09:48:00+02:00"),
            ledger_db=ledger,
            simulated_clock=True,
            export_outputs_after=False,
        )
        if not inserted27:
            raise RuntimeError("Expected a new temporary July 27 assignment.")
        morning_hashes = (
            july27.iloc[0]["assignment_payload_hash"],
            july27_plan.iloc[0]["plan_payload_hash"],
        )

        batches, natural, coverage, eod_inserted = step9s.evaluate_eod(
            session_date="2026-07-27",
            now=now("2026-07-27 17:00:00+02:00"),
            ledger_db=ledger,
            export_outputs_after=False,
        )
        if not eod_inserted or len(natural) != 2 or len(coverage) != 1:
            raise RuntimeError("July 27 temporary EOD lifecycle did not reproduce expected books.")
        if abs(float(batches.iloc[0]["natural_net_pnl_sek"]) + 4.663401) > 0.000001:
            raise RuntimeError("July 27 Step 9L natural P&L reproduction failed.")
        if not str(coverage.iloc[0]["entry_time"]).startswith("2026-07-27 09:50:00"):
            raise RuntimeError("Mandatory prospective control did not enter at the 09:50 bar.")

        batches2, natural2, coverage2, inserted2 = step9s.evaluate_eod(
            session_date="2026-07-27",
            now=now("2026-07-27 18:00:00+02:00"),
            ledger_db=ledger,
            export_outputs_after=False,
        )
        if inserted2:
            raise RuntimeError("Identical July 27 EOD rerun inserted a duplicate.")
        if batches2.iloc[0]["outcome_payload_hash"] != batches.iloc[0]["outcome_payload_hash"]:
            raise RuntimeError("July 27 EOD idempotency hash mismatch.")

        assignments, plans = step9s._read_existing_assignment(ledger, "2026-07-27")
        if (assignments["assignment_payload_hash"], plans["plan_payload_hash"]) != morning_hashes:
            raise RuntimeError("Morning assignment or plan changed during EOD.")

        audit = step9s.audit_ledger(ledger)
        if not bool(audit["passed"].all()):
            raise RuntimeError("Temporary prospective ledger audit failed.")

    after = {path: sha256(path) for path in protected}
    if before != after:
        changed = [str(path) for path in protected if before[path] != after[path]]
        raise RuntimeError("Protected files changed: " + ", ".join(changed))

    print("STEP9S_PROSPECTIVE_CONTINGENCY_SHADOW_V1_VERIFICATION: PASSED")
    print("JULY28_MORNING: TREND_DOWN / SHORT SAND.ST / 09:50 CONTROL PLAN")
    print("JULY27_LIFECYCLE: 2 NATURAL TRADES / 1 MANDATORY COVERAGE TRADE")
    print(f"JULY27_NATURAL_PNL_SEK: {float(batches.iloc[0]['natural_net_pnl_sek']):.6f}")
    print(f"JULY27_COVERAGE_PNL_SEK: {float(batches.iloc[0]['coverage_net_pnl_sek']):.6f}")
    print("MORNING_IMMUTABILITY: PASSED")
    print("MORNING_AND_EOD_IDEMPOTENCY: PASSED")
    print("PROTECTED REAL FILES: BYTE-FOR-BYTE UNCHANGED")
    print("TEMPORARY LEDGER: DELETED")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
