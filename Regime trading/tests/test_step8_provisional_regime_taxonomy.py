from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.step8_provisional_regime_taxonomy import (
    RESPONSE_DEFINITIONS,
    build_daily_taxonomy,
    build_definitions,
    build_summary,
    build_transitions,
)


def _feature_row(date: str, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "date": date,
        "point_in_time_safe": True,
        "minimum_regime_feature_ready": True,
        "full_regime_feature_ready": True,
        "feature_row_status": "FULL_READY",
        "median_early_realized_volatility": 0.0010,
        "median_opening_range_pct": 0.0030,
        "cross_sectional_return_dispersion": 0.0020,
        "gap_std": 0.0020,
        "breadth_above_open_at_cutoff": 0.50,
        "median_return_from_open": 0.0,
        "median_return_acceleration_0935_to_0940": 0.0,
        "median_gap": 0.0,
        "gap_up_breadth": 0.45,
        "gap_down_breadth": 0.45,
        "median_return_from_open_at_0935": 0.0,
        "median_return_from_open_at_0940": 0.0,
        "prior_5_session_market_return": 0.0,
    }
    row.update(overrides)
    return row


class Step8TaxonomyTests(unittest.TestCase):
    def test_every_session_gets_active_response(self) -> None:
        features = pd.DataFrame(
            [
                _feature_row("2026-01-01", minimum_regime_feature_ready=False),
                _feature_row("2026-01-02"),
                _feature_row(
                    "2026-01-03",
                    breadth_above_open_at_cutoff=0.90,
                    median_return_from_open=0.004,
                    median_return_acceleration_0935_to_0940=0.001,
                ),
            ]
        )
        daily = build_daily_taxonomy(features)
        self.assertEqual(len(daily), 3)
        self.assertTrue((daily["response_status"] == "ACTIVE_SIMULATION_RESPONSE_ASSIGNED").all())
        self.assertFalse(daily["candidate_playbook"].str.contains("NO_TRADE").any())
        self.assertEqual(daily.iloc[0]["primary_regime"], "DATA_LIMITED_DEFENSIVE")

    def test_recovery_routes_to_strict_v2_candidate(self) -> None:
        features = pd.DataFrame(
            [
                _feature_row(f"2026-01-{day:02d}")
                for day in range(1, 7)
            ]
            + [
                _feature_row(
                    "2026-01-07",
                    median_gap=-0.012,
                    gap_down_breadth=0.91,
                    gap_up_breadth=0.09,
                    breadth_above_open_at_cutoff=0.73,
                    median_return_from_open=0.0030,
                    median_return_acceleration_0935_to_0940=0.0020,
                    median_return_from_open_at_0935=0.0005,
                    median_return_from_open_at_0940=0.0030,
                )
            ]
        )
        daily = build_daily_taxonomy(features)
        recovery = daily.iloc[-1]
        self.assertEqual(recovery["primary_regime"], "RECOVERY")
        self.assertEqual(
            recovery["candidate_playbook"],
            "STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH",
        )
        self.assertEqual(recovery["strict_v1_router_status"], "STRICT_V2_CANDIDATE_REQUIRED")

    def test_future_values_do_not_change_prior_percentiles(self) -> None:
        rows = [
            _feature_row(
                f"2026-02-{day:02d}",
                median_early_realized_volatility=0.001 * day,
                median_opening_range_pct=0.002 * day,
            )
            for day in range(1, 9)
        ]
        original = build_daily_taxonomy(pd.DataFrame(rows))
        changed_rows = [dict(row) for row in rows]
        changed_rows[-1]["median_early_realized_volatility"] = 9.0
        changed_rows[-1]["median_opening_range_pct"] = 9.0
        changed = build_daily_taxonomy(pd.DataFrame(changed_rows))
        pd.testing.assert_series_equal(
            original.iloc[:-1]["early_volatility_prior_percentile"].reset_index(drop=True),
            changed.iloc[:-1]["early_volatility_prior_percentile"].reset_index(drop=True),
        )
        pd.testing.assert_series_equal(
            original.iloc[:-1]["opening_range_prior_percentile"].reset_index(drop=True),
            changed.iloc[:-1]["opening_range_prior_percentile"].reset_index(drop=True),
        )

    def test_summary_has_zero_no_trade_days_and_legacy_v1_ineligible(self) -> None:
        daily = build_daily_taxonomy(pd.DataFrame([_feature_row("2026-03-01")]))
        definitions = build_definitions()
        summary = build_summary(daily, definitions).iloc[0]
        self.assertEqual(summary["sessions_with_active_response"], 1)
        self.assertEqual(summary["no_trade_sessions"], 0)
        self.assertFalse(bool(summary["legacy_v1_router_eligible"]))
        self.assertEqual(len(definitions), len(RESPONSE_DEFINITIONS))
        self.assertTrue(definitions["active_response_required"].all())

    def test_transition_probabilities_sum_to_one(self) -> None:
        features = pd.DataFrame(
            [
                _feature_row("2026-04-01"),
                _feature_row(
                    "2026-04-02",
                    breadth_above_open_at_cutoff=0.90,
                    median_return_from_open=0.004,
                    median_return_acceleration_0935_to_0940=0.001,
                ),
                _feature_row(
                    "2026-04-03",
                    breadth_above_open_at_cutoff=0.10,
                    median_return_from_open=-0.004,
                    median_return_acceleration_0935_to_0940=-0.001,
                ),
                _feature_row("2026-04-04"),
            ]
        )
        transitions = build_transitions(build_daily_taxonomy(features))
        totals = transitions.groupby("from_regime")["transition_probability"].sum()
        self.assertTrue(((totals - 1.0).abs() < 1e-12).all())


if __name__ == "__main__":
    unittest.main()
