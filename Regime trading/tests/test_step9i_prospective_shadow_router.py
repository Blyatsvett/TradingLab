import sqlite3
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import pandas as pd

from RegimeTrading.scripts import step9i_prospective_shadow_router as s


class Step9ITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices, cls.target_date = cls._synthetic_prices()

    @staticmethod
    def _synthetic_prices():
        dates = pd.bdate_range("2026-01-02", periods=8)
        rows = []
        tickers = list(s.REGIME_SOURCE_TICKERS) + list(s.HOLDOUT_TICKERS)
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

    def _morning_time(self):
        return datetime.fromisoformat(f"{self.target_date}T09:46:00").replace(tzinfo=ZoneInfo("Europe/Stockholm"))

    def _eod_time(self):
        return datetime.fromisoformat(f"{self.target_date}T17:40:00").replace(tzinfo=ZoneInfo("Europe/Stockholm"))

    def test_registry_reuses_eight_locked_step9h_contracts(self):
        registry = s.contract_registry()
        self.assertEqual(len(registry), 8)
        self.assertEqual(int((registry["test_role"] == "PRIMARY_HYPOTHESIS").sum()), 3)
        self.assertTrue((registry["router_active"] == False).all())  # noqa: E712
        self.assertTrue(registry["locked_before_first_prospective_outcome"].all())

    def test_point_in_time_slice_excludes_target_bars_after_0940(self):
        sliced = s._point_in_time_prices(self.prices, self.target_date)
        target = sliced[sliced["date"].astype(str).eq(self.target_date)]
        self.assertEqual(target["datetime"].dt.strftime("%H:%M").max(), "09:40")
        prior = sliced[sliced["date"].astype(str).lt(self.target_date)]
        self.assertEqual(prior["datetime"].dt.strftime("%H:%M").max(), "16:30")

    def test_prospective_window_and_late_reconstruction_are_explicit(self):
        status = s._prospective_status(self.target_date, self._morning_time(), False)
        self.assertEqual(status, "PROSPECTIVE_CONFIRMATORY_ELIGIBLE")
        late = datetime.fromisoformat(f"{self.target_date}T10:05:00").replace(tzinfo=ZoneInfo("Europe/Stockholm"))
        self.assertEqual(
            s._prospective_status(self.target_date, late, True),
            "LATE_RECONSTRUCTION_NOT_CONFIRMATORY",
        )
        with self.assertRaises(s.ShadowDataNotReady):
            s._prospective_status(self.target_date, late, False)

    def test_morning_decision_builder_records_all_contract_ticker_pairs(self):
        taxonomy, decisions, coverage = s.build_morning_decisions(self.prices, self.target_date)
        self.assertEqual(str(taxonomy["date"]), self.target_date)
        self.assertEqual(len(decisions), 8 * 18)
        self.assertEqual(coverage["regime_source_tickers_observed"], 11)
        self.assertEqual(coverage["holdout_tickers_observed"], 18)
        observed_labels = decisions.loc[decisions["max_router_source_label"].ne(""), "max_router_source_label"]
        self.assertTrue(observed_labels.le("09:40").all())
        self.assertFalse(decisions["decision_action"].astype(str).str.contains("ORDER|SEND", case=False).any())

    def test_missing_locked_0940_bar_is_a_data_exclusion(self):
        broken = self.prices.copy()
        mask = (
            broken["ticker"].eq("ABB.ST")
            & broken["date"].astype(str).eq(self.target_date)
            & broken["datetime"].dt.strftime("%H:%M").eq("09:40")
        )
        broken = broken[~mask].copy()
        _, decisions, _ = s.build_morning_decisions(broken, self.target_date)
        abb = decisions[decisions["ticker"].eq("ABB.ST")]
        self.assertEqual(int(abb["contract_eligible"].sum()), 0)
        self.assertTrue(abb["decision_action"].eq("DATA_INCOMPLETE_NO_SHADOW_DECISION").all())

    def test_morning_ledger_is_idempotent_and_hash_audited(self):
        with TemporaryDirectory() as temp_dir:
            ledger = Path(temp_dir) / "ledger.db"
            source = Path(temp_dir) / "prices.db"
            first_batch, first_decisions, inserted = s.seal_morning_decisions(
                self.target_date,
                self._morning_time(),
                self.prices,
                ledger,
                source,
                export_outputs_after=False,
            )
            second_batch, second_decisions, inserted_again = s.seal_morning_decisions(
                self.target_date,
                datetime.fromisoformat(f"{self.target_date}T09:48:00").replace(tzinfo=ZoneInfo("Europe/Stockholm")),
                self.prices,
                ledger,
                source,
                export_outputs_after=False,
            )
            self.assertTrue(inserted)
            self.assertFalse(inserted_again)
            self.assertEqual(first_batch.iloc[0]["batch_payload_hash"], second_batch.iloc[0]["batch_payload_hash"])
            self.assertEqual(len(first_decisions), len(second_decisions))
            with closing(sqlite3.connect(ledger)) as con:
                batches = pd.read_sql_query("SELECT * FROM shadow_decision_batches", con)
                decisions = pd.read_sql_query("SELECT * FROM shadow_decisions", con)
                outcomes = pd.read_sql_query("SELECT * FROM shadow_outcomes", con)
                outcome_batches = pd.read_sql_query("SELECT * FROM shadow_outcome_batches", con)
            audit = s.build_audit(decisions, outcomes, batches, outcome_batches)
            self.assertTrue(audit["audit_pass"].all())

    def test_eod_requires_a_prior_morning_batch(self):
        with TemporaryDirectory() as temp_dir:
            ledger = Path(temp_dir) / "ledger.db"
            with self.assertRaises(s.ShadowDataNotReady):
                s.evaluate_eod(
                    self.target_date,
                    self._eod_time(),
                    self.prices,
                    ledger,
                    Path(temp_dir) / "prices.db",
                    export_outputs_after=False,
                )

    def test_eod_outcomes_never_rewrite_morning_decisions(self):
        with TemporaryDirectory() as temp_dir:
            ledger = Path(temp_dir) / "ledger.db"
            source = Path(temp_dir) / "prices.db"
            _, morning, _ = s.seal_morning_decisions(
                self.target_date,
                self._morning_time(),
                self.prices,
                ledger,
                source,
                export_outputs_after=False,
            )
            original_hashes = morning.set_index("decision_id")["row_payload_hash"].to_dict()
            outcome_batch, outcomes, inserted = s.evaluate_eod(
                self.target_date,
                self._eod_time(),
                self.prices,
                ledger,
                source,
                export_outputs_after=False,
            )
            _, outcomes_again, inserted_again = s.evaluate_eod(
                self.target_date,
                self._eod_time(),
                self.prices,
                ledger,
                source,
                export_outputs_after=False,
            )
            self.assertTrue(inserted)
            self.assertFalse(inserted_again)
            self.assertEqual(len(outcomes), 144)
            self.assertEqual(len(outcomes_again), 144)
            self.assertEqual(int(outcome_batch.iloc[0]["decision_rows"]), 144)
            with closing(sqlite3.connect(ledger)) as con:
                stored = pd.read_sql_query("SELECT decision_id, row_payload_hash FROM shadow_decisions", con)
            self.assertEqual(stored.set_index("decision_id")["row_payload_hash"].to_dict(), original_hashes)

    def test_nonconfirmatory_batches_are_excluded_from_performance(self):
        batches = pd.DataFrame(
            [
                {"batch_id": "P", "prospective_status": "PROSPECTIVE_CONFIRMATORY_ELIGIBLE"},
                {"batch_id": "L", "prospective_status": "LATE_RECONSTRUCTION_NOT_CONFIRMATORY"},
            ]
        )
        decisions = pd.DataFrame(
            [
                {"decision_id": "DP", "batch_id": "P", "contract_eligible": 1},
                {"decision_id": "DL", "batch_id": "L", "contract_eligible": 1},
            ]
        )
        outcomes = pd.DataFrame(
            [
                {
                    "decision_id": "DP", "contract_id": "H_TU_RANGE_REJECTION_V1", "test_role": "PRIMARY_HYPOTHESIS",
                    "session_date": "2026-01-01", "company_id": "A", "broad_sector": "S",
                    "outcome_status": "HYPOTHETICAL_TRADE_COMPLETED", "risk_capped_net_pnl_sek": 1.0,
                },
                {
                    "decision_id": "DL", "contract_id": "H_TU_RANGE_REJECTION_V1", "test_role": "PRIMARY_HYPOTHESIS",
                    "session_date": "2026-01-02", "company_id": "B", "broad_sector": "S",
                    "outcome_status": "HYPOTHETICAL_TRADE_COMPLETED", "risk_capped_net_pnl_sek": 100.0,
                },
            ]
        )
        performance, _ = s.build_performance(decisions, outcomes, batches)
        row = performance[performance["contract_id"].eq("H_TU_RANGE_REJECTION_V1")].iloc[0]
        self.assertEqual(int(row["prospective_trades"]), 1)
        self.assertAlmostEqual(float(row["net_pnl_risk_capped_sek"]), 1.0)

    def test_audit_handles_blank_or_invalid_confirmatory_timestamps(self):
        batches = pd.DataFrame(
            [
                {
                    "prospective_status": "SIMULATED_CLOCK_RECONSTRUCTION_NOT_CONFIRMATORY",
                    "created_at_stockholm": "",
                },
                {
                    "prospective_status": "PROSPECTIVE_CONFIRMATORY_ELIGIBLE",
                    "created_at_stockholm": "",
                },
                {
                    "prospective_status": "PROSPECTIVE_CONFIRMATORY_ELIGIBLE",
                    "created_at_stockholm": "not-a-timestamp",
                },
            ]
        )
        audit = s.build_audit(
            pd.DataFrame(), pd.DataFrame(), batches, pd.DataFrame()
        )
        deadline = audit[
            audit["audit_item"].eq("PROSPECTIVE_BATCHES_SEALED_BEFORE_DEADLINE")
        ].iloc[0]
        self.assertEqual(int(deadline["failures"]), 2)
        self.assertFalse(bool(deadline["audit_pass"]))


if __name__ == "__main__":
    unittest.main()
