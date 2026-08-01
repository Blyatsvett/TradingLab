from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.core.stage_registry import resolve_stage_output_dir
from RegimeTrading.scripts import step9u_historical_contingency_selector_v1 as step9u


STEP9T_DIR = resolve_stage_output_dir("step9t")
SESSION_FILE = STEP9T_DIR / "step9t_session_transitions.csv"
ARCHETYPE_FILE = STEP9T_DIR / "step9t_ticker_archetypes.csv"
OUTCOME_FILE = STEP9T_DIR / "step9t_ticker_outcomes.csv"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return pd.read_csv(SESSION_FILE), pd.read_csv(ARCHETYPE_FILE), pd.read_csv(OUTCOME_FILE)


def _candidate_book() -> pd.DataFrame:
    sessions, archetypes, outcomes = _sources()
    return step9u.build_candidate_book(sessions, archetypes, outcomes)


def test_config_is_shadow_only_and_freeze_pinned() -> None:
    assert step9u.CONFIG["router_active"] is False
    assert step9u.CONFIG["orders_enabled"] is False
    assert step9u.CONFIG["mandatory_control_active"] is False
    assert step9u.MAX_SELECTED_POSITIONS == 2
    assert step9u.MAX_POSITIONS_PER_SECTOR == 1
    assert step9u.FREEZE_ID == "92b274cb24cad391"
    assert step9u.ARTIFACT_SET_SHA256.startswith(step9u.FREEZE_ID)


def test_historical_freeze_verifies_ten_artifacts_and_30_checks() -> None:
    manifest = step9u.verify_historical_freeze()
    assert len(manifest["input_artifacts"]) == 10
    assert manifest["independent_audit"] == {"checks": 30, "failed": 0, "passed": 30}
    assert manifest["router_active"] is False
    assert manifest["orders_sent"] is False


def test_policy_registry_is_exact_and_nonconfirmatory() -> None:
    registry = step9u.policy_registry()
    assert set(registry["rule_id"]) == {
        "HD_MIXED_BCL_AVOID_V1",
        "LRL_AGGREGATE_PROMISING_V1",
        "VE_BCL_BACKOFF_CHALLENGER_V1",
    }
    assert registry["prospective_validation_status"].eq("NOT_YET_PROSPECTIVELY_VALIDATED").all()
    assert not registry["router_active"].any()
    assert not registry["orders_sent"].any()


def test_all_morning_complete_directional_candidates_are_preserved() -> None:
    candidates = _candidate_book()
    assert len(candidates) == 970
    assert candidates["candidate_id"].is_unique
    assert int(candidates["selection_eligible"].sum()) == 158
    assert int(candidates["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL").sum()) == 79
    assert int(candidates["policy_action"].eq("OBSERVATION_ONLY").sum()) == 733


def test_negative_high_dispersion_mixed_bullish_cell_is_blocked() -> None:
    candidates = _candidate_book()
    blocked = candidates[
        candidates["source_regime"].eq("HIGH_DISPERSION")
        & candidates["transition_state"].eq("MIXED_TRANSITION")
        & candidates["primary_archetype"].eq("BULLISH_CONTINUATION_LONG")
    ]
    assert len(blocked) == 79
    assert blocked["rule_id"].eq("HD_MIXED_BCL_AVOID_V1").all()
    assert blocked["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL").all()
    assert not blocked["selection_eligible"].any()
    assert not blocked["selected"].any()


def test_laggard_recovery_rule_and_signal_are_deterministic() -> None:
    candidates = _candidate_book()
    laggards = candidates[candidates["primary_archetype"].eq("LAGGARD_RECOVERY_LONG")]
    assert len(laggards) == 109
    assert laggards["selection_eligible"].all()
    assert laggards["rule_id"].eq("LRL_AGGREGATE_PROMISING_V1").all()
    expected = (-laggards["early_return"]).clip(lower=0) + laggards["last5_return"].clip(lower=0)
    assert (laggards["signal_strength"] - expected).abs().max() < 1e-15


def test_volatility_expansion_bullish_continuation_backoff_is_selectable() -> None:
    candidates = _candidate_book()
    challenger = candidates[candidates["rule_id"].eq("VE_BCL_BACKOFF_CHALLENGER_V1")]
    assert len(challenger) == 49
    assert challenger["source_regime"].eq("VOLATILITY_EXPANSION").all()
    assert challenger["primary_archetype"].eq("BULLISH_CONTINUATION_LONG").all()
    assert challenger["selection_eligible"].all()


def test_selection_does_not_use_eod_outcomes() -> None:
    sessions, archetypes, outcomes = _sources()
    first = step9u.build_candidate_book(sessions, archetypes, outcomes)
    changed = outcomes.copy()
    changed["net_pnl_sek"] = pd.to_numeric(changed["net_pnl_sek"], errors="coerce") * -1000.0
    changed["session_close_return"] = pd.to_numeric(changed["session_close_return"], errors="coerce") * -1000.0
    second = step9u.build_candidate_book(sessions, archetypes, changed)
    first_selected = first.loc[first["selected"], ["session_date", "ticker", "selected_rank", "rule_id"]].reset_index(drop=True)
    second_selected = second.loc[second["selected"], ["session_date", "ticker", "selected_rank", "rule_id"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(first_selected, second_selected)
    assert not first["selection_uses_outcome_fields"].any()


def test_selection_respects_two_position_and_sector_limits() -> None:
    candidates = _candidate_book()
    selected = candidates[candidates["selected"]]
    assert int(selected.groupby("session_date").size().max()) <= 2
    assert int(selected.groupby(["session_date", "broad_sector"]).size().max()) <= 1
    assert int(selected["selected"].sum()) == 73
    assert int(selected["session_date"].nunique()) == 43


def test_july28_has_no_step9u_selection() -> None:
    candidates = _candidate_book()
    july28 = candidates[candidates["session_date"].astype(str).eq("2026-07-28")]
    assert len(july28) == 22
    assert int(july28["selection_eligible"].sum()) == 0
    assert int(july28["selected"].sum()) == 0


def test_historical_selected_result_reproduces_expected_diagnostic_totals() -> None:
    result = step9u.run_historical_replay(write_outputs=False)
    summary = result["summary"]
    assert summary["selected_candidates"] == 73
    assert summary["selected_sessions"] == 43
    assert summary["selected_complete_outcomes"] == 71
    assert summary["selected_incomplete_outcomes"] == 2
    assert summary["selected_net_pnl_sek"] == pytest.approx(388.29973148050374, abs=1e-9)
    assert summary["selected_average_pnl_sek"] == pytest.approx(5.469010302542306, abs=1e-12)
    assert summary["selected_win_rate"] == pytest.approx(0.6338028169014085, abs=1e-12)
    assert summary["selected_complete_traded_sessions"] == 42
    assert summary["selected_positive_sessions"] == 31
    assert summary["selected_positive_session_rate"] == pytest.approx(0.7380952380952381, abs=1e-12)
    assert summary["selected_max_drawdown_sek"] == pytest.approx(-32.36926681004209, abs=1e-9)


def test_all_sessions_are_preserved_in_assignment_registry() -> None:
    result = step9u.run_historical_replay(write_outputs=False)
    assignments = result["assignments"]
    assert len(assignments) == 62
    assert assignments["session_date"].is_unique
    assert int(assignments["selected_count"].max()) <= 2
    assert not assignments["mandatory_control_active"].any()


def test_independent_audit_is_30_of_30() -> None:
    result = step9u.run_historical_replay(write_outputs=False)
    audit = result["audit"]
    assert len(audit) == 30
    assert audit["passed"].all()
    assert result["summary"]["audit_pass"] is True


def test_step9s_benchmark_is_context_only_not_direct_pnl_comparison() -> None:
    result = step9u.run_historical_replay(write_outputs=False)
    comparison = result["benchmark"]
    assert len(comparison) == 3
    assert not comparison["direct_pnl_comparison_allowed"].any()
    assert set(comparison["engine"]) == {
        "STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1",
        "STEP9S_HISTORICAL_CONTINGENCY_REPLAY_V1",
    }


def test_replay_is_deterministic_and_sources_remain_unchanged(tmp_path: Path) -> None:
    protected = [
        SESSION_FILE,
        ARCHETYPE_FILE,
        OUTCOME_FILE,
        step9u.STEP9T_FREEZE_MANIFEST,
        step9u.STEP9S_SUMMARY_FILE,
    ]
    before = {path: _hash(path) for path in protected}
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    step9u.run_historical_replay(output_dir=first_dir)
    step9u.run_historical_replay(output_dir=second_dir)
    first_files = sorted(path.name for path in first_dir.iterdir() if path.is_file())
    second_files = sorted(path.name for path in second_dir.iterdir() if path.is_file())
    assert first_files == second_files
    for name in first_files:
        assert _hash(first_dir / name) == _hash(second_dir / name)
    assert before == {path: _hash(path) for path in protected}


def test_selection_regret_is_nonnegative_feasible_oracle() -> None:
    result = step9u.run_historical_replay(write_outputs=False)
    regret = result["regret"]
    assert len(regret) == 62
    assert regret["selection_regret_sek"].ge(-1e-12).all()
    assert regret["oracle_positions"].between(0, 2).all()
    assert regret["oracle_contract"].eq("UP_TO_2_POSITIVE_MAX_1_PER_SECTOR_V1").all()
    assert regret["selection_regret_sek"].sum() == pytest.approx(354.76753198836883, abs=1e-9)


def test_selection_regret_oracle_obeys_sector_constraint() -> None:
    result = step9u.run_historical_replay(write_outputs=False)
    regret = result["regret"]
    candidates = result["candidates"]
    lookup = candidates.set_index(["session_date", "ticker"])["broad_sector"]
    for row in regret.itertuples(index=False):
        tickers = [ticker for ticker in str(row.oracle_tickers).split("|") if ticker]
        sectors = [lookup.loc[(str(row.session_date), ticker)] for ticker in tickers]
        assert len(tickers) <= 2
        assert len(sectors) == len(set(sectors))

def test_source_hash_export_uses_platform_neutral_project_relative_keys(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    step9u.run_historical_replay(output_dir=output_dir)
    payload = __import__("json").loads(
        (output_dir / step9u.SOURCE_HASH_EXPORT).read_text(encoding="utf-8")
    )
    assert set(payload["source_hashes"]) == {
        "config/step9u_historical_contingency_selector_v1.json",
        "data/outputs/research/step9s_historical_contingency_replay_v1/step9s_summary.csv",
        "data/step9t_regime_transition_archetype_research_v1/freeze_92b274cb24cad391/STEP9T_HISTORICAL_REPLAY_V1_FREEZE_MANIFEST.json",
        "data/outputs/research/step9t_regime_transition_archetype_research_v1/step9t_session_transitions.csv",
        "data/outputs/research/step9t_regime_transition_archetype_research_v1/step9t_ticker_archetypes.csv",
        "data/outputs/research/step9t_regime_transition_archetype_research_v1/step9t_ticker_outcomes.csv",
    }
    assert all("\\" not in key for key in payload["source_hashes"])
