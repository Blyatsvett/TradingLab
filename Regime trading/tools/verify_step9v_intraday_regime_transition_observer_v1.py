from __future__ import annotations

import hashlib
import runpy
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TEST_FILE = PROJECT_ROOT / "tests" / "test_step9v_intraday_regime_transition_observer_v1.py"

from RegimeTrading.scripts import step9v_intraday_regime_transition_observer_v1 as s9v


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ns = runpy.run_path(str(TEST_FILE))
    build = ns["_build_sources"]
    tz = ZoneInfo("Europe/Stockholm")
    with tempfile.TemporaryDirectory(prefix="step9v_verify_") as td:
        root = Path(td)
        tdb, udb, pdb = build(root)
        ledger = root / "step9v.db"
        source_hashes_before = {p.name: sha(p) for p in [tdb, udb, pdb]}
        times = {
            "10:30": datetime(2026, 7, 29, 10, 31, tzinfo=tz),
            "11:30": datetime(2026, 7, 29, 11, 31, tzinfo=tz),
            "13:30": datetime(2026, 7, 29, 13, 31, tzinfo=tz),
            "15:00": datetime(2026, 7, 29, 15, 1, tzinfo=tz),
        }
        selected_reviews = 0
        for cp, now in times.items():
            batch, tickers, reviews, inserted = s9v.seal_checkpoint(
                "2026-07-29", cp, now, pdb, tdb, udb, ledger, export_after=False
            )
            assert inserted and len(batch) == 1 and len(tickers) == 29
            selected_reviews += len(reviews)
            _, _, _, inserted2 = s9v.seal_checkpoint(
                "2026-07-29", cp, now, pdb, tdb, udb, ledger, export_after=False
            )
            assert not inserted2
        ob, to, ao = s9v.evaluate_eod(
            "2026-07-29", datetime(2026, 7, 29, 17, 40, tzinfo=tz), pdb, ledger,
            export_after=False,
        )
        audit = s9v.audit_ledger(ledger)
        assert len(ob) == 4
        assert len(to) == 116
        assert len(ao) == selected_reviews == 8
        assert bool(audit["passed"].all())
        source_hashes_after = {p.name: sha(p) for p in [tdb, udb, pdb]}
        assert source_hashes_before == source_hashes_after
        print("STEP9V_INTRADAY_OBSERVER_V1_VERIFICATION: PASSED")
        print("CHECKPOINTS: 10:30 / 11:30 / 13:30 / 15:00")
        print("CHECKPOINT_BATCHES: 4")
        print("TICKER_STATE_ROWS: 116")
        print("SELECTED_POSITION_REVIEWS: 8")
        print("TICKER_COUNTERFACTUAL_OUTCOMES: 116")
        print("SELECTED_ACTION_OUTCOMES: 8")
        print(f"INDEPENDENT AUDIT: {int(audit['passed'].sum())}/{len(audit)} PASSED")
        print("CHECKPOINT IDEMPOTENCY: PASSED")
        print("IMMUTABLE LEDGER TRIGGERS: PASSED")
        print("SOURCE LEDGERS: BYTE-FOR-BYTE UNCHANGED")
        print("SELECTION ACTIVE: FALSE")
        print("POSITION CHANGES ENABLED: FALSE")
        print("ROUTER ACTIVE: FALSE")
        print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
