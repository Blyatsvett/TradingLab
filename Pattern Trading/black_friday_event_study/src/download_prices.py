from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

from .database import write_table
from .settings import (
    BENCHMARK_TICKERS,
    COMPANIES_CSV,
    DOWNLOAD_END,
    DOWNLOAD_START,
    RAW_DIR,
)


def _download_one(ticker: str, retries: int = 3) -> pd.DataFrame:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            df = yf.download(
                ticker,
                start=DOWNLOAD_START,
                end=DOWNLOAD_END,
                auto_adjust=True,
                actions=False,
                progress=False,
                threads=False,
            )

            if df.empty:
                raise ValueError(f"No price data returned for {ticker}")

            # Some yfinance versions return a MultiIndex even for one ticker.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if "Close" not in df.columns:
                raise ValueError(f"'Close' column missing for {ticker}")

            result = (
                df[["Close"]]
                .rename(columns={"Close": "adjusted_close"})
                .reset_index()
                .rename(columns={"Date": "date"})
            )

            result["ticker"] = ticker
            result["date"] = pd.to_datetime(result["date"]).dt.tz_localize(None)

            return result[["ticker", "date", "adjusted_close"]]

        except Exception as exc:
            last_error = exc

            if attempt < retries:
                time.sleep(2 * attempt)

    raise RuntimeError(f"Failed to download {ticker}: {last_error}")


def download_all_prices() -> pd.DataFrame:
    companies = pd.read_csv(COMPANIES_CSV)

    tickers = sorted(
        set(companies["ticker"]).union(set(BENCHMARK_TICKERS))
    )

    frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []

    for index, ticker in enumerate(tickers, start=1):
        print(f"[{index}/{len(tickers)}] Downloading {ticker}")

        try:
            frames.append(_download_one(ticker))

        except Exception as exc:
            print(f"  WARNING: {exc}")
            failures.append(
                {
                    "ticker": ticker,
                    "error": str(exc),
                }
            )

    if not frames:
        raise RuntimeError("No price data was downloaded.")

    prices = pd.concat(frames, ignore_index=True)

    prices = (
        prices
        .sort_values(["ticker", "date"])
        .drop_duplicates(["ticker", "date"])
    )

    prices["daily_return"] = (
        prices
        .groupby("ticker")["adjusted_close"]
        .pct_change()
    )

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    prices.to_csv(
        RAW_DIR / "daily_prices.csv",
        index=False,
    )

    write_table(prices, "daily_prices")

    failures_df = pd.DataFrame(
        failures,
        columns=["ticker", "error"],
    )

    failures_df.to_csv(
        RAW_DIR / "download_failures.csv",
        index=False,
    )

    write_table(failures_df, "download_failures")

    return prices