from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from RegimeTrading.scripts import step9v_intraday_regime_transition_observer_v1 as s9v

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _insert(con: sqlite3.Connection, table: str, row: dict):
    cols = list(row)
    con.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [row[c] for c in cols],
    )


def _build_sources(tmp_path: Path, mock_status: bool = False):
    tdb = tmp_path / "t.db"
    udb = tmp_path / "u.db"
    pdb = tmp_path / "p.db"
    tickers = [f"T{i:02d}.ST" for i in range(29)]
    with sqlite3.connect(tdb) as con:
        con.execute("""CREATE TABLE step9t_prospective_batches (
          batch_id TEXT, experiment_id TEXT, session_date TEXT, prospective_status TEXT, code_version TEXT,
          historical_freeze_id TEXT, historical_freeze_artifact_sha256 TEXT,
          source_step9l_batch_id TEXT, source_step9l_batch_payload_hash TEXT, source_step9l_decision_set_hash TEXT,
          morning_price_snapshot_hash TEXT, source_regime TEXT, transition_state TEXT,
          valid_ticker_count INTEGER, incomplete_ticker_count INTEGER, advancer_share REAL, decliner_share REAL,
          median_early_return REAL, median_last5_return REAL, early_loser_count INTEGER, early_winner_count INTEGER,
          recovery_share_of_early_losers REAL, continuation_share_of_early_winners REAL,
          midpoint_reclaim_share REAL, leader_failure_share REAL, cross_sectional_dispersion REAL,
          batch_payload_hash TEXT)""")
        con.execute("""CREATE TABLE step9t_prospective_ticker_archetypes (
          ticker_row_id TEXT, batch_id TEXT, experiment_id TEXT, code_version TEXT, session_date TEXT,
          ticker TEXT, company_id TEXT, broad_sector TEXT, universe_role TEXT,
          morning_status TEXT, missing_labels TEXT, early_return REAL, last5_return REAL,
          opening_range_high REAL, opening_range_low REAL, opening_range_midpoint REAL,
          opening_range_position REAL, midpoint_reclaimed INTEGER,
          bullish_continuation_flag INTEGER, bearish_continuation_flag INTEGER,
          laggard_recovery_flag INTEGER, leader_reversal_flag INTEGER,
          primary_archetype TEXT, direction TEXT, max_source_label_used TEXT,
          point_in_time_pass INTEGER, router_active INTEGER, order_sent INTEGER, row_payload_hash TEXT)""")
        rows = []
        for i, ticker in enumerate(tickers):
            archetype = "LAGGARD_RECOVERY_LONG" if i < 2 else "NO_CLEAR_SETUP"
            direction = "LONG" if i < 2 else "NONE"
            row = {
                "ticker_row_id": f"TR-{i}", "batch_id": "TB", "experiment_id": s9v.CONFIG["source_step9t_experiment_id"],
                "code_version": s9v.CONFIG["source_step9t_code_version"], "session_date": "2026-07-29",
                "ticker": ticker, "company_id": f"C{i}", "broad_sector": f"S{i%5}", "universe_role": "HOLDOUT",
                "morning_status": "MORNING_COMPLETE", "missing_labels": "", "early_return": -0.005 if i < 2 else 0.0,
                "last5_return": 0.002 if i < 2 else 0.0, "opening_range_high": 101.0,
                "opening_range_low": 99.0, "opening_range_midpoint": 100.0, "opening_range_position": 0.5,
                "midpoint_reclaimed": int(i < 2), "bullish_continuation_flag": 0,
                "bearish_continuation_flag": 0, "laggard_recovery_flag": int(i < 2),
                "leader_reversal_flag": 0, "primary_archetype": archetype, "direction": direction,
                "max_source_label_used": "09:45", "point_in_time_pass": 1, "router_active": 0, "order_sent": 0,
            }
            row["row_payload_hash"] = s9v._payload_hash({**row, "midpoint_reclaimed": bool(row["midpoint_reclaimed"]),
                "bullish_continuation_flag": bool(row["bullish_continuation_flag"]),
                "bearish_continuation_flag": bool(row["bearish_continuation_flag"]),
                "laggard_recovery_flag": bool(row["laggard_recovery_flag"]),
                "leader_reversal_flag": bool(row["leader_reversal_flag"])})
            rows.append(row); _insert(con, "step9t_prospective_ticker_archetypes", row)
        features = {
            "valid_ticker_count": 29, "incomplete_ticker_count": 0, "advancer_share": 0.5, "decliner_share": 0.5,
            "median_early_return": 0.0, "median_last5_return": 0.0, "early_loser_count": 2, "early_winner_count": 0,
            "recovery_share_of_early_losers": 1.0, "continuation_share_of_early_winners": 0.0,
            "midpoint_reclaim_share": 0.1, "leader_failure_share": 0.0, "cross_sectional_dispersion": 0.005,
        }
        ticker_set_hash = s9v._payload_hash([r["ticker_row_id"] for r in sorted(rows, key=lambda x: x["ticker"])])
        status = "SIMULATED_POINT_IN_TIME_VERIFICATION_NOT_CONFIRMATORY" if mock_status else "PROSPECTIVE_TRANSITION_OBSERVER"
        batch = {
            "batch_id": "TB", "experiment_id": s9v.CONFIG["source_step9t_experiment_id"], "session_date": "2026-07-29",
            "prospective_status": status, "code_version": s9v.CONFIG["source_step9t_code_version"],
            "historical_freeze_id": s9v.CONFIG["source_step9t_freeze_id"], "historical_freeze_artifact_sha256": "TART",
            "source_step9l_batch_id": "L", "source_step9l_batch_payload_hash": "LH",
            "source_step9l_decision_set_hash": "LD", "morning_price_snapshot_hash": "PH",
            "source_regime": "RANGE_LOW_VOL", "transition_state": "MIXED_TRANSITION", **features,
        }
        batch_payload = {
            "batch_id": "TB", "session_date": "2026-07-29", "prospective_status": status,
            "code_version": s9v.CONFIG["source_step9t_code_version"],
            "historical_freeze_id": s9v.CONFIG["source_step9t_freeze_id"],
            "historical_freeze_artifact_sha256": "TART", "source_step9l_batch_id": "L",
            "source_step9l_batch_payload_hash": "LH", "source_step9l_decision_set_hash": "LD",
            "morning_price_snapshot_hash": "PH", "source_regime": "RANGE_LOW_VOL",
            "transition_state": "MIXED_TRANSITION", "features": features, "ticker_set_hash": ticker_set_hash,
        }
        batch["batch_payload_hash"] = s9v._payload_hash(batch_payload)
        _insert(con, "step9t_prospective_batches", batch)
    with sqlite3.connect(udb) as con:
        con.execute("""CREATE TABLE step9u_prospective_assignment_batches (
          assignment_batch_id TEXT, experiment_id TEXT, session_date TEXT, prospective_status TEXT, code_version TEXT,
          historical_freeze_id TEXT, historical_freeze_artifact_sha256 TEXT,
          source_step9t_batch_id TEXT, source_step9t_batch_payload_hash TEXT, candidate_set_hash TEXT,
          mandatory_control_active INTEGER, router_active INTEGER, order_sent INTEGER, batch_payload_hash TEXT)""")
        con.execute("""CREATE TABLE step9u_prospective_candidates (
          candidate_id TEXT, assignment_batch_id TEXT, experiment_id TEXT, code_version TEXT, session_date TEXT,
          ticker TEXT, company_id TEXT, broad_sector TEXT, universe_role TEXT, source_ticker_row_id TEXT,
          source_row_payload_hash TEXT, source_regime TEXT, transition_state TEXT, primary_archetype TEXT,
          direction TEXT, early_return REAL, last5_return REAL, policy_action TEXT, rule_id TEXT,
          rule_priority INTEGER, signal_strength REAL, selection_eligible INTEGER, blocked_reason TEXT,
          selected INTEGER, selected_rank INTEGER, selection_reason TEXT, point_in_time_pass INTEGER,
          router_active INTEGER, order_sent INTEGER, row_payload_hash TEXT)""")
        candidates = []
        for i in range(2):
            row = {
                "candidate_id": f"UC-{i}", "assignment_batch_id": "UB", "experiment_id": s9v.CONFIG["source_step9u_experiment_id"],
                "code_version": s9v.CONFIG["source_step9u_code_version"], "session_date": "2026-07-29",
                "ticker": tickers[i], "company_id": f"C{i}", "broad_sector": f"S{i}", "universe_role": "HOLDOUT",
                "source_ticker_row_id": f"TR-{i}", "source_row_payload_hash": rows[i]["row_payload_hash"],
                "source_regime": "RANGE_LOW_VOL", "transition_state": "MIXED_TRANSITION",
                "primary_archetype": "LAGGARD_RECOVERY_LONG", "direction": "LONG", "early_return": -0.005,
                "last5_return": 0.002, "policy_action": "SELECTABLE_CHALLENGER", "rule_id": "LRL_AGGREGATE_PROMISING_V1",
                "rule_priority": 200, "signal_strength": 0.007, "selection_eligible": 1, "blocked_reason": "",
                "selected": 1, "selected_rank": i + 1, "selection_reason": "SELECTED_BY_FROZEN_V1_POLICY",
                "point_in_time_pass": 1, "router_active": 0, "order_sent": 0,
            }
            row["row_payload_hash"] = s9v._payload_hash(row)
            candidates.append(row); _insert(con, "step9u_prospective_candidates", row)
        c_hash = s9v._payload_hash([r["candidate_id"] for r in sorted(candidates, key=lambda x: x["ticker"])])
        status = "SIMULATED_POINT_IN_TIME_VERIFICATION_NOT_CONFIRMATORY" if mock_status else "PROSPECTIVE_SHADOW_SELECTION"
        bp = {
            "assignment_batch_id": "UB", "session_date": "2026-07-29", "prospective_status": status,
            "code_version": s9v.CONFIG["source_step9u_code_version"], "historical_freeze_id": s9v.CONFIG["source_step9u_freeze_id"],
            "historical_freeze_artifact_sha256": "UART", "source_step9t_batch_id": "TB",
            "source_step9t_batch_payload_hash": batch["batch_payload_hash"], "candidate_set_hash": c_hash,
        }
        ub = {**bp, "experiment_id": s9v.CONFIG["source_step9u_experiment_id"],
              "mandatory_control_active": 0, "router_active": 0, "order_sent": 0,
              "batch_payload_hash": s9v._payload_hash(bp)}
        _insert(con, "step9u_prospective_assignment_batches", ub)
    labels = ["09:30", "09:45", "09:50", "10:10", "10:25", "10:30", "11:10", "11:25", "11:30",
              "13:10", "13:25", "13:30", "14:40", "14:55", "15:00", "17:20"]
    with sqlite3.connect(pdb) as con:
        con.execute("CREATE TABLE intraday_prices (datetime TEXT, open REAL, high REAL, low REAL, close REAL, ticker TEXT)")
        for i, ticker in enumerate(tickers):
            base = 100.0 + i
            for j, label in enumerate(labels):
                drift = (j * 0.12) if i < 20 else (-j * 0.10)
                if i == 0 and label >= "10:25": drift = -j * 0.16
                px = base + drift
                con.execute("INSERT INTO intraday_prices VALUES (?,?,?,?,?,?)",
                            (f"2026-07-29 {label}:00", px, px + 0.2, px - 0.2, px + 0.05, ticker))
    return tdb, udb, pdb


def test_frozen_config_is_observer_only():
    assert s9v.CONFIG["selection_active"] is False
    assert s9v.CONFIG["position_changes_enabled"] is False
    assert s9v.CONFIG["router_active"] is False
    assert s9v.CONFIG["orders_enabled"] is False


def test_checkpoint_registry():
    assert list(s9v.CHECKPOINTS) == ["10:30", "11:30", "13:30", "15:00"]
    assert s9v.CHECKPOINTS["10:30"]["source_cutoff_label"] == "10:25"


def test_archetype_classifier():
    assert s9v._current_archetype(-0.01, 0.002) == "LAGGARD_RECOVERY_LONG"
    assert s9v._current_archetype(0.01, -0.002) == "LEADER_REVERSAL_SHORT"
    assert s9v._current_archetype(0.01, 0.0) == "BULLISH_CONTINUATION_LONG"
    assert s9v._current_archetype(-0.01, 0.0) == "BEARISH_CONTINUATION_SHORT"


def test_review_action_contract():
    assert s9v._review_action("LONG", "LONG", "BULLISH")[0] == "KEEP"
    assert s9v._review_action("LONG", "NONE", "MIXED")[0] == "REDUCE"
    assert s9v._review_action("LONG", "SHORT", "BEARISH")[:2] == ("EXIT", "EXIT_AND_SWITCH_RESEARCH_ONLY")


def test_checkpoint_seals_29_rows_and_reviews(tmp_path: Path):
    t, u, p = _build_sources(tmp_path)
    ledger = tmp_path / "v.db"
    batch, rows, reviews, inserted = s9v.seal_checkpoint(
        "2026-07-29", "10:30", datetime(2026, 7, 29, 10, 31, tzinfo=STOCKHOLM), p, t, u, ledger
    )
    assert inserted and len(rows) == 29 and len(reviews) == 2
    assert int(batch.iloc[0]["position_changes_enabled"]) == 0


def test_checkpoint_idempotent(tmp_path: Path):
    t, u, p = _build_sources(tmp_path); ledger = tmp_path / "v.db"; now = datetime(2026, 7, 29, 10, 31, tzinfo=STOCKHOLM)
    s9v.seal_checkpoint("2026-07-29", "10:30", now, p, t, u, ledger)
    _, _, _, inserted = s9v.seal_checkpoint("2026-07-29", "10:30", now, p, t, u, ledger)
    assert inserted is False


def test_late_checkpoint_rejected(tmp_path: Path):
    t, u, p = _build_sources(tmp_path)
    with pytest.raises(s9v.SourceDataNotReady):
        s9v.seal_checkpoint("2026-07-29", "10:30", datetime(2026, 7, 29, 10, 40, tzinfo=STOCKHOLM), p, t, u, tmp_path / "v.db")


def test_mock_source_requires_explicit_permission(tmp_path: Path):
    t, u, p = _build_sources(tmp_path, mock_status=True)
    with pytest.raises(s9v.SourceIntegrityError):
        s9v.seal_checkpoint("2026-07-29", "10:30", datetime(2026, 7, 29, 10, 31, tzinfo=STOCKHOLM), p, t, u, tmp_path / "v.db")


def test_mock_source_allowed_and_labelled(tmp_path: Path):
    t, u, p = _build_sources(tmp_path, mock_status=True)
    batch, _, _, _ = s9v.seal_checkpoint(
        "2026-07-29", "10:30", datetime(2026, 7, 29, 10, 40, tzinfo=STOCKHOLM), p, t, u, tmp_path / "v.db",
        allow_late=True, allow_mock_source=True,
    )
    assert batch.iloc[0]["prospective_status"] == "MOCK_SOURCE_INTRADAY_OBSERVER_NOT_CONFIRMATORY"


def test_eod_counterfactuals(tmp_path: Path):
    t, u, p = _build_sources(tmp_path); ledger = tmp_path / "v.db"
    s9v.seal_checkpoint("2026-07-29", "10:30", datetime(2026, 7, 29, 10, 31, tzinfo=STOCKHOLM), p, t, u, ledger)
    ob, to, ao = s9v.evaluate_eod("2026-07-29", datetime(2026, 7, 29, 17, 40, tzinfo=STOCKHOLM), p, ledger)
    assert len(ob) == 1 and len(to) == 29 and len(ao) == 2
    assert set(ao["observer_action"]).issubset({"KEEP", "REDUCE", "EXIT"})


def test_four_checkpoint_eod(tmp_path: Path):
    t, u, p = _build_sources(tmp_path); ledger = tmp_path / "v.db"
    times = {"10:30": 10, "11:30": 11, "13:30": 13, "15:00": 15}
    for cp, hour in times.items():
        minute = 1 if cp != "15:00" else 1
        s9v.seal_checkpoint("2026-07-29", cp, datetime(2026, 7, 29, hour, int(cp.split(':')[1]) + 1, tzinfo=STOCKHOLM), p, t, u, ledger)
    ob, to, ao = s9v.evaluate_eod("2026-07-29", datetime(2026, 7, 29, 17, 40, tzinfo=STOCKHOLM), p, ledger)
    assert len(ob) == 4 and len(to) == 116 and len(ao) == 8


def test_immutable_trigger(tmp_path: Path):
    t, u, p = _build_sources(tmp_path); ledger = tmp_path / "v.db"
    s9v.seal_checkpoint("2026-07-29", "10:30", datetime(2026, 7, 29, 10, 31, tzinfo=STOCKHOLM), p, t, u, ledger)
    with sqlite3.connect(ledger) as con, pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE step9v_checkpoint_batches SET intraday_environment_state='X'")


def test_audit_clean(tmp_path: Path):
    t, u, p = _build_sources(tmp_path); ledger = tmp_path / "v.db"
    s9v.seal_checkpoint("2026-07-29", "10:30", datetime(2026, 7, 29, 10, 31, tzinfo=STOCKHOLM), p, t, u, ledger)
    audit = s9v.audit_ledger(ledger)
    assert len(audit) == 11 and audit["passed"].all()


def test_export_outputs(tmp_path: Path):
    t, u, p = _build_sources(tmp_path); ledger = tmp_path / "v.db"; out = tmp_path / "out"
    s9v.seal_checkpoint("2026-07-29", "10:30", datetime(2026, 7, 29, 10, 31, tzinfo=STOCKHOLM), p, t, u, ledger)
    s9v.export_outputs(ledger, out)
    assert (out / s9v.BATCH_EXPORT).is_file()
    assert (out / s9v.SUMMARY_EXPORT).is_file()
