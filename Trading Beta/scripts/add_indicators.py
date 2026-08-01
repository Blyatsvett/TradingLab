import sqlite3
import pandas as pd


# ----------------------------
# LOAD DATA
# ----------------------------
conn = sqlite3.connect("data/prices.db")

df = pd.read_sql("SELECT * FROM prices", conn)

df["date"] = pd.to_datetime(df["date"])
df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()

df = df.sort_values(["ticker", "date"])

# ----------------------------
# SMA GRID
# ----------------------------
for n in range(5, 201, 5):
    df[f"sma{n}"] = df.groupby("ticker")["close"].transform(
        lambda x: x.rolling(n).mean()
    )

# ----------------------------
# BASIC RETURNS
# ----------------------------
df["return"] = df.groupby("ticker")["close"].pct_change()

df["prev_close"] = df.groupby("ticker")["close"].shift(1)

df["gap"] = (
    df["open"] / df["prev_close"] - 1
)

# ----------------------------
# EXECUTION REALISM FEATURES
# ----------------------------
df["next_open"] = df.groupby("ticker")["open"].shift(-1)

df["overnight_return"] = (
    df["next_open"] / df["close"] - 1
)

df["intraday_return"] = (
    df["close"] / df["open"] - 1
)

# ----------------------------
# VOLATILITY
# ----------------------------
df["volatility"] = df.groupby("ticker")["return"].transform(
    lambda x: x.rolling(20).std()
)

df["volume_sma20"] = df.groupby("ticker")["volume"].transform(
    lambda x: x.rolling(20).mean()
)

df["volume_ratio"] = df["volume"] / df["volume_sma20"]

# ----------------------------
# REGIME DETECTION
# ----------------------------
df["trend_20"] = df.groupby("ticker")["close"].transform(
    lambda x: x.pct_change(20)
)


def regime(x):
    if pd.isna(x):
        return "sideways"
    elif x > 0.03:
        return "bull"
    elif x < -0.03:
        return "bear"
    else:
        return "sideways"


df["regime"] = df["trend_20"].apply(regime)

# ----------------------------
# CLEANUP
# ----------------------------
df = df.drop(columns=["trend_20"])

# ----------------------------
# SAVE TO SQLITE
# ----------------------------
df.to_sql(
    "prices_enriched",
    conn,
    if_exists="replace",
    index=False,
)

conn.close()

print("✅ add_indicators complete → prices_enriched rebuilt")