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

df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

df = df[df["regime"] != "bear"].copy()

print("\nMissing sectors:")
print(df[df["sector"].isna()]["ticker"].unique())

for sector in sorted(df["sector"].dropna().unique()):
    print("\n" + "=" * 60)
    print(f"SECTOR TEST: {sector}")
    print("=" * 60)

    sector_df = df[df["sector"] == sector].copy()

    equity_curve, daily_returns = simulate_rebalance_frequency(
        sector_df,
        top_n=3,
        rebalance_every=3,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)