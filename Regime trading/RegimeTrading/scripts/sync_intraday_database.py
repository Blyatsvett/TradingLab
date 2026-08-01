from __future__ import annotations

import argparse
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from RegimeTrading.core.paths import INTRADAY_DB, SOURCE_INTRADAY_DB


REQUIRED_COLUMNS = {"datetime", "open", "high", "low", "close", "ticker"}
REPLACE_ATTEMPTS = 8
REPLACE_RETRY_SECONDS = 0.25


def validate_database(db_path: Path) -> tuple[int, str, str]:
    # sqlite3.Connection's context manager does not close the connection.
    # contextlib.closing guarantees that Windows releases the file handle.
    with closing(sqlite3.connect(db_path)) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(intraday_prices)"
            ).fetchall()
        }
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise RuntimeError(
                "Database table intraday_prices is missing columns: "
                + ", ".join(sorted(missing))
            )

        row_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM intraday_prices"
            ).fetchone()[0]
        )
        first_dt, last_dt = connection.execute(
            "SELECT MIN(datetime), MAX(datetime) FROM intraday_prices"
        ).fetchone()

    return row_count, str(first_dt or ""), str(last_dt or "")


def replace_with_retry(temporary: Path, destination: Path) -> None:
    last_error: PermissionError | None = None

    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt < REPLACE_ATTEMPTS:
                time.sleep(REPLACE_RETRY_SECONDS * attempt)

    raise PermissionError(
        "Could not replace the isolated database after "
        f"{REPLACE_ATTEMPTS} attempts. Close any program that has this file open: "
        f"{destination}. The original source database was not modified."
    ) from last_error


def sync_database(source: Path, destination: Path) -> None:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()

    if not source.exists():
        raise FileNotFoundError(f"Source intraday database not found: {source}")

    if source == destination:
        raise ValueError("Source and destination database paths must be different.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")

    if temporary.exists():
        temporary.unlink()

    # SQLite's backup API creates a consistent snapshot even if the source DB
    # is being read by another process. Explicit closing is required on Windows
    # before the temporary file can be atomically moved into place.
    source_uri = source.as_uri() + "?mode=ro"

    with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
        with closing(sqlite3.connect(temporary)) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.commit()

    # Validation also opens SQLite, so that connection must be explicitly closed
    # before the subsequent os.replace call.
    validate_database(temporary)
    replace_with_retry(temporary, destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy the original intraday database into the isolated "
            "research project."
        )
    )
    parser.add_argument("--source", type=Path, default=SOURCE_INTRADAY_DB)
    parser.add_argument("--destination", type=Path, default=INTRADAY_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("\n=== SYNC INTRADAY DATABASE ===")
    print(f"Read-only source: {args.source}")
    print(f"Local copy     : {args.destination}")

    sync_database(args.source, args.destination)
    row_count, first_dt, last_dt = validate_database(args.destination)

    print(f"Rows copied    : {row_count}")
    print(f"First datetime : {first_dt}")
    print(f"Last datetime  : {last_dt}")
    print("Database synchronization complete.")


if __name__ == "__main__":
    main()
