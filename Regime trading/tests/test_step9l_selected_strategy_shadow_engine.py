from __future__ import annotations

import unittest

from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_selected_strategy_shadow_engine as step9l


class Step9LSelectedStrategyShadowEngineTests(unittest.TestCase):
    def test_registry_has_three_primaries_and_two_guardrails(self):
        self.assertEqual(len(step9l.CONTRACTS), 5)
        roles = [row["test_role"] for row in step9l.CONTRACTS]
        self.assertEqual(roles.count("PRIMARY_HYPOTHESIS"), 3)
        self.assertEqual(roles.count("NEGATIVE_GUARDRAIL"), 2)

    def test_selected_regimes_are_exact(self):
        primary = {
            row["contract_id"]: row["primary_regime"]
            for row in step9l.CONTRACTS
            if row["test_role"] == "PRIMARY_HYPOTHESIS"
        }
        self.assertEqual(
            set(primary.values()),
            {"VOLATILITY_EXPANSION", "RANGE_LOW_VOL", "HIGH_DISPERSION"},
        )

    def test_step9l_ledger_is_separate_from_step9i_v2(self):
        self.assertNotEqual(step9l.SHADOW_LEDGER_DB, step9i.SHADOW_LEDGER_DB)
        self.assertIn("step9l", step9l.SHADOW_LEDGER_DB.name.lower())
        self.assertIn("step9i_v2", step9i.SHADOW_LEDGER_DB.name.lower())

    def test_laggard_alignment_uses_early_move_direction(self):
        row = {"early_open": 100.0, "close_0940": 99.0, "cutoff_close": 99.0}
        with step9l._patched_step9l_globals():
            delayed_side = step9g._intended_side(
                "DELAYED_EARLY_MOVE_REVERSAL_1R_V1", row
            )
            catchup_side = step9g._intended_side(
                "HD_LAGGARD_MIDPOINT_CATCHUP_1R_V1", row
            )
        self.assertEqual(delayed_side, "SHORT")
        self.assertEqual(catchup_side, "SHORT")

    def test_context_restores_step9i_and_shared_contracts(self):
        original_experiment = step9i.EXPERIMENT_ID
        original_contracts = step9h.CONTRACTS
        with step9l._patched_step9l_globals():
            self.assertEqual(step9i.EXPERIMENT_ID, step9l.EXPERIMENT_ID)
            self.assertIs(step9h.CONTRACTS, step9l.CONTRACTS)
        self.assertEqual(step9i.EXPERIMENT_ID, original_experiment)
        self.assertIs(step9h.CONTRACTS, original_contracts)

    def test_rlv_selected_cohort_matches_corrected_historical_winner(self):
        row = next(
            item for item in step9l.CONTRACTS
            if item["contract_id"] == "L_RLV_GROUP_ALIGNED_LAGGARD_DELAYED_REVERSAL_V1"
        )
        self.assertEqual(row["ticker_relative_states"], "EARLY_LAGGARD")
        self.assertEqual(row["sector_alignment_states"], "ALIGNED_WITH_GROUP")
        self.assertIn("LABEL_CORRECTED", row["selection_status"])

    def test_hd_guardrails_are_exact(self):
        guards = {
            row["contract_id"]: row
            for row in step9l.CONTRACTS
            if row["test_role"] == "NEGATIVE_GUARDRAIL"
        }
        leader = guards["L_HD_EARLY_LEADER_CONTINUATION_AVOID_V1"]
        aligned = guards["L_HD_ALIGNED_LAGGARD_CATCHUP_AVOID_V1"]
        self.assertEqual(leader["ticker_relative_states"], "EARLY_LEADER")
        self.assertEqual(leader["base_challenger_id"], "EARLY_MOVE_CONTINUATION_1_5R_V1")
        self.assertEqual(aligned["ticker_relative_states"], "EARLY_LAGGARD")
        self.assertEqual(aligned["sector_alignment_states"], "ALIGNED_WITH_GROUP")

    def test_router_is_never_active_in_registry(self):
        registry = step9l.contract_registry()
        self.assertTrue((registry["router_active"] == False).all())  # noqa: E712


if __name__ == "__main__":
    unittest.main()
