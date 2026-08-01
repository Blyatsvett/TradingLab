from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.simulator import simulate_portfolio
from core.metrics import performance_summary

import pandas as pd


# -------------------------
# LOAD DATA
# -------------------------

df = load_prices()

df = build_alpha(df)


# -------------------------
# STRATEGY
# -------------------------

equity_curve, daily_returns, trade_log, portfolio_history = simulate_portfolio(df)


print("\n")
print("=" * 60)
print("ALPHA STRATEGY")
print("=" * 60)

performance_summary(
    equity_curve,
    daily_returns
)


# -------------------------
# BENCHMARK
# Equal-weight all stocks
# -------------------------

benchmark = (
    df.groupby("date")["return"]
      .mean()
      .reset_index()
)

equity = 10000

equity_history = []

for _, row in benchmark.iterrows():

    r = 0 if pd.isna(row["return"]) else row["return"]

    equity *= (1 + r)

    equity_history.append(
        {
            "date": row["date"],
            "equity": equity
        }
    )

benchmark_equity = pd.DataFrame(equity_history)

benchmark_returns = benchmark.rename(
    columns={
        "return": "daily_return"
    }
)


print("\n")
print("=" * 60)
print("EQUAL-WEIGHT BENCHMARK")
print("=" * 60)

performance_summary(
    benchmark_equity,
    benchmark_returns
)