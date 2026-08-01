from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from labor_day.contamination import load_macro_events


PROJECT_ROOT = Path(__file__).resolve().parents[2]

BEA_ARCHIVE_URL = "https://www.bea.gov/news/archive"

PRODUCTS = {
    "gdp": {
        "product_id": "451",
        "label": "Gross Domestic Product",
        "event_type": "gdp",
        "event_name": "Gross Domestic Product release",
    },
    "personal_income_outlays": {
        "product_id": "476",
        "label": "Personal Income and Outlays",
        "event_type": "personal_income_outlays",
        "event_name": "Personal Income and Outlays release",
    },
}

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
    / "bea_gdp_pio_releases_1998_2025.csv"
)

DEFAULT_CACHE_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "bea_source_cache"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "bea_gdp_pio_releases_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_bea.csv"
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
    "series",
    "release_variant",
    "reference_period",
    "release_title",
    "release_url",
    "archive_url",
    "archive_published_date",
    "time_source",
    "verification_status",
    "notes",
]

MONTH_NAMES = (
    "January|February|March|April|May|June|"
    "July|August|September|October|November|December"
)

ARCHIVE_DATE_PATTERN = re.compile(
    rf"\b(?P<month>{MONTH_NAMES})\s+"
    r"(?P<day>\d{1,2}),\s+"
    r"(?P<year>(?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)

RELEASE_HEADER_PATTERN = re.compile(
    r"(?:FOR\s+WIRE\s+TRANSMISSION|"
    r"EMBARGOED\s+UNTIL\s+RELEASE(?:\s+AT)?|"
    r"FOR\s+RELEASE(?:\s+AT)?)"
    r".{0,160}?"
    r"(?P<hour>\d{1,2})"
    r"(?::(?P<minute>\d{2}))?\s*"
    r"(?P<meridiem>[AP]\.?\s*M\.?)\s*"
    r"(?P<zone>EST|EDT|ET)\b"
    r".{0,180}?"
    rf"(?P<month>{MONTH_NAMES})\s+"
    r"(?P<day>\d{1,2}),\s+"
    r"(?P<year>(?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)

GDP_QUARTER_PATTERN = re.compile(
    r"\b(?P<quarter>1st|2nd|3rd|4th|"
    r"first|second|third|fourth)\s+quarter"
    r"(?:\s+and\s+year)?\s+"
    r"(?P<year>(?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)

PIO_PERIOD_PATTERN = re.compile(
    rf"\b(?P<month>{MONTH_NAMES})\s+"
    r"(?P<year>(?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)

PIO_COMBINED_PERIOD_PATTERN = re.compile(
    rf"\b(?P<first_month>{MONTH_NAMES})\s+and\s+"
    rf"(?P<second_month>{MONTH_NAMES})\s+"
    r"(?P<year>(?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)

TIME_PATTERN = re.compile(
    r"(?:[01]\d|2[0-3]):[0-5]\d"
)

GDP_VARIANTS = (
    ("advance", re.compile(r"\badvance\s+estimate\b", re.I)),
    ("second", re.compile(r"\bsecond\s+estimate\b", re.I)),
    ("third", re.compile(r"\bthird\s+estimate\b", re.I)),
    ("preliminary", re.compile(r"\bpreliminary\b", re.I)),
    ("final", re.compile(r"\bfinal\b", re.I)),
    ("initial", re.compile(r"\binitial\s+estimate\b", re.I)),
    ("updated", re.compile(r"\bupdated\s+estimate\b", re.I)),
    ("revised", re.compile(r"\brevised\s+estimate\b", re.I)),
)

REPLACE_EVENT_TYPES = {
    "gdp",
    "gross_domestic_product",
    "personal_income_outlays",
    "personal_income_and_outlays",
}


def normalize_text(value: str) -> str:
    """Collapse whitespace and normalize common nonbreaking characters."""
    return re.sub(
        r"\s+",
        " ",
        value.replace("\xa0", " "),
    ).strip()


def create_http_session() -> requests.Session:
    """Create a polite retrying session for official BEA pages."""
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

    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry),
    )
    session.headers.update(
        {
            "User-Agent": (
                "labor-day-event-study/1.0 "
                "(historical macro research; official BEA pages)"
            )
        }
    )
    return session


def archive_page_url(product_id: str, page: int) -> str:
    """Build a stable, explicit archive URL for logging and manifests."""
    query = urlencode(
        {
            "created_1": "All",
            "field_related_product_target_id": product_id,
            "page": page,
            "title": "",
        }
    )
    return f"{BEA_ARCHIVE_URL}?{query}"


def fetch_cached_document(
    *,
    session: requests.Session,
    url: str,
    cache_path: Path,
    refresh: bool,
    offline: bool,
    request_delay: float,
) -> tuple[bytes, bool]:
    """Read a cached source document or download it atomically."""
    if cache_path.exists() and not refresh:
        return cache_path.read_bytes(), False

    if offline:
        raise FileNotFoundError(
            f"Offline mode requires cached source: {cache_path}"
        )

    response = session.get(
        url,
        timeout=60,
    )
    response.raise_for_status()

    raw_content = response.content
    if not raw_content:
        raise RuntimeError(f"Empty BEA response: {url}")

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary_path = cache_path.with_suffix(
        cache_path.suffix + ".tmp"
    )
    temporary_path.write_bytes(raw_content)
    temporary_path.replace(cache_path)

    if request_delay > 0:
        time.sleep(request_delay)

    return raw_content, True


def parse_human_date(value: str) -> date | None:
    """Parse a US month-name date from arbitrary surrounding text."""
    match = ARCHIVE_DATE_PATTERN.search(value)
    if match is None:
        return None

    return datetime.strptime(
        (
            f"{match.group('month')} "
            f"{match.group('day')}, "
            f"{match.group('year')}"
        ),
        "%B %d, %Y",
    ).date()


def is_target_release_title(
    *,
    series: str,
    title: str,
) -> bool:
    """Select regular national GDP or PIO news releases only."""
    normalized = normalize_text(title).casefold()

    if series == "gdp":
        excluded_prefixes = (
            "gross domestic product by ",
            "gdp by ",
        )
        if normalized.startswith(excluded_prefixes):
            return False

        excluded_fragments = (
            "puerto rico",
            "guam",
            "american samoa",
            "virgin islands",
            "northern mariana",
            "u.s. territories",
        )
        if any(
            fragment in normalized
            for fragment in excluded_fragments
        ):
            return False

        return (
            normalized.startswith("gross domestic product")
            or normalized.startswith("gdp (")
        )

    if series == "personal_income_outlays":
        accepted_prefixes = (
            "personal income and outlays",
            "personal income,",
        )
        if not normalized.startswith(
            accepted_prefixes
        ):
            return False

        excluded_fragments = (
            "data update",
            "technical update",
            "errata",
            "by state",
            "by county",
            "metropolitan area",
        )
        return not any(
            fragment in normalized
            for fragment in excluded_fragments
        )

    raise ValueError(f"Unknown BEA series: {series}")


def find_release_container(anchor: object) -> object:
    """Find the nearest archive result container around an anchor."""
    for tag_name in (
        "tr",
        "article",
        "li",
        "div",
    ):
        parent = anchor.find_parent(tag_name)
        if parent is not None:
            return parent
    return anchor.parent


def parse_archive_page(
    *,
    html: str,
    index_url: str,
    series: str,
) -> tuple[list[dict[str, object]], bool]:
    """Extract target release links and listed publication dates."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, object]] = []
    seen_urls: set[str] = set()

    for anchor in soup.select("a[href]"):
        title = normalize_text(
            anchor.get_text(" ", strip=True)
        )
        if not title:
            continue

        if not is_target_release_title(
            series=series,
            title=title,
        ):
            continue

        release_url = urljoin(
            index_url,
            str(anchor.get("href")),
        )

        if "/news/" not in release_url:
            continue

        if release_url in seen_urls:
            continue
        seen_urls.add(release_url)

        container = find_release_container(anchor)
        container_text = normalize_text(
            container.get_text(" ", strip=True)
        )
        published_date = parse_human_date(
            container_text
        )

        rows.append(
            {
                "series": series,
                "release_title": title,
                "release_url": release_url,
                "archive_url": index_url,
                "archive_published_date": published_date,
            }
        )

    has_next_page = any(
        "next page" in normalize_text(
            anchor.get_text(" ", strip=True)
        ).casefold()
        for anchor in soup.select("a[href]")
    )

    return rows, has_next_page


def collect_release_links(
    *,
    session: requests.Session,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
    request_delay: float,
    max_pages: int,
) -> tuple[list[dict[str, object]], list[bytes]]:
    """Collect product-filtered BEA archive links for both series."""
    collected: list[dict[str, object]] = []
    source_documents: list[bytes] = []

    archive_cache_dir = cache_dir / "archive_pages"

    for series, product in PRODUCTS.items():
        product_rows: list[dict[str, object]] = []

        for page in range(max_pages):
            url = archive_page_url(
                product["product_id"],
                page,
            )
            cache_path = (
                archive_cache_dir
                / (
                    f"{series}_{product['product_id']}_"
                    f"page_{page:02d}.html"
                )
            )

            raw_content, _ = fetch_cached_document(
                session=session,
                url=url,
                cache_path=cache_path,
                refresh=refresh,
                offline=offline,
                request_delay=request_delay,
            )
            source_documents.append(raw_content)

            rows, has_next_page = parse_archive_page(
                html=raw_content.decode(
                    "utf-8",
                    errors="replace",
                ),
                index_url=url,
                series=series,
            )
            product_rows.extend(rows)

            print(
                f"BEA {series} archive page {page + 1}: "
                f"{len(rows)} target links"
            )

            if not has_next_page:
                break
        else:
            raise RuntimeError(
                f"BEA archive pagination exceeded {max_pages} "
                f"pages for {series}."
            )

        deduplicated: dict[str, dict[str, object]] = {}
        for row in product_rows:
            deduplicated[str(row["release_url"])] = row

        for row in deduplicated.values():
            published_date = row["archive_published_date"]
            if (
                isinstance(published_date, date)
                and start_year
                <= published_date.year
                <= end_year
            ):
                collected.append(row)

        print(
            f"BEA {series}: {len(deduplicated)} unique "
            "archive links discovered; "
            f"{sum(1 for row in deduplicated.values() if isinstance(row['archive_published_date'], date) and start_year <= row['archive_published_date'].year <= end_year)} "
            "fall inside the requested release years"
        )

    collected.sort(
        key=lambda row: (
            row["archive_published_date"] or date.min,
            str(row["series"]),
            str(row["release_url"]),
        )
    )
    return collected, source_documents


def convert_clock_time(
    hour: int,
    minute: int,
    meridiem: str,
) -> str:
    """Convert an official 12-hour clock time to HH:MM."""
    normalized_meridiem = re.sub(
        r"[^apm]",
        "",
        meridiem.casefold(),
    )

    if not 1 <= hour <= 12:
        raise ValueError(f"Invalid 12-hour clock hour: {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"Invalid minute: {minute}")

    if normalized_meridiem == "am":
        converted_hour = 0 if hour == 12 else hour
    elif normalized_meridiem == "pm":
        converted_hour = 12 if hour == 12 else hour + 12
    else:
        raise ValueError(f"Invalid meridiem: {meridiem}")

    return f"{converted_hour:02d}:{minute:02d}"


def parse_release_header(
    html: str,
) -> tuple[date | None, str | None, str | None]:
    """Parse the official date and time printed on a BEA release page."""
    soup = BeautifulSoup(html, "html.parser")
    text = normalize_text(
        soup.get_text(" ", strip=True)
    )

    match = RELEASE_HEADER_PATTERN.search(text)
    if match is None:
        return None, None, None

    release_date = datetime.strptime(
        (
            f"{match.group('month')} "
            f"{match.group('day')}, "
            f"{match.group('year')}"
        ),
        "%B %d, %Y",
    ).date()

    release_time = convert_clock_time(
        int(match.group("hour")),
        int(match.group("minute") or 0),
        match.group("meridiem"),
    )

    return (
        release_date,
        release_time,
        "official_release_page_header",
    )


def canonical_page_title(
    *,
    html: str,
    fallback: str,
) -> str:
    """Prefer the page H1 where it is a recognizable target title."""
    soup = BeautifulSoup(html, "html.parser")
    for heading in soup.find_all("h1"):
        title = normalize_text(
            heading.get_text(" ", strip=True)
        )
        if title and title.casefold() != "news release":
            return title
    return fallback


def classify_gdp_variant(title: str) -> str:
    """Classify the estimate label while preserving historical terminology."""
    normalized = normalize_text(title)
    for label, pattern in GDP_VARIANTS:
        if pattern.search(normalized):
            return label
    return "unspecified"


def parse_reference_period(
    *,
    series: str,
    title: str,
) -> str:
    """Extract the quarter or month represented by the release title."""
    normalized = normalize_text(title)

    if series == "gdp":
        match = GDP_QUARTER_PATTERN.search(normalized)
        if match is None:
            return ""

        quarter_lookup = {
            "1st": "Q1",
            "first": "Q1",
            "2nd": "Q2",
            "second": "Q2",
            "3rd": "Q3",
            "third": "Q3",
            "4th": "Q4",
            "fourth": "Q4",
        }
        quarter = quarter_lookup[
            match.group("quarter").casefold()
        ]
        return f"{match.group('year')}-{quarter}"

    if series == "personal_income_outlays":
        periods: list[str] = []

        combined_match = (
            PIO_COMBINED_PERIOD_PATTERN.search(normalized)
        )
        if combined_match is not None:
            combined_year = combined_match.group("year")
            for month_group in (
                "first_month",
                "second_month",
            ):
                parsed = datetime.strptime(
                    (
                        f"{combined_match.group(month_group)} "
                        f"{combined_year}"
                    ),
                    "%B %Y",
                )
                period = parsed.strftime("%Y-%m")
                if period not in periods:
                    periods.append(period)

        for match in PIO_PERIOD_PATTERN.finditer(normalized):
            parsed = datetime.strptime(
                (
                    f"{match.group('month')} "
                    f"{match.group('year')}"
                ),
                "%B %Y",
            )
            period = parsed.strftime("%Y-%m")
            if period not in periods:
                periods.append(period)

        return ";".join(periods)

    raise ValueError(f"Unknown BEA series: {series}")


def build_event_id(
    *,
    series: str,
    release_date: date,
) -> str:
    """Build a stable series-and-date identifier."""
    prefix = (
        "BEA_GDP"
        if series == "gdp"
        else "BEA_PIO"
    )
    return f"{prefix}_{release_date:%Y_%m_%d}"


def release_cache_path(
    *,
    cache_dir: Path,
    release_url: str,
) -> Path:
    """Map a release URL to a deterministic cache filename."""
    digest = hashlib.sha256(
        release_url.encode("utf-8")
    ).hexdigest()[:20]
    return cache_dir / "release_pages" / f"{digest}.html"


def build_release_archive(
    *,
    release_links: list[dict[str, object]],
    session: requests.Session,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
    request_delay: float,
) -> tuple[pd.DataFrame, list[bytes]]:
    """Download and normalize official BEA release pages."""
    rows: list[dict[str, str]] = []
    source_documents: list[bytes] = []
    total = len(release_links)

    for position, link in enumerate(
        release_links,
        start=1,
    ):
        release_url = str(link["release_url"])
        cache_path = release_cache_path(
            cache_dir=cache_dir,
            release_url=release_url,
        )
        raw_content, _ = fetch_cached_document(
            session=session,
            url=release_url,
            cache_path=cache_path,
            refresh=refresh,
            offline=offline,
            request_delay=request_delay,
        )
        source_documents.append(raw_content)

        html = raw_content.decode(
            "utf-8",
            errors="replace",
        )
        header_date, header_time, time_source = (
            parse_release_header(html)
        )

        archive_date = link["archive_published_date"]
        if header_date is not None:
            release_date = header_date
            release_time = header_time or ""
            verification_status = (
                "official_release_page_exact_time"
                if release_time
                else "official_release_page_date_only"
            )
            notes = (
                "Release date and time parsed from the official "
                "BEA release-page header."
            )
        elif isinstance(archive_date, date):
            release_date = archive_date
            release_time = ""
            time_source = "official_archive_published_date"
            verification_status = "official_archive_date_only"
            notes = (
                "Release-page header could not be parsed; official "
                "BEA archive publication date retained without an "
                "assumed clock time."
            )
        else:
            raise ValueError(
                "BEA release has neither a parseable page header nor "
                f"an archive date: {release_url}"
            )

        if not start_year <= release_date.year <= end_year:
            continue

        series = str(link["series"])
        title = canonical_page_title(
            html=html,
            fallback=str(link["release_title"]),
        )

        if not is_target_release_title(
            series=series,
            title=title,
        ):
            continue

        release_variant = (
            classify_gdp_variant(title)
            if series == "gdp"
            else "monthly"
        )
        reference_period = parse_reference_period(
            series=series,
            title=title,
        )

        rows.append(
            {
                "event_id": build_event_id(
                    series=series,
                    release_date=release_date,
                ),
                "release_date": release_date.isoformat(),
                "release_time_et": release_time,
                "event_timezone": "America/New_York",
                "series": series,
                "release_variant": release_variant,
                "reference_period": reference_period,
                "release_title": title,
                "release_url": release_url,
                "archive_url": str(link["archive_url"]),
                "archive_published_date": (
                    archive_date.isoformat()
                    if isinstance(archive_date, date)
                    else ""
                ),
                "time_source": time_source or "",
                "verification_status": verification_status,
                "notes": notes,
            }
        )

        if position % 25 == 0 or position == total:
            print(
                "BEA release pages processed: "
                f"{position}/{total}"
            )

    archive = pd.DataFrame(
        rows,
        columns=OUTPUT_COLUMNS,
    )

    if not archive.empty:
        exact_rank = archive[
            "verification_status"
        ].eq(
            "official_release_page_exact_time"
        ).astype(int)
        archive = (
            archive.assign(_exact_rank=exact_rank)
            .sort_values(
                [
                    "event_id",
                    "_exact_rank",
                    "release_url",
                ],
                ascending=[True, False, True],
            )
            .drop_duplicates(
                subset=["event_id"],
                keep="first",
            )
            .drop(columns=["_exact_rank"])
            .sort_values(
                [
                    "release_date",
                    "release_time_et",
                    "series",
                    "event_id",
                ]
            )
            .reset_index(drop=True)
        )

    return archive, source_documents


def validate_release_archive(
    *,
    archive: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> None:
    """Validate the normalized GDP and PIO release archive."""
    missing_columns = set(OUTPUT_COLUMNS).difference(
        archive.columns
    )
    if missing_columns:
        raise ValueError(
            "BEA archive is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    if archive.empty:
        raise ValueError("BEA release archive is empty.")

    duplicated = archive.loc[
        archive["event_id"].duplicated(keep=False),
        "event_id",
    ].tolist()
    if duplicated:
        raise ValueError(
            "Duplicate BEA event IDs: "
            + ", ".join(sorted(set(duplicated)))
        )

    release_dates = pd.to_datetime(
        archive["release_date"],
        errors="coerce",
    )
    if release_dates.isna().any():
        raise ValueError(
            "BEA archive contains invalid release dates."
        )

    if not release_dates.dt.year.between(
        start_year,
        end_year,
    ).all():
        raise ValueError(
            "BEA archive contains release dates outside "
            "the requested sample."
        )

    invalid_series = set(archive["series"]).difference(
        PRODUCTS
    )
    if invalid_series:
        raise ValueError(
            "Unexpected BEA series: "
            + ", ".join(sorted(invalid_series))
        )

    release_times = (
        archive["release_time_et"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    valid_time_mask = release_times.str.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d|",
        na=False,
    )
    invalid_times = archive.loc[
        ~valid_time_mask,
        "release_time_et",
    ].tolist()
    if invalid_times:
        raise ValueError(
            "Invalid BEA release times: "
            + ", ".join(str(value) for value in invalid_times)
        )

    for year in range(start_year, end_year + 1):
        year_rows = archive.loc[
            release_dates.dt.year.eq(year)
        ]
        missing_year_series = set(PRODUCTS).difference(
            year_rows["series"]
        )
        if missing_year_series:
            raise ValueError(
                f"BEA archive is missing {year} series: "
                + ", ".join(sorted(missing_year_series))
            )


def build_macro_rows(
    archive: pd.DataFrame,
) -> pd.DataFrame:
    """Convert BEA release records to the project macro schema."""
    rows: list[dict[str, str]] = []

    for row in archive.itertuples(index=False):
        product = PRODUCTS[row.series]
        details = []
        if row.reference_period:
            details.append(
                f"Reference period: {row.reference_period}."
            )
        if row.series == "gdp":
            details.append(
                f"Estimate label: {row.release_variant}."
            )
        details.append(row.notes)

        rows.append(
            {
                "event_id": row.event_id,
                "event_date": row.release_date,
                "event_time_et": row.release_time_et,
                "event_timezone": "America/New_York",
                "source": "Bureau of Economic Analysis",
                "event_type": product["event_type"],
                "event_name": product["event_name"],
                "tier": "tier_1",
                "verification_status": (
                    row.verification_status
                ),
                "source_url": row.release_url,
                "notes": " ".join(details),
            }
        )

    macro_rows = pd.DataFrame(
        rows,
        columns=MACRO_COLUMNS,
    )

    if macro_rows["event_id"].duplicated().any():
        raise ValueError(
            "Generated duplicate BEA macro event IDs."
        )

    return macro_rows


def merge_macro_registry(
    *,
    existing: pd.DataFrame,
    historical_rows: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """Replace historical BEA GDP/PIO rows while preserving 2026+."""
    missing_columns = set(MACRO_COLUMNS).difference(
        existing.columns
    )
    if missing_columns:
        raise ValueError(
            "Existing registry is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    registry = existing.copy()
    event_dates = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )

    replace_mask = (
        registry["event_type"]
        .astype(str)
        .isin(REPLACE_EVENT_TYPES)
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
            historical_rows[MACRO_COLUMNS],
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
    merged.reset_index(drop=True, inplace=True)

    duplicated = merged.loc[
        merged["event_id"].duplicated(keep=False),
        "event_id",
    ].tolist()
    if duplicated:
        raise ValueError(
            "Duplicate event IDs after BEA merge: "
            + ", ".join(sorted(set(duplicated)))
        )

    return merged


def atomic_write_csv(
    dataframe: pd.DataFrame,
    path: Path,
) -> None:
    """Write a CSV through a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )
    dataframe.to_csv(
        temporary_path,
        index=False,
        encoding="utf-8",
    )
    temporary_path.replace(path)


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
    """Write hashes, counts, source rules, and reproducibility metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)

    source_hasher = hashlib.sha256()
    for raw_content in source_documents:
        source_hasher.update(raw_content)

    output_bytes = archive.to_csv(index=False).encode(
        "utf-8"
    )

    try:
        relative_output = str(
            output_path.resolve().relative_to(
                PROJECT_ROOT.resolve()
            )
        )
    except ValueError:
        relative_output = str(output_path.resolve())

    series_counts = {
        str(key): int(value)
        for key, value in archive[
            "series"
        ].value_counts().sort_index().items()
    }
    exact_count = int(
        archive["verification_status"]
        .eq("official_release_page_exact_time")
        .sum()
    )
    date_only_count = int(len(archive) - exact_count)

    manifest = {
        "dataset": (
            "Historical BEA national GDP and Personal Income "
            "and Outlays releases"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "start_year": start_year,
        "end_year": end_year,
        "row_count": int(len(archive)),
        "series_counts": series_counts,
        "exact_time_count": exact_count,
        "date_only_count": date_only_count,
        "minimum_release_date": str(
            archive["release_date"].min()
        ),
        "maximum_release_date": str(
            archive["release_date"].max()
        ),
        "source_pages_sha256": source_hasher.hexdigest(),
        "output_sha256": hashlib.sha256(
            output_bytes
        ).hexdigest(),
        "archive_url": BEA_ARCHIVE_URL,
        "product_ids": {
            series: product["product_id"]
            for series, product in PRODUCTS.items()
        },
        "cache_directory": str(cache_dir.resolve()),
        "output_path": relative_output,
        "selection_rule": (
            "Official BEA national GDP estimate releases and "
            "regular Personal Income and Outlays releases only. "
            "State, county, territorial, and standalone data-update "
            "notices are excluded. Release-page header dates and "
            "times are preferred; archive publication dates are "
            "retained without assumed times when headers cannot be "
            "parsed."
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
    temporary_path.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import historical national GDP and Personal Income "
            "and Outlays release dates from official BEA pages."
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
            "Redownload official BEA pages even when cached "
            "copies exist."
        ),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use cached official BEA pages only.",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.05,
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
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
    if args.max_pages < 1:
        raise ValueError(
            "max-pages must be positive."
        )

    session = create_http_session()
    existing_registry = load_macro_events(
        args.macro_registry
    )

    release_links, archive_source_bytes = (
        collect_release_links(
            session=session,
            cache_dir=args.cache_dir,
            start_year=args.start_year,
            end_year=args.end_year,
            refresh=args.refresh,
            offline=args.offline,
            request_delay=args.request_delay,
            max_pages=args.max_pages,
        )
    )

    if not release_links:
        raise RuntimeError(
            "No official BEA GDP or PIO release links were "
            "discovered for the requested years."
        )

    print(
        "Total BEA release links inside requested years: "
        f"{len(release_links)}"
    )

    archive, release_source_bytes = (
        build_release_archive(
            release_links=release_links,
            session=session,
            cache_dir=args.cache_dir,
            start_year=args.start_year,
            end_year=args.end_year,
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

    historical_rows = build_macro_rows(archive)
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

    atomic_write_csv(archive, args.output)
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
            archive_source_bytes
            + release_source_bytes
        ),
        cache_dir=args.cache_dir,
    )

    series_counts = archive[
        "series"
    ].value_counts()
    exact_count = int(
        archive["verification_status"]
        .eq("official_release_page_exact_time")
        .sum()
    )
    date_only_count = int(len(archive) - exact_count)

    print("Historical BEA release registry imported.")
    print(f"Release rows: {len(archive)}")
    print(
        "GDP releases: "
        f"{int(series_counts.get('gdp', 0))}"
    )
    print(
        "Personal Income and Outlays releases: "
        f"{int(series_counts.get('personal_income_outlays', 0))}"
    )
    print(f"Exact official times: {exact_count}")
    print(f"Date-only releases: {date_only_count}")
    print(
        "Registry rows before: "
        f"{len(existing_registry)}"
    )
    print(
        "Registry rows after: "
        f"{len(merged_registry)}"
    )
    print(f"Archive output: {args.output}")
    print(f"Registry: {args.macro_registry}")
    print(f"Manifest: {args.manifest_output}")
    print(f"Source cache: {args.cache_dir}")


if __name__ == "__main__":
    main()