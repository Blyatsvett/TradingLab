import pandas as pd

from labor_day.ingest_bls_price_indexes import (
    MACRO_COLUMNS,
    SERIES_SPECS,
    build_macro_rows,
    combine_archives,
    extract_series_archive,
    merge_macro_registry,
    parse_reference_period,
    parse_release_date_from_url,
)


def test_parse_six_digit_cpi_date() -> None:
    result = parse_release_date_from_url(
        (
            "https://www.bls.gov/news.release/"
            "history/cpi_101698.txt"
        ),
        SERIES_SPECS["cpi"],
    )

    assert result is not None
    assert result.isoformat() == "1998-10-16"


def test_parse_eight_digit_ppi_date() -> None:
    result = parse_release_date_from_url(
        (
            "https://www.bls.gov/news.release/"
            "archives/ppi_09102025.htm"
        ),
        SERIES_SPECS["ppi"],
    )

    assert result is not None
    assert result.isoformat() == "2025-09-10"


def test_parse_cpi_reference_period() -> None:
    result = parse_reference_period(
        "August 2024 Consumer Price Index PDF",
        SERIES_SPECS["cpi"],
    )

    assert result == (
        "August",
        2024,
    )


def test_parse_ppi_reference_period() -> None:
    result = parse_reference_period(
        "September 1998 Producer Price Index TXT",
        SERIES_SPECS["ppi"],
    )

    assert result == (
        "September",
        1998,
    )


def test_archive_extract_prefers_html() -> None:
    html = """
    <html>
      <body>
        <ul>
          <li>
            August 2024 Consumer Price Index
            <a href="/news.release/archives/cpi_09112024.htm">
              HTML
            </a>
            <a href="/news.release/archives/cpi_09112024.pdf">
              PDF
            </a>
          </li>
        </ul>
      </body>
    </html>
    """

    archive = extract_series_archive(
        html=html,
        spec=SERIES_SPECS["cpi"],
        start_year=2024,
        end_year=2024,
    )

    assert len(archive) == 1
    assert (
        archive.iloc[0]["release_date"]
        == "2024-09-11"
    )
    assert (
        archive.iloc[0]["source_format"]
        == "htm"
    )
    assert (
        archive.iloc[0]["reference_month"]
        == "August"
    )


def test_combine_archives_preserves_both_series() -> None:
    cpi_html = """
    <li>
      August 2024 Consumer Price Index
      <a href="/news.release/archives/cpi_09112024.htm">
        HTML
      </a>
    </li>
    """

    ppi_html = """
    <li>
      August 2024 Producer Price Index
      <a href="/news.release/archives/ppi_09122024.htm">
        HTML
      </a>
    </li>
    """

    cpi = extract_series_archive(
        cpi_html,
        SERIES_SPECS["cpi"],
        2024,
        2024,
    )

    ppi = extract_series_archive(
        ppi_html,
        SERIES_SPECS["ppi"],
        2024,
        2024,
    )

    combined = combine_archives(
        [
            cpi,
            ppi,
        ]
    )

    assert len(combined) == 2

    assert set(
        combined["series"]
    ) == {
        "cpi",
        "ppi",
    }


def test_macro_rows_use_project_schema() -> None:
    cpi_html = """
    <li>
      August 2024 Consumer Price Index
      <a href="/news.release/archives/cpi_09112024.htm">
        HTML
      </a>
    </li>
    """

    ppi_html = """
    <li>
      August 2024 Producer Price Index
      <a href="/news.release/archives/ppi_09122024.htm">
        HTML
      </a>
    </li>
    """

    combined = combine_archives(
        [
            extract_series_archive(
                cpi_html,
                SERIES_SPECS["cpi"],
                2024,
                2024,
            ),
            extract_series_archive(
                ppi_html,
                SERIES_SPECS["ppi"],
                2024,
                2024,
            ),
        ]
    )

    macro_rows = build_macro_rows(
        combined
    )

    assert list(
        macro_rows.columns
    ) == MACRO_COLUMNS

    assert set(
        macro_rows["event_type"]
    ) == {
        "cpi",
        "ppi",
    }

    assert macro_rows[
        "event_time_et"
    ].eq("08:30").all()

    assert macro_rows[
        "tier"
    ].eq("tier_1").all()

    assert macro_rows[
        "verification_status"
    ].eq("official_archive").all()


def test_registry_merge_is_idempotent_and_preserves_2026() -> None:
    existing = pd.DataFrame(
        [
            {
                "event_id": "OLD_CPI_2024",
                "event_date": "2024-09-11",
                "event_time_et": "08:30",
                "event_timezone": "America/New_York",
                "source": "BLS",
                "event_type": "cpi",
                "event_name": "Old CPI row",
                "tier": "tier_1",
                "verification_status": "old",
                "source_url": "",
                "notes": "",
            },
            {
                "event_id": "BLS_CPI_2026_09_11",
                "event_date": "2026-09-11",
                "event_time_et": "08:30",
                "event_timezone": "America/New_York",
                "source": "BLS",
                "event_type": "cpi",
                "event_name": "Scheduled CPI",
                "tier": "tier_1",
                "verification_status": "official_schedule",
                "source_url": "",
                "notes": "",
            },
            {
                "event_id": "BLS_PPI_2026_09_10",
                "event_date": "2026-09-10",
                "event_time_et": "08:30",
                "event_timezone": "America/New_York",
                "source": "BLS",
                "event_type": "ppi",
                "event_name": "Scheduled PPI",
                "tier": "tier_1",
                "verification_status": "official_schedule",
                "source_url": "",
                "notes": "",
            },
            {
                "event_id": "OTHER_EVENT",
                "event_date": "2024-09-06",
                "event_time_et": "08:30",
                "event_timezone": "America/New_York",
                "source": "BLS",
                "event_type": "employment_situation",
                "event_name": "Other event",
                "tier": "tier_1",
                "verification_status": "official_archive",
                "source_url": "",
                "notes": "",
            },
        ],
        columns=MACRO_COLUMNS,
    )

    cpi_html = """
    <li>
      August 2024 Consumer Price Index
      <a href="/news.release/archives/cpi_09112024.htm">
        HTML
      </a>
    </li>
    """

    ppi_html = """
    <li>
      August 2024 Producer Price Index
      <a href="/news.release/archives/ppi_09122024.htm">
        HTML
      </a>
    </li>
    """

    historical_rows = build_macro_rows(
        combine_archives(
            [
                extract_series_archive(
                    cpi_html,
                    SERIES_SPECS["cpi"],
                    2024,
                    2024,
                ),
                extract_series_archive(
                    ppi_html,
                    SERIES_SPECS["ppi"],
                    2024,
                    2024,
                ),
            ]
        )
    )

    merged_once = merge_macro_registry(
        existing=existing,
        historical_rows=historical_rows,
        start_year=2024,
        end_year=2024,
    )

    merged_twice = merge_macro_registry(
        existing=merged_once,
        historical_rows=historical_rows,
        start_year=2024,
        end_year=2024,
    )

    assert (
        "OLD_CPI_2024"
        not in set(
            merged_once["event_id"]
        )
    )

    assert (
        "BLS_CPI_2026_09_11"
        in set(
            merged_once["event_id"]
        )
    )

    assert (
        "BLS_PPI_2026_09_10"
        in set(
            merged_once["event_id"]
        )
    )

    assert (
        "OTHER_EVENT"
        in set(
            merged_once["event_id"]
        )
    )

    pd.testing.assert_frame_equal(
        merged_once,
        merged_twice,
    )