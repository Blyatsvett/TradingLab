from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from RegimeTrading.scripts.v1_validation_parameter_robustness import (
    ParameterScenario,
    _build_parameter_trades,
    build_session_reconciliation,
    generate_scenarios,
)


class ParameterRobustnessValidationTests(unittest.TestCase):
    @staticmethod
    def _bars(ticker: str, day: str, high_0930: float = 100.0, low_0930: float = 99.0) -> pd.DataFrame:
        times = [
            "09:00", "09:30", "09:35", "09:40", "09:45", "09:50", "10:00", "16:30"
        ]
        rows = []
        for clock in times:
            close = 99.5
            high = 99.7
            low = 99.3
            if clock == "09:30":
                high, low, close = high_0930, low_0930, 99.5
            elif clock == "09:45":
                high, low, close = 100.2, 99.8, 100.1
            elif clock == "09:50":
                high, low, close = 101.2, 100.0, 101.0
            elif clock == "16:30":
                high, low, close = 101.0, 100.5, 100.8
            rows.append(
                {
                    "datetime": pd.Timestamp(f"{day} {clock}:00"),
                    "open": close,
                    "high": high,
                    "low": low,
                    "close": close,
                    "ticker": ticker,
                    "date": pd.Timestamp(day).date(),
                }
            )
        return pd.DataFrame(rows)

    def test_scenario_design_has_expected_count(self) -> None:
        scenarios = generate_scenarios()
        self.assertEqual(len(scenarios), 234)
        self.assertEqual(sum(s.scenario_family == "CORE_NEIGHBORHOOD" for s in scenarios), 216)
        self.assertEqual(sum(s.scenario_family == "ONE_AT_A_TIME" for s in scenarios), 17)

    def test_complete_session_requires_all_research_tickers(self) -> None:
        frames = []
        tickers = [
            "ALFA.ST", "ATCO-A.ST", "ATCO-B.ST", "AZN.ST", "BOL.ST",
            "ERIC-B.ST", "EVO.ST", "SAND.ST", "SEB-A.ST", "SHB-A.ST", "SWED-A.ST",
        ]
        for ticker in tickers:
            frames.append(self._bars(ticker, "2026-01-02"))
        incomplete = self._bars(tickers[0], "2026-01-03").iloc[:-1]
        frames.append(incomplete)
        result = build_session_reconciliation(pd.concat(frames, ignore_index=True))
        complete = result[result["date"] == "2026-01-02"].iloc[0]
        incomplete_row = result[result["date"] == "2026-01-03"].iloc[0]
        self.assertTrue(bool(complete["included_in_parameter_analysis"]))
        self.assertFalse(bool(incomplete_row["included_in_parameter_analysis"]))

    def test_baseline_builds_closed_trade(self) -> None:
        ticker = "ALFA.ST"
        session_date = date(2026, 1, 2)
        bars = self._bars(ticker, "2026-01-02")
        sessions = {(ticker, session_date): bars}
        daily_reference = pd.DataFrame(
            [{
                "ticker": ticker,
                "date": session_date,
                "open_price": 99.5,
                "daily_close": 100.8,
                "previous_close": 101.0,
            }]
        )
        regime = pd.DataFrame(
            [{
                "date": session_date,
                "early_market_regime": "EARLY_BROAD_STRENGTH",
                "favorable_regime": True,
            }]
        )
        scenario = ParameterScenario("TEST", "TEST", "NONE")
        trades, candidates, valid = _build_parameter_trades(
            scenario, sessions, daily_reference, regime
        )
        self.assertEqual(candidates, 1)
        self.assertEqual(valid, 1)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0]["exit_reason"], "TARGET_HIT")

    def test_max_risk_filter_removes_wide_opening_range(self) -> None:
        ticker = "ALFA.ST"
        session_date = date(2026, 1, 2)
        bars = self._bars(ticker, "2026-01-02", high_0930=100.0, low_0930=97.0)
        sessions = {(ticker, session_date): bars}
        daily_reference = pd.DataFrame(
            [{
                "ticker": ticker,
                "date": session_date,
                "open_price": 99.5,
                "daily_close": 100.8,
                "previous_close": 101.0,
            }]
        )
        regime = pd.DataFrame(
            [{
                "date": session_date,
                "early_market_regime": "EARLY_BROAD_STRENGTH",
                "favorable_regime": True,
            }]
        )
        scenario = ParameterScenario(
            "RISK_FILTER", "TEST", "MAX_RISK_PCT", max_risk_pct=0.02
        )
        trades, candidates, valid = _build_parameter_trades(
            scenario, sessions, daily_reference, regime
        )
        self.assertEqual(candidates, 1)
        self.assertEqual(valid, 0)
        self.assertTrue(trades.empty)


if __name__ == "__main__":
    unittest.main()
