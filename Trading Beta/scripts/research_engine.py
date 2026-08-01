import sqlite3
import pandas as pd
import numpy as np

# ----------------------------
# Load data
# ----------------------------
conn = sqlite3.connect("data/prices.db")
df = pd.read_sql("SELECT * FROM prices_enriched", conn)
conn.close()

df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["date", "ticker"])

# ----------------------------
# PARAMETER SPACE (THIS IS THE MAGIC)
# ----------------------------
strategies = [
    {"sma_fast": 10, "sma_slow": 50, "top_n": 3},
    {"sma_fast": 20, "sma_slow": 50, "top_n": 3},
    {"sma_fast": 20, "sma_slow": 100, "top_n": 3},
    {"sma_fast": 10, "sma_slow": 100, "top_n": 5},
    {"sma_fast": 20, "sma_slow": 50, "top_n": 5},
]

# ----------------------------
# scoring factory
# ----------------------------
def make_score(fast, slow):

    def score(row):
        s = 0

        if row["close"] > row[f"sma{slow}"]:
            s += 30

        if row[f"sma{fast}"] > row[f"sma{slow}"]:
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
# walk-forward backtest
# ----------------------------
def walk_forward(strategy):

    temp = df.copy()
    temp["score"] = temp.apply(make_score(strategy["sma_fast"], strategy["sma_slow"]), axis=1)

    train_years = 3
    test_years = 1

    start = temp["date"].min()

    results = []

    current = start

    while True:

        train_end = current + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)

        train = temp[(temp["date"] >= current) & (temp["date"] < train_end)]
        test = temp[(temp["date"] >= train_end) & (temp["date"] < test_end)]

        if len(train) == 0 or len(test) == 0:
            break

        top = train.groupby("ticker")["score"].mean().sort_values(ascending=False)
        top = top.head(strategy["top_n"]).index.tolist()

        test_filtered = test[test["ticker"].isin(top)].copy()

        if len(test_filtered) == 0:
            current += pd.DateOffset(years=test_years)
            continue

        test_filtered["ret"] = test_filtered.groupby("ticker")["close"].pct_change()

        avg_ret = test_filtered["ret"].mean()

        results.append(avg_ret)

        current += pd.DateOffset(years=test_years)

    if len(results) == 0:
        return None

    return {
        "avg_return": np.mean(results),
        "stability": np.std(results),
        "sharpe": np.mean(results) / (np.std(results) + 1e-9)
    }


# ----------------------------
# RUN ALL STRATEGIES
# ----------------------------
results = []

for strat in strategies:

    print(f"Running: {strat}")

    res = walk_forward(strat)

    if res is None:
        continue

    results.append({
        **strat,
        **res
    })

# ----------------------------
# RANKING ENGINE
# ----------------------------
results_df = pd.DataFrame(results)

results_df["score"] = (
    results_df["avg_return"] * 0.5 +
    results_df["sharpe"] * 0.4 -
    results_df["stability"] * 0.1
)

results_df = results_df.sort_values("score", ascending=False)

print("\n=== STRATEGY LEADERBOARD ===\n")
print(results_df)