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
df["gap"] = df["gap"]
df["trend_50"] = df["close"] / df["sma50"] - 1

for col in ["momentum_5", "gap", "trend_50"]:
    df[col + "_z"] = zscore_by_date(df, col)


# -------------------------
# Baseline: momentum_5, skip bear
# -------------------------
baseline = df[df["regime"] != "bear"].copy()
baseline["alpha"] = baseline["momentum_5_z"].fillna(0)

print("\n" + "=" * 60)
print("BASELINE: MOMENTUM_5, SKIP BEAR")
print("=" * 60)

equity_curve, daily_returns = simulate_rebalance_frequency(
    baseline,
    top_n=3,
    rebalance_every=3,
    cost_per_rebalance=0.0005,
)

performance_summary(equity_curve, daily_returns)


# -------------------------
# Regime-aware Alpha v1
# -------------------------
regime_df = df.copy()

regime_df["alpha"] = 0.0

# Bull: strong momentum
regime_df.loc[
    regime_df["regime"] == "bull",
    "alpha"
] = regime_df["momentum_5_z"]

# Sideways: mix momentum + gap
regime_df.loc[
    regime_df["regime"] == "sideways",
    "alpha"
] = (
    0.70 * regime_df["momentum_5_z"]
    + 0.30 * regime_df["gap_z"]
)

# Bear: no trading
regime_df = regime_df[regime_df["regime"] != "bear"].copy()
regime_df["alpha"] = regime_df["alpha"].fillna(0)

print("\n" + "=" * 60)
print("REGIME-AWARE ALPHA V1")
print("=" * 60)

equity_curve, daily_returns = simulate_rebalance_frequency(
    regime_df,
    top_n=3,
    rebalance_every=3,
    cost_per_rebalance=0.0005,
)

performance_summary(equity_curve, daily_returns)


# -------------------------
# Regime-aware Alpha v2
# -------------------------
regime_df = df.copy()

regime_df["alpha"] = 0.0

# Bull: momentum + trend
regime_df.loc[
    regime_df["regime"] == "bull",
    "alpha"
] = (
    0.80 * regime_df["momentum_5_z"]
    + 0.20 * regime_df["trend_50_z"]
)

# Sideways: pure momentum
regime_df.loc[
    regime_df["regime"] == "sideways",
    "alpha"
] = regime_df["momentum_5_z"]

# Bear: no trading
regime_df = regime_df[regime_df["regime"] != "bear"].copy()
regime_df["alpha"] = regime_df["alpha"].fillna(0)

print("\n" + "=" * 60)
print("REGIME-AWARE ALPHA V2")
print("=" * 60)

equity_curve, daily_returns = simulate_rebalance_frequency(
    regime_df,
    top_n=3,
    rebalance_every=3,
    cost_per_rebalance=0.0005,
)

performance_summary(equity_curve, daily_returns)