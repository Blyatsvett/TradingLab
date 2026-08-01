from core.data_loader import load_prices
from core.metrics import performance_summary

import pandas as pd
import numpy as np


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


def compute_alpha_weights(selected):
    selected = selected.copy()

    # shift to positive values
    min_alpha = selected["alpha"].min()

    if min_alpha <= 0:
        selected["alpha_shifted"] = selected["alpha"] - min_alpha + 1e-9
    else:
        selected["alpha_shifted"] = selected["alpha"]

    selected["weight"] = (
        selected["alpha_shifted"] /
        selected["alpha_shifted"].sum()
    )

    return selected


def simulate_alpha_weighted(
    df,
    top_n=3,
    rebalance_every=3,
    cost_per_rebalance=0.0005,
    initial_capital=10000,
):
    equity = initial_capital
    equity_history = []
    return_history = []

    dates = sorted(df["date"].unique())
    current_portfolio = None

    for i in range(len(dates)):
        signal_day = dates[i]

        should_rebalance = (
            current_portfolio is None or i % rebalance_every == 0
        )

        if should_rebalance:
            signal_data = df[df["date"] == signal_day].copy()

            selected = (
                signal_data
                .sort_values("alpha", ascending=False)
                .head(top_n)
                .copy()
            )

            if len(selected) == 0:
                continue

            selected = compute_alpha_weights(selected)

            current_portfolio = selected[["ticker", "weight"]].copy()
            cost = cost_per_rebalance
        else:
            cost = 0

        return_data = df[df["date"] == signal_day][
            ["ticker", "overnight_return"]
        ].copy()

        merged = current_portfolio.merge(return_data, on="ticker", how="left")
        merged["overnight_return"] = merged["overnight_return"].fillna(0)

        daily_return = (
            merged["weight"] * merged["overnight_return"]
        ).sum()

        net_return = daily_return - cost

        equity *= (1 + net_return)

        equity_history.append({
            "date": signal_day,
            "equity": equity,
        })

        return_history.append({
            "date": signal_day,
            "daily_return": net_return,
        })

    return pd.DataFrame(equity_history), pd.DataFrame(return_history)


df = load_prices()

df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

df = df[df["regime"] != "bear"].copy()

print("\n" + "=" * 60)
print("ALPHA WEIGHTED TEST")
print("=" * 60)

equity_curve, daily_returns = simulate_alpha_weighted(
    df,
    top_n=3,
    rebalance_every=3,
    cost_per_rebalance=0.0005,
)

performance_summary(equity_curve, daily_returns)