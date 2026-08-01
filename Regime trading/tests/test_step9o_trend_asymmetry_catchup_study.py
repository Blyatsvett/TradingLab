from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9o_trend_asymmetry_catchup_study as s


class Step9OTrendAsymmetryCatchupTests(unittest.TestCase):
    @staticmethod
    def _session(regime: str, confidence: str = "MEDIUM") -> dict:
        return {
            "date": "2026-07-02",
            "primary_regime": regime,
            "regime_confidence": 0.6,
            "confidence_band": confidence,
            "direction_bias": "UP" if regime == "TREND_UP" else "DOWN",
            "research_risk_multiplier": 0.75,
            "research_max_concurrent_ideas": 2,
        }

    @staticmethod
    def _states(move: float, relative_state: str = "NEUTRAL") -> pd.DataFrame:
        early_open = 100.0
        close_0940 = early_open * (1.0 + move)
        return pd.DataFrame([{
            "ticker": "ABB.ST",
            "opening_gap": 0.0,
            "previous_close": 99.5,
            "early_open": early_open,
            "early_high": 101.0,
            "early_low": 99.0,
            "early_midpoint": 100.0,
            "cutoff_close": close_0940,
            "close_0940": close_0940,
            "cutoff_return_from_open": move,
            "early_range_pct": 0.02,
            "high_0940": close_0940 + 0.2,
            "low_0940": close_0940 - 0.2,
            "max_router_source_label": "09:40",
            "ticker_relative_state": relative_state,
            "volatility_bucket": "MEDIUM_RELATIVE_VOL",
            "contract_sector_alignment": "CONTRARIAN_TO_GROUP",
            "taxonomy_point_in_time_pass": True,
        }])

    @staticmethod
    def _bars(rows) -> pd.DataFrame:
        frame = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close"])
        frame["datetime"] = pd.to_datetime(frame["datetime"])
        return frame

    def test_registry_is_focused_and_exact(self):
        self.assertEqual(len(s.CONTRACTS), 8)
        self.assertEqual(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in s.CONTRACTS), 5)
        self.assertEqual(sum(c["primary_regime"] == "TREND_UP" for c in s.CONTRACTS), 6)
        self.assertEqual(sum(c["primary_regime"] == "TREND_DOWN" for c in s.CONTRACTS), 2)

    def test_reversal_refinements_are_trend_up_aligned(self):
        reversal = [c for c in s.CONTRACTS if "REVERSAL" in c["contract_id"]]
        self.assertEqual(len(reversal), 3)
        self.assertTrue(all(c["primary_regime"] == "TREND_UP" for c in reversal))
        self.assertTrue(all(c["sector_alignment_states"] == "ALIGNED_WITH_GROUP" for c in reversal))
        self.assertTrue(all(c["early_move_regime_relation"] == "ALIGNED_WITH_REGIME" for c in reversal))

    def test_catchup_contracts_are_mirrored_contrarian_cohorts(self):
        catchup = [c for c in s.CONTRACTS if "CATCHUP" in c["contract_id"]]
        self.assertEqual(len(catchup), 4)
        self.assertTrue(all(c["sector_alignment_states"] == "CONTRARIAN_TO_GROUP" for c in catchup))
        self.assertTrue(all(c["early_move_regime_relation"] == "CONTRARIAN_TO_REGIME" for c in catchup))

    def test_confirmed_catchup_long_waits_for_close_and_next_bar(self):
        bars = self._bars([
            ("2026-07-02 09:45", 99.0, 99.6, 98.8, 99.4),
            ("2026-07-02 09:50", 99.4, 100.4, 99.2, 100.2),
            ("2026-07-02 09:55", 100.3, 102.0, 100.1, 101.8),
            ("2026-07-02 16:30", 101.8, 101.9, 101.7, 101.8),
        ])
        trades: list[dict] = []
        candidates = s._catchup_confirmed_candidates(
            self._session("TREND_UP"), s.CATCHUP_CONFIRMED, self._states(-0.012),
            {("2026-07-02", "ABB.ST"): bars}, trades, [],
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "LONG")
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-02 09:55"))
        self.assertEqual(candidates[0]["trigger_status"], "TRIGGERED_CLOSED")

    def test_confirmed_catchup_short_is_exact_mirror(self):
        bars = self._bars([
            ("2026-07-02 09:45", 101.0, 101.2, 100.4, 100.6),
            ("2026-07-02 09:50", 100.6, 100.8, 99.6, 99.8),
            ("2026-07-02 09:55", 99.7, 99.9, 98.0, 98.2),
            ("2026-07-02 16:30", 98.2, 98.3, 98.1, 98.2),
        ])
        trades: list[dict] = []
        s._catchup_confirmed_candidates(
            self._session("TREND_DOWN"), s.CATCHUP_CONFIRMED, self._states(0.012),
            {("2026-07-02", "ABB.ST"): bars}, trades, [],
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "SHORT")
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-02 09:55"))

    def test_immediate_control_enters_0945_open(self):
        bars = self._bars([
            ("2026-07-02 09:45", 99.2, 100.0, 99.1, 99.8),
            ("2026-07-02 09:50", 99.8, 101.0, 99.7, 100.8),
            ("2026-07-02 16:30", 100.8, 100.9, 100.7, 100.8),
        ])
        trades: list[dict] = []
        s._catchup_immediate_candidates(
            self._session("TREND_UP"), s.CATCHUP_IMMEDIATE, self._states(-0.012),
            {("2026-07-02", "ABB.ST"): bars}, trades, [],
        )
        self.assertEqual(len(trades), 1)
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-02 09:45"))

    def test_catchup_rejects_stock_already_aligned_with_regime(self):
        candidates = s._catchup_confirmed_candidates(
            self._session("TREND_UP"), s.CATCHUP_CONFIRMED, self._states(0.012), {}, [], [],
        )
        self.assertEqual(candidates[0]["setup_status"], "INVALID_SETUP")
        self.assertIn("STOCK_NOT_CONTRARIAN_TO_REGIME_DIRECTION", candidates[0]["invalid_reason"])

    def test_contract_mask_enforces_early_relation_to_regime(self):
        states = pd.concat([self._states(-0.012), self._states(0.012)], ignore_index=True)
        with s._patched_step9o_engine():
            mask = step9g._contract_mask(states, s.CONTRACT_BY_ID["O_TU_CONTRARIAN_CATCHUP_CONFIRMED_V1"])
        self.assertEqual(mask.tolist(), [True, False])

    def test_confidence_gate_zeroes_low_session_coverage(self):
        sessions = pd.DataFrame([{
            "date": "2026-07-20", "contract_id": "O_TU_ALIGNED_REVERSAL_MED_HIGH_CONF_V1",
            "eligible_ticker_rows": 7, "eligible_independent_companies": 7, "eligible_tickers": "A|B",
            "valid_setup_rows": 7, "selected_ideas": 2, "triggered_trades": 0,
            "equal_net_pnl_sek": 0.0, "risk_capped_net_pnl_sek": 0.0,
            "cohort_signature": "x", "coverage_status": "ELIGIBLE_NO_TRIGGER",
        }])
        taxonomy = pd.DataFrame([{"date": "2026-07-20", "confidence_band": "LOW"}])
        gated = s._apply_confidence_session_gate(sessions, taxonomy).iloc[0]
        self.assertEqual(gated["eligible_ticker_rows"], 0)
        self.assertEqual(gated["coverage_status"], "SESSION_CONFIDENCE_GATE_NOT_MET")

    def test_engine_patch_restores_shared_globals(self):
        original_contracts = step9g.CONTRACTS
        original_dispatch = step9g._single_candidates_for_challenger
        original_map = step9g.CHALLENGER_BY_ID
        with s._patched_step9o_engine():
            self.assertIs(step9g.CONTRACTS, s.CONTRACTS)
            self.assertIn(s.CATCHUP_CONFIRMED_ID, step9g.CHALLENGER_BY_ID)
        self.assertIs(step9g.CONTRACTS, original_contracts)
        self.assertIs(step9g._single_candidates_for_challenger, original_dispatch)
        self.assertIs(step9g.CHALLENGER_BY_ID, original_map)

    def test_normalized_report_preserves_up_down_asymmetry(self):
        trades = pd.DataFrame([
            {"contract_id": "O_TU_CONTRARIAN_CATCHUP_CONFIRMED_V1", "date": "2026-07-02", "risk_capped_net_pnl_sek": 4.0},
            {"contract_id": "O_TD_CONTRARIAN_CATCHUP_CONFIRMED_V1", "date": "2026-06-01", "risk_capped_net_pnl_sek": -3.0},
        ])
        row = s.build_catchup_direction_normalized_performance(trades).query("strategy_key == 'CONFIRMED_CATCHUP_1_5R'").iloc[0]
        self.assertEqual(row["combined_net_pnl_risk_capped_sek"], 1.0)
        self.assertEqual(row["asymmetry_status"], "TREND_UP_ONLY_OR_ASYMMETRIC")
        self.assertFalse(row["both_regimes_positive"])

    def test_summary_never_promotes_or_routes(self):
        taxonomy = pd.DataFrame({"date": ["2026-06-01", "2026-07-02"], "primary_regime": ["TREND_DOWN", "TREND_UP"]})
        performance = pd.DataFrame([{"test_role": "PRIMARY_HYPOTHESIS", "net_pnl_risk_capped_sek": 5.0}])
        normalized = pd.DataFrame([{
            "strategy_key": "CONFIRMED_CATCHUP_1_5R",
            "trend_up_net_pnl_risk_capped_sek": 2.0,
            "trend_down_net_pnl_risk_capped_sek": -1.0,
        }])
        row = s.build_summary(
            "2026-06-01", "2026-07-02", taxonomy, pd.DataFrame(index=range(46)),
            pd.DataFrame(index=range(2)), performance, normalized,
            pd.DataFrame({"audit_pass": [True]}),
        ).iloc[0]
        self.assertEqual(row["strategies_promoted"], 0)
        self.assertFalse(row["router_active"])
        self.assertIn("NOT_CONFIRMATORY", row["classification"])


if __name__ == "__main__":
    unittest.main()
