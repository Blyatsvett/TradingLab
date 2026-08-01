from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.v1_validation_execution_stress import (
    StressScenario,
    build_validation_step3,
    stress_trade_returns,
)


class ExecutionStressValidationTests(unittest.TestCase):
    @staticmethod
    def _row(
        ticker: str,
        entry: str,
        exit_time: str,
        reason: str,
        entry_price: float,
        exit_price: float,
    ) -> dict:
        gross = exit_price / entry_price - 1.0 if reason else 0.0
        net = gross - 0.0005 if reason else 0.0
        return {
            "strategy_id": "REGIME_AWARE_GAP_RECOVERY_V1",
            "research_status": "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION",
            "date": entry[:10],
            "ticker": ticker,
            "entry_time": entry,
            "exit_time": exit_time,
            "exit_reason": reason,
            "entry_price": entry_price,
            "stop_price": 99.0,
            "target_price": 101.0,
            "exit_price": exit_price,
            "pnl_pct": net,
            "position_size_sek": 1000.0,
            "r_multiple_achieved": 1.0,
            "gap": -0.005,
            "gap_pct": -0.5,
            "opening_range_pct": 0.01,
            "risk_pct": 0.01,
            "reward_risk": 1.0,
            "early_market_regime": "EARLY_BROAD_STRENGTH",
            "research_universe": "TEST",
        }

    @staticmethod
    def _prepare(rows: list[dict]) -> pd.DataFrame:
        frame = pd.DataFrame(rows)
        frame["source_trade_row"] = frame.index
        frame["entry_time_dt"] = pd.to_datetime(frame["entry_time"], errors="coerce")
        frame["exit_time_dt"] = pd.to_datetime(frame["exit_time"], errors="coerce")
        frame["is_closed"] = frame["exit_reason"].fillna("").astype(str).str.strip().ne("")
        frame["valid_for_simulation"] = frame["entry_time_dt"].notna() & (
            (~frame["is_closed"]) | frame["exit_time_dt"].notna()
        )
        return frame

    def test_baseline_reconstructs_source_net_return(self) -> None:
        trades = self._prepare(
            [self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 10:00:00", "TARGET_HIT", 100.0, 101.0)]
        )
        scenario = StressScenario(1, "BASELINE", "Baseline", "BASELINE", 5.0)
        stressed, detail = stress_trade_returns(trades, scenario)
        self.assertAlmostEqual(float(stressed.iloc[0]["pnl_pct"]), 0.0095, places=12)
        self.assertAlmostEqual(
            float(detail.iloc[0]["stressed_net_pnl_pct"]),
            float(detail.iloc[0]["source_net_pnl_pct"]),
            places=12,
        )

    def test_target_limit_ignores_market_exit_slippage(self) -> None:
        trades = self._prepare(
            [self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 10:00:00", "TARGET_HIT", 100.0, 101.0)]
        )
        scenario = StressScenario(1, "TARGET", "Target", "TEST", 5.0, 0.0, 10.0)
        _, detail = stress_trade_returns(trades, scenario)
        row = detail.iloc[0]
        self.assertEqual(float(row["applied_exit_slippage_bps"]), 0.0)
        self.assertAlmostEqual(float(row["stressed_exit_price"]), 101.0)

    def test_stop_exit_receives_adverse_market_slippage(self) -> None:
        trades = self._prepare(
            [self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 10:00:00", "STOP_HIT", 100.0, 99.0)]
        )
        scenario = StressScenario(1, "STOP", "Stop", "TEST", 5.0, 0.0, 10.0)
        stressed, detail = stress_trade_returns(trades, scenario)
        row = detail.iloc[0]
        self.assertEqual(float(row["applied_exit_slippage_bps"]), 10.0)
        self.assertAlmostEqual(float(row["stressed_exit_price"]), 98.901)
        self.assertLess(float(stressed.iloc[0]["pnl_pct"]), float(trades.iloc[0]["pnl_pct"]))

    def test_combined_stress_reduces_portfolio_pnl(self) -> None:
        trades = self._prepare(
            [
                self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 10:00:00", "TARGET_HIT", 100.0, 101.0),
                self._row("BBB.ST", "2026-01-03 09:45:00", "2026-01-03 10:00:00", "STOP_HIT", 100.0, 99.0),
            ]
        )
        result = build_validation_step3(trades)
        scenarios = result.scenarios.set_index("scenario_id")
        self.assertLess(
            float(scenarios.loc["CONSERVATIVE", "realized_pnl_sek"]),
            float(scenarios.loc["BASELINE", "realized_pnl_sek"]),
        )
        self.assertEqual(len(result.cost_curve), 81)


if __name__ == "__main__":
    unittest.main()
