from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from RegimeTrading.scripts.step9h_cross_sectional_holdout_transport import (
    HOLDOUT_DB,
    HOLDOUT_INSTRUMENTS,
    HOLDOUT_LOCK_VERSION,
)

LOCAL_TZ = ZoneInfo("Europe/Stockholm")


def _normalise_download(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker"])
    rows = []
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(map(str, raw.columns.get_level_values(0)))
        ticker_first = bool(level0.intersection(tickers))
        for ticker in tickers:
            try:
                frame = raw[ticker].copy() if ticker_first else raw.xs(ticker, axis=1, level=1).copy()
            except (KeyError, ValueError):
                continue
            frame.columns = [str(c).lower().replace(" ", "_") for c in frame.columns]
            frame["ticker"] = ticker
            rows.append(frame.reset_index())
    else:
        frame = raw.copy()
        frame.columns = [str(c).lower().replace(" ", "_") for c in frame.columns]
        frame["ticker"] = tickers[0]
        rows.append(frame.reset_index())
    if not rows:
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker"])
    out = pd.concat(rows, ignore_index=True)
    dt_col = next((c for c in out.columns if c.lower() in {"datetime", "date", "index"}), out.columns[0])
    out = out.rename(columns={dt_col: "datetime"})
    dt = pd.to_datetime(out["datetime"], errors="coerce", utc=True)
    out["datetime"] = dt.dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    for col in ["open", "high", "low", "close"]:
        out[col] = pd.to_numeric(out.get(col), errors="coerce")
    out = out.dropna(subset=["datetime", "ticker", "open", "high", "low", "close"])
    out = out[["datetime", "open", "high", "low", "close", "ticker"]].copy()
    out = out[out["datetime"].dt.strftime("%H:%M").between("09:00", "17:40")]
    out["datetime"] = out["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out.drop_duplicates(["ticker", "datetime"]).sort_values(["ticker", "datetime"])


def _upsert(db_path: Path, frame: pd.DataFrame) -> tuple[int, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS intraday_prices (
                datetime TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                ticker TEXT NOT NULL
            )
        """)
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_holdout_ticker_datetime ON intraday_prices(ticker, datetime)")
        before = int(con.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0])
        if not frame.empty:
            con.executemany(
                "INSERT OR REPLACE INTO intraday_prices(datetime, open, high, low, close, ticker) VALUES (?, ?, ?, ?, ?, ?)",
                list(frame.itertuples(index=False, name=None)),
            )
        con.commit()
        after = int(con.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0])
    return before, after


def collect(days: int = 59, interval: str = "5m", db_path: Path = HOLDOUT_DB) -> tuple[pd.DataFrame, int, int]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is not installed. Run .\\setup_regime_trading.ps1 after applying the Step 9H patch.") from exc
    try:
        import scipy  # noqa: F401 - required by yfinance when repair=True
    except ImportError as exc:
        raise RuntimeError(
            "scipy is required because the Step 9H collector calls yfinance with repair=True. "
            "Run .\\setup_regime_trading.ps1, or install the repair extra with "
            ".\\.venv\\Scripts\\python.exe -m pip install --upgrade \"yfinance[repair]>=1.5.1\"."
        ) from exc
    tickers = [row["ticker"] for row in HOLDOUT_INSTRUMENTS]
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
    before, after = _upsert(db_path, normalised)
    return normalised, before, after


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect research-only five-minute data for the locked Step 9H holdout universe.")
    parser.add_argument("--days", type=int, default=59)
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--db", type=Path, default=HOLDOUT_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print("\n=== STEP 9H HOLDOUT DATA COLLECTION ===")
    print(f"Universe lock : {HOLDOUT_LOCK_VERSION}")
    print(f"Tickers       : {len(HOLDOUT_INSTRUMENTS)}")
    print(f"Lookback days : {args.days}")
    print(f"Interval      : {args.interval}")
    print(f"Destination   : {args.db}")
    print("This database is separate from production and the original discovery database.")
    frame, before, after = collect(args.days, args.interval, args.db)
    print(f"Downloaded normalized rows : {len(frame)}")
    print(f"Database rows before/after : {before}/{after}")
    if frame.empty:
        print("No rows were returned. Review network access, ticker coverage, or Yahoo availability; the locked universe was not changed.")
    else:
        print(f"Observed tickers           : {frame['ticker'].nunique()}")
        print(f"First / last datetime      : {frame['datetime'].min()} / {frame['datetime'].max()}")
    print("Collection complete. Rerun .\\run_step9h_cross_sectional_holdout_transport.ps1.")


if __name__ == "__main__":
    main()
