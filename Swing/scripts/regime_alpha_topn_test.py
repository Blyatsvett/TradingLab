from core.data_loader import load_prices
from core.metrics import performance_summary
from core.rebalance_simulator import simulate_rebalance_frequency


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


df = load_prices()

# -------------------------
# Build factors
# -------------------------
df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["trend_50"] = df["close"] / df["sma50"] - 1

for col in ["momentum_5", "trend_50"]:
    df[col + "_z"] = zscore_by_date(df, col)

# -------------------------
# Alpha v2
# -------------------------
df["alpha"] = 0.0

df.loc[
    df["regime"] == "bull",
    "alpha"
] = (
    0.80 * df["momentum_5_z"]
    + 0.20 * df["trend_50_z"]
)

df.loc[
    df["regime"] == "sideways",
    "alpha"
] = df["momentum_5_z"]

df = df[df["regime"] != "bear"].copy()
df["alpha"] = df["alpha"].fillna(0)

# -------------------------
# Test portfolio sizes
# -------------------------
for top_n in [2, 3, 5]:
    print("\n" + "=" * 60)
    print(f"REGIME ALPHA TOP-N TEST: {top_n}")
    print("=" * 60)

    equity_curve, daily_returns = simulate_rebalance_frequency(
        df,
        top_n=top_n,
        rebalance_every=3,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)