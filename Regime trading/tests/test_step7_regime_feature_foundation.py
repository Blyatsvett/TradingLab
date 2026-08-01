from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.research_regime_aware_gap_recovery import GAP_RECOVERY_TICKERS
from RegimeTrading.scripts.step7_regime_feature_foundation import (
    MODEL_FEATURE_COLUMNS,
    build_feature_foundation,
)


class RegimeFeatureFoundationTests(unittest.TestCase):
    @staticmethod
    def _dataset(days: int = 3, spike_0945: bool = False) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        dates = pd.date_range("2026-01-01", periods=days, freq="D")
        for ticker_index, ticker in enumerate(GAP_RECOVERY_TICKERS):
            base = 100.0 + ticker_index
            for day_index, day in enumerate(dates):
                open_price = base + day_index
                values = {
                    "09:30": open_price,
                    "09:35": open_price * 1.005,
                    "09:40": open_price * 1.010,
                    "09:45": open_price * (1.50 if spike_0945 else 1.012),
                    "16:30": open_price * 1.020,
                }
                for clock, close in values.items():
                    timestamp = pd.Timestamp(f"{day.date()} {clock}:00")
                    rows.append(
                        {
                            "datetime": timestamp,
                            "open": open_price,
                            "high": close * 1.001,
                            "low": close * 0.999,
                            "close": close,
                            "ticker": ticker,
                            "date": timestamp.date(),
                        }
                    )
        return pd.DataFrame(rows)

    def test_start_labelled_cutoff_excludes_0945_bar(self) -> None:
        result = build_feature_foundation(self._dataset(days=3, spike_0945=True))
        row = result.daily_features[result.daily_features["date"] == pd.Timestamp("2026-01-03").date()].iloc[0]
        self.assertAlmostEqual(float(row["mean_return_from_open"]), 0.01, places=10)
        self.assertEqual(str(row["max_early_source_timestamp"]), "2026-01-03 09:40:00")
        self.assertEqual(str(row["max_early_source_information_time"]), "2026-01-03 09:45:00")

    def test_previous_session_features_are_shifted(self) -> None:
        prices = self._dataset(days=4)
        result = build_feature_foundation(prices)
        day4 = result.daily_features[result.daily_features["date"] == pd.Timestamp("2026-01-04").date()].iloc[0]
        # Day 3 closes 2% above its own daily open; that known return becomes day 4's prior-session feature.
        expected_day3_return = ((102.0 + 0) * 1.02) / ((101.0 + 0) * 1.02) - 1.0
        # The exact base differs by ticker but each advances by one currency unit, so calculate from market history directly.
        prepared = prices.copy()
        prepared["date"] = pd.to_datetime(prepared["datetime"]).dt.date
        closes = prepared[prepared["datetime"].dt.strftime("%H:%M") == "16:30"].copy()
        closes = closes.sort_values(["ticker", "date"])
        closes["ret"] = closes.groupby("ticker")["close"].pct_change()
        expected = closes[closes["date"] == pd.Timestamp("2026-01-03").date()]["ret"].mean()
        self.assertAlmostEqual(float(day4["previous_session_equal_weight_return"]), float(expected), places=12)
        self.assertNotEqual(str(day4["previous_session_date"]), str(day4["date"]))

    def test_v1_outcomes_are_diagnostic_only(self) -> None:
        v1_daily = pd.DataFrame(
            [{
                "date": "2026-01-03",
                "valid_candidates": 2,
                "triggered_candidates": 1,
                "completed_trades": 1,
                "total_pnl_sek": 5.0,
                "total_account_return": 0.0005,
            }]
        )
        result = build_feature_foundation(self._dataset(days=3), v1_daily)
        day = result.daily_features[result.daily_features["date"] == pd.Timestamp("2026-01-03").date()].iloc[0]
        self.assertTrue(bool(day["v1_diagnostic_available"]))
        self.assertEqual(float(day["v1_realized_pnl_sek"]), 5.0)
        audit = result.audit[
            (result.audit["date"] == pd.Timestamp("2026-01-03").date())
            & (result.audit["audit_group"] == "V1_OUTCOME_DIAGNOSTIC")
        ].iloc[0]
        self.assertFalse(bool(audit["classifier_eligible"]))
        self.assertEqual(audit["audit_status"], "DIAGNOSTIC_ONLY_EXCLUDED_FROM_CLASSIFIER")

    def test_definitions_separate_current_and_planned_features(self) -> None:
        result = build_feature_foundation(self._dataset(days=3))
        definitions = result.definitions
        available = definitions[definitions["current_status"] == "AVAILABLE_NOW"]
        planned = definitions[definitions["current_status"] == "AFTER_DATA_EXPANSION"]
        self.assertEqual(set(MODEL_FEATURE_COLUMNS), set(available["feature_name"]))
        self.assertGreaterEqual(len(planned), 9)
        self.assertFalse(bool(planned["included_in_initial_classifier"].any()))

    def test_full_readiness_after_ten_session_history(self) -> None:
        result = build_feature_foundation(self._dataset(days=12))
        last = result.daily_features.sort_values("date").iloc[-1]
        self.assertTrue(bool(last["minimum_regime_feature_ready"]))
        self.assertTrue(bool(last["full_regime_feature_ready"]))
        self.assertEqual(last["feature_row_status"], "FULL_READY")
        self.assertEqual(int(result.summary.iloc[0]["point_in_time_leakage_rows"]), 0)


if __name__ == "__main__":
    unittest.main()
