from core.data_loader import load_prices
from core.metrics import performance_summary
from core.rebalance_simulator import simulate_rebalance_frequency


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


df = load_prices()

df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

df = df[df["regime"] != "bear"].copy()

print("\n" + "=" * 60)
print("EXPANDED UNIVERSE TEST: MOMENTUM_5")
print("=" * 60)

equity_curve, daily_returns = simulate_rebalance_frequency(
    df,
    top_n=2,
    rebalance_every=3,
    cost_per_rebalance=0.0005,
)

performance_summary(equity_curve, daily_returns)