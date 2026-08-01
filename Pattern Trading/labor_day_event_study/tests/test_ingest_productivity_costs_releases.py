from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from labor_day.ingest_productivity_costs_releases import (
    ARCHIVE_URL,
    EXACT_TIME_SOURCE,
    EXACT_VERIFICATION_STATUS,
    KNOWN_URL_HEADER_DATE_MISMATCHES,
    MACRO_COLUMNS,
    OUTPUT_COLUMNS,
    build_macro_rows,
    build_release_archive,
    cache_filename_for_url,
    convert_clock_time,
    create_http_session,
    expected_full_sample_pairs,
    fetch_cached,
    merge_macro_registry,
    parse_archive_label,
    parse_archive_page,
    parse_reference_period_text,
    parse_release_date_from_url,
    parse_release_header,
    parse_source_format,
    quarter_index,
    resolve_event_type,
    validate_release_archive,
)


def make_archive_row(
    *,
    event_id: str = "bls_productivity_costs_20250904_revised",
    release_date: str = "2025-09-04",
    release_time_et: str = "08:30",
    reference_period: str = "2025-Q2",
    release_stage: str = "revised",
    release_url: str = (
        "https://www.bls.gov/news.release/archives/"
        "prod2_09042025.htm"
    ),
    source_format: str = "html",
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "release_date": release_date,
        "release_time_et": release_time_et,
        "event_timezone": "America/New_York",
        "reference_period": reference_period,
        "release_stage": release_stage,
        "archive_label": (
            "2025 Second Quarter (Revised) Productivity and Costs"
        ),
        "release_url": release_url,
        "archive_url": ARCHIVE_URL,
        "source_format": source_format,
        "time_source": EXACT_TIME_SOURCE,
        "verification_status": EXACT_VERIFICATION_STATUS,
        "notes": "Official BLS quarterly release.",
    }


def make_macro_row(
    *, event_id: str, event_date: str, event_type: str, event_name: str = "Test"
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "event_date": event_date,
        "event_time_et": "08:30",
        "event_timezone": "America/New_York",
        "source": "BLS",
        "event_type": event_type,
        "event_name": event_name,
        "tier": "tier_1",
        "verification_status": "official",
        "source_url": "https://www.bls.gov/example",
        "notes": "",
    }


def make_full_sample_archive() -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    first_date = pd.Timestamp("1998-02-10")
    for index, (reference_period, stage) in enumerate(
        expected_full_sample_pairs()
    ):
        release_date = first_date + pd.Timedelta(days=index * 45)
        # The validator checks the full-sample boundary dates. Keep all
        # intermediate dates inside the requested publication range.
        release_date = min(release_date, pd.Timestamp("2025-09-04"))
        date_text = release_date.strftime("%Y-%m-%d")
        url_date = release_date.strftime("%m%d%Y")
        rows.append(
            make_archive_row(
                event_id=(
                    f"bls_productivity_costs_{release_date:%Y%m%d}_{stage}_{index}"
                ),
                release_date=date_text,
                reference_period=reference_period,
                release_stage=stage,
                release_url=(
                    "https://www.bls.gov/news.release/archives/"
                    f"prod2_{url_date}.htm"
                ),
            )
        )
    rows[0]["release_date"] = "1998-02-10"
    rows[0]["release_url"] = (
        "https://www.bls.gov/news.release/history/prod2_021098.txt"
    )
    rows[0]["source_format"] = "txt"
    rows[-1]["release_date"] = "2025-09-04"
    rows[-1]["release_url"] = (
        "https://www.bls.gov/news.release/archives/prod2_09042025.htm"
    )
    rows[-1]["source_format"] = "html"
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    frame.sort_values(["release_date", "event_id"], inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame


def test_http_session_uses_browser_headers() -> None:
    session = create_http_session()
    assert session.headers["User-Agent"].startswith("Mozilla/5.0")
    assert "text/html" in session.headers["Accept"]
    assert session.headers["Referer"].startswith("https://www.bls.gov/")
    assert session._bls_force_curl is False


def test_fetch_cached_switches_to_curl_after_403(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ForbiddenResponse:
        status_code = 403

        def raise_for_status(self) -> None:
            raise AssertionError("403 must switch before raise_for_status")

    class ForbiddenSession:
        def __init__(self) -> None:
            self.headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html",
                "Accept-Language": "en-US",
                "Referer": ARCHIVE_URL,
            }
            self._bls_force_curl = False

        def get(self, url: str, timeout: int) -> ForbiddenResponse:
            assert timeout == 60
            return ForbiddenResponse()

    calls: list[str] = []

    def fake_curl(*, url: str, headers: dict[str, str]) -> bytes:
        calls.append(url)
        assert headers["User-Agent"].startswith("Mozilla")
        return b"official BLS source"

    monkeypatch.setattr(
        "labor_day.ingest_productivity_costs_releases.fetch_with_curl",
        fake_curl,
    )
    session = ForbiddenSession()
    cache_path = tmp_path / "archive.htm"
    content, downloaded = fetch_cached(
        session=session,
        url=ARCHIVE_URL,
        cache_path=cache_path,
        refresh=False,
        offline=False,
    )
    assert content == b"official BLS source"
    assert downloaded is True
    assert calls == [ARCHIVE_URL]
    assert session._bls_force_curl is True
    assert cache_path.read_bytes() == content


def test_convert_clock_time_supports_historical_and_modern_times() -> None:
    assert convert_clock_time(10, 0, "A") == "10:00"
    assert convert_clock_time(8, 30, "a") == "08:30"
    assert convert_clock_time(12, 0, "P") == "12:00"


def test_parse_old_six_digit_release_url() -> None:
    parsed = parse_release_date_from_url(
        "https://www.bls.gov/news.release/history/prod2_031098.txt"
    )
    assert parsed == date(1998, 3, 10)


def test_parse_modern_eight_digit_release_url() -> None:
    parsed = parse_release_date_from_url(
        "https://www.bls.gov/news.release/archives/prod2_09042025.htm"
    )
    assert parsed == date(2025, 9, 4)


def test_parse_source_formats() -> None:
    assert parse_source_format("https://x/prod2_09042025.htm") == "html"
    assert parse_source_format("https://x/prod2_031098.txt") == "txt"


def test_parse_standard_archive_label() -> None:
    assert parse_archive_label(
        "2025 Second Quarter (Revised) Productivity and Costs (PDF)"
    ) == ("2025-Q2", "revised")


def test_parse_hyphenated_preliminary_archive_label() -> None:
    assert parse_archive_label(
        "1998 Fourth-Quarter and Annual Averages (Preliminary) "
        "Productivity and Costs (TXT)"
    ) == ("1998-Q4", "preliminary")


def test_parse_irregular_1997_revised_archive_label() -> None:
    assert parse_archive_label(
        "1997 Fourth Quarter and Annual Averages "
        "(Revised Productivity and Costs) (TXT)"
    ) == ("1997-Q4", "revised")


def test_parse_reference_period_from_modern_page() -> None:
    text = "PRODUCTIVITY AND COSTS First Quarter 2026, Preliminary"
    assert parse_reference_period_text(text) == "2026-Q1"


def test_parse_reference_period_from_old_page() -> None:
    text = (
        "PRODUCTIVITY AND COSTS Fourth Quarter and Annual Averages, "
        "1997 The Bureau reported revised estimates."
    )
    assert parse_reference_period_text(text) == "1997-Q4"


def test_parse_1998_release_header_at_1000() -> None:
    text = (
        "USDL 98-92 TRANSMISSION OF THIS MATERIAL IS EMBARGOED UNTIL "
        "10:00 A.M. EST TUESDAY, MARCH 10, 1998. PRODUCTIVITY AND COSTS"
    )
    assert parse_release_header(text) == ("10:00", date(1998, 3, 10))


def test_parse_2003_release_header_with_abbreviated_month() -> None:
    text = (
        "USDL 03-411 TRANSMISSION OF THIS MATERIAL IS EMBARGOED UNTIL "
        "8:30 A.M. EDT, THURSDAY, AUG. 7, 2003. "
        "PRODUCTIVITY AND COSTS Second Quarter 2003"
    )
    assert parse_release_header(text) == ("08:30", date(2003, 8, 7))


def test_parse_release_header_supports_standard_month_abbreviations() -> None:
    examples = {
        "JAN. 8, 2004": date(2004, 1, 8),
        "FEB. 5, 2004": date(2004, 2, 5),
        "MAR. 4, 2004": date(2004, 3, 4),
        "APR. 1, 2004": date(2004, 4, 1),
        "JUN. 3, 2004": date(2004, 6, 3),
        "JUL. 1, 2004": date(2004, 7, 1),
        "SEPT. 2, 2004": date(2004, 9, 2),
        "OCT. 7, 2004": date(2004, 10, 7),
        "NOV. 4, 2004": date(2004, 11, 4),
        "DEC. 2, 2004": date(2004, 12, 2),
    }
    for month_date, expected in examples.items():
        text = (
            "TRANSMISSION OF THIS MATERIAL IS EMBARGOED UNTIL "
            f"8:30 A.M. EDT, THURSDAY, {month_date}."
        )
        assert parse_release_header(text) == ("08:30", expected)


def test_parse_modern_release_header_at_0830() -> None:
    text = (
        "Navigation text " * 500
        + "Transmission of material in this release is embargoed until "
        "8:30 a.m. (ET) Thursday, September 4, 2025 "
        "PRODUCTIVITY AND COSTS Second Quarter 2025, Revised"
    )
    assert parse_release_header(text) == ("08:30", date(2025, 9, 4))


def test_archive_parser_uses_actual_publication_year_and_prefers_html() -> None:
    html = """
    <ul>
      <li>1997 Fourth-Quarter and Annual Averages (Preliminary)
        Productivity and Costs
        <a href="/news.release/history/prod2_021098.txt">TXT</a>
      </li>
      <li>2007 Fourth Quarter (Revised) Productivity and Costs
        <a href="/news.release/archives/prod2_03052008.htm">Title</a>
        <a href="/news.release/pdf/prod2_03052008.pdf">PDF</a>
      </li>
      <li>2025 Third Quarter (Preliminary) Productivity and Costs
        <a href="/news.release/archives/prod2_01082026.htm">Title</a>
      </li>
    </ul>
    """
    parsed = parse_archive_page(
        html=html,
        archive_url=ARCHIVE_URL,
        start_year=1998,
        end_year=2025,
    )
    assert len(parsed) == 2
    assert parsed[0]["reference_period"] == "1997-Q4"
    assert parsed[0]["release_date"] == "1998-02-10"
    assert parsed[1]["reference_period"] == "2007-Q4"
    assert parsed[1]["source_format"] == "html"


def test_archive_parser_chooses_txt_when_pdf_is_only_alternative() -> None:
    html = """
    <ul><li>2006 Fourth Quarter (Revised) Productivity and Costs
      <a href="/news.release/history/prod2_03062007.txt">TXT</a>
      <a href="/news.release/pdf/prod2_03062007.pdf">PDF</a>
    </li></ul>
    """
    parsed = parse_archive_page(
        html=html,
        archive_url=ARCHIVE_URL,
        start_year=2007,
        end_year=2007,
    )
    assert len(parsed) == 1
    assert parsed[0]["source_format"] == "txt"


def test_cache_filename_is_collision_resistant() -> None:
    first = cache_filename_for_url(
        "https://www.bls.gov/news.release/history/prod2_031098.txt"
    )
    second = cache_filename_for_url(
        "https://example.test/history/prod2_031098.txt"
    )
    assert first != second
    assert first.endswith(".txt")


def test_quarter_index_and_expected_pairs() -> None:
    assert quarter_index("1997-Q4") + 1 == quarter_index("1998-Q1")
    pairs = expected_full_sample_pairs()
    assert len(pairs) == 222
    assert pairs[0] == ("1997-Q4", "preliminary")
    assert pairs[1] == ("1997-Q4", "revised")
    assert pairs[-1] == ("2025-Q2", "revised")


def test_build_release_archive_parses_and_verifies_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    links = [
        {
            "release_date": "1998-03-10",
            "reference_period": "1997-Q4",
            "release_stage": "revised",
            "archive_label": (
                "1997 Fourth Quarter and Annual Averages "
                "(Revised Productivity and Costs)"
            ),
            "release_url": (
                "https://www.bls.gov/news.release/history/prod2_031098.txt"
            ),
            "archive_url": ARCHIVE_URL,
            "source_format": "txt",
        }
    ]
    source = (
        b"TRANSMISSION OF THIS MATERIAL IS EMBARGOED UNTIL 10:00 A.M. "
        b"EST TUESDAY, MARCH 10, 1998. PRODUCTIVITY AND COSTS Fourth "
        b"Quarter and Annual Averages, 1997 revised estimates."
    )

    def fake_fetch_cached(**kwargs):
        return source, False

    monkeypatch.setattr(
        "labor_day.ingest_productivity_costs_releases.fetch_cached",
        fake_fetch_cached,
    )
    archive, documents = build_release_archive(
        release_links=links,
        session=object(),
        cache_dir=tmp_path,
        refresh=False,
        offline=False,
        request_delay=0,
    )
    assert len(archive) == 1
    assert archive.iloc[0]["release_time_et"] == "10:00"
    assert archive.iloc[0]["reference_period"] == "1997-Q4"
    assert archive.iloc[0]["release_stage"] == "revised"
    assert documents == [source]


def test_documented_1999_filename_header_date_mismatch_is_exact() -> None:
    documented = KNOWN_URL_HEADER_DATE_MISMATCHES[
        "https://www.bls.gov/news.release/history/prod2_11151999.txt"
    ]
    assert documented["url_date"] == date(1999, 11, 15)
    assert documented["header_date"] == date(1999, 11, 12)


def test_build_release_archive_uses_header_date_for_documented_1999_anomaly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    links = [
        {
            "release_date": "1999-11-15",
            "reference_period": "1999-Q3",
            "release_stage": "preliminary",
            "archive_label": (
                "1999 Third Quarter (Preliminary) Productivity and Costs"
            ),
            "release_url": (
                "https://www.bls.gov/news.release/history/"
                "prod2_11151999.txt"
            ),
            "archive_url": ARCHIVE_URL,
            "source_format": "txt",
        }
    ]
    source = (
        b"TRANSMISSION OF THIS MATERIAL IS EMBARGOED UNTIL 8:30 A.M. EST, "
        b"FRIDAY, NOVEMBER 12, 1999. PRODUCTIVITY AND COSTS Third Quarter "
        b"1999 preliminary productivity data."
    )
    monkeypatch.setattr(
        "labor_day.ingest_productivity_costs_releases.fetch_cached",
        lambda **kwargs: (source, False),
    )

    archive, _ = build_release_archive(
        release_links=links,
        session=object(),
        cache_dir=tmp_path,
        refresh=False,
        offline=False,
        request_delay=0,
    )

    row = archive.iloc[0]
    assert row["release_date"] == "1999-11-12"
    assert row["event_id"] == (
        "bls_productivity_costs_19991112_preliminary"
    )
    assert row["release_time_et"] == "08:30"
    assert "header date used as authoritative" in row["notes"]


def test_build_release_archive_rejects_header_date_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    links = [
        {
            "release_date": "2025-09-04",
            "reference_period": "2025-Q2",
            "release_stage": "revised",
            "archive_label": "2025 Second Quarter (Revised) Productivity and Costs",
            "release_url": (
                "https://www.bls.gov/news.release/archives/prod2_09042025.htm"
            ),
            "archive_url": ARCHIVE_URL,
            "source_format": "html",
        }
    ]
    source = (
        b"<html><body>Transmission of material is embargoed until 8:30 a.m. "
        b"(ET) Thursday, September 5, 2025 PRODUCTIVITY AND COSTS "
        b"Second Quarter 2025, Revised</body></html>"
    )
    monkeypatch.setattr(
        "labor_day.ingest_productivity_costs_releases.fetch_cached",
        lambda **kwargs: (source, False),
    )
    with pytest.raises(ValueError, match="header date does not match"):
        build_release_archive(
            release_links=links,
            session=object(),
            cache_dir=tmp_path,
            refresh=False,
            offline=False,
            request_delay=0,
        )


def test_validate_full_sample_accepts_complete_sequence() -> None:
    archive = make_full_sample_archive()
    validate_release_archive(archive=archive, start_year=1998, end_year=2025)


def test_validate_rejects_duplicate_reference_stage() -> None:
    archive = pd.DataFrame(
        [make_archive_row(), make_archive_row(event_id="different")],
        columns=OUTPUT_COLUMNS,
    )
    with pytest.raises(ValueError, match="duplicate reference-period/stage"):
        validate_release_archive(archive=archive, start_year=2025, end_year=2025)


def test_validate_rejects_non_bls_url() -> None:
    archive = pd.DataFrame(
        [make_archive_row(release_url="https://example.test/prod2_09042025.htm")],
        columns=OUTPUT_COLUMNS,
    )
    with pytest.raises(ValueError, match="Non-BLS"):
        validate_release_archive(archive=archive, start_year=2025, end_year=2025)


def test_resolve_event_type_uses_seeded_project_value() -> None:
    existing = pd.DataFrame(
        [
            make_macro_row(
                event_id="seed",
                event_date="2026-09-03",
                event_type="productivity_and_costs",
                event_name="Productivity and Costs",
            )
        ],
        columns=MACRO_COLUMNS,
    )
    assert resolve_event_type(existing) == "productivity_and_costs"


def test_resolve_event_type_defaults_when_no_seed_exists() -> None:
    existing = pd.DataFrame(
        [make_macro_row(event_id="other", event_date="2026-01-01", event_type="cpi")],
        columns=MACRO_COLUMNS,
    )
    assert resolve_event_type(existing) == "productivity_costs"


def test_build_macro_rows_preserves_stage_in_notes() -> None:
    archive = pd.DataFrame([make_archive_row()], columns=OUTPUT_COLUMNS)
    rows = build_macro_rows(archive, event_type="productivity_costs")
    assert rows.iloc[0]["event_type"] == "productivity_costs"
    assert rows.iloc[0]["event_name"] == "Productivity and Costs"
    assert rows.iloc[0]["tier"] == "tier_1"
    assert "Revised" in rows.iloc[0]["notes"]


def test_merge_is_idempotent_and_preserves_2026_seed() -> None:
    existing = pd.DataFrame(
        [
            make_macro_row(
                event_id="old_historical",
                event_date="2024-09-05",
                event_type="productivity_costs",
            ),
            make_macro_row(
                event_id="seed_2026",
                event_date="2026-09-03",
                event_type="productivity_costs",
            ),
            make_macro_row(
                event_id="cpi_2024",
                event_date="2024-08-14",
                event_type="cpi",
            ),
        ],
        columns=MACRO_COLUMNS,
    )
    historical = pd.DataFrame(
        [
            make_macro_row(
                event_id="new_historical",
                event_date="2024-09-05",
                event_type="productivity_costs",
            )
        ],
        columns=MACRO_COLUMNS,
    )
    first = merge_macro_registry(
        existing=existing,
        historical_rows=historical,
        event_type="productivity_costs",
        start_year=1998,
        end_year=2025,
    )
    second = merge_macro_registry(
        existing=first,
        historical_rows=historical,
        event_type="productivity_costs",
        start_year=1998,
        end_year=2025,
    )
    assert set(first["event_id"]) == {
        "new_historical",
        "seed_2026",
        "cpi_2024",
    }
    pd.testing.assert_frame_equal(first, second)


def test_parse_release_header_allows_usdl_code_before_time() -> None:
    text = (
        "Transmission of this material is embargoed until USDL-09-0933 "
        "8:30 a.m. (EDT) Tuesday, August 11, 2009 "
        "PRODUCTIVITY AND COSTS Second Quarter 2009, Preliminary"
    )

    assert parse_release_header(text) == ("08:30", date(2009, 8, 11))


def test_parse_release_header_supports_for_release_and_ordinal_date() -> None:
    text = (
        "FOR RELEASE: 10 A. M. EST Thursday, May 7th, 1998 "
        "PRODUCTIVITY AND COSTS First Quarter 1998, Preliminary"
    )

    assert parse_release_header(text) == ("10:00", date(1998, 5, 7))


def test_parse_release_header_ignores_later_next_release_time() -> None:
    text = (
        "USDL 09-0001 Transmission of this material is embargoed until "
        "8:30 a.m. EST Thursday, February 5, 2009. "
        "PRODUCTIVITY AND COSTS Fourth Quarter 2008, Preliminary. "
        "The next release is scheduled for 8:30 a.m. Friday, March 6, 2009."
    )

    assert parse_release_header(text) == ("08:30", date(2009, 2, 5))


def test_parse_release_header_returns_none_when_header_has_no_calendar_date() -> None:
    text = (
        "Transmission of this material is embargoed until USDL-09-0933 "
        "8:30 a.m. (EDT). PRODUCTIVITY AND COSTS"
    )

    assert parse_release_header(text) == (None, None)