from core.data_loader import load_prices
from core.metrics import performance_summary
from core.rebalance_simulator import simulate_rebalance_frequency


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


df = load_prices()
df = df[df["regime"] != "bear"].copy()

df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)

for col in ["momentum_5", "gap"]:
    df[col + "_z"] = zscore_by_date(df, col)

tests = {
    "gap only": 1.0 * df["gap_z"],
    "momentum_5 only": 1.0 * df["momentum_5_z"],
    "momentum_5 + gap": (
        0.7 * df["momentum_5_z"] +
        0.3 * df["gap_z"]
    ),
}

for name, score in tests.items():
    print("\n" + "=" * 60)
    print(f"GAP FACTOR TEST: {name}")
    print("=" * 60)

    test_df = df.copy()
    test_df["score"] = score
    test_df["alpha"] = zscore_by_date(test_df, "score")
    test_df["alpha"] = test_df["alpha"].fillna(0)

    equity_curve, daily_returns = simulate_rebalance_frequency(
        test_df,
        top_n=3,
        rebalance_every=3,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)