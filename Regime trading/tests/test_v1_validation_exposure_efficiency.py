from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.v1_validation_exposure_efficiency import (
    _observed_session_ends,
    build_daily,
    build_interval_detail,
    build_position_detail,
    build_sizing_scenarios,
    build_summary,
)


class ExposureEfficiencyValidationTests(unittest.TestCase):
    @staticmethod
    def _ledger(rows: list[dict]) -> pd.DataFrame:
        defaults = {
            "selected_for_portfolio": True,
            "selection_status": "SELECTED_CLOSED",
            "model_position_size_sek": 1000.0,
            "portfolio_pnl_sek": 10.0,
            "exit_reason": "TARGET_HIT",
            "early_market_regime": "EARLY_BROAD_STRENGTH",
            "research_universe": "TEST",
        }
        output = []
        for index, row in enumerate(rows):
            item = defaults | row
            item.setdefault("source_trade_row", index)
            output.append(item)
        return pd.DataFrame(output)

    @staticmethod
    def _candidates(date_text: str, last_bar: str) -> pd.DataFrame:
        return pd.DataFrame([{"date": date_text, "last_bar": last_bar}])

    def test_overlapping_positions_produce_correct_occupancy_minutes(self) -> None:
        date_text = "2026-01-02"
        ledger = self._ledger(
            [
                {
                    "date": date_text,
                    "ticker": "AAA.ST",
                    "entry_time": f"{date_text} 10:00:00",
                    "exit_time": f"{date_text} 11:00:00",
                },
                {
                    "date": date_text,
                    "ticker": "BBB.ST",
                    "entry_time": f"{date_text} 10:30:00",
                    "exit_time": f"{date_text} 12:00:00",
                },
            ]
        )
        observed = _observed_session_ends(
            [date_text], self._candidates(date_text, f"{date_text} 16:30:00")
        )
        detail = build_position_detail(ledger, observed)
        intervals = build_interval_detail([date_text], observed, detail)
        daily = build_daily([date_text], observed, detail, intervals).iloc[0]
        self.assertAlmostEqual(float(daily["zero_position_minutes"]), 285.0)
        self.assertAlmostEqual(float(daily["one_position_minutes"]), 90.0)
        self.assertAlmostEqual(float(daily["two_position_minutes"]), 30.0)
        self.assertAlmostEqual(float(daily["position_minutes"]), 150.0)
        self.assertEqual(float(daily["maximum_deployed_capital_sek"]), 2000.0)

    def test_open_position_uses_latest_observed_bar(self) -> None:
        date_text = "2026-01-02"
        ledger = self._ledger(
            [
                {
                    "date": date_text,
                    "ticker": "AAA.ST",
                    "selection_status": "SELECTED_OPEN",
                    "entry_time": f"{date_text} 10:00:00",
                    "exit_time": "",
                    "portfolio_pnl_sek": 0.0,
                    "exit_reason": "",
                }
            ]
        )
        observed = _observed_session_ends(
            [date_text], self._candidates(date_text, f"{date_text} 11:00:00")
        )
        detail = build_position_detail(ledger, observed).iloc[0]
        self.assertEqual(detail["exposure_end_source"], "LATEST_OBSERVED_BAR_OPEN_POSITION")
        self.assertAlmostEqual(float(detail["exposure_minutes"]), 60.0)
        self.assertEqual(float(detail["realized_pnl_sek"]), 0.0)

    def test_same_bar_entry_exit_has_zero_exposure(self) -> None:
        date_text = "2026-01-02"
        ledger = self._ledger(
            [
                {
                    "date": date_text,
                    "ticker": "AAA.ST",
                    "entry_time": f"{date_text} 09:45:00",
                    "exit_time": f"{date_text} 09:45:00",
                }
            ]
        )
        observed = _observed_session_ends(
            [date_text], self._candidates(date_text, f"{date_text} 16:30:00")
        )
        detail = build_position_detail(ledger, observed)
        intervals = build_interval_detail([date_text], observed, detail)
        self.assertEqual(int(intervals["open_positions"].max()), 0)
        self.assertAlmostEqual(float(detail.iloc[0]["exposure_minutes"]), 0.0)

    def test_position_size_scenarios_scale_pnl_without_reselection(self) -> None:
        date_text = "2026-01-02"
        ledger = self._ledger(
            [
                {
                    "date": date_text,
                    "ticker": "AAA.ST",
                    "entry_time": f"{date_text} 10:00:00",
                    "exit_time": f"{date_text} 11:00:00",
                    "portfolio_pnl_sek": 10.0,
                }
            ]
        )
        observed = _observed_session_ends(
            [date_text], self._candidates(date_text, f"{date_text} 16:30:00")
        )
        detail = build_position_detail(ledger, observed)
        scenarios = build_sizing_scenarios(detail, 100.0, 30).set_index("scenario_id")
        large = scenarios.loc["FIXED_5000_SEK"]
        self.assertAlmostEqual(float(large["scaled_realized_pnl_sek"]), 50.0)
        self.assertAlmostEqual(float(large["max_two_slot_allocation_rate"]), 1.0)
        self.assertTrue(bool(large["selection_unchanged"]))

    def test_summary_time_rates_sum_to_one(self) -> None:
        date_text = "2026-01-02"
        ledger = self._ledger(
            [
                {
                    "date": date_text,
                    "ticker": "AAA.ST",
                    "entry_time": f"{date_text} 10:00:00",
                    "exit_time": f"{date_text} 11:00:00",
                }
            ]
        )
        observed = _observed_session_ends(
            [date_text], self._candidates(date_text, f"{date_text} 16:30:00")
        )
        detail = build_position_detail(ledger, observed)
        intervals = build_interval_detail([date_text], observed, detail)
        daily = build_daily([date_text], observed, detail, intervals)
        summary = build_summary([date_text], observed, detail, intervals, daily).iloc[0]
        total = sum(
            float(summary[column])
            for column in [
                "time_zero_positions_rate",
                "time_one_position_rate",
                "time_two_positions_rate",
            ]
        )
        self.assertAlmostEqual(total, 1.0)
        self.assertLessEqual(float(summary["maximum_deployed_capital_sek"]), 2000.0)


if __name__ == "__main__":
    unittest.main()
