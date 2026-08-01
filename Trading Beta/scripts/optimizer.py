import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect("data/prices.db")
df = pd.read_sql("SELECT * FROM prices_enriched", conn)

df = df.sort_values(["date", "ticker"])

# ----------------------------
# scoring function factory
# ----------------------------
def make_score(sma_fast, sma_slow):

    def score(row):
        s = 0

        if row["close"] > row[f"sma{sma_slow}"]:
            s += 30

        if row[f"sma{sma_fast}"] > row[f"sma{sma_slow}"]:
            s += 20

        if row["return"] > 0:
            s += 20

        if pd.notna(row["volatility"]):
            if row["volatility"] < 0.02:
                s += 20
            elif row["volatility"] < 0.03:
                s += 10

        return s

    return score


# ----------------------------
# backtest function (simplified)
# ----------------------------
def run_backtest(sma_fast, sma_slow, top_n):

    temp = df.copy()

    temp["score"] = temp.apply(make_score(sma_fast, sma_slow), axis=1)

    dates = sorted(temp["date"].unique())

    portfolio = 1.0
    history = []

    for date in dates:

        daily = temp[temp["date"] == date]
        if len(daily) == 0:
            continue

        top = daily.sort_values("score", ascending=False).head(top_n)

        selected = top["ticker"].tolist()

        next_day = temp[temp["date"] > date]
        if len(next_day) == 0:
            continue

        next_prices = next_day.groupby("ticker").first().reset_index()

        returns = []

        for ticker in selected:
            if ticker in next_prices["ticker"].values:

                try:
                    buy = daily[daily["ticker"] == ticker]["close"].values[0]
                    sell = next_prices[next_prices["ticker"] == ticker]["close"].values[0]
                    returns.append((sell / buy) - 1)
                except:
                    pass

        if len(returns) == 0:
            continue

        portfolio *= (1 + np.mean(returns))
        history.append(portfolio)

    return portfolio


# ----------------------------
# GRID SEARCH
# ----------------------------
configs = [
    (20, 50, 3),
    (10, 50, 3),
    (20, 100, 3),
    (20, 50, 5),
    (10, 100, 5),
]

results = []

for fast, slow, n in configs:

    final_value = run_backtest(fast, slow, n)

    results.append({
        "sma_fast": fast,
        "sma_slow": slow,
        "top_n": n,
        "return": final_value - 1
    })

results_df = pd.DataFrame(results)
results_df = results_df.sort_values("return", ascending=False)

print("\n=== OPTIMIZATION RESULTS ===\n")
print(results_df)

conn.close()
