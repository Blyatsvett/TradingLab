from __future__ import annotations

import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine

from Intraday.core.paths import INTRADAY_DB
from Intraday.core.research_universe import RESEARCH_TICKERS_SWEDEN_LARGE_CAP


TABLE_NAME = "intraday_prices"

DOWNLOAD_PERIOD = "60d"
DOWNLOAD_INTERVAL = "5m"

# Research downloader universe.
# IMPORTANT:
# This does NOT change the production ORB strategy.
# Production ORB still uses ORB_ALLOWED_TICKERS from Intraday/core/orb_config.py.
TICKERS = RESEARCH_TICKERS_SWEDEN_LARGE_CAP


def clean_intraday(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    Normalize yfinance intraday output before saving to SQLite.

    Important:
    We keep the timestamp column named 'datetime' because existing ORB loaders
    expect intraday_prices.datetime.
    """

    output = df.copy()

    if isinstance(output.columns, pd.MultiIndex):
        output.columns = output.columns.get_level_values(0)

    output = output.reset_index()
    output.columns = [
        str(col).lower().strip().replace(" ", "_")
        for col in output.columns
    ]

    # yfinance normally gives 'datetime' for intraday data.
    # If it gives 'date', convert it to the legacy-compatible 'datetime'.
    if "date" in output.columns and "datetime" not in output.columns:
        output = output.rename(columns={"date": "datetime"})

    if "datetime" not in output.columns:
        raise ValueError(
            f"Could not find datetime column for {ticker}. "
            f"Columns found: {list(output.columns)}"
        )

    output["datetime"] = pd.to_datetime(output["datetime"], errors="coerce")
    output = output.dropna(subset=["datetime"])

    output["ticker"] = ticker

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for col in numeric_columns:
        if col in output.columns:
            output[col] = pd.to_numeric(output[col], errors="coerce")

    required_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ticker",
    ]

    for col in required_columns:
        if col not in output.columns:
            if col == "volume":
                output[col] = 0
            else:
                raise ValueError(f"Missing required column {col} for {ticker}")

    output = output[required_columns].copy()
    output = output.dropna(subset=["open", "high", "low", "close"])

    output = output.sort_values(["ticker", "datetime"]).reset_index(drop=True)

    return output


def download_ticker(ticker: str) -> pd.DataFrame:
    print(f"Downloading intraday data for {ticker}...")

    df = yf.download(
        ticker,
        period=DOWNLOAD_PERIOD,
        interval=DOWNLOAD_INTERVAL,
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if df.empty:
        print(f"WARNING: No intraday data returned for {ticker}")
        return pd.DataFrame()

    cleaned = clean_intraday(df, ticker)

    if cleaned.empty:
        print(f"WARNING: No valid cleaned rows for {ticker}")
        return pd.DataFrame()

    print(f"Downloaded {ticker}: {len(cleaned)} rows")

    return cleaned


def main() -> None:
    print("\n=== DOWNLOAD INTRADAY PRICES ===")
    print(f"Database: {INTRADAY_DB}")
    print(f"Table   : {TABLE_NAME}")
    print(f"Period  : {DOWNLOAD_PERIOD}")
    print(f"Interval: {DOWNLOAD_INTERVAL}")
    print(f"Tickers : {len(TICKERS)}")
    print("Universe: RESEARCH_TICKERS_SWEDEN_LARGE_CAP")
    print("Production ORB ticker config is NOT changed by this script.")

    engine = create_engine(f"sqlite:///{INTRADAY_DB}")

    all_frames = []
    successful_tickers = []
    failed_tickers = []

    for ticker in TICKERS:
        try:
            df = download_ticker(ticker)

            if df.empty:
                failed_tickers.append(ticker)
                continue

            all_frames.append(df)
            successful_tickers.append(ticker)

        except Exception as exc:
            failed_tickers.append(ticker)
            print(f"ERROR downloading {ticker}: {exc}")

    if not all_frames:
        raise RuntimeError(
            "No intraday data downloaded. Existing table was not replaced."
        )

    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined.sort_values(["ticker", "datetime"]).reset_index(drop=True)

    combined.to_sql(
        TABLE_NAME,
        engine,
        if_exists="replace",
        index=False,
    )

    first_datetime = combined["datetime"].min()
    last_datetime = combined["datetime"].max()

    print("\n=== DOWNLOAD SUMMARY ===")
    print(f"Rows saved          : {len(combined)}")
    print(f"Successful tickers  : {len(successful_tickers)}")
    print(f"Failed/empty tickers: {len(failed_tickers)}")
    print(f"First datetime      : {first_datetime}")
    print(f"Last datetime       : {last_datetime}")

    print("\nSuccessful tickers:")
    print(", ".join(successful_tickers))

    if failed_tickers:
        print("\nFailed/empty tickers:")
        print(", ".join(failed_tickers))

    print(f"\nSaved table -> {TABLE_NAME}")
    print("Done.")


if __name__ == "__main__":
    main()