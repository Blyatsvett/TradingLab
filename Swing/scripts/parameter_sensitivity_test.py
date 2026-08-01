from core.data_loader import load_prices
from core.simulator import simulate_portfolio
from core.metrics import performance_summary

import pandas as pd


def build_custom_alpha(df, sma_col="sma100", trend_weight=5, vol_weight=2):
    df = df.copy()

    df["score"] = 0.0

    valid_sma = df[sma_col].notna() & (df[sma_col] != 0)
    df.loc[valid_sma, "score"] += (
        (df.loc[valid_sma, "close"] / df.loc[valid_sma, sma_col] - 1)
        * trend_weight
    )

    valid_vol = df["volatility"].notna() & (df["volatility"] > 0)
    df.loc[valid_vol, "score"] -= df.loc[valid_vol, "volatility"] * vol_weight

    df["alpha"] = df.groupby("date")["score"].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )

    return df


df = load_prices()

tests = [
    ("SMA50 / vol 2", "sma50", 5, 2),
    ("SMA100 / vol 2", "sma100", 5, 2),
    ("SMA150 / vol 2", "sma150", 5, 2),
    ("SMA100 / vol 1", "sma100", 5, 1),
    ("SMA100 / vol 3", "sma100", 5, 3),
    ("SMA50 / vol 1", "sma50", 5, 1),
    ("SMA150 / vol 3", "sma150", 5, 3),
]

for name, sma_col, trend_weight, vol_weight in tests:
    print("\n" + "=" * 60)
    print(f"PARAMETER TEST: {name}")
    print("=" * 60)

    test_df = build_custom_alpha(
        df,
        sma_col=sma_col,
        trend_weight=trend_weight,
        vol_weight=vol_weight,
    )

    equity_curve, daily_returns, _, _ = simulate_portfolio(test_df)

    performance_summary(equity_curve, daily_returns)