import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine


engine = create_engine("sqlite:///data/prices.db")

ticker = "^OMXS30"

df = yf.download(
    ticker,
    start="2020-01-01",
    end="2025-01-01",
    auto_adjust=True,
    progress=False,
)

if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

df = df.reset_index()
df.columns = [col.lower() for col in df.columns]

df["ticker"] = ticker

df.to_sql(
    "market_index",
    engine,
    if_exists="replace",
    index=False,
)

print(f"Saved market index {ticker} -> {len(df)} rows")