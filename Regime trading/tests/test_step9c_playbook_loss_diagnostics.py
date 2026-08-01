import unittest

import numpy as np
import pandas as pd

from RegimeTrading.scripts.step9c_playbook_loss_diagnostics import (
    MINIMUM_INFERENCE_TRADES,
    PLAYBOOK_DIAGNOSTIC_COLUMNS,
    SUMMARY_COLUMNS,
    TARGET_R_SCENARIOS,
    TRADE_DIAGNOSTIC_COLUMNS,
    _recommendation,
    build_loss_diagnostics,
    build_trade_diagnostics,
)


class Step9CPlaybookLossDiagnosticsTests(unittest.TestCase):
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

    def _sessions(self, day="2026-01-02", regime="TREND_UP"):
        return pd.DataFrame(
            [
                {
                    "date": day,
                    "primary_regime": regime,
                    "regime_confidence": 0.60,
                    "confidence_band": "MEDIUM",
                }
            ]
        )

    def _single_trade(self, side="LONG", exit_reason="TIME_EXIT"):
        is_long = side == "LONG"
        return pd.DataFrame(
            [
                {
                    "simulation_id": "SOURCE",
                    "trade_id": "T1",
                    "idea_id": "I1",
                    "date": "2026-01-02",
                    "primary_regime": "TREND_UP" if is_long else "TREND_DOWN",
                    "playbook_id": "PB",
                    "idea_type": "SINGLE",
                    "direction": side,
                    "ticker": "ALFA.ST",
                    "paired_ticker": "",
                    "long_ticker": "ALFA.ST" if is_long else "",
                    "short_ticker": "" if is_long else "ALFA.ST",
                    "entry_time": "2026-01-02 09:45:00",
                    "entry_price": 100.0,
                    "stop_price": 99.0 if is_long else 101.0,
                    "target_price": 101.0 if is_long else 99.0,
                    "pair_entry_long_price": np.nan,
                    "pair_entry_short_price": np.nan,
                    "exit_time": "2026-01-02 10:00:00",
                    "exit_price": 100.5 if is_long else 99.5,
                    "exit_reason": exit_reason,
                    "gross_return": 0.005025 if not is_long else 0.005,
                    "net_return": 0.0045,
                    "notional_sek": 1000.0,
                    "gross_pnl_sek": 5.0,
                    "cost_sek": 0.5,
                    "net_pnl_sek": 4.5,
                    "account_return": 0.00045,
                    "trade_duration_minutes": 15.0,
                    "risk_per_share": 1.0,
                    "r_multiple_achieved": 0.5,
                    "same_bar_priority": "STOP",
                    "execution_granularity": "FIVE_MINUTE",
                    "point_in_time_pass": True,
                }
            ]
        )

    def test_long_trade_excursions_exclude_entry_bar_and_scan_horizon(self):
        prices = pd.DataFrame(
            self._bars(
                "ALFA.ST",
                "2026-01-02",
                [
                    ("09:45", 100, 110, 90, 100),
                    ("09:50", 100, 101.5, 99.5, 101),
                    ("10:00", 101, 102, 100, 100.5),
                    ("16:30", 100.5, 103, 98, 102),
                ],
            )
        )
        detail, targets, pairs = build_trade_diagnostics(
            self._single_trade("LONG"), self._sessions(), prices
        )
        self.assertEqual(len(detail), 1)
        row = detail.iloc[0]
        self.assertAlmostEqual(float(row["actual_mfe_return"]), 0.02, places=8)
        self.assertAlmostEqual(float(row["actual_mae_return"]), -0.005, places=8)
        self.assertAlmostEqual(float(row["horizon_mfe_return"]), 0.03, places=8)
        self.assertTrue(bool(row["entry_bar_excursion_excluded"]))
        self.assertEqual(len(targets), len(TARGET_R_SCENARIOS))
        self.assertEqual(len(pairs), 0)

    def test_short_trade_excursions_have_correct_sign(self):
        prices = pd.DataFrame(
            self._bars(
                "ALFA.ST",
                "2026-01-02",
                [
                    ("09:45", 100, 101, 99, 100),
                    ("09:50", 100, 100.5, 98, 99),
                    ("10:00", 99, 101, 97, 99.5),
                    ("16:30", 99.5, 100, 96, 98),
                ],
            )
        )
        sessions = self._sessions(regime="TREND_DOWN")
        detail, _, _ = build_trade_diagnostics(
            self._single_trade("SHORT"), sessions, prices
        )
        row = detail.iloc[0]
        self.assertGreater(float(row["actual_mfe_return"]), 0)
        self.assertLess(float(row["actual_mae_return"]), 0)
        self.assertGreater(float(row["horizon_close_return"]), 0)

    def test_pair_control_is_exact_sign_flip_at_same_exit(self):
        trades = pd.DataFrame(
            [
                {
                    "simulation_id": "SOURCE",
                    "trade_id": "P1",
                    "idea_id": "PI1",
                    "date": "2026-01-02",
                    "primary_regime": "HIGH_DISPERSION",
                    "playbook_id": "PAIRPB",
                    "idea_type": "PAIR",
                    "direction": "LONG_SHORT",
                    "ticker": "ALFA.ST",
                    "paired_ticker": "BOL.ST",
                    "long_ticker": "ALFA.ST",
                    "short_ticker": "BOL.ST",
                    "entry_time": "2026-01-02 09:45:00",
                    "pair_entry_long_price": 100.0,
                    "pair_entry_short_price": 100.0,
                    "exit_time": "2026-01-02 10:00:00",
                    "pair_exit_long_price": 102.0,
                    "pair_exit_short_price": 98.0,
                    "exit_reason": "TIME_EXIT",
                    "gross_return": 0.0202040816,
                    "net_return": 0.0197040816,
                    "notional_sek": 750.0,
                    "gross_pnl_sek": 15.1530612,
                    "cost_sek": 0.375,
                    "net_pnl_sek": 14.7780612,
                    "trade_duration_minutes": 15.0,
                    "point_in_time_pass": True,
                }
            ]
        )
        sessions = self._sessions(regime="HIGH_DISPERSION")
        prices = pd.DataFrame(
            self._bars("ALFA.ST", "2026-01-02", [("09:45", 100, 101, 99, 100), ("10:00", 101, 103, 101, 102)])
            + self._bars("BOL.ST", "2026-01-02", [("09:45", 100, 101, 99, 100), ("10:00", 99, 99, 97, 98)])
        )
        detail, _, controls = build_trade_diagnostics(trades, sessions, prices)
        self.assertEqual(len(detail), 1)
        self.assertEqual(len(controls), 1)
        self.assertAlmostEqual(
            float(controls.iloc[0]["opposite_gross_return_same_exit"]),
            -float(controls.iloc[0]["baseline_gross_return_same_exit"]),
            places=10,
        )

    def test_recommendation_rules_are_explicit(self):
        action = _recommendation(3, 10, 9, 1, 0.7, 2.0, 1.0, 12, np.nan)[0]
        self.assertEqual(action, "INSUFFICIENT_SAMPLE")
        action = _recommendation(MINIMUM_INFERENCE_TRADES, 10, 8, 2, 0.6, 1.5, 1.0, 10, np.nan)[0]
        self.assertEqual(action, "KEEP")
        action = _recommendation(MINIMUM_INFERENCE_TRADES, 5, -1, 6, 0.7, 1.1, 1.0, 0, np.nan)[0]
        self.assertEqual(action, "MODIFY")
        action = _recommendation(MINIMUM_INFERENCE_TRADES, -10, -12, 2, 0.2, 0.2, 0.2, -12, np.nan)[0]
        self.assertEqual(action, "REPLACE")
        action = _recommendation(MINIMUM_INFERENCE_TRADES, -2, -4, 2, 0.4, 0.8, np.nan, -4, 5)[0]
        self.assertEqual(action, "INVERT")

    def test_full_builder_returns_nine_playbook_rows_and_clean_summary(self):
        trades = self._single_trade("LONG")
        sessions = self._sessions()
        prices = pd.DataFrame(
            self._bars(
                "ALFA.ST",
                "2026-01-02",
                [
                    ("09:45", 100, 100.5, 99.5, 100),
                    ("09:50", 100, 101.5, 99.5, 101),
                    ("10:00", 101, 102, 100, 100.5),
                    ("16:30", 100.5, 103, 98, 102),
                ],
            )
        )
        baseline_summary = pd.DataFrame(
            [
                {
                    "simulation_id": "SOURCE",
                    "processed_sessions": 1,
                    "triggered_trades": 1,
                    "gross_pnl_sek_unconstrained": 5.0,
                    "cost_sek_unconstrained": 0.5,
                    "net_pnl_sek_unconstrained": 4.5,
                }
            ]
        )
        outputs = build_loss_diagnostics(
            baseline_summary,
            sessions,
            pd.DataFrame(),
            trades,
            pd.DataFrame(),
            pd.DataFrame(),
            prices,
        )
        summary, detail, playbooks = outputs[:3]
        self.assertEqual(list(summary.columns), SUMMARY_COLUMNS)
        self.assertEqual(list(detail.columns), TRADE_DIAGNOSTIC_COLUMNS)
        self.assertEqual(list(playbooks.columns), PLAYBOOK_DIAGNOSTIC_COLUMNS)
        self.assertEqual(len(playbooks), 9)
        self.assertTrue(bool(summary.iloc[0]["all_trades_enriched"]))
        self.assertEqual(
            summary.iloc[0]["classification"],
            "LOSS_DRIVERS_DIAGNOSTIC_READY_FOR_PLAYBOOK_REDESIGN",
        )


if __name__ == "__main__":
    unittest.main()
