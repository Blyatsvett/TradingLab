"""Performance calculations and Power BI-ready output helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252


def calculate_performance_metrics(
    daily_portfolio: pd.DataFrame,
    initial_capital: float,
) -> pd.DataFrame:
    if daily_portfolio.empty:
        raise ValueError("daily_portfolio is empty")

    frame = daily_portfolio.sort_values("date").copy()
    returns = frame["net_return"].astype(float)
    final_equity = float(frame["equity"].iloc[-1])
    total_return = final_equity / initial_capital - 1.0
    elapsed_days = max((frame["date"].iloc[-1] - frame["period_start"].iloc[0]).days, 1)
    elapsed_years = elapsed_days / 365.2425
    cagr = (final_equity / initial_capital) ** (1.0 / elapsed_years) - 1.0
    annual_volatility = returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = (
        returns.mean() / returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
        if returns.std(ddof=1) > 0
        else np.nan
    )
    running_peak = frame["equity"].cummax()
    drawdown = frame["equity"] / running_peak - 1.0

    metrics = {
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe,
        "max_drawdown": float(drawdown.min()),
        "positive_day_rate": float((returns > 0).mean()),
        "trading_periods": len(frame),
        "rebalance_count": int(frame["is_rebalance"].sum()),
        "total_transaction_cost": float(frame["transaction_cost"].sum()),
        "average_gross_trade_fraction": float(
            frame.loc[frame["is_rebalance"], "gross_trade_fraction"].mean()
        ),
    }
    return pd.DataFrame([metrics])


def export_power_bi_tables(
    output_dir: str | Path,
    daily_portfolio: pd.DataFrame,
    positions: pd.DataFrame,
    trades: pd.DataFrame,
    rebalance_schedule: pd.DataFrame,
    targets: pd.DataFrame,
    metrics: pd.DataFrame,
    data_quality: pd.DataFrame,
) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    tables = {
        "fact_daily_portfolio.csv": daily_portfolio,
        "fact_positions.csv": positions,
        "fact_trades.csv": trades,
        "fact_rebalances.csv": rebalance_schedule,
        "fact_selected_signals.csv": targets,
        "strategy_metrics.csv": metrics,
        "data_quality.csv": data_quality,
    }
    for filename, frame in tables.items():
        frame.to_csv(path / filename, index=False)
