from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
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
    / "bls_price_index_releases_1998_2025.csv"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests"
    / "bls_price_index_releases_manifest.json"
)

DEFAULT_BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events_before_historical_price_indexes.csv"
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

ARCHIVE_COLUMNS = [
    "series",
    "event_id",
    "release_date",
    "release_time_et",
    "event_timezone",
    "reference_month",
    "reference_year",
    "source_format",
    "source_url",
    "archive_index_url",
    "verification_status",
    "notes",
]

MONTH_PATTERN = (
    r"January|February|March|April|May|June|"
    r"July|August|September|October|November|December"
)

FORMAT_RANK = {
    ".htm": 0,
    ".html": 0,
    ".txt": 1,
    ".pdf": 2,
}


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    slug: str
    archive_url: str
    release_label: str
    event_type: str
    event_id_prefix: str
    expected_count: int


SERIES_SPECS = {
    "cpi": SeriesSpec(
        key="cpi",
        slug="cpi",
        archive_url=(
            "https://www.bls.gov/bls/news-release/cpi.htm"
        ),
        release_label="Consumer Price Index",
        event_type="cpi",
        event_id_prefix="BLS_CPI",
        expected_count=335,
    ),
    "ppi": SeriesSpec(
        key="ppi",
        slug="ppi",
        archive_url=(
            "https://www.bls.gov/bls/news-release/ppi.htm"
        ),
        release_label="Producer Price Index",
        event_type="ppi",
        event_id_prefix="BLS_PPI",
        expected_count=334,
    ),
}

KNOWN_RELEASES = {
    "cpi": {
        (
            date(1998, 10, 16),
            "September",
            1998,
        ),
        (
            date(2024, 9, 11),
            "August",
            2024,
        ),
        (
            date(2025, 9, 11),
            "August",
            2025,
        ),
        (
            date(2025, 10, 24),
            "September",
            2025,
        ),
    },
    "ppi": {
        (
            date(1998, 10, 15),
            "September",
            1998,
        ),
        (
            date(2024, 9, 12),
            "August",
            2024,
        ),
        (
            date(2025, 9, 10),
            "August",
            2025,
        ),
        (
            date(2025, 11, 25),
            "September",
            2025,
        ),
    },
}


def create_http_session() -> requests.Session:
    """Create a retrying session for optional direct downloads."""
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

    session = requests.Session()

    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry),
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
    url: str,
    timeout_seconds: int = 60,
) -> tuple[str, bytes]:
    """Download a BLS archive index."""
    session = create_http_session()

    response = session.get(
        url,
        timeout=timeout_seconds,
    )

    response.raise_for_status()

    if not response.content:
        raise RuntimeError(
            f"BLS archive response was empty: {url}"
        )

    response.encoding = (
        response.apparent_encoding
        or "utf-8"
    )

    return response.text, response.content


def decode_html_bytes(
    raw_content: bytes,
) -> str:
    """Decode browser-saved HTML using common encodings."""
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


def load_local_html(
    path: Path,
) -> tuple[str, bytes]:
    """Load a locally saved BLS archive page."""
    if not path.exists():
        raise FileNotFoundError(
            f"Local BLS archive file not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"BLS archive path is not a file: {path}"
        )

    raw_content = path.read_bytes()

    if not raw_content:
        raise RuntimeError(
            f"BLS archive file is empty: {path}"
        )

    return (
        decode_html_bytes(raw_content),
        raw_content,
    )


def release_link_pattern(
    spec: SeriesSpec,
) -> re.Pattern[str]:
    """Create the archive filename matcher for one series."""
    return re.compile(
        rf"{re.escape(spec.slug)}_"
        rf"(\d{{6}}|\d{{8}})"
        rf"\.(htm|html|txt|pdf)$",
        flags=re.IGNORECASE,
    )


def reference_period_pattern(
    spec: SeriesSpec,
) -> re.Pattern[str]:
    """Create the reference-period matcher for one series."""
    return re.compile(
        rf"\b({MONTH_PATTERN})\s+"
        rf"(\d{{4}})\s+"
        rf"{re.escape(spec.release_label)}\b",
        flags=re.IGNORECASE,
    )


def parse_release_date_from_url(
    url: str,
    spec: SeriesSpec,
) -> date | None:
    """
    Parse a publication date from a BLS archive filename.

    Historical filenames use MMDDYY. Modern filenames use MMDDYYYY.
    """
    filename = Path(
        urlparse(url).path
    ).name

    match = release_link_pattern(
        spec
    ).search(filename)

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
    spec: SeriesSpec,
) -> tuple[str, int] | None:
    """Parse the reference month and year from archive link text."""
    match = reference_period_pattern(
        spec
    ).search(text)

    if match is None:
        return None

    return (
        match.group(1).title(),
        int(match.group(2)),
    )


def archive_link_context(
    link,
) -> str:
    """Get the archive-list text surrounding an anchor."""
    container = link.find_parent("li")

    if container is None:
        container = link.find_parent(
            [
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


def extract_series_archive(
    html: str,
    spec: SeriesSpec,
    start_year: int = 1998,
    end_year: int = 2025,
) -> pd.DataFrame:
    """
    Extract actual publication dates for one BLS price-index series.

    HTML is preferred over TXT, and TXT over PDF, where duplicate
    representations exist for the same release.
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
            spec.archive_url,
            href,
        )

        release_date = (
            parse_release_date_from_url(
                source_url,
                spec,
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
                context,
                spec,
            )
        )

        if reference_period is None:
            reference_month = ""
            reference_year = pd.NA
        else:
            (
                reference_month,
                reference_year,
            ) = reference_period

        extension = Path(
            urlparse(source_url).path
        ).suffix.lower()

        event_id = (
            f"{spec.event_id_prefix}_"
            f"{release_date:%Y_%m_%d}"
        )

        candidates.append(
            {
                "series": spec.key,
                "event_id": event_id,
                "release_date": (
                    release_date.isoformat()
                ),
                "release_time_et": "08:30",
                "event_timezone": (
                    "America/New_York"
                ),
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
                "archive_index_url": (
                    spec.archive_url
                ),
                "verification_status": (
                    "official_archive"
                ),
                "notes": (
                    "Actual publication date extracted "
                    "from the official BLS archive index."
                ),
                "_format_rank": (
                    FORMAT_RANK.get(
                        extension,
                        99,
                    )
                ),
            }
        )

    if not candidates:
        raise RuntimeError(
            f"No {spec.release_label} archive links were found. "
            "Confirm that the locally saved file is the complete "
            "official BLS archive page."
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

    return archive[
        ARCHIVE_COLUMNS
    ]


def validate_series_archive(
    archive: pd.DataFrame,
    spec: SeriesSpec,
    start_year: int,
    end_year: int,
) -> None:
    """Validate one official BLS archive extract."""
    missing_columns = set(
        ARCHIVE_COLUMNS
    ).difference(
        archive.columns
    )

    if missing_columns:
        raise ValueError(
            f"{spec.key.upper()} archive is missing columns: "
            + ", ".join(
                sorted(missing_columns)
            )
        )

    if archive.empty:
        raise ValueError(
            f"{spec.key.upper()} archive is empty."
        )

    if not archive[
        "series"
    ].eq(spec.key).all():
        raise ValueError(
            f"Unexpected series value in {spec.key.upper()} archive."
        )

    if archive[
        "release_date"
    ].duplicated().any():
        raise ValueError(
            f"Duplicate {spec.key.upper()} release dates."
        )

    if archive[
        "event_id"
    ].duplicated().any():
        raise ValueError(
            f"Duplicate {spec.key.upper()} event IDs."
        )

    dates = pd.to_datetime(
        archive["release_date"],
        errors="coerce",
    )

    if dates.isna().any():
        raise ValueError(
            f"Invalid {spec.key.upper()} release dates."
        )

    if (
        dates.dt.weekday >= 5
    ).any():
        bad_dates = archive.loc[
            dates.dt.weekday >= 5,
            "release_date",
        ].tolist()

        raise ValueError(
            f"{spec.key.upper()} weekend release dates: "
            + ", ".join(bad_dates)
        )

    missing_reference = (
        archive["reference_month"]
        .astype(str)
        .str.strip()
        .eq("")
        | archive["reference_year"].isna()
    )

    if missing_reference.any():
        bad_dates = archive.loc[
            missing_reference,
            "release_date",
        ].tolist()

        raise ValueError(
            f"{spec.key.upper()} releases missing reference periods: "
            + ", ".join(bad_dates)
        )

    if not archive[
        "release_time_et"
    ].eq("08:30").all():
        raise ValueError(
            f"{spec.key.upper()} releases must use 08:30 ET."
        )

    if not archive[
        "verification_status"
    ].eq("official_archive").all():
        raise ValueError(
            f"Unexpected {spec.key.upper()} verification status."
        )

    if (
        start_year == 1998
        and end_year == 2025
        and len(archive)
        != spec.expected_count
    ):
        raise ValueError(
            f"Expected {spec.expected_count} "
            f"{spec.key.upper()} releases dated 1998-2025, "
            f"but extracted {len(archive)}."
        )

    actual_releases = {
        (
            pd.Timestamp(row.release_date).date(),
            str(row.reference_month),
            int(row.reference_year),
        )
        for row in archive.itertuples(
            index=False
        )
    }

    applicable_known = {
        item
        for item in KNOWN_RELEASES[
            spec.key
        ]
        if (
            start_year
            <= item[0].year
            <= end_year
        )
    }

    missing_known = (
        applicable_known
        - actual_releases
    )

    if missing_known:
        formatted = [
            (
                f"{release_date.isoformat()} "
                f"({reference_month} {reference_year})"
            )
            for (
                release_date,
                reference_month,
                reference_year,
            ) in sorted(missing_known)
        ]

        raise ValueError(
            f"Known {spec.key.upper()} releases missing: "
            + "; ".join(formatted)
        )


def combine_archives(
    archives: list[pd.DataFrame],
) -> pd.DataFrame:
    """Combine CPI and PPI archive extracts."""
    combined = pd.concat(
        archives,
        ignore_index=True,
    )

    combined.sort_values(
        [
            "release_date",
            "series",
            "event_id",
        ],
        inplace=True,
    )

    combined.reset_index(
        drop=True,
        inplace=True,
    )

    if combined[
        "event_id"
    ].duplicated().any():
        duplicated = combined.loc[
            combined[
                "event_id"
            ].duplicated(
                keep=False
            ),
            "event_id",
        ].tolist()

        raise ValueError(
            "Duplicate price-index event IDs: "
            + ", ".join(
                sorted(
                    set(duplicated)
                )
            )
        )

    return combined[
        ARCHIVE_COLUMNS
    ]


def build_macro_rows(
    archive: pd.DataFrame,
) -> pd.DataFrame:
    """Convert the archive extract to the project macro schema."""
    rows: list[dict[str, str]] = []

    for row in archive.itertuples(
        index=False
    ):
        spec = SERIES_SPECS[
            row.series
        ]

        reference_period = (
            f"{row.reference_month} "
            f"{int(row.reference_year)}"
        )

        rows.append(
            {
                "event_id": row.event_id,
                "event_date": (
                    row.release_date
                ),
                "event_time_et": "08:30",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "BLS",
                "event_type": (
                    spec.event_type
                ),
                "event_name": (
                    f"{spec.release_label} "
                    f"for {reference_period}"
                ),
                "tier": "tier_1",
                "verification_status": (
                    "official_archive"
                ),
                "source_url": (
                    row.source_url
                ),
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
            "Generated duplicate price-index event IDs."
        )

    return macro_rows


def merge_macro_registry(
    existing: pd.DataFrame,
    historical_rows: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """
    Idempotently replace historical CPI and PPI rows.

    Existing 2026 scheduled rows and all other events are preserved.
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

    dates = pd.to_datetime(
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
        .isin(
            {
                "cpi",
                "ppi",
            }
        )
        & dates.dt.year.between(
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
            "Duplicate event IDs after price-index merge: "
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
    path: Path,
    *,
    archive: pd.DataFrame,
    output_path: Path,
    start_year: int,
    end_year: int,
    sources: dict[str, dict[str, object]],
) -> None:
    """Write source hashes and output metadata."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_bytes = archive.to_csv(
        index=False
    ).encode("utf-8")

    source_records: dict[
        str,
        dict[str, object],
    ] = {}

    for key, source in sources.items():
        raw_content = source[
            "raw_content"
        ]

        source_file = source.get(
            "source_file"
        )

        source_records[key] = {
            "archive_url": (
                SERIES_SPECS[
                    key
                ].archive_url
            ),
            "source_kind": (
                source[
                    "source_kind"
                ]
            ),
            "source_file": (
                str(
                    Path(
                        source_file
                    ).resolve()
                )
                if source_file is not None
                else None
            ),
            "source_sha256": (
                hashlib.sha256(
                    raw_content
                ).hexdigest()
            ),
            "row_count": int(
                archive[
                    "series"
                ].eq(key).sum()
            ),
        }

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
            "Historical BLS CPI and PPI release dates"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "start_year": start_year,
        "end_year": end_year,
        "release_time_et": "08:30",
        "verification_status": (
            "official_archive"
        ),
        "total_row_count": int(
            len(archive)
        ),
        "cpi_row_count": int(
            archive[
                "series"
            ].eq("cpi").sum()
        ),
        "ppi_row_count": int(
            archive[
                "series"
            ].eq("ppi").sum()
        ),
        "minimum_release_date": (
            archive[
                "release_date"
            ].min()
        ),
        "maximum_release_date": (
            archive[
                "release_date"
            ].max()
        ),
        "output_sha256": (
            hashlib.sha256(
                output_bytes
            ).hexdigest()
        ),
        "output_path": relative_output,
        "sources": source_records,
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
            "Import historical CPI and PPI release dates "
            "from official BLS archive pages."
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
        "--cpi-html",
        type=Path,
        default=None,
        help=(
            "Locally saved official CPI archive HTML."
        ),
    )

    parser.add_argument(
        "--ppi-html",
        type=Path,
        default=None,
        help=(
            "Locally saved official PPI archive HTML."
        ),
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
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )

    return parser.parse_args()


def obtain_source(
    *,
    spec: SeriesSpec,
    local_path: Path | None,
) -> tuple[
    str,
    bytes,
    str,
    Path | None,
]:
    """Load a local archive page or attempt a direct download."""
    if local_path is not None:
        html, raw_content = (
            load_local_html(
                local_path
            )
        )

        return (
            html,
            raw_content,
            "local_official_html",
            local_path,
        )

    try:
        html, raw_content = (
            fetch_archive_index(
                spec.archive_url
            )
        )

        return (
            html,
            raw_content,
            "direct_http",
            None,
        )

    except requests.HTTPError as exc:
        raise RuntimeError(
            f"BLS rejected the automated {spec.key.upper()} "
            "archive download. Save the official archive page "
            "locally and supply its path."
        ) from exc


def main() -> None:
    args = parse_args()

    if args.start_year > args.end_year:
        raise ValueError(
            "start-year cannot exceed end-year."
        )

    existing_registry = load_macro_events(
        args.macro_registry
    )

    local_paths = {
        "cpi": args.cpi_html,
        "ppi": args.ppi_html,
    }

    archives: list[pd.DataFrame] = []
    source_metadata: dict[
        str,
        dict[str, object],
    ] = {}

    for key, spec in SERIES_SPECS.items():
        (
            html,
            raw_content,
            source_kind,
            source_file,
        ) = obtain_source(
            spec=spec,
            local_path=local_paths[key],
        )

        if source_file is not None:
            print(
                f"Using locally saved {key.upper()} archive:"
            )
            print(source_file)

        archive = extract_series_archive(
            html=html,
            spec=spec,
            start_year=args.start_year,
            end_year=args.end_year,
        )

        validate_series_archive(
            archive=archive,
            spec=spec,
            start_year=args.start_year,
            end_year=args.end_year,
        )

        archives.append(
            archive
        )

        source_metadata[key] = {
            "raw_content": raw_content,
            "source_kind": source_kind,
            "source_file": source_file,
        }

    combined_archive = combine_archives(
        archives
    )

    historical_rows = build_macro_rows(
        combined_archive
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
        combined_archive,
        args.output,
    )

    atomic_write_csv(
        merged_registry,
        args.macro_registry,
    )

    write_manifest(
        args.manifest_output,
        archive=combined_archive,
        output_path=args.output,
        start_year=args.start_year,
        end_year=args.end_year,
        sources=source_metadata,
    )

    cpi_count = int(
        combined_archive[
            "series"
        ].eq("cpi").sum()
    )

    ppi_count = int(
        combined_archive[
            "series"
        ].eq("ppi").sum()
    )

    print(
        "Historical BLS price-index registry imported."
    )

    print(
        f"CPI archive rows: {cpi_count}"
    )

    print(
        f"PPI archive rows: {ppi_count}"
    )

    print(
        "Total historical rows inserted: "
        f"{len(historical_rows)}"
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


if __name__ == "__main__":
    main()