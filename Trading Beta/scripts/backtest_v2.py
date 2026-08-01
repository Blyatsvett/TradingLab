import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

conn = sqlite3.connect("data/prices.db")

df = pd.read_sql("SELECT * FROM prices_enriched", conn)

df = df.sort_values(["date", "ticker"])

# ----------------------------
# scoring model
# ----------------------------
def score(row):
    s = 0

    if row["close"] > row["sma50"]:
        s += 30
    if row["sma20"] > row["sma50"]:
        s += 20
    if row["return"] > 0:
        s += 20
    if row["return"] > 0.02:
        s += 10

    if pd.notna(row["volatility"]):
        if row["volatility"] < 0.02:
            s += 20
        elif row["volatility"] < 0.03:
            s += 10

    return s

df["score"] = df.apply(score, axis=1)

# ----------------------------
# backtest
# ----------------------------
top_n = 3
dates = sorted(df["date"].unique())

portfolio_value = 1.0
history = []

for date in dates:

    daily = df[df["date"] == date].copy()
    if len(daily) == 0:
        continue

    top = daily.sort_values("score", ascending=False).head(top_n)
    selected = top["ticker"].tolist()

    next_day = df[df["date"] > date]

    if len(next_day) == 0:
        continue

    next_prices = next_day.groupby("ticker").first().reset_index()

    returns = []

    for ticker in selected:
        if ticker in next_prices["ticker"].values:

            try:
                buy_price = daily[daily["ticker"] == ticker]["close"].values[0]
                sell_price = next_prices[next_prices["ticker"] == ticker]["close"].values[0]
                r = (sell_price / buy_price) - 1
                returns.append(r)
            except:
                pass

    if len(returns) == 0:
        continue

    daily_return = sum(returns) / len(returns)

    portfolio_value *= (1 + daily_return)

    history.append((date, portfolio_value))

conn.close()

# ----------------------------
# analytics layer
# ----------------------------
result = pd.DataFrame(history, columns=["date", "portfolio"])
result["date"] = pd.to_datetime(result["date"])
result = result.sort_values("date")

# returns
result["returns"] = result["portfolio"].pct_change()

# drawdown
result["peak"] = result["portfolio"].cummax()
result["drawdown"] = (result["portfolio"] - result["peak"]) / result["peak"]

# ----------------------------
# metrics
# ----------------------------
total_return = result["portfolio"].iloc[-1] - 1
max_dd = result["drawdown"].min()

print("\n=== PERFORMANCE ===")
print(f"Total return: {total_return:.2%}")
print(f"Max drawdown: {max_dd:.2%}")

# ----------------------------
# plot equity curve
# ----------------------------
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

ax1.plot(result["date"], result["portfolio"])
ax1.set_title("Equity Curve")

ax2.plot(result["date"], result["drawdown"])
ax2.set_title("Drawdown")

plt.tight_layout()
plt.show()

import numpy as np

# daily returns
result["returns"] = result["portfolio"].pct_change()

# remove first NaN
rets = result["returns"].dropna()

# annualized metrics (approx)
mean_return = rets.mean()
std_return = rets.std()

sharpe = (mean_return / std_return) * np.sqrt(252)

total_return = result["portfolio"].iloc[-1] - 1
max_dd = result["drawdown"].min()

print("\n=== STRATEGY METRICS ===\n")
print(f"Total return: {total_return:.2%}")
print(f"Sharpe ratio: {sharpe:.2f}")
print(f"Max drawdown: {max_dd:.2%}")