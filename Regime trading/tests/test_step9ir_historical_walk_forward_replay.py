import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from RegimeTrading.scripts import step8_provisional_regime_taxonomy as step8
from RegimeTrading.scripts import step9i_prospective_shadow_router as step9i
from RegimeTrading.scripts import step9ir_historical_walk_forward_replay as s


class Step9IRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices, cls.target_date = cls._synthetic_prices()
        cls.temp = TemporaryDirectory()
        cls.ledger = Path(cls.temp.name) / "replay.db"
        cls.source = Path(cls.temp.name) / "shadow_prices.db"
        cls.run_log = s.run_replay(
            prices=cls.prices,
            start_date=cls.target_date,
            end_date=cls.target_date,
            ledger_db=cls.ledger,
            source_db=cls.source,
        )
        cls.batches, cls.decisions, cls.outcome_batches, cls.outcomes = s._read_replay_tables(cls.ledger)
        cls.registry = s._contract_registry()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def _synthetic_prices():
        dates = pd.bdate_range("2026-01-02", periods=8)
        rows = []
        tickers = list(step9i.REGIME_SOURCE_TICKERS) + list(step9i.HOLDOUT_TICKERS)
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
                            "open": open_,
                            "high": high,
                            "low": low,
                            "close": close,
                            "ticker": ticker,
                            "date": session_date.date(),
                        }
                    )
                previous_close = opening * 1.011
        return pd.DataFrame(rows), dates[-1].strftime("%Y-%m-%d")

    def test_registry_is_the_eight_locked_contracts_and_never_confirmatory(self):
        self.assertEqual(len(self.registry), 8)
        self.assertEqual(int(self.registry["test_role"].eq("PRIMARY_HYPOTHESIS").sum()), 3)
        self.assertTrue(self.registry["historical_replay_only"].all())
        self.assertFalse(self.registry["confirmatory_evidence"].any())
        self.assertFalse(self.registry["router_active"].any())

    def test_replay_seals_one_immutable_morning_and_eod_batch(self):
        self.assertEqual(len(self.batches), 1)
        self.assertEqual(len(self.outcome_batches), 1)
        self.assertEqual(len(self.decisions), 8 * 18)
        self.assertEqual(len(self.outcomes), 8 * 18)
        self.assertEqual(
            self.batches.iloc[0]["prospective_status"],
            "SIMULATED_CLOCK_RECONSTRUCTION_NOT_CONFIRMATORY",
        )
        self.assertTrue(self.run_log.iloc[0]["eod_status"] == "EOD_EVALUATED")

    def test_replay_is_idempotent(self):
        rerun = s.run_replay(
            prices=self.prices,
            start_date=self.target_date,
            end_date=self.target_date,
            ledger_db=self.ledger,
            source_db=self.source,
        )
        batches, decisions, outcome_batches, outcomes = s._read_replay_tables(self.ledger)
        self.assertFalse(bool(rerun.iloc[0]["morning_inserted"]))
        self.assertFalse(bool(rerun.iloc[0]["eod_inserted"]))
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(decisions), 144)
        self.assertEqual(len(outcome_batches), 1)
        self.assertEqual(len(outcomes), 144)

    def test_regime_strategy_matrix_contains_all_nine_by_eight_cells(self):
        matrix = s.build_regime_strategy_matrix(self.batches, self.outcomes, self.registry)
        self.assertEqual(len(matrix), len(step8.REGIMES) * 8)
        self.assertEqual(int(matrix["locked_regime_match"].sum()), 8)
        observed = str(self.batches.iloc[0]["primary_regime"])
        non_observed = matrix[~matrix["observed_regime"].eq(observed)]
        self.assertEqual(int(non_observed["eligible_ticker_contract_rows"].sum()), 0)
        self.assertFalse(matrix["confirmatory_evidence"].any())

    def test_daily_summary_keeps_roles_separate(self):
        daily = s.build_daily_summary(self.batches, self.outcomes)
        self.assertEqual(len(daily), 1)
        row = daily.iloc[0]
        role_total = (
            int(row["primary_trades"])
            + int(row["control_trades"])
            + int(row["comparator_trades"])
            + int(row["guardrail_counterfactual_trades"])
        )
        self.assertEqual(role_total, int(row["completed_trades"]))
        self.assertFalse(bool(row["confirmatory_evidence"]))
        self.assertFalse(bool(row["router_active"]))

    def test_contract_performance_preserves_strategy_and_regime_labels(self):
        performance = s.build_contract_performance(self.outcomes, self.registry)
        self.assertEqual(set(performance["contract_id"]), set(self.registry["contract_id"]))
        merged = performance.merge(
            self.registry[["contract_id", "primary_regime", "strategy_name"]],
            on="contract_id",
            suffixes=("_performance", "_registry"),
        )
        self.assertTrue(
            merged["primary_regime_performance"].eq(merged["primary_regime_registry"]).all()
        )
        self.assertTrue(
            merged["strategy_name_performance"].eq(merged["strategy_name_registry"]).all()
        )

    def test_cumulative_primary_aggregate_excludes_controls_and_guardrails(self):
        sample = pd.DataFrame(
            [
                {
                    "outcome_id": "P1", "morning_contract_eligible": 1,
                    "outcome_status": "HYPOTHETICAL_TRADE_COMPLETED",
                    "contract_id": "H_TU_RANGE_REJECTION_V1", "test_role": "PRIMARY_HYPOTHESIS",
                    "session_date": "2026-01-10", "risk_capped_net_pnl_sek": 2.0,
                },
                {
                    "outcome_id": "P2", "morning_contract_eligible": 1,
                    "outcome_status": "HYPOTHETICAL_TRADE_COMPLETED",
                    "contract_id": "H_VE_ALIGNED_EARLY_CONTINUATION_V1", "test_role": "PRIMARY_HYPOTHESIS",
                    "session_date": "2026-01-11", "risk_capped_net_pnl_sek": 3.0,
                },
                {
                    "outcome_id": "C1", "morning_contract_eligible": 1,
                    "outcome_status": "HYPOTHETICAL_TRADE_COMPLETED",
                    "contract_id": "H_VE_CONTRARIAN_EARLY_CONTINUATION_CONTROL_V1", "test_role": "COMPLEMENT_CONTROL",
                    "session_date": "2026-01-11", "risk_capped_net_pnl_sek": 100.0,
                },
            ]
        )
        cumulative = s.build_cumulative_pnl(sample, self.registry)
        primary = cumulative[cumulative["series_id"].eq("PRIMARY_HYPOTHESES_AGGREGATE")]
        self.assertAlmostEqual(float(primary.iloc[-1]["cumulative_net_pnl_sek"]), 5.0)
        self.assertNotAlmostEqual(float(primary.iloc[-1]["cumulative_net_pnl_sek"]), 105.0)

    def test_replay_audit_passes_and_contains_no_confirmatory_batch(self):
        audit = s.build_audit(
            self.run_log, self.batches, self.decisions, self.outcome_batches, self.outcomes
        )
        self.assertTrue(audit["audit_pass"].all())
        check = audit[audit["audit_item"].eq("REPLAY_BATCHES_NEVER_CONFIRMATORY")].iloc[0]
        self.assertEqual(int(check["failures"]), 0)
        with closing(sqlite3.connect(self.ledger)) as con:
            statuses = pd.read_sql_query(
                "SELECT DISTINCT prospective_status FROM shadow_decision_batches", con
            )["prospective_status"].tolist()
        self.assertNotIn("PROSPECTIVE_CONFIRMATORY_ELIGIBLE", statuses)


if __name__ == "__main__":
    unittest.main()
