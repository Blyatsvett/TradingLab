from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from RegimeTrading.core.nasdaq_config import NASDAQ_INSTRUMENTS


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.row_factory = sqlite3.Row
    return connection


def ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    existing = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name not in existing:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


def initialize_database(path: Path) -> None:
    with closing(connect_database(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS instrument_map (
                ticker TEXT PRIMARY KEY,
                isin TEXT NOT NULL UNIQUE,
                company_name TEXT NOT NULL,
                sector_group TEXT NOT NULL,
                primary_mic TEXT NOT NULL,
                currency TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS collection_runs (
                run_id TEXT PRIMARY KEY,
                started_at_utc TEXT NOT NULL,
                finished_at_utc TEXT,
                status TEXT NOT NULL,
                discovered_reports INTEGER NOT NULL DEFAULT 0,
                already_processed_reports INTEGER NOT NULL DEFAULT 0,
                attempted_reports INTEGER NOT NULL DEFAULT 0,
                processed_reports INTEGER NOT NULL DEFAULT 0,
                no_data_reports INTEGER NOT NULL DEFAULT 0,
                failed_reports INTEGER NOT NULL DEFAULT 0,
                rows_read INTEGER NOT NULL DEFAULT 0,
                selected_rows INTEGER NOT NULL DEFAULT 0,
                primary_lit_rows INTEGER NOT NULL DEFAULT 0,
                inserted_trades INTEGER NOT NULL DEFAULT 0,
                rebuilt_bars INTEGER NOT NULL DEFAULT 0,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS downloaded_reports (
                report_id TEXT PRIMARY KEY,
                report_url TEXT,
                report_time_stockholm TEXT,
                source_filename TEXT,
                archive_path TEXT,
                file_sha256 TEXT,
                file_size_bytes INTEGER,
                rows_in_file INTEGER NOT NULL DEFAULT 0,
                selected_rows INTEGER NOT NULL DEFAULT 0,
                primary_lit_rows INTEGER NOT NULL DEFAULT 0,
                inserted_trades INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                downloaded_at_utc TEXT,
                processed_at_utc TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS nasdaq_trades (
                trade_key TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                isin TEXT NOT NULL,
                trade_time_utc TEXT NOT NULL,
                trade_time_stockholm TEXT NOT NULL,
                trade_date_stockholm TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                price_currency TEXT,
                price_notation TEXT,
                venue_execution TEXT,
                trading_system TEXT,
                publication_time_utc TEXT,
                venue_publication TEXT,
                transaction_id TEXT,
                flags TEXT,
                is_primary_lit INTEGER NOT NULL,
                source_filename TEXT NOT NULL,
                inserted_at_utc TEXT NOT NULL,
                FOREIGN KEY (report_id) REFERENCES downloaded_reports(report_id)
            );

            CREATE INDEX IF NOT EXISTS idx_nasdaq_trades_ticker_time
                ON nasdaq_trades(ticker, trade_time_stockholm);
            CREATE INDEX IF NOT EXISTS idx_nasdaq_trades_date
                ON nasdaq_trades(trade_date_stockholm);
            CREATE INDEX IF NOT EXISTS idx_nasdaq_trades_primary
                ON nasdaq_trades(is_primary_lit, ticker, trade_time_stockholm);

            CREATE TABLE IF NOT EXISTS nasdaq_5m_bars (
                ticker TEXT NOT NULL,
                datetime TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                trade_count INTEGER NOT NULL,
                first_trade_time TEXT NOT NULL,
                last_trade_time TEXT NOT NULL,
                source_mode TEXT NOT NULL,
                rebuilt_at_utc TEXT NOT NULL,
                PRIMARY KEY (ticker, datetime, source_mode)
            );

            CREATE INDEX IF NOT EXISTS idx_nasdaq_bars_date
                ON nasdaq_5m_bars(date, source_mode);
            """
        )

        # Existing databases created by collector V1 need an in-place schema
        # migration. Empty/no-trade Nasdaq minute reports are expected around
        # pre-open periods and should not be counted as failures.
        ensure_column(
            connection,
            "collection_runs",
            "no_data_reports",
            "INTEGER NOT NULL DEFAULT 0",
        )

        updated_at = utc_now_text()
        connection.executemany(
            """
            INSERT INTO instrument_map (
                ticker, isin, company_name, sector_group,
                primary_mic, currency, active, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                isin=excluded.isin,
                company_name=excluded.company_name,
                sector_group=excluded.sector_group,
                primary_mic=excluded.primary_mic,
                currency=excluded.currency,
                active=1,
                updated_at_utc=excluded.updated_at_utc
            """,
            [
                (
                    item.ticker,
                    item.isin,
                    item.company_name,
                    item.sector_group,
                    item.primary_mic,
                    item.currency,
                    updated_at,
                )
                for item in NASDAQ_INSTRUMENTS
            ],
        )
        connection.commit()
