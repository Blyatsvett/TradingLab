from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.simulator import simulate_portfolio

import pandas as pd


# -------------------------
# LOAD + SIMULATE
# -------------------------
df = load_prices()
df = build_alpha(df)

equity_curve, daily_returns, trade_log, portfolio_history = simulate_portfolio(df)


# -------------------------
# TURNOVER CALCULATION
# -------------------------
dates = sorted(portfolio_history["date"].unique())

turnover_values = []

for i in range(1, len(dates)):

    prev_date = dates[i - 1]
    curr_date = dates[i]

    prev_port = portfolio_history[
        portfolio_history["date"] == prev_date
    ][["ticker", "weight"]].copy()

    curr_port = portfolio_history[
        portfolio_history["date"] == curr_date
    ][["ticker", "weight"]].copy()

    prev_port = prev_port.rename(
        columns={"weight": "prev_weight"}
    )

    curr_port = curr_port.rename(
        columns={"weight": "curr_weight"}
    )

    merged = prev_port.merge(
        curr_port,
        on="ticker",
        how="outer"
    ).fillna(0)

    turnover = (
        (merged["curr_weight"] - merged["prev_weight"])
        .abs()
        .sum()
    )

    turnover_values.append(turnover)


turnover_series = pd.Series(turnover_values)


# -------------------------
# REPORT
# -------------------------
print("\n")
print("=" * 40)
print("TURNOVER REPORT")
print("=" * 40)

print(f"Average Daily Turnover : {turnover_series.mean():.2%}")
print(f"Median Daily Turnover  : {turnover_series.median():.2%}")
print(f"Max Daily Turnover     : {turnover_series.max():.2%}")

annual_turnover = turnover_series.mean() * 252

print(f"Estimated Annual Turnover: {annual_turnover:.2f}x")

print("=" * 40)