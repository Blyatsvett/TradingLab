from core.data_loader import load_prices
from core.metrics import performance_summary

import pandas as pd


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


def simulate_rebalance_frequency(
    df,
    top_n=3,
    rebalance_every=1,
    cost_per_rebalance=0.0005,
    initial_capital=10000,
):
    equity = initial_capital
    equity_history = []
    return_history = []

    dates = sorted(df["date"].unique())
    current_portfolio = None

    for i in range(len(dates) - 1):
        signal_day = dates[i]

        should_rebalance = (
            current_portfolio is None
            or i % rebalance_every == 0
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

            selected["weight"] = 1.0 / len(selected)
            current_portfolio = selected[["ticker", "weight"]].copy()

            cost = cost_per_rebalance
        else:
            cost = 0.0

        # Use overnight return from current signal day
        return_data = df[df["date"] == signal_day][
            ["ticker", "overnight_return"]
        ].copy()

        merged = current_portfolio.merge(
            return_data,
            on="ticker",
            how="left"
        )

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


# -------------------------
# Build best known strategy
# -------------------------
df = load_prices()

df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

# Stock-level regime filter
df = df[df["regime"] != "bear"].copy()


# -------------------------
# Test rebalance frequencies
# -------------------------
frequencies = [1, 2, 3, 5, 10]

for freq in frequencies:
    print("\n" + "=" * 60)
    print(f"REBALANCE EVERY {freq} DAY(S)")
    print("=" * 60)

    equity_curve, daily_returns = simulate_rebalance_frequency(
        df,
        top_n=3,
        rebalance_every=freq,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)