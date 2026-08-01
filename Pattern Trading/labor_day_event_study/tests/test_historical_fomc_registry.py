from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

FOMC_ARCHIVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "fomc_policy_decisions_1998_2025.csv"
)

MACRO_REGISTRY_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "macro_releases"
    / "macro_events.csv"
)

MAPPED_EVENTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "labor_day_macro_event_map.csv"
)


def load_fomc_archive() -> pd.DataFrame:
    archive = pd.read_csv(
        FOMC_ARCHIVE_PATH,
        dtype=str,
        keep_default_na=False,
    )
    archive["decision_date"] = pd.to_datetime(
        archive["decision_date"],
        errors="raise",
    )
    return archive


def load_macro_registry() -> pd.DataFrame:
    registry = pd.read_csv(
        MACRO_REGISTRY_PATH,
        dtype=str,
        keep_default_na=False,
    )
    registry["event_date"] = pd.to_datetime(
        registry["event_date"],
        errors="raise",
    )
    return registry


def load_mapped_events() -> pd.DataFrame:
    mapped = pd.read_csv(
        MAPPED_EVENTS_PATH,
        dtype=str,
        keep_default_na=False,
    )
    mapped["event_time"] = pd.to_numeric(
        mapped["event_time"],
        errors="raise",
    ).astype(int)
    mapped["event_year"] = pd.to_numeric(
        mapped["event_year"],
        errors="raise",
    ).astype(int)
    return mapped


def test_historical_fomc_archive_exists() -> None:
    assert FOMC_ARCHIVE_PATH.exists(), (
        "Historical FOMC archive is missing. Run "
        "`python -m labor_day.ingest_fomc_decisions`."
    )


def test_historical_fomc_archive_is_complete() -> None:
    archive = load_fomc_archive()

    assert len(archive) == 229
    assert archive["event_id"].nunique() == 229

    meeting_counts = (
        archive["meeting_type"]
        .value_counts()
        .to_dict()
    )

    assert meeting_counts == {
        "scheduled": 215,
        "unscheduled": 14,
    }

    assert archive["decision_date"].dt.year.min() == 1998
    assert archive["decision_date"].dt.year.max() == 2025


def test_historical_fomc_time_quality_counts() -> None:
    archive = load_fomc_archive()

    exact_count = archive[
        "verification_status"
    ].eq(
        "official_statement_exact_time"
    ).sum()

    rule_count = archive[
        "verification_status"
    ].eq(
        "official_statement_rule_time"
    ).sum()

    date_only_count = archive[
        "verification_status"
    ].eq(
        "official_statement_date_only"
    ).sum()

    assert exact_count == 90
    assert rule_count == 118
    assert date_only_count == 21
    assert exact_count + rule_count + date_only_count == 229


def test_registry_contains_all_historical_fomc_rows() -> None:
    archive = load_fomc_archive()
    registry = load_macro_registry()

    historical_registry = registry.loc[
        registry["event_type"].eq("fomc_decision")
        & registry["event_date"].dt.year.between(1998, 2025)
    ]

    assert set(archive["event_id"]) == set(
        historical_registry["event_id"]
    )


def test_registry_has_no_duplicate_event_ids() -> None:
    registry = load_macro_registry()

    duplicated = registry.loc[
        registry["event_id"].duplicated(keep=False),
        "event_id",
    ].tolist()

    assert duplicated == []


def test_2026_scheduled_fomc_row_is_preserved() -> None:
    registry = load_macro_registry()

    fomc_identifier = (
        registry["event_type"].str.contains(
            "fomc",
            case=False,
            regex=False,
            na=False,
        )
        | registry["event_name"].str.contains(
            r"fomc|federal open market",
            case=False,
            regex=True,
            na=False,
        )
    )

    forward_rows = registry.loc[
        registry["event_date"].dt.year.eq(2026)
        & fomc_identifier
    ]

    assert not forward_rows.empty
    assert forward_rows["event_date"].dt.year.eq(2026).all()


def test_2020_emergency_actions_are_unscheduled() -> None:
    archive = load_fomc_archive()

    expected_dates = pd.to_datetime(
        [
            "2020-03-03",
            "2020-03-15",
            "2020-03-23",
        ]
    )

    emergency_rows = archive.loc[
        archive["decision_date"].isin(expected_dates)
    ].sort_values("decision_date")

    assert emergency_rows["decision_date"].tolist() == list(
        expected_dates
    )
    assert emergency_rows["meeting_type"].eq(
        "unscheduled"
    ).all()

    march_23 = emergency_rows.loc[
        emergency_rows["decision_date"].eq(
            pd.Timestamp("2020-03-23")
        )
    ].iloc[0]

    assert march_23["release_time_et"] == "08:00"


def test_2025_strategy_statement_is_excluded() -> None:
    archive = load_fomc_archive()

    assert not archive["decision_date"].eq(
        pd.Timestamp("2025-08-22")
    ).any()


def test_historical_fomc_mappings_have_no_event_zero() -> None:
    mapped = load_mapped_events()

    historical_fomc = mapped.loc[
        mapped["event_type"].eq("fomc_decision")
        & mapped["event_year"].between(1998, 2025)
    ]

    assert not historical_fomc.empty
    assert not historical_fomc["event_time"].eq(0).any()
    assert historical_fomc["event_time"].between(
        -20,
        20,
    ).all()


def test_false_2025_s_minus_6_mapping_is_absent() -> None:
    mapped = load_mapped_events()

    false_mapping = mapped.loc[
        mapped["event_type"].eq("fomc_decision")
        & mapped["event_year"].eq(2025)
        & mapped["event_time"].eq(-6)
    ]

    assert false_mapping.empty