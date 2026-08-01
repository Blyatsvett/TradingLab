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
df["momentum_20"] = df.groupby("ticker")["close"].pct_change(20)
df["trend_50"] = df["close"] / df["sma50"] - 1
df["continuation_1"] = df.groupby("ticker")["return"].shift(0)

for col in ["momentum_5", "momentum_20", "trend_50", "continuation_1"]:
    df[col + "_z"] = zscore_by_date(df, col)

tests = {
    "momentum_5 only": (
        1.00 * df["momentum_5_z"]
    ),
    "momentum_5 + trend_50": (
        0.70 * df["momentum_5_z"]
        + 0.30 * df["trend_50_z"]
    ),
    "momentum_5 + momentum_20": (
        0.70 * df["momentum_5_z"]
        + 0.30 * df["momentum_20_z"]
    ),
    "momentum_5 + continuation_1": (
        0.70 * df["momentum_5_z"]
        + 0.30 * df["continuation_1_z"]
    ),
    "balanced combo": (
        0.50 * df["momentum_5_z"]
        + 0.20 * df["trend_50_z"]
        + 0.20 * df["continuation_1_z"]
        + 0.10 * df["momentum_20_z"]
    ),
}

for name, score in tests.items():
    print("\n" + "=" * 60)
    print(f"FACTOR COMBO TEST: {name}")
    print("=" * 60)

    test_df = df.copy()
    test_df["alpha"] = zscore_by_date(
        test_df.assign(score=score),
        "score"
    )
    test_df["alpha"] = test_df["alpha"].fillna(0)

    equity_curve, daily_returns = simulate_rebalance_frequency(
        test_df,
        top_n=3,
        rebalance_every=3,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)