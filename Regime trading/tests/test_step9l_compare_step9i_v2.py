from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path

from RegimeTrading.scripts import step9l_compare_step9i_v2 as compare


SCHEMA = """
CREATE TABLE shadow_decision_batches (
    batch_id TEXT, session_date TEXT, prospective_status TEXT,
    primary_regime TEXT, regime_confidence REAL
);
CREATE TABLE shadow_decisions (
    session_date TEXT, contract_id TEXT, ticker TEXT, test_role TEXT,
    contract_eligible INTEGER, decision_action TEXT
);
CREATE TABLE shadow_outcomes (
    session_date TEXT, contract_id TEXT, ticker TEXT, test_role TEXT,
    outcome_status TEXT, risk_capped_net_pnl_sek REAL
);
"""


class Step9LComparisonTests(unittest.TestCase):
    def _ledger(self, path: Path, pnl: float, role: str = "PRIMARY_HYPOTHESIS") -> None:
        with closing(sqlite3.connect(path)) as con:
            con.executescript(SCHEMA)
            con.execute(
                "INSERT INTO shadow_decision_batches VALUES (?, ?, ?, ?, ?)",
                ("B", "2026-07-27", "PROSPECTIVE_CONFIRMATORY_ELIGIBLE", "HIGH_DISPERSION", 0.7),
            )
            con.execute(
                "INSERT INTO shadow_decisions VALUES (?, ?, ?, ?, ?, ?)",
                ("2026-07-27", "C", "ALFA.ST", role, 1, "ELIGIBLE_FOR_EOD_TRIGGER_EVALUATION"),
            )
            con.execute(
                "INSERT INTO shadow_outcomes VALUES (?, ?, ?, ?, ?, ?)",
                ("2026-07-27", "C", "ALFA.ST", role, "HYPOTHETICAL_TRADE_COMPLETED", pnl),
            )
            con.commit()

    def test_comparison_uses_primary_pnl_and_keeps_ledgers_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            frozen = Path(tmp) / "frozen.db"
            research = Path(tmp) / "research.db"
            self._ledger(frozen, -2.0)
            self._ledger(research, 3.0)
            daily, summary, audit = compare.build_comparison(frozen, research)
            self.assertEqual(len(daily), 1)
            self.assertAlmostEqual(
                float(daily.iloc[0]["research_minus_frozen_primary_pnl_sek"]), 5.0
            )
            self.assertEqual(int(summary.iloc[0]["fully_prospective_sessions"]), 1)
            self.assertTrue(bool(audit["audit_pass"].all()))


if __name__ == "__main__":
    unittest.main()
