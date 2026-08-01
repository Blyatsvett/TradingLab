from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from RegimeTrading.core.nasdaq_config import (
    INSTRUMENT_BY_ISIN,
    NASDAQ_ARCHIVE_DIR,
    NASDAQ_FORWARD_DB,
    NASDAQ_INCOMING_DIR,
    NASDAQ_PROBE_DIR,
    POST_TRADE_PAGE,
    PRIMARY_BAR_MODE,
    PRIMARY_CURRENCY,
    PRIMARY_MIC,
    PRIMARY_PRICE_NOTATION,
    PRIMARY_TRADING_SYSTEM,
    REPORT_PREFIX,
    STOCKHOLM_TIMEZONE,
    ensure_nasdaq_directories,
)
from RegimeTrading.core.nasdaq_database import (
    connect_database,
    initialize_database,
    utc_now_text,
)

class NasdaqNoDataReport(RuntimeError):
    """A valid report identifier whose payload contains no trade table."""


def _decode_report_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if not raw or not raw.strip():
        raise NasdaqNoDataReport("Empty Nasdaq report payload.")

    for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1", errors="replace"), "latin1"


def _meaningful_report_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _strip_sep_declaration(value: str) -> str:
    declaration = value.lstrip("\ufeff").strip()
    if (
        len(declaration) >= 2
        and declaration[0] == declaration[-1]
        and declaration[0] in {"\"", "'"}
    ):
        declaration = declaration[1:-1].strip()
    return declaration


def read_nasdaq_csv(path: Path) -> pd.DataFrame:
    """Parse Nasdaq CSV files and identify legitimate empty reports."""
    text, preferred_encoding = _decode_report_text(path)
    lines = _meaningful_report_lines(text)
    if not lines:
        raise NasdaqNoDataReport("Nasdaq report contains no non-empty lines.")

    first = _strip_sep_declaration(lines[0])
    first_is_declaration = bool(
        re.fullmatch(r"sep\s*=\s*.", first, flags=re.IGNORECASE)
    )
    content_lines = lines[1:] if first_is_declaration else lines
    if not content_lines:
        raise NasdaqNoDataReport(
            "Nasdaq report contains only a separator declaration."
        )

    preview = "\n".join(content_lines[:5]).lstrip().lower()
    if preview.startswith(("<!doctype html", "<html")):
        raise RuntimeError("Nasdaq report returned HTML instead of CSV data.")
    if preview in {"no data", "no records", "no trades"}:
        raise NasdaqNoDataReport("Nasdaq report explicitly contains no data.")

    encodings = [preferred_encoding, "utf-8-sig", "utf-8", "cp1252", "latin1"]
    encodings = list(dict.fromkeys(encodings))
    last_error: Exception | None = None

    for encoding in encodings:
        try:
            file_lines = path.read_text(encoding=encoding).splitlines()
            delimiter = ""
            skiprows = 0
            first_content_index = next(
                (index for index, line in enumerate(file_lines) if line.strip()),
                None,
            )
            if first_content_index is not None:
                declaration = _strip_sep_declaration(file_lines[first_content_index])
                match = re.fullmatch(
                    r"sep\s*=\s*(.)", declaration, flags=re.IGNORECASE
                )
                if match:
                    delimiter = match.group(1)
                    skiprows = first_content_index + 1

            if not delimiter:
                sample = "\n".join(file_lines[skiprows:])[:20000]
                if not sample.strip():
                    raise NasdaqNoDataReport("Nasdaq report has no CSV body.")
                try:
                    delimiter = csv.Sniffer().sniff(
                        sample, delimiters=[",", ";", "\t", "|"]
                    ).delimiter
                except csv.Error:
                    delimiter = ";" if sample.count(";") > sample.count(",") else ","

            dataframe = pd.read_csv(
                path,
                encoding=encoding,
                sep=delimiter,
                skiprows=skiprows,
                dtype=str,
                keep_default_na=False,
                engine="python",
            )
            if len(dataframe.columns) == 0:
                raise NasdaqNoDataReport("Nasdaq report has no CSV columns.")
            return dataframe
        except NasdaqNoDataReport:
            raise
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Could not parse Nasdaq report: {path}") from last_error


EXPECTED_COLUMNS = {
    "Trading date and time",
    "Instrument identification code",
    "Price",
    "Missing Price",
    "Price currency",
    "Price notation",
    "Quantity",
    "Venue of execution",
    "Trading system",
    "Publication date and time",
    "Venue of publication",
    "Transaction identification code",
    "Flags",
}
REPORT_ID_PATTERN = re.compile(
    rf"({re.escape(REPORT_PREFIX)}\d{{4}}-\d{{2}}-\d{{2}}T\d{{4}})",
    flags=re.IGNORECASE,
)


@dataclass
class ProcessResult:
    report_id: str
    status: str = "PROCESSED"
    rows_read: int = 0
    selected_rows: int = 0
    primary_lit_rows: int = 0
    inserted_trades: int = 0
    affected_dates: set[str] | None = None

    def __post_init__(self) -> None:
        if self.affected_dates is None:
            self.affected_dates = set()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect Nasdaq Nordic delayed post-trade reports into a separate "
            "persistent SQLite database and aggregate primary XSTO trades into "
            "five-minute bars."
        )
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome headless. Visible Chrome is the safer default.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=2000,
        help="Maximum new reports to download. Use 0 for no explicit limit.",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=48,
        help="Ignore discovered report identifiers older than this many hours.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help=(
            "Import existing probe/incoming files and rebuild bars without "
            "opening Chrome or downloading reports."
        ),
    )
    parser.add_argument(
        "--no-import-probe",
        action="store_true",
        help="Do not import existing CSV files from data/nasdaq_raw/probe.",
    )
    return parser.parse_args()


def report_id_from_text(value: str) -> str:
    match = REPORT_ID_PATTERN.search(value)
    return match.group(1) if match else ""


def report_time_stockholm(report_id: str) -> datetime | None:
    value = report_id.removeprefix(REPORT_PREFIX)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H%M")
    except ValueError:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_file(path: Path, report_id: str, remove_source: bool) -> Path:
    report_time = report_time_stockholm(report_id)
    date_part = report_time.date().isoformat() if report_time else "unknown_date"
    destination_dir = NASDAQ_ARCHIVE_DIR / date_part
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{report_id}.csv.gz"

    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with path.open("rb") as source, gzip.open(temporary, "wb") as target:
            shutil.copyfileobj(source, target)
        temporary.replace(destination)

    if remove_source and path.exists():
        path.unlink()

    return destination


def normalize_report_candidates(
    candidates: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    by_identifier: dict[str, str] = {}
    for identifier, href in candidates:
        identifier = report_id_from_text(identifier)
        if not identifier:
            continue
        href = str(href or "").strip()
        existing = by_identifier.get(identifier, "")
        if identifier not in by_identifier or (not existing and href):
            by_identifier[identifier] = href
    return sorted(by_identifier.items(), key=lambda item: item[0])


def discover_browser_reports(
    headless: bool,
) -> tuple[list[tuple[str, str]], str]:
    from selenium.webdriver.support.ui import WebDriverWait

    from RegimeTrading.scripts.probe_nasdaq_posttrade import (
        browser_cookie_header,
        build_driver,
        collect_browser_report_candidates,
        try_accept_cookies,
    )

    print("\nDiscovering available Nasdaq reports...")
    if not headless:
        print("A Chrome window will open briefly. Do not close it.")

    driver = build_driver(NASDAQ_INCOMING_DIR, headless=headless)
    try:
        driver.get(POST_TRADE_PAGE)
        WebDriverWait(driver, 75).until(
            lambda current: current.execute_script("return document.readyState")
            in {"interactive", "complete"}
        )
        try_accept_cookies(driver)

        def candidates_available(current) -> bool:
            try:
                return bool(
                    collect_browser_report_candidates(current, NASDAQ_INCOMING_DIR)
                )
            except Exception:
                return False

        WebDriverWait(driver, 75).until(candidates_available)

        # Some Nasdaq tables lazy-load. Scroll and take fresh DOM snapshots until
        # the number of unique report identifiers stabilises.
        best: list[tuple[str, str]] = []
        stable_rounds = 0
        previous_count = -1
        for _ in range(20):
            snapshot = normalize_report_candidates(
                collect_browser_report_candidates(driver, NASDAQ_INCOMING_DIR)
            )
            if len(snapshot) > len(best):
                best = snapshot
            if len(best) == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                previous_count = len(best)
            if stable_rounds >= 3:
                break
            driver.execute_script(
                "window.scrollTo(0, Math.max(document.body.scrollHeight, "
                "document.documentElement.scrollHeight));"
            )
            time.sleep(0.8)

        cookie_header = browser_cookie_header(driver)
        if not best:
            raise RuntimeError("No Nasdaq report identifiers were found.")
        return best, cookie_header
    finally:
        driver.quit()


def ensure_report_row(
    connection: sqlite3.Connection,
    report_id: str,
    report_url: str,
    source_filename: str,
    status: str,
) -> None:
    report_time = report_time_stockholm(report_id)
    connection.execute(
        """
        INSERT INTO downloaded_reports (
            report_id, report_url, report_time_stockholm,
            source_filename, status, downloaded_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(report_id) DO UPDATE SET
            report_url=CASE
                WHEN excluded.report_url <> '' THEN excluded.report_url
                ELSE downloaded_reports.report_url
            END,
            source_filename=CASE
                WHEN excluded.source_filename <> '' THEN excluded.source_filename
                ELSE downloaded_reports.source_filename
            END,
            status=excluded.status,
            downloaded_at_utc=COALESCE(
                downloaded_reports.downloaded_at_utc,
                excluded.downloaded_at_utc
            )
        """,
        (
            report_id,
            report_url,
            report_time.isoformat(timespec="minutes") if report_time else "",
            source_filename,
            status,
            utc_now_text(),
        ),
    )


def processed_report_ids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT report_id
        FROM downloaded_reports
        WHERE status IN ('PROCESSED', 'NO_DATA')
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def trade_key_for_row(row: pd.Series) -> str:
    transaction_id = str(row.get("transaction_id", "")).strip()
    identity = "|".join(
        [
            str(row.get("trade_date_stockholm", "")),
            str(row.get("venue_publication", "")),
            transaction_id,
            str(row.get("isin", "")),
        ]
    )
    if not transaction_id:
        identity = "|".join(
            [
                str(row.get("trade_time_utc", "")),
                str(row.get("isin", "")),
                str(row.get("price", "")),
                str(row.get("quantity", "")),
                str(row.get("venue_execution", "")),
                str(row.get("flags", "")),
            ]
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def normalize_selected_rows(dataframe: pd.DataFrame) -> pd.DataFrame:
    missing_columns = EXPECTED_COLUMNS - set(dataframe.columns)
    if missing_columns:
        raise RuntimeError(
            "Nasdaq report is missing expected columns: "
            + ", ".join(sorted(missing_columns))
        )

    selected = dataframe[
        dataframe["Instrument identification code"].isin(INSTRUMENT_BY_ISIN)
    ].copy()
    if selected.empty:
        return selected

    selected = selected.rename(
        columns={
            "Trading date and time": "trade_time_utc_raw",
            "Instrument identification code": "isin",
            "Price": "price",
            "Missing Price": "missing_price",
            "Price currency": "price_currency",
            "Price notation": "price_notation",
            "Quantity": "quantity",
            "Venue of execution": "venue_execution",
            "Trading system": "trading_system",
            "Publication date and time": "publication_time_utc_raw",
            "Venue of publication": "venue_publication",
            "Transaction identification code": "transaction_id",
            "Flags": "flags",
        }
    )

    selected["ticker"] = selected["isin"].map(
        lambda isin: INSTRUMENT_BY_ISIN[str(isin)].ticker
    )
    selected["price"] = pd.to_numeric(selected["price"], errors="coerce")
    selected["quantity"] = pd.to_numeric(selected["quantity"], errors="coerce")
    selected["trade_time_utc_ts"] = pd.to_datetime(
        selected["trade_time_utc_raw"], utc=True, errors="coerce"
    )
    selected["publication_time_utc_ts"] = pd.to_datetime(
        selected["publication_time_utc_raw"], utc=True, errors="coerce"
    )

    selected = selected.dropna(
        subset=["price", "quantity", "trade_time_utc_ts"]
    ).copy()
    selected = selected[
        (selected["price"] > 0)
        & (selected["quantity"] > 0)
        & (selected["missing_price"].astype(str).str.strip() == "")
    ].copy()

    stockholm = selected["trade_time_utc_ts"].dt.tz_convert(STOCKHOLM_TIMEZONE)
    selected["trade_time_stockholm_ts"] = stockholm
    selected["trade_date_stockholm"] = stockholm.dt.strftime("%Y-%m-%d")
    selected["trade_time_utc"] = selected["trade_time_utc_ts"].dt.strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    selected["trade_time_stockholm"] = stockholm.dt.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )
    selected["publication_time_utc"] = selected[
        "publication_time_utc_ts"
    ].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    for column in [
        "price_currency",
        "price_notation",
        "venue_execution",
        "trading_system",
        "venue_publication",
        "transaction_id",
        "flags",
    ]:
        selected[column] = selected[column].astype(str).str.strip()

    selected["is_primary_lit"] = (
        selected["price_currency"].eq(PRIMARY_CURRENCY)
        & selected["price_notation"].eq(PRIMARY_PRICE_NOTATION)
        & selected["venue_execution"].eq(PRIMARY_MIC)
        & selected["trading_system"].eq(PRIMARY_TRADING_SYSTEM)
    ).astype(int)
    selected["trade_key"] = selected.apply(trade_key_for_row, axis=1)
    return selected


def process_no_data_report(
    connection: sqlite3.Connection,
    path: Path,
    report_id: str,
    report_url: str,
    reason: str,
    remove_source_after_archive: bool,
) -> ProcessResult:
    archive_path = archive_file(
        path=path,
        report_id=report_id,
        remove_source=remove_source_after_archive,
    )
    connection.execute(
        """
        UPDATE downloaded_reports SET
            archive_path=?,
            file_sha256=?,
            file_size_bytes=?,
            rows_in_file=0,
            selected_rows=0,
            primary_lit_rows=0,
            inserted_trades=0,
            status='NO_DATA',
            processed_at_utc=?,
            error_message=?
        WHERE report_id=?
        """,
        (
            str(archive_path),
            sha256_file(archive_path),
            archive_path.stat().st_size,
            utc_now_text(),
            reason[:2000],
            report_id,
        ),
    )
    connection.commit()
    return ProcessResult(report_id=report_id, status="NO_DATA")


def process_report_file(
    connection: sqlite3.Connection,
    path: Path,
    report_id: str,
    report_url: str,
    remove_source_after_archive: bool,
) -> ProcessResult:
    ensure_report_row(
        connection,
        report_id=report_id,
        report_url=report_url,
        source_filename=path.name,
        status="PROCESSING",
    )
    connection.commit()

    try:
        dataframe = read_nasdaq_csv(path)
    except NasdaqNoDataReport as exc:
        return process_no_data_report(
            connection=connection,
            path=path,
            report_id=report_id,
            report_url=report_url,
            reason=str(exc),
            remove_source_after_archive=remove_source_after_archive,
        )

    rows_read = len(dataframe)
    selected = normalize_selected_rows(dataframe)
    selected_rows = len(selected)
    primary_lit_rows = (
        int(selected["is_primary_lit"].sum()) if not selected.empty else 0
    )

    inserted_before = connection.total_changes
    inserted_at = utc_now_text()
    if not selected.empty:
        records = [
            (
                row.trade_key,
                report_id,
                row.ticker,
                row.isin,
                row.trade_time_utc,
                row.trade_time_stockholm,
                row.trade_date_stockholm,
                float(row.price),
                float(row.quantity),
                row.price_currency,
                row.price_notation,
                row.venue_execution,
                row.trading_system,
                row.publication_time_utc,
                row.venue_publication,
                row.transaction_id,
                row.flags,
                int(row.is_primary_lit),
                path.name,
                inserted_at,
            )
            for row in selected.itertuples(index=False)
        ]
        connection.executemany(
            """
            INSERT OR IGNORE INTO nasdaq_trades (
                trade_key, report_id, ticker, isin,
                trade_time_utc, trade_time_stockholm,
                trade_date_stockholm, price, quantity,
                price_currency, price_notation, venue_execution,
                trading_system, publication_time_utc,
                venue_publication, transaction_id, flags,
                is_primary_lit, source_filename, inserted_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
    inserted_trades = connection.total_changes - inserted_before

    archive_path = archive_file(
        path=path,
        report_id=report_id,
        remove_source=remove_source_after_archive,
    )
    connection.execute(
        """
        UPDATE downloaded_reports SET
            archive_path=?,
            file_sha256=?,
            file_size_bytes=?,
            rows_in_file=?,
            selected_rows=?,
            primary_lit_rows=?,
            inserted_trades=?,
            status='PROCESSED',
            processed_at_utc=?,
            error_message=''
        WHERE report_id=?
        """,
        (
            str(archive_path),
            sha256_file(archive_path),
            archive_path.stat().st_size,
            rows_read,
            selected_rows,
            primary_lit_rows,
            inserted_trades,
            utc_now_text(),
            report_id,
        ),
    )
    connection.commit()

    dates = (
        set(selected["trade_date_stockholm"].astype(str))
        if not selected.empty
        else set()
    )
    return ProcessResult(
        report_id=report_id,
        rows_read=rows_read,
        selected_rows=selected_rows,
        primary_lit_rows=primary_lit_rows,
        inserted_trades=inserted_trades,
        affected_dates=dates,
    )


def mark_report_failed(
    connection: sqlite3.Connection,
    report_id: str,
    report_url: str,
    message: str,
) -> None:
    ensure_report_row(
        connection,
        report_id=report_id,
        report_url=report_url,
        source_filename="",
        status="FAILED",
    )
    connection.execute(
        """
        UPDATE downloaded_reports
        SET status='FAILED', error_message=?, processed_at_utc=?
        WHERE report_id=?
        """,
        (message[:2000], utc_now_text(), report_id),
    )
    connection.commit()


def import_existing_files(
    connection: sqlite3.Connection,
    directories: list[Path],
) -> tuple[list[ProcessResult], int]:
    results: list[ProcessResult] = []
    failures = 0
    already = processed_report_ids(connection)

    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.csv")):
            report_id = report_id_from_text(path.name)
            if not report_id or report_id in already:
                continue
            try:
                print(f"Importing existing report: {path.name}")
                result = process_report_file(
                    connection=connection,
                    path=path,
                    report_id=report_id,
                    report_url="",
                    remove_source_after_archive=directory == NASDAQ_INCOMING_DIR,
                )
                results.append(result)
                already.add(report_id)
            except Exception as exc:
                connection.rollback()
                failures += 1
                message = f"{type(exc).__name__}: {exc}"
                print(f"FAILED existing report {path.name}: {message}")
                mark_report_failed(connection, report_id, "", message)
    return results, failures


def rebuild_five_minute_bars(
    connection: sqlite3.Connection,
    affected_dates: set[str],
) -> int:
    if not affected_dates:
        return 0

    placeholders = ",".join("?" for _ in affected_dates)
    query = f"""
        SELECT ticker, trade_time_stockholm, price, quantity
        FROM nasdaq_trades
        WHERE is_primary_lit = 1
          AND trade_date_stockholm IN ({placeholders})
        ORDER BY ticker, trade_time_stockholm
    """
    trades = pd.read_sql_query(
        query,
        connection,
        params=sorted(affected_dates),
    )

    connection.executemany(
        "DELETE FROM nasdaq_5m_bars WHERE date=? AND source_mode=?",
        [(date_value, PRIMARY_BAR_MODE) for date_value in sorted(affected_dates)],
    )

    if trades.empty:
        connection.commit()
        return 0

    trades["bar_time"] = pd.to_datetime(
        trades["trade_time_stockholm"], errors="coerce"
    ).dt.floor("5min")
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce")
    trades = trades.dropna(subset=["bar_time", "price", "quantity"])
    trades = trades.sort_values(["ticker", "bar_time", "trade_time_stockholm"])

    grouped = trades.groupby(["ticker", "bar_time"], as_index=False).agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("quantity", "sum"),
        trade_count=("price", "size"),
        first_trade_time=("trade_time_stockholm", "first"),
        last_trade_time=("trade_time_stockholm", "last"),
    )
    rebuilt_at = utc_now_text()
    records = [
        (
            row.ticker,
            row.bar_time.strftime("%Y-%m-%d %H:%M:%S"),
            row.bar_time.strftime("%Y-%m-%d"),
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            float(row.volume),
            int(row.trade_count),
            str(row.first_trade_time),
            str(row.last_trade_time),
            PRIMARY_BAR_MODE,
            rebuilt_at,
        )
        for row in grouped.itertuples(index=False)
    ]
    connection.executemany(
        """
        INSERT INTO nasdaq_5m_bars (
            ticker, datetime, date, open, high, low, close,
            volume, trade_count, first_trade_time, last_trade_time,
            source_mode, rebuilt_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
    connection.commit()
    return len(records)


def filter_candidates(
    candidates: list[tuple[str, str]],
    processed: set[str],
    lookback_hours: int,
    max_files: int,
) -> tuple[list[tuple[str, str]], int]:
    cutoff = datetime.now() - timedelta(hours=max(lookback_hours, 1))
    eligible: list[tuple[str, str]] = []
    already_processed = 0

    for report_id, href in candidates:
        report_time = report_time_stockholm(report_id)
        if report_time is not None and report_time < cutoff:
            continue
        if report_id in processed:
            already_processed += 1
            continue
        if not href:
            continue
        eligible.append((report_id, href))

    # Oldest first prevents gaps when the collector is restarted with a limit.
    eligible.sort(key=lambda item: item[0])
    if max_files > 0:
        eligible = eligible[:max_files]
    return eligible, already_processed


def update_run(
    connection: sqlite3.Connection,
    run_id: str,
    **values,
) -> None:
    if not values:
        return
    columns = ", ".join(f"{column}=?" for column in values)
    connection.execute(
        f"UPDATE collection_runs SET {columns} WHERE run_id=?",
        [*values.values(), run_id],
    )
    connection.commit()


def main() -> None:
    args = parse_args()
    ensure_nasdaq_directories()
    initialize_database(NASDAQ_FORWARD_DB)

    run_id = str(uuid.uuid4())
    started_at = utc_now_text()

    print("\n=== COLLECT NASDAQ NORDIC POST-TRADE DATA ===")
    print(f"Persistent database : {NASDAQ_FORWARD_DB}")
    print(f"Raw archive         : {NASDAQ_ARCHIVE_DIR}")
    print("Research input      : unchanged (Yahoo intraday_prices.db)")
    print("Bar filter          : XSTO + CLOB + SEK + MONE")

    with closing(connect_database(NASDAQ_FORWARD_DB)) as connection:
        connection.execute(
            """
            INSERT INTO collection_runs (run_id, started_at_utc, status)
            VALUES (?, ?, 'RUNNING')
            """,
            (run_id, started_at),
        )
        connection.commit()

        total_rows = 0
        total_selected = 0
        total_primary = 0
        total_inserted = 0
        processed_reports_count = 0
        no_data_reports = 0
        failed_reports = 0
        affected_dates: set[str] = set()

        existing_dirs = [NASDAQ_INCOMING_DIR]
        if not args.no_import_probe:
            existing_dirs.insert(0, NASDAQ_PROBE_DIR)

        existing_results, existing_failures = import_existing_files(
            connection,
            existing_dirs,
        )
        failed_reports += existing_failures
        for result in existing_results:
            if result.status == "NO_DATA":
                no_data_reports += 1
            else:
                processed_reports_count += 1
            total_rows += result.rows_read
            total_selected += result.selected_rows
            total_primary += result.primary_lit_rows
            total_inserted += result.inserted_trades
            affected_dates.update(result.affected_dates or set())

        discovered_reports = 0
        already_processed_count = 0
        attempted_reports = 0

        if not args.skip_download:
            candidates, cookie_header = discover_browser_reports(args.headless)
            discovered_reports = len(candidates)
            processed = processed_report_ids(connection)
            eligible, already_processed_count = filter_candidates(
                candidates=candidates,
                processed=processed,
                lookback_hours=args.lookback_hours,
                max_files=args.max_files,
            )
            print(f"Reports discovered  : {discovered_reports}")
            print(f"Already processed   : {already_processed_count}")
            print(f"New reports selected: {len(eligible)}")

            from RegimeTrading.scripts.probe_nasdaq_posttrade import download_url

            for index, (report_id, href) in enumerate(eligible, start=1):
                attempted_reports += 1
                print(f"[{index}/{len(eligible)}] {report_id}")
                try:
                    path = download_url(
                        url=href,
                        destination_dir=NASDAQ_INCOMING_DIR,
                        identifier=report_id,
                        cookie_header=cookie_header,
                        referer=POST_TRADE_PAGE,
                    )
                    result = process_report_file(
                        connection=connection,
                        path=path,
                        report_id=report_id,
                        report_url=href,
                        remove_source_after_archive=True,
                    )
                    if result.status == "NO_DATA":
                        no_data_reports += 1
                    else:
                        processed_reports_count += 1
                    total_rows += result.rows_read
                    total_selected += result.selected_rows
                    total_primary += result.primary_lit_rows
                    total_inserted += result.inserted_trades
                    affected_dates.update(result.affected_dates or set())
                    time.sleep(0.05)
                except Exception as exc:
                    connection.rollback()
                    failed_reports += 1
                    message = f"{type(exc).__name__}: {exc}"
                    print(f"FAILED {report_id}: {message}")
                    mark_report_failed(connection, report_id, href, message)

        rebuilt_bars = rebuild_five_minute_bars(connection, affected_dates)
        final_status = "SUCCESS" if failed_reports == 0 else "PARTIAL_SUCCESS"
        update_run(
            connection,
            run_id,
            finished_at_utc=utc_now_text(),
            status=final_status,
            discovered_reports=discovered_reports,
            already_processed_reports=already_processed_count,
            attempted_reports=attempted_reports,
            processed_reports=processed_reports_count,
            no_data_reports=no_data_reports,
            failed_reports=failed_reports,
            rows_read=total_rows,
            selected_rows=total_selected,
            primary_lit_rows=total_primary,
            inserted_trades=total_inserted,
            rebuilt_bars=rebuilt_bars,
            message=(
                "Nasdaq data remains diagnostic and is not used by the V1 "
                "research strategy."
            ),
        )

    print("\n=== COLLECTION RESULT ===")
    print(f"Processed reports : {processed_reports_count}")
    print(f"No-data reports   : {no_data_reports}")
    print(f"Failed reports    : {failed_reports}")
    print(f"Rows read         : {total_rows}")
    print(f"Selected rows     : {total_selected}")
    print(f"Primary-lit rows  : {total_primary}")
    print(f"New trades stored : {total_inserted}")
    print(f"Five-minute bars  : {rebuilt_bars}")
    print("Nasdaq collection complete. V1 research input was not changed.")


if __name__ == "__main__":
    main()
