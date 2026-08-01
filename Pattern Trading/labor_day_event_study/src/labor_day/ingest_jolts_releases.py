from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
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

ARCHIVE_URL = (
    "https://www.bls.gov/bls/news-release/jolts.htm"
)

DEFAULT_MACRO_REGISTRY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events.csv"
)

DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "jolts_releases_2004_2025.csv"
)

DEFAULT_CACHE_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "jolts_source_cache"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "jolts_releases_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_jolts.csv"
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

OUTPUT_COLUMNS = [
    "event_id",
    "release_date",
    "release_time_et",
    "event_timezone",
    "reference_period",
    "archive_label",
    "release_url",
    "archive_url",
    "source_format",
    "time_source",
    "verification_status",
    "notes",
]

MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

MONTH_PATTERN = (
    r"(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)"
)

RELEASE_URL_PATTERN = re.compile(
    r"jolts_(\d{8})\.(htm|html|txt)$",
    flags=re.IGNORECASE,
)

TIME_PATTERNS = [
    (
        "official_for_release",
        re.compile(
            r"\bFor\s+release"
            r"(?:\s+at|\s*:)?\s+"
            r"(\d{1,2})"
            r"(?::(\d{2}))?\s*"
            r"([ap])\.?\s*m\.?",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "official_release_time",
        re.compile(
            r"\bRelease\s+time"
            r"(?:\s+at|\s*:)?\s+"
            r"(\d{1,2})"
            r"(?::(\d{2}))?\s*"
            r"([ap])\.?\s*m\.?",
            flags=re.IGNORECASE,
        ),
    ),
]

REFERENCE_PATTERNS = [
    re.compile(
        r"\bJOB\s+OPENINGS\s+AND\s+LABOR\s+TURNOVER"
        r"(?:\s+SURVEY)?\s*"
        r"(?:[-:\u2013\u2014]|\uFFFD)+\s*"
        + MONTH_PATTERN
        + r"\s+((?:19|20)\d{2})\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\bJob\s+Openings\s+and\s+Labor\s+Turnover"
        r"(?:\s+Survey)?\s+"
        + MONTH_PATTERN
        + r"\s+((?:19|20)\d{2})\b",
        flags=re.IGNORECASE,
    ),
]


def create_http_session() -> requests.Session:
    """Create a polite retrying HTTP session for BLS pages."""
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
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
    session.mount(
        "http://",
        adapter,
    )
    # BLS currently rejects generic script/bot user agents on some
    # archive endpoints. Use ordinary browser navigation headers while
    # retaining a slow request cadence and the local source cache.
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.bls.gov/jlt/news.htm",
            "Upgrade-Insecure-Requests": "1",
        }
    )

    # Set dynamically after the first requests-level 403. Once BLS
    # blocks the requests client, all remaining files use curl.exe/curl
    # instead of repeating a known-failing route.
    session._bls_force_curl = False  # type: ignore[attr-defined]

    return session


def normalize_text(value: str) -> str:
    """Collapse whitespace while preserving readable punctuation."""
    return re.sub(
        r"\s+",
        " ",
        value.replace(
            "\xa0",
            " ",
        ),
    ).strip()


def decode_source(
    raw_content: bytes,
) -> str:
    """Decode historical BLS HTML/TXT pages conservatively."""
    for encoding in (
        "utf-8-sig",
        "cp1252",
        "latin-1",
    ):
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


def source_to_text(
    raw_content: bytes,
    source_format: str,
) -> str:
    """Convert an official HTML or TXT release to normalized text."""
    decoded = decode_source(
        raw_content
    )

    if source_format == "html":
        soup = BeautifulSoup(
            decoded,
            "html.parser",
        )
        return normalize_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

    return normalize_text(
        decoded
    )


def convert_clock_time(
    hour: int,
    minute: int,
    meridiem: str,
) -> str:
    """Convert a 12-hour clock time to project HH:MM format."""
    normalized = meridiem.lower()

    if not 1 <= hour <= 12:
        raise ValueError(
            f"Invalid 12-hour clock hour: {hour}"
        )

    if not 0 <= minute <= 59:
        raise ValueError(
            f"Invalid minute: {minute}"
        )

    if normalized == "a":
        converted_hour = (
            0 if hour == 12 else hour
        )
    elif normalized == "p":
        converted_hour = (
            12 if hour == 12 else hour + 12
        )
    else:
        raise ValueError(
            f"Invalid meridiem: {meridiem}"
        )

    return (
        f"{converted_hour:02d}:"
        f"{minute:02d}"
    )


def parse_release_date_from_url(
    url: str,
) -> date:
    """Read the official publication date encoded in a BLS URL."""
    filename = Path(
        urlparse(url).path
    ).name

    match = RELEASE_URL_PATTERN.fullmatch(
        filename
    )

    if match is None:
        raise ValueError(
            "Unrecognized JOLTS release URL: "
            f"{url}"
        )

    return datetime.strptime(
        match.group(1),
        "%m%d%Y",
    ).date()


def parse_source_format(
    url: str,
) -> str:
    """Classify the official release representation."""
    suffix = Path(
        urlparse(url).path
    ).suffix.lower()

    if suffix in {
        ".htm",
        ".html",
    }:
        return "html"

    if suffix == ".txt":
        return "txt"

    raise ValueError(
        f"Unsupported JOLTS source format: {url}"
    )


def parse_reference_period_text(
    text: str,
) -> str | None:
    """Extract the JOLTS reference month from release-page text."""
    normalized = normalize_text(
        text
    )

    for pattern in REFERENCE_PATTERNS:
        match = pattern.search(
            normalized
        )

        if match is None:
            continue

        month = MONTH_NAMES[
            match.group(1).lower()
        ]
        year = int(
            match.group(2)
        )

        return (
            f"{year:04d}-{month:02d}"
        )

    return None


def parse_reference_period_label(
    archive_label: str,
) -> str | None:
    """Extract a reference month from an archive-list label."""
    pattern = re.compile(
        MONTH_PATTERN
        + r"\s+((?:19|20)\d{2})\b",
        flags=re.IGNORECASE,
    )

    match = pattern.search(
        normalize_text(
            archive_label
        )
    )

    if match is None:
        return None

    month = MONTH_NAMES[
        match.group(1).lower()
    ]
    year = int(
        match.group(2)
    )

    return (
        f"{year:04d}-{month:02d}"
    )


def parse_release_time(
    text: str,
) -> tuple[str | None, str]:
    """Extract the official release time from a JOLTS page."""
    normalized = normalize_text(
        text
    )

    for time_source, pattern in TIME_PATTERNS:
        match = pattern.search(
            normalized
        )

        if match is None:
            continue

        hour = int(
            match.group(1)
        )
        minute = int(
            match.group(2)
            or 0
        )
        meridiem = match.group(3)

        return (
            convert_clock_time(
                hour,
                minute,
                meridiem,
            ),
            time_source,
        )

    return (
        None,
        "official_page_date_only",
    )


def parse_archive_page(
    *,
    html: str,
    archive_url: str,
    start_year: int,
    end_year: int,
) -> list[dict[str, str]]:
    """
    Extract one official HTML/TXT link per archived JOLTS release.

    The BLS archive starts with February 2004 data. PDF links and
    non-national JOLTS material are intentionally ignored.
    """
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    candidates: dict[
        date,
        dict[str, str],
    ] = {}

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        absolute_url = urljoin(
            archive_url,
            anchor["href"],
        )

        filename = Path(
            urlparse(
                absolute_url
            ).path
        ).name

        if RELEASE_URL_PATTERN.fullmatch(
            filename
        ) is None:
            continue

        release_date = (
            parse_release_date_from_url(
                absolute_url
            )
        )

        if not (
            start_year
            <= release_date.year
            <= end_year
        ):
            continue

        source_format = (
            parse_source_format(
                absolute_url
            )
        )

        list_item = anchor.find_parent(
            "li"
        )

        if list_item is None:
            archive_label = (
                anchor.get_text(
                    " ",
                    strip=True,
                )
            )
        else:
            archive_label = (
                list_item.get_text(
                    " ",
                    strip=True,
                )
            )

        candidate = {
            "release_date": (
                release_date.isoformat()
            ),
            "archive_label": normalize_text(
                archive_label
            ),
            "release_url": absolute_url,
            "archive_url": archive_url,
            "source_format": source_format,
        }

        existing = candidates.get(
            release_date
        )

        if existing is None:
            candidates[
                release_date
            ] = candidate
            continue

        # Prefer HTML when both an HTML and TXT representation exist.
        if (
            existing[
                "source_format"
            ]
            == "txt"
            and source_format
            == "html"
        ):
            candidates[
                release_date
            ] = candidate

    return [
        candidates[
            release_date
        ]
        for release_date in sorted(
            candidates
        )
    ]


def cache_filename_for_url(
    url: str,
) -> str:
    """Return a stable cache name for an official source URL."""
    filename = Path(
        urlparse(url).path
    ).name

    if filename:
        return filename

    return (
        hashlib.sha256(
            url.encode(
                "utf-8"
            )
        ).hexdigest()
        + ".bin"
    )


def fetch_with_curl(
    *,
    url: str,
    headers: dict[str, str],
) -> bytes:
    """
    Download an official BLS page with the system curl client.

    BLS occasionally returns HTTP 403 to Python requests while serving
    the same public page to normal command-line/browser clients. Modern
    Windows includes curl.exe; Unix-like systems generally expose curl.
    """
    curl_path = (
        shutil.which("curl.exe")
        or shutil.which("curl")
    )

    if curl_path is None:
        raise RuntimeError(
            "BLS blocked the Python HTTP client with HTTP 403, "
            "and curl.exe/curl was not found on this computer."
        )

    command = [
        curl_path,
        "--location",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--compressed",
        "--retry",
        "5",
        "--retry-delay",
        "1",
        "--connect-timeout",
        "30",
        "--max-time",
        "120",
        "--user-agent",
        headers.get(
            "User-Agent",
            "Mozilla/5.0",
        ),
        "--header",
        (
            "Accept: "
            + headers.get(
                "Accept",
                "text/html,*/*;q=0.8",
            )
        ),
        "--header",
        (
            "Accept-Language: "
            + headers.get(
                "Accept-Language",
                "en-US,en;q=0.9",
            )
        ),
        "--referer",
        headers.get(
            "Referer",
            "https://www.bls.gov/jlt/news.htm",
        ),
        url,
    ]

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
    )

    if completed.returncode != 0:
        stderr = completed.stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()

        raise RuntimeError(
            "BLS download failed through both Python requests "
            "and curl. "
            f"curl exit code {completed.returncode}. "
            f"URL: {url}. "
            f"Details: {stderr}"
        )

    if not completed.stdout:
        raise RuntimeError(
            "curl returned an empty BLS response for "
            f"{url}"
        )

    return completed.stdout


def fetch_cached(
    *,
    session: requests.Session,
    url: str,
    cache_path: Path,
    refresh: bool,
    offline: bool,
) -> tuple[bytes, bool]:
    """Load an official source from cache or download it."""
    if (
        cache_path.exists()
        and not refresh
    ):
        return (
            cache_path.read_bytes(),
            False,
        )

    if offline:
        raise FileNotFoundError(
            "Offline mode requested but cache is missing: "
            f"{cache_path}"
        )

    force_curl = bool(
        getattr(
            session,
            "_bls_force_curl",
            False,
        )
    )

    if force_curl:
        raw_content = fetch_with_curl(
            url=url,
            headers=dict(
                session.headers
            ),
        )
    else:
        response = session.get(
            url,
            timeout=60,
        )

        if response.status_code == 403:
            print(
                "BLS returned HTTP 403 to Python requests; "
                "switching this run to curl.exe/curl."
            )
            session._bls_force_curl = True  # type: ignore[attr-defined]

            raw_content = fetch_with_curl(
                url=url,
                headers=dict(
                    session.headers
                ),
            )
        else:
            response.raise_for_status()
            raw_content = response.content

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    cache_path.write_bytes(
        raw_content
    )

    return (
        raw_content,
        True,
    )


def collect_release_links(
    *,
    session: requests.Session,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
) -> tuple[list[dict[str, str]], bytes]:
    """Download and parse the official BLS JOLTS archive page."""
    archive_cache_path = (
        cache_dir
        / "jolts_archive.html"
    )

    archive_bytes, _ = fetch_cached(
        session=session,
        url=ARCHIVE_URL,
        cache_path=archive_cache_path,
        refresh=refresh,
        offline=offline,
    )

    links = parse_archive_page(
        html=decode_source(
            archive_bytes
        ),
        archive_url=ARCHIVE_URL,
        start_year=start_year,
        end_year=end_year,
    )

    return (
        links,
        archive_bytes,
    )


def build_release_archive(
    *,
    release_links: list[dict[str, str]],
    session: requests.Session,
    cache_dir: Path,
    refresh: bool,
    offline: bool,
    request_delay: float,
) -> tuple[pd.DataFrame, list[bytes]]:
    """Parse official JOLTS release pages into a normalized archive."""
    rows: list[dict[str, str]] = []
    source_documents: list[bytes] = []

    total = len(
        release_links
    )

    for position, link in enumerate(
        release_links,
        start=1,
    ):
        release_url = link[
            "release_url"
        ]

        cache_path = (
            cache_dir
            / cache_filename_for_url(
                release_url
            )
        )

        raw_content, downloaded = fetch_cached(
            session=session,
            url=release_url,
            cache_path=cache_path,
            refresh=refresh,
            offline=offline,
        )

        source_documents.append(
            raw_content
        )

        page_text = source_to_text(
            raw_content,
            link["source_format"],
        )

        release_time, time_source = (
            parse_release_time(
                page_text
            )
        )

        reference_period = (
            parse_reference_period_text(
                page_text
            )
        )

        if reference_period is None:
            reference_period = (
                parse_reference_period_label(
                    link[
                        "archive_label"
                    ]
                )
            )

        release_date = date.fromisoformat(
            link[
                "release_date"
            ]
        )

        if reference_period is None:
            raise ValueError(
                "Could not determine JOLTS reference period "
                f"for {release_url}"
            )

        event_id = (
            "bls_jolts_"
            + release_date.strftime(
                "%Y%m%d"
            )
        )

        if release_time is None:
            verification_status = (
                "official_release_page_date_only"
            )
        else:
            verification_status = (
                "official_release_page_exact_time"
            )

        rows.append(
            {
                "event_id": event_id,
                "release_date": (
                    release_date.isoformat()
                ),
                "release_time_et": (
                    release_time
                    or ""
                ),
                "event_timezone": (
                    "America/New_York"
                ),
                "reference_period": (
                    reference_period
                ),
                "archive_label": (
                    link[
                        "archive_label"
                    ]
                ),
                "release_url": release_url,
                "archive_url": (
                    link[
                        "archive_url"
                    ]
                ),
                "source_format": (
                    link[
                        "source_format"
                    ]
                ),
                "time_source": (
                    time_source
                ),
                "verification_status": (
                    verification_status
                ),
                "notes": (
                    "Official national JOLTS news release. "
                    "The BLS archive begins with February 2004 "
                    "reference data."
                ),
            }
        )

        if (
            position % 25 == 0
            or position == total
        ):
            print(
                "JOLTS release pages processed: "
                f"{position}/{total}"
            )

        if (
            downloaded
            and request_delay > 0
        ):
            time.sleep(
                request_delay
            )

    archive = pd.DataFrame(
        rows,
        columns=OUTPUT_COLUMNS,
    )

    archive.sort_values(
        [
            "release_date",
            "event_id",
        ],
        inplace=True,
    )
    archive.reset_index(
        drop=True,
        inplace=True,
    )

    return (
        archive,
        source_documents,
    )


def validate_release_archive(
    *,
    archive: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> None:
    """Validate the normalized historical JOLTS archive."""
    missing_columns = set(
        OUTPUT_COLUMNS
    ).difference(
        archive.columns
    )

    if missing_columns:
        raise ValueError(
            "JOLTS archive is missing columns: "
            + ", ".join(
                sorted(
                    missing_columns
                )
            )
        )

    if archive.empty:
        raise ValueError(
            "JOLTS release archive is empty."
        )

    if archive[
        "event_id"
    ].duplicated().any():
        raise ValueError(
            "JOLTS archive contains duplicate event IDs."
        )

    if archive[
        "reference_period"
    ].duplicated().any():
        duplicated = archive.loc[
            archive[
                "reference_period"
            ].duplicated(
                keep=False
            ),
            "reference_period",
        ].tolist()

        raise ValueError(
            "JOLTS archive contains duplicate reference "
            "periods: "
            + ", ".join(
                sorted(
                    set(
                        duplicated
                    )
                )
            )
        )

    release_dates = pd.to_datetime(
        archive[
            "release_date"
        ],
        errors="coerce",
    )

    if release_dates.isna().any():
        raise ValueError(
            "JOLTS archive contains invalid release dates."
        )

    if not release_dates.dt.year.between(
        start_year,
        end_year,
    ).all():
        raise ValueError(
            "JOLTS archive contains release dates outside "
            "the requested sample."
        )

    invalid_reference_periods = archive.loc[
        ~archive[
            "reference_period"
        ].astype(str).str.match(
            r"^(?:19|20)\d{2}-(?:0[1-9]|1[0-2])$"
        ),
        "reference_period",
    ].tolist()

    if invalid_reference_periods:
        raise ValueError(
            "Invalid JOLTS reference periods: "
            + ", ".join(
                str(value)
                for value
                in invalid_reference_periods
            )
        )

    invalid_times = archive.loc[
        ~archive[
            "release_time_et"
        ].astype(str).str.match(
            r"^(?:|(?:(?:[01]\d|2[0-3]):[0-5]\d))$"
        ),
        "release_time_et",
    ].tolist()

    if invalid_times:
        raise ValueError(
            "Invalid JOLTS release times: "
            + ", ".join(
                str(value)
                for value
                in invalid_times
            )
        )

    invalid_formats = set(
        archive[
            "source_format"
        ]
    ).difference(
        {
            "html",
            "txt",
        }
    )

    if invalid_formats:
        raise ValueError(
            "Unexpected JOLTS source formats: "
            + ", ".join(
                sorted(
                    invalid_formats
                )
            )
        )

    # The official archived national release series starts with
    # February 2004 reference data. Earlier research years must stay
    # explicitly unavailable rather than being backfilled by rule.
    requested_includes_start = (
        start_year <= 2004
        and end_year >= 2004
    )

    if requested_includes_start:
        reference_periods = set(
            archive[
                "reference_period"
            ]
        )

        if "2004-02" not in reference_periods:
            raise ValueError(
                "The first official archived JOLTS reference "
                "period, 2004-02, is missing."
            )

        earlier_periods = {
            value
            for value in reference_periods
            if value < "2004-02"
        }

        if earlier_periods:
            raise ValueError(
                "JOLTS archive unexpectedly contains reference "
                "periods before official archive coverage: "
                + ", ".join(
                    sorted(
                        earlier_periods
                    )
                )
            )

    for year in range(
        max(
            start_year,
            2005,
        ),
        min(
            end_year,
            2024,
        )
        + 1,
    ):
        year_count = int(
            release_dates.dt.year.eq(
                year
            ).sum()
        )

        if year_count < 10:
            raise ValueError(
                f"Only {year_count} JOLTS releases were found "
                f"for {year}; expected at least 10."
            )


def build_macro_rows(
    archive: pd.DataFrame,
) -> pd.DataFrame:
    """Convert JOLTS releases to the project macro schema."""
    rows: list[dict[str, str]] = []

    for row in archive.itertuples(
        index=False
    ):
        rows.append(
            {
                "event_id": (
                    row.event_id
                ),
                "event_date": (
                    row.release_date
                ),
                "event_time_et": (
                    row.release_time_et
                ),
                "event_timezone": (
                    row.event_timezone
                ),
                "source": "BLS",
                "event_type": "jolts",
                "event_name": (
                    "Job Openings and Labor Turnover Survey"
                ),
                "tier": "tier_1",
                "verification_status": (
                    row.verification_status
                ),
                "source_url": (
                    row.release_url
                ),
                "notes": (
                    "Reference period "
                    f"{row.reference_period}. "
                    f"Official {row.source_format.upper()} "
                    "national JOLTS release."
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
            "Generated duplicate JOLTS macro event IDs."
        )

    return macro_rows


def merge_macro_registry(
    *,
    existing: pd.DataFrame,
    historical_rows: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """
    Replace historical JOLTS rows idempotently.

    Forward 2026 rows and all non-JOLTS events are preserved.
    """
    missing_columns = set(
        MACRO_COLUMNS
    ).difference(
        existing.columns
    )

    if missing_columns:
        raise ValueError(
            "Existing registry is missing columns: "
            + ", ".join(
                sorted(
                    missing_columns
                )
            )
        )

    registry = existing.copy()

    event_dates = pd.to_datetime(
        registry[
            "event_date"
        ],
        errors="raise",
    )

    replace_mask = (
        registry[
            "event_type"
        ].astype(str).eq(
            "jolts"
        )
        & event_dates.dt.year.between(
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

    duplicated = merged.loc[
        merged[
            "event_id"
        ].duplicated(
            keep=False
        ),
        "event_id",
    ].tolist()

    if duplicated:
        raise ValueError(
            "Duplicate event IDs after JOLTS merge: "
            + ", ".join(
                sorted(
                    set(
                        duplicated
                    )
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
    *,
    path: Path,
    archive: pd.DataFrame,
    output_path: Path,
    requested_start_year: int,
    requested_end_year: int,
    source_documents: list[bytes],
    cache_dir: Path,
) -> None:
    """Write reproducibility metadata and aggregate source hashes."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_hasher = hashlib.sha256()

    for raw_content in source_documents:
        source_hasher.update(
            raw_content
        )

    output_bytes = archive.to_csv(
        index=False
    ).encode(
        "utf-8"
    )

    release_dates = pd.to_datetime(
        archive[
            "release_date"
        ],
        errors="raise",
    )

    exact_time_count = int(
        archive[
            "verification_status"
        ].eq(
            "official_release_page_exact_time"
        ).sum()
    )

    try:
        relative_output = str(
            output_path.resolve().relative_to(
                PROJECT_ROOT.resolve()
            )
        )
    except ValueError:
        relative_output = str(
            output_path.resolve()
        )

    manifest = {
        "dataset": (
            "Historical national JOLTS news releases"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "requested_start_year": (
            requested_start_year
        ),
        "requested_end_year": (
            requested_end_year
        ),
        "official_archive_reference_start": (
            "2004-02"
        ),
        "pre_archive_years_unavailable": [
            year
            for year in range(
                requested_start_year,
                min(
                    requested_end_year,
                    2003,
                )
                + 1,
            )
        ],
        "row_count": int(
            len(
                archive
            )
        ),
        "exact_time_count": (
            exact_time_count
        ),
        "date_only_count": int(
            len(
                archive
            )
            - exact_time_count
        ),
        "minimum_release_date": (
            release_dates.min().date().isoformat()
        ),
        "maximum_release_date": (
            release_dates.max().date().isoformat()
        ),
        "minimum_reference_period": (
            archive[
                "reference_period"
            ].min()
        ),
        "maximum_reference_period": (
            archive[
                "reference_period"
            ].max()
        ),
        "source_pages_sha256": (
            source_hasher.hexdigest()
        ),
        "output_sha256": hashlib.sha256(
            output_bytes
        ).hexdigest(),
        "archive_url": ARCHIVE_URL,
        "cache_directory": str(
            cache_dir.resolve()
        ),
        "output_path": (
            relative_output
        ),
        "selection_rule": (
            "Official national Job Openings and Labor "
            "Turnover archived HTML/TXT releases, selected "
            "by actual publication date. PDF duplicates, "
            "state releases, supplemental material, and "
            "rule-derived pre-2004 dates are excluded."
        ),
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
            "Import historical national JOLTS news "
            "releases from the official BLS archive."
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
        "--macro-registry",
        type=Path,
        default=DEFAULT_MACRO_REGISTRY,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
    )

    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
    )

    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Redownload official pages even when "
            "cached copies exist."
        ),
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Use cached official pages only."
        ),
    )

    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.05,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.start_year > args.end_year:
        raise ValueError(
            "start-year cannot exceed end-year."
        )

    if args.request_delay < 0:
        raise ValueError(
            "request-delay cannot be negative."
        )

    session = create_http_session()

    existing_registry = load_macro_events(
        args.macro_registry
    )

    release_links, archive_source = (
        collect_release_links(
            session=session,
            cache_dir=args.cache_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            refresh=args.refresh,
            offline=args.offline,
        )
    )

    if not release_links:
        raise RuntimeError(
            "No official JOLTS release links were discovered."
        )

    print(
        "Official JOLTS links inside requested "
        "release years: "
        f"{len(release_links)}"
    )

    archive, release_sources = (
        build_release_archive(
            release_links=release_links,
            session=session,
            cache_dir=args.cache_dir,
            refresh=args.refresh,
            offline=args.offline,
            request_delay=args.request_delay,
        )
    )

    validate_release_archive(
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
        args.output,
    )

    atomic_write_csv(
        merged_registry,
        args.macro_registry,
    )

    write_manifest(
        path=args.manifest_output,
        archive=archive,
        output_path=args.output,
        requested_start_year=args.start_year,
        requested_end_year=args.end_year,
        source_documents=[
            archive_source,
            *release_sources,
        ],
        cache_dir=args.cache_dir,
    )

    exact_time_count = int(
        archive[
            "verification_status"
        ].eq(
            "official_release_page_exact_time"
        ).sum()
    )

    print(
        "Historical JOLTS release registry imported."
    )
    print(
        f"Release rows: {len(archive)}"
    )
    print(
        "Exact official times: "
        f"{exact_time_count}"
    )
    print(
        "Date-only releases: "
        f"{len(archive) - exact_time_count}"
    )
    print(
        "Reference-period coverage: "
        f"{archive['reference_period'].min()} "
        "through "
        f"{archive['reference_period'].max()}"
    )
    print(
        "Registry rows before: "
        f"{len(existing_registry)}"
    )
    print(
        "Registry rows after: "
        f"{len(merged_registry)}"
    )
    print(
        f"Archive output: {args.output}"
    )
    print(
        f"Registry: {args.macro_registry}"
    )
    print(
        f"Manifest: {args.manifest_output}"
    )
    print(
        f"Source cache: {args.cache_dir}"
    )


if __name__ == "__main__":
    main()