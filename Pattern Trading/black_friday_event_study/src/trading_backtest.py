from __future__ import annotations

import numpy as np
import pandas as pd

from .database import read_table, write_table
from .settings import OUTPUT_DIR


CANDIDATES = [
    {
        "strategy": "AMZN_vs_SPY_XRT",
        "ticker": "AMZN",
        "model_name": "SPY_XRT",
        "factors": [
            ("SPY", "SPY_return", "beta_spy"),
            ("XRT", "XRT_return", "beta_xrt"),
        ],
    },
    {
        "strategy": "WMT_vs_SPY_XRT",
        "ticker": "WMT",
        "model_name": "SPY_XRT",
        "factors": [
            ("SPY", "SPY_return", "beta_spy"),
            ("XRT", "XRT_return", "beta_xrt"),
        ],
    },
    {
        "strategy": "XRT_vs_SPY",
        "ticker": "XRT",
        "model_name": "SPY",
        "factors": [("SPY", "SPY_return", "beta_spy")],
    },
    {
        "strategy": "ETSY_vs_SPY_XRT",
        "ticker": "ETSY",
        "model_name": "SPY_XRT",
        "factors": [
            ("SPY", "SPY_return", "beta_spy"),
            ("XRT", "XRT_return", "beta_xrt"),
        ],
    },
]

ENTRY_RELATIVE_DAY = -4
EXIT_RELATIVE_DAY = 1
RETURN_START_DAY = -3
RETURN_END_DAY = 1

# Complete round-trip cost per $1 of traded notional, not per side.
ROUND_TRIP_COST_BPS = [0, 10, 25, 50]

SAMPLE_NAMES = [
    "Full_2010_2025",
    "Discovery_2010_2018",
    "Validation_2019_2025",
]


def _sample_mask(dataframe: pd.DataFrame, sample: str) -> pd.Series:
    if sample == "Full_2010_2025":
        return pd.Series(True, index=dataframe.index)
    if sample == "Discovery_2010_2018":
        return dataframe["event_year"] <= 2018
    if sample == "Validation_2019_2025":
        return dataframe["event_year"] >= 2019
    raise ValueError(f"Unknown sample: {sample}")


def _compound_return(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(numeric) == 0:
        return np.nan
    return float(np.prod(1.0 + numeric) - 1.0)


def _first_float(dataframe: pd.DataFrame, column: str, default: float = 0.0) -> float:
    if column not in dataframe.columns:
        return default
    values = pd.to_numeric(dataframe[column], errors="coerce").dropna()
    return default if values.empty else float(values.iloc[0])


def _get_price(price_lookup: pd.Series, ticker: str, date: pd.Timestamp) -> float:
    try:
        value = price_lookup.loc[(ticker, date)]
    except KeyError:
        return np.nan
    if isinstance(value, pd.Series):
        value = value.iloc[0]
    return float(value)


def _max_drawdown(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return np.nan
    wealth = np.cumprod(1.0 + returns)
    wealth_with_start = np.concatenate(([1.0], wealth))
    peaks = np.maximum.accumulate(wealth_with_start)
    return float(np.min(wealth_with_start / peaks - 1.0))


def _summarize_returns(trades: pd.DataFrame, sample: str) -> dict:
    sample_trades = trades.loc[_sample_mask(trades, sample)].sort_values("event_year")
    if sample_trades.empty:
        return {}

    values = sample_trades["net_return"].to_numpy(dtype=float)
    years = sample_trades["event_year"].to_numpy(dtype=int)
    n = len(values)
    best_index = int(np.argmax(values))
    worst_index = int(np.argmin(values))
    growth = float(np.prod(1.0 + values))

    return {
        "sample": sample,
        "n_trades": n,
        "mean_return": float(np.mean(values)),
        "median_return": float(np.median(values)),
        "std_return": float(np.std(values, ddof=1)) if n > 1 else np.nan,
        "positive_rate": float(np.mean(values > 0)),
        "worst_return": float(values[worst_index]),
        "worst_year": int(years[worst_index]),
        "best_return": float(values[best_index]),
        "best_year": int(years[best_index]),
        "mean_excluding_best": (
            float(np.mean(np.delete(values, best_index))) if n > 1 else np.nan
        ),
        "mean_excluding_worst": (
            float(np.mean(np.delete(values, worst_index))) if n > 1 else np.nan
        ),
        "cumulative_return": growth - 1.0,
        "geometric_mean_per_trade": (
            float(growth ** (1.0 / n) - 1.0) if growth > 0 else np.nan
        ),
        "max_drawdown": _max_drawdown(values),
        "average_gross_notional": float(sample_trades["gross_notional"].mean()),
        "average_beta_spy": float(sample_trades["beta_spy"].mean()),
        "average_beta_xrt": float(sample_trades["beta_xrt"].mean()),
    }


def run_trading_backtest() -> dict[str, pd.DataFrame]:
    panel = read_table("event_panel")
    prices = read_table("daily_prices")

    panel["date"] = pd.to_datetime(panel["date"])
    panel["event_year"] = panel["event_year"].astype(int)
    panel["relative_day"] = panel["relative_day"].astype(int)
    prices["date"] = pd.to_datetime(prices["date"])

    price_lookup = (
        prices.drop_duplicates(["ticker", "date"])
        .set_index(["ticker", "date"])["adjusted_close"]
        .sort_index()
    )

    required_days = set(range(ENTRY_RELATIVE_DAY, EXIT_RELATIVE_DAY + 1))
    return_days = set(range(RETURN_START_DAY, RETURN_END_DAY + 1))
    trade_rows: list[dict] = []
    diagnostic_rows: list[dict] = []

    for candidate in CANDIDATES:
        strategy = candidate["strategy"]
        ticker = candidate["ticker"]
        model_name = candidate["model_name"]
        factors = candidate["factors"]

        candidate_panel = panel[
            (panel["ticker"] == ticker) & (panel["model_name"] == model_name)
        ].copy()

        if candidate_panel.empty:
            diagnostic_rows.append(
                {
                    "strategy": strategy,
                    "ticker": ticker,
                    "model_name": model_name,
                    "event_year": np.nan,
                    "status": "candidate_panel_missing",
                    "detail": "",
                }
            )
            continue

        for event_year, year_panel in candidate_panel.groupby("event_year"):
            year_panel = (
                year_panel.drop_duplicates("relative_day")
                .sort_values("relative_day")
                .copy()
            )
            available_days = set(year_panel["relative_day"].astype(int))

            if not required_days.issubset(available_days):
                diagnostic_rows.append(
                    {
                        "strategy": strategy,
                        "ticker": ticker,
                        "model_name": model_name,
                        "event_year": int(event_year),
                        "status": "missing_relative_days",
                        "detail": str(sorted(required_days - available_days)),
                    }
                )
                continue

            trade_window = year_panel[
                year_panel["relative_day"].between(
                    ENTRY_RELATIVE_DAY, EXIT_RELATIVE_DAY
                )
            ].copy()
            return_window = trade_window[
                trade_window["relative_day"].isin(return_days)
            ].sort_values("relative_day")

            entry_date = pd.Timestamp(
                trade_window.loc[
                    trade_window["relative_day"] == ENTRY_RELATIVE_DAY, "date"
                ].iloc[0]
            )
            exit_date = pd.Timestamp(
                trade_window.loc[
                    trade_window["relative_day"] == EXIT_RELATIVE_DAY, "date"
                ].iloc[0]
            )
            entry_price = _get_price(price_lookup, ticker, entry_date)
            exit_price = _get_price(price_lookup, ticker, exit_date)

            if not np.isfinite(entry_price) or not np.isfinite(exit_price):
                diagnostic_rows.append(
                    {
                        "strategy": strategy,
                        "ticker": ticker,
                        "model_name": model_name,
                        "event_year": int(event_year),
                        "status": "entry_or_exit_price_missing",
                        "detail": f"{entry_date.date()} -> {exit_date.date()}",
                    }
                )
                continue

            long_gross_return = float(exit_price / entry_price - 1.0)
            reconstructed = _compound_return(return_window["stock_return"])
            beta_spy = _first_float(year_panel, "beta_spy")
            beta_xrt = _first_float(year_panel, "beta_xrt")
            factor_returns = {"SPY": 0.0, "XRT": 0.0}
            hedge_pnl = 0.0
            hedge_notional = 0.0

            for factor_ticker, return_column, beta_column in factors:
                factor_return = _compound_return(return_window[return_column])
                beta = _first_float(year_panel, beta_column)
                factor_returns[factor_ticker] = factor_return
                hedge_pnl += beta * factor_return
                hedge_notional += abs(beta)

            hedged_gross_return = long_gross_return - hedge_pnl
            gross_notional = 1.0 + hedge_notional
            abnormal_car = float(return_window["abnormal_return"].sum())

            common = {
                "strategy": strategy,
                "ticker": ticker,
                "model_name": model_name,
                "event_year": int(event_year),
                "entry_relative_day": ENTRY_RELATIVE_DAY,
                "exit_relative_day": EXIT_RELATIVE_DAY,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "holding_return_days": len(return_window),
                "entry_adjusted_close": entry_price,
                "exit_adjusted_close": exit_price,
                "long_gross_return": long_gross_return,
                "reconstructed_long_return": reconstructed,
                "return_reconstruction_error": long_gross_return - reconstructed,
                "spy_window_return": factor_returns["SPY"],
                "xrt_window_return": factor_returns["XRT"],
                "beta_spy": beta_spy,
                "beta_xrt": beta_xrt,
                "spy_hedge_weight": -beta_spy,
                "xrt_hedge_weight": -beta_xrt,
                "gross_notional": gross_notional,
                "net_notional": 1.0 - beta_spy - beta_xrt,
                "hedged_gross_return": hedged_gross_return,
                "model_abnormal_car": abnormal_car,
            }

            for cost_bps in ROUND_TRIP_COST_BPS:
                cost_rate = cost_bps / 10_000.0
                trade_rows.append(
                    {
                        **common,
                        "trade_type": "LongOnly",
                        "cost_bps": cost_bps,
                        "transaction_cost": cost_rate,
                        "gross_return": long_gross_return,
                        "net_return": long_gross_return - cost_rate,
                    }
                )
                hedged_cost = cost_rate * gross_notional
                trade_rows.append(
                    {
                        **common,
                        "trade_type": "BetaHedged",
                        "cost_bps": cost_bps,
                        "transaction_cost": hedged_cost,
                        "gross_return": hedged_gross_return,
                        "net_return": hedged_gross_return - hedged_cost,
                    }
                )

            diagnostic_rows.append(
                {
                    "strategy": strategy,
                    "ticker": ticker,
                    "model_name": model_name,
                    "event_year": int(event_year),
                    "status": "ok",
                    "detail": "",
                }
            )

    trades = pd.DataFrame(trade_rows)
    diagnostics = pd.DataFrame(diagnostic_rows)
    if trades.empty:
        raise RuntimeError("No backtest trades were created.")

    summary_rows: list[dict] = []
    group_columns = [
        "strategy",
        "ticker",
        "model_name",
        "trade_type",
        "cost_bps",
    ]

    for keys, group in trades.groupby(group_columns, sort=False):
        metadata = dict(zip(group_columns, keys))
        for sample in SAMPLE_NAMES:
            metrics = _summarize_returns(group, sample)
            if metrics:
                summary_rows.append({**metadata, **metrics})

    summary = pd.DataFrame(summary_rows)
    equity_rows: list[dict] = []

    for keys, group in trades.groupby(group_columns, sort=False):
        metadata = dict(zip(group_columns, keys))
        ordered = group.sort_values("event_year")
        values = ordered["net_return"].to_numpy(dtype=float)
        wealth = np.cumprod(1.0 + values)
        peaks = np.maximum.accumulate(np.concatenate(([1.0], wealth)))[1:]
        drawdowns = wealth / peaks - 1.0

        for position, row in enumerate(ordered.itertuples(index=False)):
            equity_rows.append(
                {
                    **metadata,
                    "event_year": int(row.event_year),
                    "entry_date": row.entry_date,
                    "exit_date": row.exit_date,
                    "net_return": float(row.net_return),
                    "cumulative_wealth": float(wealth[position]),
                    "drawdown": float(drawdowns[position]),
                }
            )

    equity_curve = pd.DataFrame(equity_rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "backtest_trade_results": trades,
        "backtest_summary": summary,
        "backtest_equity_curve": equity_curve,
        "backtest_diagnostics": diagnostics,
    }

    for name, dataframe in outputs.items():
        dataframe.to_csv(OUTPUT_DIR / f"{name}.csv", index=False)
        write_table(dataframe, name)

    ok_count = int((diagnostics["status"] == "ok").sum())
    print("Trading backtest completed.")
    print(
        f"Created {ok_count} annual candidate trades, "
        f"{len(trades)} cost-adjusted trade rows, and "
        f"{len(summary)} summary rows."
    )
    return outputs


if __name__ == "__main__":
    run_trading_backtest()
