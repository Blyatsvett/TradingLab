from core.data_loader import load_prices
from core.metrics import performance_summary
from scripts.rebalance_frequency_test import simulate_rebalance_frequency

import pandas as pd


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


df = load_prices()
df = df[df["regime"] != "bear"].copy()

windows = [3, 5, 10, 20]

for window in windows:
    print("\n" + "=" * 60)
    print(f"MOMENTUM WINDOW TEST: {window}")
    print("=" * 60)

    test_df = df.copy()

    factor = f"momentum_{window}"
    test_df[factor] = (
        test_df.groupby("ticker")["close"].pct_change(window)
    )

    test_df["alpha"] = zscore_by_date(test_df, factor)
    test_df["alpha"] = test_df["alpha"].fillna(0)

    equity_curve, daily_returns = simulate_rebalance_frequency(
        test_df,
        top_n=3,
        rebalance_every=3,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)