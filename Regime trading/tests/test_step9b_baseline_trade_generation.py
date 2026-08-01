import unittest
from datetime import date

import numpy as np
import pandas as pd

from RegimeTrading.scripts.step9b_baseline_trade_generation import (
    CANDIDATE_COLUMNS,
    PLAYBOOKS,
    _directional_execution,
    _pair_candidate,
    build_baseline_simulation,
    build_market_state,
)
from RegimeTrading.scripts.research_regime_aware_gap_recovery import build_daily_reference


class Step9BBaselineTradeGenerationTests(unittest.TestCase):
    def _bars(self, ticker, day, rows):
        output = []
        for clock, open_, high, low, close in rows:
            output.append(
                {
                    "datetime": pd.Timestamp(f"{day} {clock}"),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "ticker": ticker,
                    "date": pd.Timestamp(day).date(),
                }
            )
        return output

    def _taxonomy(self, day, regime, direction="NEUTRAL"):
        return pd.DataFrame(
            [
                {
                    "date": day,
                    "primary_regime": regime,
                    "regime_confidence": 0.60,
                    "confidence_band": "MEDIUM",
                    "direction_bias": direction,
                }
            ]
        )

    def _coverage(self, day, regime):
        return pd.DataFrame(
            [
                {
                    "date": day,
                    "playbook_id": PLAYBOOKS[regime].playbook_id,
                    "point_in_time_contract_pass": True,
                }
            ]
        )

    def test_market_state_excludes_0945_bar_from_router_inputs(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars(
            "ALFA.ST",
            "2026-01-02",
            [
                ("09:30", 100, 101, 99, 100),
                ("09:35", 100, 101, 99, 100.5),
                ("09:40", 100.5, 101, 100, 100.8),
                ("09:45", 100.8, 120, 100, 119),
            ],
        )
        prices = pd.DataFrame(rows)
        state, _ = build_market_state(prices, build_daily_reference(prices), {"2026-01-02"})
        self.assertEqual(len(state), 1)
        self.assertAlmostEqual(float(state.iloc[0]["cutoff_close"]), 100.8)
        self.assertEqual(state.iloc[0]["max_router_source_label"], "09:40")

    def test_long_same_bar_stop_has_priority(self):
        bars = pd.DataFrame(
            self._bars(
                "ALFA.ST",
                "2026-01-02",
                [("09:45", 100, 103, 98, 101), ("09:50", 101, 102, 100, 101)],
            )
        )
        result = _directional_execution(
            bars, "LONG", pd.Timestamp("2026-01-02 09:45"), 100, 99, 102, "16:30"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.exit_reason, "STOP_HIT")
        self.assertEqual(result.exit_price, 99)

    def test_short_execution_has_correct_return_sign(self):
        bars = pd.DataFrame(
            self._bars(
                "ALFA.ST",
                "2026-01-02",
                [("09:45", 100, 100.2, 97, 98), ("09:50", 98, 98.5, 97, 98)],
            )
        )
        result = _directional_execution(
            bars, "SHORT", pd.Timestamp("2026-01-02 09:45"), 100, 101, 98, "16:30"
        )
        self.assertEqual(result.exit_reason, "TARGET_HIT")
        self.assertGreater(result.gross_return, 0)

    def test_high_dispersion_pairs_long_strongest_short_weakest(self):
        states = pd.DataFrame(
            [
                {"date": "2026-01-02", "ticker": "ALFA.ST", "cutoff_return_from_open": 0.02, "max_router_source_label": "09:40"},
                {"date": "2026-01-02", "ticker": "BOL.ST", "cutoff_return_from_open": -0.02, "max_router_source_label": "09:40"},
            ]
        )
        lookup = {
            ("2026-01-02", "ALFA.ST"): pd.DataFrame(self._bars("ALFA.ST", "2026-01-02", [("09:45", 102, 103, 101, 103), ("15:30", 103, 104, 103, 104)])),
            ("2026-01-02", "BOL.ST"): pd.DataFrame(self._bars("BOL.ST", "2026-01-02", [("09:45", 98, 99, 97, 97), ("15:30", 97, 97, 96, 96)])),
        }
        trades, legs = [], []
        candidates = _pair_candidate(
            {"date": "2026-01-02", "primary_regime": "HIGH_DISPERSION"},
            states,
            lookup,
            trades,
            legs,
        )
        self.assertEqual(candidates[0]["long_ticker"], "ALFA.ST")
        self.assertEqual(candidates[0]["short_ticker"], "BOL.ST")
        self.assertIn("CONTINUATION", candidates[0]["mechanical_interpretation"])

    def test_defensive_pair_direction_matches_convergence_target(self):
        states = pd.DataFrame(
            [
                {"date": "2026-01-02", "ticker": "ALFA.ST", "cutoff_return_from_open": 0.01, "early_range_pct": 0.005, "max_router_source_label": "09:40"},
                {"date": "2026-01-02", "ticker": "BOL.ST", "cutoff_return_from_open": -0.01, "early_range_pct": 0.005, "max_router_source_label": "09:40"},
            ]
        )
        lookup = {
            ("2026-01-02", "ALFA.ST"): pd.DataFrame(self._bars("ALFA.ST", "2026-01-02", [("09:45", 101, 101, 100, 100), ("14:30", 100, 100, 99, 99)])),
            ("2026-01-02", "BOL.ST"): pd.DataFrame(self._bars("BOL.ST", "2026-01-02", [("09:45", 99, 100, 99, 100), ("14:30", 100, 101, 100, 101)])),
        }
        candidates = _pair_candidate(
            {"date": "2026-01-02", "primary_regime": "DEFENSIVE_MIXED"},
            states,
            lookup,
            [],
            [],
        )
        self.assertEqual(candidates[0]["long_ticker"], "BOL.ST")
        self.assertEqual(candidates[0]["short_ticker"], "ALFA.ST")
        self.assertIn("CONVERGENCE", candidates[0]["mechanical_interpretation"])

    def test_data_limited_first_session_needs_no_previous_close(self):
        rows = []
        for ticker, base in [("ALFA.ST", 100), ("BOL.ST", 110)]:
            rows += self._bars(
                ticker,
                "2026-01-02",
                [
                    ("09:30", base, base + 0.2, base - 0.2, base),
                    ("09:35", base, base + 0.2, base - 0.2, base),
                    ("09:40", base, base + 0.2, base - 0.2, base),
                    ("09:45", base, base + 0.2, base - 0.2, base),
                    ("12:00", base, base + 0.2, base - 0.2, base),
                ],
            )
        summary, sessions, candidates, trades, legs, performance, audit = build_baseline_simulation(
            self._taxonomy("2026-01-02", "DATA_LIMITED_DEFENSIVE"),
            self._coverage("2026-01-02", "DATA_LIMITED_DEFENSIVE"),
            pd.DataFrame(rows),
        )
        self.assertEqual(len(trades), 1)
        self.assertTrue(bool(audit.iloc[0]["execution_invariant_pass"]))
        self.assertEqual(summary.iloc[0]["classification"], "BASELINE_TRADE_GENERATION_READY_FOR_DIAGNOSTIC_REVIEW")

    def test_trade_and_leg_pnl_reconcile_exactly(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars("BOL.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars("ALFA.ST", "2026-01-02", [("09:30", 100, 101, 99, 100), ("09:35", 100, 102, 100, 102), ("09:40", 102, 103, 102, 103), ("09:45", 103, 104, 103, 104), ("15:30", 104, 105, 104, 105)])
        rows += self._bars("BOL.ST", "2026-01-02", [("09:30", 100, 101, 99, 100), ("09:35", 100, 100, 98, 98), ("09:40", 98, 98, 97, 97), ("09:45", 97, 97, 96, 96), ("15:30", 96, 96, 95, 95)])
        result = build_baseline_simulation(
            self._taxonomy("2026-01-02", "HIGH_DISPERSION"),
            self._coverage("2026-01-02", "HIGH_DISPERSION"),
            pd.DataFrame(rows),
        )
        summary, _, _, trades, legs, _, audit = result
        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(float(trades["net_pnl_sek"].sum()), float(legs["net_pnl_sek"].sum()), places=10)
        self.assertAlmostEqual(float(summary.iloc[0]["trade_leg_reconciliation_max_abs_diff_sek"]), 0.0, places=10)
        self.assertTrue(bool(audit.iloc[0]["trade_leg_reconciliation_pass"]))

    def test_trend_up_generates_breakout_trade_after_0945(self):
        rows = []
        for ticker, prior in [("ALFA.ST", 100), ("BOL.ST", 100)]:
            rows += self._bars(ticker, "2026-01-01", [("16:30", prior, prior, prior, prior)])
        rows += self._bars("ALFA.ST", "2026-01-02", [("09:30", 100.5, 101, 100, 100.8), ("09:35", 100.8, 101.2, 100.7, 101.1), ("09:40", 101.1, 101.5, 101, 101.4), ("09:45", 101.4, 102, 101.2, 101.8), ("09:50", 101.8, 103, 101.8, 102.8), ("16:30", 102.8, 102.8, 102.8, 102.8)])
        rows += self._bars("BOL.ST", "2026-01-02", [("09:30", 100.2, 100.5, 100, 100.3), ("09:35", 100.3, 100.6, 100.2, 100.4), ("09:40", 100.4, 100.7, 100.3, 100.5), ("09:45", 100.5, 100.6, 100.4, 100.5), ("16:30", 100.5, 100.5, 100.5, 100.5)])
        summary, sessions, candidates, trades, legs, performance, audit = build_baseline_simulation(
            self._taxonomy("2026-01-02", "TREND_UP", "UP"),
            self._coverage("2026-01-02", "TREND_UP"),
            pd.DataFrame(rows),
        )
        self.assertGreaterEqual(len(trades), 1)
        self.assertTrue((pd.to_datetime(trades["entry_time"]).dt.strftime("%H:%M") >= "09:45").all())
        self.assertTrue(bool(audit.iloc[0]["router_cutoff_pass"]))

    def test_neutral_volatility_two_sided_same_bar_is_not_fabricated(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars("ALFA.ST", "2026-01-02", [("09:30", 100, 101, 99, 100), ("09:35", 100, 101, 99, 100), ("09:40", 100, 101, 99, 100), ("09:45", 100, 102, 98, 100), ("16:30", 100, 100, 100, 100)])
        summary, sessions, candidates, trades, legs, performance, audit = build_baseline_simulation(
            self._taxonomy("2026-01-02", "VOLATILITY_EXPANSION", "NEUTRAL"),
            self._coverage("2026-01-02", "VOLATILITY_EXPANSION"),
            pd.DataFrame(rows),
        )
        selected = candidates[candidates["selected_for_simulation"]]
        self.assertEqual(len(trades), 0)
        self.assertTrue(selected["trigger_status"].eq("AMBIGUOUS_SAME_BAR_TWO_SIDED_BREAK").all())


    def test_recovery_uses_strict_0930_range_and_previous_close_target(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars("ALFA.ST", "2026-01-02", [("09:30", 99, 99.5, 98.5, 99.0), ("09:35", 99.0, 99.4, 98.8, 99.2), ("09:40", 99.2, 99.45, 99.1, 99.3), ("09:45", 99.3, 99.6, 99.2, 99.5), ("09:50", 99.5, 100.1, 99.5, 100.0), ("16:30", 100, 100, 100, 100)])
        result = build_baseline_simulation(
            self._taxonomy("2026-01-02", "RECOVERY", "UP"),
            self._coverage("2026-01-02", "RECOVERY"),
            pd.DataFrame(rows),
        )
        _, _, candidates, trades, _, _, audit = result
        self.assertEqual(len(trades), 1)
        selected = candidates[candidates["selected_for_simulation"]].iloc[0]
        self.assertAlmostEqual(float(selected["entry_price"]), 99.5)
        self.assertAlmostEqual(float(selected["stop_price"]), 98.5)
        self.assertAlmostEqual(float(selected["target_price"]), 100.0)
        self.assertTrue(bool(audit.iloc[0]["execution_invariant_pass"]))

    def test_trend_down_generates_short_breakout(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars("ALFA.ST", "2026-01-02", [("09:30", 99.5, 100, 99, 99.3), ("09:35", 99.3, 99.4, 98.8, 99.0), ("09:40", 99.0, 99.1, 98.5, 98.7), ("09:45", 98.7, 98.8, 98.0, 98.2), ("09:50", 98.2, 98.3, 97.0, 97.2), ("16:30", 97.2, 97.2, 97.2, 97.2)])
        result = build_baseline_simulation(
            self._taxonomy("2026-01-02", "TREND_DOWN", "DOWN"),
            self._coverage("2026-01-02", "TREND_DOWN"),
            pd.DataFrame(rows),
        )
        _, _, _, trades, legs, _, _ = result
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0]["direction"], "SHORT")
        self.assertGreater(float(trades.iloc[0]["gross_return"]), 0)
        self.assertEqual(legs.iloc[0]["side"], "SHORT")

    def test_range_reversion_enters_next_bar_after_completed_reentry_signal(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars("ALFA.ST", "2026-01-02", [("09:30", 100, 101, 99, 100.5), ("09:35", 100.5, 101, 100, 100.8), ("09:40", 100.8, 101, 100.5, 100.9), ("09:45", 100.9, 101.2, 100.7, 100.8), ("09:50", 100.8, 100.9, 100.0, 100.1), ("15:30", 100.1, 100.2, 100.0, 100.0)])
        result = build_baseline_simulation(
            self._taxonomy("2026-01-02", "RANGE_LOW_VOL", "NEUTRAL"),
            self._coverage("2026-01-02", "RANGE_LOW_VOL"),
            pd.DataFrame(rows),
        )
        _, _, candidates, trades, _, _, _ = result
        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(pd.Timestamp(trade["entry_time"]).strftime("%H:%M"), "09:50")
        selected = candidates[candidates["selected_for_simulation"]].iloc[0]
        self.assertEqual(pd.Timestamp(selected["signal_time"]).strftime("%H:%M"), "09:50")

    def test_high_vol_reversal_uses_opposite_0940_pivot_break(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars("ALFA.ST", "2026-01-02", [("09:30", 100, 100.8, 99.8, 100.5), ("09:35", 100.5, 102.2, 100.4, 102.0), ("09:40", 102.0, 102.1, 101.0, 101.2), ("09:45", 101.2, 101.3, 100.8, 100.9), ("09:50", 100.9, 101.0, 99.8, 100.0), ("16:30", 100, 100, 100, 100)])
        result = build_baseline_simulation(
            self._taxonomy("2026-01-02", "HIGH_VOL_REVERSAL", "NEUTRAL"),
            self._coverage("2026-01-02", "HIGH_VOL_REVERSAL"),
            pd.DataFrame(rows),
        )
        _, _, candidates, trades, _, _, _ = result
        self.assertEqual(len(trades), 1)
        selected = candidates[candidates["selected_for_simulation"]].iloc[0]
        self.assertEqual(selected["direction"], "SHORT")
        self.assertAlmostEqual(float(selected["entry_price"]), 101.0)

    def test_output_candidate_schema_is_stable(self):
        self.assertIn("mechanical_interpretation", CANDIDATE_COLUMNS)
        self.assertIn("point_in_time_pass", CANDIDATE_COLUMNS)
        self.assertIn("pair_target_return", CANDIDATE_COLUMNS)


if __name__ == "__main__":
    unittest.main()
