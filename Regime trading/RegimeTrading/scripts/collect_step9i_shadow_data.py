from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from RegimeTrading.core.paths import SOURCE_INTRADAY_DB
from RegimeTrading.scripts.collect_step9h_holdout_data import _normalise_download
from RegimeTrading.scripts.step9b_baseline_trade_generation import GAP_RECOVERY_TICKERS
from RegimeTrading.scripts.step9h_cross_sectional_holdout_transport import (
    HOLDOUT_DB,
    HOLDOUT_INSTRUMENTS,
)
from RegimeTrading.scripts.step9i_prospective_shadow_router import (
    SHADOW_INTRADAY_DB,
    SHADOW_UNIVERSE_VERSION,
)


def shadow_tickers() -> list[str]:
    return list(dict.fromkeys(list(GAP_RECOVERY_TICKERS) + [row["ticker"] for row in HOLDOUT_INSTRUMENTS]))


def _ensure_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS intraday_prices (
            datetime TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            ticker TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'UNKNOWN',
            collected_at_utc TEXT NOT NULL DEFAULT ''
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(intraday_prices)")}
    if "source" not in columns:
        connection.execute("ALTER TABLE intraday_prices ADD COLUMN source TEXT NOT NULL DEFAULT 'UNKNOWN'")
    if "collected_at_utc" not in columns:
        connection.execute("ALTER TABLE intraday_prices ADD COLUMN collected_at_utc TEXT NOT NULL DEFAULT ''")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_step9i_ticker_datetime ON intraday_prices(ticker, datetime)"
    )


def _upsert(db_path: Path, frame: pd.DataFrame, source: str) -> tuple[int, int]:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    clean = frame.copy()
    if not clean.empty:
        clean = clean[["datetime", "open", "high", "low", "close", "ticker"]].copy()
        clean["source"] = source
        clean["collected_at_utc"] = stamp
    with closing(sqlite3.connect(db_path)) as con:
        _ensure_table(con)
        before = int(con.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0])
        if not clean.empty:
            con.executemany(
                """
                INSERT INTO intraday_prices(datetime, open, high, low, close, ticker, source, collected_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, datetime) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    source=excluded.source,
                    collected_at_utc=excluded.collected_at_utc
                """,
                list(clean.itertuples(index=False, name=None)),
            )
        con.commit()
        after = int(con.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0])
    return before, after


def _read_existing_db(path: Path, allowed_tickers: set[str]) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker"])
    with closing(sqlite3.connect(path)) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(intraday_prices)")}
        if not {"datetime", "open", "high", "low", "close", "ticker"}.issubset(columns):
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker"])
        frame = pd.read_sql_query(
            "SELECT datetime, open, high, low, close, ticker FROM intraday_prices",
            con,
        )
    if frame.empty:
        return frame
    frame["ticker"] = frame["ticker"].astype(str).str.strip()
    return frame[frame["ticker"].isin(allowed_tickers)].copy()


def bootstrap_from_existing(
    db_path: Path = SHADOW_INTRADAY_DB,
    source_db: Path = SOURCE_INTRADAY_DB,
    holdout_db: Path = HOLDOUT_DB,
) -> dict[str, int]:
    regime_set = set(GAP_RECOVERY_TICKERS)
    holdout_set = {row["ticker"] for row in HOLDOUT_INSTRUMENTS}
    regime = _read_existing_db(source_db, regime_set)
    holdout = _read_existing_db(holdout_db, holdout_set)
    counts = {"regime_rows": len(regime), "holdout_rows": len(holdout)}
    if not regime.empty:
        _upsert(db_path, regime, "BOOTSTRAP_ORIGINAL_SOURCE_DB")
    if not holdout.empty:
        _upsert(db_path, holdout, "BOOTSTRAP_STEP9H_HOLDOUT_DB")
    return counts


def collect(
    days: int = 5,
    interval: str = "5m",
    db_path: Path = SHADOW_INTRADAY_DB,
    bootstrap: bool = True,
) -> tuple[pd.DataFrame, int, int, dict[str, int]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is not installed. Run .\\setup_regime_trading.ps1.") from exc
    try:
        import scipy  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "scipy is required because the shadow collector uses yfinance repair=True. "
            "Run .\\setup_regime_trading.ps1."
        ) from exc

    bootstrap_counts = bootstrap_from_existing(db_path) if bootstrap else {"regime_rows": 0, "holdout_rows": 0}
    tickers = shadow_tickers()
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=int(days))
    raw = yf.download(
        tickers=tickers,
        start=start.isoformat(),
        end=end.isoformat(),
        interval=interval,
        group_by="ticker",
        auto_adjust=False,
        actions=False,
        prepost=False,
        repair=True,
        threads=True,
        progress=True,
        timeout=30,
    )
    normalised = _normalise_download(raw, tickers)
    before, after = _upsert(db_path, normalised, "YAHOO_YFINANCE_REPAIR")
    return normalised, before, after, bootstrap_counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect five-minute bars for the Step 9I prospective shadow universe.")
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--db", type=Path, default=SHADOW_INTRADAY_DB)
    parser.add_argument("--skip-bootstrap", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = shadow_tickers()
    print("\n=== STEP 9I SHADOW DATA COLLECTION ===")
    print(f"Universe version : {SHADOW_UNIVERSE_VERSION}")
    print(f"Tickers          : {len(tickers)} ({len(GAP_RECOVERY_TICKERS)} regime-source + {len(HOLDOUT_INSTRUMENTS)} holdout)")
    print(f"Lookback days    : {args.days}")
    print(f"Destination      : {args.db}")
    print("The Step 9H database and production source database are read-only inputs; this collector writes only to Step 9I.")
    frame, before, after, boot = collect(args.days, args.interval, args.db, not args.skip_bootstrap)
    print(f"Bootstrapped rows: regime={boot['regime_rows']}, holdout={boot['holdout_rows']}")
    print(f"Downloaded rows : {len(frame)}")
    print(f"DB rows before/after Yahoo upsert: {before}/{after}")
    if frame.empty:
        print("Yahoo returned no rows. Existing bootstrapped bars remain available; no ledger was changed.")
    else:
        print(f"Observed tickers : {frame['ticker'].nunique()}/{len(tickers)}")
        print(f"First / last     : {frame['datetime'].min()} / {frame['datetime'].max()}")
    print("Collection complete. Morning decisions are sealed separately by .\\run_step9i_morning_shadow_router.ps1.")


if __name__ == "__main__":
    main()
