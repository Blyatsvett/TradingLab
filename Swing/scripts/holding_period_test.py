from core.data_loader import load_prices
from core.metrics import performance_summary

import pandas as pd


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


def simulate_holding_period(df, top_n=3, holding_days=1, initial_capital=10000):
    equity = initial_capital
    equity_history = []
    return_history = []

    dates = sorted(df["date"].unique())

    print(f"\nRunning holding-period simulation: {holding_days} day(s)")
    print(f"Trading days: {len(dates)}")

    for i in range(len(dates) - holding_days):

        signal_day = dates[i]
        exit_day = dates[i + holding_days]

        signal_data = df[df["date"] == signal_day].copy()
        exit_data = df[df["date"] == exit_day][["ticker", "close"]].copy()
        entry_data = df[df["date"] == signal_day][["ticker", "close"]].copy()

        entry_data = entry_data.rename(columns={"close": "entry_close"})
        exit_data = exit_data.rename(columns={"close": "exit_close"})

        selected = (
            signal_data
            .sort_values("alpha", ascending=False)
            .head(top_n)
            .copy()
        )

        if len(selected) == 0:
            continue

        selected["weight"] = 1.0 / len(selected)

        merged = selected.merge(entry_data, on="ticker", how="left")
        merged = merged.merge(exit_data, on="ticker", how="left")

        merged["holding_return"] = (
            merged["exit_close"] / merged["entry_close"] - 1
        )

        merged["holding_return"] = merged["holding_return"].fillna(0)

        period_return = (
            merged["weight"] * merged["holding_return"]
        ).sum()

        equity *= (1 + period_return)

        equity_history.append({
            "date": exit_day,
            "equity": equity,
        })

        return_history.append({
            "date": exit_day,
            "daily_return": period_return,
        })

    return pd.DataFrame(equity_history), pd.DataFrame(return_history)


# -------------------------
# Build momentum_5 alpha
# -------------------------
df = load_prices()

df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)


# -------------------------
# Test holding periods
# -------------------------
holding_periods = [1, 2, 3, 5]

for holding_days in holding_periods:
    print("\n" + "=" * 60)
    print(f"HOLDING PERIOD TEST: {holding_days} DAY(S)")
    print("=" * 60)

    equity_curve, daily_returns = simulate_holding_period(
        df,
        top_n=3,
        holding_days=holding_days,
    )

    performance_summary(equity_curve, daily_returns)