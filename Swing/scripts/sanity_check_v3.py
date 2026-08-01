import sqlite3
import pandas as pd
from core.alpha_model import calculate_score


# -------------------------
# LOAD DATA
# -------------------------
conn = sqlite3.connect("data/prices.db")
df = pd.read_sql("SELECT * FROM prices_enriched", conn)
conn.close()

df["date"] = pd.to_datetime(df["date"])


# -------------------------
# SCORE (single source of truth)
# -------------------------
df["score"] = df.apply(calculate_score, axis=1)


# -------------------------
# 1. BASIC SANITY
# -------------------------
print("\n=== BASIC SANITY ===")
print(df[["score", "return"]].describe())


# -------------------------
# 2. CORRELATION (IC proxy)
# -------------------------
print("\n=== SIGNAL QUALITY ===")
print(df[["score", "return"]].corr())


# -------------------------
# 3. DECILE TEST (IMPORTANT)
# -------------------------
print("\n=== DECILE TEST ===")

df_clean = df.dropna(subset=["score", "return"])

df_clean["decile"] = df_clean.groupby("date")["score"].transform(
    lambda x: pd.qcut(x, 10, labels=False, duplicates="drop")
)

top = df_clean[df_clean["decile"] == 9]["return"].mean()
bottom = df_clean[df_clean["decile"] == 0]["return"].mean()

print(f"Top decile avg return: {top:.6f}")
print(f"Bottom decile avg return: {bottom:.6f}")
print(f"Spread: {top - bottom:.6f}")


# -------------------------
# 4. CROSS-SECTIONAL STABILITY
# -------------------------
print("\n=== DAILY IC ===")

daily_ic = df_clean.groupby("date").apply(
    lambda x: x["score"].corr(x["return"])
)

print(daily_ic.describe())

print("\nAvg IC:", daily_ic.mean())