from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from RegimeTrading.core.stage_registry import resolve_stage_output_dir
from RegimeTrading.core.stage_registry import resolve_stage_path
from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as step9t_p


STOCKHOLM = ZoneInfo("Europe/Stockholm")
SOURCE_DB = resolve_stage_path("prices")
STEP9L_LEDGER = resolve_stage_path("step9l")
HISTORICAL_DIR = resolve_stage_output_dir("step9t")


def _now(value: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(STOCKHOLM)
    else:
        timestamp = timestamp.tz_convert(STOCKHOLM)
    return timestamp.to_pydatetime()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ticker_row() -> pd.Series:
    return pd.Series(
        {
            "ticker": "TEST.ST",
            "company_id": "TEST",
            "broad_sector": "TEST",
            "universe_role": "REGIME_SOURCE",
        }
    )


def _ticker_prices(future_close: float = 101.0) -> pd.DataFrame:
    values = [
        ("09:30", 100.0, 100.5, 99.5, 100.0),
        ("09:35", 100.0, 100.5, 99.5, 100.0),
        ("09:40", 99.8, 100.0, 99.5, 99.8),
        ("09:45", 99.6, 99.8, 99.4, 99.6),
        ("09:50", 100.0, max(100.0, future_close), min(100.0, future_close), future_close),
        ("17:25", future_close, future_close, future_close, future_close),
    ]
    rows = []
    for index, (clock, open_, high, low, close) in enumerate(values, start=1):
        rows.append(
            {
                "source_rowid": index,
                "datetime": pd.Timestamp(f"2026-07-28 {clock}:00"),
                "session_date": "2026-07-28",
                "clock": clock,
                "ticker": "TEST.ST",
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
            }
        )
    return pd.DataFrame(rows)


def test_config_is_observer_only_and_freeze_pinned() -> None:
    assert step9t_p.CONFIG["router_active"] is False
    assert step9t_p.CONFIG["orders_enabled"] is False
    assert step9t_p.CONFIG["selection_active"] is False
    assert step9t_p.LATEST_MORNING_LABEL == "09:45"
    assert step9t_p.ENTRY_LABEL == "09:50"
    provenance = step9t_p._historical_freeze_provenance()
    assert provenance["freeze_id"] == "92b274cb24cad391"
    assert provenance["artifact_set_sha256"].startswith("92b274cb24cad391")


def test_future_bars_do_not_change_morning_assignment() -> None:
    first = step9t_p.classify_ticker_assignment(
        "2026-07-28", _ticker_row(), _ticker_prices(future_close=90.0)
    )
    second = step9t_p.classify_ticker_assignment(
        "2026-07-28", _ticker_row(), _ticker_prices(future_close=110.0)
    )
    comparable = [
        "morning_status",
        "early_return",
        "last5_return",
        "primary_archetype",
        "direction",
        "max_source_label_used",
        "ticker_row_id",
    ]
    assert {key: first[key] for key in comparable} == {
        key: second[key] for key in comparable
    }
    assert first["primary_archetype"] == "BEARISH_CONTINUATION_SHORT"
    assert first["max_source_label_used"] == "09:45"


def test_latest_sqlite_rowid_canonicalization_is_read_only(tmp_path: Path) -> None:
    database = tmp_path / "prices.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE intraday_prices("
            "datetime TEXT, open REAL, high REAL, low REAL, close REAL, ticker TEXT)"
        )
        connection.executemany(
            "INSERT INTO intraday_prices VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("2026-07-28 09:30:00", 100, 101, 99, 100, "TEST.ST"),
                ("2026-07-28 09:30:00.000000", 100, 102, 98, 101, "TEST.ST"),
            ],
        )
        connection.commit()
    before = _hash(database)
    prices, provenance = step9t_p._load_prices_canonical(database, "2026-07-28")
    assert len(prices) == 1
    assert prices.iloc[0]["close"] == 101
    assert int(prices.iloc[0]["source_rowid"]) == 2
    assert provenance["duplicate_minute_count"] == 1
    assert provenance["conflicting_minute_count"] == 1
    assert _hash(database) == before


def test_july28_morning_snapshot_is_29_rows_and_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "prospective.db"
    protected = {path: _hash(path) for path in [SOURCE_DB, STEP9L_LEDGER]}
    batches, rows, inserted = step9t_p.seal_morning_snapshot(
        session_date="2026-07-28",
        now=_now("2026-07-28 09:48:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        allow_late=True,
        simulated_clock=True,
        export_outputs_after=False,
    )
    assert inserted is True
    batch = batches.iloc[0]
    assert batch["source_regime"] == "TREND_DOWN"
    assert batch["transition_state"] == "WEAKNESS_PERSISTING"
    assert int(batch["valid_ticker_count"]) == 28
    assert len(rows) == 29
    assert rows["max_source_label_used"].fillna("").le("09:45").all()
    sand = rows[rows["ticker"].eq("SAND.ST")].iloc[0]
    assert sand["primary_archetype"] == "BEARISH_CONTINUATION_SHORT"

    second_batches, second_rows, second_inserted = step9t_p.seal_morning_snapshot(
        session_date="2026-07-28",
        now=_now("2026-07-28 10:15:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        allow_late=True,
        simulated_clock=True,
        export_outputs_after=False,
    )
    assert second_inserted is False
    assert second_batches.iloc[0]["batch_payload_hash"] == batch["batch_payload_hash"]
    assert sorted(second_rows["ticker_row_id"]) == sorted(rows["ticker_row_id"])
    assert protected == {path: _hash(path) for path in protected}



def test_new_snapshot_before_decision_time_fails(tmp_path: Path) -> None:
    with pytest.raises(step9t_p.SourceDataNotReady, match="not allowed before"):
        step9t_p.seal_morning_snapshot(
            session_date="2026-07-28",
            now=_now("2026-07-28 09:47:00+02:00"),
            source_db=SOURCE_DB,
            step9l_ledger_db=STEP9L_LEDGER,
            ledger_db=tmp_path / "early.db",
            allow_late=False,
            simulated_clock=False,
            export_outputs_after=False,
        )

def test_new_snapshot_after_deadline_fails(tmp_path: Path) -> None:
    with pytest.raises(step9t_p.SourceDataNotReady, match="deadline"):
        step9t_p.seal_morning_snapshot(
            session_date="2026-07-28",
            now=_now("2026-07-28 10:00:00+02:00"),
            source_db=SOURCE_DB,
            step9l_ledger_db=STEP9L_LEDGER,
            ledger_db=tmp_path / "late.db",
            allow_late=False,
            simulated_clock=False,
            export_outputs_after=False,
        )


def test_july28_eod_preserves_all_tickers_and_matches_frozen_directional_pnl(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "lifecycle.db"
    step9t_p.seal_morning_snapshot(
        session_date="2026-07-28",
        now=_now("2026-07-28 09:48:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        allow_late=True,
        simulated_clock=True,
        export_outputs_after=False,
    )
    batches, outcomes, inserted = step9t_p.evaluate_eod(
        session_date="2026-07-28",
        now=_now("2026-07-28 18:00:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        allow_early=True,
        export_outputs_after=False,
    )
    assert inserted is True
    assert len(outcomes) == 29
    batch = batches.iloc[0]
    assert int(batch["directional_outcomes"]) == 22
    assert int(batch["zero_outcomes"]) == 6
    assert int(batch["incomplete_outcomes"]) == 1
    assert float(batch["net_standardized_directional_pnl_sek"]) == pytest.approx(
        -67.719900026773, abs=1e-9
    )

    frozen = pd.read_csv(HISTORICAL_DIR / "step9t_ticker_outcomes.csv")
    frozen = frozen[frozen["session_date"].astype(str).eq("2026-07-28")]
    merged = outcomes.merge(frozen, on="ticker", suffixes=("_prospective", "_frozen"))
    assert len(merged) == 29
    assert (
        merged["primary_archetype_prospective"]
        == merged["primary_archetype_frozen"]
    ).all()
    assert (merged["direction_prospective"] == merged["direction_frozen"]).all()
    assert (merged["outcome_status_prospective"] == merged["outcome_status_frozen"]).all()
    assert np.nanmax(
        np.abs(merged["net_pnl_sek_prospective"] - merged["net_pnl_sek_frozen"])
    ) < 1e-9

    second_batches, second_outcomes, second_inserted = step9t_p.evaluate_eod(
        session_date="2026-07-28",
        now=_now("2026-07-28 19:00:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        allow_early=True,
        export_outputs_after=False,
    )
    assert second_inserted is False
    assert second_batches.iloc[0]["outcome_payload_hash"] == batch["outcome_payload_hash"]
    assert sorted(second_outcomes["outcome_id"]) == sorted(outcomes["outcome_id"])


def test_eod_requires_sealed_morning_snapshot(tmp_path: Path) -> None:
    with pytest.raises(step9t_p.SourceDataNotReady, match="No complete sealed"):
        step9t_p.evaluate_eod(
            session_date="2026-07-28",
            now=_now("2026-07-28 18:00:00+02:00"),
            source_db=SOURCE_DB,
            step9l_ledger_db=STEP9L_LEDGER,
            ledger_db=tmp_path / "empty.db",
            allow_early=True,
            export_outputs_after=False,
        )


def test_database_triggers_and_conflicting_insert_protect_immutability(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "immutable.db"
    batches, _, _ = step9t_p.seal_morning_snapshot(
        session_date="2026-07-28",
        now=_now("2026-07-28 09:48:00+02:00"),
        source_db=SOURCE_DB,
        step9l_ledger_db=STEP9L_LEDGER,
        ledger_db=ledger,
        allow_late=True,
        simulated_clock=True,
        export_outputs_after=False,
    )
    with closing(sqlite3.connect(ledger)) as connection:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="IMMUTABLE_STEP9T_PROSPECTIVE_UPDATE_FORBIDDEN",
        ):
            connection.execute(
                "UPDATE step9t_prospective_batches SET source_regime='RECOVERY'"
            )
        connection.rollback()
        with pytest.raises(
            sqlite3.IntegrityError,
            match="IMMUTABLE_STEP9T_PROSPECTIVE_DELETE_FORBIDDEN",
        ):
            connection.execute("DELETE FROM step9t_prospective_batches")
        connection.rollback()
        conflicting = batches.iloc[0].to_dict()
        conflicting["batch_payload_hash"] = "conflict"
        with pytest.raises(step9t_p.ImmutableLedgerConflict):
            step9t_p._insert_immutable(
                connection,
                "step9t_prospective_batches",
                "batch_id",
                "batch_payload_hash",
                conflicting,
            )


def test_audit_and_exports_pass_on_complete_lifecycle(tmp_path: Path) -> None:
    ledger = tmp_path / "audit.db"
    output = tmp_path / "exports"
    step9t_p.seal_morning_snapshot(
        session_date="2026-07-28",
        now=_now("2026-07-28 09:48:00+02:00"),
        ledger_db=ledger,
        allow_late=True,
        simulated_clock=True,
        export_outputs_after=False,
    )
    step9t_p.evaluate_eod(
        session_date="2026-07-28",
        now=_now("2026-07-28 18:00:00+02:00"),
        ledger_db=ledger,
        allow_early=True,
        export_outputs_after=False,
    )
    audit = step9t_p.audit_ledger(ledger)
    assert audit["passed"].all()
    step9t_p.export_outputs(ledger, output)
    expected = {
        step9t_p.BATCH_EXPORT,
        step9t_p.ARCHETYPE_EXPORT,
        step9t_p.OUTCOME_BATCH_EXPORT,
        step9t_p.OUTCOME_EXPORT,
        step9t_p.SUMMARY_EXPORT,
        step9t_p.AUDIT_EXPORT,
    }
    assert expected == {path.name for path in output.iterdir()}


def test_sqlite_handles_close_on_windows(tmp_path: Path) -> None:
    ledger = tmp_path / "windows.db"
    step9t_p.seal_morning_snapshot(
        session_date="2026-07-28",
        now=_now("2026-07-28 09:48:00+02:00"),
        ledger_db=ledger,
        allow_late=True,
        simulated_clock=True,
        export_outputs_after=False,
    )
    with closing(sqlite3.connect(ledger)) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM step9t_prospective_batches").fetchone()[0]
            == 1
        )
    ledger.unlink()
    assert not ledger.exists()
