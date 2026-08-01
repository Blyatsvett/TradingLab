from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date as date_type, datetime, time
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from RegimeTrading.core.paths import DATA_DIR, FREEZE_DIRS
from RegimeTrading.core.stage_registry import resolve_stage_output_dir


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "step9u_prospective_contingency_selector_v1.json"
DEFAULT_STEP9T_LEDGER_DB = DATA_DIR / "step9t_regime_transition_archetype_prospective_v1.db"
DEFAULT_LEDGER_DB = DATA_DIR / "step9u_contingency_selector_prospective_shadow_v1.db"
DEFAULT_EXPORT_DIR = resolve_stage_output_dir("step9u")
HISTORICAL_ROOT = DATA_DIR / "step9u_historical_contingency_selector_v1"
DEFAULT_FREEZE_ROOT = FREEZE_DIRS["step9u"]
DEFAULT_FREEZE_MANIFEST = DEFAULT_FREEZE_ROOT / "STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1_FREEZE_MANIFEST.json"
HISTORICAL_CONFIG = PROJECT_ROOT / "config" / "step9u_historical_contingency_selector_v1.json"
STOCKHOLM = ZoneInfo("Europe/Stockholm")

BATCH_EXPORT = "step9u_prospective_assignment_batches.csv"
CANDIDATE_EXPORT = "step9u_prospective_all_candidates.csv"
OUTCOME_BATCH_EXPORT = "step9u_prospective_outcome_batches.csv"
OUTCOME_EXPORT = "step9u_prospective_candidate_outcomes.csv"
SELECTED_EXPORT = "step9u_prospective_selected_outcomes.csv"
SUMMARY_EXPORT = "step9u_prospective_summary.csv"
AUDIT_EXPORT = "step9u_prospective_audit.csv"


class Step9UProspectiveError(RuntimeError):
    pass


class SourceIntegrityError(Step9UProspectiveError):
    pass


class SourceDataNotReady(Step9UProspectiveError):
    pass


class ImmutableLedgerConflict(Step9UProspectiveError):
    pass


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _clean_scalar(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_clean_scalar(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date_type)):
        if isinstance(value, date_type) and not isinstance(value, datetime):
            return value.isoformat()
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if pd.isna(value) else float(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _canonical_payload(payload: Any) -> str:
    return json.dumps(_clean_scalar(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    if bool(config.get("router_active")) or bool(config.get("orders_enabled")):
        raise SourceIntegrityError("Step 9U prospective routing and orders must remain disabled.")
    if not bool(config.get("selection_active")):
        raise SourceIntegrityError("Step 9U prospective V1 must preserve its frozen shadow selection contract.")
    if bool(config.get("mandatory_control_active")):
        raise SourceIntegrityError("Step 9U has no mandatory control book; Step 9S remains the benchmark.")
    if int(config.get("max_selected_positions", 0)) != 2:
        raise SourceIntegrityError("Step 9U must select at most two shadow positions.")
    if int(config.get("max_positions_per_sector", 0)) != 1:
        raise SourceIntegrityError("Step 9U must enforce one selected position per broad sector.")
    expected = {"HD_MIXED_BCL_AVOID_V1", "LRL_AGGREGATE_PROMISING_V1", "VE_BCL_BACKOFF_CHALLENGER_V1"}
    if {str(row.get("rule_id")) for row in config.get("rules", [])} != expected:
        raise SourceIntegrityError("Unexpected Step 9U prospective rule registry.")
    return config


CONFIG = _load_config()
EXPERIMENT_ID = str(CONFIG["experiment_id"])
RESEARCH_STATUS = str(CONFIG["research_status"])
CODE_VERSION = str(CONFIG["code_version"])
DECISION_TIME = str(CONFIG["decision_time"])
ASSIGNMENT_DEADLINE = str(CONFIG["assignment_deadline"])
ENTRY_LABEL = str(CONFIG["standardized_entry_label"])
EOD_TIME = str(CONFIG["eod_time"])
MAX_SELECTED_POSITIONS = int(CONFIG["max_selected_positions"])
MAX_POSITIONS_PER_SECTOR = int(CONFIG["max_positions_per_sector"])


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _parse_stockholm_datetime(value: str | None) -> datetime:
    if value:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            return timestamp.tz_localize(STOCKHOLM).to_pydatetime()
        return timestamp.tz_convert(STOCKHOLM).to_pydatetime()
    return datetime.now(STOCKHOLM)


def _target_date(value: str | None, now: datetime) -> str:
    target = value or now.date().isoformat()
    pd.Timestamp(target)
    return target


def _clock_to_time(value: str) -> time:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


def _historical_freeze_provenance(
    manifest_path: Path = DEFAULT_FREEZE_MANIFEST,
) -> dict[str, str]:
    if not manifest_path.is_file():
        raise SourceDataNotReady(f"Step 9U historical freeze manifest is missing: {manifest_path}")
    manifest_hash = _sha256(manifest_path)
    if manifest_hash != str(CONFIG["historical_freeze_manifest_sha256"]):
        raise SourceIntegrityError("Step 9U historical freeze manifest hash is invalid.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if str(manifest.get("freeze_id")) != str(CONFIG["historical_freeze_id"]):
        raise SourceIntegrityError("Unexpected Step 9U historical freeze ID.")
    if str(manifest.get("artifact_set_sha256")) != str(CONFIG["historical_freeze_artifact_sha256"]):
        raise SourceIntegrityError("Unexpected Step 9U historical artifact-set hash.")
    audit = dict(manifest.get("independent_audit", {}))
    if int(audit.get("passed", -1)) != 61 or int(audit.get("failed", -1)) != 0:
        raise SourceIntegrityError("Step 9U historical freeze audit is not 61/61.")
    if bool(manifest.get("router_active")) or bool(manifest.get("orders_sent")):
        raise SourceIntegrityError("Step 9U historical freeze contains an unsafe state.")
    if _sha256(HISTORICAL_CONFIG) != str(CONFIG["historical_config_sha256"]):
        raise SourceIntegrityError("Frozen Step 9U historical policy configuration changed.")
    return {
        "freeze_id": str(manifest["freeze_id"]),
        "artifact_set_sha256": str(manifest["artifact_set_sha256"]),
        "manifest_sha256": manifest_hash,
    }


def _verify_row_payload(row: dict[str, Any], hash_column: str = "row_payload_hash") -> None:
    expected = str(row[hash_column])
    payload = {key: value for key, value in row.items() if key != hash_column}
    # SQLite stores Python booleans as 0/1. Restore the source payload types
    # before verifying the immutable hash created by Step 9T.
    for field in [
        "midpoint_reclaimed",
        "bullish_continuation_flag",
        "bearish_continuation_flag",
        "laggard_recovery_flag",
        "leader_reversal_flag",
    ]:
        if field in payload:
            payload[field] = bool(payload[field])
    if _payload_hash(payload) != expected:
        raise SourceIntegrityError("A sealed Step 9T prospective row payload hash is invalid.")


def _verify_step9t_morning_batch(batch: dict[str, Any], archetypes: list[dict[str, Any]]) -> None:
    for row in archetypes:
        _verify_row_payload(row)
    features = {
        key: batch[key]
        for key in [
            "valid_ticker_count", "incomplete_ticker_count", "advancer_share", "decliner_share",
            "median_early_return", "median_last5_return", "early_loser_count", "early_winner_count",
            "recovery_share_of_early_losers", "continuation_share_of_early_winners",
            "midpoint_reclaim_share", "leader_failure_share", "cross_sectional_dispersion",
        ]
    }
    ticker_set_hash = _payload_hash([row["ticker_row_id"] for row in sorted(archetypes, key=lambda item: item["ticker"])])
    payload = {
        "batch_id": batch["batch_id"],
        "session_date": batch["session_date"],
        "prospective_status": batch["prospective_status"],
        "code_version": batch["code_version"],
        "historical_freeze_id": batch["historical_freeze_id"],
        "historical_freeze_artifact_sha256": batch["historical_freeze_artifact_sha256"],
        "source_step9l_batch_id": batch["source_step9l_batch_id"],
        "source_step9l_batch_payload_hash": batch["source_step9l_batch_payload_hash"],
        "source_step9l_decision_set_hash": batch["source_step9l_decision_set_hash"],
        "morning_price_snapshot_hash": batch["morning_price_snapshot_hash"],
        "source_regime": batch["source_regime"],
        "transition_state": batch["transition_state"],
        "features": features,
        "ticker_set_hash": ticker_set_hash,
    }
    if _payload_hash(payload) != str(batch["batch_payload_hash"]):
        raise SourceIntegrityError("The sealed Step 9T prospective morning batch hash is invalid.")


def _read_step9t_morning(session_date: str, ledger_db: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with closing(_readonly_connection(ledger_db)) as connection:
        connection.row_factory = sqlite3.Row
        batches = connection.execute(
            "SELECT * FROM step9t_prospective_batches WHERE session_date = ?", (session_date,)
        ).fetchall()
        if len(batches) != 1:
            raise SourceDataNotReady(
                f"Expected one sealed Step 9T prospective morning batch for {session_date}; found {len(batches)}."
            )
        batch = dict(batches[0])
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM step9t_prospective_ticker_archetypes WHERE batch_id = ? ORDER BY ticker",
            (batch["batch_id"],),
        ).fetchall()]
    if str(batch["experiment_id"]) != str(CONFIG["source_step9t_experiment_id"]):
        raise SourceIntegrityError("Unexpected Step 9T prospective experiment.")
    if str(batch["code_version"]) != str(CONFIG["source_step9t_code_version"]):
        raise SourceIntegrityError("Unexpected Step 9T prospective code version.")
    if len(rows) != 29:
        raise SourceDataNotReady(f"Expected 29 sealed Step 9T ticker rows; found {len(rows)}.")
    _verify_step9t_morning_batch(batch, rows)
    return batch, rows


def _verify_step9t_outcome_batch(batch: dict[str, Any], outcomes: list[dict[str, Any]]) -> None:
    for row in outcomes:
        _verify_row_payload(row)
    outcome_set_hash = _payload_hash([row["outcome_id"] for row in sorted(outcomes, key=lambda item: item["ticker"])])
    payload = {
        "outcome_batch_id": batch["outcome_batch_id"],
        "morning_batch_id": batch["morning_batch_id"],
        "session_date": batch["session_date"],
        "code_version": batch["code_version"],
        "eod_price_snapshot_hash": batch["eod_price_snapshot_hash"],
        "outcome_set_hash": outcome_set_hash,
        "directional_outcomes": int(batch["directional_outcomes"]),
        "zero_outcomes": int(batch["zero_outcomes"]),
        "incomplete_outcomes": int(batch["incomplete_outcomes"]),
        "net_standardized_directional_pnl_sek": float(batch["net_standardized_directional_pnl_sek"]),
    }
    if _payload_hash(payload) != str(batch["outcome_payload_hash"]):
        raise SourceIntegrityError("The sealed Step 9T prospective EOD batch hash is invalid.")


def _read_step9t_outcomes(session_date: str, ledger_db: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with closing(_readonly_connection(ledger_db)) as connection:
        connection.row_factory = sqlite3.Row
        batches = connection.execute(
            "SELECT * FROM step9t_prospective_outcome_batches WHERE session_date = ?", (session_date,)
        ).fetchall()
        if len(batches) != 1:
            raise SourceDataNotReady(
                f"Expected one sealed Step 9T prospective EOD batch for {session_date}; found {len(batches)}."
            )
        batch = dict(batches[0])
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM step9t_prospective_ticker_outcomes WHERE outcome_batch_id = ? ORDER BY ticker",
            (batch["outcome_batch_id"],),
        ).fetchall()]
    if len(rows) != 29:
        raise SourceDataNotReady(f"Expected 29 sealed Step 9T outcome rows; found {len(rows)}.")
    _verify_step9t_outcome_batch(batch, rows)
    return batch, rows


def _policy_decision(row: dict[str, Any]) -> dict[str, Any]:
    regime = str(row["source_regime"])
    transition = str(row["transition_state"])
    archetype = str(row["primary_archetype"])
    if regime == "HIGH_DISPERSION" and transition == "MIXED_TRANSITION" and archetype == "BULLISH_CONTINUATION_LONG":
        return {
            "policy_action": "BLOCKED_NEGATIVE_CONTROL", "rule_id": "HD_MIXED_BCL_AVOID_V1",
            "rule_priority": 1000, "signal_strength": None, "selection_eligible": 0,
            "blocked_reason": "FROZEN_NEGATIVE_EXPLORATORY_CELL",
        }
    early = float(row["early_return"])
    last5 = float(row["last5_return"])
    if archetype == "LAGGARD_RECOVERY_LONG":
        return {
            "policy_action": "SELECTABLE_CHALLENGER", "rule_id": "LRL_AGGREGATE_PROMISING_V1",
            "rule_priority": 200, "signal_strength": max(-early, 0.0) + max(last5, 0.0),
            "selection_eligible": 1, "blocked_reason": "",
        }
    if regime == "VOLATILITY_EXPANSION" and archetype == "BULLISH_CONTINUATION_LONG":
        return {
            "policy_action": "SELECTABLE_CHALLENGER", "rule_id": "VE_BCL_BACKOFF_CHALLENGER_V1",
            "rule_priority": 100, "signal_strength": max(early, 0.0) + max(last5, 0.0),
            "selection_eligible": 1, "blocked_reason": "",
        }
    return {
        "policy_action": "OBSERVATION_ONLY", "rule_id": "NO_SELECT_RULE_V1",
        "rule_priority": 0, "signal_strength": None, "selection_eligible": 0,
        "blocked_reason": "NO_FROZEN_POSITIVE_CHALLENGER_RULE",
    }


def build_candidate_assignments(batch: dict[str, Any], archetypes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in archetypes:
        if str(source["morning_status"]) != "MORNING_COMPLETE" or str(source["direction"]) == "NONE":
            continue
        base = {
            "session_date": str(source["session_date"]), "ticker": str(source["ticker"]),
            "company_id": str(source["company_id"]), "broad_sector": str(source["broad_sector"]),
            "universe_role": str(source["universe_role"]), "source_ticker_row_id": str(source["ticker_row_id"]),
            "source_row_payload_hash": str(source["row_payload_hash"]), "source_regime": str(batch["source_regime"]),
            "transition_state": str(batch["transition_state"]), "primary_archetype": str(source["primary_archetype"]),
            "direction": str(source["direction"]), "early_return": float(source["early_return"]),
            "last5_return": float(source["last5_return"]), "point_in_time_pass": int(source["point_in_time_pass"]),
        }
        base.update(_policy_decision(base))
        base.update({"selected": 0, "selected_rank": None, "selection_reason": "NOT_SELECTED"})
        candidates.append(base)
    eligible = sorted(
        [row for row in candidates if int(row["selection_eligible"]) == 1],
        key=lambda row: (-int(row["rule_priority"]), -float(row["signal_strength"]), str(row["ticker"])),
    )
    selected: list[dict[str, Any]] = []
    sectors: set[str] = set()
    for row in eligible:
        if str(row["broad_sector"]) in sectors:
            row["selection_reason"] = "SKIPPED_SECTOR_LIMIT"
            continue
        if len(selected) >= MAX_SELECTED_POSITIONS:
            row["selection_reason"] = "NOT_SELECTED_POSITION_LIMIT"
            continue
        selected.append(row)
        sectors.add(str(row["broad_sector"]))
    for rank, row in enumerate(selected, start=1):
        row["selected"] = 1
        row["selected_rank"] = rank
        row["selection_reason"] = "SELECTED_BY_FROZEN_V1_POLICY"
    for row in candidates:
        if row["selection_reason"] == "NOT_SELECTED":
            row["selection_reason"] = (
                "NOT_SELECTED_OBSERVATION_ONLY" if row["policy_action"] == "OBSERVATION_ONLY"
                else "NOT_SELECTED_BLOCKED_NEGATIVE_CONTROL"
            )
        identity = {
            "experiment_id": EXPERIMENT_ID, "session_date": row["session_date"], "ticker": row["ticker"],
            "source_ticker_row_id": row["source_ticker_row_id"], "policy_action": row["policy_action"],
            "rule_id": row["rule_id"], "selected": bool(row["selected"]), "selected_rank": row["selected_rank"],
        }
        row["candidate_id"] = _payload_hash(identity)
    return sorted(candidates, key=lambda row: (row["selected_rank"] is None, row["selected_rank"] or 999, row["ticker"]))


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS step9u_prospective_assignment_batches (
            assignment_batch_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            session_date TEXT NOT NULL UNIQUE,
            created_at_stockholm TEXT NOT NULL,
            run_mode TEXT NOT NULL,
            prospective_status TEXT NOT NULL,
            decision_time TEXT NOT NULL,
            assignment_deadline TEXT NOT NULL,
            standardized_entry_label TEXT NOT NULL,
            code_version TEXT NOT NULL,
            historical_freeze_id TEXT NOT NULL,
            historical_freeze_artifact_sha256 TEXT NOT NULL,
            historical_freeze_manifest_sha256 TEXT NOT NULL,
            source_step9t_ledger_db TEXT NOT NULL,
            source_step9t_batch_id TEXT NOT NULL UNIQUE,
            source_step9t_batch_payload_hash TEXT NOT NULL,
            source_regime TEXT NOT NULL,
            transition_state TEXT NOT NULL,
            directional_candidate_rows INTEGER NOT NULL,
            selectable_candidate_rows INTEGER NOT NULL,
            blocked_negative_control_rows INTEGER NOT NULL,
            observation_only_rows INTEGER NOT NULL,
            selected_count INTEGER NOT NULL,
            selected_tickers TEXT NOT NULL,
            selected_rule_ids TEXT NOT NULL,
            no_selection_reason TEXT NOT NULL,
            max_selected_positions INTEGER NOT NULL,
            max_positions_per_sector INTEGER NOT NULL,
            candidate_set_hash TEXT NOT NULL,
            point_in_time_pass INTEGER NOT NULL,
            mandatory_control_active INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            batch_payload_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS step9u_prospective_candidates (
            candidate_id TEXT PRIMARY KEY,
            assignment_batch_id TEXT NOT NULL,
            experiment_id TEXT NOT NULL,
            code_version TEXT NOT NULL,
            session_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            company_id TEXT NOT NULL,
            broad_sector TEXT NOT NULL,
            universe_role TEXT NOT NULL,
            source_ticker_row_id TEXT NOT NULL UNIQUE,
            source_row_payload_hash TEXT NOT NULL,
            source_regime TEXT NOT NULL,
            transition_state TEXT NOT NULL,
            primary_archetype TEXT NOT NULL,
            direction TEXT NOT NULL,
            early_return REAL NOT NULL,
            last5_return REAL NOT NULL,
            policy_action TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            rule_priority INTEGER NOT NULL,
            signal_strength REAL,
            selection_eligible INTEGER NOT NULL,
            blocked_reason TEXT NOT NULL,
            selected INTEGER NOT NULL,
            selected_rank INTEGER,
            selection_reason TEXT NOT NULL,
            point_in_time_pass INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            row_payload_hash TEXT NOT NULL,
            UNIQUE(session_date, ticker),
            FOREIGN KEY(assignment_batch_id) REFERENCES step9u_prospective_assignment_batches(assignment_batch_id)
        );
        CREATE TABLE IF NOT EXISTS step9u_prospective_outcome_batches (
            outcome_batch_id TEXT PRIMARY KEY,
            assignment_batch_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL UNIQUE,
            created_at_stockholm TEXT NOT NULL,
            code_version TEXT NOT NULL,
            source_step9t_outcome_batch_id TEXT NOT NULL UNIQUE,
            source_step9t_outcome_payload_hash TEXT NOT NULL,
            all_candidate_outcomes INTEGER NOT NULL,
            complete_candidate_outcomes INTEGER NOT NULL,
            incomplete_candidate_outcomes INTEGER NOT NULL,
            selected_outcomes INTEGER NOT NULL,
            selected_complete_outcomes INTEGER NOT NULL,
            selected_incomplete_outcomes INTEGER NOT NULL,
            all_candidate_net_pnl_sek REAL NOT NULL,
            selected_net_pnl_sek REAL NOT NULL,
            outcome_set_hash TEXT NOT NULL,
            mandatory_control_active INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            outcome_payload_hash TEXT NOT NULL,
            FOREIGN KEY(assignment_batch_id) REFERENCES step9u_prospective_assignment_batches(assignment_batch_id)
        );
        CREATE TABLE IF NOT EXISTS step9u_prospective_candidate_outcomes (
            step9u_outcome_id TEXT PRIMARY KEY,
            outcome_batch_id TEXT NOT NULL,
            assignment_batch_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            source_step9t_outcome_id TEXT NOT NULL UNIQUE,
            source_step9t_outcome_status TEXT NOT NULL,
            primary_archetype TEXT NOT NULL,
            direction TEXT NOT NULL,
            policy_action TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            selected INTEGER NOT NULL,
            selected_rank INTEGER,
            outcome_status TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            entry_price REAL,
            exit_time TEXT NOT NULL,
            exit_price REAL,
            session_close_return REAL,
            mfe_return REAL,
            mae_return REAL,
            gross_pnl_sek REAL,
            cost_sek REAL,
            net_pnl_sek REAL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            row_payload_hash TEXT NOT NULL,
            UNIQUE(session_date, ticker),
            FOREIGN KEY(outcome_batch_id) REFERENCES step9u_prospective_outcome_batches(outcome_batch_id),
            FOREIGN KEY(assignment_batch_id) REFERENCES step9u_prospective_assignment_batches(assignment_batch_id),
            FOREIGN KEY(candidate_id) REFERENCES step9u_prospective_candidates(candidate_id)
        );
        """
    )
    for table in [
        "step9u_prospective_assignment_batches", "step9u_prospective_candidates",
        "step9u_prospective_outcome_batches", "step9u_prospective_candidate_outcomes",
    ]:
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_STEP9U_PROSPECTIVE_UPDATE_FORBIDDEN'); END"
        )
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_STEP9U_PROSPECTIVE_DELETE_FORBIDDEN'); END"
        )


def _insert_immutable(
    connection: sqlite3.Connection, table: str, key_column: str, hash_column: str, row: dict[str, Any]
) -> bool:
    existing = connection.execute(
        f"SELECT {hash_column} FROM {table} WHERE {key_column} = ?", (row[key_column],)
    ).fetchone()
    if existing:
        if str(existing[0]) != str(row[hash_column]):
            raise ImmutableLedgerConflict(f"Conflicting immutable Step 9U row for {table}.{key_column}={row[key_column]}")
        return False
    columns = list(row)
    connection.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        [_clean_scalar(row[column]) for column in columns],
    )
    return True


def _read_existing_assignment(ledger_db: Path, session_date: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not ledger_db.exists():
        return None, []
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        connection.row_factory = sqlite3.Row
        batch = connection.execute(
            "SELECT * FROM step9u_prospective_assignment_batches WHERE session_date = ?", (session_date,)
        ).fetchone()
        if not batch:
            return None, []
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM step9u_prospective_candidates WHERE assignment_batch_id = ? ORDER BY ticker",
            (batch["assignment_batch_id"],),
        ).fetchall()]
    return dict(batch), rows


def _prospective_status(source_status: str, session_date: str, now: datetime, allow_late: bool, simulated_clock: bool) -> str:
    if simulated_clock:
        return "SIMULATED_POINT_IN_TIME_VERIFICATION_NOT_CONFIRMATORY"
    if allow_late or session_date != now.date().isoformat():
        return "LATE_RECONSTRUCTION_NOT_CONFIRMATORY"
    if "NOT_CONFIRMATORY" in str(source_status):
        return "SOURCE_STEP9T_NOT_CONFIRMATORY"
    return "PROSPECTIVE_SHADOW_SELECTION"


def seal_morning_selection(
    session_date: str,
    now: datetime,
    step9t_ledger_db: Path = DEFAULT_STEP9T_LEDGER_DB,
    ledger_db: Path = DEFAULT_LEDGER_DB,
    allow_late: bool = False,
    simulated_clock: bool = False,
    export_outputs_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    freeze = _historical_freeze_provenance()
    source_batch, source_archetypes = _read_step9t_morning(session_date, step9t_ledger_db)
    candidates = build_candidate_assignments(source_batch, source_archetypes)
    candidate_set_hash = _payload_hash([row["candidate_id"] for row in sorted(candidates, key=lambda item: item["ticker"])])
    existing_batch, existing_candidates = _read_existing_assignment(ledger_db, session_date)
    if existing_batch:
        comparisons = {
            "historical_freeze_id": freeze["freeze_id"],
            "historical_freeze_artifact_sha256": freeze["artifact_set_sha256"],
            "historical_freeze_manifest_sha256": freeze["manifest_sha256"],
            "source_step9t_batch_id": source_batch["batch_id"],
            "source_step9t_batch_payload_hash": source_batch["batch_payload_hash"],
            "candidate_set_hash": candidate_set_hash,
        }
        for field, expected in comparisons.items():
            if str(existing_batch[field]) != str(expected):
                raise ImmutableLedgerConflict(f"Conflicting rerun changed Step 9U prospective field {field}.")
        if export_outputs_after:
            export_outputs(ledger_db)
        return pd.DataFrame([existing_batch]), pd.DataFrame(existing_candidates), False
    if not allow_late and not simulated_clock:
        if session_date != now.date().isoformat():
            raise SourceDataNotReady("A new Step 9U prospective selection may only be sealed for the current session.")
        local_time = now.time().replace(tzinfo=None)
        if local_time < _clock_to_time(DECISION_TIME):
            raise SourceDataNotReady(f"Step 9U prospective selection is not allowed before {DECISION_TIME}.")
        if local_time > _clock_to_time(ASSIGNMENT_DEADLINE):
            raise SourceDataNotReady(f"Step 9U prospective selection deadline {ASSIGNMENT_DEADLINE} has passed.")
    status = _prospective_status(str(source_batch["prospective_status"]), session_date, now, allow_late, simulated_clock)
    selected = [row for row in candidates if int(row["selected"]) == 1]
    selected_sorted = sorted(selected, key=lambda row: int(row["selected_rank"]))
    batch_id = f"S9U-{session_date.replace('-', '')}-MORNING"
    batch_payload = {
        "assignment_batch_id": batch_id, "session_date": session_date, "prospective_status": status,
        "code_version": CODE_VERSION, "historical_freeze_id": freeze["freeze_id"],
        "historical_freeze_artifact_sha256": freeze["artifact_set_sha256"],
        "source_step9t_batch_id": source_batch["batch_id"],
        "source_step9t_batch_payload_hash": source_batch["batch_payload_hash"],
        "candidate_set_hash": candidate_set_hash,
    }
    batch_row = {
        "assignment_batch_id": batch_id, "experiment_id": EXPERIMENT_ID, "session_date": session_date,
        "created_at_stockholm": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "run_mode": "MORNING_CONTINGENCY_SELECTION_SEAL", "prospective_status": status,
        "decision_time": DECISION_TIME, "assignment_deadline": ASSIGNMENT_DEADLINE,
        "standardized_entry_label": ENTRY_LABEL, "code_version": CODE_VERSION,
        "historical_freeze_id": freeze["freeze_id"],
        "historical_freeze_artifact_sha256": freeze["artifact_set_sha256"],
        "historical_freeze_manifest_sha256": freeze["manifest_sha256"],
        "source_step9t_ledger_db": str(step9t_ledger_db), "source_step9t_batch_id": str(source_batch["batch_id"]),
        "source_step9t_batch_payload_hash": str(source_batch["batch_payload_hash"]),
        "source_regime": str(source_batch["source_regime"]), "transition_state": str(source_batch["transition_state"]),
        "directional_candidate_rows": len(candidates),
        "selectable_candidate_rows": sum(int(row["selection_eligible"]) for row in candidates),
        "blocked_negative_control_rows": sum(row["policy_action"] == "BLOCKED_NEGATIVE_CONTROL" for row in candidates),
        "observation_only_rows": sum(row["policy_action"] == "OBSERVATION_ONLY" for row in candidates),
        "selected_count": len(selected), "selected_tickers": "|".join(row["ticker"] for row in selected_sorted),
        "selected_rule_ids": "|".join(row["rule_id"] for row in selected_sorted),
        "no_selection_reason": "" if selected else "NO_SELECTABLE_CANDIDATE",
        "max_selected_positions": MAX_SELECTED_POSITIONS,
        "max_positions_per_sector": MAX_POSITIONS_PER_SECTOR,
        "candidate_set_hash": candidate_set_hash, "point_in_time_pass": 1,
        "mandatory_control_active": 0, "router_active": 0, "order_sent": 0,
        "batch_payload_hash": _payload_hash(batch_payload),
    }
    stored_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        row = {
            "assignment_batch_id": batch_id, "experiment_id": EXPERIMENT_ID, "code_version": CODE_VERSION,
            **candidate, "router_active": 0, "order_sent": 0,
        }
        row["row_payload_hash"] = _payload_hash({key: value for key, value in row.items() if key != "row_payload_hash"})
        stored_candidates.append(row)
    ledger_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(connection, "step9u_prospective_assignment_batches", "assignment_batch_id", "batch_payload_hash", batch_row)
        for row in stored_candidates:
            _insert_immutable(connection, "step9u_prospective_candidates", "candidate_id", "row_payload_hash", row)
        connection.commit()
    if export_outputs_after:
        export_outputs(ledger_db)
    return pd.DataFrame([batch_row]), pd.DataFrame(stored_candidates), inserted


def _read_existing_outcomes(ledger_db: Path, session_date: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not ledger_db.exists():
        return None, []
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        connection.row_factory = sqlite3.Row
        batch = connection.execute(
            "SELECT * FROM step9u_prospective_outcome_batches WHERE session_date = ?", (session_date,)
        ).fetchone()
        if not batch:
            return None, []
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM step9u_prospective_candidate_outcomes WHERE outcome_batch_id = ? ORDER BY ticker",
            (batch["outcome_batch_id"],),
        ).fetchall()]
    return dict(batch), rows


def evaluate_eod(
    session_date: str,
    now: datetime,
    step9t_ledger_db: Path = DEFAULT_STEP9T_LEDGER_DB,
    ledger_db: Path = DEFAULT_LEDGER_DB,
    allow_early: bool = False,
    export_outputs_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    assignment_batch, candidates = _read_existing_assignment(ledger_db, session_date)
    if not assignment_batch:
        raise SourceDataNotReady(f"No sealed Step 9U prospective morning selection exists for {session_date}.")
    if not allow_early:
        if session_date != now.date().isoformat():
            raise SourceDataNotReady("Step 9U EOD may only evaluate the current session.")
        if now.time().replace(tzinfo=None) < _clock_to_time(EOD_TIME):
            raise SourceDataNotReady(f"Step 9U EOD evaluation is not allowed before {EOD_TIME} Stockholm time.")
    source_outcome_batch, source_outcomes = _read_step9t_outcomes(session_date, step9t_ledger_db)
    if str(source_outcome_batch["morning_batch_id"]) != str(assignment_batch["source_step9t_batch_id"]):
        raise ImmutableLedgerConflict("Step 9T EOD batch does not match the Step 9U morning source batch.")
    source_by_ticker_row = {str(row["ticker_row_id"]): row for row in source_outcomes}
    outcome_batch_id = f"S9U-{session_date.replace('-', '')}-EOD"
    stored: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda row: row["ticker"]):
        source = source_by_ticker_row.get(str(candidate["source_ticker_row_id"]))
        if source is None:
            raise SourceIntegrityError(f"Missing Step 9T EOD outcome for Step 9U candidate {candidate['ticker']}.")
        payload = {
            "session_date": session_date, "ticker": str(candidate["ticker"]),
            "candidate_id": str(candidate["candidate_id"]), "source_step9t_outcome_id": str(source["outcome_id"]),
            "source_step9t_outcome_status": str(source["outcome_status"]),
            "primary_archetype": str(candidate["primary_archetype"]), "direction": str(candidate["direction"]),
            "policy_action": str(candidate["policy_action"]), "rule_id": str(candidate["rule_id"]),
            "selected": int(candidate["selected"]), "selected_rank": candidate["selected_rank"],
            "outcome_status": str(source["outcome_status"]), "entry_time": str(source["entry_time"]),
            "entry_price": source["entry_price"], "exit_time": str(source["exit_time"]), "exit_price": source["exit_price"],
            "session_close_return": source["session_close_return"], "mfe_return": source["mfe_return"],
            "mae_return": source["mae_return"], "gross_pnl_sek": source["gross_pnl_sek"],
            "cost_sek": source["cost_sek"], "net_pnl_sek": source["net_pnl_sek"],
        }
        payload["step9u_outcome_id"] = _payload_hash(payload)
        row = {
            "outcome_batch_id": outcome_batch_id, "assignment_batch_id": assignment_batch["assignment_batch_id"],
            **payload, "router_active": 0, "order_sent": 0,
        }
        row["row_payload_hash"] = _payload_hash({key: value for key, value in row.items() if key != "row_payload_hash"})
        stored.append(row)
    outcome_set_hash = _payload_hash([row["step9u_outcome_id"] for row in sorted(stored, key=lambda item: item["ticker"])])
    existing_batch, existing_rows = _read_existing_outcomes(ledger_db, session_date)
    if existing_batch:
        if str(existing_batch["source_step9t_outcome_payload_hash"]) != str(source_outcome_batch["outcome_payload_hash"]):
            raise ImmutableLedgerConflict("Step 9T EOD source batch changed on rerun.")
        if str(existing_batch["outcome_set_hash"]) != outcome_set_hash:
            raise ImmutableLedgerConflict("Step 9U candidate outcome set changed on rerun.")
        if export_outputs_after:
            export_outputs(ledger_db)
        return pd.DataFrame([existing_batch]), pd.DataFrame(existing_rows), False
    complete = [row for row in stored if row["outcome_status"] == "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"]
    incomplete = [row for row in stored if row["outcome_status"] != "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"]
    selected = [row for row in stored if int(row["selected"]) == 1]
    selected_complete = [row for row in selected if row["outcome_status"] == "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"]
    selected_incomplete = [row for row in selected if row["outcome_status"] != "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"]
    all_pnl = float(sum(float(row["net_pnl_sek"]) for row in complete if row["net_pnl_sek"] is not None))
    selected_pnl = float(sum(float(row["net_pnl_sek"]) for row in selected_complete if row["net_pnl_sek"] is not None))
    batch_payload = {
        "outcome_batch_id": outcome_batch_id, "assignment_batch_id": assignment_batch["assignment_batch_id"],
        "session_date": session_date, "code_version": CODE_VERSION,
        "source_step9t_outcome_batch_id": source_outcome_batch["outcome_batch_id"],
        "source_step9t_outcome_payload_hash": source_outcome_batch["outcome_payload_hash"],
        "outcome_set_hash": outcome_set_hash, "selected_net_pnl_sek": selected_pnl,
    }
    batch_row = {
        "outcome_batch_id": outcome_batch_id, "assignment_batch_id": assignment_batch["assignment_batch_id"],
        "session_date": session_date, "created_at_stockholm": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "code_version": CODE_VERSION, "source_step9t_outcome_batch_id": source_outcome_batch["outcome_batch_id"],
        "source_step9t_outcome_payload_hash": source_outcome_batch["outcome_payload_hash"],
        "all_candidate_outcomes": len(stored), "complete_candidate_outcomes": len(complete),
        "incomplete_candidate_outcomes": len(incomplete), "selected_outcomes": len(selected),
        "selected_complete_outcomes": len(selected_complete), "selected_incomplete_outcomes": len(selected_incomplete),
        "all_candidate_net_pnl_sek": all_pnl, "selected_net_pnl_sek": selected_pnl,
        "outcome_set_hash": outcome_set_hash, "mandatory_control_active": 0, "router_active": 0, "order_sent": 0,
        "outcome_payload_hash": _payload_hash(batch_payload),
    }
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(connection, "step9u_prospective_outcome_batches", "outcome_batch_id", "outcome_payload_hash", batch_row)
        for row in stored:
            _insert_immutable(connection, "step9u_prospective_candidate_outcomes", "step9u_outcome_id", "row_payload_hash", row)
        connection.commit()
    if export_outputs_after:
        export_outputs(ledger_db)
    return pd.DataFrame([batch_row]), pd.DataFrame(stored), inserted


def _read_table(connection: sqlite3.Connection, table: str) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {table}", connection)


def audit_ledger(ledger_db: Path = DEFAULT_LEDGER_DB) -> pd.DataFrame:
    checks: list[dict[str, Any]] = []
    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check_name": name, "passed": bool(passed), "detail": detail})
    if not ledger_db.is_file():
        add("LEDGER_EXISTS", False, str(ledger_db))
        return pd.DataFrame(checks)
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        batches = _read_table(connection, "step9u_prospective_assignment_batches")
        candidates = _read_table(connection, "step9u_prospective_candidates")
        outcome_batches = _read_table(connection, "step9u_prospective_outcome_batches")
        outcomes = _read_table(connection, "step9u_prospective_candidate_outcomes")
    add("LEDGER_EXISTS", True, str(ledger_db))
    add("UNIQUE_SESSION_ASSIGNMENTS", not batches["session_date"].duplicated().any(), f"rows={len(batches)}")
    add("UNIQUE_CANDIDATES", not candidates["candidate_id"].duplicated().any(), f"rows={len(candidates)}")
    add("SELECTION_MAX_TWO", bool((batches["selected_count"] <= 2).all()), "max_selected=2")
    sector_ok = True
    for _, group in candidates[candidates["selected"].eq(1)].groupby("session_date"):
        if group["broad_sector"].duplicated().any():
            sector_ok = False
    add("ONE_SELECTED_PER_SECTOR", sector_ok, "max_per_sector=1")
    add("NO_BLOCKED_SELECTED", not bool(((candidates["policy_action"] == "BLOCKED_NEGATIVE_CONTROL") & candidates["selected"].eq(1)).any()), "blocked selections=0")
    add("NO_OBSERVATION_SELECTED", not bool(((candidates["policy_action"] == "OBSERVATION_ONLY") & candidates["selected"].eq(1)).any()), "observation selections=0")
    add("SAFE_ASSIGNMENTS", not bool((batches["router_active"].eq(1) | batches["order_sent"].eq(1) | batches["mandatory_control_active"].eq(1)).any()), "router/order/control=false")
    if not outcome_batches.empty:
        add("UNIQUE_SESSION_OUTCOMES", not outcome_batches["session_date"].duplicated().any(), f"rows={len(outcome_batches)}")
        add("OUTCOMES_MATCH_CANDIDATES", set(outcomes["candidate_id"].astype(str)) == set(candidates[candidates["session_date"].isin(outcome_batches["session_date"])]["candidate_id"].astype(str)), "candidate outcome coverage")
        add("SAFE_OUTCOMES", not bool((outcome_batches["router_active"].eq(1) | outcome_batches["order_sent"].eq(1) | outcome_batches["mandatory_control_active"].eq(1)).any()), "router/order/control=false")
    return pd.DataFrame(checks)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temp, index=False, lineterminator="\n")
    temp.replace(path)


def export_outputs(ledger_db: Path = DEFAULT_LEDGER_DB, export_dir: Path = DEFAULT_EXPORT_DIR) -> None:
    if not ledger_db.is_file():
        raise FileNotFoundError(ledger_db)
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        batches = _read_table(connection, "step9u_prospective_assignment_batches")
        candidates = _read_table(connection, "step9u_prospective_candidates")
        outcome_batches = _read_table(connection, "step9u_prospective_outcome_batches")
        outcomes = _read_table(connection, "step9u_prospective_candidate_outcomes")
    selected = outcomes[outcomes["selected"].eq(1)].copy() if not outcomes.empty else outcomes.copy()
    summary = pd.DataFrame([{
        "experiment_id": EXPERIMENT_ID, "research_status": RESEARCH_STATUS, "code_version": CODE_VERSION,
        "sessions": len(batches), "directional_candidates": len(candidates),
        "selectable_candidates": int(candidates["selection_eligible"].sum()) if not candidates.empty else 0,
        "selected_candidates": int(candidates["selected"].sum()) if not candidates.empty else 0,
        "eod_sessions": len(outcome_batches), "candidate_outcomes": len(outcomes), "selected_outcomes": len(selected),
        "selected_net_pnl_sek": float(outcome_batches["selected_net_pnl_sek"].sum()) if not outcome_batches.empty else 0.0,
        "historical_freeze_id": str(CONFIG["historical_freeze_id"]),
        "mandatory_control_active": False, "router_active": False, "orders_sent": False,
    }])
    audit = audit_ledger(ledger_db)
    export_dir.mkdir(parents=True, exist_ok=True)
    for frame, name in [
        (batches, BATCH_EXPORT), (candidates, CANDIDATE_EXPORT), (outcome_batches, OUTCOME_BATCH_EXPORT),
        (outcomes, OUTCOME_EXPORT), (selected, SELECTED_EXPORT), (summary, SUMMARY_EXPORT), (audit, AUDIT_EXPORT),
    ]:
        _atomic_csv(frame, export_dir / name)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 9U prospective contingency selector shadow V1")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["morning", "eod"]:
        child = sub.add_parser(command)
        child.add_argument("--date", default="")
        child.add_argument("--as-of", default="")
        child.add_argument("--step9t-ledger-db", type=Path, default=DEFAULT_STEP9T_LEDGER_DB)
        child.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
        if command == "morning":
            child.add_argument("--allow-late-reconstruction", action="store_true")
        else:
            child.add_argument("--allow-early-evaluation", action="store_true")
    audit = sub.add_parser("audit")
    audit.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    audit.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "audit":
        export_outputs(args.ledger_db, args.export_dir)
        audit = audit_ledger(args.ledger_db)
        failed = audit[~audit["passed"]]
        print("=== STEP 9U PROSPECTIVE SHADOW AUDIT ===")
        print(f"Checks passed/failed: {int(audit['passed'].sum())}/{len(failed)}")
        print(f"Ledger: {args.ledger_db}")
        print("MANDATORY CONTROL ACTIVE: FALSE")
        print("ROUTER ACTIVE: FALSE")
        print("NO ORDER WAS SENT")
        if not failed.empty:
            raise Step9UProspectiveError(f"Step 9U prospective audit failed: {failed.to_dict('records')}")
        return
    now = _parse_stockholm_datetime(args.as_of)
    session_date = _target_date(args.date, now)
    if args.command == "morning":
        batches, candidates, inserted = seal_morning_selection(
            session_date, now, args.step9t_ledger_db, args.ledger_db,
            allow_late=bool(args.allow_late_reconstruction), export_outputs_after=True,
        )
        row = batches.iloc[0]
        print("=== STEP 9U PROSPECTIVE CONTINGENCY SHADOW SELECTION ===")
        print(f"Session date       : {session_date}")
        print(f"Ledger action      : {'SEALED_NEW_ASSIGNMENT_BATCH' if inserted else 'EXISTING_IDENTICAL_BATCH'}")
        print(f"Regime / transition: {row['source_regime']} / {row['transition_state']}")
        print(f"Candidates/selectable/selected: {len(candidates)}/{int(row['selectable_candidate_rows'])}/{int(row['selected_count'])}")
        print(f"Selected tickers   : {row['selected_tickers'] or 'NONE'}")
        print("MANDATORY CONTROL ACTIVE: FALSE")
        print("ROUTER ACTIVE: FALSE")
        print("NO ORDER WAS SENT")
    else:
        batches, outcomes, inserted = evaluate_eod(
            session_date, now, args.step9t_ledger_db, args.ledger_db,
            allow_early=bool(args.allow_early_evaluation), export_outputs_after=True,
        )
        row = batches.iloc[0]
        print("=== STEP 9U PROSPECTIVE CONTINGENCY SHADOW EOD ===")
        print(f"Session date       : {session_date}")
        print(f"Ledger action      : {'SEALED_NEW_OUTCOME_BATCH' if inserted else 'EXISTING_IDENTICAL_BATCH'}")
        print(f"Candidate outcomes : {len(outcomes)}")
        print(f"Selected outcomes  : {int(row['selected_outcomes'])}")
        print(f"Selected P&L       : {float(row['selected_net_pnl_sek']):.6f} SEK")
        print("All candidate outcomes were preserved; selections were not rewritten.")
        print("MANDATORY CONTROL ACTIVE: FALSE")
        print("ROUTER ACTIVE: FALSE")
        print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
