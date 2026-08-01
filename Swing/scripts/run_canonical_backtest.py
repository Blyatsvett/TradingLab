"""Run the consolidated next-open Swing pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, DEFAULT_OUTPUT_DIR, load_config
from core.data_repository import load_price_history, validate_price_history
from core.features import build_feature_table, build_return_table
from core.portfolio_engine import simulate_next_open_swing
from core.reporting import calculate_performance_metrics, export_power_bi_tables
from core.signals import build_target_portfolios


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    prices = load_price_history(args.db, config.start_date, config.end_date)
    data_quality = validate_price_history(prices)
    features = build_feature_table(prices, config)
    returns = build_return_table(prices)
    trading_calendar = returns["date"].drop_duplicates().sort_values()
    targets = build_target_portfolios(features, trading_calendar, config)
    result = simulate_next_open_swing(returns, targets, config)
    metrics = calculate_performance_metrics(result.daily_portfolio, config.initial_capital)

    export_power_bi_tables(
        output_dir=args.output,
        daily_portfolio=result.daily_portfolio,
        positions=result.positions,
        trades=result.trades,
        rebalance_schedule=result.rebalance_schedule,
        targets=targets,
        metrics=metrics,
        data_quality=data_quality,
    )

    row = metrics.iloc[0]
    print("\nCanonical Swing backtest complete")
    print(f"Strategy          : {config.strategy_name}")
    print(f"Final equity      : {row['final_equity']:,.2f} SEK")
    print(f"CAGR              : {row['cagr']:.2%}")
    print(f"Sharpe ratio      : {row['sharpe_ratio']:.2f}")
    print(f"Maximum drawdown  : {row['max_drawdown']:.2%}")
    print(f"Transaction costs : {row['total_transaction_cost']:,.2f} SEK")
    print(f"Output directory  : {args.output.resolve()}")


if __name__ == "__main__":
    main()
