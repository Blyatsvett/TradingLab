from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from RegimeTrading.scripts import step9kpi_read_only_evaluation_v1 as kpi


HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parents[1]
CONFIG = PROJECT_ROOT / "config" / "step9kpi_read_only_evaluation_v1.json"
SCHEMA = PROJECT_ROOT / "config" / "step9kpi_output_schema_v1.json"


def test_01_identifiers_are_frozen() -> None:
    assert kpi.SPECIFICATION_ID == "STEP9KPI_READ_ONLY_EVALUATION_V1"
    assert kpi.SCHEMA_ID == "STEP9_KPI_OUTPUT_SCHEMA_V1"
    assert "READ_ONLY" in kpi.STATUS


def test_02_config_loads_with_router_and_orders_disabled() -> None:
    config = kpi._read_config(CONFIG)
    assert config["router_active"] is False
    assert config["orders_enabled"] is False
    assert config["comparison_notional_sek"] == 1000.0


def test_03_config_rejects_active_router(tmp_path: Path) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["router_active"] = True
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(kpi.SourceContractError):
        kpi._read_config(path)


def test_04_schema_contains_exact_required_tables() -> None:
    schema = kpi._read_schema(SCHEMA)
    expected = {
        "dimSession", "dimEngine", "dimStrategy", "tblEngineDaily",
        "tblBenchmarkDaily", "tblStrategyOutcome", "tblStrategyAccuracy",
        "tblRegimeAccuracy", "tblRegimeStrategyAccuracy", "tblRankingTicker",
        "tblRankingDaily", "tblPortfolioSize", "tblDataQuality",
    }
    assert set(schema["tables"]) == expected


def test_05_evidence_status_classification() -> None:
    assert kpi._evidence_status("SIMULATED_CLOCK_RECONSTRUCTION_NOT_CONFIRMATORY") == "MOCK_REHEARSAL"
    assert kpi._evidence_status("PROSPECTIVE_CONFIRMATORY") == "PROSPECTIVE_CONFIRMATORY"
    assert kpi._evidence_status("HISTORICAL_RETROSPECTIVE") == "HISTORICAL_RETROSPECTIVE"
    assert kpi._evidence_status("UNKNOWN") == "PROSPECTIVE_EXCLUDED"


def test_06_standardized_return_uses_locked_notional_and_cost() -> None:
    cost, pnl = kpi._standardize_return(0.01, 1000.0, 0.0005)
    assert cost == pytest.approx(0.5)
    assert pnl == pytest.approx(9.5)


def test_07_outcome_status_normalization() -> None:
    assert kpi._normalize_outcome_status("COMPLETE") == "COMPLETE"
    assert kpi._normalize_outcome_status("NO_COMPLETED_TRADE") == "NO_TRIGGER"
    assert kpi._normalize_outcome_status("CASH") == "ZERO_CASH"
    assert kpi._normalize_outcome_status("UNKNOWN") == "INCOMPLETE"


def test_08_safe_scalar_helpers() -> None:
    assert kpi._safe_float("1.25") == 1.25
    assert kpi._safe_float(float("nan")) is None
    assert kpi._safe_int("4") == 4
    assert kpi._bool("true") is True
    assert kpi._bool("no") is False


def test_09_sqlite_connection_is_query_only(tmp_path: Path) -> None:
    db = tmp_path / "source.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE t(x INTEGER)")
        connection.execute("INSERT INTO t VALUES (1)")
    before = kpi._sha256(db)
    with kpi._connect_ro(db) as connection:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert connection.execute("SELECT x FROM t").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO t VALUES (2)")
    assert kpi._sha256(db) == before


def test_10_best_per_ticker_keeps_highest_comparison_eligible_strategy() -> None:
    outcomes = pd.DataFrame([
        {"ticker": "AAA", "strategy_variant_id": "S1", "outcome_status": "COMPLETE", "standardized_net_pnl_sek": 2.0, "morning_available_flag": True, "governance_feasible_flag": True},
        {"ticker": "AAA", "strategy_variant_id": "S2", "outcome_status": "COMPLETE", "standardized_net_pnl_sek": 5.0, "morning_available_flag": True, "governance_feasible_flag": True},
        {"ticker": "BBB", "strategy_variant_id": "S3", "outcome_status": "COMPLETE", "standardized_net_pnl_sek": 9.0, "morning_available_flag": True, "governance_feasible_flag": True},
    ])
    dim = pd.DataFrame([
        {"strategy_variant_id": "S1", "comparison_eligible": True},
        {"strategy_variant_id": "S2", "comparison_eligible": True},
        {"strategy_variant_id": "S3", "comparison_eligible": False},
    ])
    result = kpi._best_per_ticker(outcomes, False, dim)
    assert result[["ticker", "strategy_variant_id"]].to_dict("records") == [{"ticker": "AAA", "strategy_variant_id": "S2"}]


def test_11_portfolio_selection_respects_sector_cap() -> None:
    candidates = pd.DataFrame([
        {"ticker": "AAA", "broad_sector": "IND", "standardized_net_pnl_sek": 10.0},
        {"ticker": "BBB", "broad_sector": "IND", "standardized_net_pnl_sek": 9.0},
        {"ticker": "CCC", "broad_sector": "HEALTH", "standardized_net_pnl_sek": 8.0},
    ])
    selected, status = kpi._select_portfolio(candidates, 2, True, False, 1)
    assert status == "COMPLETE"
    assert selected["ticker"].tolist() == ["AAA", "CCC"]


def test_12_up_to_portfolio_does_not_force_negative_trade() -> None:
    candidates = pd.DataFrame([
        {"ticker": "AAA", "broad_sector": "IND", "standardized_net_pnl_sek": 3.0},
        {"ticker": "BBB", "broad_sector": "HEALTH", "standardized_net_pnl_sek": -1.0},
    ])
    selected, status = kpi._select_portfolio(candidates, 2, False, True, None)
    assert status == "COMPLETE"
    assert selected["ticker"].tolist() == ["AAA"]


def test_13_fixed_portfolio_is_not_evaluable_when_too_few_candidates() -> None:
    candidates = pd.DataFrame([
        {"ticker": "AAA", "broad_sector": "IND", "standardized_net_pnl_sek": 3.0},
    ])
    selected, status = kpi._select_portfolio(candidates, 2, True, False, None)
    assert len(selected) == 1
    assert status == "NOT_EVALUABLE"


def test_14_dense_and_ordinal_ranks_handle_ties() -> None:
    frame = pd.DataFrame([
        {"ticker": "AAA", "standardized_net_pnl_sek": 5.000},
        {"ticker": "BBB", "standardized_net_pnl_sek": 4.995},
        {"ticker": "CCC", "standardized_net_pnl_sek": 1.000},
    ])
    result = kpi._dense_and_ordinal_ranks(frame, 0.01)
    assert result["actual_dense_rank"].tolist() == [1, 1, 2]
    assert result["actual_ordinal_rank"].tolist() == [1, 2, 3]


def _regime_config() -> dict:
    return kpi._read_config(CONFIG)


def test_15_realized_regime_classifier_detects_trend_down() -> None:
    feature = {
        "coverage": 1.0, "eod_label": "17:25", "median_eod_return": -0.008,
        "median_morning_return": -0.003, "advancer_share": 0.1, "decliner_share": 0.9,
        "path_persistence": 0.8, "reversal_strength": 0.0, "median_opening_gap": -0.001,
        "gap_down_share": 0.6, "median_post_morning_return": -0.005,
        "median_range": 0.01, "median_realized_volatility": 0.01, "dispersion": 0.01,
    }
    result = kpi._classify_regime(feature, [], _regime_config())
    assert result["realized_eod_regime"] == "TREND_DOWN"


def test_16_realized_regime_classifier_uses_defensive_fallback() -> None:
    feature = {
        "coverage": 1.0, "eod_label": "17:25", "median_eod_return": -0.001,
        "median_morning_return": 0.0002, "advancer_share": 0.3, "decliner_share": 0.7,
        "path_persistence": 0.4, "reversal_strength": 0.0, "median_opening_gap": 0.0,
        "gap_down_share": 0.5, "median_post_morning_return": -0.001,
        "median_range": 0.01, "median_realized_volatility": 0.01, "dispersion": 0.01,
    }
    result = kpi._classify_regime(feature, [], _regime_config())
    assert result["realized_eod_regime"] == "DEFENSIVE_MIXED"


def test_17_schema_validation_rejects_duplicate_primary_key() -> None:
    schema = {
        "tables": {
            "x": {
                "primary_key": ["id"],
                "columns": [
                    {"name": "id", "nullable": False},
                    {"name": "value", "nullable": True},
                ],
            }
        }
    }
    tables = {"x": pd.DataFrame([{"id": "A", "value": 1}, {"id": "A", "value": 2}])}
    with pytest.raises(kpi.OutputContractError):
        kpi._validate_schema(tables, schema)


def test_18_conform_columns_uses_contract_order() -> None:
    schema = {"tables": {"x": {"columns": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}}}
    frame = pd.DataFrame([{"c": 3, "a": 1}])
    result = kpi._conform_columns(frame, schema, "x")
    assert result.columns.tolist() == ["a", "b", "c"]
    assert result.iloc[0].to_dict() == {"a": 1, "b": None, "c": 3}
