from __future__ import annotations

import unittest

import pandas as pd

from core.config import StrategyConfig
from core.features import build_feature_table, build_return_table
from core.portfolio_engine import simulate_next_open_swing
from core.signals import build_target_portfolios


class CanonicalPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=30)
        rows = []
        for ticker, drift in [("AAA.ST", 0.01), ("BBB.ST", 0.005), ("CCC.ST", -0.002)]:
            price = 100.0
            for i, date in enumerate(dates):
                open_price = price
                close_price = open_price * (1 + drift + (i % 3 - 1) * 0.001)
                rows.append(
                    {
                        "date": date,
                        "ticker": ticker,
                        "open": open_price,
                        "high": max(open_price, close_price) * 1.001,
                        "low": min(open_price, close_price) * 0.999,
                        "close": close_price,
                        "volume": 100_000 + i,
                    }
                )
                price = close_price * 1.001
        self.prices = pd.DataFrame(rows)
        self.config = StrategyConfig(
            momentum_window=3,
            regime_window=5,
            top_n=2,
            rebalance_every_sessions=3,
            trading_cost_bps_per_side=5.0,
        )

    def test_feature_table_contains_no_future_return_targets(self) -> None:
        features = build_feature_table(self.prices, self.config)
        forbidden = {"next_open", "overnight_return", "open_to_next_open_return"}
        self.assertTrue(forbidden.isdisjoint(features.columns))

    def test_execution_occurs_after_signal(self) -> None:
        features = build_feature_table(self.prices, self.config)
        returns = build_return_table(self.prices)
        targets = build_target_portfolios(
            features,
            returns["date"].drop_duplicates().sort_values(),
            self.config,
        )
        self.assertTrue((targets["execution_date"] > targets["signal_date"]).all())

    def test_target_weights_sum_to_one(self) -> None:
        features = build_feature_table(self.prices, self.config)
        returns = build_return_table(self.prices)
        targets = build_target_portfolios(
            features,
            returns["date"].drop_duplicates().sort_values(),
            self.config,
        )
        sums = targets.groupby("execution_date")["target_weight"].sum()
        self.assertTrue(((sums - 1.0).abs() < 1e-12).all())

    def test_integration_produces_complete_outputs(self) -> None:
        features = build_feature_table(self.prices, self.config)
        returns = build_return_table(self.prices)
        targets = build_target_portfolios(
            features,
            returns["date"].drop_duplicates().sort_values(),
            self.config,
        )
        result = simulate_next_open_swing(returns, targets, self.config)
        self.assertFalse(result.daily_portfolio.empty)
        self.assertFalse(result.positions.empty)
        self.assertFalse(result.trades.empty)
        self.assertTrue((result.daily_portfolio["date"] > result.daily_portfolio["period_start"]).all())
        self.assertTrue((result.daily_portfolio["equity"] > 0).all())


if __name__ == "__main__":
    unittest.main()
