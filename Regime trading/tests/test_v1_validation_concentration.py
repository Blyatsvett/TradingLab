from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.v1_validation_concentration import (
    build_concentration_scenarios,
    build_contribution_detail,
    build_leave_one_out,
)
from RegimeTrading.scripts.v1_validation_portfolio import simulate_portfolio


class ConcentrationValidationTests(unittest.TestCase):
    @staticmethod
    def _row(
        ticker: str,
        entry: str,
        exit_time: str,
        reason: str,
        pnl_pct: float,
        regime: str = "EARLY_BROAD_STRENGTH",
    ) -> dict:
        return {
            "strategy_id": "REGIME_AWARE_GAP_RECOVERY_V1",
            "research_status": "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION",
            "date": entry[:10],
            "ticker": ticker,
            "entry_time": entry,
            "exit_time": exit_time,
            "exit_reason": reason,
            "entry_price": 100.0,
            "stop_price": 99.0,
            "target_price": 101.0,
            "exit_price": 101.0 if pnl_pct > 0 else 99.0,
            "pnl_pct": pnl_pct,
            "position_size_sek": 1000.0,
            "r_multiple_achieved": pnl_pct / 0.01,
            "gap": -0.005,
            "gap_pct": -0.5,
            "opening_range_pct": 0.01,
            "risk_pct": 0.01,
            "reward_risk": 1.0,
            "early_market_regime": regime,
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

    def test_contribution_detail_ranks_largest_trade_first(self) -> None:
        trades = self._prepare(
            [
                self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 10:00:00", "TARGET_HIT", 0.01),
                self._row("BBB.ST", "2026-01-03 09:45:00", "2026-01-03 10:00:00", "TARGET_HIT", 0.02),
            ]
        )
        baseline = simulate_portfolio(trades)
        detail = build_contribution_detail(baseline)
        top_trade = detail[detail["contribution_level"] == "TRADE"].iloc[0]
        self.assertIn("BBB.ST", top_trade["display_label"])
        self.assertAlmostEqual(float(top_trade["pnl_sek"]), 20.0)

    def test_excluding_top_trade_resimulates_and_admits_blocked_trade(self) -> None:
        trades = self._prepare(
            [
                self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 12:00:00", "TARGET_HIT", 0.03),
                self._row("BBB.ST", "2026-01-02 09:45:00", "2026-01-02 12:00:00", "STOP_HIT", -0.01),
                self._row("CCC.ST", "2026-01-02 09:45:00", "2026-01-02 12:00:00", "TARGET_HIT", 0.02),
            ]
        )
        baseline = simulate_portfolio(trades)
        scenarios = build_concentration_scenarios(trades, baseline).set_index("scenario_id")
        top_one = scenarios.loc["EXCLUDE_TOP_1_TRADES"]
        self.assertIn("2", str(top_one["added_selected_trade_rows"]))
        self.assertAlmostEqual(float(top_one["replacement_effect_sek"]), 20.0)

    def test_leave_one_ticker_out_reports_reselection(self) -> None:
        trades = self._prepare(
            [
                self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 12:00:00", "TARGET_HIT", 0.03),
                self._row("BBB.ST", "2026-01-02 09:45:00", "2026-01-02 12:00:00", "STOP_HIT", -0.01),
                self._row("CCC.ST", "2026-01-02 09:45:00", "2026-01-02 12:00:00", "TARGET_HIT", 0.02),
            ]
        )
        baseline = simulate_portfolio(trades)
        loo = build_leave_one_out(trades, baseline)
        aaa = loo[(loo["dimension"] == "TICKER") & (loo["excluded_value"] == "AAA.ST")].iloc[0]
        self.assertEqual(int(aaa["added_selected_trade_count"]), 1)
        self.assertIn("2", str(aaa["added_selected_trade_rows"]))


if __name__ == "__main__":
    unittest.main()
