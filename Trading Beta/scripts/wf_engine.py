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
# Strategy definition
# ----------------------------
def score(row):
    s = 0

    if row["close"] > row["sma50"]:
        s += 30

    if row["sma20"] > row["sma50"]:
        s += 20

    if row["return"] > 0:
        s += 20

    if pd.notna(row["volatility"]):
        if row["volatility"] < 0.02:
            s += 20
        elif row["volatility"] < 0.03:
            s += 10

    return s

df["score"] = df.apply(score, axis=1)

# ----------------------------
# Walk-forward settings
# ----------------------------
train_years = 3
test_years = 1

start = df["date"].min()

results = []

current_start = start

# ----------------------------
# Walk-forward loop
# ----------------------------
while True:

    train_end = current_start + pd.DateOffset(years=train_years)
    test_end = train_end + pd.DateOffset(years=test_years)

    train = df[(df["date"] >= current_start) & (df["date"] < train_end)]
    test = df[(df["date"] >= train_end) & (df["date"] < test_end)]

    if len(train) == 0 or len(test) == 0:
        break

    # ----------------------------
    # pick top strategies from TRAIN
    # ----------------------------
    train_scores = train.groupby("ticker")["score"].mean()
    top = train_scores.sort_values(ascending=False).head(3).index.tolist()

    # ----------------------------
    # evaluate on TEST
    # ----------------------------
    test_filtered = test[test["ticker"].isin(top)].copy()

    if len(test_filtered) == 0:
        current_start += pd.DateOffset(years=test_years)
        continue

    test_filtered["ret"] = test_filtered.groupby("ticker")["close"].pct_change()

    avg_return = test_filtered["ret"].mean()
    std_return = test_filtered["ret"].std()

    if pd.isna(std_return) or std_return == 0:
        sharpe = 0
    else:
        sharpe = avg_return / std_return

    results.append({
        "train_start": current_start,
        "train_end": train_end,
        "test_end": test_end,
        "return": avg_return,
        "sharpe": sharpe
    })

    current_start += pd.DateOffset(years=test_years)

# ----------------------------
# RESULTS ANALYSIS
# ----------------------------
res = pd.DataFrame(results)

print("\n=== WALK-FORWARD RESULTS ===\n")
print(res)

print("\n=== STRATEGY QUALITY ===\n")

avg_return = res["return"].mean()
avg_sharpe = res["sharpe"].mean()
stability = res["return"].std()

print(f"Avg return (OOS): {avg_return:.4f}")
print(f"Avg Sharpe (OOS): {avg_sharpe:.4f}")
print(f"Stability (std of returns): {stability:.4f}")

# ----------------------------
# DECISION LOGIC (KEY PART)
# ----------------------------
print("\n=== DECISION ===\n")

if avg_return > 0 and avg_sharpe > 0.5 and stability < 0.02:
    print("✅ STRATEGY ACCEPTED (robust)")
else:
    print("❌ STRATEGY REJECTED (unstable or weak)")