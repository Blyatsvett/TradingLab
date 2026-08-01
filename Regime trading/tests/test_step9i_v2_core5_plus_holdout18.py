import sqlite3
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import pandas as pd

from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as v2
from RegimeTrading.scripts import step9ir_v2_historical_walk_forward_replay as replay
from RegimeTrading.scripts import step9j_v2_combined23_challenger_redesign as step9j_v2


class Step9IV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices, cls.target_date = cls._synthetic_prices()
        cls.taxonomy, cls.decisions, cls.coverage = v2.build_morning_decisions(cls.prices, cls.target_date)

    @staticmethod
    def _synthetic_prices():
        dates = pd.bdate_range("2026-01-02", periods=8)
        rows = []
        tickers = list(dict.fromkeys(list(v2.REGIME_SOURCE_TICKERS) + list(v2.HOLDOUT_ONLY_TICKERS)))
        for ticker_index, ticker in enumerate(tickers):
            previous_close = 100.0 + ticker_index
            for session_date in dates:
                day = session_date.strftime("%Y-%m-%d")
                opening = previous_close * (1.0 + 0.0005 * ((ticker_index % 3) - 1))
                bars = [
                    ("09:30", opening, opening * 1.002, opening * 0.999, opening * 1.001),
                    ("09:35", opening * 1.001, opening * 1.004, opening, opening * 1.003),
                    ("09:40", opening * 1.003, opening * 1.007, opening * 1.002, opening * 1.006),
                    ("09:45", opening * 1.006, opening * 1.012, opening * 1.005, opening * 1.011),
                    ("09:50", opening * 1.011, opening * 1.015, opening * 1.009, opening * 1.014),
                    ("10:00", opening * 1.014, opening * 1.016, opening * 1.010, opening * 1.012),
                    ("16:30", opening * 1.012, opening * 1.014, opening * 1.010, opening * 1.011),
                ]
                for clock, open_, high, low, close in bars:
                    rows.append(
                        {
                            "datetime": pd.Timestamp(f"{day} {clock}"),
                            "open": open_, "high": high, "low": low, "close": close,
                            "ticker": ticker, "date": session_date.date(),
                        }
                    )
                previous_close = opening * 1.011
        return pd.DataFrame(rows), dates[-1].strftime("%Y-%m-%d")

    def _morning(self):
        return datetime.fromisoformat(f"{self.target_date}T09:46:00").replace(tzinfo=ZoneInfo("Europe/Stockholm"))

    def _eod(self):
        return datetime.fromisoformat(f"{self.target_date}T17:40:00").replace(tzinfo=ZoneInfo("Europe/Stockholm"))

    def test_trading_taxonomy_is_core5_plus_holdout18(self):
        static = v2.build_trading_static()
        self.assertEqual(len(static), 23)
        self.assertEqual(static["ticker"].nunique(), 23)
        self.assertEqual(int(static["universe_segment"].eq("CORE_5").sum()), 5)
        self.assertEqual(int(static["universe_segment"].eq("HOLDOUT_18").sum()), 18)
        self.assertEqual(set(v2.CORE_TICKERS), {"SHB-A.ST", "ERIC-B.ST", "ALFA.ST", "SEB-A.ST", "ATCO-A.ST"})

    def test_morning_grid_contains_184_decisions(self):
        self.assertEqual(len(self.decisions), 23 * 8)
        self.assertEqual(self.decisions["ticker"].nunique(), 23)
        self.assertEqual(int(self.decisions["universe_segment"].eq("CORE_5").sum()), 5 * 8)
        self.assertEqual(int(self.decisions["universe_segment"].eq("HOLDOUT_18").sum()), 18 * 8)
        self.assertEqual(self.coverage["regime_source_tickers_observed"], 11)
        self.assertEqual(self.coverage["trading_tickers_observed"], 23)

    def test_v2_ledger_is_separate_immutable_and_records_self_influence(self):
        self.assertNotEqual(v2.SHADOW_LEDGER_DB.name, "step9i_shadow_ledger.db")
        with TemporaryDirectory() as temp_dir:
            ledger = Path(temp_dir) / "v2.db"
            source = Path(temp_dir) / "prices.db"
            _, morning, inserted = v2.seal_morning_decisions(
                self.target_date, self._morning(), self.prices, ledger, source, export_outputs_after=False
            )
            _, morning_again, inserted_again = v2.seal_morning_decisions(
                self.target_date, self._morning(), self.prices, ledger, source, export_outputs_after=False
            )
            self.assertTrue(inserted)
            self.assertFalse(inserted_again)
            self.assertEqual(len(morning), 184)
            self.assertEqual(len(morning_again), 184)
            _, outcomes, eod_inserted = v2.evaluate_eod(
                self.target_date, self._eod(), self.prices, ledger, source, export_outputs_after=False
            )
            self.assertTrue(eod_inserted)
            self.assertEqual(len(outcomes), 184)
            core_eligible = outcomes[
                outcomes["ticker"].isin(v2.CORE_TICKERS)
                & outcomes["morning_contract_eligible"].astype(bool)
            ]
            if not core_eligible.empty:
                self.assertTrue(core_eligible["candidate_generated"].astype(bool).all())
            with closing(sqlite3.connect(ledger)) as con:
                sensitivity = pd.read_sql_query("SELECT * FROM core_regime_sensitivity", con)
                batches = pd.read_sql_query("SELECT * FROM shadow_decision_batches", con)
                decisions = pd.read_sql_query("SELECT * FROM shadow_decisions", con)
                outcome_batches = pd.read_sql_query("SELECT * FROM shadow_outcome_batches", con)
                stored_outcomes = pd.read_sql_query("SELECT * FROM shadow_outcomes", con)
            self.assertEqual(len(sensitivity), 5)
            audit = v2.build_audit(decisions, stored_outcomes, batches, outcome_batches, sensitivity)
            self.assertTrue(audit["audit_pass"].all())

    def test_segment_performance_has_three_views_for_each_contract(self):
        batches = pd.DataFrame([{"batch_id": "B", "prospective_status": "PROSPECTIVE_CONFIRMATORY_ELIGIBLE"}])
        decisions = pd.DataFrame(
            [
                {"decision_id": "C", "batch_id": "B", "ticker": "SEB-A.ST", "contract_eligible": 1},
                {"decision_id": "H", "batch_id": "B", "ticker": "ABB.ST", "contract_eligible": 1},
            ]
        )
        outcomes = pd.DataFrame(
            [
                {"decision_id": "C", "ticker": "SEB-A.ST", "contract_id": "H_TU_RANGE_REJECTION_V1", "test_role": "PRIMARY_HYPOTHESIS", "session_date": "2026-01-01", "company_id": "SEB", "broad_sector": "FINANCIALS", "outcome_status": "HYPOTHETICAL_TRADE_COMPLETED", "risk_capped_net_pnl_sek": 1.0},
                {"decision_id": "H", "ticker": "ABB.ST", "contract_id": "H_TU_RANGE_REJECTION_V1", "test_role": "PRIMARY_HYPOTHESIS", "session_date": "2026-01-01", "company_id": "ABB", "broad_sector": "INDUSTRIALS", "outcome_status": "HYPOTHETICAL_TRADE_COMPLETED", "risk_capped_net_pnl_sek": 2.0},
            ]
        )
        perf = v2._build_segment_performance(decisions, outcomes, batches)
        self.assertEqual(set(perf["universe_segment"]), {"CORE_5", "HOLDOUT_18", "COMBINED_23"})
        self.assertEqual(len(perf), 3 * 8)
        row = perf[(perf["universe_segment"] == "COMBINED_23") & (perf["contract_id"] == "H_TU_RANGE_REJECTION_V1")].iloc[0]
        self.assertAlmostEqual(float(row["net_pnl_risk_capped_sek"]), 3.0)

    def test_v2_compatibility_context_patches_shared_trade_engine_to_23_tickers(self):
        original = tuple(v2.base.step9b.GAP_RECOVERY_TICKERS)
        with v2._patched_holdout_tickers():
            self.assertEqual(tuple(v2.base.step9b.GAP_RECOVERY_TICKERS), v2.TRADING_TICKERS)
        self.assertEqual(tuple(v2.base.step9b.GAP_RECOVERY_TICKERS), original)

    def test_v2_patch_updates_step9h_execution_registry_to_23(self):
        original_instruments = list(v2.step9h.HOLDOUT_INSTRUMENTS)
        original_step9b = tuple(v2.base.step9b.GAP_RECOVERY_TICKERS)
        with v2._patched_base():
            self.assertEqual(
                {row["ticker"] for row in v2.step9h.HOLDOUT_INSTRUMENTS},
                set(v2.TRADING_TICKERS),
            )
            with v2.step9h._patched_step9g_globals():
                self.assertEqual(
                    set(v2.base.step9b.GAP_RECOVERY_TICKERS),
                    set(v2.TRADING_TICKERS),
                )
        self.assertEqual(v2.step9h.HOLDOUT_INSTRUMENTS, original_instruments)
        self.assertEqual(tuple(v2.base.step9b.GAP_RECOVERY_TICKERS), original_step9b)

    def test_replay_and_step9j_are_wired_to_the_23_ticker_adapter(self):
        self.assertIs(replay.step9i, v2)
        self.assertIs(step9j_v2.step9i, v2)
        self.assertTrue(hasattr(step9j_v2.step9i, "_patched_holdout_tickers"))
        self.assertEqual(len(replay.step9i.HOLDOUT_TICKERS), 23)
        self.assertIn("v2", replay.REPLAY_LEDGER_DB.name)
        self.assertIn("v2", step9j_v2.PERFORMANCE_FILE.name)


if __name__ == "__main__":
    unittest.main()
