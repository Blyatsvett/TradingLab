import sqlite3
import pandas as pd
import numpy as np
import random

# ----------------------------
# LOAD DATA
# ----------------------------
conn = sqlite3.connect("data/prices.db")
df = pd.read_sql("SELECT * FROM prices_enriched", conn)
conn.close()

df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["ticker", "date"])

# ----------------------------
# STRATEGY SCORE FUNCTION
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
# WALK-FORWARD ENGINE
# ----------------------------
def walk_forward(fast, slow, top_n):

    temp = df.copy()
    temp["score"] = temp.apply(make_score(fast, slow), axis=1)

    train_years = 3
    test_years = 1

    start = temp["date"].min()
    current = start

    results = []

    while True:

        train_end = current + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)

        train = temp[(temp["date"] >= current) & (temp["date"] < train_end)]
        test = temp[(temp["date"] >= train_end) & (temp["date"] < test_end)]

        if len(train) == 0 or len(test) == 0:
            break

        top = train.groupby("ticker")["score"].mean()
        top = top.sort_values(ascending=False).head(top_n).index.tolist()

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

    return np.mean(results), np.std(results)


# ----------------------------
# RANDOM STRATEGY GENERATION
# ----------------------------
def generate_strategy():

    fast = random.choice([10, 20])
    slow = random.choice([50, 100])

    top_n = random.choice([2, 3, 5, 7])

    if fast >= slow:
        fast, slow = 10, 50

    return fast, slow, top_n


# ----------------------------
# EVOLUTION LOOP
# ----------------------------
N = 20  # number of strategies to test

results = []

for i in range(N):

    fast, slow, top_n = generate_strategy()

    print(f"Testing strategy {i+1}: SMA{fast}/{slow}, top {top_n}")

    res = walk_forward(fast, slow, top_n)

    if res is None:
        continue

    avg_ret, std_ret = res

    sharpe = avg_ret / (std_ret + 1e-9)

    score = (avg_ret * 0.5) + (sharpe * 0.5)

    results.append({
        "fast": fast,
        "slow": slow,
        "top_n": top_n,
        "avg_return": avg_ret,
        "sharpe": sharpe,
        "score": score
    })

# ----------------------------
# RESULTS
# ----------------------------
df_res = pd.DataFrame(results)
df_res = df_res.sort_values("score", ascending=False)

print("\n=== EVOLUTION RESULTS ===\n")
print(df_res)

print("\nBEST STRATEGY:\n")
print(df_res.head(1))