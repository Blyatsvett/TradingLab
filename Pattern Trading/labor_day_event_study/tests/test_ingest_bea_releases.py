from __future__ import annotations

from datetime import date

import pandas as pd

from labor_day.ingest_bea_releases import (
    MACRO_COLUMNS,
    PRODUCTS,
    archive_page_url,
    OUTPUT_COLUMNS,
    build_macro_rows,
    classify_gdp_variant,
    convert_clock_time,
    is_target_release_title,
    merge_macro_registry,
    parse_archive_page,
    parse_reference_period,
    parse_release_header,
    validate_release_archive,
)


def test_official_bea_product_ids() -> None:
    assert PRODUCTS["gdp"]["product_id"] == "451"
    assert (
        PRODUCTS["personal_income_outlays"]["product_id"]
        == "476"
    )

    gdp_url = archive_page_url(
        PRODUCTS["gdp"]["product_id"],
        0,
    )
    assert "field_related_product_target_id=451" in gdp_url



def test_parse_archive_page_filters_and_dates() -> None:
    html = """
    <html><body>
      <table>
        <tr>
          <td>
            <a href="/news/2025/gross-domestic-product-second-quarter-2025-advance-estimate">
              Gross Domestic Product, 2nd Quarter 2025 (Advance Estimate)
            </a>
          </td>
          <td>July 30, 2025</td>
        </tr>
        <tr>
          <td>
            <a href="/news/2025/gross-domestic-product-state-second-quarter-2025">
              Gross Domestic Product by State, 2nd Quarter 2025
            </a>
          </td>
          <td>September 26, 2025</td>
        </tr>
      </table>
      <a href="?page=1">Next page &gt;&gt;</a>
    </body></html>
    """

    rows, has_next = parse_archive_page(
        html=html,
        index_url="https://www.bea.gov/news/archive?page=0",
        series="gdp",
    )

    assert has_next is True
    assert len(rows) == 1
    assert rows[0]["archive_published_date"] == date(
        2025,
        7,
        30,
    )
    assert rows[0]["release_url"].startswith(
        "https://www.bea.gov/news/2025/"
    )


def test_release_title_selection_rules() -> None:
    assert is_target_release_title(
        series="gdp",
        title=(
            "Gross Domestic Product, 2nd Quarter 2025 "
            "(Second Estimate) and Corporate Profits"
        ),
    )
    assert is_target_release_title(
        series="gdp",
        title=(
            "GDP (Third Estimate), Industries, Corporate "
            "Profits, State GDP, and State Personal Income, "
            "4th Quarter and Year 2025"
        ),
    )
    assert not is_target_release_title(
        series="gdp",
        title=(
            "Gross Domestic Product by State and Personal "
            "Income by State, 2nd Quarter 2025"
        ),
    )
    assert is_target_release_title(
        series="personal_income_outlays",
        title="Personal Income and Outlays, July 2025",
    )
    assert is_target_release_title(
        series="personal_income_outlays",
        title="Personal Income, December 1999",
    )
    assert not is_target_release_title(
        series="personal_income_outlays",
        title="Personal Income by State, 3rd Quarter 1999",
    )
    assert not is_target_release_title(
        series="personal_income_outlays",
        title=(
            "Personal Income and Outlays, Data Update, "
            "September 2025"
        ),
    )


def test_parse_old_wire_transmission_header() -> None:
    html = """
    <html><body>
      FOR WIRE TRANSMISSION: 8:30 A.M. EDT,
      FRIDAY, AUGUST 28, 1998
    </body></html>
    """

    release_date, release_time, source = (
        parse_release_header(html)
    )

    assert release_date == date(1998, 8, 28)
    assert release_time == "08:30"
    assert source == "official_release_page_header"


def test_parse_modern_embargo_header() -> None:
    html = """
    <html><body>
      EMBARGOED UNTIL RELEASE AT 8:30 a.m. EST,
      Friday, February 20, 2026
    </body></html>
    """

    release_date, release_time, source = (
        parse_release_header(html)
    )

    assert release_date == date(2026, 2, 20)
    assert release_time == "08:30"
    assert source == "official_release_page_header"


def test_convert_clock_time_handles_noon_and_midnight() -> None:
    assert convert_clock_time(12, 0, "a.m.") == "00:00"
    assert convert_clock_time(12, 0, "p.m.") == "12:00"
    assert convert_clock_time(8, 30, "A.M.") == "08:30"


def test_classify_gdp_variants() -> None:
    assert classify_gdp_variant(
        "GDP (Advance Estimate), 1st Quarter 2025"
    ) == "advance"
    assert classify_gdp_variant(
        "Gross Domestic Product, Second Quarter 2001 "
        "(Preliminary)"
    ) == "preliminary"
    assert classify_gdp_variant(
        "Gross Domestic Product, Third Quarter 1999 "
        "(Final)"
    ) == "final"


def test_parse_reference_periods() -> None:
    assert parse_reference_period(
        series="gdp",
        title=(
            "Gross Domestic Product, 2nd Quarter 2025 "
            "(Advance Estimate)"
        ),
    ) == "2025-Q2"

    assert parse_reference_period(
        series="personal_income_outlays",
        title="Personal Income and Outlays, July 2025",
    ) == "2025-07"

    assert parse_reference_period(
        series="personal_income_outlays",
        title=(
            "Personal Income and Outlays, October and "
            "November 2025"
        ),
    ) == "2025-10;2025-11"


def sample_archive() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "BEA_GDP_2025_08_28",
                "release_date": "2025-08-28",
                "release_time_et": "08:30",
                "event_timezone": "America/New_York",
                "series": "gdp",
                "release_variant": "second",
                "reference_period": "2025-Q2",
                "release_title": (
                    "Gross Domestic Product, 2nd Quarter "
                    "2025 (Second Estimate)"
                ),
                "release_url": "https://www.bea.gov/news/gdp",
                "archive_url": "https://www.bea.gov/news/archive",
                "archive_published_date": "2025-08-28",
                "time_source": "official_release_page_header",
                "verification_status": (
                    "official_release_page_exact_time"
                ),
                "notes": "Official page header.",
            },
            {
                "event_id": "BEA_PIO_2025_08_29",
                "release_date": "2025-08-29",
                "release_time_et": "",
                "event_timezone": "America/New_York",
                "series": "personal_income_outlays",
                "release_variant": "monthly",
                "reference_period": "2025-07",
                "release_title": (
                    "Personal Income and Outlays, July 2025"
                ),
                "release_url": "https://www.bea.gov/news/pio",
                "archive_url": "https://www.bea.gov/news/archive",
                "archive_published_date": "2025-08-29",
                "time_source": "official_archive_published_date",
                "verification_status": "official_archive_date_only",
                "notes": "Archive date only.",
            },
        ],
        columns=OUTPUT_COLUMNS,
    )


def test_archive_validation_allows_blank_release_times() -> None:
    validate_release_archive(
        archive=sample_archive(),
        start_year=2025,
        end_year=2025,
    )


def test_macro_rows_use_project_schema() -> None:
    macro_rows = build_macro_rows(sample_archive())

    assert list(macro_rows.columns) == MACRO_COLUMNS
    assert set(macro_rows["event_type"]) == {
        "gdp",
        "personal_income_outlays",
    }
    assert macro_rows["tier"].eq("tier_1").all()
    assert macro_rows["source"].eq(
        "Bureau of Economic Analysis"
    ).all()


def test_registry_merge_is_idempotent_and_preserves_2026() -> None:
    historical_rows = build_macro_rows(sample_archive())

    existing = pd.DataFrame(
        [
            {
                "event_id": "OLD_BEA_GDP_2025_08_28",
                "event_date": "2025-08-28",
                "event_time_et": "08:30",
                "event_timezone": "America/New_York",
                "source": "BEA",
                "event_type": "gross_domestic_product",
                "event_name": "Old GDP row",
                "tier": "tier_1",
                "verification_status": "scheduled",
                "source_url": "",
                "notes": "Replace me.",
            },
            {
                "event_id": "BEA_GDP_2026_08_26",
                "event_date": "2026-08-26",
                "event_time_et": "08:30",
                "event_timezone": "America/New_York",
                "source": "BEA",
                "event_type": "gdp",
                "event_name": "2026 GDP",
                "tier": "tier_1",
                "verification_status": "scheduled",
                "source_url": "",
                "notes": "Preserve me.",
            },
            {
                "event_id": "OTHER_2025_08_28",
                "event_date": "2025-08-28",
                "event_time_et": "10:00",
                "event_timezone": "America/New_York",
                "source": "Other",
                "event_type": "other_event",
                "event_name": "Other event",
                "tier": "tier_2",
                "verification_status": "official",
                "source_url": "",
                "notes": "Preserve me too.",
            },
        ],
        columns=MACRO_COLUMNS,
    )

    first = merge_macro_registry(
        existing=existing,
        historical_rows=historical_rows,
        start_year=2025,
        end_year=2025,
    )
    second = merge_macro_registry(
        existing=first,
        historical_rows=historical_rows,
        start_year=2025,
        end_year=2025,
    )

    pd.testing.assert_frame_equal(first, second)
    assert "OLD_BEA_GDP_2025_08_28" not in set(
        first["event_id"]
    )
    assert "BEA_GDP_2026_08_26" in set(
        first["event_id"]
    )
    assert "OTHER_2025_08_28" in set(
        first["event_id"]
    )