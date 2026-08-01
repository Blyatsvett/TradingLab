from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_selected_strategy_shadow_engine as step9l_v1
from RegimeTrading.scripts import step9l_v2_selected_strategy_shadow_engine as step9l_v2
from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as step9l_v3


class Step9LV3SelectedStrategyShadowEngineTests(unittest.TestCase):
    def test_registry_has_five_primaries_and_three_guardrails(self):
        self.assertEqual(len(step9l_v3.CONTRACTS), 8)
        roles = [row["test_role"] for row in step9l_v3.CONTRACTS]
        self.assertEqual(roles.count("PRIMARY_HYPOTHESIS"), 5)
        self.assertEqual(roles.count("NEGATIVE_GUARDRAIL"), 3)

    def test_v2_contracts_are_preserved_exactly(self):
        self.assertEqual(
            step9l_v3.CONTRACTS[: len(step9l_v2.CONTRACTS)],
            step9l_v2.CONTRACTS,
        )

    def test_selected_regimes_are_exact(self):
        primary = {
            row["primary_regime"]
            for row in step9l_v3.CONTRACTS
            if row["test_role"] == "PRIMARY_HYPOTHESIS"
        }
        self.assertEqual(
            primary,
            {
                "VOLATILITY_EXPANSION",
                "RANGE_LOW_VOL",
                "HIGH_DISPERSION",
                "HIGH_VOL_REVERSAL",
                "TREND_UP",
            },
        )
        self.assertNotIn("TREND_DOWN", primary)

    def test_v3_ledger_is_separate_from_all_earlier_engines(self):
        self.assertNotEqual(step9l_v3.SHADOW_LEDGER_DB, step9i.SHADOW_LEDGER_DB)
        self.assertNotEqual(step9l_v3.SHADOW_LEDGER_DB, step9l_v1.SHADOW_LEDGER_DB)
        self.assertNotEqual(step9l_v3.SHADOW_LEDGER_DB, step9l_v2.SHADOW_LEDGER_DB)
        self.assertIn("step9l_v3", step9l_v3.SHADOW_LEDGER_DB.name.lower())

    def test_trend_up_contract_is_exact(self):
        row = next(
            item for item in step9l_v3.CONTRACTS
            if item["contract_id"] == "L3_TU_ALIGNED_DELAYED_REVERSAL_1R_V1"
        )
        self.assertEqual(row["test_role"], "PRIMARY_HYPOTHESIS")
        self.assertEqual(row["primary_regime"], "TREND_UP")
        self.assertEqual(row["base_challenger_id"], "DELAYED_EARLY_MOVE_REVERSAL_1R_V1")
        self.assertEqual(row["ticker_relative_states"], "ANY")
        self.assertEqual(row["sector_alignment_states"], "ALIGNED_WITH_GROUP")
        self.assertEqual(row["early_move_regime_relation"], "ALIGNED_WITH_REGIME")
        self.assertEqual(
            row["selection_status"],
            "PROSPECTIVE_TREND_UP_REVERSAL_CHALLENGER",
        )

    def test_trend_up_alignment_uses_early_move_not_later_short_trade(self):
        row = {"early_open": 100.0, "close_0940": 101.0, "cutoff_close": 101.0}
        with step9l_v3._patched_step9l_v3_globals():
            alignment_side = step9g._intended_side(
                "DELAYED_EARLY_MOVE_REVERSAL_1R_V1", row
            )
        self.assertEqual(alignment_side, "LONG")

    def test_trend_up_contract_rejects_downward_early_move(self):
        contract = next(
            item for item in step9l_v3.CONTRACTS
            if item["contract_id"] == "L3_TU_ALIGNED_DELAYED_REVERSAL_1R_V1"
        )
        states = pd.DataFrame(
            [
                {
                    "ticker_relative_state": "NEUTRAL",
                    "volatility_bucket": "MEDIUM",
                    "contract_sector_alignment": "ALIGNED_WITH_GROUP",
                    "taxonomy_point_in_time_pass": True,
                    "early_open": 100.0,
                    "close_0940": 101.0,
                    "cutoff_close": 101.0,
                },
                {
                    "ticker_relative_state": "NEUTRAL",
                    "volatility_bucket": "MEDIUM",
                    "contract_sector_alignment": "ALIGNED_WITH_GROUP",
                    "taxonomy_point_in_time_pass": True,
                    "early_open": 100.0,
                    "close_0940": 99.0,
                    "cutoff_close": 99.0,
                },
            ]
        )
        with step9l_v3._patched_step9l_v3_globals():
            mask = step9g._contract_mask(states, contract)
        self.assertEqual(mask.tolist(), [True, False])

    def test_context_restores_shared_globals(self):
        original_experiment = step9i.EXPERIMENT_ID
        original_contracts = step9h.CONTRACTS
        original_mask = step9g._contract_mask
        with step9l_v3._patched_step9l_v3_globals():
            self.assertEqual(step9i.EXPERIMENT_ID, step9l_v3.EXPERIMENT_ID)
            self.assertIs(step9h.CONTRACTS, step9l_v3.CONTRACTS)
            self.assertIsNot(step9g._contract_mask, original_mask)
        self.assertEqual(step9i.EXPERIMENT_ID, original_experiment)
        self.assertIs(step9h.CONTRACTS, original_contracts)
        self.assertIs(step9g._contract_mask, original_mask)

    def test_registry_is_non_router_and_labels_v3(self):
        registry = step9l_v3.contract_registry()
        self.assertTrue((registry["router_active"] == False).all())  # noqa: E712
        self.assertTrue(registry["engine_version"].eq("STEP9L_V3").all())
        trend = registry[
            registry["contract_id"].eq("L3_TU_ALIGNED_DELAYED_REVERSAL_1R_V1")
        ].iloc[0]
        self.assertEqual(trend["early_move_regime_relation"], "ALIGNED_WITH_REGIME")


if __name__ == "__main__":
    unittest.main()
