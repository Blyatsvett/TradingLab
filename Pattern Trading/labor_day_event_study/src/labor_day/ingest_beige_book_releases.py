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

YEAR_PAGE_TEMPLATE = (
    "https://www.federalreserve.gov/"
    "monetarypolicy/beigebook{year}.htm"
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
    / "beige_book_releases_1998_2025.csv"
)

DEFAULT_CACHE_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "beige_book_source_cache"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "beige_book_releases_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_beige_book.csv"
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
    "report_url",
    "year_page_url",
    "archive_label",
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

DATE_PATTERN = re.compile(
    rf"\b{MONTH_PATTERN}\s+([0-3]?\d)\b",
    flags=re.IGNORECASE,
)

STANDARD_RELEASE_TIME_ET = "14:00"

STANDARD_TIME_SOURCE = (
    "official_federal_reserve_standard_release_time"
)

STANDARD_VERIFICATION_STATUS = (
    "official_archive_date_standard_time"
)

# The current Federal Reserve 2003 annual index omits the September 3
# entry, although the official report remains available on the Board's
# website. Keep this as a narrow, source-linked archive exception.
KNOWN_ARCHIVE_OMISSIONS = {
    2003: [
        {
            "release_date": "2003-09-03",
            "report_url": (
                "https://www.federalreserve.gov/"
                "fomc/beigebook/2003/20030903/default.htm"
            ),
            "archive_label": (
                "September 3 HTML "
                "(official report omitted from current annual index)"
            ),
            "provenance_note": (
                "Exact release date and report URL from the official "
                "Federal Reserve September 3, 2003 report page; the "
                "current 2003 annual index omits this entry."
            ),
        }
    ]
}

# Beige Book releases are normally Wednesdays. October 12, 2006 is a
# documented Thursday exception on the official Federal Reserve archive.
KNOWN_NON_WEDNESDAY_RELEASES = {
    date(2006, 10, 12),
}


def create_http_session() -> requests.Session:
    """Create a retrying browser-like session for Federal Reserve pages."""
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
    """Collapse whitespace in parsed Federal Reserve labels."""
    return re.sub(
        r"\s+",
        " ",
        value.replace(
            "\xa0",
            " ",
        ),
    ).strip()


def year_page_url(year: int) -> str:
    """Return the official Federal Reserve Beige Book page for a year."""
    return YEAR_PAGE_TEMPLATE.format(
        year=year
    )


def parse_month_day(
    value: str,
    year: int,
) -> date | None:
    """Extract one month/day pair from a nearby archive label."""
    match = DATE_PATTERN.search(
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

    try:
        return date(
            year,
            month,
            day,
        )
    except ValueError:
        return None


def nearby_archive_label(
    anchor,
    year: int,
) -> tuple[str, date] | None:
    """
    Find the closest ancestor that contains the date paired with an HTML link.

    Older pages use table rows; newer pages may use compact div/list blocks.
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

        release_date = parse_month_day(
            text,
            year,
        )

        if release_date is None:
            continue

        # Prefer local row-like containers. The length guard prevents an
        # entire yearly table from being treated as a single release row.
        if (
            ancestor.name in {
                "tr",
                "li",
                "p",
            }
            or len(text) <= 160
        ):
            return (
                text,
                release_date,
            )

    return None


def is_report_html_link(
    *,
    anchor_text: str,
    absolute_url: str,
    year: int,
) -> bool:
    """Identify one report-level Beige Book HTML link."""
    if normalize_text(
        anchor_text
    ).lower() != "html":
        return False

    parsed = urlparse(
        absolute_url
    )
    path = parsed.path.lower()

    if parsed.netloc.lower() not in {
        "www.federalreserve.gov",
        "federalreserve.gov",
    }:
        return False

    if "beigebook" not in path:
        return False

    if not path.endswith(
        (
            ".htm",
            ".html",
        )
    ):
        return False

    yearly_page_names = {
        f"beigebook{year}.htm",
        f"beigebook{year}.html",
    }

    if Path(
        path
    ).name in yearly_page_names:
        return False

    return True


def parse_year_page(
    *,
    html: str,
    year: int,
    source_url: str,
) -> list[dict[str, str]]:
    """Parse one official annual Beige Book archive page."""
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    rows_by_date: dict[
        date,
        dict[str, str],
    ] = {}

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        absolute_url = urljoin(
            source_url,
            anchor["href"],
        )

        if not is_report_html_link(
            anchor_text=anchor.get_text(
                " ",
                strip=True,
            ),
            absolute_url=absolute_url,
            year=year,
        ):
            continue

        nearby = nearby_archive_label(
            anchor,
            year,
        )

        if nearby is None:
            continue

        archive_label, release_date = nearby

        rows_by_date[
            release_date
        ] = {
            "release_date": (
                release_date.isoformat()
            ),
            "report_url": absolute_url,
            "year_page_url": source_url,
            "archive_label": archive_label,
        }

    return [
        rows_by_date[
            release_date
        ]
        for release_date in sorted(
            rows_by_date
        )
    ]


def apply_known_archive_exceptions(
    *,
    year_rows: list[dict[str, str]],
    year: int,
    source_url: str,
) -> list[dict[str, str]]:
    """Add narrowly documented official releases omitted by an index page."""
    rows_by_date = {
        row["release_date"]: dict(row)
        for row in year_rows
    }

    for exception in KNOWN_ARCHIVE_OMISSIONS.get(
        year,
        [],
    ):
        release_date = exception[
            "release_date"
        ]

        if release_date in rows_by_date:
            continue

        rows_by_date[
            release_date
        ] = {
            "release_date": release_date,
            "report_url": exception[
                "report_url"
            ],
            "year_page_url": source_url,
            "archive_label": exception[
                "archive_label"
            ],
            "provenance_note": exception[
                "provenance_note"
            ],
        }

    return [
        rows_by_date[
            release_date
        ]
        for release_date in sorted(
            rows_by_date
        )
    ]


def fetch_cached_text(
    *,
    session: requests.Session,
    url: str,
    cache_path: Path,
    refresh: bool,
    offline: bool,
) -> tuple[str, bytes]:
    """Read an official year page from cache or download it."""
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

    for encoding in (
        "utf-8-sig",
        "cp1252",
        "latin-1",
    ):
        try:
            return (
                raw_content.decode(
                    encoding
                ),
                raw_content,
            )
        except UnicodeDecodeError:
            continue

    return (
        raw_content.decode(
            "utf-8",
            errors="replace",
        ),
        raw_content,
    )


def build_release_archive(
    *,
    session: requests.Session,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    refresh: bool,
    offline: bool,
) -> tuple[pd.DataFrame, list[bytes]]:
    """Build the complete historical Beige Book release archive."""
    rows: list[dict[str, str]] = []
    source_documents: list[bytes] = []

    for year in range(
        start_year,
        end_year + 1,
    ):
        source_url = year_page_url(
            year
        )
        cache_path = (
            cache_dir
            / f"beigebook_{year}.html"
        )

        html, raw_content = fetch_cached_text(
            session=session,
            url=source_url,
            cache_path=cache_path,
            refresh=refresh,
            offline=offline,
        )

        source_documents.append(
            raw_content
        )

        year_rows = parse_year_page(
            html=html,
            year=year,
            source_url=source_url,
        )

        year_rows = apply_known_archive_exceptions(
            year_rows=year_rows,
            year=year,
            source_url=source_url,
        )

        print(
            f"Beige Book {year}: "
            f"{len(year_rows)} releases"
        )

        for parsed_row in year_rows:
            release_date = date.fromisoformat(
                parsed_row[
                    "release_date"
                ]
            )

            rows.append(
                {
                    "event_id": (
                        "fed_beige_book_"
                        + release_date.strftime(
                            "%Y%m%d"
                        )
                    ),
                    "release_date": (
                        release_date.isoformat()
                    ),
                    "release_time_et": (
                        STANDARD_RELEASE_TIME_ET
                    ),
                    "event_timezone": (
                        "America/New_York"
                    ),
                    "report_url": (
                        parsed_row[
                            "report_url"
                        ]
                    ),
                    "year_page_url": (
                        parsed_row[
                            "year_page_url"
                        ]
                    ),
                    "archive_label": (
                        parsed_row[
                            "archive_label"
                        ]
                    ),
                    "time_source": (
                        STANDARD_TIME_SOURCE
                    ),
                    "verification_status": (
                        STANDARD_VERIFICATION_STATUS
                    ),
                    "notes": (
                        parsed_row.get(
                            "provenance_note",
                            (
                                "Exact release date and HTML report URL "
                                "from the official Federal Reserve annual "
                                "Beige Book archive."
                            ),
                        )
                        + " The 14:00 ET time is the Federal Reserve's "
                        "standard Beige Book publication time, used as "
                        "an explicit historical fallback."
                    ),
                }
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
    """Validate exact annual coverage and project invariants."""
    missing_columns = set(
        OUTPUT_COLUMNS
    ).difference(
        archive.columns
    )

    if missing_columns:
        raise ValueError(
            "Beige Book archive is missing columns: "
            + ", ".join(
                sorted(
                    missing_columns
                )
            )
        )

    if archive.empty:
        raise ValueError(
            "Beige Book archive is empty."
        )

    if archive[
        "event_id"
    ].duplicated().any():
        raise ValueError(
            "Beige Book archive contains duplicate event IDs."
        )

    release_dates = pd.to_datetime(
        archive[
            "release_date"
        ],
        errors="coerce",
    )

    if release_dates.isna().any():
        raise ValueError(
            "Beige Book archive contains invalid release dates."
        )

    if not release_dates.dt.year.between(
        start_year,
        end_year,
    ).all():
        raise ValueError(
            "Beige Book archive contains dates outside "
            "the requested sample."
        )

    release_date_values = release_dates.dt.date

    valid_weekday_mask = (
        release_dates.dt.weekday.eq(2)
        | release_date_values.isin(
            KNOWN_NON_WEDNESDAY_RELEASES
        )
    )

    if not valid_weekday_mask.all():
        invalid_dates = (
            release_dates.loc[
                ~valid_weekday_mask
            ]
            .dt.date.astype(str)
            .tolist()
        )

        raise ValueError(
            "Beige Book releases are expected on Wednesdays "
            "except for documented historical exceptions; "
            "unexpected dates: "
            + ", ".join(
                invalid_dates
            )
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

        if year_count != 8:
            raise ValueError(
                f"Beige Book {year} contains {year_count} "
                "releases; expected exactly 8."
            )

    expected_rows = (
        end_year
        - start_year
        + 1
    ) * 8

    if len(
        archive
    ) != expected_rows:
        raise ValueError(
            f"Beige Book archive contains {len(archive)} rows; "
            f"expected {expected_rows}."
        )

    if not archive[
        "release_time_et"
    ].eq(
        STANDARD_RELEASE_TIME_ET
    ).all():
        raise ValueError(
            "Unexpected Beige Book release time."
        )

    if not archive[
        "verification_status"
    ].eq(
        STANDARD_VERIFICATION_STATUS
    ).all():
        raise ValueError(
            "Unexpected Beige Book verification status."
        )

    if not archive[
        "report_url"
    ].astype(str).str.contains(
        "federalreserve.gov",
        case=False,
        regex=False,
    ).all():
        raise ValueError(
            "Non-Federal Reserve report URL found."
        )


def build_macro_rows(
    archive: pd.DataFrame,
) -> pd.DataFrame:
    """Convert the release archive to the project macro schema."""
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
                "source": (
                    "Federal Reserve"
                ),
                "event_type": (
                    "beige_book"
                ),
                "event_name": (
                    "Federal Reserve Beige Book"
                ),
                "tier": "tier_2",
                "verification_status": (
                    row.verification_status
                ),
                "source_url": (
                    row.report_url
                ),
                "notes": (
                    "Official annual archive date. "
                    "14:00 ET uses the documented Federal "
                    "Reserve standard Beige Book release time."
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
            "Generated duplicate Beige Book event IDs."
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
    Replace historical Beige Book rows idempotently.

    Forward 2026+ rows and every non-Beige-Book event are preserved.
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
            "beige_book"
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
            "Duplicate event IDs after Beige Book merge: "
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
    """Write hashes and source-selection metadata."""
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
            "Historical Federal Reserve Beige Book "
            "publication calendar"
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
        "row_count": int(
            len(
                archive
            )
        ),
        "rows_per_year": 8,
        "minimum_release_date": (
            release_dates.min().date().isoformat()
        ),
        "maximum_release_date": (
            release_dates.max().date().isoformat()
        ),
        "release_time_et": (
            STANDARD_RELEASE_TIME_ET
        ),
        "time_source": (
            STANDARD_TIME_SOURCE
        ),
        "verification_status": (
            STANDARD_VERIFICATION_STATUS
        ),
        "source_pages_sha256": (
            source_hasher.hexdigest()
        ),
        "output_sha256": hashlib.sha256(
            output_bytes
        ).hexdigest(),
        "year_page_template": (
            YEAR_PAGE_TEMPLATE
        ),
        "cache_directory": str(
            cache_dir.resolve()
        ),
        "output_path": (
            relative_output
        ),
        "selection_rule": (
            "One official HTML report link for each dated "
            "release on every annual Federal Reserve Beige "
            "Book archive page. Exact archive dates are used. "
            "The standard 2:00 p.m. ET publication time is "
            "recorded as an explicit historical fallback."
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
            "Import historical Federal Reserve Beige Book "
            "publication dates from official annual archives."
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
            "Redownload annual archive pages even when "
            "cached copies exist."
        ),
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Use cached official annual pages only."
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

    archive, source_documents = (
        build_release_archive(
            session=session,
            cache_dir=args.cache_dir,
            start_year=args.start_year,
            end_year=args.end_year,
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
        source_documents=source_documents,
        cache_dir=args.cache_dir,
    )

    print(
        "Historical Beige Book registry imported."
    )
    print(
        f"Release rows: {len(archive)}"
    )
    print(
        "Release time: "
        f"{STANDARD_RELEASE_TIME_ET} ET "
        "(standard-time fallback)"
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