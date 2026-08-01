from core.data_loader import load_prices
from core.metrics import performance_summary
from core.overnight_simulator import simulate_overnight_execution


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


# -------------------------
# Build momentum_5 alpha
# -------------------------
df = load_prices()

df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)

df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

# -------------------------
# Test portfolio sizes
# -------------------------
portfolio_sizes = [3, 5, 10, 15]

for top_n in portfolio_sizes:
    print("\n" + "=" * 60)
    print(f"PORTFOLIO SIZE TEST: TOP {top_n}")
    print("=" * 60)

    equity_curve, daily_returns, _, _ = simulate_overnight_execution(
        df,
        top_n=top_n,
    )

    performance_summary(equity_curve, daily_returns)