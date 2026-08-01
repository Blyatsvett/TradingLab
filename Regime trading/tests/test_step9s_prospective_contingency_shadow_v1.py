from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from RegimeTrading.core.paths import legacy_output_path
from RegimeTrading.core.stage_registry import resolve_stage_path
from RegimeTrading.scripts import step9s_prospective_contingency_shadow_v1 as step9s


STOCKHOLM = ZoneInfo("Europe/Stockholm")
SOURCE_DB = resolve_stage_path("prices")
STEP9L_LEDGER = resolve_stage_path("step9l")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now(value: str) -> datetime:
    return pd.Timestamp(value).tz_convert(STOCKHOLM).to_pydatetime()


def test_registry_covers_nine_regimes_and_is_shadow_only() -> None:
    assert len(step9s.ASSIGNMENT_REGISTRY) == 9
    assert set(step9s.REGISTRY_BY_REGIME) == {
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
    assert step9s.ENTRY_WINDOW_START == "09:50"
    assert step9s.CONFIG["router_active"] is False
    assert step9s.CONFIG["orders_enabled"] is False


def test_july28_morning_assignment_is_point_in_time_and_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "step9s.db"
    protected = {path: _hash(path) for path in [SOURCE_DB, STEP9L_LEDGER]}

    assignments, plans, inserted = step9s.seal_morning_assignment(
        session_date="2026-07-28",
        now=_now("2026-07-28 09:48:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        simulated_clock=True,
        export_outputs_after=False,
    )
    assert inserted is True
    assert assignments.iloc[0]["primary_regime"] == "TREND_DOWN"
    assert assignments.iloc[0]["natural_strategy_id"] == "TREND_DOWN_MOMENTUM_CONTINUATION_V1_RESEARCH"
    assert assignments.iloc[0]["point_in_time_pass"] == 1
    assert assignments.iloc[0]["router_active"] == 0
    assert assignments.iloc[0]["order_sent"] == 0
    assert plans.iloc[0]["entry_window_start"] == "09:50"
    assert plans.iloc[0]["max_router_source_label"] <= "09:40"
    assert plans.iloc[0]["ticker"] == "SAND.ST"
    assert plans.iloc[0]["direction"] == "SHORT"

    second_assignments, second_plans, second_inserted = step9s.seal_morning_assignment(
        session_date="2026-07-28",
        now=_now("2026-07-28 10:15:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        simulated_clock=True,
        export_outputs_after=False,
    )
    assert second_inserted is False
    assert second_assignments.iloc[0]["assignment_payload_hash"] == assignments.iloc[0]["assignment_payload_hash"]
    assert second_plans.iloc[0]["plan_payload_hash"] == plans.iloc[0]["plan_payload_hash"]
    assert protected == {path: _hash(path) for path in protected}


def test_new_assignment_after_deadline_fails_without_late_flag(tmp_path: Path) -> None:
    with pytest.raises(step9s.SourceDataNotReady, match="deadline"):
        step9s.seal_morning_assignment(
            session_date="2026-07-28",
            now=_now("2026-07-28 10:00:00+02:00"),
            source_db=SOURCE_DB,
            step9l_ledger_db=STEP9L_LEDGER,
            ledger_db=tmp_path / "late.db",
            allow_late=False,
            simulated_clock=False,
            export_outputs_after=False,
        )


def test_july27_full_lifecycle_is_idempotent_and_reproduces_natural_step9l_trades(tmp_path: Path) -> None:
    ledger = tmp_path / "lifecycle.db"
    protected = {path: _hash(path) for path in [SOURCE_DB, STEP9L_LEDGER]}
    assignments, plans, morning_inserted = step9s.seal_morning_assignment(
        session_date="2026-07-27",
        now=_now("2026-07-27 09:48:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        simulated_clock=True,
        export_outputs_after=False,
    )
    assert morning_inserted is True
    morning_assignment_hash = assignments.iloc[0]["assignment_payload_hash"]
    morning_plan_hash = plans.iloc[0]["plan_payload_hash"]

    batches, natural, coverage, eod_inserted = step9s.evaluate_eod(
        session_date="2026-07-27",
        now=_now("2026-07-27 17:00:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        export_outputs_after=False,
    )
    assert eod_inserted is True
    assert int(batches.iloc[0]["natural_trade_count"]) == 2
    assert int(batches.iloc[0]["coverage_trade_count"]) == 1
    assert float(batches.iloc[0]["natural_net_pnl_sek"]) == pytest.approx(-4.663401, abs=1e-6)
    assert float(batches.iloc[0]["coverage_net_pnl_sek"]) == pytest.approx(-1.680024, abs=1e-6)
    assert len(natural) == 2
    assert len(coverage) == 1
    assert coverage.iloc[0]["entry_time"].startswith("2026-07-27 09:50:00")
    assert coverage.iloc[0]["used_candidate_rank"] == 1
    assert coverage.iloc[0]["router_active"] == 0
    assert coverage.iloc[0]["order_sent"] == 0

    batches2, natural2, coverage2, inserted2 = step9s.evaluate_eod(
        session_date="2026-07-27",
        now=_now("2026-07-27 18:00:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        export_outputs_after=False,
    )
    assert inserted2 is False
    assert batches2.iloc[0]["outcome_payload_hash"] == batches.iloc[0]["outcome_payload_hash"]
    assert sorted(natural2["row_payload_hash"]) == sorted(natural["row_payload_hash"])
    assert coverage2.iloc[0]["row_payload_hash"] == coverage.iloc[0]["row_payload_hash"]

    with sqlite3.connect(ledger) as con:
        stored_assignment = con.execute(
            "SELECT assignment_payload_hash FROM step9s_assignments WHERE session_date='2026-07-27'"
        ).fetchone()[0]
        stored_plan = con.execute(
            "SELECT plan_payload_hash FROM step9s_coverage_plans WHERE session_date='2026-07-27'"
        ).fetchone()[0]
    assert stored_assignment == morning_assignment_hash
    assert stored_plan == morning_plan_hash
    assert protected == {path: _hash(path) for path in protected}


def test_database_triggers_and_conflicting_insert_protect_immutability(tmp_path: Path) -> None:
    ledger = tmp_path / "immutable.db"
    assignments, _, _ = step9s.seal_morning_assignment(
        session_date="2026-07-28",
        now=_now("2026-07-28 09:48:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        simulated_clock=True,
        export_outputs_after=False,
    )
    with sqlite3.connect(ledger) as con:
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_STEP9S_LEDGER_UPDATE_FORBIDDEN"):
            con.execute("UPDATE step9s_assignments SET primary_regime='RECOVERY'")
        con.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_STEP9S_LEDGER_DELETE_FORBIDDEN"):
            con.execute("DELETE FROM step9s_assignments")
        con.rollback()
        conflicting = assignments.iloc[0].to_dict()
        conflicting["assignment_payload_hash"] = "conflict"
        with pytest.raises(step9s.ImmutableLedgerConflict):
            step9s._insert_immutable(
                con,
                "step9s_assignments",
                "assignment_id",
                "assignment_payload_hash",
                conflicting,
            )


def test_local_natural_evaluators_cover_all_non_step9l_regimes() -> None:
    prices = step9s._load_prices_read_only(SOURCE_DB)
    taxonomy = pd.read_csv(legacy_output_path("regime_daily_taxonomy.csv"))
    expected = {
        "RECOVERY": "2026-07-08",
        "TREND_DOWN": "2026-07-14",
        "DEFENSIVE_MIXED": "2026-06-11",
        "DATA_LIMITED_DEFENSIVE": "2026-04-30",
    }
    for regime, session_date in expected.items():
        source = taxonomy[
            taxonomy["date"].astype(str).eq(session_date)
            & taxonomy["primary_regime"].eq(regime)
        ].iloc[0].to_dict()
        assignment = {
            "session_date": session_date,
            "primary_regime": regime,
            "taxonomy_payload_json": step9s._canonical_payload(source),
        }
        trades = step9s._local_natural_trades(assignment, prices)
        assert len(trades) >= 1
        assert all(int(row["point_in_time_pass"]) == 1 for row in trades)


def test_unknown_regime_fails_loudly() -> None:
    state = pd.DataFrame([{
        "date": "2026-07-28",
        "ticker": "ALFA.ST",
        "previous_close": 100.0,
        "early_open": 99.0,
        "opening_bar_high": 100.0,
        "opening_bar_low": 98.0,
        "early_high": 100.0,
        "early_low": 98.0,
        "early_midpoint": 99.0,
        "early_range_pct": 0.02,
        "cutoff_close": 99.0,
        "cutoff_return_from_open": 0.0,
        "opening_gap": -0.01,
        "close_0935": 99.0,
        "close_0940": 99.0,
        "high_0940": 99.5,
        "low_0940": 98.5,
        "max_router_source_label": "09:40",
    }])
    with pytest.raises(ValueError, match="Unsupported single"):
        step9s._single_candidate_pool("UNKNOWN", state, {"direction_bias": "NEUTRAL"})


def test_eod_requires_a_sealed_morning_assignment(tmp_path: Path) -> None:
    ledger = tmp_path / "empty.db"
    with pytest.raises(step9s.SourceDataNotReady, match="No sealed Step 9S morning assignment"):
        step9s.evaluate_eod(
            session_date="2026-07-27",
            now=_now("2026-07-27 17:00:00+02:00"),
            source_db=SOURCE_DB,
            step9l_ledger_db=STEP9L_LEDGER,
            ledger_db=ledger,
            export_outputs_after=False,
        )
