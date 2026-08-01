from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from labor_day.contamination import load_macro_events


PROJECT_ROOT = Path(__file__).resolve().parents[2]

BEA_ARCHIVE_URL = "https://www.bea.gov/news/archive"
CENSUS_HISTORY_URL = (
    "https://www.census.gov/foreign-trade/"
    "Press-Release/ft900_index.html"
)
CENSUS_SCHEDULE_URL = (
    "https://www.census.gov/foreign-trade/schedule.html"
)

TITLE_QUERY = "U.S. International Trade in Goods and Services"

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
    / "international_trade_releases_1998_2025.csv"
)

DEFAULT_CACHE_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "international_trade_source_cache"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "international_trade_releases_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_international_trade.csv"
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
    "release_title",
    "release_url",
    "archive_url",
    "time_source",
    "verification_status",
    "notes",
]

MONTHS = {
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

REFERENCE_TITLE_PATTERN = re.compile(
    rf"""
    U\.?\s*S\.?
    \s+(?:International\s+)?Trade\s+in\s+Goods\s+and\s+Services
    (?:
        \s*[,;:\-]\s*
        |
        \s+for\s+
        |
        \s+
    )
    {MONTH_PATTERN}
    (?:\s+and\s+Annual)?
    \s+((?:19|20)\d{{2}})
    \b
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

FT900_REFERENCE_PATTERN = re.compile(
    r"""
    \bFT[\s\-–—]*900
    \s*
    \(
    (\d{2})
    \s*[-/]\s*
    (0[1-9]|1[0-2])
    \)
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

FULL_DATE_PATTERN = re.compile(
    rf"""
    \b{MONTH_PATTERN}
    \s+([0-3]?\d)
    ,?\s+
    ((?:19|20)\d{{2}})
    \b
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

TIME_PATTERN = re.compile(
    r"""
    (?:
        embargoed\s+until\s+release\s+at
        |
        not\s+to\s+be\s+released\s+before
        |
        release(?:d)?\s+at
        |
        for\s+release\s+at
        |
        for\s+wire\s+transmission
        |
        for\s+immediate\s+release(?:\s+at)?
    )
    [^0-9]{0,80}
    ([01]?\d)
    :
    ([0-5]\d)
    \s*
    (a\.?\s*m\.?|p\.?\s*m\.?)
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

BEA_RELEASE_PATH_PATTERN = re.compile(
    r"""
    ^(?:/index\.php)?/news/
    ((?:19|20)\d{2})
    /
    us-(?:international-)?trade-goods-and-services-
    .+
    $
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

STANDARD_RELEASE_TIME_ET = "08:30"
STANDARD_TIME_SOURCE = "official_census_schedule_standard_time"
EXACT_TIME_SOURCE = "official_bea_release_page"
EXACT_VERIFICATION_STATUS = "official_release_page_exact_time"
STANDARD_VERIFICATION_STATUS = "official_archive_date_standard_time"

EXPECTED_FULL_SAMPLE_REFERENCE_START = "1997-11"
EXPECTED_FULL_SAMPLE_REFERENCE_END = "2025-09"
EXPECTED_FULL_SAMPLE_ROWS = 335

KNOWN_OMISSION_DISCOVERY_SOURCE = (
    "official_census_ft900_pdf_known_bea_archive_omission"
)

# These six monthly releases are present in the complete official Census
# FT-900 history but absent from the current BEA news archive index.
# Each linked PDF states the exact release date, 08:30 ET time, and FT-900
# reference period on its first page.
KNOWN_ARCHIVE_OMISSIONS = {
    "2006-06": {
        "release_date": "2006-08-10",
        "release_url": (
            "https://www.census.gov/foreign-trade/"
            "Press-Release/ft900/ft900_0606.pdf"
        ),
    },
    "2006-12": {
        "release_date": "2007-02-13",
        "release_url": (
            "https://www.census.gov/foreign-trade/"
            "Press-Release/ft900/ft900_0612.pdf"
        ),
    },
    "2008-06": {
        "release_date": "2008-08-12",
        "release_url": (
            "https://www.census.gov/foreign-trade/"
            "Press-Release/ft900/ft900_0806.pdf"
        ),
    },
    "2011-04": {
        "release_date": "2011-06-09",
        "release_url": (
            "https://www.census.gov/foreign-trade/"
            "Press-Release/ft900/ft900_1104.pdf"
        ),
    },
    "2012-04": {
        "release_date": "2012-06-08",
        "release_url": (
            "https://www.census.gov/foreign-trade/"
            "Press-Release/ft900/ft900_1204.pdf"
        ),
    },
    "2013-04": {
        "release_date": "2013-06-04",
        "release_url": (
            "https://www.census.gov/foreign-trade/"
            "Press-Release/ft900/ft900_1304.pdf"
        ),
    },
}


def create_http_session() -> requests.Session:
    """Create a retrying browser-like session for official government pages."""
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
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        }
    )

    return session


def normalize_text(value: str) -> str:
    """Collapse whitespace and nonbreaking spaces."""
    return re.sub(
        r"\s+",
        " ",
        value.replace(
            "\xa0",
            " ",
        ),
    ).strip()


def archive_url_for_page(page: int = 0) -> str:
    """Return one unfiltered official BEA archive pagination URL."""
    if page < 0:
        raise ValueError("Archive page cannot be negative.")

    base = (
        f"{BEA_ARCHIVE_URL}"
        "?created_1=All"
        "&field_related_product_target_id=All"
        "&title="
    )

    if page == 0:
        return base

    return f"{base}&page={page}"


def archive_url_for_year(year: int) -> str:
    """
    Backward-compatible helper retained for stored test fixtures.

    BEA's year/keyword filters are no longer reliable enough for discovery,
    so live collection uses archive_url_for_page() and filters dates locally.
    """
    if year < 1900 or year > 2100:
        raise ValueError(f"Unexpected archive year: {year}")

    return archive_url_for_page(0)


def parse_reference_period(
    value: str,
) -> str | None:
    """Parse the statistical month from a monthly FT-900 release title."""
    match = REFERENCE_TITLE_PATTERN.search(
        normalize_text(
            value
        )
    )

    if match is None:
        return None

    month = MONTHS[
        match.group(1).lower()
    ]
    year = int(
        match.group(2)
    )

    return f"{year:04d}-{month:02d}"


def parse_release_page_reference_period(
    page_text: str,
) -> str | None:
    """
    Parse the statistical month from an official release page.

    Historical pages vary in title punctuation and sometimes shorten the
    product name to "U.S. Trade in Goods and Services." The FT-900 release
    number is used as an authoritative fallback.
    """
    normalized = normalize_text(
        page_text
    )

    title_reference = parse_reference_period(
        normalized
    )
    if title_reference is not None:
        return title_reference

    match = FT900_REFERENCE_PATTERN.search(
        normalized[:20000]
    )
    if match is None:
        return None

    year_two_digits = int(
        match.group(1)
    )
    month = int(
        match.group(2)
    )

    # The project sample is 1997-2025, so the two-digit FT-900 year is
    # unambiguous here. Keep the conventional pivot for unit reusability.
    year = (
        1900 + year_two_digits
        if year_two_digits >= 70
        else 2000 + year_two_digits
    )

    return f"{year:04d}-{month:02d}"


def parse_full_date(
    value: str,
) -> date | None:
    """Parse a full English month/day/year date."""
    match = FULL_DATE_PATTERN.search(
        normalize_text(
            value
        )
    )

    if match is None:
        return None

    month = MONTHS[
        match.group(1).lower()
    ]
    day = int(
        match.group(2)
    )
    year = int(
        match.group(3)
    )

    try:
        return date(
            year,
            month,
            day,
        )
    except ValueError:
        return None


def convert_clock_time(
    hour: int,
    minute: int,
    meridiem: str,
) -> str:
    """Convert a 12-hour clock value to HH:MM."""
    normalized_meridiem = (
        meridiem.lower()
        .replace(
            ".",
            "",
        )
        .replace(
            " ",
            "",
        )
    )

    if hour < 1 or hour > 12:
        raise ValueError(
            f"Invalid 12-hour clock hour: {hour}"
        )

    if minute < 0 or minute > 59:
        raise ValueError(
            f"Invalid clock minute: {minute}"
        )

    if normalized_meridiem == "am":
        hour_24 = 0 if hour == 12 else hour
    elif normalized_meridiem == "pm":
        hour_24 = 12 if hour == 12 else hour + 12
    else:
        raise ValueError(
            f"Unknown meridiem: {meridiem}"
        )

    return f"{hour_24:02d}:{minute:02d}"


def parse_release_time(
    page_text: str,
) -> str | None:
    """Parse the embargo/release clock time from a BEA release page."""
    match = TIME_PATTERN.search(
        page_text[:12000]
    )

    if match is None:
        return None

    return convert_clock_time(
        hour=int(
            match.group(1)
        ),
        minute=int(
            match.group(2)
        ),
        meridiem=match.group(3),
    )


def parse_release_header_date(
    page_text: str,
) -> date | None:
    """Parse the date attached to a release/embargo header."""
    header_patterns = [
        re.compile(
            rf"""
            (?:
                embargoed\s+until\s+release\s+at
                |
                not\s+to\s+be\s+released\s+before
                |
                release(?:d)?\s+at
                |
                for\s+release\s+at
                |
                for\s+wire\s+transmission
                |
                for\s+immediate\s+release(?:\s+at)?
            )
            .{{0,220}}?
            ({MONTH_PATTERN}\s+[0-3]?\d,?\s+(?:19|20)\d{{2}})
            """,
            flags=re.IGNORECASE | re.VERBOSE | re.DOTALL,
        ),
    ]

    for pattern in header_patterns:
        match = pattern.search(
            page_text[:12000]
        )

        if match is None:
            continue

        parsed = parse_full_date(
            match.group(1)
        )

        if parsed is not None:
            return parsed

    return None


def is_monthly_trade_release(
    *,
    title: str,
    absolute_url: str,
) -> bool:
    """Identify monthly FT-900 releases and exclude annual-only revisions."""
    normalized_title = normalize_text(
        title
    )

    if parse_reference_period(
        normalized_title
    ) is None:
        return False

    if re.search(
        r"\bAnnual\s+Revision\b",
        normalized_title,
        flags=re.IGNORECASE,
    ):
        return False

    parsed = urlparse(
        absolute_url
    )

    if parsed.netloc.lower() not in {
        "bea.gov",
        "www.bea.gov",
    }:
        return False

    return (
        BEA_RELEASE_PATH_PATTERN.match(
            parsed.path
        )
        is not None
    )


def is_approved_release_source(
    *,
    reference_period: str,
    release_url: str,
) -> bool:
    """Allow official BEA release pages and only documented Census fallbacks."""
    normalized_url = str(release_url).strip()
    parsed = urlparse(normalized_url)

    if (
        parsed.netloc.lower() in {
            "bea.gov",
            "www.bea.gov",
        }
        and BEA_RELEASE_PATH_PATTERN.match(parsed.path) is not None
    ):
        return True

    omission = KNOWN_ARCHIVE_OMISSIONS.get(
        str(reference_period)
    )

    return (
        omission is not None
        and normalized_url == omission["release_url"]
    )


def find_published_date_near_anchor(
    anchor,
) -> date | None:
    """
    Find the publication date paired with a release link in a BEA archive row.
    """
    for ancestor in anchor.parents:
        if ancestor.name in {
            "html",
            "body",
        }:
            break

        text = normalize_text(
            ancestor.get_text(
                " ",
                strip=True,
            )
        )

        parsed = parse_full_date(
            text
        )

        if parsed is None:
            continue

        if (
            ancestor.name in {
                "tr",
                "li",
                "article",
            }
            or "views-row" in (
                ancestor.get(
                    "class",
                    [],
                )
                or []
            )
            or len(
                text
            ) <= 280
        ):
            return parsed

    return None


def canonical_release_url(
    *,
    publication_year: int,
    title: str,
) -> str:
    """Construct the canonical BEA release URL from an archive title."""
    normalized = normalize_text(title)
    match = REFERENCE_TITLE_PATTERN.search(normalized)

    if match is None:
        raise ValueError(
            "Cannot construct a trade release URL from title: "
            f"{title}"
        )

    matched_title = match.group(0)
    suffix = re.sub(
        r"^U\.?\s*S\.?\s+(?:International\s+)?Trade\s+in\s+Goods\s+and\s+Services"
        r"(?:\s*[,;:\-]\s*|\s+for\s+|\s+)",
        "",
        matched_title,
        flags=re.IGNORECASE,
    )
    suffix = re.sub(
        r"[^a-z0-9]+",
        "-",
        suffix.lower(),
    ).strip("-")

    return (
        "https://www.bea.gov/news/"
        f"{publication_year}/"
        "us-international-trade-goods-and-services-"
        f"{suffix}"
    )


def reference_period_title(reference_period: str) -> str:
    """Return the canonical monthly FT-900 release title."""
    period = pd.Period(
        reference_period,
        freq="M",
    )
    return (
        "U.S. International Trade in Goods and Services, "
        + period.strftime("%B %Y")
    )


def candidate_release_urls(
    reference_period: str,
) -> list[str]:
    """
    Return official BEA URL variants for one missing reference month.

    Historical BEA slugs vary in three ways:
    - "us-international-trade..." versus shortened "us-trade...";
    - ordinary monthly pages versus April pages combined with annual revision;
    - publication year can equal the reference year or the following year.
    """
    period = pd.Period(
        reference_period,
        freq="M",
    )
    suffix = period.strftime(
        "%B-%Y"
    ).lower()

    slug_variants = [
        (
            "us-international-trade-goods-and-services-"
            f"{suffix}"
        ),
        (
            "us-trade-goods-and-services-"
            f"{suffix}"
        ),
        (
            "us-international-trade-goods-and-services-"
            f"{suffix}-us-international-trade-goods-and"
        ),
    ]

    urls: list[str] = []
    for publication_year in (
        period.year,
        period.year + 1,
    ):
        for slug in slug_variants:
            urls.append(
                "https://www.bea.gov/news/"
                f"{publication_year}/"
                f"{slug}"
            )

    return urls


def decode_html_bytes(raw_content: bytes) -> str:
    """Decode official government HTML with conservative fallbacks."""
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


def fetch_optional_cached(
    *,
    session: requests.Session,
    url: str,
    cache_path: Path,
    refresh: bool,
    offline: bool,
) -> tuple[str, bytes] | None:
    """Fetch a candidate page, treating an official 404 as a normal miss."""
    if (
        cache_path.exists()
        and not refresh
    ):
        raw_content = cache_path.read_bytes()
        return (
            decode_html_bytes(
                raw_content
            ),
            raw_content,
        )

    if offline:
        return None

    response = session.get(
        url,
        timeout=60,
    )

    if response.status_code == 404:
        return None

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
        decode_html_bytes(
            raw_content
        ),
        raw_content,
    )


def recovered_candidate_cache_filename(
    *,
    reference_period: str,
    candidate_url: str,
) -> str:
    """Keep URL variants in separate cache files to prevent collisions."""
    digest = hashlib.sha256(
        candidate_url.encode(
            "utf-8"
        )
    ).hexdigest()[:12]

    return (
        reference_period.replace(
            "-",
            "",
        )
        + "_"
        + digest
        + ".html"
    )


def known_archive_omission_entry(
    reference_period: str,
) -> dict[str, str] | None:
    """Return one explicitly verified Census PDF fallback, when required."""
    metadata = KNOWN_ARCHIVE_OMISSIONS.get(
        reference_period
    )

    if metadata is None:
        return None

    return {
        "release_date": metadata[
            "release_date"
        ],
        "reference_period": reference_period,
        "release_title": reference_period_title(
            reference_period
        ),
        "release_url": metadata[
            "release_url"
        ],
        "archive_url": CENSUS_HISTORY_URL,
        "discovery_source": (
            KNOWN_OMISSION_DISCOVERY_SOURCE
        ),
    }


def recover_reference_period_entry(
    *,
    session: requests.Session,
    cache_dir: Path,
    reference_period: str,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
) -> dict[str, str] | None:
    """Recover one archive-index omission from an official release source."""
    known_entry = known_archive_omission_entry(
        reference_period
    )

    if known_entry is not None:
        release_year = date.fromisoformat(
            known_entry["release_date"]
        ).year

        if (
            start_year
            <= release_year
            <= end_year
        ):
            return known_entry

        return None

    expected_title = reference_period_title(
        reference_period
    )

    candidate_cache_dir = (
        cache_dir
        / "recovered_candidates"
    )

    for candidate_url in candidate_release_urls(
        reference_period
    ):
        publication_year = int(
            urlparse(
                candidate_url
            ).path.split("/")[2]
        )

        if (
            publication_year < start_year
            or publication_year > end_year
        ):
            continue

        candidate_cache_path = (
            candidate_cache_dir
            / recovered_candidate_cache_filename(
                reference_period=reference_period,
                candidate_url=candidate_url,
            )
        )

        fetched = fetch_optional_cached(
            session=session,
            url=candidate_url,
            cache_path=candidate_cache_path,
            refresh=refresh,
            offline=offline,
        )

        if fetched is None:
            continue

        html, raw_content = fetched
        soup = BeautifulSoup(
            html,
            "html.parser",
        )
        page_text = soup.get_text(
            "\n",
            strip=True,
        )

        page_reference_period = parse_release_page_reference_period(
            page_text
        )
        release_date = parse_release_header_date(
            page_text
        )

        if page_reference_period != reference_period:
            continue

        if release_date is None:
            continue

        if not (
            start_year
            <= release_date.year
            <= end_year
        ):
            continue

        # Seed the normal release-page cache so the subsequent archive build
        # does not download this recovered page a second time.
        release_cache_path = (
            cache_dir
            / "release_pages"
            / (
                release_date.strftime(
                    "%Y%m%d"
                )
                + "_"
                + reference_period.replace(
                    "-",
                    "",
                )
                + ".html"
            )
        )
        release_cache_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        release_cache_path.write_bytes(
            raw_content
        )

        return {
            "release_date": release_date.isoformat(),
            "reference_period": reference_period,
            "release_title": expected_title,
            "release_url": candidate_url,
            "archive_url": CENSUS_HISTORY_URL,
            "discovery_source": (
                "official_bea_release_page_recovered_from_"
                "census_reference_month_sequence"
            ),
        }

    return None


def recover_missing_archive_entries(
    *,
    session: requests.Session,
    entries: list[dict[str, str]],
    cache_dir: Path,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
) -> list[dict[str, str]]:
    """Recover BEA archive-index omissions for the locked full sample."""
    if (
        start_year != 1998
        or end_year != 2025
    ):
        return entries

    expected_reference_periods = reference_period_range(
        EXPECTED_FULL_SAMPLE_REFERENCE_START,
        EXPECTED_FULL_SAMPLE_REFERENCE_END,
    )
    existing_reference_periods = {
        entry["reference_period"]
        for entry in entries
    }
    missing_reference_periods = [
        reference_period
        for reference_period in expected_reference_periods
        if reference_period not in existing_reference_periods
    ]

    if not missing_reference_periods:
        return entries

    print(
        "BEA archive-index omissions detected: "
        + ", ".join(
            missing_reference_periods
        )
    )

    recovered_entries: list[
        dict[str, str]
    ] = []

    for reference_period in missing_reference_periods:
        recovered = recover_reference_period_entry(
            session=session,
            cache_dir=cache_dir,
            reference_period=reference_period,
            start_year=start_year,
            end_year=end_year,
            refresh=refresh,
            offline=offline,
        )

        if recovered is None:
            raise ValueError(
                "Could not recover official BEA release page for "
                f"missing reference period {reference_period}."
            )

        recovered_entries.append(
            recovered
        )
        print(
            "Recovered missing international trade release: "
            f"{reference_period} -> "
            f"{recovered['release_date']}"
        )

    combined = entries + recovered_entries
    combined.sort(
        key=lambda row: (
            row["release_date"],
            row["reference_period"],
        )
    )
    return combined


def parse_last_archive_page(html: str) -> int:
    """Return the highest zero-based BEA archive page number advertised."""
    soup = BeautifulSoup(html, "html.parser")
    page_numbers = {0}

    for anchor in soup.find_all("a", href=True):
        absolute_url = urljoin(BEA_ARCHIVE_URL, anchor["href"])
        parsed = urlparse(absolute_url)

        if parsed.path.rstrip("/") != "/news/archive":
            continue

        values = parse_qs(parsed.query).get("page", [])
        for value in values:
            if value.isdigit():
                page_numbers.add(int(value))

    return max(page_numbers)


def archive_row_containers(soup: BeautifulSoup):
    """Yield row-like containers once, supporting old and modern BEA markup."""
    seen: set[int] = set()

    selectors = [
        "table tbody tr",
        "table tr",
        ".views-row",
        "article",
        "li",
    ]

    for selector in selectors:
        for container in soup.select(selector):
            identity = id(container)
            if identity in seen:
                continue
            seen.add(identity)
            yield container


def extract_trade_title(container) -> str | None:
    """Extract a monthly FT-900 title from one archive result container."""
    for anchor in container.find_all("a", href=True):
        title = normalize_text(anchor.get_text(" ", strip=True))
        if parse_reference_period(title) is not None:
            return title

    text = normalize_text(container.get_text(" ", strip=True))
    match = REFERENCE_TITLE_PATTERN.search(text)
    if match is None:
        return None

    return normalize_text(match.group(0))


def extract_release_url(
    *,
    container,
    title: str,
    publication_year: int,
    source_url: str,
) -> str:
    """Use the official archive link, with a canonical old-row fallback."""
    for anchor in container.find_all("a", href=True):
        anchor_title = normalize_text(anchor.get_text(" ", strip=True))
        absolute_url = urljoin(source_url, anchor["href"])

        if is_monthly_trade_release(
            title=anchor_title,
            absolute_url=absolute_url,
        ):
            return absolute_url

    return canonical_release_url(
        publication_year=publication_year,
        title=title,
    )


def parse_archive_page(
    *,
    html: str,
    source_url: str,
    start_year: int | None = None,
    end_year: int | None = None,
    year: int | None = None,
) -> list[dict[str, str]]:
    """Extract monthly trade releases from one unfiltered archive page."""
    # ``year`` remains accepted for backward-compatible unit fixtures.
    if year is not None:
        if start_year is not None or end_year is not None:
            raise ValueError(
                "Use either year or start_year/end_year, not both."
            )
        start_year = year
        end_year = year

    soup = BeautifulSoup(html, "html.parser")
    rows_by_reference: dict[str, dict[str, str]] = {}

    for container in archive_row_containers(soup):
        title = extract_trade_title(container)
        if title is None:
            continue

        reference_period = parse_reference_period(title)
        if reference_period is None:
            continue

        if re.search(
            r"\bAnnual\s+Revision\b",
            title,
            flags=re.IGNORECASE,
        ):
            continue

        container_text = normalize_text(
            container.get_text(" ", strip=True)
        )
        published_date = parse_full_date(container_text)
        if published_date is None:
            continue

        if start_year is not None and published_date.year < start_year:
            continue
        if end_year is not None and published_date.year > end_year:
            continue

        release_url = extract_release_url(
            container=container,
            title=title,
            publication_year=published_date.year,
            source_url=source_url,
        )

        if not is_monthly_trade_release(
            title=title,
            absolute_url=release_url,
        ):
            continue

        candidate = {
            "release_date": published_date.isoformat(),
            "reference_period": reference_period,
            "release_title": title,
            "release_url": release_url,
            "archive_url": source_url,
            "discovery_source": "official_bea_archive_index",
        }

        existing = rows_by_reference.get(reference_period)
        if existing is None:
            rows_by_reference[reference_period] = candidate
            continue

        # Prefer a directly linked archive URL over a constructed fallback.
        direct_link_present = any(
            is_monthly_trade_release(
                title=normalize_text(anchor.get_text(" ", strip=True)),
                absolute_url=urljoin(source_url, anchor["href"]),
            )
            for anchor in container.find_all("a", href=True)
        )
        if direct_link_present:
            rows_by_reference[reference_period] = candidate

    return sorted(
        rows_by_reference.values(),
        key=lambda row: (
            row["release_date"],
            row["reference_period"],
        ),
    )


def fetch_cached(
    *,
    session: requests.Session,
    url: str,
    cache_path: Path,
    refresh: bool,
    offline: bool,
) -> tuple[str, bytes]:
    """Read an official page from cache or download it."""
    if (
        cache_path.exists()
        and not refresh
    ):
        raw_content = cache_path.read_bytes()
    else:
        if offline:
            raise FileNotFoundError(
                "Offline mode requested but cache is missing: "
                f"{cache_path}"
            )

        response = session.get(
            url,
            timeout=60,
        )
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
        decode_html_bytes(
            raw_content
        ),
        raw_content,
    )


def fetch_cached_bytes(
    *,
    session: requests.Session,
    url: str,
    cache_path: Path,
    refresh: bool,
    offline: bool,
) -> bytes:
    """Read an official binary source from cache or download it."""
    if (
        cache_path.exists()
        and not refresh
    ):
        return cache_path.read_bytes()

    if offline:
        raise FileNotFoundError(
            "Offline mode requested but cache is missing: "
            f"{cache_path}"
        )

    response = session.get(
        url,
        timeout=60,
    )
    response.raise_for_status()
    raw_content = response.content

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    cache_path.write_bytes(
        raw_content
    )

    return raw_content


def collect_archive_entries(
    *,
    session: requests.Session,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
) -> tuple[list[dict[str, str]], list[bytes]]:
    """Crawl the official BEA archive and filter publication dates locally."""
    entries: list[dict[str, str]] = []
    source_documents: list[bytes] = []

    archive_cache_dir = cache_dir / "archive_pages"

    first_url = archive_url_for_page(0)
    first_cache_path = archive_cache_dir / "trade_archive_page_000.html"
    first_html, first_raw = fetch_cached(
        session=session,
        url=first_url,
        cache_path=first_cache_path,
        refresh=refresh,
        offline=offline,
    )

    last_page = parse_last_archive_page(first_html)
    print(
        "BEA archive pagination discovered: "
        f"pages 0 through {last_page}"
    )

    for page in range(0, last_page + 1):
        if page == 0:
            source_url = first_url
            html = first_html
            raw_content = first_raw
        else:
            source_url = archive_url_for_page(page)
            cache_path = (
                archive_cache_dir
                / f"trade_archive_page_{page:03d}.html"
            )
            html, raw_content = fetch_cached(
                session=session,
                url=source_url,
                cache_path=cache_path,
                refresh=refresh,
                offline=offline,
            )

        source_documents.append(raw_content)
        page_entries = parse_archive_page(
            html=html,
            source_url=source_url,
            start_year=start_year,
            end_year=end_year,
        )
        entries.extend(page_entries)

        if page == 0 or (page + 1) % 10 == 0 or page == last_page:
            print(
                "Scanned BEA archive pages: "
                f"{page + 1}/{last_page + 1}; "
                f"candidate monthly releases: {len(entries)}"
            )

    entries_by_reference: dict[str, dict[str, str]] = {}
    for entry in entries:
        reference_period = entry["reference_period"]
        existing = entries_by_reference.get(reference_period)

        if existing is None:
            entries_by_reference[reference_period] = entry
            continue

        if existing != entry:
            raise ValueError(
                "Conflicting BEA archive rows for reference period "
                f"{reference_period}: {existing} vs {entry}"
            )

    deduplicated = sorted(
        entries_by_reference.values(),
        key=lambda row: (
            row["release_date"],
            row["reference_period"],
        ),
    )

    deduplicated = recover_missing_archive_entries(
        session=session,
        entries=deduplicated,
        cache_dir=cache_dir,
        start_year=start_year,
        end_year=end_year,
        refresh=refresh,
        offline=offline,
    )

    counts_by_year: dict[int, int] = {
        year: 0
        for year in range(start_year, end_year + 1)
    }
    for entry in deduplicated:
        release_year = date.fromisoformat(
            entry["release_date"]
        ).year
        counts_by_year[release_year] += 1

    for year in range(start_year, end_year + 1):
        print(
            f"International trade publication year {year}: "
            f"{counts_by_year[year]} monthly releases"
        )

    return deduplicated, source_documents


def release_cache_filename(
    entry: dict[str, str],
) -> str:
    """Return a deterministic cache filename for one release source."""
    source_suffix = Path(
        urlparse(
            entry["release_url"]
        ).path
    ).suffix.lower()

    if source_suffix not in {
        ".html",
        ".htm",
        ".pdf",
    }:
        source_suffix = ".html"

    return (
        entry[
            "release_date"
        ].replace(
            "-",
            "",
        )
        + "_"
        + entry[
            "reference_period"
        ].replace(
            "-",
            ""
        )
        + source_suffix
    )


def build_release_archive(
    *,
    session: requests.Session,
    entries: list[dict[str, str]],
    cache_dir: Path,
    refresh: bool,
    offline: bool,
) -> tuple[pd.DataFrame, list[bytes]]:
    """Fetch release pages and build the verified historical calendar."""
    rows: list[
        dict[str, str]
    ] = []
    source_documents: list[
        bytes
    ] = []

    release_cache_dir = (
        cache_dir
        / "release_pages"
    )

    for index, entry in enumerate(
        entries,
        start=1,
    ):
        cache_path = (
            release_cache_dir
            / release_cache_filename(
                entry
            )
        )

        is_known_pdf_omission = (
            entry.get(
                "discovery_source"
            )
            == KNOWN_OMISSION_DISCOVERY_SOURCE
        )

        release_date = date.fromisoformat(
            entry[
                "release_date"
            ]
        )

        if is_known_pdf_omission:
            raw_content = fetch_cached_bytes(
                session=session,
                url=entry[
                    "release_url"
                ],
                cache_path=cache_path,
                refresh=refresh,
                offline=offline,
            )
            source_documents.append(
                raw_content
            )

            release_time = (
                STANDARD_RELEASE_TIME_ET
            )
            time_source = (
                "official_census_ft900_pdf"
            )
            verification_status = (
                EXACT_VERIFICATION_STATUS
            )
            notes = (
                "Exact publication date, reference period, and "
                "08:30 ET release time from the first page of the "
                "official Census/BEA FT-900 PDF. This monthly release "
                "is present in the complete Census FT-900 history but "
                "omitted from the current BEA news archive index."
            )
        else:
            html, raw_content = fetch_cached(
                session=session,
                url=entry[
                    "release_url"
                ],
                cache_path=cache_path,
                refresh=refresh,
                offline=offline,
            )

            source_documents.append(
                raw_content
            )

            soup = BeautifulSoup(
                html,
                "html.parser",
            )
            page_text = soup.get_text(
                "\n",
                strip=True,
            )

            parsed_time = parse_release_time(
                page_text
            )
            parsed_header_date = parse_release_header_date(
                page_text
            )

            if (
                parsed_header_date is not None
                and parsed_header_date != release_date
            ):
                raise ValueError(
                    "BEA archive/release-page date mismatch for "
                    f"{entry['release_url']}: archive={release_date}, "
                    f"page={parsed_header_date}"
                )

            if parsed_time is None:
                release_time = (
                    STANDARD_RELEASE_TIME_ET
                )
                time_source = (
                    STANDARD_TIME_SOURCE
                )
                verification_status = (
                    STANDARD_VERIFICATION_STATUS
                )
                if entry.get(
                    "discovery_source"
                ) == (
                    "official_bea_release_page_recovered_from_"
                    "census_reference_month_sequence"
                ):
                    notes = (
                        "Exact publication date and reference period from "
                        "the official BEA monthly release page. The month "
                        "was recovered because it is present in the official "
                        "Census FT-900 historical sequence but omitted from "
                        "the current BEA archive index. The 08:30 ET time "
                        "uses the official Census schedule standard because "
                        "no release-header time was parsed."
                    )
                else:
                    notes = (
                        "Exact publication date and reference period from "
                        "the official BEA archive/release page. The 08:30 "
                        "ET time uses the official Census FT-900 schedule "
                        "standard because no release-header time was parsed."
                    )
            else:
                release_time = parsed_time
                time_source = (
                    EXACT_TIME_SOURCE
                )
                verification_status = (
                    EXACT_VERIFICATION_STATUS
                )
                if entry.get(
                    "discovery_source"
                ) == (
                    "official_bea_release_page_recovered_from_"
                    "census_reference_month_sequence"
                ):
                    notes = (
                        "Exact publication date, reference period, and "
                        "release time from the official BEA monthly FT-900 "
                        "release page. The month was recovered because it "
                        "is present in the official Census FT-900 historical "
                        "sequence but omitted from the current BEA archive "
                        "index."
                    )
                else:
                    notes = (
                        "Exact publication date, reference period, and "
                        "release time from the official BEA archive and "
                        "monthly FT-900 release page."
                    )

        rows.append(
            {
                "event_id": (
                    "census_bea_trade_"
                    + release_date.strftime(
                        "%Y%m%d"
                    )
                ),
                "release_date": (
                    release_date.isoformat()
                ),
                "release_time_et": (
                    release_time
                ),
                "event_timezone": (
                    "America/New_York"
                ),
                "reference_period": (
                    entry[
                        "reference_period"
                    ]
                ),
                "release_title": (
                    entry[
                        "release_title"
                    ]
                ),
                "release_url": (
                    entry[
                        "release_url"
                    ]
                ),
                "archive_url": (
                    entry[
                        "archive_url"
                    ]
                ),
                "time_source": (
                    time_source
                ),
                "verification_status": (
                    verification_status
                ),
                "notes": notes,
            }
        )

        if (
            index % 25 == 0
            or index == len(
                entries
            )
        ):
            print(
                "Processed international trade releases: "
                f"{index}/{len(entries)}"
            )

    archive = pd.DataFrame(
        rows,
        columns=OUTPUT_COLUMNS,
    )

    archive.sort_values(
        [
            "release_date",
            "reference_period",
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


def reference_period_range(
    start: str,
    end: str,
) -> list[str]:
    """Generate an inclusive YYYY-MM monthly sequence."""
    start_period = pd.Period(
        start,
        freq="M",
    )
    end_period = pd.Period(
        end,
        freq="M",
    )

    return [
        str(
            period
        )
        for period in pd.period_range(
            start_period,
            end_period,
            freq="M",
        )
    ]


def validate_release_archive(
    *,
    archive: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> None:
    """Validate historical monthly coverage and project invariants."""
    missing_columns = set(
        OUTPUT_COLUMNS
    ).difference(
        archive.columns
    )

    if missing_columns:
        raise ValueError(
            "International trade archive is missing columns: "
            + ", ".join(
                sorted(
                    missing_columns
                )
            )
        )

    if archive.empty:
        raise ValueError(
            "International trade archive is empty."
        )

    if archive[
        "event_id"
    ].duplicated().any():
        raise ValueError(
            "International trade archive contains duplicate event IDs."
        )

    if archive[
        "reference_period"
    ].duplicated().any():
        raise ValueError(
            "International trade archive contains duplicate "
            "reference periods."
        )

    release_dates = pd.to_datetime(
        archive[
            "release_date"
        ],
        errors="coerce",
    )

    if release_dates.isna().any():
        raise ValueError(
            "International trade archive contains invalid release dates."
        )

    if not release_dates.dt.year.between(
        start_year,
        end_year,
    ).all():
        raise ValueError(
            "International trade archive contains dates outside "
            "the requested publication-year sample."
        )

    if release_dates.dt.weekday.ge(
        5
    ).any():
        invalid_dates = (
            release_dates.loc[
                release_dates.dt.weekday.ge(
                    5
                )
            ]
            .dt.date.astype(
                str
            )
            .tolist()
        )
        raise ValueError(
            "International trade releases must occur on weekdays; "
            "unexpected dates: "
            + ", ".join(
                invalid_dates
            )
        )

    if not archive[
        "release_time_et"
    ].eq(
        STANDARD_RELEASE_TIME_ET
    ).all():
        unexpected_times = sorted(
            set(
                archive.loc[
                    ~archive[
                        "release_time_et"
                    ].eq(
                        STANDARD_RELEASE_TIME_ET
                    ),
                    "release_time_et",
                ]
            )
        )
        raise ValueError(
            "Unexpected FT-900 release time(s): "
            + ", ".join(
                unexpected_times
            )
        )

    valid_statuses = {
        EXACT_VERIFICATION_STATUS,
        STANDARD_VERIFICATION_STATUS,
    }

    if not archive[
        "verification_status"
    ].isin(
        valid_statuses
    ).all():
        raise ValueError(
            "Unexpected international trade verification status."
        )

    for year in range(
        start_year,
        end_year + 1,
    ):
        year_count = int(
            release_dates.dt.year.eq(
                year
            ).sum()
        )

        if year_count < 10 or year_count > 14:
            raise ValueError(
                f"International trade publication year {year} "
                f"contains {year_count} releases; expected 10-14."
            )

    invalid_sources: list[str] = []

    for source_row in archive[[
        "reference_period",
        "release_url",
    ]].itertuples(index=False):
        if not is_approved_release_source(
            reference_period=str(
                source_row.reference_period
            ),
            release_url=str(
                source_row.release_url
            ),
        ):
            invalid_sources.append(
                f"{source_row.reference_period}={source_row.release_url}"
            )

    if invalid_sources:
        raise ValueError(
            "Unapproved international trade release URL(s): "
            + "; ".join(
                invalid_sources[:10]
            )
        )

    if archive[
        "release_title"
    ].astype(
        str
    ).str.contains(
        r"\bAnnual\s+Revision\b",
        case=False,
        regex=True,
    ).any():
        raise ValueError(
            "Standalone annual-revision notice entered monthly archive."
        )

    ordered_reference_periods = sorted(
        archive[
            "reference_period"
        ].tolist()
    )

    expected_sequence = reference_period_range(
        ordered_reference_periods[
            0
        ],
        ordered_reference_periods[
            -1
        ],
    )

    if ordered_reference_periods != expected_sequence:
        missing_periods = sorted(
            set(
                expected_sequence
            ).difference(
                ordered_reference_periods
            )
        )
        raise ValueError(
            "International trade reference-month sequence is not "
            "contiguous. Missing: "
            + ", ".join(
                missing_periods
            )
        )

    if (
        start_year == 1998
        and end_year == 2025
    ):
        if len(
            archive
        ) != EXPECTED_FULL_SAMPLE_ROWS:
            raise ValueError(
                f"Full international trade sample contains "
                f"{len(archive)} rows; expected "
                f"{EXPECTED_FULL_SAMPLE_ROWS}."
            )

        if ordered_reference_periods[
            0
        ] != EXPECTED_FULL_SAMPLE_REFERENCE_START:
            raise ValueError(
                "Unexpected full-sample first reference period: "
                + ordered_reference_periods[
                    0
                ]
            )

        if ordered_reference_periods[
            -1
        ] != EXPECTED_FULL_SAMPLE_REFERENCE_END:
            raise ValueError(
                "Unexpected full-sample final reference period: "
                + ordered_reference_periods[
                    -1
                ]
            )


def build_macro_rows(
    archive: pd.DataFrame,
) -> pd.DataFrame:
    """Convert the verified archive to the project macro-event schema."""
    rows: list[
        dict[str, str]
    ] = []

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
                "source": (
                    "Census/BEA"
                ),
                "event_type": (
                    "international_trade"
                ),
                "event_name": (
                    "U.S. International Trade in Goods and Services"
                ),
                "tier": "tier_1",
                "verification_status": (
                    row.verification_status
                ),
                "source_url": (
                    row.release_url
                ),
                "notes": (
                    "Monthly FT-900 release for reference period "
                    f"{row.reference_period}. "
                    + row.notes
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
            "Generated duplicate international trade event IDs."
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
    Replace historical international-trade rows idempotently.

    Every 2026+ row and every non-trade event is preserved.
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
        ].astype(
            str
        ).eq(
            "international_trade"
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
            "Duplicate event IDs after international trade merge: "
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
    """Write a CSV atomically through a temporary file."""
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


def combined_sha256(
    documents: list[bytes],
) -> str:
    """Hash an ordered list of source documents."""
    hasher = hashlib.sha256()

    for document in documents:
        hasher.update(
            document
        )

    return hasher.hexdigest()


def write_manifest(
    *,
    path: Path,
    archive: pd.DataFrame,
    output_path: Path,
    requested_start_year: int,
    requested_end_year: int,
    archive_documents: list[bytes],
    release_documents: list[bytes],
    cache_dir: Path,
) -> None:
    """Write source hashes and sample-selection metadata."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
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

    status_counts = (
        archive[
            "verification_status"
        ]
        .value_counts()
        .sort_index()
        .to_dict()
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
            "Historical U.S. International Trade in Goods "
            "and Services (FT-900) publication calendar"
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
        "selection_basis": (
            "Actual publication date on official BEA archive pages"
        ),
        "row_count": int(
            len(
                archive
            )
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
        "release_time_et": (
            STANDARD_RELEASE_TIME_ET
        ),
        "verification_status_counts": {
            str(
                key
            ): int(
                value
            )
            for key, value in status_counts.items()
        },
        "bea_archive_pages_sha256": (
            combined_sha256(
                archive_documents
            )
        ),
        "bea_release_pages_sha256": (
            combined_sha256(
                release_documents
            )
        ),
        "output_sha256": hashlib.sha256(
            output_bytes
        ).hexdigest(),
        "bea_archive_url": (
            BEA_ARCHIVE_URL
        ),
        "census_historical_releases_url": (
            CENSUS_HISTORY_URL
        ),
        "census_schedule_url": (
            CENSUS_SCHEDULE_URL
        ),
        "cache_directory": str(
            cache_dir.resolve()
        ),
        "output_path": (
            relative_output
        ),
        "selection_rule": (
            "Include monthly FT-900 releases whose actual publication "
            "date falls from the requested start year through end year. "
            "Use the official BEA news archive and release pages for "
            "indexed records, plus the exact official Census FT-900 PDFs "
            "for six documented BEA archive-index omissions. Exclude "
            "standalone annual-revision notices. Preserve late or "
            "shutdown-delayed releases on their actual publication dates. "
            "Use exact source times when available and the official Census "
            "08:30 ET standard only as an explicitly labelled fallback."
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
            "Import historical monthly U.S. International Trade "
            "in Goods and Services release dates from official "
            "BEA archive/release pages and verified Census FT-900 "
            "PDF fallbacks for documented archive omissions."
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
            "Redownload official archive and release pages even "
            "when cached copies exist."
        ),
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Use cached official pages only."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.start_year > args.end_year:
        raise ValueError(
            "start-year cannot exceed end-year."
        )

    session = create_http_session()

    existing_registry = load_macro_events(
        args.macro_registry
    )

    entries, archive_documents = (
        collect_archive_entries(
            session=session,
            cache_dir=args.cache_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            refresh=args.refresh,
            offline=args.offline,
        )
    )

    print(
        "Official monthly trade release links discovered: "
        f"{len(entries)}"
    )

    archive, release_documents = (
        build_release_archive(
            session=session,
            entries=entries,
            cache_dir=args.cache_dir,
            refresh=args.refresh,
            offline=args.offline,
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
        archive_documents=archive_documents,
        release_documents=release_documents,
        cache_dir=args.cache_dir,
    )

    exact_count = int(
        archive[
            "verification_status"
        ].eq(
            EXACT_VERIFICATION_STATUS
        ).sum()
    )
    fallback_count = int(
        archive[
            "verification_status"
        ].eq(
            STANDARD_VERIFICATION_STATUS
        ).sum()
    )

    print(
        "Historical international trade registry imported."
    )
    print(
        f"Release rows: {len(archive)}"
    )
    print(
        f"Exact release-page times: {exact_count}"
    )
    print(
        f"Standard-time fallbacks: {fallback_count}"
    )
    print(
        "Reference-period span: "
        f"{archive['reference_period'].min()} to "
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