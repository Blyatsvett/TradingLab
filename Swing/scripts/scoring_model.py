import sqlite3
import pandas as pd

conn = sqlite3.connect("data/prices.db")

df = pd.read_sql("SELECT * FROM prices_enriched", conn)

df = df.sort_values(["ticker", "date"])

latest = df.groupby("ticker").tail(1).copy()

# ---------------------------
# Scoring system (0–100)
# ---------------------------

def score(row):
    score = 0

    # Trend strength
    if row["close"] > row["sma50"]:
        score += 30
    if row["sma20"] > row["sma50"]:
        score += 20

    # Momentum
    if row["return"] > 0:
        score += 20
    if row["return"] > 0.02:
        score += 10

    # Volatility (lower = better)
    if pd.notna(row["volatility"]):
        if row["volatility"] < 0.02:
            score += 20
        elif row["volatility"] < 0.03:
            score += 10

    return score

latest["score"] = latest.apply(score, axis=1)

result = latest[["ticker", "close", "sma20", "sma50", "return", "volatility", "score"]]

result = result.sort_values("score", ascending=False)

print("\n=== STOCK RANKING (0–100) ===\n")
print(result.to_string(index=False))

conn.close()