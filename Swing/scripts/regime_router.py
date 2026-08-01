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
df = df.sort_values(["date"])


# ----------------------------
# SIMPLE REGIME DETECTOR (LATEST STATE)
# ----------------------------
latest = df.groupby("ticker").tail(1)

regime_counts = latest["regime"].value_counts()
current_regime = regime_counts.idxmax()

print("\n=== CURRENT MARKET REGIME ===")
print(regime_counts)
print(f"\n👉 Dominant regime: {current_regime}")


# ----------------------------
# DEFINE STRATEGY MAP (from your experiments)
# ----------------------------
strategy_map = {
    "bull": ("SMA20", "SMA100", 5),
    "bear": ("SMA10", "SMA50", 3),
    "sideways": ("SMA30", "SMA100", 2)
}


# ----------------------------
# SELECT STRATEGY
# ----------------------------
fast, slow, top_n = strategy_map[current_regime]

print("\n=== SELECTED STRATEGY ===")
print(f"Regime: {current_regime}")
print(f"Using: {fast}/{slow}, top {top_n}")


# ----------------------------
# SIMPLE SIMULATION (LAST PERIOD ONLY)
# ----------------------------
def make_score(fast, slow):

    def score(row):
        s = 0

        if row["close"] > row[f"ma_{slow.lower()}"] if f"ma_{slow.lower()}" in row else 0:
            s += 20

        return s

    return score


# NOTE: simplified fallback simulation
subset = df.tail(1000).copy()

subset["ret"] = subset.groupby("ticker")["close"].pct_change()

print("\n=== RECENT PERFORMANCE SNAPSHOT ===")
print(subset.groupby("ticker")["ret"].mean().sort_values(ascending=False).head(10))