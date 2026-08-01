import os
import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine


os.makedirs("data", exist_ok=True)

DB_PATH = "sqlite:///data/prices.db"
TICKERS_PATH = "data/tickers_sweden_expanded.csv"

engine = create_engine(DB_PATH)


def load_tickers(path=TICKERS_PATH):
    tickers_df = pd.read_csv(path)

    tickers = (
        tickers_df["ticker"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .tolist()
    )

    return tickers


def clean_df(df, ticker):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df.columns = [col.lower() for col in df.columns]

    df["ticker"] = ticker

    return df


def load_ticker(ticker):
    print(f"Processing {ticker}")

    df = yf.download(
        ticker,
        start="2020-01-01",
        end="2025-01-01",
        auto_adjust=True,
        progress=False,
    )

    if df.empty:
        print(f"No data for {ticker}")
        return

    df = clean_df(df, ticker)

    df.to_sql(
        "prices",
        engine,
        if_exists="append",
        index=False,
    )

    print(f"Saved {ticker} -> {len(df)} rows")


if __name__ == "__main__":

    tickers = load_tickers()

    print(f"Loaded {len(tickers)} tickers")

    # Important: rebuild raw prices table from scratch
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS prices")

    for ticker in tickers:
        load_ticker(ticker)

    print("\nDone.")