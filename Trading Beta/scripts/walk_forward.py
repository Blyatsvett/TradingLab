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
# strategy (same as before)
# ----------------------------
def make_score(row):
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


df["score"] = df.apply(make_score, axis=1)

# ----------------------------
# walk-forward windows
# ----------------------------
train_years = 3
test_years = 1

start = df["date"].min()
end = df["date"].max()

results = []

current_start = start

while True:

    train_end = current_start + pd.DateOffset(years=train_years)
    test_end = train_end + pd.DateOffset(years=test_years)

    train = df[(df["date"] >= current_start) & (df["date"] < train_end)]
    test = df[(df["date"] >= train_end) & (df["date"] < test_end)]

    if len(test) == 0:
        break

    if len(train) == 0:
        break

    # ----------------------------
    # "learn" best stocks on TRAIN
    # ----------------------------
    daily_train = train.groupby("ticker")["score"].mean()
    top_tickers = daily_train.sort_values(ascending=False).head(3).index.tolist()

    # ----------------------------
    # simulate on TEST
    # ----------------------------
    test = test[test["ticker"].isin(top_tickers)]

    if len(test) == 0:
        current_start += pd.DateOffset(years=test_years)
        continue

    test_returns = test.groupby("ticker")["close"].pct_change().dropna()

    if len(test_returns) == 0:
        current_start += pd.DateOffset(years=test_years)
        continue

    period_return = test_returns.mean()

    results.append({
        "train_start": current_start,
        "train_end": train_end,
        "test_end": test_end,
        "return": period_return
    })

    current_start += pd.DateOffset(years=test_years)

# ----------------------------
# results
# ----------------------------
results_df = pd.DataFrame(results)

print("\n=== WALK FORWARD RESULTS ===\n")
print(results_df)

print("\nAverage out-of-sample return:", results_df["return"].mean())