from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from labor_day.universe import (
    ALLOWED_HYPOTHESES,
    DEFAULT_UNIVERSE_PATH,
    EXPECTED_COLUMNS,
    FORWARD_YEAR,
    UniverseValidationError,
    build_universe_artifacts,
    build_year_panel,
    eligible_instruments,
    normalize_universe,
    read_universe,
    resolve_benchmark,
    sample_for_year,
    validate_universe,
)


EXPECTED_HYPOTHESIS_COUNTS = {
    "generic_control": 5,
    "refining_gasoline": 5,
    "auto_dealers": 5,
    "domestic_leisure_travel": 10,
}


def raw_universe() -> pd.DataFrame:
    return pd.read_csv(
        DEFAULT_UNIVERSE_PATH,
        dtype=str,
        keep_default_na=False,
    )


def universe() -> pd.DataFrame:
    return read_universe(DEFAULT_UNIVERSE_PATH)


def test_frozen_universe_file_exists() -> None:
    assert DEFAULT_UNIVERSE_PATH.exists()


def test_schema_is_exact_and_ordered() -> None:
    frame = raw_universe()
    assert list(frame.columns) == EXPECTED_COLUMNS


def test_universe_validates_and_contains_25_rows() -> None:
    frame = universe()
    assert len(frame) == 25
    assert frame["ticker"].nunique() == 25
    assert frame["provider_symbol"].nunique() == 25


def test_hypothesis_counts_are_frozen() -> None:
    counts = (
        universe()["hypothesis"].value_counts().to_dict()
    )
    assert counts == EXPECTED_HYPOTHESIS_COUNTS


def test_all_hypotheses_are_allowed() -> None:
    assert set(universe()["hypothesis"]).issubset(
        ALLOWED_HYPOTHESES
    )


def test_role_counts_are_frozen() -> None:
    counts = universe()["role"].value_counts().to_dict()
    assert counts == {
        "hypothesis_stock": 20,
        "sector_benchmark": 2,
        "market_benchmark": 1,
        "negative_control": 1,
        "size_control": 1,
    }


def test_spy_is_unique_market_benchmark() -> None:
    market = universe().loc[
        universe()["role"].eq("market_benchmark")
    ]
    assert len(market) == 1
    assert market.iloc[0]["ticker"] == "SPY"
    assert market.iloc[0]["primary_benchmark"] == ""
    assert market.iloc[0]["fallback_benchmark"] == ""


def test_target_groups_use_frozen_benchmarks() -> None:
    frame = universe()

    refiners = frame.loc[
        frame["hypothesis"].eq("refining_gasoline")
    ]
    assert refiners["primary_benchmark"].eq("XLE").all()
    assert refiners["fallback_benchmark"].eq("SPY").all()

    consumer = frame.loc[
        frame["hypothesis"].isin(
            {
                "auto_dealers",
                "domestic_leisure_travel",
            }
        )
    ]
    assert consumer["primary_benchmark"].eq("XLY").all()
    assert consumer["fallback_benchmark"].eq("SPY").all()


def test_sample_boundaries_are_frozen() -> None:
    assert sample_for_year(1998) == "discovery"
    assert sample_for_year(2014) == "discovery"
    assert sample_for_year(2015) == "validation"
    assert sample_for_year(2025) == "validation"
    assert sample_for_year(2026) == "forward"

    with pytest.raises(ValueError, match="outside"):
        sample_for_year(1997)
    with pytest.raises(ValueError, match="outside"):
        sample_for_year(2027)


def test_eligible_counts_by_landmark_year() -> None:
    frame = universe()
    expected = {
        1998: 12,
        1999: 15,
        2000: 17,
        2005: 24,
        2006: 25,
        2014: 25,
        2025: 25,
        2026: 25,
    }
    actual = {
        year: len(eligible_instruments(frame, year))
        for year in expected
    }
    assert actual == expected


def test_vlo_uses_spy_fallback_in_1998() -> None:
    assert resolve_benchmark(
        universe(),
        "VLO",
        1998,
    ) == ("SPY", "fallback")


def test_vlo_uses_xle_from_1999() -> None:
    assert resolve_benchmark(
        universe(),
        "VLO",
        1999,
    ) == ("XLE", "primary")


def test_auto_dealers_use_spy_in_1998_and_xly_afterward() -> None:
    frame = universe()
    assert resolve_benchmark(
        frame,
        "KMX",
        1998,
    ) == ("SPY", "fallback")
    assert resolve_benchmark(
        frame,
        "KMX",
        1999,
    ) == ("XLY", "primary")


def test_market_benchmark_resolves_to_none() -> None:
    assert resolve_benchmark(
        universe(),
        "SPY",
        1998,
    ) == ("", "none")


def test_year_panel_has_frozen_row_count() -> None:
    panel = build_year_panel(universe())
    assert len(panel) == 613
    assert not panel.duplicated(
        ["event_year", "ticker"]
    ).any()


def test_year_panel_has_expected_sample_counts() -> None:
    panel = build_year_panel(universe())
    counts = panel["sample"].value_counts().to_dict()
    assert counts == {
        "discovery": 313,
        "validation": 275,
        "forward": 25,
    }


def test_equal_weights_sum_to_one_by_group_year() -> None:
    panel = build_year_panel(universe())
    stocks = panel.loc[
        panel["role"].eq("hypothesis_stock")
    ].copy()
    sums = stocks.groupby(
        ["event_year", "hypothesis"]
    )["equal_weight"].sum()
    assert sums.map(
        lambda value: abs(float(value) - 1.0) < 1e-12
    ).all()


def test_1998_group_member_counts_are_dynamic() -> None:
    panel = build_year_panel(universe())
    year = panel.loc[panel["event_year"].eq(1998)]

    refinery = year.loc[
        year["hypothesis"].eq("refining_gasoline")
    ]
    assert refinery["ticker"].tolist() == ["VLO"]
    assert refinery["eligible_group_members"].tolist() == [1]
    assert refinery["equal_weight"].tolist() == [1.0]

    travel = year.loc[
        year["hypothesis"].eq("domestic_leisure_travel")
    ]
    assert len(travel) == 5
    assert travel["eligible_group_members"].eq(5).all()
    assert travel["equal_weight"].eq(0.2).all()


def test_predecessor_rows_are_explicit() -> None:
    frame = universe()
    predecessor = frame.loc[
        frame["continuity_status"].eq(
            "predecessor_continuity"
        )
    ].set_index("ticker")

    assert set(predecessor.index) == {
        "DINO",
        "PAG",
        "BKNG",
    }
    assert predecessor.loc["DINO", "predecessor_symbols"] == "HFC"
    assert predecessor.loc["PAG", "predecessor_symbols"] == "UAG"
    assert predecessor.loc["BKNG", "predecessor_symbols"] == "PCLN"


def test_current_public_era_rows_do_not_backfill_predecessors() -> None:
    frame = universe()
    current_era = set(
        frame.loc[
            frame["continuity_status"].eq(
                "current_public_era"
            ),
            "ticker",
        ]
    )
    assert current_era == {
        "MPC",
        "PSX",
        "PBF",
        "HLT",
        "DAL",
        "UAL",
    }


def test_duplicate_ticker_is_rejected() -> None:
    frame = raw_universe()
    duplicate = pd.concat(
        [frame, frame.iloc[[0]]],
        ignore_index=True,
    )
    with pytest.raises(
        UniverseValidationError,
        match="Duplicate ticker",
    ):
        validate_universe(duplicate)


def test_unknown_benchmark_is_rejected() -> None:
    frame = raw_universe()
    frame.loc[
        frame["ticker"].eq("VLO"),
        "primary_benchmark",
    ] = "MISSING"
    with pytest.raises(
        UniverseValidationError,
        match="Unknown primary_benchmark",
    ):
        validate_universe(frame)


def test_inconsistent_sample_flag_is_rejected() -> None:
    frame = raw_universe()
    frame.loc[
        frame["ticker"].eq("HLT"),
        "discovery_eligible",
    ] = "false"
    with pytest.raises(
        UniverseValidationError,
        match="discovery_eligible conflicts",
    ):
        validate_universe(frame)


def test_bad_boolean_is_rejected() -> None:
    frame = raw_universe()
    frame.loc[
        frame["ticker"].eq("SPY"),
        "forward_eligible",
    ] = "yes"
    with pytest.raises(
        UniverseValidationError,
        match="true/false",
    ):
        validate_universe(frame)


def test_predecessor_continuity_requires_symbol() -> None:
    frame = raw_universe()
    frame.loc[
        frame["ticker"].eq("DINO"),
        "predecessor_symbols",
    ] = ""
    with pytest.raises(
        UniverseValidationError,
        match="requires predecessor_symbols",
    ):
        validate_universe(frame)


def test_normalization_parses_years_and_booleans() -> None:
    normalized = normalize_universe(raw_universe())
    assert str(normalized["analysis_start_year"].dtype) == "Int64"
    assert str(normalized["analysis_end_year"].dtype) == "Int64"
    assert normalized["discovery_eligible"].dtype == bool
    assert normalized["validation_eligible"].dtype == bool
    assert normalized["forward_eligible"].dtype == bool


def test_filtering_by_hypothesis_and_role() -> None:
    frame = universe()
    refiners = eligible_instruments(
        frame,
        2014,
        hypothesis="refining_gasoline",
        role="hypothesis_stock",
    )
    assert set(refiners["ticker"]) == {
        "VLO",
        "MPC",
        "PSX",
        "DINO",
        "PBF",
    }


def test_invalid_panel_range_is_rejected() -> None:
    frame = universe()
    with pytest.raises(ValueError, match="precede"):
        build_year_panel(frame, start_year=1997)
    with pytest.raises(ValueError, match="exceed"):
        build_year_panel(frame, end_year=FORWARD_YEAR + 1)
    with pytest.raises(ValueError, match="must not exceed"):
        build_year_panel(
            frame,
            start_year=2020,
            end_year=2019,
        )


def test_build_artifacts_writes_panel_and_manifest(
    tmp_path: Path,
) -> None:
    panel_path = tmp_path / "panel.csv"
    manifest_path = tmp_path / "manifest.json"

    result = build_universe_artifacts(
        universe_path=DEFAULT_UNIVERSE_PATH,
        panel_path=panel_path,
        manifest_path=manifest_path,
    )

    assert panel_path.exists()
    assert manifest_path.exists()
    assert len(result.universe) == 25
    assert len(result.panel) == 613

    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["version"] == "1.0.0"
    assert manifest["universe"]["rows"] == 25
    assert manifest["year_panel"]["rows"] == 613
    assert manifest["universe"]["hypothesis_counts"] == (
        EXPECTED_HYPOTHESIS_COUNTS
    )
    assert manifest["year_panel"]["rows_by_year"]["1998"] == 12
    assert manifest["year_panel"]["rows_by_year"]["2014"] == 25
    assert manifest["year_panel"]["rows_by_year"]["2026"] == 25
