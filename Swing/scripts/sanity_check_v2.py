import sqlite3
import pandas as pd

from core.alpha_model import calculate_score

df["score"] = df.apply(calculate_score, axis=1)


conn = sqlite3.connect("data/prices.db")
df = pd.read_sql("SELECT * FROM prices_enriched", conn)
conn.close()

# compute score (IMPORTANT FIX)
df["score"] = df.apply(calculate_score, axis=1)

# forward-looking test
top = df.groupby("date").apply(
    lambda x: x.nlargest(3, "score")["return"].mean()
).mean()

bottom = df.groupby("date").apply(
    lambda x: x.nsmallest(3, "score")["return"].mean()
).mean()

print("\n=== SANITY CHECK V2 ===")
print("Top avg return:", top)
print("Bottom avg return:", bottom)