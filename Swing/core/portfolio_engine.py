"""Stateful next-open portfolio simulation with turnover-based costs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from core.config import StrategyConfig


@dataclass
class SimulationResult:
    daily_portfolio: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    rebalance_schedule: pd.DataFrame


def _weights(position_values: Mapping[str, float], cash: float) -> dict[str, float]:
    total = cash + sum(position_values.values())
    if total <= 0:
        return {}
    return {ticker: value / total for ticker, value in position_values.items() if value != 0}


def simulate_next_open_swing(
    returns: pd.DataFrame,
    targets: pd.DataFrame,
    config: StrategyConfig,
) -> SimulationResult:
    """Run the canonical continuously-held next-open strategy.

    Signal at close T -> rebalance at open T+1 -> hold until a future rebalance
    open. The portfolio is marked from each session open to the following session
    open, preserving intraday and overnight exposure.
    """

    required_returns = {
        "date",
        "next_date",
        "ticker",
        "open_to_next_open_return",
        "open_to_close_return",
        "close_to_next_open_return",
    }
    required_targets = {"execution_date", "signal_date", "ticker", "target_weight", "alpha"}
    if missing := required_returns.difference(returns.columns):
        raise ValueError(f"returns missing columns: {sorted(missing)}")
    if missing := required_targets.difference(targets.columns):
        raise ValueError(f"targets missing columns: {sorted(missing)}")

    return_frame = returns.dropna(subset=["next_date", "open_to_next_open_return"]).copy()
    return_frame["date"] = pd.to_datetime(return_frame["date"])
    return_frame["next_date"] = pd.to_datetime(return_frame["next_date"])
    target_frame = targets.copy()
    target_frame["execution_date"] = pd.to_datetime(target_frame["execution_date"])
    target_frame["signal_date"] = pd.to_datetime(target_frame["signal_date"])

    calendar = pd.DatetimeIndex(sorted(return_frame["date"].unique()))
    available_execution_dates = sorted(set(target_frame["execution_date"]).intersection(calendar))
    if not available_execution_dates:
        raise ValueError("No target portfolio dates overlap the return calendar")

    first_execution_date = pd.Timestamp(available_execution_dates[0])
    first_index = int(calendar.get_loc(first_execution_date))
    scheduled_dates = set(calendar[first_index:: config.rebalance_every_sessions])

    target_lookup = {
        pd.Timestamp(date): group.set_index("ticker")["target_weight"].to_dict()
        for date, group in target_frame.groupby("execution_date")
    }
    signal_lookup = {
        pd.Timestamp(date): group.copy()
        for date, group in target_frame.groupby("execution_date")
    }
    indexed_returns = return_frame.set_index(["date", "ticker"])
    return_lookup = indexed_returns["open_to_next_open_return"]
    intraday_lookup = indexed_returns["open_to_close_return"]
    overnight_lookup = indexed_returns["close_to_next_open_return"]
    next_date_lookup = return_frame.groupby("date")["next_date"].first().to_dict()

    cash = float(config.initial_capital)
    position_values: dict[str, float] = {}
    daily_rows: list[dict] = []
    position_rows: list[dict] = []
    trade_rows: list[dict] = []
    rebalance_rows: list[dict] = []
    cost_rate = config.trading_cost_bps_per_side / 10_000.0

    for session_date in calendar[first_index:]:
        session_date = pd.Timestamp(session_date)
        if session_date not in next_date_lookup:
            continue
        next_date = pd.Timestamp(next_date_lookup[session_date])
        equity_before_trade = cash + sum(position_values.values())
        if equity_before_trade <= 0:
            raise RuntimeError("Portfolio equity became non-positive")

        previous_weights = _weights(position_values, cash)
        is_rebalance = session_date in scheduled_dates
        transaction_cost = 0.0
        gross_trade_fraction = 0.0
        signal_date = pd.NaT

        if is_rebalance:
            target_weights = target_lookup.get(session_date, {})
            signal_group = signal_lookup.get(session_date)
            if signal_group is not None and not signal_group.empty:
                signal_date = signal_group["signal_date"].iloc[0]

            all_tickers = sorted(set(previous_weights) | set(target_weights))
            deltas = {
                ticker: target_weights.get(ticker, 0.0) - previous_weights.get(ticker, 0.0)
                for ticker in all_tickers
            }
            gross_trade_fraction = float(sum(abs(delta) for delta in deltas.values()))
            transaction_cost = equity_before_trade * gross_trade_fraction * cost_rate
            equity_after_cost = equity_before_trade - transaction_cost
            if equity_after_cost < 0:
                raise RuntimeError("Transaction costs exceeded portfolio equity")

            allocated_cost = {
                ticker: (
                    transaction_cost * abs(delta) / gross_trade_fraction
                    if gross_trade_fraction > 0
                    else 0.0
                )
                for ticker, delta in deltas.items()
            }
            for ticker, delta in deltas.items():
                if abs(delta) < 1e-15:
                    continue
                trade_rows.append(
                    {
                        "date": session_date,
                        "signal_date": signal_date,
                        "ticker": ticker,
                        "side": "BUY" if delta > 0 else "SELL",
                        "previous_weight": previous_weights.get(ticker, 0.0),
                        "target_weight": target_weights.get(ticker, 0.0),
                        "weight_change": delta,
                        "gross_trade_notional": abs(delta) * equity_before_trade,
                        "allocated_cost": allocated_cost[ticker],
                    }
                )

            position_values = {
                ticker: weight * equity_after_cost
                for ticker, weight in target_weights.items()
                if weight > 0
            }
            invested_value = sum(position_values.values())
            cash = equity_after_cost - invested_value
            rebalance_rows.append(
                {
                    "date": session_date,
                    "signal_date": signal_date,
                    "selected_positions": len(target_weights),
                    "gross_trade_fraction": gross_trade_fraction,
                    "transaction_cost": transaction_cost,
                    "equity_before_trade": equity_before_trade,
                    "equity_after_cost": equity_after_cost,
                }
            )
        else:
            equity_after_cost = equity_before_trade

        period_start_equity = cash + sum(position_values.values())
        period_pnl = 0.0
        period_intraday_pnl = 0.0
        period_overnight_pnl = 0.0
        end_position_values: dict[str, float] = {}

        for ticker, start_value in position_values.items():
            try:
                realized_return = float(return_lookup.loc[(session_date, ticker)])
            except KeyError as exc:
                raise ValueError(
                    f"Missing realized return for held ticker {ticker} on {session_date.date()}"
                ) from exc
            if not np.isfinite(realized_return):
                raise ValueError(
                    f"Non-finite realized return for held ticker {ticker} on {session_date.date()}"
                )

            intraday_return = float(intraday_lookup.loc[(session_date, ticker)])
            overnight_return = float(overnight_lookup.loc[(session_date, ticker)])
            intraday_pnl = start_value * intraday_return
            close_value = start_value + intraday_pnl
            overnight_pnl = close_value * overnight_return
            pnl = intraday_pnl + overnight_pnl
            end_value = start_value + pnl
            end_position_values[ticker] = end_value
            period_pnl += pnl
            period_intraday_pnl += intraday_pnl
            period_overnight_pnl += overnight_pnl
            position_rows.append(
                {
                    "period_start": session_date,
                    "date": next_date,
                    "ticker": ticker,
                    "start_value": start_value,
                    "start_weight": start_value / period_start_equity if period_start_equity else 0.0,
                    "intraday_return": intraday_return,
                    "overnight_return": overnight_return,
                    "realized_return": realized_return,
                    "intraday_pnl": intraday_pnl,
                    "overnight_pnl": overnight_pnl,
                    "pnl": pnl,
                    "contribution": pnl / equity_before_trade if equity_before_trade else 0.0,
                    "end_value": end_value,
                    "is_rebalance": is_rebalance,
                }
            )

        position_values = end_position_values
        end_equity = cash + sum(position_values.values())
        gross_return = period_pnl / period_start_equity if period_start_equity else 0.0
        gross_intraday_return = (
            period_intraday_pnl / period_start_equity if period_start_equity else 0.0
        )
        gross_overnight_return = (
            period_overnight_pnl / period_start_equity if period_start_equity else 0.0
        )
        net_return = end_equity / equity_before_trade - 1.0

        daily_rows.append(
            {
                "period_start": session_date,
                "date": next_date,
                "signal_date": signal_date,
                "is_rebalance": is_rebalance,
                "gross_return": gross_return,
                "gross_intraday_return": gross_intraday_return,
                "gross_overnight_return": gross_overnight_return,
                "net_return": net_return,
                "equity": end_equity,
                "cash_value": cash,
                "cash_weight": cash / end_equity if end_equity else 0.0,
                "number_of_positions": len(position_values),
                "gross_trade_fraction": gross_trade_fraction,
                "transaction_cost": transaction_cost,
            }
        )

    return SimulationResult(
        daily_portfolio=pd.DataFrame(daily_rows),
        positions=pd.DataFrame(position_rows),
        trades=pd.DataFrame(trade_rows),
        rebalance_schedule=pd.DataFrame(rebalance_rows),
    )
