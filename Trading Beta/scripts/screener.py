import sqlite3
import pandas as pd

conn = sqlite3.connect("data/prices.db")

df = pd.read_sql("SELECT * FROM prices_enriched", conn)

# Make sure sorted correctly
df = df.sort_values(["ticker", "date"])

# Take latest row per stock
latest = df.groupby("ticker").tail(1).copy()

# Momentum rules
def classify(row):
    if (
        row["close"] > row["sma50"]
        and row["sma20"] > row["sma50"]
        and row["return"] > 0
    ):
        return "🚀 Strong Uptrend"

    elif row["close"] < row["sma50"]:
        return "📉 Downtrend"

    else:
        return "⚪ Neutral"

latest["signal"] = latest.apply(classify, axis=1)

# Show clean output
result = latest[["ticker", "close", "sma20", "sma50", "return", "signal"]]

print("\n=== MOMENTUM SCREENER ===\n")
print(result.to_string(index=False))

conn.close()
