import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as s
from RegimeTrading.scripts.collect_step9h_holdout_data import _normalise_download, _upsert


class Step9HTests(unittest.TestCase):
    def test_holdout_universe_is_locked_and_disjoint(self):
        static = s.build_holdout_static()
        discovery = {"ALFA_LAVAL", "ATLAS_COPCO", "ASTRAZENECA", "BOLIDEN", "ERICSSON", "EVOLUTION", "SANDVIK", "SEB", "HANDELSBANKEN", "SWEDBANK"}
        self.assertEqual(len(static), 18)
        self.assertEqual(static["company_id"].nunique(), 18)
        self.assertTrue(set(static["company_id"]).isdisjoint(discovery))
        self.assertTrue(static["locked_before_results"].all())

    def test_three_primary_contracts(self):
        primary = [x for x in s.CONTRACTS if x["test_role"] == "PRIMARY_HYPOTHESIS"]
        self.assertEqual(len(primary), 3)
        self.assertEqual({x["primary_regime"] for x in primary}, {"TREND_UP", "VOLATILITY_EXPANSION", "RANGE_LOW_VOL"})

    def test_empty_database_returns_collection_required(self):
        taxonomy = pd.DataFrame({"date": ["2026-01-02"], "primary_regime": ["TREND_UP"]})
        static = s.build_holdout_static()
        prices = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker", "date"])
        outputs = s.build_holdout_transport(taxonomy, prices, static)
        summary = outputs[0].iloc[0]
        self.assertEqual(summary["classification"], "HOLDOUT_DATA_COLLECTION_REQUIRED")
        self.assertEqual(int(summary["strategies_promoted"]), 0)
        self.assertFalse(bool(summary["router_active"]))

    def test_confirmatory_threshold_requires_all_dimensions(self):
        base = pd.DataFrame([{c: None for c in __import__("RegimeTrading.scripts.step9g_state_filtered_contract_experiments", fromlist=["PERFORMANCE_COLUMNS"]).PERFORMANCE_COLUMNS}])
        base.loc[0, ["contract_id", "test_role", "trades", "sessions_with_trades", "independent_companies", "net_pnl_risk_capped_sek"]] = ["X", "PRIMARY_HYPOTHESIS", 20, 10, 8, 1.0]
        base.loc[0, "bh_adjusted_q_value_primary_family"] = 0.2
        trades = pd.DataFrame({"contract_id": ["X"] * 8, "company_id": [f"C{i}" for i in range(8)], "broad_sector": ["A", "B", "C", "A", "B", "C", "A", "B"], "risk_capped_net_pnl_sek": [1.0] * 8})
        out = s.enrich_performance(base, trades)
        self.assertTrue(bool(out.iloc[0]["confirmatory_sample_ready"]))


    def test_holdout_tickers_reach_state_eligibility_and_original_whitelist_is_restored(self):
        static = s.build_holdout_static()
        taxonomy = pd.DataFrame(
            [{
                "date": "2026-01-02",
                "primary_regime": "TREND_UP",
                "regime_confidence": 0.70,
                "confidence_band": "HIGH",
                "direction_bias": "UP",
                "research_risk_multiplier": 1.0,
                "research_max_concurrent_ideas": 2,
            }]
        )
        bars = [
            {"datetime": pd.Timestamp("2026-01-01 16:30"), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-01").date()},
            {"datetime": pd.Timestamp("2026-01-02 09:30"), "open": 100.0, "high": 101.0, "low": 99.8, "close": 100.5, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            {"datetime": pd.Timestamp("2026-01-02 09:35"), "open": 100.5, "high": 101.5, "low": 100.4, "close": 101.2, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            {"datetime": pd.Timestamp("2026-01-02 09:40"), "open": 101.2, "high": 102.0, "low": 101.0, "close": 101.8, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            {"datetime": pd.Timestamp("2026-01-02 09:45"), "open": 101.8, "high": 102.2, "low": 101.5, "close": 101.9, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            {"datetime": pd.Timestamp("2026-01-02 09:50"), "open": 101.8, "high": 101.9, "low": 101.2, "close": 101.3, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            {"datetime": pd.Timestamp("2026-01-02 10:00"), "open": 101.3, "high": 101.4, "low": 98.0, "close": 98.5, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            {"datetime": pd.Timestamp("2026-01-02 16:30"), "open": 98.6, "high": 98.6, "low": 98.6, "close": 98.6, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
        ]
        prices = pd.DataFrame(bars)
        original = list(s.step9b.GAP_RECOVERY_TICKERS)
        outputs = s.build_holdout_transport(taxonomy, prices, static)
        sessions = outputs[6]
        contract = sessions[sessions["contract_id"].eq("H_TU_RANGE_REJECTION_V1")]
        self.assertGreater(int(contract["eligible_ticker_rows"].sum()), 0)
        self.assertEqual(list(s.step9b.GAP_RECOVERY_TICKERS), original)

    def test_partial_router_window_is_excluded_from_contract_eligibility(self):
        static = s.build_holdout_static()
        taxonomy = pd.DataFrame(
            [{
                "date": "2026-01-02",
                "primary_regime": "TREND_UP",
                "regime_confidence": 0.70,
                "confidence_band": "HIGH",
                "direction_bias": "UP",
                "research_risk_multiplier": 1.0,
                "research_max_concurrent_ideas": 2,
            }]
        )
        bars = [
            {"datetime": pd.Timestamp("2026-01-01 16:30"), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-01").date()},
            {"datetime": pd.Timestamp("2026-01-02 09:30"), "open": 100.0, "high": 101.0, "low": 99.8, "close": 100.5, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            {"datetime": pd.Timestamp("2026-01-02 09:35"), "open": 100.5, "high": 101.5, "low": 100.4, "close": 101.2, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            # The locked 09:40 input bar is intentionally missing.
            {"datetime": pd.Timestamp("2026-01-02 09:45"), "open": 101.2, "high": 102.2, "low": 101.0, "close": 101.9, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
            {"datetime": pd.Timestamp("2026-01-02 16:30"), "open": 101.9, "high": 101.9, "low": 101.9, "close": 101.9, "ticker": "ABB.ST", "date": pd.Timestamp("2026-01-02").date()},
        ]
        outputs = s.build_holdout_transport(taxonomy, pd.DataFrame(bars), static)
        sessions = outputs[6]
        contract = sessions[sessions["contract_id"].eq("H_TU_RANGE_REJECTION_V1")]
        self.assertEqual(int(contract["eligible_ticker_rows"].sum()), 0)
        audit = outputs[-1].set_index("audit_item")
        self.assertTrue(bool(audit.loc["HOLDOUT_STRICT_EARLY_COMPLETENESS_EXCLUSION", "audit_pass"]))
        self.assertEqual(int(audit.loc["HOLDOUT_STRICT_EARLY_COMPLETENESS_EXCLUSION", "rows_checked"]), 1)

    def test_empty_same_day_label_is_not_misclassified_as_future_leakage(self):
        row = pd.Series({
            "audit_date": "2026-01-02",
            "max_source_date": "2026-01-01",
            "max_source_label": "",
            "allowed_source_label": "09:40",
        })
        self.assertFalse(s._future_source_violation(row))

    def test_nan_same_day_label_is_not_misclassified_as_future_leakage(self):
        row = pd.Series({
            "audit_date": "2026-01-02",
            "max_source_date": "2026-01-01",
            "max_source_label": float("nan"),
            "allowed_source_label": "09:40",
        })
        self.assertFalse(s._future_source_violation(row))

    def test_sqlite_upsert_is_idempotent(self):
        frame = pd.DataFrame({"datetime": ["2026-07-24 09:30:00"], "open": [1.0], "high": [1.1], "low": [0.9], "close": [1.05], "ticker": ["ABB.ST"]})
        with TemporaryDirectory() as td:
            path = Path(td) / "h.db"
            self.assertEqual(_upsert(path, frame), (0, 1))
            self.assertEqual(_upsert(path, frame), (1, 1))

    def test_normalise_single_ticker_download(self):
        idx = pd.DatetimeIndex(["2026-07-24 07:30:00+00:00"])
        raw = pd.DataFrame({"Open": [1.0], "High": [1.1], "Low": [0.9], "Close": [1.05]}, index=idx)
        out = _normalise_download(raw, ["ABB.ST"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["ticker"], "ABB.ST")
        self.assertEqual(out.iloc[0]["datetime"], "2026-07-24 09:30:00")


if __name__ == "__main__":
    unittest.main()
