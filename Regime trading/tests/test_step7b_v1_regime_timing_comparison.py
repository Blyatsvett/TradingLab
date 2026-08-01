from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.research_regime_aware_gap_recovery import (
    GAP_RECOVERY_TICKERS,
    build_daily_reference,
    calculate_early_market_regime,
)
from RegimeTrading.scripts.step7_regime_feature_foundation import build_feature_foundation
from RegimeTrading.scripts.step7b_v1_regime_timing_comparison import (
    CANDIDATE_COLUMNS,
    DAILY_COLUMNS,
    SUMMARY_COLUMNS,
    TRADE_COLUMNS,
    _calculate_regime_at_label,
    run_comparison,
)


class V1RegimeTimingComparisonTests(unittest.TestCase):
    @staticmethod
    def _dataset(days: int = 3, reverse_at_0945: bool = True) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        dates = pd.date_range("2026-01-01", periods=days, freq="D")
        for ticker_index, ticker in enumerate(GAP_RECOVERY_TICKERS):
            base = 100.0 + ticker_index
            previous_close = base
            for day_index, day in enumerate(dates):
                # Day 1 establishes history. Later days open one percent below
                # the preceding close, then strengthen through the strict 09:40 cutoff.
                open_price = previous_close if day_index == 0 else previous_close * 0.99
                close_0940 = open_price * 1.006
                close_0945 = open_price * (0.994 if reverse_at_0945 else 1.007)
                close_eod = open_price * 1.012
                values = {
                    "09:00": open_price,
                    "09:30": open_price,
                    "09:35": open_price * 1.003,
                    "09:40": close_0940,
                    "09:45": close_0945,
                    "09:50": open_price * 1.010,
                    "16:30": close_eod,
                }
                for clock, close in values.items():
                    timestamp = pd.Timestamp(f"{day.date()} {clock}:00")
                    rows.append(
                        {
                            "datetime": timestamp,
                            "open": open_price,
                            "high": max(open_price, close) * 1.001,
                            "low": min(open_price, close) * 0.999,
                            "close": close,
                            "ticker": ticker,
                            "date": timestamp.date(),
                        }
                    )
                previous_close = close_eod
        return pd.DataFrame(rows)

    def test_legacy_helper_matches_frozen_v1_implementation(self) -> None:
        prices = self._dataset(reverse_at_0945=False)
        daily_reference = build_daily_reference(prices)
        frozen = calculate_early_market_regime(prices, daily_reference).sort_values("date").reset_index(drop=True)
        comparison_legacy = _calculate_regime_at_label(prices, daily_reference, "09:45").sort_values("date").reset_index(drop=True)
        pd.testing.assert_frame_equal(frozen, comparison_legacy, check_dtype=False)

    def test_strict_cutoff_detects_0945_reversal(self) -> None:
        prices = self._dataset(reverse_at_0945=True)
        daily_reference = build_daily_reference(prices)
        strict = _calculate_regime_at_label(prices, daily_reference, "09:40")
        legacy = calculate_early_market_regime(prices, daily_reference)
        merged = strict.merge(legacy, on="date", suffixes=("_strict", "_legacy"))
        eligible = merged[merged["sample_size_strict"] >= 5]
        self.assertGreater(len(eligible), 0)
        self.assertTrue(bool((eligible["favorable_regime_strict"] != eligible["favorable_regime_legacy"]).any()))

    def test_first_session_without_history_is_not_leakage_failure(self) -> None:
        result = build_feature_foundation(self._dataset(days=3, reverse_at_0945=False))
        first_date = result.daily_features.sort_values("date").iloc[0]["date"]
        audit = result.audit[
            (result.audit["date"] == first_date)
            & (result.audit["audit_group"] == "PREVIOUS_AND_MULTI_SESSION_HISTORY")
        ].iloc[0]
        self.assertTrue(bool(audit["point_in_time_pass"]))
        self.assertEqual(audit["audit_status"], "NOT_APPLICABLE_NO_PRIOR_SESSION")
        self.assertEqual(int(result.summary.iloc[0]["point_in_time_leakage_rows"]), 0)

    def test_run_comparison_exports_stable_shapes(self) -> None:
        # Exercise the actual local test database and verify stable schemas.
        summary, daily, candidates, trades = run_comparison()
        self.assertEqual(list(summary.columns), SUMMARY_COLUMNS)
        self.assertEqual(list(daily.columns), DAILY_COLUMNS)
        self.assertEqual(list(candidates.columns), CANDIDATE_COLUMNS)
        self.assertEqual(list(trades.columns), TRADE_COLUMNS)
        self.assertEqual(len(summary), 1)
        self.assertGreaterEqual(int(summary.iloc[0]["observed_sessions"]), 1)
        self.assertIn(
            summary.iloc[0]["classification"],
            {
                "STRICT_0940_AND_LEGACY_0945_IDENTICAL",
                "LABEL_DIFFERENCES_NO_TRADING_IMPACT",
                "NON_GATE_DIAGNOSTIC_DIFFERENCES_NO_PORTFOLIO_IMPACT",
                "LIMITED_V1_TIMING_IMPACT_VERSIONED_FIX_RECOMMENDED",
                "MATERIAL_V1_TIMING_IMPACT_VERSIONED_FIX_REQUIRED",
            },
        )


if __name__ == "__main__":
    unittest.main()
