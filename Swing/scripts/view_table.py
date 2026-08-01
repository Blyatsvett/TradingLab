import sqlite3
import pandas as pd

conn = sqlite3.connect("data/prices.db")

df = pd.read_sql("SELECT * FROM prices_enriched LIMIT 20", conn)

print(df)

conn.close()