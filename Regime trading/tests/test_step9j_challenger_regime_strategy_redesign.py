from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from RegimeTrading.scripts import step9j_challenger_regime_strategy_redesign as s
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g


class Step9JTests(unittest.TestCase):
    def _session(self) -> dict:
        return {
            "date": "2026-07-01",
            "primary_regime": "TREND_UP",
            "regime_confidence": 0.8,
            "confidence_band": "HIGH",
            "direction_bias": "UP",
            "research_risk_multiplier": 1.0,
            "research_max_concurrent_ideas": 2,
        }

    def _state(self) -> pd.DataFrame:
        return pd.DataFrame([
            {
                "ticker": "ABB.ST",
                "opening_gap": 0.002,
                "previous_close": 99.0,
                "early_open": 100.0,
                "early_high": 101.0,
                "early_low": 100.0,
                "early_midpoint": 100.5,
                "cutoff_close": 101.2,
                "close_0940": 101.2,
                "cutoff_return_from_open": 0.012,
                "early_range_pct": 0.01,
                "max_router_source_label": "09:40",
            }
        ])

    def _bars(self, retest: bool = True) -> pd.DataFrame:
        rows = [
            ("2026-07-01 09:45", 101.0, 101.3, 100.9, 101.2),
            ("2026-07-01 09:50", 101.2, 101.4, 101.1, 101.25),
        ]
        if retest:
            rows += [
                ("2026-07-01 09:55", 101.2, 101.3, 100.95, 101.10),
                ("2026-07-01 10:00", 101.1, 101.35, 100.98, 101.20),
                ("2026-07-01 10:05", 101.25, 101.5, 101.2, 101.4),
                ("2026-07-01 10:10", 101.4, 102.5, 101.3, 102.4),
            ]
        else:
            rows += [
                ("2026-07-01 09:55", 101.3, 101.6, 101.2, 101.5),
                ("2026-07-01 10:00", 101.5, 101.8, 101.4, 101.7),
                ("2026-07-01 10:05", 101.7, 102.0, 101.6, 101.9),
            ]
        frame = pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close"])
        frame["datetime"] = pd.to_datetime(frame["datetime"])
        return frame

    def test_registry_is_fixed_and_never_router_active(self):
        self.assertEqual(len(s.CONTRACTS), 11)
        self.assertEqual(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in s.CONTRACTS), 5)
        self.assertEqual(len({c["contract_id"] for c in s.CONTRACTS}), 11)
        self.assertTrue(all(c["primary_regime"] in {"TREND_UP", "VOLATILITY_EXPANSION", "RANGE_LOW_VOL"} for c in s.CONTRACTS))
        self.assertIn("POST_HOC", s.RESEARCH_STATUS)

    def test_pullback_requires_breakout_retest_hold_and_enters_next_bar(self):
        trades: list[dict] = []
        legs: list[dict] = []
        candidates = s._pullback_hold_candidates(
            self._session(),
            s.PULLBACK_CHALLENGER,
            self._state(),
            {("2026-07-01", "ABB.ST"): self._bars(retest=True)},
            trades,
            legs,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(candidates[0]["trigger_status"], "TRIGGERED_CLOSED")
        self.assertTrue(str(trades[0]["entry_time"]).startswith("2026-07-01 10:05"))
        self.assertGreater(trades[0]["target_price"], trades[0]["entry_price"])
        self.assertTrue(trades[0]["point_in_time_pass"])

    def test_pullback_without_retest_generates_no_trade(self):
        trades: list[dict] = []
        legs: list[dict] = []
        candidates = s._pullback_hold_candidates(
            self._session(),
            s.PULLBACK_CHALLENGER,
            self._state(),
            {("2026-07-01", "ABB.ST"): self._bars(retest=False)},
            trades,
            legs,
        )
        self.assertEqual(trades, [])
        self.assertEqual(candidates[0]["trigger_status"], "BREAKOUT_WITHOUT_RETEST_HOLD")

    def test_engine_patch_restores_shared_step9g_globals(self):
        original_contracts = step9g.CONTRACTS
        original_dispatch = step9g._single_candidates_for_challenger
        with s._patched_step9j_engine():
            self.assertIs(step9g.CONTRACTS, s.CONTRACTS)
            self.assertIn(s.PULLBACK_CHALLENGER_ID, step9g.CHALLENGER_BY_ID)
            side = step9g._intended_side(s.PULLBACK_CHALLENGER_ID, self._state().iloc[0])
            self.assertEqual(side, "LONG")
        self.assertIs(step9g.CONTRACTS, original_contracts)
        self.assertIs(step9g._single_candidates_for_challenger, original_dispatch)

    def test_trade_diagnostics_have_correct_long_mfe_and_mae_signs(self):
        trades = pd.DataFrame([
            {
                "contract_id": "TEST",
                "test_role": "PRIMARY_HYPOTHESIS",
                "date": "2026-07-01",
                "primary_regime": "TREND_UP",
                "ticker": "ABB.ST",
                "company_id": "ABB",
                "broad_sector": "INDUSTRIALS",
                "direction": "LONG",
                "ticker_relative_state": "EARLY_LEADER",
                "volatility_bucket": "MEDIUM_RELATIVE_VOL",
                "sector_direction_alignment": "ALIGNED_WITH_GROUP",
                "entry_time": "2026-07-01 10:00:00",
                "entry_price": 100.0,
                "stop_price": 99.0,
                "target_price": 102.0,
                "exit_time": "2026-07-01 10:10:00",
                "exit_reason": "TIME_EXIT",
                "risk_pct_at_entry": 0.01,
                "r_multiple_achieved": 0.5,
                "risk_capped_net_pnl_sek": 1.0,
                "point_in_time_pass": True,
            }
        ])
        states = pd.DataFrame([
            {
                "date": "2026-07-01",
                "ticker": "ABB.ST",
                "early_range_pct": 0.01,
                "early_open": 99.5,
                "early_midpoint": 99.8,
                "close_0940": 100.2,
                "cutoff_close": 100.2,
            }
        ])
        bars = pd.DataFrame([
            {"datetime": pd.Timestamp("2026-07-01 10:05"), "high": 102.0, "low": 98.0},
            {"datetime": pd.Timestamp("2026-07-01 10:10"), "high": 101.0, "low": 99.0},
        ])
        with patch.object(s.step9b, "build_daily_reference", return_value=pd.DataFrame()), patch.object(
            s.step9b, "build_market_state", return_value=(states, {("2026-07-01", "ABB.ST"): bars})
        ), patch.object(s.step9i, "_patched_holdout_tickers"):
            diagnostics = s.build_trade_diagnostics(trades, pd.DataFrame(), {"2026-07-01"}, "STEP9J_CHALLENGER")
        row = diagnostics.iloc[0]
        self.assertAlmostEqual(row["mfe_pct"], 0.02)
        self.assertAlmostEqual(row["mae_pct"], -0.02)
        self.assertAlmostEqual(row["mfe_r"], 2.0)
        self.assertAlmostEqual(row["mae_r"], -2.0)

    def test_time_split_is_descriptive_and_uses_both_halves(self):
        trades = pd.DataFrame([
            {
                "contract_id": "A", "test_role": "PRIMARY_HYPOTHESIS", "primary_regime": "TREND_UP",
                "date": "2026-06-01", "company_id": "A", "broad_sector": "X", "risk_capped_net_pnl_sek": 1.0,
            },
            {
                "contract_id": "A", "test_role": "PRIMARY_HYPOTHESIS", "primary_regime": "TREND_UP",
                "date": "2026-06-04", "company_id": "B", "broad_sector": "Y", "risk_capped_net_pnl_sek": -1.0,
            },
        ])
        result = s.build_time_split_performance(
            trades, ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]
        )
        self.assertEqual(set(result["phase"]), {"EARLY_HALF", "LATE_HALF"})
        self.assertTrue(result["interpretation"].str.contains("neither is confirmatory").all())

    def test_summary_never_promotes_or_activates_router(self):
        taxonomy = pd.DataFrame({"date": ["2026-06-01", "2026-06-02"]})
        performance = pd.DataFrame([
            {"test_role": "PRIMARY_HYPOTHESIS", "net_pnl_risk_capped_sek": 10.0}
        ])
        time_split = pd.DataFrame([
            {"test_role": "PRIMARY_HYPOTHESIS", "phase": "LATE_HALF", "net_pnl_risk_capped_sek": 5.0}
        ])
        audit = pd.DataFrame({"audit_pass": [True]})
        summary = s.build_summary(
            "2026-06-01", "2026-06-02", taxonomy, pd.DataFrame(index=range(2)),
            pd.DataFrame(index=range(3)), performance, time_split, audit
        ).iloc[0]
        self.assertEqual(summary["strategies_promoted"], 0)
        self.assertFalse(summary["router_active"])
        self.assertIn("NOT_CONFIRMATORY", summary["classification"])


if __name__ == "__main__":
    unittest.main()
