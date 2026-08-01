import sqlite3
import pandas as pd

conn = sqlite3.connect("data/prices.db")
df = pd.read_sql("SELECT * FROM prices_enriched", conn)
conn.close()

from core.alpha_model import calculate_score

df["score"] = df.apply(calculate_score, axis=1)

print(df["score"].describe())
print(df[['score', 'return']].corr())