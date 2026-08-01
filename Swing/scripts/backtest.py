import sqlite3
import pandas as pd

conn = sqlite3.connect("data/prices.db")

df = pd.read_sql("SELECT * FROM prices_enriched", conn)

df = df.sort_values(["date", "ticker"])

# ----------------------------
# Recreate scoring logic
# ----------------------------
def score(row):
    score = 0

    if row["close"] > row["sma50"]:
        score += 30
    if row["sma20"] > row["sma50"]:
        score += 20
    if row["return"] > 0:
        score += 20
    if row["return"] > 0.02:
        score += 10

    if pd.notna(row["volatility"]):
        if row["volatility"] < 0.02:
            score += 20
        elif row["volatility"] < 0.03:
            score += 10

    return score

df["score"] = df.apply(score, axis=1)

# ----------------------------
# Backtest settings
# ----------------------------
top_n = 3
portfolio = []
dates = sorted(df["date"].unique())

portfolio_value = 1.0
history = []

# ----------------------------
# Simulation loop
# ----------------------------
for date in dates:

    daily = df[df["date"] == date].copy()

    if len(daily) == 0:
        continue

    # pick top N stocks
    top = daily.sort_values("score", ascending=False).head(top_n)

    selected = top["ticker"].tolist()

    # next day returns simulation
    next_day = df[df["date"] > date]

    if len(next_day) == 0:
        continue

    next_prices = next_day.groupby("ticker").first().reset_index()

    returns = []

    for ticker in selected:
        if ticker in next_prices["ticker"].values:
            r = next_prices[next_prices["ticker"] == ticker]["close"].values[0] / \
                daily[daily["ticker"] == ticker]["close"].values[0] - 1
            returns.append(r)

    if len(returns) == 0:
        continue

    daily_return = sum(returns) / len(returns)

    portfolio_value *= (1 + daily_return)

    history.append((date, portfolio_value))

# ----------------------------
# Results
# ----------------------------
result = pd.DataFrame(history, columns=["date", "portfolio"])
result["date"] = pd.to_datetime(result["date"])

print("\n=== BACKTEST RESULT ===\n")
print(result.tail())

print(f"\nFinal portfolio value: {portfolio_value:.2f}x")

conn.close()