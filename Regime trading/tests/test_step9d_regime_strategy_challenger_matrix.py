import unittest

import numpy as np
import pandas as pd

from RegimeTrading.scripts.step9d_regime_strategy_challenger_matrix import (
    AUDIT_COLUMNS,
    CHALLENGERS,
    CHALLENGER_BY_ID,
    PERFORMANCE_COLUMNS,
    RANKING_COLUMNS,
    SUMMARY_COLUMNS,
    _pair_candidate_for_challenger,
    _risk_notionals,
    build_challenger_matrix,
)


class Step9DRegimeStrategyChallengerMatrixTests(unittest.TestCase):
    def _bars(self, ticker, day, rows):
        return [
            {
                "datetime": pd.Timestamp(f"{day} {clock}"),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "ticker": ticker,
                "date": pd.Timestamp(day).date(),
            }
            for clock, open_, high, low, close in rows
        ]

    def _taxonomy(self, day="2026-01-02", regime="TREND_UP", direction="UP"):
        return pd.DataFrame(
            [
                {
                    "date": day,
                    "primary_regime": regime,
                    "regime_confidence": 0.60,
                    "confidence_band": "MEDIUM",
                    "direction_bias": direction,
                    "research_risk_multiplier": 1.0,
                    "research_max_concurrent_ideas": 2,
                }
            ]
        )

    def _prices(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars("BOL.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars(
            "ALFA.ST",
            "2026-01-02",
            [
                ("09:30", 100.2, 101.0, 100.0, 100.5),
                ("09:35", 100.5, 101.2, 100.4, 100.8),
                ("09:40", 100.8, 101.5, 100.7, 101.4),
                ("09:45", 101.4, 101.8, 101.3, 101.6),
                ("09:50", 101.6, 103.5, 101.5, 103.0),
                ("10:00", 103.0, 104.0, 102.8, 103.5),
                ("16:30", 103.5, 103.5, 103.5, 103.5),
            ],
        )
        rows += self._bars(
            "BOL.ST",
            "2026-01-02",
            [
                ("09:30", 99.8, 100.0, 99.0, 99.5),
                ("09:35", 99.5, 99.6, 98.8, 99.0),
                ("09:40", 99.0, 99.1, 98.2, 98.4),
                ("09:45", 98.4, 98.5, 97.8, 98.0),
                ("09:50", 98.0, 98.1, 96.5, 97.0),
                ("10:00", 97.0, 97.2, 96.0, 96.5),
                ("16:30", 96.5, 96.5, 96.5, 96.5),
            ],
        )
        return pd.DataFrame(rows)

    def _empty_baseline(self):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def test_registry_is_pre_registered_and_contains_one_control(self):
        self.assertEqual(len(CHALLENGERS), 10)
        self.assertEqual(sum(row["control_status"] != "CHALLENGER" for row in CHALLENGERS), 1)
        self.assertEqual(sum(bool(row["ranking_eligible"]) for row in CHALLENGERS), 9)

    def test_fixed_risk_cap_reduces_wide_risk_notional(self):
        equal, capped = _risk_notionals(0.02, 1.0)
        self.assertEqual(equal, 1000.0)
        self.assertEqual(capped, 250.0)
        equal_small, capped_small = _risk_notionals(0.002, 1.0)
        self.assertEqual(equal_small, capped_small)

    def test_pair_challengers_isolate_continuation_and_convergence(self):
        states = pd.DataFrame(
            [
                {"ticker": "ALFA.ST", "cutoff_return_from_open": 0.02, "max_router_source_label": "09:40"},
                {"ticker": "BOL.ST", "cutoff_return_from_open": -0.02, "max_router_source_label": "09:40"},
            ]
        )
        lookup = {
            ("2026-01-02", "ALFA.ST"): pd.DataFrame(self._bars("ALFA.ST", "2026-01-02", [("09:45", 102, 103, 101, 102), ("15:30", 102, 104, 102, 104)])),
            ("2026-01-02", "BOL.ST"): pd.DataFrame(self._bars("BOL.ST", "2026-01-02", [("09:45", 98, 99, 97, 98), ("15:30", 98, 98, 96, 96)])),
        }
        session = self._taxonomy().iloc[0].to_dict()
        continuation = _pair_candidate_for_challenger(
            session,
            CHALLENGER_BY_ID["PAIR_RELATIVE_STRENGTH_CONTINUATION_V1"],
            states,
            lookup,
            [],
            [],
        )[0]
        convergence = _pair_candidate_for_challenger(
            session,
            CHALLENGER_BY_ID["PAIR_SPREAD_CONVERGENCE_V1"],
            states,
            lookup,
            [],
            [],
        )[0]
        self.assertEqual((continuation["long_ticker"], continuation["short_ticker"]), ("ALFA.ST", "BOL.ST"))
        self.assertEqual((convergence["long_ticker"], convergence["short_ticker"]), ("BOL.ST", "ALFA.ST"))
        self.assertAlmostEqual(continuation["pair_stop_return"], convergence["pair_stop_return"])
        self.assertAlmostEqual(continuation["pair_target_return"], convergence["pair_target_return"])

    def test_close_confirmed_breakout_enters_next_bar(self):
        outputs = build_challenger_matrix(
            self._taxonomy(),
            self._prices(),
            *self._empty_baseline(),
        )
        trades = outputs[3]
        confirmed = trades[
            (trades["challenger_id"].eq("ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1"))
            & (trades["ticker"].eq("ALFA.ST"))
        ]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(pd.Timestamp(confirmed.iloc[0]["entry_time"]).strftime("%H:%M"), "09:50")

    def test_full_matrix_has_ninety_cells_and_no_promotions(self):
        outputs = build_challenger_matrix(
            self._taxonomy(),
            self._prices(),
            *self._empty_baseline(),
        )
        summary, _, _, _, _, performance, rankings, _, audit = outputs
        self.assertEqual(list(summary.columns), SUMMARY_COLUMNS)
        self.assertEqual(list(performance.columns), PERFORMANCE_COLUMNS)
        self.assertEqual(list(rankings.columns), RANKING_COLUMNS)
        self.assertEqual(list(audit.columns), AUDIT_COLUMNS)
        self.assertEqual(len(performance), 90)
        self.assertEqual(int(summary.iloc[0]["strategies_promoted"]), 0)

    def test_all_generated_entries_are_after_router_cutoff(self):
        outputs = build_challenger_matrix(
            self._taxonomy(),
            self._prices(),
            *self._empty_baseline(),
        )
        trades = outputs[3]
        generated = trades[trades["control_status"].eq("CHALLENGER")]
        self.assertTrue((pd.to_datetime(generated["entry_time"]).dt.strftime("%H:%M") >= "09:45").all())
        self.assertTrue(generated["point_in_time_pass"].fillna(False).all())

    def test_trade_leg_reconciliation_is_exact_under_both_sizing_models(self):
        outputs = build_challenger_matrix(
            self._taxonomy(),
            self._prices(),
            *self._empty_baseline(),
        )
        summary, _, _, trades, legs = outputs[:5]
        trade_equal = trades.groupby("trade_id")["equal_net_pnl_sek"].sum()
        leg_equal = legs.groupby("trade_id")["equal_net_pnl_sek"].sum()
        trade_risk = trades.groupby("trade_id")["risk_capped_net_pnl_sek"].sum()
        leg_risk = legs.groupby("trade_id")["risk_capped_net_pnl_sek"].sum()
        self.assertAlmostEqual(float((trade_equal - leg_equal).abs().max()), 0.0, places=10)
        self.assertAlmostEqual(float((trade_risk - leg_risk).abs().max()), 0.0, places=10)
        self.assertAlmostEqual(float(summary.iloc[0]["trade_leg_reconciliation_max_abs_diff_risk_capped_sek"]), 0.0, places=10)

    def test_mechanical_classification_passes_without_selecting_winner(self):
        summary = build_challenger_matrix(
            self._taxonomy(),
            self._prices(),
            *self._empty_baseline(),
        )[0]
        self.assertEqual(
            summary.iloc[0]["classification"],
            "REGIME_STRATEGY_CHALLENGER_MATRIX_READY_FOR_DISCOVERY_REVIEW",
        )
        self.assertEqual(int(summary.iloc[0]["execution_invariant_failures"]), 0)


if __name__ == "__main__":
    unittest.main()
