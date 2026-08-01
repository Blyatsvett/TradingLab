from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from labor_day.ingest_international_trade_releases import (
    EXACT_VERIFICATION_STATUS,
    KNOWN_ARCHIVE_OMISSIONS,
    KNOWN_OMISSION_DISCOVERY_SOURCE,
    MACRO_COLUMNS,
    OUTPUT_COLUMNS,
    STANDARD_RELEASE_TIME_ET,
    STANDARD_VERIFICATION_STATUS,
    archive_url_for_page,
    archive_url_for_year,
    build_macro_rows,
    build_release_archive,
    candidate_release_urls,
    canonical_release_url,
    convert_clock_time,
    create_http_session,
    is_approved_release_source,
    is_monthly_trade_release,
    known_archive_omission_entry,
    merge_macro_registry,
    parse_archive_page,
    parse_full_date,
    parse_last_archive_page,
    parse_reference_period,
    parse_release_header_date,
    parse_release_page_reference_period,
    parse_release_time,
    recover_reference_period_entry,
    recovered_candidate_cache_filename,
    release_cache_filename,
    reference_period_range,
    reference_period_title,
    validate_release_archive,
)


def make_archive_row(
    *,
    event_id: str,
    release_date: str,
    reference_period: str,
    verification_status: str = EXACT_VERIFICATION_STATUS,
) -> dict[str, str]:
    time_source = (
        "official_bea_release_page"
        if verification_status == EXACT_VERIFICATION_STATUS
        else "official_census_schedule_standard_time"
    )

    return {
        "event_id": event_id,
        "release_date": release_date,
        "release_time_et": STANDARD_RELEASE_TIME_ET,
        "event_timezone": "America/New_York",
        "reference_period": reference_period,
        "release_title": (
            "U.S. International Trade in Goods and Services, "
            f"{pd.Period(reference_period, freq='M').strftime('%B %Y')}"
        ),
        "release_url": (
            "https://www.bea.gov/news/"
            f"{release_date[:4]}/"
            "us-international-trade-goods-and-services-"
            f"{reference_period}"
        ),
        "archive_url": archive_url_for_year(
            int(
                release_date[:4]
            )
        ),
        "time_source": time_source,
        "verification_status": verification_status,
        "notes": "Official release.",
    }


def make_full_sample_archive() -> pd.DataFrame:
    references = reference_period_range(
        "1997-11",
        "2025-09",
    )

    release_dates: list[str] = []

    # 1998-2024: 12 weekday publication dates per year.
    for year in range(
        1998,
        2025,
    ):
        for month in range(
            1,
            13,
        ):
            timestamp = pd.Timestamp(
                year=year,
                month=month,
                day=5,
            )
            while timestamp.weekday() >= 5:
                timestamp += pd.Timedelta(
                    days=1
                )
            release_dates.append(
                timestamp.date().isoformat()
            )

    # 2025: 11 actual publication dates because the October 2025
    # reference month moved into January 2026 after the funding lapse.
    for month in range(
        1,
        12,
    ):
        timestamp = pd.Timestamp(
            year=2025,
            month=month,
            day=5,
        )
        while timestamp.weekday() >= 5:
            timestamp += pd.Timedelta(
                days=1
            )
        release_dates.append(
            timestamp.date().isoformat()
        )

    assert len(references) == 335
    assert len(release_dates) == 335

    rows = [
        make_archive_row(
            event_id=(
                "census_bea_trade_"
                + release_date.replace(
                    "-",
                    "",
                )
            ),
            release_date=release_date,
            reference_period=reference_period,
        )
        for release_date, reference_period in zip(
            release_dates,
            references,
            strict=True,
        )
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
        "event_time_et": "08:30",
        "event_timezone": "America/New_York",
        "source": "Census/BEA",
        "event_type": event_type,
        "event_name": "Test event",
        "tier": "tier_1",
        "verification_status": "official",
        "source_url": "https://example.test",
        "notes": "",
    }


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(
                f"HTTP {self.status_code}"
            )


class FakeSession:
    def __init__(
        self,
        responses: dict[str, FakeResponse],
    ) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []

    def get(
        self,
        url: str,
        timeout: int,
    ) -> FakeResponse:
        assert timeout == 60
        self.requested_urls.append(url)
        return self.responses.get(
            url,
            FakeResponse(
                status_code=404
            ),
        )


def test_reference_period_title_and_candidate_urls() -> None:
    assert reference_period_title(
        "1999-12"
    ) == (
        "U.S. International Trade in Goods and Services, "
        "December 1999"
    )

    urls = candidate_release_urls(
        "1999-12"
    )

    assert len(urls) == 6
    assert urls[0] == (
        "https://www.bea.gov/news/1999/"
        "us-international-trade-goods-and-services-december-1999"
    )
    assert urls[1] == (
        "https://www.bea.gov/news/1999/"
        "us-trade-goods-and-services-december-1999"
    )
    assert urls[3] == (
        "https://www.bea.gov/news/2000/"
        "us-international-trade-goods-and-services-december-1999"
    )


def test_known_archive_omission_metadata_is_complete() -> None:
    assert set(
        KNOWN_ARCHIVE_OMISSIONS
    ) == {
        "2006-06",
        "2006-12",
        "2008-06",
        "2011-04",
        "2012-04",
        "2013-04",
    }

    assert {
        metadata["release_date"]
        for metadata in KNOWN_ARCHIVE_OMISSIONS.values()
    } == {
        "2006-08-10",
        "2007-02-13",
        "2008-08-12",
        "2011-06-09",
        "2012-06-08",
        "2013-06-04",
    }

    assert all(
        metadata["release_url"].startswith(
            "https://www.census.gov/foreign-trade/"
            "Press-Release/ft900/ft900_"
        )
        and metadata["release_url"].endswith(".pdf")
        for metadata in KNOWN_ARCHIVE_OMISSIONS.values()
    )


def test_known_archive_omission_returns_verified_pdf_entry() -> None:
    entry = known_archive_omission_entry(
        "2006-06"
    )

    assert entry is not None
    assert entry["release_date"] == "2006-08-10"
    assert entry["reference_period"] == "2006-06"
    assert entry["release_url"].endswith(
        "ft900_0606.pdf"
    )
    assert entry["discovery_source"] == (
        KNOWN_OMISSION_DISCOVERY_SOURCE
    )
    assert entry["archive_url"].endswith(
        "ft900_index.html"
    )


def test_known_archive_omission_is_preferred_without_http(
    tmp_path,
) -> None:
    session = FakeSession({})

    recovered = recover_reference_period_entry(
        session=session,
        cache_dir=tmp_path,
        reference_period="2012-04",
        start_year=1998,
        end_year=2025,
        refresh=False,
        offline=False,
    )

    assert recovered is not None
    assert recovered["release_date"] == "2012-06-08"
    assert recovered["release_url"].endswith(
        "ft900_1204.pdf"
    )
    assert session.requested_urls == []


def test_release_cache_filename_preserves_pdf_extension() -> None:
    entry = known_archive_omission_entry(
        "2013-04"
    )

    assert entry is not None
    assert release_cache_filename(
        entry
    ) == "20130604_201304.pdf"


def test_build_archive_uses_verified_census_pdf_metadata(
    tmp_path,
) -> None:
    entry = known_archive_omission_entry(
        "2006-06"
    )
    assert entry is not None

    session = FakeSession(
        {
            entry["release_url"]: FakeResponse(
                status_code=200,
                text="%PDF-1.4 official FT-900 source",
            ),
        }
    )

    archive, source_documents = build_release_archive(
        session=session,
        entries=[entry],
        cache_dir=tmp_path,
        refresh=False,
        offline=False,
    )

    assert len(archive) == 1
    assert archive.loc[0, "release_date"] == "2006-08-10"
    assert archive.loc[0, "reference_period"] == "2006-06"
    assert archive.loc[0, "release_time_et"] == "08:30"
    assert archive.loc[0, "time_source"] == (
        "official_census_ft900_pdf"
    )
    assert archive.loc[0, "verification_status"] == (
        EXACT_VERIFICATION_STATUS
    )
    assert "official Census/BEA FT-900 PDF" in archive.loc[
        0,
        "notes",
    ]
    assert source_documents == [
        b"%PDF-1.4 official FT-900 source"
    ]
    assert (
        tmp_path
        / "release_pages"
        / "20060810_200606.pdf"
    ).exists()


def test_recover_reference_period_from_official_page(
    tmp_path,
) -> None:
    candidate_urls = candidate_release_urls(
        "1999-12"
    )
    page = """
    <html>
      <h1>
        U.S. International Trade in Goods and Services, December 1999
      </h1>
      <p>
        This release contains sensitive economic data not to be
        released before 8:30 a.m. Friday, February 18, 2000
      </p>
    </html>
    """
    session = FakeSession(
        {
            candidate_urls[0]: FakeResponse(
                status_code=404
            ),
            candidate_urls[1]: FakeResponse(
                status_code=404
            ),
            candidate_urls[2]: FakeResponse(
                status_code=404
            ),
            candidate_urls[3]: FakeResponse(
                status_code=200,
                text=page,
            ),
        }
    )

    recovered = recover_reference_period_entry(
        session=session,
        cache_dir=tmp_path,
        reference_period="1999-12",
        start_year=1998,
        end_year=2025,
        refresh=False,
        offline=False,
    )

    assert recovered is not None
    assert recovered["release_date"] == "2000-02-18"
    assert recovered["reference_period"] == "1999-12"
    assert recovered["release_url"] == candidate_urls[3]
    assert recovered["archive_url"].endswith(
        "ft900_index.html"
    )

    seeded_cache = (
        tmp_path
        / "release_pages"
        / "20000218_199912.html"
    )
    assert seeded_cache.exists()
    assert session.requested_urls == candidate_urls[:4]


def test_recovery_rejects_wrong_reference_period(
    tmp_path,
) -> None:
    candidate_urls = candidate_release_urls(
        "2007-06"
    )
    wrong_page = """
    <html>
      <h1>
        U.S. International Trade in Goods and Services, May 2007
      </h1>
      <p>
        EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT,
        Friday, August 10, 2007
      </p>
    </html>
    """
    session = FakeSession(
        {
            candidate_urls[0]: FakeResponse(
                status_code=200,
                text=wrong_page,
            ),
            candidate_urls[1]: FakeResponse(
                status_code=404,
            ),
        }
    )

    recovered = recover_reference_period_entry(
        session=session,
        cache_dir=tmp_path,
        reference_period="2007-06",
        start_year=1998,
        end_year=2025,
        refresh=False,
        offline=False,
    )

    assert recovered is None


def test_parse_unpunctuated_1999_title() -> None:
    assert parse_reference_period(
        "U.S. International Trade in Goods and Services April 1999"
    ) == "1999-04"


def test_parse_shortened_2007_title() -> None:
    assert parse_reference_period(
        "U.S. Trade in Goods and Services, January 2007"
    ) == "2007-01"


def test_release_page_reference_period_uses_ft900_fallback() -> None:
    page_text = """
    FOR IMMEDIATE RELEASE 8:30 A.M. EDT FRIDAY, MARCH 9, 2007
    BEA 07-08
    FT-900 (07-01)
    U.S. TRADE REPORT
    """

    assert parse_release_page_reference_period(
        page_text
    ) == "2007-01"


def test_parse_for_immediate_release_header() -> None:
    page_text = (
        "FOR IMMEDIATE RELEASE 8:30 A.M. EDT "
        "FRIDAY, MARCH 9, 2007"
    )

    assert parse_release_time(
        page_text
    ) == "08:30"
    assert parse_release_header_date(
        page_text
    ) == date(
        2007,
        3,
        9,
    )


def test_candidate_cache_names_do_not_collide() -> None:
    urls = candidate_release_urls(
        "2007-01"
    )

    names = {
        recovered_candidate_cache_filename(
            reference_period="2007-01",
            candidate_url=url,
        )
        for url in urls
    }

    assert len(names) == len(urls)


def test_recovery_supports_combined_annual_revision_slug(
    tmp_path,
) -> None:
    # Use a synthetic non-exception month so this test continues to exercise
    # the generic BEA combined-page fallback rather than the locked Census PDF.
    candidate_urls = candidate_release_urls(
        "2014-04"
    )
    combined_url = candidate_urls[2]
    page = """
    <html>
      <h1>
        U.S. International Trade in Goods and Services, April 2014
        U.S. International Trade in Goods and Services, 2013 annual revision
      </h1>
      <p>
        FOR IMMEDIATE RELEASE AT 8:30 A.M. EDT,
        WEDNESDAY, JUNE 4, 2014
      </p>
      <p>FT-900 (14-04)</p>
    </html>
    """
    session = FakeSession(
        {
            combined_url: FakeResponse(
                status_code=200,
                text=page,
            ),
        }
    )

    recovered = recover_reference_period_entry(
        session=session,
        cache_dir=tmp_path,
        reference_period="2014-04",
        start_year=1998,
        end_year=2025,
        refresh=False,
        offline=False,
    )

    assert recovered is not None
    assert recovered["release_date"] == "2014-06-04"
    assert recovered["reference_period"] == "2014-04"
    assert recovered["release_url"] == combined_url


def test_archive_url_uses_unfiltered_pagination() -> None:
    first = archive_url_for_page(0)
    later = archive_url_for_page(7)

    assert first == (
        "https://www.bea.gov/news/archive"
        "?created_1=All"
        "&field_related_product_target_id=All"
        "&title="
    )
    assert later.endswith("&page=7")
    assert archive_url_for_year(1998) == first


def test_http_session_uses_browser_headers() -> None:
    session = create_http_session()

    assert "Mozilla/5.0" in session.headers[
        "User-Agent"
    ]
    assert "text/html" in session.headers[
        "Accept"
    ]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "U.S. International Trade in Goods and Services, May 1998",
            "1998-05",
        ),
        (
            (
                "U.S. International Trade in Goods and Services, "
                "December and Annual 2024"
            ),
            "2024-12",
        ),
        (
            "U.S. International Trade in Goods and Services for February 1999",
            "1999-02",
        ),
        (
            "U.S. International Trade in Goods and Services, Annual Revision",
            None,
        ),
    ],
)
def test_parse_reference_period(
    title: str,
    expected: str | None,
) -> None:
    assert parse_reference_period(
        title
    ) == expected


def test_parse_full_date() -> None:
    assert parse_full_date(
        "Published February 19, 1998"
    ) == date(
        1998,
        2,
        19,
    )

    assert parse_full_date(
        "No date"
    ) is None


def test_convert_clock_time_handles_noon_and_midnight() -> None:
    assert convert_clock_time(
        12,
        0,
        "a.m.",
    ) == "00:00"

    assert convert_clock_time(
        12,
        0,
        "p.m.",
    ) == "12:00"


def test_parse_modern_release_header() -> None:
    text = (
        "EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, "
        "Thursday, June 5, 2025"
    )

    assert parse_release_time(
        text
    ) == "08:30"

    assert parse_release_header_date(
        text
    ) == date(
        2025,
        6,
        5,
    )


def test_parse_old_release_header() -> None:
    text = (
        "This release contains sensitive economic data not to be "
        "released before 8:30 a.m. Thursday, February 19, 1998"
    )

    assert parse_release_time(
        text
    ) == "08:30"

    assert parse_release_header_date(
        text
    ) == date(
        1998,
        2,
        19,
    )


def test_monthly_release_filter_excludes_annual_revision() -> None:
    assert is_monthly_trade_release(
        title=(
            "U.S. International Trade in Goods and Services, May 1998"
        ),
        absolute_url=(
            "https://www.bea.gov/news/1998/"
            "us-international-trade-goods-and-services-may-1998"
        ),
    )

    assert not is_monthly_trade_release(
        title=(
            "U.S. International Trade in Goods and Services, "
            "Annual Revision"
        ),
        absolute_url=(
            "https://www.bea.gov/news/2025/"
            "us-international-trade-goods-and-services-annual-revision"
        ),
    )


def test_parse_last_archive_page() -> None:
    html = """
    <nav class="pager">
      <a href="/news/archive?created_1=All&page=1&title=">2</a>
      <a href="/news/archive?created_1=All&page=87&title=">Last</a>
    </nav>
    """

    assert parse_last_archive_page(html) == 87


def test_canonical_release_url_handles_historical_for_title() -> None:
    assert canonical_release_url(
        publication_year=1999,
        title=(
            "U.S. International Trade in Goods and Services "
            "for February 1999"
        ),
    ) == (
        "https://www.bea.gov/news/1999/"
        "us-international-trade-goods-and-services-february-1999"
    )


def test_archive_parser_preserves_shortened_2007_bea_url() -> None:
    html = """
    <table>
      <tr>
        <td>
          <a href="/index.php/news/2007/us-trade-goods-and-services-january-2007">
            U.S. Trade in Goods and Services, January 2007
          </a>
        </td>
        <td>March 9, 2007</td>
      </tr>
    </table>
    """

    rows = parse_archive_page(
        html=html,
        source_url=archive_url_for_page(62),
        start_year=2007,
        end_year=2007,
    )

    assert len(rows) == 1
    assert rows[0]["reference_period"] == "2007-01"
    assert rows[0]["release_date"] == "2007-03-09"
    assert rows[0]["release_url"] == (
        "https://www.bea.gov/index.php/news/2007/"
        "us-trade-goods-and-services-january-2007"
    )


def test_shortened_bea_trade_slug_is_monthly_release() -> None:
    assert is_monthly_trade_release(
        title="U.S. Trade in Goods and Services, January 2007",
        absolute_url=(
            "https://www.bea.gov/index.php/news/2007/"
            "us-trade-goods-and-services-january-2007"
        ),
    )


def test_archive_parser_constructs_url_for_plain_text_old_row() -> None:
    html = """
    <table>
      <tr>
        <td>
          U.S. International Trade in Goods and Services for February 1999
        </td>
        <td>April 20, 1999</td>
      </tr>
    </table>
    """

    rows = parse_archive_page(
        html=html,
        source_url=archive_url_for_page(84),
        start_year=1999,
        end_year=1999,
    )

    assert len(rows) == 1
    assert rows[0]["reference_period"] == "1999-02"
    assert rows[0]["release_date"] == "1999-04-20"
    assert rows[0]["release_url"].endswith(
        "/us-international-trade-goods-and-services-february-1999"
    )


def test_parse_archive_page_extracts_monthly_rows() -> None:
    html = """
    <table>
      <tr>
        <td>
          <a href="/news/1998/us-international-trade-goods-and-services-november-1997">
            U.S. International Trade in Goods and Services, November 1997
          </a>
        </td>
        <td>January 21, 1998</td>
      </tr>
      <tr>
        <td>
          <a href="/news/1998/us-international-trade-goods-and-services-december-1997">
            U.S. International Trade in Goods and Services, December 1997
          </a>
        </td>
        <td>February 19, 1998</td>
      </tr>
      <tr>
        <td>
          <a href="/news/1998/us-international-trade-goods-and-services-annual-revision">
            U.S. International Trade in Goods and Services, Annual Revision
          </a>
        </td>
        <td>June 18, 1998</td>
      </tr>
    </table>
    """

    rows = parse_archive_page(
        html=html,
        source_url=archive_url_for_page(86),
        start_year=1998,
        end_year=1998,
    )

    assert len(
        rows
    ) == 2

    assert [
        row[
            "reference_period"
        ]
        for row in rows
    ] == [
        "1997-11",
        "1997-12",
    ]

    assert rows[0][
        "release_date"
    ] == "1998-01-21"


def test_approved_source_accepts_shortened_bea_index_url() -> None:
    assert is_approved_release_source(
        reference_period="2007-01",
        release_url=(
            "https://www.bea.gov/index.php/news/2007/"
            "us-trade-goods-and-services-january-2007"
        ),
    )


def test_full_sample_validation_accepts_known_census_fallbacks() -> None:
    archive = make_full_sample_archive()

    for reference_period, metadata in KNOWN_ARCHIVE_OMISSIONS.items():
        mask = archive["reference_period"].eq(
            reference_period
        )
        assert int(mask.sum()) == 1
        archive.loc[mask, "release_url"] = metadata["release_url"]

    validate_release_archive(
        archive=archive,
        start_year=1998,
        end_year=2025,
    )


def test_validation_rejects_undocumented_census_pdf() -> None:
    archive = make_full_sample_archive()
    mask = archive["reference_period"].eq(
        "2010-06"
    )
    archive.loc[mask, "release_url"] = (
        "https://www.census.gov/foreign-trade/"
        "Press-Release/ft900/ft900_1006.pdf"
    )

    with pytest.raises(
        ValueError,
        match="Unapproved international trade release URL",
    ):
        validate_release_archive(
            archive=archive,
            start_year=1998,
            end_year=2025,
        )


def test_full_sample_validation_accepts_shortened_bea_index_url() -> None:
    archive = make_full_sample_archive()
    mask = archive["reference_period"].eq(
        "2007-01"
    )
    archive.loc[mask, "release_url"] = (
        "https://www.bea.gov/index.php/news/2007/"
        "us-trade-goods-and-services-january-2007"
    )

    validate_release_archive(
        archive=archive,
        start_year=1998,
        end_year=2025,
    )


def test_full_sample_validation_accepts_contiguous_335_rows() -> None:
    archive = make_full_sample_archive()

    validate_release_archive(
        archive=archive,
        start_year=1998,
        end_year=2025,
    )


def test_validation_rejects_missing_reference_month() -> None:
    archive = make_full_sample_archive()
    archive = archive.loc[
        archive[
            "reference_period"
        ].ne(
            "2010-06"
        )
    ].copy()

    with pytest.raises(
        ValueError,
        match=(
            "reference-month sequence is not contiguous"
            "|Full international trade sample contains"
        ),
    ):
        validate_release_archive(
            archive=archive,
            start_year=1998,
            end_year=2025,
        )


def test_validation_allows_explicit_standard_time_fallback() -> None:
    archive = make_full_sample_archive()
    archive.loc[
        0,
        "verification_status",
    ] = STANDARD_VERIFICATION_STATUS
    archive.loc[
        0,
        "time_source",
    ] = "official_census_schedule_standard_time"

    validate_release_archive(
        archive=archive,
        start_year=1998,
        end_year=2025,
    )


def test_macro_rows_use_project_schema() -> None:
    archive = make_full_sample_archive().iloc[
        :1
    ].copy()

    macro_rows = build_macro_rows(
        archive
    )

    assert list(
        macro_rows.columns
    ) == MACRO_COLUMNS

    assert macro_rows.loc[
        0,
        "event_type",
    ] == "international_trade"

    assert macro_rows.loc[
        0,
        "tier",
    ] == "tier_1"

    assert macro_rows.loc[
        0,
        "event_time_et",
    ] == "08:30"


def test_registry_merge_is_idempotent_and_preserves_2026() -> None:
    existing = pd.DataFrame(
        [
            make_macro_row(
                event_id="old_trade_20240904",
                event_date="2024-09-04",
                event_type="international_trade",
            ),
            make_macro_row(
                event_id="scheduled_trade_20260903",
                event_date="2026-09-03",
                event_type="international_trade",
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
        make_full_sample_archive()
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
        == "scheduled_trade_20260903"
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
        == "old_trade_20240904"
    ).any()