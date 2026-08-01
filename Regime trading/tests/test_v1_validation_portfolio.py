from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.v1_validation_portfolio import simulate_portfolio


class PortfolioValidationTests(unittest.TestCase):
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

    @staticmethod
    def _row(ticker: str, entry: str, exit_time: str, reason: str, pnl_pct: float) -> dict:
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
            "early_market_regime": "EARLY_BROAD_STRENGTH",
            "research_universe": "TEST",
        }

    def test_empty_input_keeps_initial_equity(self) -> None:
        result = simulate_portfolio(pd.DataFrame())
        summary = result.summary.iloc[0]
        self.assertEqual(int(summary["selected_trade_rows"]), 0)
        self.assertEqual(float(summary["final_realized_equity_sek"]), 10000.0)

    def test_capacity_limit_and_ticker_tie_break(self) -> None:
        rows = [
            self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 10:00:00", "TARGET_HIT", 0.01),
            self._row("BBB.ST", "2026-01-02 09:45:00", "2026-01-02 11:00:00", "STOP_HIT", -0.005),
            self._row("CCC.ST", "2026-01-02 09:45:00", "2026-01-02 12:00:00", "TARGET_HIT", 0.02),
        ]
        result = simulate_portfolio(self._prepare(rows))
        status = result.ledger.set_index("ticker")["selection_status"].to_dict()
        self.assertEqual(status["AAA.ST"], "SELECTED_CLOSED")
        self.assertEqual(status["BBB.ST"], "SELECTED_CLOSED")
        self.assertEqual(status["CCC.ST"], "REJECTED_CAPACITY")
        self.assertEqual(int(result.summary.iloc[0]["same_timestamp_ambiguous_groups"]), 1)

    def test_entries_do_not_reuse_same_timestamp_exit_slot(self) -> None:
        rows = [
            self._row("AAA.ST", "2026-01-02 09:45:00", "2026-01-02 10:00:00", "TARGET_HIT", 0.01),
            self._row("BBB.ST", "2026-01-02 09:45:00", "2026-01-02 11:00:00", "STOP_HIT", -0.005),
            self._row("CCC.ST", "2026-01-02 10:00:00", "2026-01-02 10:30:00", "TARGET_HIT", 0.02),
            self._row("DDD.ST", "2026-01-02 10:05:00", "2026-01-02 10:35:00", "TARGET_HIT", 0.003),
        ]
        result = simulate_portfolio(self._prepare(rows))
        status = result.ledger.set_index("ticker")["selection_status"].to_dict()
        self.assertEqual(status["CCC.ST"], "REJECTED_CAPACITY")
        self.assertEqual(status["DDD.ST"], "SELECTED_CLOSED")

    def test_open_trade_remains_selected_without_realized_pnl(self) -> None:
        rows = [
            self._row("AAA.ST", "2026-01-02 09:45:00", "", "", 0.0),
        ]
        result = simulate_portfolio(self._prepare(rows))
        summary = result.summary.iloc[0]
        self.assertEqual(int(summary["selected_open_trades"]), 1)
        self.assertEqual(float(summary["total_realized_pnl_sek"]), 0.0)
        self.assertEqual(result.ledger.iloc[0]["selection_status"], "SELECTED_OPEN")


if __name__ == "__main__":
    unittest.main()
