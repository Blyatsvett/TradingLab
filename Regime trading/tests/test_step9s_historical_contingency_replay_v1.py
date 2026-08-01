from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.scripts import step9s_historical_contingency_replay_v1 as step9s


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_registry_covers_exactly_the_nine_recognized_regimes() -> None:
    expected = {
        "RECOVERY",
        "TREND_UP",
        "TREND_DOWN",
        "RANGE_LOW_VOL",
        "HIGH_VOL_REVERSAL",
        "HIGH_DISPERSION",
        "VOLATILITY_EXPANSION",
        "DEFENSIVE_MIXED",
        "DATA_LIMITED_DEFENSIVE",
    }
    assert set(step9s.REGISTRY_BY_REGIME) == expected
    assert len(step9s.ASSIGNMENT_REGISTRY) == 9
    assert all(not row.get("router_active", False) for row in step9s.ASSIGNMENT_REGISTRY)


def test_full_historical_replay_has_one_mandatory_trade_per_session(tmp_path: Path) -> None:
    protected = [
        step9s.PRICE_DB,
        step9s.TAXONOMY_FILE,
        step9s.BASELINE_CANDIDATE_FILE,
        step9s.BASELINE_TRADE_FILE,
    ]
    before = {path: _hash(path) for path in protected}

    result = step9s.run_replay(DATA_DIR, tmp_path)

    assert result["sessions"] == 60
    assert result["regimes"] == 9
    assert result["mandatory_coverage_trades"] == 60
    assert result["mandatory_coverage_sessions"] == 60
    assert result["complete_trade_coverage_rate"] == 1.0
    assert result["natural_trades"] == 59
    assert result["natural_sessions_with_trades"] == 38
    assert result["router_active"] is False
    assert result["orders_sent"] is False

    assignments = pd.read_csv(tmp_path / "step9s_session_assignments.csv")
    coverage = pd.read_csv(tmp_path / "step9s_mandatory_coverage_trades.csv")
    natural = pd.read_csv(tmp_path / "step9s_natural_trades.csv")
    audit = pd.read_csv(tmp_path / "step9s_audit.csv")

    assert len(assignments) == 60
    assert assignments["date"].is_unique
    assert assignments["mandatory_coverage_trade_count"].eq(1).all()
    assert assignments["complete_trade_coverage_pass"].all()
    assert len(coverage) == 60
    assert coverage.groupby("date").size().eq(1).all()
    assert coverage["trade_label"].eq(step9s.COVERAGE_TRADE_LABEL).all()
    assert coverage["point_in_time_pass"].all()
    assert coverage["execution_invariant_pass"].all()
    assert not coverage["router_active"].any()
    assert not coverage["order_sent"].any()
    assert len(natural) == 59
    assert natural["trade_label"].eq(step9s.NATURAL_TRADE_LABEL).all()
    assert audit["passed"].all()

    after = {path: _hash(path) for path in protected}
    assert before == after


def test_replay_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    step9s.run_replay(DATA_DIR, first)
    step9s.run_replay(DATA_DIR, second)

    names = [
        "step9s_assignment_registry.csv",
        "step9s_session_assignments.csv",
        "step9s_natural_trades.csv",
        "step9s_mandatory_coverage_trades.csv",
        "step9s_all_trades.csv",
        "step9s_performance.csv",
        "step9s_audit.csv",
        "step9s_source_hashes.json",
        "step9s_summary.csv",
    ]
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()
