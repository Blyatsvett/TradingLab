"""Validated access to canonical Swing market data."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd

from core.config import DEFAULT_DB_PATH


REQUIRED_PRICE_COLUMNS = {"date", "ticker", "open", "high", "low", "close", "volume"}


def load_price_history(
    db_path: str | Path = DEFAULT_DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Load adjusted daily OHLCV from the raw ``prices`` table.

    The canonical pipeline intentionally avoids ``prices_enriched`` because that
    table mixes predictors with future-return target columns.
    """

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Price database not found: {path}")

    with sqlite3.connect(path) as connection:
        frame = pd.read_sql_query("SELECT * FROM prices", connection)

    missing = REQUIRED_PRICE_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"prices table is missing columns: {sorted(missing)}")

    frame = frame.loc[:, sorted(REQUIRED_PRICE_COLUMNS)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()

    numeric_columns = ["open", "high", "low", "close", "volume"]
    frame[numeric_columns] = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")

    if start_date:
        frame = frame[frame["date"] >= pd.Timestamp(start_date)]
    if end_date:
        frame = frame[frame["date"] <= pd.Timestamp(end_date)]

    frame = frame.sort_values(["ticker", "date"]).reset_index(drop=True)
    return frame


def validate_price_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a compact data-quality table and raise on structural failures."""

    missing = REQUIRED_PRICE_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"price frame is missing columns: {sorted(missing)}")

    duplicate_count = int(frame.duplicated(["date", "ticker"]).sum())
    null_ohlcv = int(frame[["open", "high", "low", "close", "volume"]].isna().sum().sum())
    nonpositive_prices = int((frame[["open", "high", "low", "close"]] <= 0).sum().sum())
    invalid_high = int((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).sum())
    invalid_low = int((frame["low"] > frame[["open", "close", "high"]].min(axis=1)).sum())

    report = pd.DataFrame(
        [
            {"check": "rows", "value": len(frame), "status": "info"},
            {"check": "tickers", "value": frame["ticker"].nunique(), "status": "info"},
            {"check": "first_date", "value": frame["date"].min(), "status": "info"},
            {"check": "last_date", "value": frame["date"].max(), "status": "info"},
            {"check": "duplicate_ticker_dates", "value": duplicate_count, "status": "pass" if duplicate_count == 0 else "fail"},
            {"check": "null_ohlcv_values", "value": null_ohlcv, "status": "pass" if null_ohlcv == 0 else "fail"},
            {"check": "nonpositive_prices", "value": nonpositive_prices, "status": "pass" if nonpositive_prices == 0 else "fail"},
            {"check": "invalid_high_rows", "value": invalid_high, "status": "pass" if invalid_high == 0 else "warning"},
            {"check": "invalid_low_rows", "value": invalid_low, "status": "pass" if invalid_low == 0 else "warning"},
        ]
    )

    hard_failures = report[report["status"] == "fail"]
    if not hard_failures.empty:
        details = hard_failures[["check", "value"]].to_dict("records")
        raise ValueError(f"Price data failed structural validation: {details}")

    return report
