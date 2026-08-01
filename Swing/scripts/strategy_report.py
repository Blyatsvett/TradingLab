import sqlite3
import pandas as pd
import numpy as np

# ----------------------------
# LOAD DATA
# ----------------------------
conn = sqlite3.connect("data/prices.db")
df = pd.read_sql("SELECT * FROM prices_enriched", conn)
conn.close()

df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["ticker", "date"])


# ----------------------------
# STRATEGY SCORING (same logic family)
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
# STRATEGY TEST FUNCTION
# ----------------------------
def test_strategy(fast, slow, top_n):

    temp = df.copy()
    temp["score"] = temp.apply(make_score(fast, slow), axis=1)

    results = []

    for regime in ["bull", "bear", "sideways"]:

        sub = temp[temp["regime"] == regime]

        if len(sub) < 200:
            continue

        train = sub.iloc[:int(len(sub)*0.7)]
        test = sub.iloc[int(len(sub)*0.7):]

        top = train.groupby("ticker")["score"].mean()
        top = top.sort_values(ascending=False).head(top_n).index.tolist()

        test_filtered = test[test["ticker"].isin(top)]

        if len(test_filtered) == 0:
            continue

        test_filtered["ret"] = test_filtered.groupby("ticker")["close"].pct_change()

        avg_ret = test_filtered["ret"].mean()

        results.append((regime, avg_ret))

    return results


# ----------------------------
# STRATEGY GRID
# ----------------------------
strategies = [
    (10, 50, 3),
    (10, 100, 3),
    (20, 50, 5),
    (20, 100, 5),
    (30, 100, 3),
]


# ----------------------------
# RUN REPORT
# ----------------------------
rows = []

for fast, slow, top_n in strategies:

    res = test_strategy(fast, slow, top_n)

    row = {
        "strategy": f"SMA{fast}/{slow} top{top_n}",
        "bull": 0,
        "bear": 0,
        "sideways": 0
    }

    for regime, r in res:
        row[regime] = r

    rows.append(row)


report = pd.DataFrame(rows)

print("\n=== STRATEGY REGIME PERFORMANCE ===\n")
print(report)

print("\n=== BEST IN BULL ===")
print(report.sort_values("bull", ascending=False).head(1))

print("\n=== BEST IN BEAR ===")
print(report.sort_values("bear", ascending=False).head(1))

print("\n=== BEST IN SIDEWAYS ===")
print(report.sort_values("sideways", ascending=False).head(1))