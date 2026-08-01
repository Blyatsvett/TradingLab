from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from labor_day.contamination import load_macro_events


PROJECT_ROOT = Path(__file__).resolve().parents[2]

HISTORICAL_YEAR_URL_TEMPLATE = (
    "https://www.federalreserve.gov/"
    "monetarypolicy/fomchistorical{year}.htm"
)

MODERN_CALENDAR_URL = (
    "https://www.federalreserve.gov/"
    "monetarypolicy/fomccalendars.htm"
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
    / "fomc_policy_decisions_1998_2025.csv"
)

DEFAULT_CACHE_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "fomc_source_cache"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "fomc_policy_decisions_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_fomc.csv"
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
    "decision_date",
    "release_time_et",
    "event_timezone",
    "meeting_type",
    "meeting_label",
    "statement_url",
    "index_url",
    "time_source",
    "verification_status",
    "notes",
]

DATE_IN_URL_PATTERN = re.compile(
    r"(?<!\d)((?:19|20)\d{6})(?!\d)"
)

MODERN_STATEMENT_PATTERN = re.compile(
    r"monetary((?:19|20)\d{6})a\.htm$",
    flags=re.IGNORECASE,
)

KNOWN_POLICY_DATES = {
    date(1998, 9, 29),
    date(1998, 10, 15),
    date(2001, 1, 3),
    date(2001, 4, 18),
    date(2001, 9, 17),
    date(2008, 1, 22),
    date(2008, 10, 8),
    date(2020, 3, 3),
    date(2020, 3, 15),
    date(2024, 9, 18),
    date(2025, 9, 17),
}


def create_http_session() -> requests.Session:
    """Create a polite retrying session for Federal Reserve pages."""
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

    session = requests.Session()

    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=retry
        ),
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


def decode_html_bytes(
    raw_content: bytes,
) -> str:
    """Decode HTML using common Federal Reserve page encodings."""
    for encoding in (
        "utf-8-sig",
        "utf-8",
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


def cache_filename_for_statement(
    statement_url: str,
    decision_date: date,
) -> str:
    """Create a deterministic cache filename for a statement page."""
    digest = hashlib.sha256(
        statement_url.encode("utf-8")
    ).hexdigest()[:10]

    return (
        f"statement_{decision_date:%Y%m%d}_"
        f"{digest}.html"
    )


def fetch_html_with_cache(
    *,
    session: requests.Session,
    url: str,
    cache_path: Path,
    refresh: bool,
    offline: bool,
    timeout_seconds: int = 60,
) -> tuple[str, bytes, str, bool]:
    """
    Load an official page from cache or download it.

    Returns HTML text, raw bytes, final URL, and whether a network download
    occurred. The final URL accounts for Federal Reserve redirects.
    """
    if (
        cache_path.exists()
        and not refresh
    ):
        raw_content = cache_path.read_bytes()

        if not raw_content:
            raise RuntimeError(
                f"Cached file is empty: {cache_path}"
            )

        return (
            decode_html_bytes(
                raw_content
            ),
            raw_content,
            url,
            False,
        )

    if offline:
        raise FileNotFoundError(
            "Required cached Federal Reserve page "
            f"does not exist: {cache_path}"
        )

    response = session.get(
        url,
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    raw_content = response.content

    if not raw_content:
        raise RuntimeError(
            f"Federal Reserve response was empty: {url}"
        )

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = cache_path.with_suffix(
        cache_path.suffix + ".tmp"
    )

    temporary_path.write_bytes(
        raw_content
    )

    temporary_path.replace(
        cache_path
    )

    return (
        decode_html_bytes(
            raw_content
        ),
        raw_content,
        response.url,
        True,
    )


def parse_date_from_url(
    url: str,
) -> date | None:
    """Extract a YYYYMMDD decision date embedded in an official URL."""
    matches = DATE_IN_URL_PATTERN.findall(
        url
    )

    if not matches:
        return None

    digits = matches[-1]

    try:
        return datetime.strptime(
            digits,
            "%Y%m%d",
        ).date()
    except ValueError:
        return None


def normalize_text(
    value: str,
) -> str:
    """Collapse repeated whitespace."""
    return " ".join(
        value.split()
    )


def classify_historical_heading(
    heading: str,
) -> str | None:
    """Classify a historical FOMC page heading."""
    normalized = heading.lower()

    if "conference call" in normalized:
        return "unscheduled"

    if "meeting" in normalized:
        return "scheduled"

    return None


def extract_historical_statement_links(
    *,
    html: str,
    index_url: str,
    year: int,
) -> list[dict[str, object]]:
    """
    Extract official policy-statement links from a historical year page.

    Only links whose visible label is exactly "Statement" are accepted.
    This excludes supplementary documents such as longer-run-goals and
    balance-sheet implementation statements. Conference calls are included
    only when their official entry has a plain policy statement link.
    """
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    rows: list[dict[str, object]] = []

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        anchor_text = normalize_text(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        if anchor_text.casefold() != "statement":
            continue

        heading_element = anchor.find_previous(
            [
                "h5",
                "h4",
            ]
        )

        if heading_element is None:
            continue

        meeting_label = normalize_text(
            heading_element.get_text(
                " ",
                strip=True,
            )
        )

        meeting_type = (
            classify_historical_heading(
                meeting_label
            )
        )

        if meeting_type is None:
            continue

        statement_url = urljoin(
            index_url,
            str(anchor["href"]).strip(),
        )

        decision_date = (
            parse_date_from_url(
                statement_url
            )
        )

        if decision_date is None:
            continue

        if decision_date.year != year:
            continue

        rows.append(
            {
                "decision_date": decision_date,
                "meeting_type": meeting_type,
                "meeting_label": meeting_label,
                "statement_url": statement_url,
                "index_url": index_url,
            }
        )

    return rows


def extract_modern_statement_links(
    *,
    html: str,
    index_url: str,
    start_year: int,
    end_year: int,
) -> list[dict[str, object]]:
    """
    Extract HTML policy-statement links from the modern FOMC calendar.

    Main policy statement URLs end in monetaryYYYYMMDDa.htm. PDF copies,
    implementation notes, minutes, projections, and press conferences are
    excluded.
    """
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    rows: list[dict[str, object]] = []

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        statement_url = urljoin(
            index_url,
            str(anchor["href"]).strip(),
        )

        filename = statement_url.rsplit(
            "/",
            maxsplit=1,
        )[-1]

        match = MODERN_STATEMENT_PATTERN.search(
            filename
        )

        if match is None:
            continue

        decision_date = datetime.strptime(
            match.group(1),
            "%Y%m%d",
        ).date()

        if not (
            start_year
            <= decision_date.year
            <= end_year
        ):
            continue

        rows.append(
            {
                "decision_date": decision_date,
                "meeting_type": "scheduled",
                "meeting_label": (
                    "Scheduled FOMC decision "
                    f"{decision_date.isoformat()}"
                ),
                "statement_url": statement_url,
                "index_url": index_url,
            }
        )

    return rows


def convert_clock_time(
    hour: int,
    minute: int,
    meridiem: str,
) -> str:
    """Convert a 12-hour clock time to project HH:MM format."""
    normalized_meridiem = (
        meridiem.lower()
        .replace(".", "")
        .replace(" ", "")
    )

    if hour < 1 or hour > 12:
        raise ValueError(
            f"Invalid 12-hour clock hour: {hour}"
        )

    if minute < 0 or minute > 59:
        raise ValueError(
            f"Invalid minute: {minute}"
        )

    if normalized_meridiem == "am":
        converted_hour = (
            0 if hour == 12 else hour
        )
    elif normalized_meridiem == "pm":
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


def parse_release_time(
    html: str,
) -> tuple[str | None, str | None]:
    """Extract an official release time from statement-page text."""
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    text = normalize_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    patterns = [
        (
            "official_for_release_at",
            re.compile(
                r"For release at\s+"
                r"(\d{1,2})"
                r"(?::(\d{2}))?\s*"
                r"([ap]\.?(?:\s*)m\.?)",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "official_released_at",
            re.compile(
                r"Released\b.{0,80}?\bat\s+"
                r"(\d{1,2})"
                r"(?::(\d{2}))?\s*"
                r"([ap]\.?(?:\s*)m\.?)",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "official_last_update",
            re.compile(
                r"Last\s+[Uu]pdate:"
                r".{0,100}?,\s*"
                r"(\d{1,2})"
                r"(?::(\d{2}))?\s*"
                r"([ap]\.?(?:\s*)m\.?)",
                flags=re.IGNORECASE,
            ),
        ),
    ]

    for time_source, pattern in patterns:
        match = pattern.search(
            text
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

    return None, None


def scheduled_time_fallback(
    decision_date: date,
    meeting_type: str,
) -> tuple[str | None, str]:
    """
    Apply conservative time fallbacks only where timing conventions are clear.

    Unscheduled actions are never assigned a generic scheduled-meeting time.
    The 2011-2012 period is also left blank because statement timing differed
    depending on whether a press conference was held.
    """
    if meeting_type != "scheduled":
        return (
            None,
            "official_page_date_only",
        )

    if decision_date >= date(
        2013,
        3,
        20,
    ):
        return (
            "14:00",
            "scheduled_rule_fallback_1400",
        )

    if (
        date(2011, 4, 27)
        <= decision_date
        <= date(2012, 12, 31)
    ):
        return (
            None,
            "official_page_date_only",
        )

    return (
        "14:15",
        "scheduled_rule_fallback_1415",
    )


def deduplicate_link_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Deduplicate statement links while preserving chronological order."""
    seen_urls: set[str] = set()
    unique_rows: list[
        dict[str, object]
    ] = []

    for row in sorted(
        rows,
        key=lambda item: (
            item["decision_date"],
            item["statement_url"],
        ),
    ):
        statement_url = str(
            row["statement_url"]
        )

        if statement_url in seen_urls:
            continue

        seen_urls.add(
            statement_url
        )

        unique_rows.append(
            row
        )

    return unique_rows


def collect_statement_links(
    *,
    session: requests.Session,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
    request_delay: float,
) -> tuple[
    list[dict[str, object]],
    list[bytes],
]:
    """Collect statement links from official Fed index pages."""
    rows: list[dict[str, object]] = []
    source_bytes: list[bytes] = []

    historical_end_year = min(
        end_year,
        2020,
    )

    if start_year <= historical_end_year:
        for year in range(
            start_year,
            historical_end_year + 1,
        ):
            index_url = (
                HISTORICAL_YEAR_URL_TEMPLATE.format(
                    year=year
                )
            )

            cache_path = (
                cache_dir
                / f"fomc_index_{year}.html"
            )

            (
                html,
                raw_content,
                final_url,
                downloaded,
            ) = fetch_html_with_cache(
                session=session,
                url=index_url,
                cache_path=cache_path,
                refresh=refresh,
                offline=offline,
            )

            source_bytes.append(
                raw_content
            )

            extracted = (
                extract_historical_statement_links(
                    html=html,
                    index_url=final_url,
                    year=year,
                )
            )

            rows.extend(
                extracted
            )

            print(
                f"FOMC {year}: "
                f"{len(extracted)} policy statements found"
            )

            if downloaded and request_delay > 0:
                time.sleep(
                    request_delay
                )

    modern_start_year = max(
        start_year,
        2021,
    )

    if modern_start_year <= end_year:
        cache_path = (
            cache_dir
            / "fomc_calendar_modern.html"
        )

        (
            html,
            raw_content,
            final_url,
            downloaded,
        ) = fetch_html_with_cache(
            session=session,
            url=MODERN_CALENDAR_URL,
            cache_path=cache_path,
            refresh=refresh,
            offline=offline,
        )

        source_bytes.append(
            raw_content
        )

        extracted = (
            extract_modern_statement_links(
                html=html,
                index_url=final_url,
                start_year=modern_start_year,
                end_year=end_year,
            )
        )

        rows.extend(
            extracted
        )

        print(
            "Modern calendar "
            f"{modern_start_year}-{end_year}: "
            f"{len(extracted)} policy statements found"
        )

        if downloaded and request_delay > 0:
            time.sleep(
                request_delay
            )

    return (
        deduplicate_link_rows(
            rows
        ),
        source_bytes,
    )


def build_decision_archive(
    *,
    statement_links: list[dict[str, object]],
    session: requests.Session,
    cache_dir: Path,
    refresh: bool,
    offline: bool,
    request_delay: float,
) -> tuple[
    pd.DataFrame,
    list[bytes],
]:
    """Fetch statement pages and construct the decision archive."""
    rows: list[dict[str, object]] = []
    statement_source_bytes: list[
        bytes
    ] = []

    total = len(
        statement_links
    )

    for position, link_row in enumerate(
        statement_links,
        start=1,
    ):
        decision_date = link_row[
            "decision_date"
        ]

        if not isinstance(
            decision_date,
            date,
        ):
            raise TypeError(
                "decision_date must be a date."
            )

        statement_url = str(
            link_row["statement_url"]
        )

        cache_path = (
            cache_dir
            / "statements"
            / cache_filename_for_statement(
                statement_url,
                decision_date,
            )
        )

        (
            html,
            raw_content,
            final_url,
            downloaded,
        ) = fetch_html_with_cache(
            session=session,
            url=statement_url,
            cache_path=cache_path,
            refresh=refresh,
            offline=offline,
        )

        statement_source_bytes.append(
            raw_content
        )

        release_time, time_source = (
            parse_release_time(
                html
            )
        )

        if release_time is None:
            (
                release_time,
                time_source,
            ) = scheduled_time_fallback(
                decision_date=decision_date,
                meeting_type=str(
                    link_row["meeting_type"]
                ),
            )

        if (
            time_source is not None
            and time_source.startswith(
                "official_"
            )
            and release_time is not None
        ):
            verification_status = (
                "official_statement_exact_time"
            )
        elif release_time is not None:
            verification_status = (
                "official_statement_rule_time"
            )
        else:
            verification_status = (
                "official_statement_date_only"
            )

        event_id = (
            "FED_FOMC_"
            f"{decision_date:%Y_%m_%d}"
        )

        notes = (
            "Public FOMC policy statement identified "
            "from an official Federal Reserve FOMC page. "
        )

        if release_time is None:
            notes += (
                "The exact release time was not reliably "
                "available, so no time was imputed."
            )
        elif (
            time_source is not None
            and time_source.startswith(
                "scheduled_rule_fallback"
            )
        ):
            notes += (
                "The statement page did not expose a machine-"
                "readable time; the documented scheduled-"
                "meeting convention was used as a fallback."
            )
        else:
            notes += (
                "The release time was extracted from the "
                "official statement page."
            )

        rows.append(
            {
                "event_id": event_id,
                "decision_date": (
                    decision_date.isoformat()
                ),
                "release_time_et": (
                    release_time
                    or ""
                ),
                "event_timezone": (
                    "America/New_York"
                ),
                "meeting_type": (
                    link_row[
                        "meeting_type"
                    ]
                ),
                "meeting_label": (
                    link_row[
                        "meeting_label"
                    ]
                ),
                "statement_url": final_url,
                "index_url": (
                    link_row[
                        "index_url"
                    ]
                ),
                "time_source": (
                    time_source
                    or "official_page_date_only"
                ),
                "verification_status": (
                    verification_status
                ),
                "notes": notes,
            }
        )

        if (
            position % 25 == 0
            or position == total
        ):
            print(
                "Statement pages processed: "
                f"{position}/{total}"
            )

        if downloaded and request_delay > 0:
            time.sleep(
                request_delay
            )

    archive = pd.DataFrame(
        rows,
        columns=OUTPUT_COLUMNS,
    )

    archive.sort_values(
        [
            "decision_date",
            "meeting_type",
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
        statement_source_bytes,
    )


def validate_decision_archive(
    *,
    archive: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> None:
    """Validate official FOMC decision records."""
    missing_columns = set(
        OUTPUT_COLUMNS
    ).difference(
        archive.columns
    )

    if missing_columns:
        raise ValueError(
            "FOMC archive is missing columns: "
            + ", ".join(
                sorted(missing_columns)
            )
        )

    if archive.empty:
        raise ValueError(
            "FOMC decision archive is empty."
        )

    if archive[
        "event_id"
    ].duplicated().any():
        duplicated = archive.loc[
            archive[
                "event_id"
            ].duplicated(
                keep=False
            ),
            "event_id",
        ].tolist()

        raise ValueError(
            "Duplicate FOMC event IDs: "
            + ", ".join(
                sorted(
                    set(duplicated)
                )
            )
        )

    decision_dates = pd.to_datetime(
        archive["decision_date"],
        errors="coerce",
    )

    if decision_dates.isna().any():
        raise ValueError(
            "FOMC archive contains invalid decision dates."
        )

    if not decision_dates.dt.year.between(
        start_year,
        end_year,
    ).all():
        raise ValueError(
            "FOMC archive contains dates outside "
            "the requested sample."
        )

    invalid_meeting_types = set(
        archive["meeting_type"]
    ).difference(
        {
            "scheduled",
            "unscheduled",
        }
    )

    if invalid_meeting_types:
        raise ValueError(
            "Unexpected FOMC meeting types: "
            + ", ".join(
                sorted(
                    invalid_meeting_types
                )
            )
        )

    invalid_times = archive.loc[
        ~archive[
            "release_time_et"
        ].astype(str).str.match(
            r"^(?:|[01]\d|2[0-3]):[0-5]\d$"
        ),
        "release_time_et",
    ].tolist()

    if invalid_times:
        raise ValueError(
            "Invalid FOMC release times: "
            + ", ".join(
                str(value)
                for value in invalid_times
            )
        )

    available_dates = {
        timestamp.date()
        for timestamp in decision_dates
    }

    applicable_known_dates = {
        known_date
        for known_date in KNOWN_POLICY_DATES
        if (
            start_year
            <= known_date.year
            <= end_year
        )
    }

    missing_known_dates = (
        applicable_known_dates
        - available_dates
    )

    if missing_known_dates:
        raise ValueError(
            "Known FOMC policy decisions are missing: "
            + ", ".join(
                sorted(
                    value.isoformat()
                    for value
                    in missing_known_dates
                )
            )
        )

    for year in range(
        max(start_year, 2000),
        end_year + 1,
    ):
        year_count = int(
            decision_dates.dt.year.eq(
                year
            ).sum()
        )

        if year_count < 8:
            raise ValueError(
                f"Only {year_count} FOMC statements "
                f"were found for {year}; expected at least 8."
            )


def build_macro_rows(
    archive: pd.DataFrame,
) -> pd.DataFrame:
    """Convert FOMC decisions to the project macro schema."""
    rows: list[dict[str, str]] = []

    for row in archive.itertuples(
        index=False
    ):
        if row.meeting_type == "scheduled":
            event_name = (
                "FOMC scheduled policy decision"
            )
        else:
            event_name = (
                "FOMC unscheduled policy decision"
            )

        rows.append(
            {
                "event_id": row.event_id,
                "event_date": (
                    row.decision_date
                ),
                "event_time_et": (
                    row.release_time_et
                ),
                "event_timezone": (
                    "America/New_York"
                ),
                "source": (
                    "Federal Reserve"
                ),
                "event_type": (
                    "fomc_decision"
                ),
                "event_name": event_name,
                "tier": "tier_1",
                "verification_status": (
                    row.verification_status
                ),
                "source_url": (
                    row.statement_url
                ),
                "notes": (
                    f"{row.meeting_label}. "
                    f"{row.notes}"
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
            "Generated duplicate FOMC macro event IDs."
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
    Replace historical FOMC rows idempotently.

    Scheduled 2026 rows and all non-FOMC events are preserved.
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
                sorted(missing_columns)
            )
        )

    registry = existing.copy()

    event_dates = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )

    replace_mask = (
        registry["event_type"]
        .astype(str)
        .eq("fomc_decision")
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
            "Duplicate event IDs after FOMC merge: "
            + ", ".join(
                sorted(
                    set(duplicated)
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
    start_year: int,
    end_year: int,
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
            "Historical public FOMC policy decisions"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "start_year": start_year,
        "end_year": end_year,
        "row_count": int(
            len(archive)
        ),
        "scheduled_count": int(
            archive["meeting_type"]
            .eq("scheduled")
            .sum()
        ),
        "unscheduled_count": int(
            archive["meeting_type"]
            .eq("unscheduled")
            .sum()
        ),
        "exact_time_count": int(
            archive["verification_status"]
            .eq(
                "official_statement_exact_time"
            )
            .sum()
        ),
        "rule_time_count": int(
            archive["verification_status"]
            .eq(
                "official_statement_rule_time"
            )
            .sum()
        ),
        "date_only_count": int(
            archive["verification_status"]
            .eq(
                "official_statement_date_only"
            )
            .sum()
        ),
        "minimum_decision_date": (
            archive["decision_date"].min()
        ),
        "maximum_decision_date": (
            archive["decision_date"].max()
        ),
        "source_pages_sha256": (
            source_hasher.hexdigest()
        ),
        "output_sha256": (
            hashlib.sha256(
                output_bytes
            ).hexdigest()
        ),
        "historical_url_template": (
            HISTORICAL_YEAR_URL_TEMPLATE
        ),
        "modern_calendar_url": (
            MODERN_CALENDAR_URL
        ),
        "cache_directory": str(
            cache_dir.resolve()
        ),
        "output_path": relative_output,
        "selection_rule": (
            "Public FOMC policy statements only. "
            "Historical conference calls without an "
            "official plain Statement link are excluded. "
            "Supplementary statements are excluded."
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
            "Import historical public FOMC policy "
            "decision statements from official "
            "Federal Reserve pages."
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

    statement_links, index_source_bytes = (
        collect_statement_links(
            session=session,
            cache_dir=args.cache_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            refresh=args.refresh,
            offline=args.offline,
            request_delay=args.request_delay,
        )
    )

    if not statement_links:
        raise RuntimeError(
            "No official FOMC policy statement "
            "links were discovered."
        )

    print(
        "Total unique policy statement links: "
        f"{len(statement_links)}"
    )

    archive, statement_source_bytes = (
        build_decision_archive(
            statement_links=statement_links,
            session=session,
            cache_dir=args.cache_dir,
            refresh=args.refresh,
            offline=args.offline,
            request_delay=args.request_delay,
        )
    )

    validate_decision_archive(
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
        start_year=args.start_year,
        end_year=args.end_year,
        source_documents=(
            index_source_bytes
            + statement_source_bytes
        ),
        cache_dir=args.cache_dir,
    )

    scheduled_count = int(
        archive["meeting_type"]
        .eq("scheduled")
        .sum()
    )

    unscheduled_count = int(
        archive["meeting_type"]
        .eq("unscheduled")
        .sum()
    )

    exact_time_count = int(
        archive["verification_status"]
        .eq(
            "official_statement_exact_time"
        )
        .sum()
    )

    rule_time_count = int(
        archive["verification_status"]
        .eq(
            "official_statement_rule_time"
        )
        .sum()
    )

    date_only_count = int(
        archive["verification_status"]
        .eq(
            "official_statement_date_only"
        )
        .sum()
    )

    print(
        "Historical FOMC policy registry imported."
    )

    print(
        f"Decision rows: {len(archive)}"
    )

    print(
        f"Scheduled decisions: {scheduled_count}"
    )

    print(
        f"Unscheduled decisions: {unscheduled_count}"
    )

    print(
        f"Exact official times: {exact_time_count}"
    )

    print(
        f"Rule-based time fallbacks: {rule_time_count}"
    )

    print(
        f"Date-only decisions: {date_only_count}"
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
