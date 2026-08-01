from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.metrics import performance_summary

import pandas as pd


def delayed_simulation(df, top_n=10):
    equity = 10000
    equity_history = []
    returns = []

    dates = sorted(df["date"].unique())

    print("\nRunning delayed simulation...")
    print(f"Trading days: {len(dates)}")

    for i in range(len(dates) - 2):
        signal_day = dates[i]
        return_day = dates[i + 2]

        signal_data = df[df["date"] == signal_day].copy()

        return_data = (
            df[df["date"] == return_day][["ticker", "return"]]
            .copy()
            .rename(columns={"return": "future_return"})
        )

        selected = (
            signal_data
            .sort_values("alpha", ascending=False)
            .head(top_n)
            .copy()
        )

        if len(selected) == 0:
            continue

        selected["weight"] = 1 / len(selected)

        merged = selected.merge(
            return_data,
            on="ticker",
            how="left"
        )

        merged["future_return"] = merged["future_return"].fillna(0)

        daily_return = (
            merged["weight"] * merged["future_return"]
        ).sum()

        equity *= (1 + daily_return)

        equity_history.append({
            "date": return_day,
            "equity": equity
        })

        returns.append({
            "date": return_day,
            "daily_return": daily_return
        })

    return pd.DataFrame(equity_history), pd.DataFrame(returns)


df = build_alpha(load_prices())

equity_curve, daily_returns = delayed_simulation(df)

performance_summary(equity_curve, daily_returns)