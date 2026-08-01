from __future__ import annotations

import unittest

from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_selected_strategy_shadow_engine as step9l_v1
from RegimeTrading.scripts import step9l_v2_selected_strategy_shadow_engine as step9l_v2


class Step9LV2SelectedStrategyShadowEngineTests(unittest.TestCase):
    def test_registry_has_four_primaries_and_three_guardrails(self):
        self.assertEqual(len(step9l_v2.CONTRACTS), 7)
        roles = [row["test_role"] for row in step9l_v2.CONTRACTS]
        self.assertEqual(roles.count("PRIMARY_HYPOTHESIS"), 4)
        self.assertEqual(roles.count("NEGATIVE_GUARDRAIL"), 3)

    def test_v1_contracts_are_preserved_exactly(self):
        self.assertEqual(step9l_v2.CONTRACTS[: len(step9l_v1.CONTRACTS)], step9l_v1.CONTRACTS)

    def test_selected_regimes_are_exact(self):
        primary = {
            row["primary_regime"]
            for row in step9l_v2.CONTRACTS
            if row["test_role"] == "PRIMARY_HYPOTHESIS"
        }
        self.assertEqual(
            primary,
            {
                "VOLATILITY_EXPANSION",
                "RANGE_LOW_VOL",
                "HIGH_DISPERSION",
                "HIGH_VOL_REVERSAL",
            },
        )

    def test_v2_ledgers_are_separate_from_step9i_and_v1(self):
        self.assertNotEqual(step9l_v2.SHADOW_LEDGER_DB, step9i.SHADOW_LEDGER_DB)
        self.assertNotEqual(step9l_v2.SHADOW_LEDGER_DB, step9l_v1.SHADOW_LEDGER_DB)
        self.assertIn("step9l_v2", step9l_v2.SHADOW_LEDGER_DB.name.lower())

    def test_hvr_directional_breakout_is_exact(self):
        row = next(
            item for item in step9l_v2.CONTRACTS
            if item["contract_id"] == "L2_HVR_DIRECTIONAL_BREAKOUT_2R_V1"
        )
        self.assertEqual(row["test_role"], "PRIMARY_HYPOTHESIS")
        self.assertEqual(row["primary_regime"], "HIGH_VOL_REVERSAL")
        self.assertEqual(row["base_challenger_id"], "DIRECTIONAL_VOLATILITY_BREAKOUT_2R_V1")
        self.assertEqual(row["sector_alignment_states"], "ANY")
        self.assertEqual(row["selection_status"], "PROSPECTIVE_HVR_CHALLENGER")

    def test_hvr_guardrail_is_exact(self):
        row = next(
            item for item in step9l_v2.CONTRACTS
            if item["contract_id"] == "L2_HVR_ALIGNED_DELAYED_REVERSAL_AVOID_V1"
        )
        self.assertEqual(row["test_role"], "NEGATIVE_GUARDRAIL")
        self.assertEqual(row["primary_regime"], "HIGH_VOL_REVERSAL")
        self.assertEqual(row["base_challenger_id"], "DELAYED_EARLY_MOVE_REVERSAL_1R_V1")
        self.assertEqual(row["sector_alignment_states"], "ALIGNED_WITH_GROUP")

    def test_hvr_guardrail_alignment_uses_early_move_direction(self):
        row = {"early_open": 100.0, "close_0940": 99.0, "cutoff_close": 99.0}
        with step9l_v2._patched_step9l_v2_globals():
            alignment_side = step9g._intended_side(
                "DELAYED_EARLY_MOVE_REVERSAL_1R_V1", row
            )
        self.assertEqual(alignment_side, "SHORT")

    def test_context_restores_step9i_and_shared_contracts(self):
        original_experiment = step9i.EXPERIMENT_ID
        original_contracts = step9h.CONTRACTS
        with step9l_v2._patched_step9l_v2_globals():
            self.assertEqual(step9i.EXPERIMENT_ID, step9l_v2.EXPERIMENT_ID)
            self.assertIs(step9h.CONTRACTS, step9l_v2.CONTRACTS)
        self.assertEqual(step9i.EXPERIMENT_ID, original_experiment)
        self.assertIs(step9h.CONTRACTS, original_contracts)

    def test_router_is_never_active_in_registry(self):
        registry = step9l_v2.contract_registry()
        self.assertTrue((registry["router_active"] == False).all())  # noqa: E712
        self.assertTrue(registry["engine_version"].eq("STEP9L_V2").all())


if __name__ == "__main__":
    unittest.main()
