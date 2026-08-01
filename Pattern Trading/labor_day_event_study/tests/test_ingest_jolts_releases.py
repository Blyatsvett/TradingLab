from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from labor_day.ingest_jolts_releases import (
    MACRO_COLUMNS,
    OUTPUT_COLUMNS,
    build_macro_rows,
    convert_clock_time,
    create_http_session,
    fetch_cached,
    merge_macro_registry,
    parse_archive_page,
    parse_reference_period_label,
    parse_reference_period_text,
    parse_release_date_from_url,
    parse_release_time,
    validate_release_archive,
)


ARCHIVE_URL = (
    "https://www.bls.gov/bls/news-release/jolts.htm"
)


def make_archive_row(
    *,
    event_id: str = "bls_jolts_20240904",
    release_date: str = "2024-09-04",
    release_time_et: str = "10:00",
    reference_period: str = "2024-07",
    verification_status: str = (
        "official_release_page_exact_time"
    ),
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "release_date": release_date,
        "release_time_et": release_time_et,
        "event_timezone": "America/New_York",
        "reference_period": reference_period,
        "archive_label": "July 2024 (HTML) (PDF)",
        "release_url": (
            "https://www.bls.gov/news.release/"
            "archives/jolts_09042024.htm"
        ),
        "archive_url": ARCHIVE_URL,
        "source_format": "html",
        "time_source": (
            "official_for_release"
            if release_time_et
            else "official_page_date_only"
        ),
        "verification_status": verification_status,
        "notes": "Official national JOLTS news release.",
    }


def make_macro_row(
    *,
    event_id: str,
    event_date: str,
    event_type: str,
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "event_date": event_date,
        "event_time_et": "10:00",
        "event_timezone": "America/New_York",
        "source": "BLS",
        "event_type": event_type,
        "event_name": "Test event",
        "tier": "tier_1",
        "verification_status": "official",
        "source_url": "https://example.test",
        "notes": "",
    }


def test_http_session_uses_browser_navigation_headers() -> None:
    session = create_http_session()

    assert session.headers["User-Agent"].startswith(
        "Mozilla/5.0"
    )
    assert "text/html" in session.headers["Accept"]
    assert session.headers["Referer"].startswith(
        "https://www.bls.gov/"
    )
    assert session._bls_force_curl is False


def test_fetch_cached_switches_to_curl_after_403(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class ForbiddenResponse:
        status_code = 403

        def raise_for_status(self) -> None:
            raise AssertionError(
                "403 should be handled before raise_for_status"
            )

    class ForbiddenSession:
        def __init__(self) -> None:
            self.headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html",
                "Accept-Language": "en-US",
                "Referer": "https://www.bls.gov/jlt/news.htm",
            }
            self._bls_force_curl = False

        def get(
            self,
            url: str,
            timeout: int,
        ) -> ForbiddenResponse:
            assert url.startswith(
                "https://www.bls.gov/"
            )
            assert timeout == 60
            return ForbiddenResponse()

    fallback_calls: list[str] = []

    def fake_curl(
        *,
        url: str,
        headers: dict[str, str],
    ) -> bytes:
        fallback_calls.append(
            url
        )
        assert headers[
            "User-Agent"
        ].startswith(
            "Mozilla"
        )
        return b"official BLS content"

    monkeypatch.setattr(
        "labor_day.ingest_jolts_releases.fetch_with_curl",
        fake_curl,
    )

    session = ForbiddenSession()
    cache_path = tmp_path / "source.htm"

    content, downloaded = fetch_cached(
        session=session,
        url=(
            "https://www.bls.gov/bls/"
            "news-release/jolts.htm"
        ),
        cache_path=cache_path,
        refresh=False,
        offline=False,
    )

    assert content == b"official BLS content"
    assert downloaded is True
    assert fallback_calls == [
        (
            "https://www.bls.gov/bls/"
            "news-release/jolts.htm"
        )
    ]
    assert session._bls_force_curl is True
    assert cache_path.read_bytes() == content


def test_parse_release_date_from_html_url() -> None:
    parsed = parse_release_date_from_url(
        "https://www.bls.gov/news.release/"
        "archives/jolts_09042024.htm"
    )

    assert parsed == date(
        2024,
        9,
        4,
    )


def test_parse_release_date_from_old_txt_url() -> None:
    parsed = parse_release_date_from_url(
        "https://www.bls.gov/news.release/"
        "history/jolts_04152004.txt"
    )

    assert parsed == date(
        2004,
        4,
        15,
    )


def test_archive_page_selects_html_txt_and_release_years() -> None:
    html = """
    <ul>
      <li>July 2024
        <a href="/news.release/archives/jolts_09042024.htm">
          HTML
        </a>
        <a href="/news.release/pdf/jolts.pdf">PDF</a>
      </li>
      <li>February 2004
        <a href="/news.release/history/jolts_04152004.txt">
          TXT
        </a>
      </li>
      <li>May 2026
        <a href="/news.release/archives/jolts_06302026.htm">
          HTML
        </a>
      </li>
    </ul>
    """

    links = parse_archive_page(
        html=html,
        archive_url=ARCHIVE_URL,
        start_year=1998,
        end_year=2025,
    )

    assert len(links) == 2
    assert {
        row["source_format"]
        for row in links
    } == {
        "html",
        "txt",
    }
    assert links[0]["release_date"] == "2004-04-15"
    assert links[1]["release_date"] == "2024-09-04"


def test_parse_modern_release_time() -> None:
    release_time, source = parse_release_time(
        "For release 10:00 a.m. (ET) "
        "Wednesday, September 4, 2024"
    )

    assert release_time == "10:00"
    assert source == "official_for_release"


def test_parse_old_txt_release_time() -> None:
    release_time, source = parse_release_time(
        "FOR RELEASE: 10:00 A.M. EDT "
        "THURSDAY, APRIL 15, 2004"
    )

    assert release_time == "10:00"
    assert source == "official_for_release"


def test_convert_clock_time_handles_noon_and_midnight() -> None:
    assert convert_clock_time(
        12,
        0,
        "a",
    ) == "00:00"

    assert convert_clock_time(
        12,
        0,
        "p",
    ) == "12:00"


def test_parse_reference_period_from_release_heading() -> None:
    assert parse_reference_period_text(
        "JOB OPENINGS AND LABOR TURNOVER — JULY 2024"
    ) == "2024-07"

    assert parse_reference_period_text(
        "JOB OPENINGS AND LABOR TURNOVER: FEBRUARY 2004"
    ) == "2004-02"


def test_parse_reference_period_label_fallback() -> None:
    assert parse_reference_period_label(
        "August 2007 (TXT) (PDF)"
    ) == "2007-08"


def test_archive_validation_allows_blank_release_time() -> None:
    archive = pd.DataFrame(
        [
            make_archive_row(
                event_id="bls_jolts_20250801",
                release_date="2025-08-01",
                release_time_et="",
                reference_period="2025-06",
                verification_status=(
                    "official_release_page_date_only"
                ),
            )
        ],
        columns=OUTPUT_COLUMNS,
    )

    validate_release_archive(
        archive=archive,
        start_year=2025,
        end_year=2025,
    )


def test_archive_validation_requires_official_2004_start() -> None:
    archive = pd.DataFrame(
        [
            make_archive_row(
                event_id="bls_jolts_20040415",
                release_date="2004-04-15",
                reference_period="2004-02",
            )
        ],
        columns=OUTPUT_COLUMNS,
    )

    validate_release_archive(
        archive=archive,
        start_year=1998,
        end_year=2004,
    )

    bad_archive = archive.copy()
    bad_archive.loc[
        0,
        "reference_period",
    ] = "2004-03"

    with pytest.raises(
        ValueError,
        match="2004-02",
    ):
        validate_release_archive(
            archive=bad_archive,
            start_year=1998,
            end_year=2004,
        )


def test_macro_rows_use_project_schema() -> None:
    archive = pd.DataFrame(
        [
            make_archive_row()
        ],
        columns=OUTPUT_COLUMNS,
    )

    macro_rows = build_macro_rows(
        archive
    )

    assert list(
        macro_rows.columns
    ) == MACRO_COLUMNS
    assert len(
        macro_rows
    ) == 1
    assert macro_rows.loc[
        0,
        "event_type",
    ] == "jolts"
    assert macro_rows.loc[
        0,
        "tier",
    ] == "tier_1"


def test_registry_merge_is_idempotent_and_preserves_2026() -> None:
    existing = pd.DataFrame(
        [
            make_macro_row(
                event_id="old_jolts_20240904",
                event_date="2024-09-04",
                event_type="jolts",
            ),
            make_macro_row(
                event_id="scheduled_jolts_20260901",
                event_date="2026-09-01",
                event_type="jolts",
            ),
            make_macro_row(
                event_id="other_20240904",
                event_date="2024-09-04",
                event_type="employment_situation",
            ),
        ],
        columns=MACRO_COLUMNS,
    )

    archive = pd.DataFrame(
        [
            make_archive_row()
        ],
        columns=OUTPUT_COLUMNS,
    )
    historical = build_macro_rows(
        archive
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
        == "scheduled_jolts_20260901"
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
        == "old_jolts_20240904"
    ).any()