import sqlite3
import pandas as pd

db_path = "data/prices.db"

conn = sqlite3.connect(db_path)

# 1. Check total rows
total_rows = pd.read_sql("SELECT COUNT(*) as count FROM prices", conn)
print("\nTOTAL ROWS:")
print(total_rows)

# 2. Check which tickers exist
tickers = pd.read_sql("""
SELECT ticker, COUNT(*) as rows
FROM prices
GROUP BY ticker
ORDER BY rows DESC
""", conn)

print("\nTICKERS IN DATABASE:")
print(tickers)

# 3. Preview data
preview = pd.read_sql("""
SELECT *
FROM prices
LIMIT 5
""", conn)

print("\nSAMPLE DATA:")
print(preview)

conn.close()