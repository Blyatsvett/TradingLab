from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from RegimeTrading.core.nasdaq_config import (
    INSTRUMENT_BY_TICKER,
    NASDAQ_5M_BARS_LATEST_CSV,
    NASDAQ_COLLECTION_STATUS_CSV,
    NASDAQ_FORWARD_DB,
    NASDAQ_INSTRUMENT_COVERAGE_CSV,
    NASDAQ_YAHOO_BAR_COMPARISON_CSV,
    NASDAQ_YAHOO_OR_COMPARISON_CSV,
    PRIMARY_BAR_MODE,
)
from RegimeTrading.core.nasdaq_database import connect_database, initialize_database
from RegimeTrading.core.paths import INTRADAY_DB


OHLC_COLUMNS = ["open", "high", "low", "close"]
OPENING_RANGE_START = "09:30"
OPENING_RANGE_END = "09:35"


def now_utc_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_csv(path, columns: list[str]) -> None:
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def load_nasdaq_bars(connection: sqlite3.Connection) -> pd.DataFrame:
    bars = pd.read_sql_query(
        """
        SELECT ticker, datetime, date, open, high, low, close,
               volume, trade_count, first_trade_time, last_trade_time,
               source_mode
        FROM nasdaq_5m_bars
        WHERE source_mode = ?
        ORDER BY ticker, datetime
        """,
        connection,
        params=[PRIMARY_BAR_MODE],
    )
    if bars.empty:
        return bars
    bars["datetime"] = pd.to_datetime(bars["datetime"], errors="coerce")
    for column in [*OHLC_COLUMNS, "volume", "trade_count"]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    return bars.dropna(subset=["ticker", "datetime", *OHLC_COLUMNS])


def load_yahoo_bars(
    minimum_datetime: pd.Timestamp,
    maximum_datetime: pd.Timestamp,
) -> pd.DataFrame:
    if not INTRADAY_DB.exists():
        raise FileNotFoundError(
            f"Yahoo/local intraday database does not exist: {INTRADAY_DB}. "
            "Run sync_intraday_database first."
        )

    query = """
        SELECT ticker, datetime, open, high, low, close, volume
        FROM intraday_prices
        WHERE datetime >= ? AND datetime <= ?
    """
    with closing(sqlite3.connect(INTRADAY_DB)) as connection:
        yahoo = pd.read_sql_query(
            query,
            connection,
            params=[
                minimum_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                maximum_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            ],
        )

    if yahoo.empty:
        return yahoo
    yahoo["datetime"] = pd.to_datetime(yahoo["datetime"], errors="coerce").dt.floor(
        "5min"
    )
    for column in [*OHLC_COLUMNS, "volume"]:
        yahoo[column] = pd.to_numeric(yahoo[column], errors="coerce")
    yahoo = yahoo.dropna(subset=["ticker", "datetime", *OHLC_COLUMNS])
    yahoo = (
        yahoo.sort_values(["ticker", "datetime"])
        .drop_duplicates(["ticker", "datetime"], keep="last")
        .reset_index(drop=True)
    )
    return yahoo


def build_bar_comparison(
    nasdaq: pd.DataFrame,
    yahoo: pd.DataFrame,
) -> pd.DataFrame:
    nasdaq_names = {
        column: f"nasdaq_{column}"
        for column in [*OHLC_COLUMNS, "volume", "trade_count"]
    }
    yahoo_names = {
        column: f"yahoo_{column}" for column in [*OHLC_COLUMNS, "volume"]
    }

    left = nasdaq[
        ["ticker", "datetime", *nasdaq_names.keys()]
    ].rename(columns=nasdaq_names)
    right = yahoo[["ticker", "datetime", *yahoo_names.keys()]].rename(
        columns=yahoo_names
    )
    comparison = left.merge(right, on=["ticker", "datetime"], how="outer")
    comparison["date"] = comparison["datetime"].dt.strftime("%Y-%m-%d")
    comparison["time"] = comparison["datetime"].dt.strftime("%H:%M")
    comparison["has_nasdaq_bar"] = comparison["nasdaq_close"].notna()
    comparison["has_yahoo_bar"] = comparison["yahoo_close"].notna()
    comparison["has_both"] = (
        comparison["has_nasdaq_bar"] & comparison["has_yahoo_bar"]
    )

    for column in OHLC_COLUMNS:
        comparison[f"{column}_abs_diff"] = (
            comparison[f"nasdaq_{column}"] - comparison[f"yahoo_{column}"]
        )
        comparison[f"{column}_diff_bps"] = np.where(
            comparison[f"yahoo_{column}"].notna()
            & comparison[f"yahoo_{column}"].ne(0),
            (
                comparison[f"nasdaq_{column}"]
                / comparison[f"yahoo_{column}"]
                - 1.0
            )
            * 10000.0,
            np.nan,
        )

    comparison["max_abs_ohlc_diff_bps"] = comparison[
        [f"{column}_diff_bps" for column in OHLC_COLUMNS]
    ].abs().max(axis=1)
    comparison["ohlc_within_1bp"] = comparison["has_both"] & comparison[
        "max_abs_ohlc_diff_bps"
    ].le(1.0)
    comparison["ohlc_within_5bps"] = comparison["has_both"] & comparison[
        "max_abs_ohlc_diff_bps"
    ].le(5.0)
    comparison["volume_diff"] = (
        comparison["nasdaq_volume"] - comparison["yahoo_volume"]
    )
    comparison["generated_at_utc"] = now_utc_text()
    return comparison.sort_values(["datetime", "ticker"]).reset_index(drop=True)


def opening_range_table(
    bars: pd.DataFrame,
    prefix: str,
) -> pd.DataFrame:
    if bars.empty:
        return pd.DataFrame()
    working = bars.copy()
    working["date"] = working["datetime"].dt.strftime("%Y-%m-%d")
    working["clock"] = working["datetime"].dt.strftime("%H:%M")
    working = working[
        working["clock"].ge(OPENING_RANGE_START)
        & working["clock"].lt(OPENING_RANGE_END)
    ].copy()
    if working.empty:
        return pd.DataFrame()

    grouped = working.groupby(["ticker", "date"], as_index=False).agg(
        opening_range_high=("high", "max"),
        opening_range_low=("low", "min"),
        opening_range_bar_count=("datetime", "nunique"),
    )
    return grouped.rename(
        columns={
            "opening_range_high": f"{prefix}_opening_range_high",
            "opening_range_low": f"{prefix}_opening_range_low",
            "opening_range_bar_count": f"{prefix}_opening_range_bar_count",
        }
    )


def build_opening_range_comparison(
    nasdaq: pd.DataFrame,
    yahoo: pd.DataFrame,
) -> pd.DataFrame:
    nasdaq_or = opening_range_table(nasdaq, "nasdaq")
    yahoo_or = opening_range_table(yahoo, "yahoo")
    if nasdaq_or.empty and yahoo_or.empty:
        return pd.DataFrame()

    comparison = nasdaq_or.merge(yahoo_or, on=["ticker", "date"], how="outer")
    comparison["has_both"] = comparison["nasdaq_opening_range_high"].notna() & (
        comparison["yahoo_opening_range_high"].notna()
    )
    for side in ["high", "low"]:
        nasdaq_column = f"nasdaq_opening_range_{side}"
        yahoo_column = f"yahoo_opening_range_{side}"
        comparison[f"opening_range_{side}_abs_diff"] = (
            comparison[nasdaq_column] - comparison[yahoo_column]
        )
        comparison[f"opening_range_{side}_diff_bps"] = np.where(
            comparison[yahoo_column].notna() & comparison[yahoo_column].ne(0),
            (comparison[nasdaq_column] / comparison[yahoo_column] - 1.0)
            * 10000.0,
            np.nan,
        )
    comparison["generated_at_utc"] = now_utc_text()
    return comparison.sort_values(["date", "ticker"]).reset_index(drop=True)


def build_coverage(
    connection: sqlite3.Connection,
    nasdaq: pd.DataFrame,
    comparison: pd.DataFrame,
) -> pd.DataFrame:
    trade_counts = pd.read_sql_query(
        """
        SELECT ticker,
               COUNT(*) AS selected_trade_rows,
               SUM(is_primary_lit) AS primary_lit_trade_rows,
               MIN(trade_time_stockholm) AS first_trade_time_stockholm,
               MAX(trade_time_stockholm) AS last_trade_time_stockholm
        FROM nasdaq_trades
        GROUP BY ticker
        """,
        connection,
    )

    rows: list[dict] = []
    for ticker, instrument in INSTRUMENT_BY_TICKER.items():
        ticker_bars = nasdaq[nasdaq["ticker"].eq(ticker)]
        ticker_comparison = comparison[comparison["ticker"].eq(ticker)]
        both = ticker_comparison[ticker_comparison["has_both"]]
        trade_row = trade_counts[trade_counts["ticker"].eq(ticker)]

        nasdaq_bar_count = int(ticker_comparison["has_nasdaq_bar"].sum())
        yahoo_bar_count = int(ticker_comparison["has_yahoo_bar"].sum())
        overlap_count = int(ticker_comparison["has_both"].sum())
        rows.append(
            {
                "ticker": ticker,
                "isin": instrument.isin,
                "company_name": instrument.company_name,
                "sector_group": instrument.sector_group,
                "selected_trade_rows": (
                    int(trade_row.iloc[0]["selected_trade_rows"])
                    if not trade_row.empty
                    else 0
                ),
                "primary_lit_trade_rows": (
                    int(trade_row.iloc[0]["primary_lit_trade_rows"] or 0)
                    if not trade_row.empty
                    else 0
                ),
                "nasdaq_5m_bars": nasdaq_bar_count,
                "yahoo_5m_bars_in_nasdaq_window": yahoo_bar_count,
                "overlapping_5m_bars": overlap_count,
                "nasdaq_bar_overlap_rate": (
                    overlap_count / nasdaq_bar_count if nasdaq_bar_count else np.nan
                ),
                "ohlc_within_1bp_rate": (
                    float(both["ohlc_within_1bp"].mean()) if not both.empty else np.nan
                ),
                "ohlc_within_5bps_rate": (
                    float(both["ohlc_within_5bps"].mean()) if not both.empty else np.nan
                ),
                "mean_abs_close_diff_bps": (
                    float(both["close_diff_bps"].abs().mean())
                    if not both.empty
                    else np.nan
                ),
                "first_nasdaq_bar": (
                    ticker_bars["datetime"].min() if not ticker_bars.empty else pd.NaT
                ),
                "last_nasdaq_bar": (
                    ticker_bars["datetime"].max() if not ticker_bars.empty else pd.NaT
                ),
                "first_trade_time_stockholm": (
                    trade_row.iloc[0]["first_trade_time_stockholm"]
                    if not trade_row.empty
                    else ""
                ),
                "last_trade_time_stockholm": (
                    trade_row.iloc[0]["last_trade_time_stockholm"]
                    if not trade_row.empty
                    else ""
                ),
                "generated_at_utc": now_utc_text(),
            }
        )
    return pd.DataFrame(rows)


def export_collection_status(connection: sqlite3.Connection) -> None:
    status = pd.read_sql_query(
        """
        SELECT *
        FROM collection_runs
        ORDER BY started_at_utc DESC
        LIMIT 25
        """,
        connection,
    )
    status.to_csv(NASDAQ_COLLECTION_STATUS_CSV, index=False)


def main() -> None:
    initialize_database(NASDAQ_FORWARD_DB)

    print("\n=== COMPARE NASDAQ AND YAHOO FIVE-MINUTE DATA ===")
    print(f"Nasdaq database : {NASDAQ_FORWARD_DB}")
    print(f"Yahoo database  : {INTRADAY_DB}")
    print("V1 research input remains unchanged.")

    with closing(connect_database(NASDAQ_FORWARD_DB)) as connection:
        nasdaq = load_nasdaq_bars(connection)
        export_collection_status(connection)

        if nasdaq.empty:
            print("No Nasdaq five-minute bars exist yet.")
            empty_csv(
                NASDAQ_INSTRUMENT_COVERAGE_CSV,
                ["ticker", "isin", "nasdaq_5m_bars", "generated_at_utc"],
            )
            empty_csv(
                NASDAQ_YAHOO_BAR_COMPARISON_CSV,
                ["ticker", "datetime", "has_nasdaq_bar", "has_yahoo_bar"],
            )
            empty_csv(
                NASDAQ_YAHOO_OR_COMPARISON_CSV,
                ["ticker", "date", "has_both"],
            )
            empty_csv(NASDAQ_5M_BARS_LATEST_CSV, list(nasdaq.columns))
            return

        minimum_datetime = nasdaq["datetime"].min() - pd.Timedelta(minutes=5)
        maximum_datetime = nasdaq["datetime"].max() + pd.Timedelta(minutes=5)
        yahoo = load_yahoo_bars(minimum_datetime, maximum_datetime)

        comparison = build_bar_comparison(nasdaq, yahoo)
        opening_range = build_opening_range_comparison(nasdaq, yahoo)
        coverage = build_coverage(connection, nasdaq, comparison)

        latest_date = nasdaq["date"].max()
        latest_bars = nasdaq[nasdaq["date"].eq(latest_date)].copy()

        comparison.to_csv(NASDAQ_YAHOO_BAR_COMPARISON_CSV, index=False)
        opening_range.to_csv(NASDAQ_YAHOO_OR_COMPARISON_CSV, index=False)
        coverage.to_csv(NASDAQ_INSTRUMENT_COVERAGE_CSV, index=False)
        latest_bars.to_csv(NASDAQ_5M_BARS_LATEST_CSV, index=False)

    print(f"Nasdaq bars         : {len(nasdaq)}")
    print(f"Yahoo bars in range : {len(yahoo)}")
    print(f"Overlapping bars    : {int(comparison['has_both'].sum())}")
    print(f"Latest Nasdaq date  : {latest_date}")
    print(f"Saved -> {NASDAQ_COLLECTION_STATUS_CSV.name}")
    print(f"Saved -> {NASDAQ_INSTRUMENT_COVERAGE_CSV.name}")
    print(f"Saved -> {NASDAQ_5M_BARS_LATEST_CSV.name}")
    print(f"Saved -> {NASDAQ_YAHOO_BAR_COMPARISON_CSV.name}")
    print(f"Saved -> {NASDAQ_YAHOO_OR_COMPARISON_CSV.name}")


if __name__ == "__main__":
    main()
