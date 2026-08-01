from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from labor_day.contamination import load_macro_events


PROJECT_ROOT = Path(__file__).resolve().parents[2]

ARCHIVE_INDEX_URL = (
    "https://www.bls.gov/bls/news-release/empsit.htm"
)

DEFAULT_MACRO_REGISTRY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events.csv"
)

DEFAULT_ARCHIVE_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "bls_empsit_archive_1998_2025.csv"
)

DEFAULT_MANIFEST_OUTPUT = (
    PROJECT_ROOT
    / "manifests"
    / "bls_empsit_archive_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_empsit.csv"
)

MACRO_COLUMNS = [
    "event_id",
    "event_date",
    "event_time_et",
    "event_timezone",
    "source",
    "event_type",
    "event_name",
    "tier",
    "verification_status",
    "source_url",
    "notes",
]

RELEASE_LINK_PATTERN = re.compile(
    r"empsit_(\d{6}|\d{8})\.(?:htm|html|txt|pdf)$",
    flags=re.IGNORECASE,
)

REFERENCE_PERIOD_PATTERN = re.compile(
    r"\b("
    r"January|February|March|April|May|June|"
    r"July|August|September|October|November|December"
    r")\s+(\d{4})\s+Employment Situation\b",
    flags=re.IGNORECASE,
)

FORMAT_RANK = {
    ".htm": 0,
    ".html": 0,
    ".txt": 1,
    ".pdf": 2,
}

EXPECTED_1998_2025_RELEASE_COUNT = 335

KNOWN_RELEASE_DATES = {
    date(1998, 9, 4),
    date(2001, 9, 7),
    date(2024, 9, 6),
    date(2025, 9, 5),
}


def create_http_session() -> requests.Session:
    """Create a retrying HTTP session for official source retrieval."""
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.0,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods={"GET"},
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry
    )

    session = requests.Session()

    session.mount(
        "https://",
        adapter,
    )

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    return session


def fetch_archive_index(
    url: str = ARCHIVE_INDEX_URL,
    timeout_seconds: int = 60,
) -> tuple[str, bytes]:
    """Download the official BLS Employment Situation archive index."""
    session = create_http_session()

    response = session.get(
        url,
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    raw_content = response.content

    if not raw_content:
        raise RuntimeError(
            "The BLS archive response was empty."
        )

    response.encoding = (
        response.apparent_encoding
        or "utf-8"
    )

    return response.text, raw_content


def decode_html_bytes(
    raw_content: bytes,
) -> str:
    """Decode locally saved HTML using common browser encodings."""
    encodings = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin-1",
    ]

    for encoding in encodings:
        try:
            return raw_content.decode(
                encoding
            )
        except UnicodeDecodeError:
            continue

    return raw_content.decode(
        "utf-8",
        errors="replace",
    )


def load_local_archive_html(
    path: Path,
) -> tuple[str, bytes]:
    """Read a locally saved official BLS archive page."""
    if not path.exists():
        raise FileNotFoundError(
            "Local BLS archive HTML file not found: "
            f"{path}"
        )

    if not path.is_file():
        raise ValueError(
            "Local BLS archive path is not a file: "
            f"{path}"
        )

    raw_content = path.read_bytes()

    if not raw_content:
        raise RuntimeError(
            "The local BLS archive HTML file is empty."
        )

    html = decode_html_bytes(
        raw_content
    )

    return html, raw_content


def parse_release_date_from_url(
    url: str,
) -> date | None:
    """
    Parse the actual publication date from a BLS archive URL.

    Historical files may use either MMDDYY or MMDDYYYY.
    """
    path = urlparse(url).path
    filename = Path(path).name

    match = RELEASE_LINK_PATTERN.search(
        filename
    )

    if match is None:
        return None

    digits = match.group(1)

    if len(digits) == 8:
        return datetime.strptime(
            digits,
            "%m%d%Y",
        ).date()

    month = int(digits[0:2])
    day = int(digits[2:4])
    short_year = int(digits[4:6])

    year = (
        1900 + short_year
        if short_year >= 90
        else 2000 + short_year
    )

    return date(
        year,
        month,
        day,
    )


def parse_reference_period(
    text: str,
) -> tuple[str, int] | None:
    """Extract the survey reference month and year from archive text."""
    match = REFERENCE_PERIOD_PATTERN.search(
        text
    )

    if match is None:
        return None

    month = match.group(1).title()
    year = int(match.group(2))

    return month, year


def archive_link_context(
    link,
) -> str:
    """Return surrounding archive text describing a release link."""
    container = link.find_parent(
        [
            "li",
            "tr",
            "p",
            "div",
        ]
    )

    if container is None:
        container = link.parent

    if container is None:
        return link.get_text(
            " ",
            strip=True,
        )

    return container.get_text(
        " ",
        strip=True,
    )


def extract_archive_index(
    html: str,
    index_url: str = ARCHIVE_INDEX_URL,
    start_year: int = 1998,
    end_year: int = 2025,
) -> pd.DataFrame:
    """
    Extract and deduplicate publication dates from the archive index.

    HTML is preferred over TXT, and TXT is preferred over PDF when
    multiple official formats exist for one publication date.
    """
    if start_year > end_year:
        raise ValueError(
            "start_year cannot exceed end_year."
        )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    candidates: list[dict[str, object]] = []

    for link in soup.find_all(
        "a",
        href=True,
    ):
        href = str(
            link["href"]
        ).strip()

        source_url = urljoin(
            index_url,
            href,
        )

        release_date = (
            parse_release_date_from_url(
                source_url
            )
        )

        if release_date is None:
            continue

        if not (
            start_year
            <= release_date.year
            <= end_year
        ):
            continue

        context = archive_link_context(
            link
        )

        reference_period = (
            parse_reference_period(
                context
            )
        )

        if reference_period is None:
            reference_month = ""
            reference_year = pd.NA
        else:
            reference_month, reference_year = (
                reference_period
            )

        extension = Path(
            urlparse(source_url).path
        ).suffix.lower()

        candidates.append(
            {
                "release_date": (
                    release_date.isoformat()
                ),
                "release_time_et": "08:30",
                "reference_month": (
                    reference_month
                ),
                "reference_year": (
                    reference_year
                ),
                "source_format": (
                    extension.lstrip(".")
                ),
                "source_url": source_url,
                "archive_index_url": index_url,
                "_format_rank": FORMAT_RANK.get(
                    extension,
                    99,
                ),
            }
        )

    if not candidates:
        raise RuntimeError(
            "No Employment Situation archive links were found. "
            "Confirm that the saved HTML is the full official "
            "BLS archive page rather than an error page."
        )

    archive = pd.DataFrame(
        candidates
    )

    archive.sort_values(
        [
            "release_date",
            "_format_rank",
            "source_url",
        ],
        inplace=True,
    )

    archive.drop_duplicates(
        subset=["release_date"],
        keep="first",
        inplace=True,
    )

    archive.drop(
        columns=["_format_rank"],
        inplace=True,
    )

    archive.sort_values(
        "release_date",
        inplace=True,
    )

    archive.reset_index(
        drop=True,
        inplace=True,
    )

    return archive


def validate_archive(
    archive: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> None:
    """Apply completeness and integrity checks to the archive extract."""
    required_columns = {
        "release_date",
        "release_time_et",
        "reference_month",
        "reference_year",
        "source_format",
        "source_url",
        "archive_index_url",
    }

    missing_columns = (
        required_columns.difference(
            archive.columns
        )
    )

    if missing_columns:
        raise ValueError(
            "Archive extract is missing columns: "
            + ", ".join(
                sorted(missing_columns)
            )
        )

    parsed_dates = pd.to_datetime(
        archive["release_date"],
        errors="coerce",
    )

    if parsed_dates.isna().any():
        raise ValueError(
            "Archive contains invalid release dates."
        )

    if archive[
        "release_date"
    ].duplicated().any():
        raise ValueError(
            "Archive contains duplicate release dates."
        )

    missing_reference_period = (
        archive["reference_month"]
        .astype(str)
        .str.strip()
        .eq("")
        | archive["reference_year"].isna()
    )

    if missing_reference_period.any():
        bad_dates = archive.loc[
            missing_reference_period,
            "release_date",
        ].tolist()

        raise ValueError(
            "Missing reference period for releases: "
            + ", ".join(bad_dates)
        )

    weekend_dates = archive.loc[
        parsed_dates.dt.weekday >= 5,
        "release_date",
    ].tolist()

    if weekend_dates:
        raise ValueError(
            "Employment Situation releases found on weekends: "
            + ", ".join(weekend_dates)
        )

    if not archive[
        "release_time_et"
    ].eq("08:30").all():
        raise ValueError(
            "Historical Employment Situation rows must "
            "use the official 08:30 ET release time."
        )

    if (
        start_year == 1998
        and end_year == 2025
        and len(archive)
        != EXPECTED_1998_2025_RELEASE_COUNT
    ):
        raise ValueError(
            "Expected "
            f"{EXPECTED_1998_2025_RELEASE_COUNT} "
            "official releases dated 1998-2025, "
            f"but extracted {len(archive)}."
        )

    extracted_dates = {
        timestamp.date()
        for timestamp in parsed_dates
    }

    applicable_known_dates = {
        known_date
        for known_date in KNOWN_RELEASE_DATES
        if (
            start_year
            <= known_date.year
            <= end_year
        )
    }

    missing_known_dates = (
        applicable_known_dates
        - extracted_dates
    )

    if missing_known_dates:
        formatted = sorted(
            value.isoformat()
            for value in missing_known_dates
        )

        raise ValueError(
            "Known official release dates are missing: "
            + ", ".join(formatted)
        )


def build_macro_rows(
    archive: pd.DataFrame,
) -> pd.DataFrame:
    """Convert the archive extract to the project macro schema."""
    rows: list[dict[str, str]] = []

    for row in archive.itertuples(
        index=False
    ):
        release_date = pd.Timestamp(
            row.release_date
        )

        reference_year = int(
            row.reference_year
        )

        reference_period = (
            f"{row.reference_month} "
            f"{reference_year}"
        )

        rows.append(
            {
                "event_id": (
                    "BLS_EMPSIT_"
                    f"{release_date:%Y_%m_%d}"
                ),
                "event_date": (
                    release_date.strftime(
                        "%Y-%m-%d"
                    )
                ),
                "event_time_et": "08:30",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "BLS",
                "event_type": (
                    "employment_situation"
                ),
                "event_name": (
                    "Employment Situation for "
                    f"{reference_period}"
                ),
                "tier": "tier_1",
                "verification_status": (
                    "official_archive"
                ),
                "source_url": row.source_url,
                "notes": (
                    "Historical release imported from "
                    "the official BLS archive index. "
                    f"Reference period: {reference_period}. "
                    "Publication time: 08:30 ET."
                ),
            }
        )

    macro_rows = pd.DataFrame(
        rows,
        columns=MACRO_COLUMNS,
    )

    if macro_rows[
        "event_id"
    ].duplicated().any():
        raise ValueError(
            "Generated duplicate Employment Situation "
            "event IDs."
        )

    return macro_rows


def merge_macro_registry(
    existing: pd.DataFrame,
    historical_rows: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """
    Replace historical Employment Situation rows idempotently.

    Other event types and manually entered 2026 events are retained.
    """
    registry = existing.copy()

    for column in MACRO_COLUMNS:
        if column not in registry.columns:
            raise ValueError(
                "Existing registry is missing column: "
                f"{column}"
            )

    registry_dates = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )

    replace_mask = (
        registry["source"]
        .astype(str)
        .str.upper()
        .eq("BLS")
        & registry["event_type"]
        .astype(str)
        .eq("employment_situation")
        & registry_dates.dt.year.between(
            start_year,
            end_year,
        )
    )

    retained = registry.loc[
        ~replace_mask,
        MACRO_COLUMNS,
    ].copy()

    merged = pd.concat(
        [
            retained,
            historical_rows[
                MACRO_COLUMNS
            ],
        ],
        ignore_index=True,
    )

    merged.sort_values(
        [
            "event_date",
            "event_time_et",
            "event_type",
            "event_id",
        ],
        inplace=True,
    )

    merged.reset_index(
        drop=True,
        inplace=True,
    )

    duplicated_ids = merged.loc[
        merged["event_id"].duplicated(
            keep=False
        ),
        "event_id",
    ].tolist()

    if duplicated_ids:
        raise ValueError(
            "Duplicate event IDs after registry merge: "
            + ", ".join(
                sorted(
                    set(duplicated_ids)
                )
            )
        )

    return merged


def atomic_write_csv(
    dataframe: pd.DataFrame,
    path: Path,
) -> None:
    """Write a CSV through a temporary file."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    dataframe.to_csv(
        temporary_path,
        index=False,
        encoding="utf-8",
    )

    temporary_path.replace(
        path
    )


def write_manifest(
    path: Path,
    *,
    source_url: str,
    source_kind: str,
    source_file: Path | None,
    raw_content: bytes,
    archive: pd.DataFrame,
    archive_output: Path,
) -> None:
    """Record source and integrity metadata for the archive import."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_file_text = (
        str(source_file.resolve())
        if source_file is not None
        else None
    )

    try:
        archive_output_text = str(
            archive_output.resolve().relative_to(
                PROJECT_ROOT.resolve()
            )
        )
    except ValueError:
        archive_output_text = str(
            archive_output.resolve()
        )

    manifest = {
        "dataset": (
            "BLS Employment Situation "
            "historical release calendar"
        ),
        "source_url": source_url,
        "source_kind": source_kind,
        "source_file": source_file_text,
        "retrieved_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source_sha256": hashlib.sha256(
            raw_content
        ).hexdigest(),
        "row_count": int(
            len(archive)
        ),
        "minimum_release_date": (
            archive["release_date"].min()
        ),
        "maximum_release_date": (
            archive["release_date"].max()
        ),
        "release_time_et": "08:30",
        "archive_output": archive_output_text,
    }

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(
        path
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import historical Employment Situation "
            "publication dates from the official BLS archive."
        )
    )

    parser.add_argument(
        "--start-year",
        type=int,
        default=1998,
    )

    parser.add_argument(
        "--end-year",
        type=int,
        default=2025,
    )

    parser.add_argument(
        "--archive-url",
        default=ARCHIVE_INDEX_URL,
    )

    parser.add_argument(
        "--archive-html",
        type=Path,
        default=None,
        help=(
            "Optional locally saved copy of the official "
            "BLS archive index. When supplied, no web "
            "request is made."
        ),
    )

    parser.add_argument(
        "--macro-registry",
        type=Path,
        default=DEFAULT_MACRO_REGISTRY,
    )

    parser.add_argument(
        "--archive-output",
        type=Path,
        default=DEFAULT_ARCHIVE_OUTPUT,
    )

    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_OUTPUT,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.start_year > args.end_year:
        raise ValueError(
            "start-year cannot exceed end-year."
        )

    existing_registry = load_macro_events(
        args.macro_registry
    )

    if args.archive_html is not None:
        html, raw_content = (
            load_local_archive_html(
                args.archive_html
            )
        )

        source_kind = "local_official_html"
        source_file = args.archive_html

        print(
            "Using locally saved official BLS archive index:"
        )
        print(
            args.archive_html
        )

    else:
        try:
            html, raw_content = (
                fetch_archive_index(
                    args.archive_url
                )
            )

            source_kind = "direct_http"
            source_file = None

        except requests.HTTPError as exc:
            raise RuntimeError(
                "The BLS website rejected the automated "
                "download. Save the official archive page "
                "locally and rerun with:\n\n"
                "python -m labor_day.ingest_bls_empsit "
                "--archive-html "
                "data/raw/macro_releases/"
                "bls_empsit_archive_index.html"
            ) from exc

    archive = extract_archive_index(
        html=html,
        index_url=args.archive_url,
        start_year=args.start_year,
        end_year=args.end_year,
    )

    validate_archive(
        archive=archive,
        start_year=args.start_year,
        end_year=args.end_year,
    )

    historical_rows = build_macro_rows(
        archive
    )

    merged_registry = merge_macro_registry(
        existing=existing_registry,
        historical_rows=historical_rows,
        start_year=args.start_year,
        end_year=args.end_year,
    )

    if not DEFAULT_BACKUP_PATH.exists():
        DEFAULT_BACKUP_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            args.macro_registry,
            DEFAULT_BACKUP_PATH,
        )

    atomic_write_csv(
        archive,
        args.archive_output,
    )

    atomic_write_csv(
        merged_registry,
        args.macro_registry,
    )

    write_manifest(
        args.manifest_output,
        source_url=args.archive_url,
        source_kind=source_kind,
        source_file=source_file,
        raw_content=raw_content,
        archive=archive,
        archive_output=args.archive_output,
    )

    print(
        "Historical Employment Situation registry imported."
    )

    print(
        f"Official archive rows: {len(archive)}"
    )

    print(
        "Registry rows before: "
        f"{len(existing_registry)}"
    )

    print(
        "Historical rows inserted: "
        f"{len(historical_rows)}"
    )

    print(
        "Registry rows after: "
        f"{len(merged_registry)}"
    )

    print(
        f"Archive extract: {args.archive_output}"
    )

    print(
        f"Registry: {args.macro_registry}"
    )

    print(
        f"Manifest: {args.manifest_output}"
    )


if __name__ == "__main__":
    main()