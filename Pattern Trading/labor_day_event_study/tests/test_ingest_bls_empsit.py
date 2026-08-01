import pandas as pd

from labor_day.ingest_bls_empsit import (
    MACRO_COLUMNS,
    build_macro_rows,
    extract_archive_index,
    merge_macro_registry,
    parse_reference_period,
    parse_release_date_from_url,
)


SYNTHETIC_ARCHIVE_HTML = """
<html>
  <body>
    <ul>
      <li>
        August 1998 Employment Situation
        <a href="/news.release/history/empsit_090498.txt">
          TXT
        </a>
      </li>

      <li>
        August 2024 Employment Situation
        <a href="/news.release/archives/empsit_09062024.htm">
          August 2024 Employment Situation
        </a>
        <a href="/news.release/archives/empsit_09062024.pdf">
          PDF
        </a>
      </li>

      <li>
        August 2026 Employment Situation
        <a href="/news.release/archives/empsit_09042026.htm">
          August 2026 Employment Situation
        </a>
      </li>
    </ul>
  </body>
</html>
"""


def test_parse_six_digit_archive_date() -> None:
    parsed = parse_release_date_from_url(
        "https://www.bls.gov/news.release/"
        "history/empsit_090498.txt"
    )

    assert parsed is not None
    assert parsed.isoformat() == "1998-09-04"


def test_parse_eight_digit_archive_date() -> None:
    parsed = parse_release_date_from_url(
        "https://www.bls.gov/news.release/"
        "archives/empsit_09062024.pdf"
    )

    assert parsed is not None
    assert parsed.isoformat() == "2024-09-06"


def test_parse_reference_period() -> None:
    parsed = parse_reference_period(
        "August 2024 Employment Situation (PDF)"
    )

    assert parsed == (
        "August",
        2024,
    )


def test_archive_extract_deduplicates_formats() -> None:
    archive = extract_archive_index(
        html=SYNTHETIC_ARCHIVE_HTML,
        start_year=1998,
        end_year=2025,
    )

    assert len(archive) == 2

    assert set(
        archive["release_date"]
    ) == {
        "1998-09-04",
        "2024-09-06",
    }

    row_2024 = archive.loc[
        archive["release_date"]
        == "2024-09-06"
    ].iloc[0]

    assert row_2024[
        "source_format"
    ] == "htm"


def test_macro_rows_use_project_schema() -> None:
    archive = extract_archive_index(
        html=SYNTHETIC_ARCHIVE_HTML,
        start_year=1998,
        end_year=2025,
    )

    macro_rows = build_macro_rows(
        archive
    )

    assert list(
        macro_rows.columns
    ) == MACRO_COLUMNS

    assert macro_rows[
        "event_time_et"
    ].eq("08:30").all()

    assert macro_rows[
        "tier"
    ].eq("tier_1").all()

    assert macro_rows[
        "event_type"
    ].eq("employment_situation").all()


def test_registry_merge_is_idempotent() -> None:
    existing = pd.DataFrame(
        [
            {
                "event_id": "STALE_1998",
                "event_date": "1998-09-05",
                "event_time_et": "08:30",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "BLS",
                "event_type": (
                    "employment_situation"
                ),
                "event_name": "Stale row",
                "tier": "tier_1",
                "verification_status": "stale",
                "source_url": "",
                "notes": "",
            },
            {
                "event_id": (
                    "BLS_EMPSIT_2026_09_04"
                ),
                "event_date": "2026-09-04",
                "event_time_et": "08:30",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "BLS",
                "event_type": (
                    "employment_situation"
                ),
                "event_name": (
                    "Employment Situation "
                    "August 2026"
                ),
                "tier": "tier_1",
                "verification_status": (
                    "official_schedule"
                ),
                "source_url": "",
                "notes": "",
            },
            {
                "event_id": "OTHER_EVENT",
                "event_date": "2024-09-10",
                "event_time_et": "08:30",
                "event_timezone": (
                    "America/New_York"
                ),
                "source": "BLS",
                "event_type": (
                    "producer_price_index"
                ),
                "event_name": "Other event",
                "tier": "tier_1",
                "verification_status": (
                    "official"
                ),
                "source_url": "",
                "notes": "",
            },
        ],
        columns=MACRO_COLUMNS,
    )

    archive = extract_archive_index(
        html=SYNTHETIC_ARCHIVE_HTML,
        start_year=1998,
        end_year=2025,
    )

    historical = build_macro_rows(
        archive
    )

    first_merge = merge_macro_registry(
        existing=existing,
        historical_rows=historical,
        start_year=1998,
        end_year=2025,
    )

    second_merge = merge_macro_registry(
        existing=first_merge,
        historical_rows=historical,
        start_year=1998,
        end_year=2025,
    )

    pd.testing.assert_frame_equal(
        first_merge,
        second_merge,
    )

    assert "STALE_1998" not in set(
        first_merge["event_id"]
    )

    assert (
        "BLS_EMPSIT_2026_09_04"
        in set(first_merge["event_id"])
    )

    assert "OTHER_EVENT" in set(
        first_merge["event_id"]
    )