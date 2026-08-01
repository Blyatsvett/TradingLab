from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.v1_validation_provider_quality import (
    build_mismatch_detail,
    build_session_detail,
    build_validation_step5,
)


class ProviderQualityValidationTests(unittest.TestCase):
    @staticmethod
    def _bars(day: str, ticker: str, end_clock: str = "16:30") -> pd.DataFrame:
        times = pd.date_range(f"{day} 09:30", f"{day} {end_clock}", freq="5min")
        return pd.DataFrame(
            {
                "ticker": ticker,
                "datetime": times,
                "nasdaq_open": 100.0,
                "nasdaq_high": 101.0,
                "nasdaq_low": 99.0,
                "nasdaq_close": 100.5,
                "yahoo_open": 100.0,
                "yahoo_high": 101.0,
                "yahoo_low": 99.0,
                "yahoo_close": 100.5,
                "has_nasdaq_bar": True,
                "has_yahoo_bar": True,
                "has_both": True,
                "ohlc_within_1bp": True,
            }
        )

    @staticmethod
    def _decision(
        day: str,
        ticker: str,
        yahoo_class: str = "INVALID",
        nasdaq_class: str = "INVALID",
        exact: bool = True,
        invalid_reason_match: bool = True,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "strategy_id": "REGIME_AWARE_GAP_RECOVERY_V1",
                    "date": day,
                    "ticker": ticker,
                    "sector_group": "TEST",
                    "setup_comparable": True,
                    "trigger_final_comparable": False,
                    "outcome_comparable": False,
                    "yahoo_decision_class": yahoo_class,
                    "nasdaq_decision_class": nasdaq_class,
                    "yahoo_invalid_reason": "A",
                    "nasdaq_invalid_reason": "A" if invalid_reason_match else "B",
                    "overall_current_decision_match": exact,
                    "invalid_reason_match": invalid_reason_match,
                    "entry_trigger_within_1bp": True,
                    "stop_price_within_1bp": True,
                    "current_trigger_state_match": True,
                    "final_trigger_decision_match": False,
                    "exit_reason_match": False,
                }
            ]
        )

    def test_full_session_passes_all_completeness_gates(self) -> None:
        detail = build_session_detail(
            self._decision("2026-01-02", "AAA.ST"),
            self._bars("2026-01-02", "AAA.ST"),
        )
        row = detail.iloc[0]
        self.assertEqual(row["comparison_stage"], "FINAL_OUTCOME_READY")
        self.assertTrue(bool(row["setup_quality_gate_both"]))
        self.assertTrue(bool(row["entry_quality_gate_both"]))
        self.assertTrue(bool(row["eod_quality_gate_both"]))
        self.assertEqual(int(row["expected_full_bars"]), 85)
        self.assertEqual(int(row["both_full_bars"]), 85)

    def test_partial_session_is_final_trigger_ready_not_eod_ready(self) -> None:
        detail = build_session_detail(
            self._decision("2026-01-02", "AAA.ST"),
            self._bars("2026-01-02", "AAA.ST", end_clock="13:00"),
        )
        row = detail.iloc[0]
        self.assertEqual(row["comparison_stage"], "FINAL_TRIGGER_READY")
        self.assertTrue(bool(row["entry_quality_gate_both"]))
        self.assertFalse(bool(row["eod_quality_gate_both"]))

    def test_operational_action_can_match_when_diagnostic_reason_differs(self) -> None:
        detail = build_session_detail(
            self._decision(
                "2026-01-02",
                "AAA.ST",
                exact=False,
                invalid_reason_match=False,
            ),
            self._bars("2026-01-02", "AAA.ST"),
        )
        row = detail.iloc[0]
        self.assertTrue(bool(row["trading_action_match"]))
        self.assertFalse(bool(row["exact_diagnostic_match"]))
        mismatches = build_mismatch_detail(detail)
        self.assertIn("DIAGNOSTIC_DETAIL_MISMATCH", set(mismatches["issue_type"]))
        self.assertNotIn("TRADING_ACTION_MISMATCH", set(mismatches["issue_type"]))

    def test_summary_marks_small_strong_sample_as_early(self) -> None:
        decisions = self._decision("2026-01-02", "AAA.ST")
        result = build_validation_step5(
            decisions,
            self._bars("2026-01-02", "AAA.ST"),
        )
        summary = result.summary.iloc[0]
        self.assertEqual(float(summary["trading_action_match_rate"]), 1.0)
        self.assertEqual(
            summary["provider_quality_classification"],
            "EARLY_STRONG_ALIGNMENT_MORE_COMPLETE_SESSIONS_REQUIRED",
        )


if __name__ == "__main__":
    unittest.main()
