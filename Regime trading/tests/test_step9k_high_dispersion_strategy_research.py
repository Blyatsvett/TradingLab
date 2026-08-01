from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9k_high_dispersion_strategy_research as s


class Step9KTests(unittest.TestCase):
    def _session(self) -> dict:
        return {
            "date": "2026-07-01",
            "primary_regime": "HIGH_DISPERSION",
            "regime_confidence": 0.8,
            "confidence_band": "HIGH",
            "direction_bias": "NEUTRAL",
            "research_risk_multiplier": 0.75,
            "research_max_concurrent_ideas": 2,
        }

    def _state(self, move: float = 0.012) -> pd.DataFrame:
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

    def test_registry_is_high_dispersion_only_and_never_active(self):
        self.assertEqual(len(s.CONTRACTS), 5)
        self.assertEqual(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in s.CONTRACTS), 3)
        self.assertEqual(len({c["contract_id"] for c in s.CONTRACTS}), 5)
        self.assertTrue(all(c["primary_regime"] == "HIGH_DISPERSION" for c in s.CONTRACTS))
        self.assertIn("NOT_CONFIRMATORY", s.RESEARCH_STATUS)

    def test_failed_leader_requires_breakout_failure_and_enters_next_bar(self):
        bars = self._bars([
            ("2026-07-01 09:45", 101.0, 101.4, 100.9, 101.2),
            ("2026-07-01 09:50", 101.2, 101.8, 101.1, 101.6),  # close-confirmed breakout
            ("2026-07-01 09:55", 101.5, 101.7, 100.7, 100.8),  # close back inside
            ("2026-07-01 10:00", 100.7, 100.8, 99.5, 99.8),   # next-bar short entry
            ("2026-07-01 10:05", 99.8, 100.0, 98.5, 98.7),
            ("2026-07-01 16:30", 98.7, 98.8, 98.5, 98.6),
        ])
        trades: list[dict] = []
        legs: list[dict] = []
        candidates = s._failed_leader_reversal_candidates(
            self._session(), s.FAILED_LEADER_REVERSAL, self._state(),
            {("2026-07-01", "ABB.ST"): bars}, trades, legs,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "SHORT")
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-01 10:00"))
        self.assertEqual(candidates[0]["trigger_status"], "TRIGGERED_CLOSED")
        self.assertGreater(trades[0]["stop_price"], trades[0]["entry_price"])

    def test_leader_close_orb_waits_for_completed_close_and_next_bar(self):
        bars = self._bars([
            ("2026-07-01 09:45", 100.8, 101.2, 100.7, 100.9),
            ("2026-07-01 09:50", 100.9, 101.5, 100.8, 101.3),  # close beyond 101
            ("2026-07-01 09:55", 101.4, 102.2, 101.3, 102.0),  # entry
            ("2026-07-01 10:00", 102.0, 103.8, 101.9, 103.6),
            ("2026-07-01 16:30", 103.6, 103.7, 103.4, 103.5),
        ])
        trades: list[dict] = []
        legs: list[dict] = []
        candidates = s._leader_close_orb_candidates(
            self._session(), s.LEADER_CLOSE_ORB, self._state(),
            {("2026-07-01", "ABB.ST"): bars}, trades, legs,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "LONG")
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-01 09:55"))
        self.assertEqual(candidates[0]["trigger_status"], "TRIGGERED_CLOSED")

    def test_laggard_catchup_reverses_initial_direction_after_midpoint(self):
        state = self._state(move=-0.012)
        bars = self._bars([
            ("2026-07-01 09:45", 98.8, 99.0, 98.4, 98.6),
            ("2026-07-01 10:00", 98.6, 99.7, 98.5, 99.5),
            ("2026-07-01 10:05", 99.5, 100.3, 99.4, 100.2),  # close > midpoint
            ("2026-07-01 10:10", 100.3, 101.8, 100.2, 101.5), # next-bar long
            ("2026-07-01 16:30", 101.5, 101.7, 101.4, 101.6),
        ])
        trades: list[dict] = []
        legs: list[dict] = []
        candidates = s._laggard_catchup_candidates(
            self._session(), s.LAGGARD_CATCHUP, state,
            {("2026-07-01", "ABB.ST"): bars}, trades, legs,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "LONG")
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-01 10:10"))
        self.assertEqual(candidates[0]["trigger_status"], "TRIGGERED_CLOSED")

    def test_catchup_alignment_uses_early_move_not_reversal_trade(self):
        state = self._state(move=-0.012).iloc[0]
        original = step9g._intended_side
        with s._patched_step9k_engine():
            # Early weakness is SHORT. The eventual catch-up trade would be LONG,
            # but cohort alignment must describe the early weakness.
            self.assertEqual(step9g._intended_side(s.LAGGARD_CATCHUP_ID, state), "SHORT")
        self.assertIs(step9g._intended_side, original)

    def test_engine_patch_restores_shared_globals(self):
        original_contracts = step9g.CONTRACTS
        original_dispatch = step9g._single_candidates_for_challenger
        with s._patched_step9k_engine():
            self.assertIs(step9g.CONTRACTS, s.CONTRACTS)
            self.assertIn(s.FAILED_LEADER_REVERSAL_ID, step9g.CHALLENGER_BY_ID)
        self.assertIs(step9g.CONTRACTS, original_contracts)
        self.assertIs(step9g._single_candidates_for_challenger, original_dispatch)

    def test_summary_never_promotes_or_activates_router(self):
        taxonomy = pd.DataFrame({
            "date": ["2026-06-01", "2026-06-02"],
            "primary_regime": ["HIGH_DISPERSION", "RANGE_LOW_VOL"],
        })
        performance = pd.DataFrame([
            {"test_role": "PRIMARY_HYPOTHESIS", "net_pnl_risk_capped_sek": 10.0}
        ])
        time_split = pd.DataFrame([
            {"test_role": "PRIMARY_HYPOTHESIS", "phase": "LATE_HALF", "net_pnl_risk_capped_sek": 5.0}
        ])
        audit = pd.DataFrame({"audit_pass": [True]})
        summary = s.build_summary(
            "2026-06-01", "2026-06-02", taxonomy, pd.DataFrame(index=range(23)),
            pd.DataFrame(index=range(2)), performance, time_split, audit,
        ).iloc[0]
        self.assertEqual(summary["strategies_promoted"], 0)
        self.assertFalse(summary["router_active"])
        self.assertIn("NOT_CONFIRMATORY", summary["classification"])


if __name__ == "__main__":
    unittest.main()
