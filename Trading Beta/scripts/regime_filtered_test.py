from core.data_loader import load_prices
from core.metrics import performance_summary
from core.overnight_simulator import simulate_overnight_execution


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


df = load_prices()

# momentum_5 alpha
df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

# filter out bear regime
filtered_df = df[df["regime"] != "bear"].copy()

print("\n" + "=" * 60)
print("REGIME FILTERED TEST: BULL + SIDEWAYS ONLY")
print("=" * 60)

equity_curve, daily_returns, _, _ = simulate_overnight_execution(
    filtered_df,
    top_n=3,
)

performance_summary(equity_curve, daily_returns)