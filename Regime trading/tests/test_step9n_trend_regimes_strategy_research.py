from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9n_trend_regimes_strategy_research as s


class Step9NTrendRegimesResearchTests(unittest.TestCase):
    @staticmethod
    def _session(regime: str) -> dict:
        return {
            "date": "2026-07-02",
            "primary_regime": regime,
            "regime_confidence": 0.8,
            "confidence_band": "HIGH",
            "direction_bias": "UP" if regime == "TREND_UP" else "DOWN",
            "research_risk_multiplier": 0.75,
            "research_max_concurrent_ideas": 2,
        }

    @staticmethod
    def _state(move: float) -> pd.DataFrame:
        early_open = 100.0
        close_0940 = early_open * (1.0 + move)
        return pd.DataFrame([
            {
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
            }
        ])

    @staticmethod
    def _bars(rows) -> pd.DataFrame:
        frame = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close"])
        frame["datetime"] = pd.to_datetime(frame["datetime"])
        return frame

    def test_registry_is_mirrored_and_small(self):
        self.assertEqual(len(s.CONTRACTS), 10)
        self.assertEqual(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in s.CONTRACTS), 6)
        self.assertEqual(sum(c["primary_regime"] == "TREND_UP" for c in s.CONTRACTS), 5)
        self.assertEqual(sum(c["primary_regime"] == "TREND_DOWN" for c in s.CONTRACTS), 5)
        up_keys = {c["strategy_key"] for c in s.CONTRACTS if c["primary_regime"] == "TREND_UP"}
        down_keys = {c["strategy_key"] for c in s.CONTRACTS if c["primary_regime"] == "TREND_DOWN"}
        self.assertEqual(up_keys, down_keys)

    def test_every_contract_uses_group_aligned_early_move(self):
        self.assertTrue(all(c["sector_alignment_states"] == "ALIGNED_WITH_GROUP" for c in s.CONTRACTS))

    def test_pullback_resume_long_waits_for_pullback_resume_and_next_bar(self):
        bars = self._bars([
            ("2026-07-02 09:45", 100.8, 101.2, 100.5, 101.0),
            ("2026-07-02 09:50", 101.0, 101.1, 99.8, 100.2),  # midpoint pullback
            ("2026-07-02 09:55", 100.2, 101.4, 100.1, 101.3), # close > pullback high
            ("2026-07-02 10:00", 101.5, 103.0, 101.4, 102.9), # next-bar entry
            ("2026-07-02 16:30", 102.9, 103.0, 102.7, 102.8),
        ])
        trades: list[dict] = []
        legs: list[dict] = []
        candidates = s._pullback_resume_candidates(
            self._session("TREND_UP"), s.PULLBACK_RESUME, self._state(0.012),
            {("2026-07-02", "ABB.ST"): bars}, trades, legs,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "LONG")
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-02 10:00"))
        self.assertEqual(candidates[0]["trigger_status"], "TRIGGERED_CLOSED")
        self.assertAlmostEqual(trades[0]["target_price"], 104.05, places=6)

    def test_pullback_resume_short_is_exact_mirror(self):
        bars = self._bars([
            ("2026-07-02 09:45", 99.2, 99.5, 98.8, 99.0),
            ("2026-07-02 09:50", 99.0, 100.2, 98.9, 99.8),   # midpoint rally
            ("2026-07-02 09:55", 99.8, 99.9, 98.6, 98.7),   # close < pullback low
            ("2026-07-02 10:00", 98.5, 98.6, 96.8, 97.0),   # next-bar entry
            ("2026-07-02 16:30", 97.0, 97.1, 96.8, 96.9),
        ])
        trades: list[dict] = []
        legs: list[dict] = []
        s._pullback_resume_candidates(
            self._session("TREND_DOWN"), s.PULLBACK_RESUME, self._state(-0.012),
            {("2026-07-02", "ABB.ST"): bars}, trades, legs,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "SHORT")
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-02 10:00"))

    def test_pullback_rejects_stock_opposite_regime_direction(self):
        candidates = s._pullback_resume_candidates(
            self._session("TREND_UP"), s.PULLBACK_RESUME, self._state(-0.012), {}, [], [],
        )
        self.assertEqual(candidates[0]["setup_status"], "INVALID_SETUP")
        self.assertIn("STOCK_NOT_ALIGNED_WITH_REGIME_DIRECTION", candidates[0]["invalid_reason"])

    def test_alignment_semantics_use_early_move_for_reversal_and_breakout(self):
        state = self._state(-0.012).iloc[0]
        original = step9g._intended_side
        with s._patched_step9n_engine():
            self.assertEqual(step9g._intended_side(s.PULLBACK_RESUME_ID, state), "SHORT")
            self.assertEqual(step9g._intended_side(s.DIRECTIONAL_BREAKOUT_ID, state), "SHORT")
            self.assertEqual(step9g._intended_side(s.DELAYED_REVERSAL_ID, state), "SHORT")
        self.assertIs(step9g._intended_side, original)


    def test_contract_mask_requires_regime_aligned_early_move(self):
        states = pd.DataFrame([
            {
                "early_open": 100.0, "close_0940": 101.0, "cutoff_close": 101.0,
                "cutoff_return_from_open": 0.01, "ticker_relative_state": "NEUTRAL",
                "volatility_bucket": "MEDIUM_RELATIVE_VOL",
                "contract_sector_alignment": "ALIGNED_WITH_GROUP",
                "taxonomy_point_in_time_pass": True,
            },
            {
                "early_open": 100.0, "close_0940": 99.0, "cutoff_close": 99.0,
                "cutoff_return_from_open": -0.01, "ticker_relative_state": "NEUTRAL",
                "volatility_bucket": "MEDIUM_RELATIVE_VOL",
                "contract_sector_alignment": "ALIGNED_WITH_GROUP",
                "taxonomy_point_in_time_pass": True,
            },
        ])
        with s._patched_step9n_engine():
            mask = step9g._contract_mask(states, s.CONTRACT_BY_ID["N_TU_EARLY_CONTINUATION_CONTROL_V1"])
        self.assertEqual(mask.tolist(), [True, False])

    def test_engine_patch_restores_shared_globals(self):
        original_contracts = step9g.CONTRACTS
        original_dispatch = step9g._single_candidates_for_challenger
        original_map = step9g.CHALLENGER_BY_ID
        with s._patched_step9n_engine():
            self.assertIs(step9g.CONTRACTS, s.CONTRACTS)
            self.assertIn(s.PULLBACK_RESUME_ID, step9g.CHALLENGER_BY_ID)
        self.assertIs(step9g.CONTRACTS, original_contracts)
        self.assertIs(step9g._single_candidates_for_challenger, original_dispatch)
        self.assertIs(step9g.CHALLENGER_BY_ID, original_map)

    def test_direction_normalized_report_preserves_asymmetry(self):
        trades = pd.DataFrame([
            {"contract_id": "N_TU_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "date": "2026-07-02", "risk_capped_net_pnl_sek": 4.0},
            {"contract_id": "N_TD_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "date": "2026-06-01", "risk_capped_net_pnl_sek": -3.0},
        ])
        row = s.build_direction_normalized_performance(trades).query("strategy_key == 'CLOSE_CONFIRMED_ORB_1R'").iloc[0]
        self.assertEqual(row["combined_net_pnl_risk_capped_sek"], 1.0)
        self.assertEqual(row["symmetry_status"], "TREND_UP_ONLY_OR_ASYMMETRIC")
        self.assertFalse(row["both_regimes_positive"])

    def test_audit_uses_combined23_trading_tickers(self):
        taxonomy = pd.DataFrame({
            "date": ["2026-06-01", "2026-07-02"],
            "primary_regime": ["TREND_DOWN", "TREND_UP"],
            "direction_bias": ["DOWN", "UP"],
        })
        diagnostics = pd.DataFrame(index=range(2 * len(s.step9i.TRADING_TICKERS)))
        registry = pd.DataFrame({
            "primary_regime": [c["primary_regime"] for c in s.CONTRACTS],
            "router_active": [False] * len(s.CONTRACTS),
            "promotion_eligible": [False] * len(s.CONTRACTS),
        })
        normalized = pd.DataFrame(index=range(5))
        audit = s.extend_audit(pd.DataFrame(), taxonomy, diagnostics, registry, normalized)
        row = audit[audit["audit_item"].eq("TREND_DIAGNOSTIC_COVERAGE_23_TICKERS")].iloc[0]
        self.assertTrue(row["audit_pass"])
        self.assertEqual(row["failures"], 0)

    def test_summary_never_promotes_or_routes(self):
        taxonomy = pd.DataFrame({
            "date": ["2026-06-01", "2026-07-02"],
            "primary_regime": ["TREND_DOWN", "TREND_UP"],
        })
        performance = pd.DataFrame([
            {"test_role": "PRIMARY_HYPOTHESIS", "net_pnl_risk_capped_sek": 10.0}
        ])
        normalized = pd.DataFrame([
            {"test_role": "PRIMARY_HYPOTHESIS", "both_regimes_positive": True}
        ])
        summary = s.build_summary(
            "2026-06-01", "2026-07-02", taxonomy, pd.DataFrame(index=range(46)),
            pd.DataFrame(index=range(2)), performance, normalized,
            pd.DataFrame({"audit_pass": [True]}),
        ).iloc[0]
        self.assertEqual(summary["strategies_promoted"], 0)
        self.assertFalse(summary["router_active"])
        self.assertIn("NOT_CONFIRMATORY", summary["classification"])


if __name__ == "__main__":
    unittest.main()
