import sqlite3
import pandas as pd


conn = sqlite3.connect("data/intraday_prices.db")
df = pd.read_sql("SELECT * FROM intraday_prices", conn)
conn.close()

df["datetime"] = pd.to_datetime(df["datetime"])
df["date"] = df["datetime"].dt.date
df["time"] = df["datetime"].dt.time

# Opening range: first 30 minutes, 09:00–09:30
opening_range = df[
    (df["datetime"].dt.time >= pd.to_datetime("09:00").time()) &
    (df["datetime"].dt.time <= pd.to_datetime("09:30").time())
]

orb = (
    opening_range
    .groupby(["ticker", "date"])
    .agg(
        opening_high=("high", "max"),
        opening_low=("low", "min"),
        opening_volume=("volume", "sum"),
    )
    .reset_index()
)

print("\n=== OPENING RANGE SAMPLE ===")
print(orb.head(20))

print("\nRows:", len(orb))
print("Tickers:", orb["ticker"].nunique())
print("Dates:", orb["date"].nunique())