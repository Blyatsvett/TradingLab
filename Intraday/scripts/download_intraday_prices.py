import os
import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine
from Intraday.core.paths import INTRADAY_DB

engine = create_engine(f"sqlite:///{INTRADAY_DB}")

# Clear old intraday table once before reloading
with engine.connect() as conn:
    conn.exec_driver_sql("DROP TABLE IF EXISTS intraday_prices")

tickers = [
    "ABB.ST",
    "ALFA.ST",
    "ASSA-B.ST",
    "ATCO-A.ST",
    "ERIC-B.ST",
    "EVO.ST",
    "INVE-B.ST",
    "SEB-A.ST",
    "SHB-A.ST",
    "VOLV-B.ST",
]


def clean_intraday(df, ticker):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df.columns = [col.lower() for col in df.columns]

    df["ticker"] = ticker

    return df


for ticker in tickers:
    print(f"Downloading intraday data for {ticker}...")

    df = yf.download(
        ticker,
        period="60d",
        interval="5m",
        auto_adjust=True,
        progress=False,
    )

    if df.empty:
        print(f"No intraday data for {ticker}")
        continue

    df = clean_intraday(df, ticker)

    df.to_sql(
        "intraday_prices",
        engine,
        if_exists="append",
        index=False,
    )

    print(f"Saved {ticker}: {len(df)} rows")

print("\nDone.")