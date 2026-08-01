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

ARCHIVE_URL = "https://www.bls.gov/bls/news-release/prod.htm"
DEFAULT_EVENT_TYPE = "productivity_costs"

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
    / "productivity_costs_releases_1998_2025.csv"
)

DEFAULT_CACHE_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "productivity_costs_source_cache"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "productivity_costs_releases_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_productivity_costs.csv"
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
    "release_stage",
    "archive_label",
    "release_url",
    "archive_url",
    "source_format",
    "time_source",
    "verification_status",
    "notes",
]

QUARTER_NUMBERS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
}

MONTH_NUMBERS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

# Historical BLS text releases frequently abbreviate the month in the
# embargo line (for example, ``AUG. 7, 2003``), while later HTML releases
# generally spell it out. Accept only standard English month names and
# abbreviations, with an optional trailing period.
MONTH_PATTERN = (
    r"(January|Jan\.?|February|Feb\.?|March|Mar\.?|"
    r"April|Apr\.?|May|June|Jun\.?|July|Jul\.?|"
    r"August|Aug\.?|September|Sept?\.?|October|Oct\.?|"
    r"November|Nov\.?|December|Dec\.?)"
)

RELEASE_URL_PATTERN = re.compile(
    r"prod2_(\d{6}|\d{8})\.(htm|html|txt)$",
    flags=re.IGNORECASE,
)

LABEL_YEAR_PATTERN = re.compile(
    r"\b((?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)

LABEL_QUARTER_PATTERN = re.compile(
    r"\b(First|Second|Third|Fourth)\s*[-–—]?\s*Quarter\b",
    flags=re.IGNORECASE,
)

LABEL_STAGE_PATTERN = re.compile(
    r"\b(Preliminary|Revised)\b",
    flags=re.IGNORECASE,
)

PAGE_REFERENCE_PATTERNS = [
    re.compile(
        r"\bPRODUCTIVITY\s+AND\s+COSTS\b"
        r".{0,180}?"
        r"\b(First|Second|Third|Fourth)\s*[-–—]?\s*Quarter\b"
        r"(?:\s+and\s+Annual\s+Averages)?"
        r"[^0-9]{0,50}"
        r"((?:19|20)\d{2})\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(First|Second|Third|Fourth)\s*[-–—]?\s*Quarter\b"
        r"(?:\s+and\s+Annual\s+Averages)?"
        r"[^0-9]{0,50}"
        r"((?:19|20)\d{2})\b"
        r".{0,100}?"
        r"\bPRODUCTIVITY\s+AND\s+COSTS\b",
        flags=re.IGNORECASE,
    ),
]

# Historical BLS release headers are not structurally uniform. Depending on
# the year, the embargo line can contain a USDL release identifier between the
# word ``until`` and the clock time, can use ``FOR RELEASE:``, or can vary the
# punctuation around A.M./P.M. Parse the clock and date from a short window
# anchored on official release-header language instead of assuming that only
# non-numeric characters occur before the time.
HEADER_ANCHOR_PATTERN = re.compile(
    r"(?:TRANSMISSION\s+OF\s+THIS\s+MATERIAL\s+IS\s+)?"
    r"(?:EMBARGOED|RELEASED)\b|\bFOR\s+RELEASE\b",
    flags=re.IGNORECASE,
)

CLOCK_TIME_PATTERN = re.compile(
    r"\b(\d{1,2})"
    r"(?::(\d{2}))?"
    r"\s*"
    r"([AP])\.?\s*M\.?\b",
    flags=re.IGNORECASE,
)

HEADER_DATE_PATTERN = re.compile(
    rf"\b{MONTH_PATTERN}\s+([0-3]?\d)"
    r"(?:st|nd|rd|th)?"
    r",?\s+((?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)

HEADER_WINDOW_CHARS = 700
HEADER_DATE_AFTER_TIME_CHARS = 300

EXACT_VERIFICATION_STATUS = "official_release_page_exact_time"
EXACT_TIME_SOURCE = "official_bls_release_header"

EXPECTED_FULL_SAMPLE_ROWS = 222
EXPECTED_FULL_SAMPLE_FIRST_REFERENCE = "1997-Q4"
EXPECTED_FULL_SAMPLE_LAST_REFERENCE = "2025-Q2"
EXPECTED_FULL_SAMPLE_FIRST_DATE = "1998-02-10"
EXPECTED_FULL_SAMPLE_LAST_DATE = "2025-09-04"

# The BLS archive filename for the preliminary third-quarter 1999 release
# encodes 1999-11-15, but the official release header states that the
# material was embargoed until Friday, 1999-11-12. The release header is
# the authoritative publication timestamp; this exact discrepancy is
# documented narrowly so unrelated filename/header disagreements still fail.
KNOWN_URL_HEADER_DATE_MISMATCHES = {
    "https://www.bls.gov/news.release/history/prod2_11151999.txt": {
        "url_date": date(1999, 11, 15),
        "header_date": date(1999, 11, 12),
    }
}


def create_http_session() -> requests.Session:
    """Create a retrying browser-like session for public BLS pages."""
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
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
            "Referer": "https://www.bls.gov/productivity/news-releases.htm",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    session._bls_force_curl = False  # type: ignore[attr-defined]
    return session


def normalize_text(value: str) -> str:
    """Collapse source whitespace into a stable single-line representation."""
    return re.sub(
        r"\s+",
        " ",
        value.replace("\xa0", " ").replace("\u200b", " "),
    ).strip()


def decode_source(raw_content: bytes) -> str:
    """Decode historical BLS HTML/TXT documents conservatively."""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw_content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_content.decode("utf-8", errors="replace")


def source_to_text(raw_content: bytes, source_format: str) -> str:
    """Convert cached HTML/TXT source bytes to normalized readable text."""
    decoded = decode_source(raw_content)
    if source_format == "html":
        soup = BeautifulSoup(decoded, "html.parser")
        return normalize_text(soup.get_text(" ", strip=True))
    if source_format == "txt":
        return normalize_text(decoded)
    raise ValueError(f"Unsupported productivity source format: {source_format}")


def convert_clock_time(hour: int, minute: int, meridiem: str) -> str:
    """Convert a 12-hour clock value to HH:MM."""
    if not 1 <= hour <= 12:
        raise ValueError(f"Invalid hour: {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"Invalid minute: {minute}")

    normalized = meridiem.strip().lower()[0]
    if normalized == "a":
        converted_hour = 0 if hour == 12 else hour
    elif normalized == "p":
        converted_hour = 12 if hour == 12 else hour + 12
    else:
        raise ValueError(f"Invalid meridiem: {meridiem}")
    return f"{converted_hour:02d}:{minute:02d}"


def parse_release_date_from_url(url: str) -> date:
    """Read the BLS publication date encoded in a prod2 archive URL."""
    filename = Path(urlparse(url).path).name
    match = RELEASE_URL_PATTERN.fullmatch(filename)
    if match is None:
        raise ValueError(f"Unrecognized Productivity and Costs URL: {url}")

    digits = match.group(1)
    date_format = "%m%d%Y" if len(digits) == 8 else "%m%d%y"
    return datetime.strptime(digits, date_format).date()


def parse_source_format(url: str) -> str:
    """Classify the official release representation."""
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".htm", ".html"}:
        return "html"
    if suffix == ".txt":
        return "txt"
    raise ValueError(f"Unsupported Productivity and Costs source: {url}")


def parse_archive_label(label: str) -> tuple[str, str] | None:
    """Extract reference quarter and preliminary/revised stage from a list item."""
    normalized = normalize_text(label)
    if "productivity and costs" not in normalized.lower():
        return None

    year_match = LABEL_YEAR_PATTERN.search(normalized)
    quarter_match = LABEL_QUARTER_PATTERN.search(normalized)
    stage_match = LABEL_STAGE_PATTERN.search(normalized)
    if year_match is None or quarter_match is None or stage_match is None:
        return None

    year = int(year_match.group(1))
    quarter = QUARTER_NUMBERS[quarter_match.group(1).lower()]
    stage = stage_match.group(1).lower()
    return (f"{year:04d}-Q{quarter}", stage)


def parse_reference_period_text(text: str) -> str | None:
    """Extract the reference quarter from the official release body."""
    normalized = normalize_text(text)
    for pattern in PAGE_REFERENCE_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        quarter = QUARTER_NUMBERS[match.group(1).lower()]
        year = int(match.group(2))
        return f"{year:04d}-Q{quarter}"
    return None


def release_header_windows(normalized_text: str) -> list[str]:
    """Return likely release-header windows in source order.

    The BLS HTML wrapper can contain navigation and contact information before
    the actual release. Anchoring the search prevents a later ``next release``
    sentence from being mistaken for the publication timestamp.
    """
    windows: list[str] = []
    seen_starts: set[int] = set()

    for anchor in HEADER_ANCHOR_PATTERN.finditer(normalized_text):
        start = max(0, anchor.start() - 80)
        if start in seen_starts:
            continue
        seen_starts.add(start)
        windows.append(normalized_text[start : anchor.start() + HEADER_WINDOW_CHARS])

    if not windows:
        windows.append(normalized_text[:HEADER_WINDOW_CHARS])
    return windows


def parse_release_header(text: str) -> tuple[str | None, date | None]:
    """Parse the exact embargo time and publication date from a BLS header.

    Historical variants include release identifiers such as ``USDL-09-0933``
    between ``embargoed until`` and ``8:30 a.m.``, month abbreviations, optional
    ordinal day suffixes, and several punctuation styles. A valid result must
    contain a clock time with A.M./P.M. and a nearby calendar date in the same
    anchored header window.
    """
    normalized = normalize_text(text)

    for window in release_header_windows(normalized):
        for time_match in CLOCK_TIME_PATTERN.finditer(window):
            date_region = window[
                time_match.end() :
                time_match.end() + HEADER_DATE_AFTER_TIME_CHARS
            ]
            date_match = HEADER_DATE_PATTERN.search(date_region)
            if date_match is None:
                continue

            release_time = convert_clock_time(
                int(time_match.group(1)),
                int(time_match.group(2) or 0),
                time_match.group(3),
            )
            release_date = date(
                int(date_match.group(3)),
                MONTH_NUMBERS[date_match.group(1).lower().rstrip(".")],
                int(date_match.group(2)),
            )
            return release_time, release_date

    return None, None


def parse_archive_page(
    *,
    html: str,
    archive_url: str,
    start_year: int,
    end_year: int,
) -> list[dict[str, str]]:
    """Extract one official HTML/TXT source per release from the BLS archive."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[tuple[str, str], dict[str, str]] = {}

    for list_item in soup.find_all("li"):
        archive_label = normalize_text(list_item.get_text(" ", strip=True))
        parsed_label = parse_archive_label(archive_label)
        if parsed_label is None:
            continue
        reference_period, release_stage = parsed_label

        eligible_links: list[tuple[int, str, str, date]] = []
        for anchor in list_item.find_all("a", href=True):
            absolute_url = urljoin(archive_url, anchor["href"])
            filename = Path(urlparse(absolute_url).path).name
            if RELEASE_URL_PATTERN.fullmatch(filename) is None:
                continue

            publication_date = parse_release_date_from_url(absolute_url)
            if not start_year <= publication_date.year <= end_year:
                continue

            source_format = parse_source_format(absolute_url)
            priority = 0 if source_format == "html" else 1
            eligible_links.append(
                (priority, absolute_url, source_format, publication_date)
            )

        if not eligible_links:
            continue

        eligible_links.sort(key=lambda item: (item[0], item[1]))
        _, release_url, source_format, publication_date = eligible_links[0]

        key = (reference_period, release_stage)
        candidate = {
            "release_date": publication_date.isoformat(),
            "reference_period": reference_period,
            "release_stage": release_stage,
            "archive_label": archive_label,
            "release_url": release_url,
            "archive_url": archive_url,
            "source_format": source_format,
        }

        existing = candidates.get(key)
        if existing is None:
            candidates[key] = candidate
            continue

        existing_priority = 0 if existing["source_format"] == "html" else 1
        if (priority, release_url) < (existing_priority, existing["release_url"]):
            candidates[key] = candidate

    return sorted(
        candidates.values(),
        key=lambda row: (row["release_date"], row["release_stage"]),
    )


def cache_filename_for_url(url: str) -> str:
    """Return a stable collision-resistant cache filename."""
    filename = Path(urlparse(url).path).name
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    if filename:
        stem = Path(filename).stem
        suffix = Path(filename).suffix or ".bin"
        return f"{stem}_{digest}{suffix}"
    return f"source_{digest}.bin"


def fetch_with_curl(*, url: str, headers: dict[str, str]) -> bytes:
    """Use curl when BLS rejects the Python requests client."""
    curl_path = shutil.which("curl.exe") or shutil.which("curl")
    if curl_path is None:
        raise RuntimeError(
            "BLS blocked Python requests and curl.exe/curl was not found."
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
        headers.get("User-Agent", "Mozilla/5.0"),
        "--header",
        "Accept: " + headers.get("Accept", "text/html,*/*;q=0.8"),
        "--header",
        "Accept-Language: " + headers.get("Accept-Language", "en-US,en;q=0.9"),
        "--referer",
        headers.get("Referer", ARCHIVE_URL),
        url,
    ]

    completed = subprocess.run(command, check=False, capture_output=True)
    if completed.returncode != 0:
        details = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "BLS download failed through requests and curl. "
            f"URL: {url}. Details: {details}"
        )
    if not completed.stdout:
        raise RuntimeError(f"curl returned an empty response for {url}")
    return completed.stdout


def fetch_cached(
    *,
    session: requests.Session,
    url: str,
    cache_path: Path,
    refresh: bool,
    offline: bool,
) -> tuple[bytes, bool]:
    """Read an official source from cache or download it."""
    if cache_path.exists() and not refresh:
        return cache_path.read_bytes(), False
    if offline:
        raise FileNotFoundError(
            f"Offline mode requested but cache is missing: {cache_path}"
        )

    force_curl = bool(getattr(session, "_bls_force_curl", False))
    if force_curl:
        raw_content = fetch_with_curl(url=url, headers=dict(session.headers))
    else:
        response = session.get(url, timeout=60)
        if response.status_code == 403:
            print(
                "BLS returned HTTP 403 to Python requests; "
                "switching this run to curl.exe/curl."
            )
            session._bls_force_curl = True  # type: ignore[attr-defined]
            raw_content = fetch_with_curl(url=url, headers=dict(session.headers))
        else:
            response.raise_for_status()
            raw_content = response.content

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(raw_content)
    return raw_content, True


def collect_release_links(
    *,
    session: requests.Session,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
) -> tuple[list[dict[str, str]], bytes]:
    """Download and parse the official BLS Productivity archive index."""
    archive_cache_path = cache_dir / "productivity_costs_archive.html"
    archive_bytes, _ = fetch_cached(
        session=session,
        url=ARCHIVE_URL,
        cache_path=archive_cache_path,
        refresh=refresh,
        offline=offline,
    )
    links = parse_archive_page(
        html=decode_source(archive_bytes),
        archive_url=ARCHIVE_URL,
        start_year=start_year,
        end_year=end_year,
    )
    return links, archive_bytes


def build_release_archive(
    *,
    release_links: list[dict[str, str]],
    session: requests.Session,
    cache_dir: Path,
    refresh: bool,
    offline: bool,
    request_delay: float,
) -> tuple[pd.DataFrame, list[bytes]]:
    """Parse official release pages into a normalized quarterly archive."""
    rows: list[dict[str, str]] = []
    source_documents: list[bytes] = []
    header_failures: list[str] = []
    total = len(release_links)

    for position, link in enumerate(release_links, start=1):
        release_url = link["release_url"]
        cache_path = cache_dir / "release_pages" / cache_filename_for_url(release_url)
        raw_content, downloaded = fetch_cached(
            session=session,
            url=release_url,
            cache_path=cache_path,
            refresh=refresh,
            offline=offline,
        )
        source_documents.append(raw_content)

        page_text = source_to_text(raw_content, link["source_format"])
        release_time, header_date = parse_release_header(page_text)
        reference_period = parse_reference_period_text(page_text)
        url_date = date.fromisoformat(link["release_date"])

        if release_time is None or header_date is None:
            missing_parts: list[str] = []
            if release_time is None:
                missing_parts.append("time")
            if header_date is None:
                missing_parts.append("date")
            header_failures.append(
                f"{release_url} (missing {' and '.join(missing_parts)})"
            )
            if position % 25 == 0 or position == total:
                print(
                    "Productivity and Costs release pages processed: "
                    f"{position}/{total}"
                )
            if downloaded and request_delay > 0:
                time.sleep(request_delay)
            continue
        verified_release_date = header_date
        date_discrepancy_note = ""
        if header_date != url_date:
            documented = KNOWN_URL_HEADER_DATE_MISMATCHES.get(release_url)
            if (
                documented is None
                or documented["url_date"] != url_date
                or documented["header_date"] != header_date
            ):
                raise ValueError(
                    "Productivity release header date does not match URL date: "
                    f"{release_url}; header={header_date}; url={url_date}"
                )
            date_discrepancy_note = (
                " Official BLS archive filename encodes "
                f"{url_date.isoformat()}, while the release header states "
                f"{header_date.isoformat()}; header date used as authoritative."
            )
        if reference_period is None:
            reference_period = link["reference_period"]
        if reference_period != link["reference_period"]:
            raise ValueError(
                "Productivity reference period disagrees with archive label: "
                f"{release_url}; page={reference_period}; "
                f"archive={link['reference_period']}"
            )

        release_stage = link["release_stage"]
        event_id = (
            "bls_productivity_costs_"
            + verified_release_date.strftime("%Y%m%d")
            + "_"
            + release_stage
        )

        rows.append(
            {
                "event_id": event_id,
                "release_date": verified_release_date.isoformat(),
                "release_time_et": release_time,
                "event_timezone": "America/New_York",
                "reference_period": reference_period,
                "release_stage": release_stage,
                "archive_label": link["archive_label"],
                "release_url": release_url,
                "archive_url": link["archive_url"],
                "source_format": link["source_format"],
                "time_source": EXACT_TIME_SOURCE,
                "verification_status": EXACT_VERIFICATION_STATUS,
                "notes": (
                    "Official BLS quarterly Productivity and Costs "
                    f"{release_stage} release for {reference_period}."
                    + date_discrepancy_note
                ),
            }
        )

        if position % 25 == 0 or position == total:
            print(
                "Productivity and Costs release pages processed: "
                f"{position}/{total}"
            )
        if downloaded and request_delay > 0:
            time.sleep(request_delay)

    if header_failures:
        formatted = "\n - ".join(header_failures)
        raise ValueError(
            "Could not parse official Productivity and Costs release header "
            f"for {len(header_failures)} document(s):\n - {formatted}"
        )

    archive = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    archive.sort_values(
        ["release_date", "release_time_et", "release_stage", "event_id"],
        inplace=True,
    )
    archive.reset_index(drop=True, inplace=True)
    return archive, source_documents


def quarter_index(reference_period: str) -> int:
    """Convert YYYY-Qn to an integer suitable for continuity checks."""
    match = re.fullmatch(r"((?:19|20)\d{2})-Q([1-4])", reference_period)
    if match is None:
        raise ValueError(f"Invalid reference quarter: {reference_period}")
    return int(match.group(1)) * 4 + int(match.group(2)) - 1


def expected_full_sample_pairs() -> list[tuple[str, str]]:
    """Return all preliminary/revised pairs from 1997-Q4 through 2025-Q2."""
    first = quarter_index(EXPECTED_FULL_SAMPLE_FIRST_REFERENCE)
    last = quarter_index(EXPECTED_FULL_SAMPLE_LAST_REFERENCE)
    pairs: list[tuple[str, str]] = []
    for value in range(first, last + 1):
        year, zero_based_quarter = divmod(value, 4)
        period = f"{year:04d}-Q{zero_based_quarter + 1}"
        for stage in ("preliminary", "revised"):
            pairs.append((period, stage))
    return pairs


def validate_release_archive(
    *, archive: pd.DataFrame, start_year: int, end_year: int
) -> None:
    """Validate source integrity, exact timing, and quarterly completeness."""
    missing_columns = set(OUTPUT_COLUMNS).difference(archive.columns)
    if missing_columns:
        raise ValueError(
            "Productivity archive is missing columns: "
            + ", ".join(sorted(missing_columns))
        )
    if archive.empty:
        raise ValueError("Productivity and Costs release archive is empty.")
    if archive["event_id"].duplicated().any():
        raise ValueError("Productivity archive contains duplicate event IDs.")
    if archive.duplicated(["reference_period", "release_stage"]).any():
        raise ValueError(
            "Productivity archive contains duplicate reference-period/stage pairs."
        )

    release_dates = pd.to_datetime(archive["release_date"], errors="raise")
    if not release_dates.dt.year.between(start_year, end_year).all():
        raise ValueError("Productivity archive contains dates outside requested years.")
    if not archive["reference_period"].str.fullmatch(r"(?:19|20)\d{2}-Q[1-4]").all():
        raise ValueError("Productivity archive contains invalid reference quarters.")
    if not archive["release_stage"].isin({"preliminary", "revised"}).all():
        raise ValueError("Productivity archive contains invalid release stages.")
    if not archive["release_time_et"].str.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d").all():
        raise ValueError("Productivity archive contains invalid release times.")
    if not archive["event_timezone"].eq("America/New_York").all():
        raise ValueError("Unexpected Productivity and Costs timezone.")
    if not archive["verification_status"].eq(EXACT_VERIFICATION_STATUS).all():
        raise ValueError("Every Productivity release must have exact header time.")
    if not archive["time_source"].eq(EXACT_TIME_SOURCE).all():
        raise ValueError("Unexpected Productivity release time source.")

    for release_url in archive["release_url"]:
        parsed = urlparse(release_url)
        if parsed.netloc.lower() not in {"bls.gov", "www.bls.gov"}:
            raise ValueError("Non-BLS Productivity release URL found.")
        if RELEASE_URL_PATTERN.fullmatch(Path(parsed.path).name) is None:
            raise ValueError(f"Invalid BLS Productivity release URL: {release_url}")

    if start_year == 1998 and end_year == 2025:
        if len(archive) != EXPECTED_FULL_SAMPLE_ROWS:
            raise ValueError(
                f"Full Productivity sample contains {len(archive)} rows; "
                f"expected {EXPECTED_FULL_SAMPLE_ROWS}."
            )
        actual_pairs = sorted(
            zip(archive["reference_period"], archive["release_stage"]),
            key=lambda pair: (quarter_index(pair[0]), pair[1]),
        )
        expected_pairs = sorted(
            expected_full_sample_pairs(),
            key=lambda pair: (quarter_index(pair[0]), pair[1]),
        )
        if actual_pairs != expected_pairs:
            missing = sorted(set(expected_pairs).difference(actual_pairs))
            extra = sorted(set(actual_pairs).difference(expected_pairs))
            raise ValueError(
                "Full Productivity reference-stage sequence is incomplete. "
                f"Missing={missing}; extra={extra}"
            )
        if archive["release_date"].min() != EXPECTED_FULL_SAMPLE_FIRST_DATE:
            raise ValueError("Unexpected first Productivity publication date.")
        if archive["release_date"].max() != EXPECTED_FULL_SAMPLE_LAST_DATE:
            raise ValueError("Unexpected final Productivity publication date.")


def resolve_event_type(existing: pd.DataFrame) -> str:
    """Reuse the project's seeded Productivity event type when unambiguous."""
    event_type_text = existing["event_type"].astype(str)
    event_name_text = existing["event_name"].astype(str)
    notes_text = existing["notes"].astype(str)
    mask = (
        event_type_text.str.contains("product", case=False, na=False)
        | event_name_text.str.contains(
            r"productivity\s+and\s+costs", case=False, regex=True, na=False
        )
        | notes_text.str.contains(
            r"productivity\s+and\s+costs", case=False, regex=True, na=False
        )
    )
    candidates = sorted(
        {
            value.strip()
            for value in existing.loc[mask, "event_type"].astype(str)
            if value.strip()
        }
    )
    if len(candidates) == 1:
        return candidates[0]
    return DEFAULT_EVENT_TYPE


def build_macro_rows(archive: pd.DataFrame, *, event_type: str) -> pd.DataFrame:
    """Convert the verified archive to the common macro-event schema."""
    rows: list[dict[str, str]] = []
    for row in archive.itertuples(index=False):
        stage_title = row.release_stage.capitalize()
        rows.append(
            {
                "event_id": row.event_id,
                "event_date": row.release_date,
                "event_time_et": row.release_time_et,
                "event_timezone": row.event_timezone,
                "source": "BLS",
                "event_type": event_type,
                "event_name": "Productivity and Costs",
                "tier": "tier_1",
                "verification_status": row.verification_status,
                "source_url": row.release_url,
                "notes": (
                    f"{stage_title} quarterly Productivity and Costs release "
                    f"for {row.reference_period}. {row.notes}"
                ),
            }
        )
    macro_rows = pd.DataFrame(rows, columns=MACRO_COLUMNS)
    if macro_rows["event_id"].duplicated().any():
        raise ValueError("Generated duplicate Productivity event IDs.")
    return macro_rows


def merge_macro_registry(
    *,
    existing: pd.DataFrame,
    historical_rows: pd.DataFrame,
    event_type: str,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """Replace historical Productivity rows idempotently and preserve 2026+."""
    missing_columns = set(MACRO_COLUMNS).difference(existing.columns)
    if missing_columns:
        raise ValueError(
            "Existing registry is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    registry = existing.copy()
    event_dates = pd.to_datetime(registry["event_date"], errors="raise")
    replace_mask = (
        registry["event_type"].astype(str).eq(event_type)
        & event_dates.dt.year.between(start_year, end_year)
    )
    retained = registry.loc[~replace_mask, MACRO_COLUMNS].copy()
    merged = pd.concat(
        [retained, historical_rows[MACRO_COLUMNS]], ignore_index=True
    )
    merged.sort_values(
        ["event_date", "event_time_et", "event_type", "event_id"],
        inplace=True,
    )
    merged.reset_index(drop=True, inplace=True)

    duplicated = merged.loc[
        merged["event_id"].duplicated(keep=False), "event_id"
    ].tolist()
    if duplicated:
        raise ValueError(
            "Duplicate event IDs after Productivity merge: "
            + ", ".join(sorted(set(duplicated)))
        )
    return merged


def atomic_write_csv(dataframe: pd.DataFrame, path: Path) -> None:
    """Write a CSV through a temporary file and atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    dataframe.to_csv(temporary_path, index=False, encoding="utf-8")
    temporary_path.replace(path)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_manifest(
    *,
    path: Path,
    archive: pd.DataFrame,
    output_path: Path,
    requested_start_year: int,
    requested_end_year: int,
    archive_document: bytes,
    release_documents: list[bytes],
    cache_dir: Path,
    event_type: str,
) -> None:
    """Write a reproducibility manifest for official inputs and output."""
    output_bytes = archive.to_csv(index=False).encode("utf-8")
    release_times = archive["release_time_et"].value_counts().sort_index()
    publication_counts = (
        pd.to_datetime(archive["release_date"])
        .dt.year.value_counts()
        .sort_index()
    )
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "module": "labor_day.ingest_productivity_costs_releases",
        "archive_url": ARCHIVE_URL,
        "requested_publication_years": {
            "start": requested_start_year,
            "end": requested_end_year,
        },
        "event_type": event_type,
        "row_count": int(len(archive)),
        "reference_period_start": archive["reference_period"].iloc[0],
        "reference_period_end": archive["reference_period"].iloc[-1],
        "release_stage_counts": {
            key: int(value)
            for key, value in archive["release_stage"].value_counts().items()
        },
        "release_time_counts": {
            key: int(value) for key, value in release_times.items()
        },
        "publication_year_counts": {
            str(key): int(value) for key, value in publication_counts.items()
        },
        "verification_status_counts": {
            key: int(value)
            for key, value in archive["verification_status"].value_counts().items()
        },
        "source_format_counts": {
            key: int(value)
            for key, value in archive["source_format"].value_counts().items()
        },
        "official_source_hashes": {
            "archive_page_sha256": sha256_bytes(archive_document),
            "release_documents_sha256": sorted(
                sha256_bytes(document) for document in release_documents
            ),
        },
        "output": {
            "path": str(output_path),
            "sha256": sha256_bytes(output_bytes),
        },
        "cache_directory": str(cache_dir),
        "methodology": (
            "One official BLS HTML/TXT release per preliminary or revised "
            "quarterly observation. The publication date and exact embargo "
            "time are parsed from every official release header. The date "
            "encoded in the archive URL is cross-checked; only the documented "
            "1999-11-15 filename versus 1999-11-12 header anomaly is allowed, "
            "with the official header date treated as authoritative."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import historical BLS Productivity and Costs preliminary and "
            "revised releases into the Labor Day macro registry."
        )
    )
    parser.add_argument("--start-year", type=int, default=1998)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--macro-registry", type=Path, default=DEFAULT_MACRO_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_year > args.end_year:
        raise ValueError("start-year cannot exceed end-year.")
    if args.request_delay < 0:
        raise ValueError("request-delay cannot be negative.")

    session = create_http_session()
    existing_registry = load_macro_events(args.macro_registry)
    event_type = resolve_event_type(existing_registry)

    release_links, archive_document = collect_release_links(
        session=session,
        cache_dir=args.cache_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        refresh=args.refresh,
        offline=args.offline,
    )
    print(
        "Official Productivity and Costs release links discovered: "
        f"{len(release_links)}"
    )

    archive, release_documents = build_release_archive(
        release_links=release_links,
        session=session,
        cache_dir=args.cache_dir,
        refresh=args.refresh,
        offline=args.offline,
        request_delay=args.request_delay,
    )
    validate_release_archive(
        archive=archive,
        start_year=args.start_year,
        end_year=args.end_year,
    )

    historical_rows = build_macro_rows(archive, event_type=event_type)
    merged_registry = merge_macro_registry(
        existing=existing_registry,
        historical_rows=historical_rows,
        event_type=event_type,
        start_year=args.start_year,
        end_year=args.end_year,
    )

    if not DEFAULT_BACKUP_PATH.exists():
        DEFAULT_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.macro_registry, DEFAULT_BACKUP_PATH)

    atomic_write_csv(archive, args.output)
    atomic_write_csv(merged_registry, args.macro_registry)
    write_manifest(
        path=args.manifest_output,
        archive=archive,
        output_path=args.output,
        requested_start_year=args.start_year,
        requested_end_year=args.end_year,
        archive_document=archive_document,
        release_documents=release_documents,
        cache_dir=args.cache_dir,
        event_type=event_type,
    )

    publication_counts = (
        pd.to_datetime(archive["release_date"])
        .dt.year.value_counts()
        .sort_index()
    )
    for year, count in publication_counts.items():
        print(f"Productivity publication year {year}: {count} releases")

    print("Historical Productivity and Costs registry imported.")
    print(f"Release rows: {len(archive)}")
    print(
        "Preliminary releases: "
        f"{int(archive['release_stage'].eq('preliminary').sum())}"
    )
    print(
        "Revised releases: "
        f"{int(archive['release_stage'].eq('revised').sum())}"
    )
    print("Release-time distribution:")
    for release_time, count in (
        archive["release_time_et"].value_counts().sort_index().items()
    ):
        print(f"  {release_time}: {count}")
    print(
        "Reference-period span: "
        f"{archive['reference_period'].iloc[0]} to "
        f"{archive['reference_period'].iloc[-1]}"
    )
    print(f"Resolved event type: {event_type}")
    print(f"Registry rows before: {len(existing_registry)}")
    print(f"Registry rows after: {len(merged_registry)}")
    print(f"Archive output: {args.output.resolve()}")
    print(f"Registry: {args.macro_registry.resolve()}")
    print(f"Manifest: {args.manifest_output.resolve()}")
    print(f"Source cache: {args.cache_dir.resolve()}")


if __name__ == "__main__":
    main()