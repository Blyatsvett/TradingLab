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
# STRATEGY SCORE
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
# WALK FORWARD BACKTEST
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

        results.append(test_filtered["ret"].mean())

        current += pd.DateOffset(years=test_years)

    if len(results) == 0:
        return None

    avg = np.mean(results)
    std = np.std(results)

    return avg, std


# ----------------------------
# FITNESS FUNCTION
# ----------------------------
def fitness(strategy):

    temp = df.copy()

    temp["score"] = temp.apply(
        make_score(strategy["fast"], strategy["slow"]),
        axis=1
    )

    results = []

    for regime_type in ["bull", "bear", "sideways"]:

        sub = temp[temp["regime"] == regime_type]

        if len(sub) < 100:
            continue

        train = sub.iloc[:int(len(sub) * 0.7)]
        test = sub.iloc[int(len(sub) * 0.7):]

        top = train.groupby("ticker")["score"].mean()
        top = top.sort_values(ascending=False).head(strategy["top_n"]).index.tolist()

        test_filtered = test[test["ticker"].isin(top)]

        if len(test_filtered) == 0:
            continue

        test_filtered["ret"] = test_filtered.groupby("ticker")["close"].pct_change()

        results.append(test_filtered["ret"].mean())

    if len(results) == 0:
        return -999

    avg = np.mean(results)
    std = np.std(results)

    sharpe = avg / (std + 1e-9)

    stability_penalty = std

    return avg * 0.5 + sharpe * 0.4 - stability_penalty * 0.1


# ----------------------------
# INITIAL POPULATION
# ----------------------------
def random_strategy():

    fast = random.choice([10, 20, 30, 40])
    slow = random.choice([50, 100, 150])
    top_n = random.choice([2, 3, 5, 7])

    if fast >= slow:
        fast, slow = 10, 50

    return {"fast": fast, "slow": slow, "top_n": top_n}


# ----------------------------
# MUTATION
# ----------------------------
def mutate(strategy):

    new = strategy.copy()

    if random.random() < 0.5:
        new["fast"] += random.choice([-5, 5])

    if random.random() < 0.5:
        new["slow"] += random.choice([-10, 10])

    if random.random() < 0.3:
        new["top_n"] += random.choice([-1, 1])

    # constraints
    new["fast"] = max(5, min(new["fast"], 50))
    new["slow"] = max(50, min(new["slow"], 200))
    new["top_n"] = max(1, min(new["top_n"], 10))

    if new["fast"] >= new["slow"]:
        new = random_strategy()

    return new


# ----------------------------
# EVOLUTION LOOP
# ----------------------------
POP_SIZE = 10
GENERATIONS = 5

population = [random_strategy() for _ in range(POP_SIZE)]

for gen in range(GENERATIONS):

    print(f"\n=== GENERATION {gen+1} ===")

    scored = []

    for s in population:
        f = fitness(s)
        scored.append((f, s))
        print(f, s)

    scored.sort(reverse=True, key=lambda x: x[0])

    # keep top 50%
    survivors = [s for _, s in scored[:POP_SIZE // 2]]

    # reproduce + mutate
    new_population = survivors.copy()

    while len(new_population) < POP_SIZE:
        parent = random.choice(survivors)
        child = mutate(parent)
        new_population.append(child)

    population = new_population


print("\n=== FINAL BEST STRATEGIES ===")
for s in population:
    print(s)