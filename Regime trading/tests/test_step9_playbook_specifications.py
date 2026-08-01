import unittest

import pandas as pd

from RegimeTrading.scripts.step8_provisional_regime_taxonomy import REGIMES
from RegimeTrading.scripts.step9_playbook_specifications import (
    PLAYBOOKS,
    _registry_frame,
    _requirements_frame,
    build_coverage,
    build_summary,
)


class Step9PlaybookSpecificationTests(unittest.TestCase):
    def _taxonomy(self) -> pd.DataFrame:
        rows = []
        for index, regime in enumerate(REGIMES, start=1):
            rows.append(
                {
                    "date": f"2026-01-{index:02d}",
                    "primary_regime": regime,
                    "regime_confidence": 0.50,
                    "confidence_band": "MEDIUM",
                    "taxonomy_eligible": regime != "DATA_LIMITED_DEFENSIVE",
                    "data_quality_override": regime == "DATA_LIMITED_DEFENSIVE",
                    "point_in_time_safe": True,
                }
            )
        return pd.DataFrame(rows)

    def test_every_regime_has_one_unique_playbook(self):
        registry = _registry_frame()
        self.assertEqual(set(registry["regime"]), set(REGIMES))
        self.assertEqual(len(registry), len(REGIMES))
        self.assertEqual(registry["playbook_id"].nunique(), len(REGIMES))
        self.assertTrue(registry["stop_rule"].str.len().gt(0).all())
        self.assertTrue(registry["target_rule"].str.len().gt(0).all())
        self.assertTrue(registry["time_exit_rule"].str.len().gt(0).all())

    def test_recovery_uses_strict_v2_and_legacy_is_ineligible(self):
        recovery = PLAYBOOKS["RECOVERY"]
        self.assertEqual(
            recovery.playbook_id,
            "STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH",
        )
        self.assertFalse(recovery.legacy_v1_eligible)
        self.assertIn("09:40", recovery.point_in_time_rule)

    def test_all_sessions_receive_active_point_in_time_contract(self):
        registry = _registry_frame()
        coverage = build_coverage(self._taxonomy(), registry)
        self.assertEqual(len(coverage), len(REGIMES))
        self.assertTrue(coverage["active_simulation_contract"].all())
        self.assertTrue(coverage["point_in_time_contract_pass"].all())
        self.assertTrue(coverage["coverage_status"].eq("ACTIVE_EXECUTABLE_CONTRACT").all())
        self.assertFalse(coverage["legacy_v1_router_eligible"].any())

    def test_missing_optional_inputs_have_explicit_proxies(self):
        requirements = _requirements_frame()
        optional_missing = requirements[
            (~requirements["available_in_current_project"])
            & (~requirements["required_for_baseline_simulation"])
        ]
        self.assertGreater(len(optional_missing), 0)
        self.assertTrue(optional_missing["fallback_or_proxy"].str.len().gt(0).all())
        self.assertTrue(
            optional_missing["availability_status"].eq(
                "OPTIONAL_UPGRADE_PROXY_DEFINED"
            ).all()
        )
        blocking = requirements[requirements["availability_status"].eq("BLOCKING_MISSING")]
        self.assertEqual(len(blocking), 0)

    def test_summary_reports_complete_executable_coverage(self):
        registry = _registry_frame()
        requirements = _requirements_frame()
        coverage = build_coverage(self._taxonomy(), registry)
        summary = build_summary(registry, requirements, coverage).iloc[0]
        self.assertEqual(int(summary["taxonomy_sessions"]), len(REGIMES))
        self.assertEqual(int(summary["sessions_without_mapped_playbook"]), 0)
        self.assertEqual(int(summary["no_trade_sessions"]), 0)
        self.assertEqual(int(summary["blocked_playbooks"]), 0)
        self.assertTrue(bool(summary["all_entries_point_in_time_safe"]))
        self.assertFalse(bool(summary["legacy_v1_router_eligible"]))
        self.assertEqual(
            summary["classification"],
            "EXECUTABLE_PLAYBOOK_SPECIFICATIONS_READY_FOR_BASELINE_SIMULATION",
        )


    def test_data_limited_first_session_without_prior_history_is_safe(self):
        taxonomy = pd.DataFrame(
            [
                {
                    "date": "2026-04-29",
                    "primary_regime": "DATA_LIMITED_DEFENSIVE",
                    "regime_confidence": 0.25,
                    "confidence_band": "LOW",
                    "taxonomy_eligible": False,
                    "data_quality_override": True,
                    "point_in_time_safe": False,
                    "portfolio_structure": "MINIMUM_GROSS_MARKET_NEUTRAL",
                    "research_risk_multiplier": 0.25,
                }
            ]
        )
        coverage = build_coverage(taxonomy, _registry_frame())
        row = coverage.iloc[0]
        self.assertTrue(bool(row["point_in_time_contract_pass"]))
        self.assertEqual(
            row["point_in_time_contract_reason"],
            "DATA_LIMITED_DETERMINISTIC_FALLBACK_SAFE",
        )
        self.assertEqual(row["coverage_status"], "ACTIVE_EXECUTABLE_CONTRACT")

    def test_directional_contract_still_fails_unsafe_taxonomy_input(self):
        taxonomy = pd.DataFrame(
            [
                {
                    "date": "2026-04-29",
                    "primary_regime": "TREND_UP",
                    "regime_confidence": 0.50,
                    "confidence_band": "MEDIUM",
                    "taxonomy_eligible": True,
                    "data_quality_override": False,
                    "point_in_time_safe": False,
                }
            ]
        )
        coverage = build_coverage(taxonomy, _registry_frame())
        row = coverage.iloc[0]
        self.assertFalse(bool(row["point_in_time_contract_pass"]))
        self.assertEqual(
            row["point_in_time_contract_reason"],
            "TAXONOMY_POINT_IN_TIME_INPUT_FAILED",
        )

    def test_contract_merge_exports_structure_and_risk_fields(self):
        taxonomy = self._taxonomy()
        taxonomy["portfolio_structure"] = "TAXONOMY_PLACEHOLDER"
        taxonomy["research_risk_multiplier"] = -1.0
        coverage = build_coverage(taxonomy, _registry_frame())
        self.assertTrue(coverage["portfolio_structure"].str.len().gt(0).all())
        self.assertTrue(coverage["research_risk_multiplier"].notna().all())
        recovery = coverage.loc[coverage["primary_regime"].eq("RECOVERY")].iloc[0]
        self.assertEqual(recovery["portfolio_structure"], "LONG_ONLY_RECOVERY_BASKET")
        self.assertEqual(float(recovery["research_risk_multiplier"]), 1.0)

    def test_data_limited_requirements_do_not_require_prior_history(self):
        requirements = _requirements_frame()
        data_limited = requirements[
            requirements["regime"].eq("DATA_LIMITED_DEFENSIVE")
        ]
        self.assertFalse(data_limited["requirement_group"].eq("PRIOR_REFERENCE").any())
        self.assertTrue(
            data_limited["requirement_group"].eq("STATIC_CONFIGURATION").any()
        )


if __name__ == "__main__":
    unittest.main()
