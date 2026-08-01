from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9m_high_vol_reversal_strategy_research as step9m


class Step9MHighVolReversalResearchTests(unittest.TestCase):
    def test_registry_is_small_and_exact(self):
        self.assertEqual(len(step9m.CONTRACTS), 5)
        self.assertEqual(sum(c["test_role"] == "PRIMARY_HYPOTHESIS" for c in step9m.CONTRACTS), 3)
        self.assertEqual(sum(c["test_role"] != "PRIMARY_HYPOTHESIS" for c in step9m.CONTRACTS), 2)

    def test_every_contract_is_high_vol_reversal(self):
        self.assertTrue(all(c["primary_regime"] == "HIGH_VOL_REVERSAL" for c in step9m.CONTRACTS))

    def test_contracts_cover_reversal_breakout_and_control(self):
        ids = {c["contract_id"] for c in step9m.CONTRACTS}
        self.assertIn("M_HVR_DELAYED_REVERSAL_ALL_V1", ids)
        self.assertIn("M_HVR_ALIGNED_DELAYED_REVERSAL_V1", ids)
        self.assertIn("M_HVR_DIRECTIONAL_BREAKOUT_2R_V1", ids)
        self.assertIn("M_HVR_CONTRARIAN_DELAYED_REVERSAL_CONTROL_V1", ids)
        self.assertIn("M_HVR_EARLY_CONTINUATION_CONTROL_V1", ids)

    def test_alignment_uses_early_move_direction(self):
        row_up = {"early_open": 100.0, "close_0940": 101.0}
        row_down = {"early_open": 100.0, "close_0940": 99.0}
        with step9m._patched_step9m_engine():
            self.assertEqual(step9g._intended_side(step9m.DELAYED_REVERSAL_ID, row_up), "LONG")
            self.assertEqual(step9g._intended_side(step9m.DELAYED_REVERSAL_ID, row_down), "SHORT")

    def test_context_restores_step9g_globals(self):
        original_id = step9g.EXPERIMENT_ID
        original_contracts = step9g.CONTRACTS
        original_intended = step9g._intended_side
        with step9m._patched_step9m_engine():
            self.assertEqual(step9g.EXPERIMENT_ID, step9m.EXPERIMENT_ID)
            self.assertIs(step9g.CONTRACTS, step9m.CONTRACTS)
        self.assertEqual(step9g.EXPERIMENT_ID, original_id)
        self.assertIs(step9g.CONTRACTS, original_contracts)
        self.assertIs(step9g._intended_side, original_intended)

    def test_audit_uses_combined23_trading_tickers(self):
        taxonomy = pd.DataFrame([
            {"date": "2026-06-01", "primary_regime": "HIGH_VOL_REVERSAL"}
        ])
        diagnostics = pd.DataFrame(
            [{"date": "2026-06-01", "ticker": ticker} for ticker in step9m.step9i.TRADING_TICKERS]
        )
        registry = pd.DataFrame([
            {
                "primary_regime": "HIGH_VOL_REVERSAL",
                "router_active": False,
                "promotion_eligible": False,
            }
        ])
        audit = step9m.extend_audit(pd.DataFrame(), taxonomy, diagnostics, registry)
        coverage = audit[audit["audit_item"].eq("HIGH_VOL_REVERSAL_DIAGNOSTIC_COVERAGE_23_TICKERS")].iloc[0]
        self.assertEqual(int(coverage["rows_checked"]), len(step9m.step9i.TRADING_TICKERS))
        self.assertTrue(bool(coverage["audit_pass"]))

    def test_summary_never_promotes_or_routes(self):
        taxonomy = pd.DataFrame([
            {"date": "2026-06-01", "primary_regime": "HIGH_VOL_REVERSAL"}
        ])
        diagnostics = pd.DataFrame([{"date": "2026-06-01"}])
        performance = pd.DataFrame([
            {"test_role": "PRIMARY_HYPOTHESIS", "net_pnl_risk_capped_sek": 1.0}
        ])
        time_split = pd.DataFrame([
            {"test_role": "PRIMARY_HYPOTHESIS", "phase": "LATE_HALF", "net_pnl_risk_capped_sek": 1.0}
        ])
        audit = pd.DataFrame([{"audit_pass": True}])
        summary = step9m.build_summary(
            "2026-06-01", "2026-06-01", taxonomy, diagnostics,
            pd.DataFrame(), performance, time_split, audit,
        ).iloc[0]
        self.assertEqual(int(summary["strategies_promoted"]), 0)
        self.assertFalse(bool(summary["router_active"]))


if __name__ == "__main__":
    unittest.main()
