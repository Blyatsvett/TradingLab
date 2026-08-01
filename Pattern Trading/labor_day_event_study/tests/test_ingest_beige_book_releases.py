from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from labor_day.ingest_beige_book_releases import (
    MACRO_COLUMNS,
    OUTPUT_COLUMNS,
    KNOWN_NON_WEDNESDAY_RELEASES,
    STANDARD_RELEASE_TIME_ET,
    STANDARD_VERIFICATION_STATUS,
    apply_known_archive_exceptions,
    build_macro_rows,
    create_http_session,
    is_report_html_link,
    merge_macro_registry,
    parse_month_day,
    parse_year_page,
    validate_release_archive,
    year_page_url,
)


def make_archive_row(
    *,
    event_id: str,
    release_date: str,
    report_url: str,
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "release_date": release_date,
        "release_time_et": STANDARD_RELEASE_TIME_ET,
        "event_timezone": "America/New_York",
        "report_url": report_url,
        "year_page_url": (
            "https://www.federalreserve.gov/"
            "monetarypolicy/beigebook2024.htm"
        ),
        "archive_label": "September 4 HTML PDF",
        "time_source": (
            "official_federal_reserve_standard_release_time"
        ),
        "verification_status": (
            STANDARD_VERIFICATION_STATUS
        ),
        "notes": "Official archive date.",
    }


def make_valid_year_archive(
    year: int = 2024,
) -> pd.DataFrame:
    dates = [
        f"{year}-01-17",
        f"{year}-03-06",
        f"{year}-04-17",
        f"{year}-05-29",
        f"{year}-07-17",
        f"{year}-09-04",
        f"{year}-10-23",
        f"{year}-12-04",
    ]

    rows = [
        make_archive_row(
            event_id=(
                "fed_beige_book_"
                + release_date.replace(
                    "-",
                    "",
                )
            ),
            release_date=release_date,
            report_url=(
                "https://www.federalreserve.gov/"
                "monetarypolicy/beigebook"
                + release_date[:4]
                + release_date[5:7]
                + ".htm"
            ),
        )
        for release_date in dates
    ]

    return pd.DataFrame(
        rows,
        columns=OUTPUT_COLUMNS,
    )


def make_macro_row(
    *,
    event_id: str,
    event_date: str,
    event_type: str,
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "event_date": event_date,
        "event_time_et": "14:00",
        "event_timezone": "America/New_York",
        "source": "Federal Reserve",
        "event_type": event_type,
        "event_name": "Test event",
        "tier": "tier_2",
        "verification_status": "official",
        "source_url": "https://example.test",
        "notes": "",
    }


def test_year_page_url_uses_official_pattern() -> None:
    assert year_page_url(
        1998
    ) == (
        "https://www.federalreserve.gov/"
        "monetarypolicy/beigebook1998.htm"
    )


def test_http_session_uses_browser_headers() -> None:
    session = create_http_session()

    assert "Mozilla/5.0" in session.headers[
        "User-Agent"
    ]
    assert "text/html" in session.headers[
        "Accept"
    ]


def test_parse_month_day() -> None:
    assert parse_month_day(
        "September 4 HTML PDF",
        2024,
    ) == date(
        2024,
        9,
        4,
    )

    assert parse_month_day(
        "No release date",
        2024,
    ) is None


def test_report_link_filter() -> None:
    assert is_report_html_link(
        anchor_text="HTML",
        absolute_url=(
            "https://www.federalreserve.gov/"
            "monetarypolicy/beigebook202408.htm"
        ),
        year=2024,
    )

    assert not is_report_html_link(
        anchor_text="PDF",
        absolute_url=(
            "https://www.federalreserve.gov/"
            "monetarypolicy/files/BeigeBook_20240904.pdf"
        ),
        year=2024,
    )

    assert not is_report_html_link(
        anchor_text="HTML",
        absolute_url=year_page_url(
            2024
        ),
        year=2024,
    )


def test_parse_classic_table_year_page() -> None:
    html = """
    <table>
      <tr>
        <td>January 21</td>
        <td>
          <a href="/monetarypolicy/beigebook/beigebook199801.htm">
            HTML
          </a>
          <a href="/files/beigebook199801.pdf">PDF</a>
        </td>
      </tr>
      <tr>
        <td>March 18</td>
        <td>
          <a href="/monetarypolicy/beigebook/beigebook199803.htm">
            HTML
          </a>
        </td>
      </tr>
    </table>
    """

    rows = parse_year_page(
        html=html,
        year=1998,
        source_url=year_page_url(
            1998
        ),
    )

    assert [
        row["release_date"]
        for row in rows
    ] == [
        "1998-01-21",
        "1998-03-18",
    ]

    assert rows[0][
        "report_url"
    ].endswith(
        "beigebook199801.htm"
    )


def test_parse_modern_compact_year_page() -> None:
    html = """
    <div class="row">
      <div>
        September 4:
        <a href="/monetarypolicy/beigebook202408.htm">
          HTML
        </a>
        |
        <a href="/files/BeigeBook_20240904.pdf">PDF</a>
      </div>
    </div>
    """

    rows = parse_year_page(
        html=html,
        year=2024,
        source_url=year_page_url(
            2024
        ),
    )

    assert len(
        rows
    ) == 1
    assert rows[0][
        "release_date"
    ] == "2024-09-04"


def test_parse_year_page_ignores_nonreport_links() -> None:
    html = """
    <p>
      September 4
      <a href="/monetarypolicy/beigebook2024.htm">HTML</a>
      <a href="https://example.com/beigebook202408.htm">HTML</a>
      <a href="/monetarypolicy/beigebook202408.htm">HTML</a>
    </p>
    """

    rows = parse_year_page(
        html=html,
        year=2024,
        source_url=year_page_url(
            2024
        ),
    )

    assert len(
        rows
    ) == 1


def test_known_2003_archive_omission_is_restored() -> None:
    parsed_rows = [
        {
            "release_date": "2003-01-15",
            "report_url": (
                "https://www.federalreserve.gov/"
                "monetarypolicy/beigebook/beigebook200301.htm"
            ),
            "year_page_url": year_page_url(2003),
            "archive_label": "January 15 HTML",
        }
    ]

    completed = apply_known_archive_exceptions(
        year_rows=parsed_rows,
        year=2003,
        source_url=year_page_url(2003),
    )

    september_rows = [
        row
        for row in completed
        if row["release_date"] == "2003-09-03"
    ]

    assert len(september_rows) == 1
    assert september_rows[0]["report_url"].endswith(
        "/20030903/default.htm"
    )

    completed_again = apply_known_archive_exceptions(
        year_rows=completed,
        year=2003,
        source_url=year_page_url(2003),
    )

    assert completed_again == completed


def test_documented_2006_thursday_exception_is_allowed() -> None:
    archive = make_valid_year_archive(
        2024
    )

    # Recast the synthetic complete-year fixture as 2006 and include
    # the official Thursday exception in place of one Wednesday.
    dates = [
        "2006-01-18",
        "2006-03-15",
        "2006-04-26",
        "2006-06-14",
        "2006-07-26",
        "2006-09-06",
        "2006-10-12",
        "2006-11-29",
    ]

    for index, release_date in enumerate(dates):
        archive.loc[
            index,
            "release_date",
        ] = release_date
        archive.loc[
            index,
            "event_id",
        ] = (
            "fed_beige_book_"
            + release_date.replace("-", "")
        )

    assert date(2006, 10, 12) in (
        KNOWN_NON_WEDNESDAY_RELEASES
    )

    validate_release_archive(
        archive=archive,
        start_year=2006,
        end_year=2006,
    )


def test_archive_validation_accepts_complete_year() -> None:
    archive = make_valid_year_archive(
        2024
    )

    validate_release_archive(
        archive=archive,
        start_year=2024,
        end_year=2024,
    )


def test_archive_validation_requires_eight_releases() -> None:
    archive = make_valid_year_archive(
        2024
    ).iloc[:-1].copy()

    with pytest.raises(
        ValueError,
        match="expected exactly 8",
    ):
        validate_release_archive(
            archive=archive,
            start_year=2024,
            end_year=2024,
        )


def test_archive_validation_rejects_non_wednesday() -> None:
    archive = make_valid_year_archive(
        2024
    )
    archive.loc[
        0,
        "release_date",
    ] = "2024-01-18"

    with pytest.raises(
        ValueError,
        match="documented historical exceptions",
    ):
        validate_release_archive(
            archive=archive,
            start_year=2024,
            end_year=2024,
        )


def test_macro_rows_use_project_schema() -> None:
    archive = make_valid_year_archive(
        2024
    ).iloc[:1].copy()

    macro_rows = build_macro_rows(
        archive
    )

    assert list(
        macro_rows.columns
    ) == MACRO_COLUMNS

    assert macro_rows.loc[
        0,
        "event_type",
    ] == "beige_book"

    assert macro_rows.loc[
        0,
        "tier",
    ] == "tier_2"

    assert macro_rows.loc[
        0,
        "event_time_et",
    ] == "14:00"


def test_registry_merge_is_idempotent_and_preserves_2026() -> None:
    existing = pd.DataFrame(
        [
            make_macro_row(
                event_id="old_beige_book_20240904",
                event_date="2024-09-04",
                event_type="beige_book",
            ),
            make_macro_row(
                event_id="scheduled_beige_book_20260902",
                event_date="2026-09-02",
                event_type="beige_book",
            ),
            make_macro_row(
                event_id="other_20240904",
                event_date="2024-09-04",
                event_type="fomc",
            ),
        ],
        columns=MACRO_COLUMNS,
    )

    historical = build_macro_rows(
        make_valid_year_archive(
            2024
        )
    )

    first = merge_macro_registry(
        existing=existing,
        historical_rows=historical,
        start_year=1998,
        end_year=2025,
    )

    second = merge_macro_registry(
        existing=first,
        historical_rows=historical,
        start_year=1998,
        end_year=2025,
    )

    assert first.equals(
        second
    )

    assert (
        first[
            "event_id"
        ]
        == "scheduled_beige_book_20260902"
    ).any()

    assert (
        first[
            "event_id"
        ]
        == "other_20240904"
    ).any()

    assert not (
        first[
            "event_id"
        ]
        == "old_beige_book_20240904"
    ).any()