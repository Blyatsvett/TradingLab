from core.data_loader import load_prices
from core.metrics import performance_summary
from core.overnight_simulator import simulate_overnight_execution


def zscore_by_date(df, col):
    return df.groupby("date")[col].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )


def apply_transaction_costs(daily_returns, cost_per_trade=0.0005):
    daily_returns = daily_returns.copy()

    # Assume full turnover each rebalance
    daily_returns["daily_return"] = (
        daily_returns["daily_return"] - cost_per_trade
    )

    return daily_returns


# -------------------------
# Build best strategy alpha
# -------------------------
df = load_prices()

df["momentum_5"] = df.groupby("ticker")["close"].pct_change(5)
df["alpha"] = zscore_by_date(df, "momentum_5")
df["alpha"] = df["alpha"].fillna(0)

# Regime filter
filtered_df = df[df["regime"] != "bear"].copy()

print("\n" + "=" * 60)
print("REALISTIC COST TEST")
print("=" * 60)

equity_curve, daily_returns, _, _ = simulate_overnight_execution(
    filtered_df,
    top_n=3,
)

print("\nBASE STRATEGY")
performance_summary(equity_curve, daily_returns)

# Test cost scenarios
costs = [0.0002, 0.0005, 0.0010]

for cost in costs:
    print("\n" + "=" * 60)
    print(f"COST TEST: {cost*100:.02f}%")
    print("=" * 60)

    cost_returns = apply_transaction_costs(daily_returns, cost)

    equity = 10000
    equity_curve_cost = []

    for _, row in cost_returns.iterrows():
        equity *= (1 + row["daily_return"])
        equity_curve_cost.append({
            "date": row["date"],
            "equity": equity,
        })

    import pandas as pd
    equity_curve_cost = pd.DataFrame(equity_curve_cost)

    performance_summary(equity_curve_cost, cost_returns)