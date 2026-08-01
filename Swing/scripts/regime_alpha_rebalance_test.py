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
# Regime-aware Alpha V2
# -------------------------
df["alpha"] = 0.0

df.loc[df["regime"] == "bull", "alpha"] = (
    0.80 * df["momentum_5_z"]
    + 0.20 * df["trend_50_z"]
)

df.loc[df["regime"] == "sideways", "alpha"] = df["momentum_5_z"]

df = df[df["regime"] != "bear"].copy()
df["alpha"] = df["alpha"].fillna(0)

# -------------------------
# Rebalance frequency tests
# -------------------------
for freq in [1, 2, 3, 5, 10]:
    print("\n" + "=" * 60)
    print(f"REGIME ALPHA REBALANCE TEST: EVERY {freq} DAY(S)")
    print("=" * 60)

    equity_curve, daily_returns = simulate_rebalance_frequency(
        df,
        top_n=2,
        rebalance_every=freq,
        cost_per_rebalance=0.0005,
    )

    performance_summary(equity_curve, daily_returns)