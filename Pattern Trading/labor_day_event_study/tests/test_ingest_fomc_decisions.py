from datetime import date

import pandas as pd

from labor_day.ingest_fomc_decisions import (
    MACRO_COLUMNS,
    OUTPUT_COLUMNS,
    convert_clock_time,
    extract_historical_statement_links,
    extract_modern_statement_links,
    merge_macro_registry,
    parse_date_from_url,
    parse_release_time,
    scheduled_time_fallback,
    validate_decision_archive,
)


def test_parse_old_statement_url_date() -> None:
    result = parse_date_from_url(
        (
            "https://www.federalreserve.gov/"
            "boarddocs/press/general/1998/"
            "19980929/"
        )
    )

    assert result == date(
        1998,
        9,
        29,
    )


def test_parse_modern_statement_url_date() -> None:
    result = parse_date_from_url(
        (
            "https://www.federalreserve.gov/"
            "newsevents/pressreleases/"
            "monetary20250917a.htm"
        )
    )

    assert result == date(
        2025,
        9,
        17,
    )


def test_convert_clock_time() -> None:
    assert convert_clock_time(
        2,
        0,
        "p.m.",
    ) == "14:00"

    assert convert_clock_time(
        12,
        30,
        "p.m.",
    ) == "12:30"

    assert convert_clock_time(
        10,
        0,
        "a.m.",
    ) == "10:00"

    assert convert_clock_time(
        12,
        0,
        "a.m.",
    ) == "00:00"


def test_parse_modern_for_release_time() -> None:
    html = """
    <html>
      <body>
        <p>For release at 2:00 p.m. EDT</p>
      </body>
    </html>
    """

    release_time, source = parse_release_time(
        html
    )

    assert release_time == "14:00"
    assert source == "official_for_release_at"


def test_parse_old_last_update_time() -> None:
    html = """
    <html>
      <body>
        Last update: October 15, 1998, 3:15 PM
      </body>
    </html>
    """

    release_time, source = parse_release_time(
        html
    )

    assert release_time == "15:15"
    assert source == "official_last_update"


def test_historical_extraction_classifies_meeting_types() -> None:
    html = """
    <html>
      <body>
        <h5>September 29 Meeting - 1998</h5>
        <p>
          <a href="/boarddocs/press/general/1998/19980929/">
            Statement
          </a>
        </p>

        <h5>October 15 Conference Call - 1998</h5>
        <p>
          <a href="/boarddocs/press/general/1998/19981015/">
            Statement
          </a>
        </p>

        <h5>October 20 Conference Call - 1998</h5>
        <p>
          <a href="/transcript.pdf">
            Transcript
          </a>
        </p>
      </body>
    </html>
    """

    rows = extract_historical_statement_links(
        html=html,
        index_url=(
            "https://www.federalreserve.gov/"
            "monetarypolicy/"
            "fomchistorical1998.htm"
        ),
        year=1998,
    )

    assert len(rows) == 2
    assert rows[0]["meeting_type"] == "scheduled"
    assert rows[1]["meeting_type"] == "unscheduled"


def test_historical_extraction_excludes_supplementary_statements() -> None:
    html = """
    <html>
      <body>
        <h5>January 29-30 Meeting - 2019</h5>

        <p>
          <a href="/newsevents/pressreleases/monetary20190130a.htm">
            Statement
          </a>
        </p>

        <p>
          <a href="/newsevents/pressreleases/monetary20190130b.htm">
            Statement on Longer-Run Goals and Monetary Policy Strategy
          </a>
        </p>

        <p>
          <a href="/newsevents/pressreleases/monetary20190130c.htm">
            Statement Regarding Monetary Policy Implementation
            and Balance Sheet Normalization
          </a>
        </p>
      </body>
    </html>
    """

    rows = extract_historical_statement_links(
        html=html,
        index_url=(
            "https://www.federalreserve.gov/"
            "monetarypolicy/"
            "fomchistorical2019.htm"
        ),
        year=2019,
    )

    assert len(rows) == 1
    assert rows[0]["statement_url"].endswith(
        "monetary20190130a.htm"
    )
    assert rows[0]["decision_date"] == date(
        2019,
        1,
        30,
    )
    assert rows[0]["meeting_type"] == "scheduled"


def test_historical_extraction_handles_unscheduled_meetings_and_votes() -> None:
    html = """
    <html>
      <body>
        <h5>March 2 (unscheduled) Meeting - 2020</h5>
        <p>
          <a href="/newsevents/pressreleases/monetary20200303a.htm">
            Statement
          </a>
        </p>

        <h5>March 15 (unscheduled) Meeting - 2020</h5>
        <p>
          <a href="/newsevents/pressreleases/monetary20200315a.htm">
            Statement
          </a>
        </p>

        <h5>March 23 (notation vote) - 2020</h5>
        <p>
          <a href="/newsevents/pressreleases/monetary20200323a.htm">
            Statement
          </a>
        </p>

        <h5>March 17-18 (cancelled) Meeting - 2020</h5>
        <p>
          <a href="/newsevents/pressreleases/monetary20200318a.htm">
            Statement
          </a>
        </p>
      </body>
    </html>
    """

    rows = extract_historical_statement_links(
        html=html,
        index_url=(
            "https://www.federalreserve.gov/"
            "monetarypolicy/"
            "fomchistorical2020.htm"
        ),
        year=2020,
    )

    assert len(rows) == 3
    assert {
        row["decision_date"]
        for row in rows
    } == {
        date(2020, 3, 3),
        date(2020, 3, 15),
        date(2020, 3, 23),
    }
    assert {
        row["meeting_type"]
        for row in rows
    } == {
        "unscheduled",
    }


def test_modern_extraction_excludes_nonstatement_links() -> None:
    html = """
    <html>
      <body>
        <div>
          September 16-17
          Statement:
          <a href="/monetarypolicy/files/monetary20250917a1.pdf">
            PDF
          </a>
          <a href="/newsevents/pressreleases/monetary20250917a.htm">
            HTML
          </a>
        </div>

        <div>
          August 22 (notation vote)
          <a href="/newsevents/pressreleases/monetary20250822a.htm">
            Statement on Longer-Run Goals and Monetary Policy Strategy
          </a>
        </div>

        <a href="/newsevents/pressreleases/monetary20250917b.htm">
          Implementation Note
        </a>

        <a href="/newsevents/pressreleases/monetary20260916a.htm">
          HTML
        </a>
      </body>
    </html>
    """

    rows = extract_modern_statement_links(
        html=html,
        index_url=(
            "https://www.federalreserve.gov/"
            "monetarypolicy/fomccalendars.htm"
        ),
        start_year=2025,
        end_year=2025,
    )

    assert len(rows) == 1
    assert rows[0]["decision_date"] == date(
        2025,
        9,
        17,
    )
    assert rows[0]["statement_url"].endswith(
        "monetary20250917a.htm"
    )


def test_time_fallback_is_conservative() -> None:
    assert scheduled_time_fallback(
        date(
            2014,
            9,
            17,
        ),
        "scheduled",
    ) == (
        "14:00",
        "scheduled_rule_fallback_1400",
    )

    assert scheduled_time_fallback(
        date(
            2012,
            9,
            13,
        ),
        "scheduled",
    ) == (
        None,
        "official_page_date_only",
    )

    assert scheduled_time_fallback(
        date(
            2008,
            1,
            22,
        ),
        "unscheduled",
    ) == (
        None,
        "official_page_date_only",
    )


def test_archive_validation_allows_blank_release_times() -> None:
    archive = pd.DataFrame(
        [
            {
                "event_id": "FED_FOMC_1998_09_29",
                "decision_date": "1998-09-29",
                "release_time_et": "14:15",
                "event_timezone": "America/New_York",
                "meeting_type": "scheduled",
                "meeting_label": "September 29 Meeting - 1998",
                "statement_url": (
                    "https://www.federalreserve.gov/"
                    "boarddocs/press/general/1998/19980929/"
                ),
                "index_url": (
                    "https://www.federalreserve.gov/"
                    "monetarypolicy/fomchistorical1998.htm"
                ),
                "time_source": "scheduled_rule_fallback_1415",
                "verification_status": "official_statement_rule_time",
                "notes": "Test scheduled decision.",
            },
            {
                "event_id": "FED_FOMC_1998_10_15",
                "decision_date": "1998-10-15",
                "release_time_et": "",
                "event_timezone": "America/New_York",
                "meeting_type": "unscheduled",
                "meeting_label": "October 15 Conference Call - 1998",
                "statement_url": (
                    "https://www.federalreserve.gov/"
                    "boarddocs/press/general/1998/19981015/"
                ),
                "index_url": (
                    "https://www.federalreserve.gov/"
                    "monetarypolicy/fomchistorical1998.htm"
                ),
                "time_source": "official_page_date_only",
                "verification_status": "official_statement_date_only",
                "notes": "Test date-only decision.",
            },
        ],
        columns=OUTPUT_COLUMNS,
    )

    validate_decision_archive(
        archive=archive,
        start_year=1998,
        end_year=1998,
    )


def test_registry_merge_is_idempotent_and_preserves_2026() -> None:
    existing = pd.DataFrame(
        [
            {
                "event_id": "OLD_FOMC_2024",
                "event_date": "2024-09-18",
                "event_time_et": "14:00",
                "event_timezone": "America/New_York",
                "source": "Federal Reserve",
                "event_type": "fomc_decision",
                "event_name": "Old historical row",
                "tier": "tier_1",
                "verification_status": "old",
                "source_url": "",
                "notes": "",
            },
            {
                "event_id": "FED_FOMC_2026_09_16",
                "event_date": "2026-09-16",
                "event_time_et": "14:00",
                "event_timezone": "America/New_York",
                "source": "Federal Reserve",
                "event_type": "fomc_decision",
                "event_name": "Scheduled 2026 decision",
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

    historical = pd.DataFrame(
        [
            {
                "event_id": "FED_FOMC_2024_09_18",
                "event_date": "2024-09-18",
                "event_time_et": "14:00",
                "event_timezone": "America/New_York",
                "source": "Federal Reserve",
                "event_type": "fomc_decision",
                "event_name": "FOMC scheduled policy decision",
                "tier": "tier_1",
                "verification_status": "official_statement_exact_time",
                "source_url": "",
                "notes": "",
            }
        ],
        columns=MACRO_COLUMNS,
    )

    merged_once = merge_macro_registry(
        existing=existing,
        historical_rows=historical,
        start_year=2024,
        end_year=2024,
    )

    merged_twice = merge_macro_registry(
        existing=merged_once,
        historical_rows=historical,
        start_year=2024,
        end_year=2024,
    )

    assert "OLD_FOMC_2024" not in set(
        merged_once["event_id"]
    )
    assert "FED_FOMC_2026_09_16" in set(
        merged_once["event_id"]
    )
    assert "OTHER_EVENT" in set(
        merged_once["event_id"]
    )

    pd.testing.assert_frame_equal(
        merged_once,
        merged_twice,
    )
