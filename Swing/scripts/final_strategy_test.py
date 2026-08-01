from core.data_loader import load_prices
from core.metrics import performance_summary
from scripts.rebalance_frequency_test import simulate_rebalance_frequency

import pandas as pd


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


df = load_prices()

sector_map = pd.read_csv("data/sector_map.csv")
df = df.merge(sector_map, on="ticker", how="left")

# Alpha: momentum_5
df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

# Filters
df = df[df["regime"] != "bear"].copy()
df = df[df["sector"] == "Financials"].copy()

print("\n" + "=" * 60)
print("FINAL STRATEGY TEST")
print("=" * 60)

equity_curve, daily_returns = simulate_rebalance_frequency(
    df,
    top_n=3,
    rebalance_every=3,
    cost_per_rebalance=0.0005,
)

performance_summary(equity_curve, daily_returns)