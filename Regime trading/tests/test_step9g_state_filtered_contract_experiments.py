import unittest

import numpy as np
import pandas as pd

from RegimeTrading.scripts.step9e_instrument_sector_taxonomy import build_static_taxonomy
from RegimeTrading.scripts.step9g_state_filtered_contract_experiments import (
    AUDIT_COLUMNS,
    COMPARISON_COLUMNS,
    CONTRACTS,
    CONTRACT_BY_ID,
    PERFORMANCE_COLUMNS,
    REGISTRY_COLUMNS,
    SUMMARY_COLUMNS,
    _bh_adjust,
    _bootstrap_total,
    _contract_mask,
    _direction_alignment,
    _intended_side,
    _sign_flip_p_value,
    build_comparisons,
    build_state_filtered_experiment,
)


class Step9GStateFilteredContractExperimentTests(unittest.TestCase):
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

    def _taxonomy(self):
        return pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "primary_regime": "TREND_UP",
                    "regime_confidence": 0.70,
                    "confidence_band": "HIGH",
                    "direction_bias": "UP",
                    "research_risk_multiplier": 1.0,
                    "research_max_concurrent_ideas": 2,
                }
            ]
        )

    def _prices(self):
        rows = []
        rows += self._bars("ALFA.ST", "2026-01-01", [("16:30", 100, 100, 100, 100)])
        rows += self._bars(
            "ALFA.ST",
            "2026-01-02",
            [
                ("09:30", 100.0, 101.0, 99.8, 100.5),
                ("09:35", 100.5, 101.5, 100.4, 101.2),
                ("09:40", 101.2, 102.0, 101.0, 101.8),
                ("09:45", 101.8, 102.2, 101.5, 101.9),
                ("09:50", 101.8, 101.9, 101.2, 101.3),
                ("10:00", 101.3, 101.4, 98.0, 98.5),
                ("15:30", 98.5, 98.7, 98.4, 98.6),
                ("16:30", 98.6, 98.6, 98.6, 98.6),
            ],
        )
        return pd.DataFrame(rows)

    def _characteristics(self):
        return pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "ticker": "ALFA.ST",
                    "ticker_relative_state": "EARLY_LEADER",
                    "volatility_bucket": "HIGH_RELATIVE_VOL",
                    "range_state": "RANGE_NORMAL",
                    "historical_tendency": "CONTINUATION_PRONE",
                    "point_in_time_pass": True,
                }
            ]
        )

    def _group_states(self):
        return pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "aggregation_level": "BROAD_SECTOR",
                    "group_name": "INDUSTRIALS",
                    "group_direction_state": "UP",
                    "point_in_time_pass": True,
                }
            ]
        )

    def test_registry_is_fixed_with_seven_primary_and_seven_controls(self):
        self.assertEqual(len(CONTRACTS), 14)
        self.assertEqual(sum(row["test_role"] == "PRIMARY_HYPOTHESIS" for row in CONTRACTS), 7)
        self.assertEqual(sum(row["test_role"] == "COMPLEMENT_CONTROL" for row in CONTRACTS), 7)
        self.assertEqual(len({row["contract_id"] for row in CONTRACTS}), 14)

    def test_state_filter_separates_trend_up_leader_and_laggard(self):
        state = pd.DataFrame(
            [
                {
                    "ticker_relative_state": "EARLY_LEADER",
                    "volatility_bucket": "HIGH_RELATIVE_VOL",
                    "contract_sector_alignment": "CONTRARIAN_TO_GROUP",
                    "taxonomy_point_in_time_pass": True,
                }
            ]
        )
        leader = _contract_mask(state, CONTRACT_BY_ID["TU_EARLY_LEADER_RANGE_REJECTION_V1"])
        laggard = _contract_mask(state, CONTRACT_BY_ID["TU_EARLY_LAGGARD_RANGE_REJECTION_CONTROL_V1"])
        self.assertTrue(bool(leader.iloc[0]))
        self.assertFalse(bool(laggard.iloc[0]))

    def test_intended_direction_and_group_alignment_are_point_in_time_definitions(self):
        row = {
            "early_open": 100.0,
            "close_0940": 101.0,
            "cutoff_close": 101.0,
            "cutoff_return_from_open": 0.01,
            "early_midpoint": 100.5,
        }
        continuation_side = _intended_side("EARLY_MOVE_CONTINUATION_1_5R_V1", row)
        reversal_side = _intended_side("DELAYED_EARLY_MOVE_REVERSAL_1R_V1", row)
        self.assertEqual(continuation_side, "LONG")
        self.assertEqual(reversal_side, "SHORT")
        self.assertEqual(_direction_alignment(continuation_side, "UP"), "ALIGNED_WITH_GROUP")
        self.assertEqual(_direction_alignment(reversal_side, "UP"), "CONTRARIAN_TO_GROUP")

    def test_bootstrap_and_sign_flip_are_deterministic(self):
        values = np.array([2.0, 1.0, 3.0, 0.5])
        first = _bootstrap_total(values, iterations=1000, seed=7)
        second = _bootstrap_total(values, iterations=1000, seed=7)
        self.assertEqual(first, second)
        self.assertGreater(first[0], 0.0)
        self.assertEqual(_sign_flip_p_value(values, iterations=2000, seed=9), _sign_flip_p_value(values, iterations=2000, seed=9))

    def test_bh_adjustment_is_monotone_in_sorted_p_values(self):
        p = pd.Series([0.01, 0.04, 0.03, 0.20], index=["a", "b", "c", "d"])
        q = _bh_adjust(p)
        ordered = pd.DataFrame({"p": p, "q": q}).sort_values("p")
        self.assertTrue((ordered["q"].diff().dropna() >= -1e-12).all())
        self.assertTrue((q >= p).all())

    def test_same_cohort_comparison_confirms_matching_signatures(self):
        dates = ["2026-01-02", "2026-01-03"]
        session_rows = []
        for cid in ["VE_GROUP_ALIGNED_EARLY_CONTINUATION_V1", "VE_GROUP_ALIGNED_CLOSE_CONFIRMED_ORB_V1"]:
            for day in dates:
                session_rows.append(
                    {
                        "date": day,
                        "contract_id": cid,
                        "regime_match": True,
                        "eligible_ticker_rows": 1,
                        "cohort_signature": f"{day}|ALFA.ST",
                    }
                )
        sessions = pd.DataFrame(session_rows)
        trades = pd.DataFrame(
            [
                {"date": "2026-01-02", "contract_id": "VE_GROUP_ALIGNED_EARLY_CONTINUATION_V1", "risk_capped_net_pnl_sek": 1.0},
                {"date": "2026-01-02", "contract_id": "VE_GROUP_ALIGNED_CLOSE_CONFIRMED_ORB_V1", "risk_capped_net_pnl_sek": 0.5},
            ]
        )
        comparisons = build_comparisons(sessions, trades)
        row = comparisons[comparisons["comparison_id"].eq("VE_ALIGNED_EARLY_CONT_MINUS_CLOSE_ORB")].iloc[0]
        self.assertTrue(bool(row["cohort_signature_match"]))
        self.assertEqual(row["comparison_status"], "SAME_COHORT_CONFIRMED_DISCOVERY_ONLY")
        self.assertEqual(list(comparisons.columns), COMPARISON_COLUMNS)

    def test_end_to_end_reruns_filtered_contract_from_raw_bars(self):
        outputs = build_state_filtered_experiment(
            self._taxonomy(),
            self._prices(),
            build_static_taxonomy(),
            self._characteristics(),
            self._group_states(),
        )
        summary, registry, sessions, candidates, trades, legs, performance, comparisons, _, _, audit = outputs
        leader = trades[trades["contract_id"].eq("TU_EARLY_LEADER_RANGE_REJECTION_V1")]
        laggard = trades[trades["contract_id"].eq("TU_EARLY_LAGGARD_RANGE_REJECTION_CONTROL_V1")]
        self.assertEqual(len(leader), 1)
        self.assertEqual(len(laggard), 0)
        self.assertEqual(pd.Timestamp(leader.iloc[0]["entry_time"]).strftime("%H:%M"), "09:50")
        self.assertEqual(list(summary.columns), SUMMARY_COLUMNS)
        self.assertEqual(list(registry.columns), REGISTRY_COLUMNS)
        self.assertEqual(list(performance.columns), PERFORMANCE_COLUMNS)
        self.assertEqual(list(audit.columns), AUDIT_COLUMNS)
        self.assertEqual(int(summary.iloc[0]["strategies_promoted"]), 0)
        self.assertFalse(bool(summary.iloc[0]["router_active"]))
        self.assertEqual(summary.iloc[0]["classification"], "STATE_FILTERED_CONTRACT_EXPERIMENT_READY_FOR_CONTROLLED_REVIEW")

    def test_trade_leg_reconciliation_is_exact(self):
        outputs = build_state_filtered_experiment(
            self._taxonomy(),
            self._prices(),
            build_static_taxonomy(),
            self._characteristics(),
            self._group_states(),
        )
        trades, legs = outputs[4], outputs[5]
        trade_equal = trades.set_index("trade_id")["equal_net_pnl_sek"]
        leg_equal = legs.groupby("trade_id")["equal_net_pnl_sek"].sum()
        trade_risk = trades.set_index("trade_id")["risk_capped_net_pnl_sek"]
        leg_risk = legs.groupby("trade_id")["risk_capped_net_pnl_sek"].sum()
        self.assertAlmostEqual(float((trade_equal - leg_equal).abs().max()), 0.0, places=10)
        self.assertAlmostEqual(float((trade_risk - leg_risk).abs().max()), 0.0, places=10)


if __name__ == "__main__":
    unittest.main()
