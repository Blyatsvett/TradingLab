from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date as date_type, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from RegimeTrading.core.paths import DATA_DIR, FREEZE_DIRS
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path
from RegimeTrading.scripts import step9t_regime_transition_archetype_research_v1 as historical


CONFIG_FILE = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "step9t_prospective_regime_transition_archetype_v1.json"
)
DEFAULT_SOURCE_DB = resolve_stage_path("prices")
DEFAULT_STEP9L_LEDGER_DB = resolve_stage_path("step9l")
DEFAULT_LEDGER_DB = DATA_DIR / "step9t_regime_transition_archetype_prospective_v1.db"
DEFAULT_EXPORT_DIR = resolve_stage_output_dir("step9t")
HISTORICAL_ROOT = DATA_DIR / "step9t_regime_transition_archetype_research_v1"
DEFAULT_FREEZE_ROOT = FREEZE_DIRS["step9t"]
DEFAULT_FREEZE_MANIFEST = DEFAULT_FREEZE_ROOT / "STEP9T_HISTORICAL_REPLAY_V1_FREEZE_MANIFEST.json"

STOCKHOLM = ZoneInfo("Europe/Stockholm")

BATCH_EXPORT = "step9t_prospective_transition_batches.csv"
ARCHETYPE_EXPORT = "step9t_prospective_ticker_archetypes.csv"
OUTCOME_BATCH_EXPORT = "step9t_prospective_outcome_batches.csv"
OUTCOME_EXPORT = "step9t_prospective_ticker_outcomes.csv"
SUMMARY_EXPORT = "step9t_prospective_summary.csv"
AUDIT_EXPORT = "step9t_prospective_audit.csv"


class Step9TProspectiveError(RuntimeError):
    pass


class SourceIntegrityError(Step9TProspectiveError):
    pass


class SourceDataNotReady(Step9TProspectiveError):
    pass


class ImmutableLedgerConflict(Step9TProspectiveError):
    pass


def _load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    if bool(config.get("router_active")):
        raise SourceIntegrityError("Step 9T prospective routing must remain disabled.")
    if bool(config.get("orders_enabled")):
        raise SourceIntegrityError("Step 9T prospective orders must remain disabled.")
    if bool(config.get("selection_active")):
        raise SourceIntegrityError("Step 9T V1 is an observer and may not select trades.")
    if str(config.get("source_duplicate_policy")) != "LATEST_SQLITE_ROWID_PER_TICKER_MINUTE_V1":
        raise SourceIntegrityError("Unexpected source duplicate policy.")
    if int(config.get("expected_universe_size", 0)) != 29:
        raise SourceIntegrityError("Step 9T prospective V1 requires the frozen 29-ticker universe.")
    return config


CONFIG = _load_config()
EXPERIMENT_ID = str(CONFIG["experiment_id"])
RESEARCH_STATUS = str(CONFIG["research_status"])
CODE_VERSION = str(CONFIG["code_version"])
DECISION_TIME = str(CONFIG["decision_time"])
ASSIGNMENT_DEADLINE = str(CONFIG["assignment_deadline"])
LATEST_MORNING_LABEL = str(CONFIG["latest_morning_source_label"])
ENTRY_LABEL = str(CONFIG["standardized_entry_label"])
EOD_MINIMUM_LABEL = str(CONFIG["eod_minimum_label"])
EOD_TIME = str(CONFIG["eod_time"])
EXPECTED_UNIVERSE_SIZE = int(CONFIG["expected_universe_size"])
BASE_NOTIONAL_SEK = float(CONFIG["base_notional_sek"])
ROUND_TRIP_COST_RATE = float(CONFIG["round_trip_cost_rate"])
SOURCE_DUPLICATE_POLICY = str(CONFIG["source_duplicate_policy"])


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
    return json.dumps(
        _clean_scalar(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _parse_stockholm_datetime(value: str | None) -> datetime:
    if value:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            return parsed.tz_localize(STOCKHOLM).to_pydatetime()
        return parsed.tz_convert(STOCKHOLM).to_pydatetime()
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
    if not bool(CONFIG.get("historical_freeze_required", True)):
        return {
            "freeze_id": "NOT_REQUIRED",
            "artifact_set_sha256": "NOT_REQUIRED",
            "manifest_sha256": "NOT_REQUIRED",
        }
    if not manifest_path.is_file():
        raise SourceDataNotReady(
            f"Step 9T historical freeze manifest is missing: {manifest_path}"
        )
    manifest_hash = _sha256(manifest_path)
    if manifest_hash != str(CONFIG["historical_freeze_manifest_sha256"]):
        raise SourceIntegrityError("Step 9T historical freeze manifest hash is invalid.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if str(manifest.get("freeze_id")) != str(CONFIG["historical_freeze_id"]):
        raise SourceIntegrityError("Unexpected Step 9T historical freeze ID.")
    if str(manifest.get("artifact_set_sha256")) != str(
        CONFIG["historical_freeze_artifact_sha256"]
    ):
        raise SourceIntegrityError("Unexpected Step 9T historical artifact-set hash.")
    if int(manifest.get("independent_audit", {}).get("failed", -1)) != 0:
        raise SourceIntegrityError("Step 9T historical freeze audit is not clean.")
    if int(manifest.get("independent_audit", {}).get("passed", -1)) != 30:
        raise SourceIntegrityError("Step 9T historical freeze audit is not 30/30.")
    if bool(manifest.get("router_active")) or bool(manifest.get("orders_sent")):
        raise SourceIntegrityError("Step 9T historical freeze has an unsafe state.")
    historical_config = historical.CONFIG_FILE
    if _sha256(historical_config) != str(CONFIG["historical_config_sha256"]):
        raise SourceIntegrityError("Frozen Step 9T historical configuration changed.")
    return {
        "freeze_id": str(manifest["freeze_id"]),
        "artifact_set_sha256": str(manifest["artifact_set_sha256"]),
        "manifest_sha256": manifest_hash,
    }


def _verify_step9l_batch_hash(row: dict[str, Any]) -> None:
    taxonomy_payload = json.loads(str(row["taxonomy_payload_json"]))
    payload = {
        "batch_id": row["batch_id"],
        "session_date": row["session_date"],
        "prospective_status": row["prospective_status"],
        "code_version": row["code_version"],
        "contract_registry_hash": row["contract_registry_hash"],
        "universe_hash": row["universe_hash"],
        "source_max_datetime": row["source_max_datetime"],
        "taxonomy_payload": taxonomy_payload,
        "decision_rows": int(row["decision_rows"]),
        "eligible_rows": int(row["eligible_rows"]),
        "active_guardrails": int(row["active_guardrails"]),
    }
    if _payload_hash(payload) != str(row["batch_payload_hash"]):
        raise SourceIntegrityError("The sealed Step 9L morning batch payload hash is invalid.")


def _read_step9l_morning(
    session_date: str,
    ledger_db: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    with closing(_readonly_connection(ledger_db)) as connection:
        connection.row_factory = sqlite3.Row
        batches = connection.execute(
            "SELECT * FROM shadow_decision_batches WHERE session_date = ?",
            (session_date,),
        ).fetchall()
        if len(batches) != 1:
            raise SourceDataNotReady(
                f"Expected one sealed Step 9L V3 morning batch for {session_date}; found {len(batches)}."
            )
        batch = dict(batches[0])
        decisions = [
            dict(row)
            for row in connection.execute(
                "SELECT rowid, * FROM shadow_decisions WHERE batch_id = ? ORDER BY rowid",
                (batch["batch_id"],),
            ).fetchall()
        ]
    if str(batch["experiment_id"]) != str(CONFIG["source_step9l_experiment_id"]):
        raise SourceIntegrityError(f"Unexpected Step 9L experiment: {batch['experiment_id']}")
    if str(batch["code_version"]) != str(CONFIG["source_step9l_code_version"]):
        raise SourceIntegrityError(f"Unexpected Step 9L code version: {batch['code_version']}")
    if str(batch["run_mode"]) != "MORNING_DECISION_SEAL":
        raise SourceIntegrityError("Step 9L source row is not a morning decision seal.")
    if not bool(int(batch["regime_point_in_time_pass"])):
        raise SourceIntegrityError("Step 9L source regime is not point-in-time eligible.")
    if int(batch["decision_rows"]) != len(decisions):
        raise SourceIntegrityError("Step 9L decision count does not match the sealed batch.")
    _verify_step9l_batch_hash(batch)
    for row in decisions:
        payload = {
            key: value
            for key, value in row.items()
            if key not in {"rowid", "row_payload_hash"}
        }
        if _payload_hash(payload) != str(row["row_payload_hash"]):
            raise SourceIntegrityError(f"Invalid Step 9L decision hash: {row['decision_id']}")
    decision_set_hash = _payload_hash([row["row_payload_hash"] for row in decisions])
    return batch, decisions, decision_set_hash


def _load_prices_canonical(
    path: Path,
    session_date: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    query = """
        SELECT rowid AS source_rowid, datetime, open, high, low, close, ticker
        FROM intraday_prices
        WHERE substr(datetime, 1, 10) = ?
        ORDER BY ticker, datetime, source_rowid
    """
    with closing(_readonly_connection(path)) as connection:
        prices = pd.read_sql_query(query, connection, params=[session_date])
    if prices.empty:
        raise SourceDataNotReady(f"No source prices found for {session_date}.")
    prices["source_rowid"] = pd.to_numeric(
        prices["source_rowid"], errors="raise"
    ).astype("int64")
    prices["datetime"] = pd.to_datetime(prices["datetime"], errors="raise", format="mixed")
    prices["ticker"] = prices["ticker"].astype(str).str.strip()
    for column in ["open", "high", "low", "close"]:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
    prices = prices.dropna(
        subset=["datetime", "ticker", "open", "high", "low", "close"]
    ).copy()
    prices["session_date"] = prices["datetime"].dt.strftime("%Y-%m-%d")
    prices["clock"] = prices["datetime"].dt.strftime("%H:%M")
    key = ["session_date", "ticker", "clock"]
    counts = prices.groupby(key, dropna=False)["source_rowid"].transform("size")
    prices["source_duplicate_count"] = counts.astype("int64")
    conflict = (
        prices.groupby(key, dropna=False)[["open", "high", "low", "close"]]
        .nunique(dropna=False)
        .max(axis=1)
        .gt(1)
    )
    conflict_keys = set(conflict[conflict].index.tolist())
    prices["source_duplicate_conflict"] = [
        int((date, ticker, clock) in conflict_keys)
        for date, ticker, clock in prices[key].itertuples(index=False, name=None)
    ]
    canonical = (
        prices.sort_values(key + ["source_rowid"], kind="mergesort")
        .drop_duplicates(key, keep="last")
        .sort_values(["ticker", "datetime", "source_rowid"], kind="mergesort")
        .reset_index(drop=True)
    )
    group_sizes = prices.groupby(key, dropna=False).size()
    provenance = {
        "raw_row_count": int(len(prices)),
        "canonical_row_count": int(len(canonical)),
        "duplicate_minute_count": int(group_sizes.gt(1).sum()),
        "conflicting_minute_count": int(len(conflict_keys)),
        "source_max_datetime": pd.Timestamp(canonical["datetime"].max()).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }
    return canonical, provenance


def _bar_map(ticker_prices: pd.DataFrame) -> dict[str, Any]:
    return {str(row.clock): row for row in ticker_prices.itertuples(index=False)}


def _direction_for_archetype(archetype: str) -> str:
    if archetype.endswith("_LONG"):
        return "LONG"
    if archetype.endswith("_SHORT"):
        return "SHORT"
    return "NONE"


def _primary_archetype(flags: dict[str, bool]) -> str:
    for archetype in historical.ARCHETYPE_PRIORITY:
        if archetype == "NO_CLEAR_SETUP" or flags.get(archetype, False):
            return archetype
    raise AssertionError("Frozen Step 9T archetype priority did not produce a label.")


def classify_ticker_assignment(
    session_date: str,
    ticker_row: pd.Series,
    ticker_prices: pd.DataFrame,
) -> dict[str, Any]:
    bars = _bar_map(ticker_prices[ticker_prices["clock"] <= LATEST_MORNING_LABEL])
    required = ("09:30", "09:35", "09:40", LATEST_MORNING_LABEL)
    missing = [label for label in required if label not in bars]
    base = {
        "experiment_id": EXPERIMENT_ID,
        "code_version": CODE_VERSION,
        "session_date": session_date,
        "ticker": str(ticker_row["ticker"]),
        "company_id": str(ticker_row["company_id"]),
        "broad_sector": str(ticker_row["broad_sector"]),
        "universe_role": str(ticker_row["universe_role"]),
        "latest_morning_source_label": LATEST_MORNING_LABEL,
        "standardized_entry_label": ENTRY_LABEL,
    }
    if missing:
        payload = {
            **base,
            "morning_status": "INCOMPLETE_MORNING_BARS",
            "missing_labels": "|".join(missing),
            "early_return": np.nan,
            "last5_return": np.nan,
            "opening_range_high": np.nan,
            "opening_range_low": np.nan,
            "opening_range_midpoint": np.nan,
            "opening_range_position": np.nan,
            "midpoint_reclaimed": False,
            "bullish_continuation_flag": False,
            "bearish_continuation_flag": False,
            "laggard_recovery_flag": False,
            "leader_reversal_flag": False,
            "primary_archetype": "NO_CLEAR_SETUP",
            "direction": "NONE",
            "max_source_label_used": max(bars) if bars else "",
            "point_in_time_pass": 1,
            "router_active": 0,
            "order_sent": 0,
        }
        payload["ticker_row_id"] = _payload_hash(payload)
        payload["row_payload_hash"] = _payload_hash(payload)
        return payload

    open_0930 = float(bars["09:30"].open)
    close_0940 = float(bars["09:40"].close)
    close_0945 = float(bars[LATEST_MORNING_LABEL].close)
    early_return = close_0945 / open_0930 - 1.0
    last5_return = close_0945 / close_0940 - 1.0
    opening_rows = [bars[label] for label in ("09:30", "09:35", "09:40")]
    opening_high = max(float(row.high) for row in opening_rows)
    opening_low = min(float(row.low) for row in opening_rows)
    midpoint = (opening_high + opening_low) / 2.0
    if opening_high > opening_low:
        range_position = (close_0945 - opening_low) / (opening_high - opening_low)
    else:
        range_position = 0.5
    midpoint_reclaimed = bool(
        early_return <= -historical.EARLY_MOVE_THRESHOLD and close_0945 >= midpoint
    )
    flags = {
        "LAGGARD_RECOVERY_LONG": bool(
            early_return <= -historical.EARLY_MOVE_THRESHOLD
            and (
                last5_return >= historical.LAST5_CONFIRMATION_THRESHOLD
                or midpoint_reclaimed
            )
        ),
        "LEADER_REVERSAL_SHORT": bool(
            early_return >= historical.EARLY_MOVE_THRESHOLD
            and last5_return <= -historical.LAST5_CONFIRMATION_THRESHOLD
        ),
        "BULLISH_CONTINUATION_LONG": bool(
            early_return >= historical.EARLY_MOVE_THRESHOLD and last5_return >= 0.0
        ),
        "BEARISH_CONTINUATION_SHORT": bool(
            early_return <= -historical.EARLY_MOVE_THRESHOLD and last5_return <= 0.0
        ),
    }
    archetype = _primary_archetype(flags)
    payload = {
        **base,
        "morning_status": "MORNING_COMPLETE",
        "missing_labels": "",
        "early_return": early_return,
        "last5_return": last5_return,
        "opening_range_high": opening_high,
        "opening_range_low": opening_low,
        "opening_range_midpoint": midpoint,
        "opening_range_position": range_position,
        "midpoint_reclaimed": midpoint_reclaimed,
        "bullish_continuation_flag": flags["BULLISH_CONTINUATION_LONG"],
        "bearish_continuation_flag": flags["BEARISH_CONTINUATION_SHORT"],
        "laggard_recovery_flag": flags["LAGGARD_RECOVERY_LONG"],
        "leader_reversal_flag": flags["LEADER_REVERSAL_SHORT"],
        "primary_archetype": archetype,
        "direction": _direction_for_archetype(archetype),
        "max_source_label_used": LATEST_MORNING_LABEL,
        "point_in_time_pass": 1,
        "router_active": 0,
        "order_sent": 0,
    }
    payload["ticker_row_id"] = _payload_hash(payload)
    payload["row_payload_hash"] = _payload_hash(payload)
    return payload


def _morning_price_snapshot_hash(prices: pd.DataFrame, session_date: str) -> str:
    required_labels = {"09:30", "09:35", "09:40", LATEST_MORNING_LABEL}
    scoped = prices[prices["clock"].isin(required_labels)].copy()
    rows = []
    for row in scoped.sort_values(["ticker", "clock"]).itertuples(index=False):
        rows.append(
            {
                "session_date": session_date,
                "ticker": str(row.ticker),
                "clock": str(row.clock),
                "source_rowid": int(row.source_rowid),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
            }
        )
    return _payload_hash(rows)


def _eod_price_snapshot_hash(prices: pd.DataFrame, session_date: str) -> str:
    scoped = prices[prices["clock"] >= ENTRY_LABEL].copy()
    rows = []
    for row in scoped.sort_values(["ticker", "clock"]).itertuples(index=False):
        rows.append(
            {
                "session_date": session_date,
                "ticker": str(row.ticker),
                "clock": str(row.clock),
                "source_rowid": int(row.source_rowid),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
            }
        )
    return _payload_hash(rows)


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS step9t_prospective_batches (
            batch_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            session_date TEXT NOT NULL UNIQUE,
            created_at_stockholm TEXT NOT NULL,
            run_mode TEXT NOT NULL,
            prospective_status TEXT NOT NULL,
            decision_time TEXT NOT NULL,
            assignment_deadline TEXT NOT NULL,
            latest_morning_source_label TEXT NOT NULL,
            standardized_entry_label TEXT NOT NULL,
            code_version TEXT NOT NULL,
            historical_freeze_id TEXT NOT NULL,
            historical_freeze_artifact_sha256 TEXT NOT NULL,
            historical_freeze_manifest_sha256 TEXT NOT NULL,
            source_step9l_db TEXT NOT NULL,
            source_step9l_batch_id TEXT NOT NULL,
            source_step9l_batch_payload_hash TEXT NOT NULL,
            source_step9l_decision_set_hash TEXT NOT NULL,
            source_price_db TEXT NOT NULL,
            source_duplicate_policy TEXT NOT NULL,
            source_max_datetime TEXT NOT NULL,
            raw_source_rows INTEGER NOT NULL,
            canonical_source_rows INTEGER NOT NULL,
            conflicting_minute_count INTEGER NOT NULL,
            morning_price_snapshot_hash TEXT NOT NULL,
            source_regime TEXT NOT NULL,
            source_regime_confidence REAL,
            source_confidence_band TEXT NOT NULL,
            source_direction_bias TEXT NOT NULL,
            transition_state TEXT NOT NULL,
            valid_ticker_count INTEGER NOT NULL,
            incomplete_ticker_count INTEGER NOT NULL,
            advancer_share REAL,
            decliner_share REAL,
            median_early_return REAL,
            median_last5_return REAL,
            early_loser_count INTEGER NOT NULL,
            early_winner_count INTEGER NOT NULL,
            recovery_share_of_early_losers REAL NOT NULL,
            continuation_share_of_early_winners REAL NOT NULL,
            midpoint_reclaim_share REAL NOT NULL,
            leader_failure_share REAL NOT NULL,
            cross_sectional_dispersion REAL,
            ticker_row_count INTEGER NOT NULL,
            point_in_time_pass INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            batch_payload_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS step9t_prospective_ticker_archetypes (
            ticker_row_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            experiment_id TEXT NOT NULL,
            code_version TEXT NOT NULL,
            session_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            company_id TEXT NOT NULL,
            broad_sector TEXT NOT NULL,
            universe_role TEXT NOT NULL,
            latest_morning_source_label TEXT NOT NULL,
            standardized_entry_label TEXT NOT NULL,
            morning_status TEXT NOT NULL,
            missing_labels TEXT NOT NULL,
            early_return REAL,
            last5_return REAL,
            opening_range_high REAL,
            opening_range_low REAL,
            opening_range_midpoint REAL,
            opening_range_position REAL,
            midpoint_reclaimed INTEGER NOT NULL,
            bullish_continuation_flag INTEGER NOT NULL,
            bearish_continuation_flag INTEGER NOT NULL,
            laggard_recovery_flag INTEGER NOT NULL,
            leader_reversal_flag INTEGER NOT NULL,
            primary_archetype TEXT NOT NULL,
            direction TEXT NOT NULL,
            max_source_label_used TEXT NOT NULL,
            point_in_time_pass INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            row_payload_hash TEXT NOT NULL,
            UNIQUE(session_date, ticker),
            FOREIGN KEY(batch_id) REFERENCES step9t_prospective_batches(batch_id)
        );
        CREATE TABLE IF NOT EXISTS step9t_prospective_outcome_batches (
            outcome_batch_id TEXT PRIMARY KEY,
            morning_batch_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL UNIQUE,
            created_at_stockholm TEXT NOT NULL,
            code_version TEXT NOT NULL,
            source_price_db TEXT NOT NULL,
            source_duplicate_policy TEXT NOT NULL,
            source_max_datetime TEXT NOT NULL,
            eod_price_snapshot_hash TEXT NOT NULL,
            eod_complete INTEGER NOT NULL,
            ticker_outcome_rows INTEGER NOT NULL,
            directional_outcomes INTEGER NOT NULL,
            zero_outcomes INTEGER NOT NULL,
            incomplete_outcomes INTEGER NOT NULL,
            net_standardized_directional_pnl_sek REAL NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            outcome_payload_hash TEXT NOT NULL,
            FOREIGN KEY(morning_batch_id) REFERENCES step9t_prospective_batches(batch_id)
        );
        CREATE TABLE IF NOT EXISTS step9t_prospective_ticker_outcomes (
            outcome_id TEXT PRIMARY KEY,
            outcome_batch_id TEXT NOT NULL,
            morning_batch_id TEXT NOT NULL,
            ticker_row_id TEXT NOT NULL UNIQUE,
            experiment_id TEXT NOT NULL,
            code_version TEXT NOT NULL,
            session_date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            primary_archetype TEXT NOT NULL,
            direction TEXT NOT NULL,
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
            point_in_time_pass INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            row_payload_hash TEXT NOT NULL,
            UNIQUE(session_date, ticker),
            FOREIGN KEY(outcome_batch_id) REFERENCES step9t_prospective_outcome_batches(outcome_batch_id),
            FOREIGN KEY(morning_batch_id) REFERENCES step9t_prospective_batches(batch_id),
            FOREIGN KEY(ticker_row_id) REFERENCES step9t_prospective_ticker_archetypes(ticker_row_id)
        );
        """
    )
    for table in [
        "step9t_prospective_batches",
        "step9t_prospective_ticker_archetypes",
        "step9t_prospective_outcome_batches",
        "step9t_prospective_ticker_outcomes",
    ]:
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_STEP9T_PROSPECTIVE_UPDATE_FORBIDDEN'); END"
        )
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_STEP9T_PROSPECTIVE_DELETE_FORBIDDEN'); END"
        )


def _insert_immutable(
    connection: sqlite3.Connection,
    table: str,
    key_column: str,
    hash_column: str,
    row: dict[str, Any],
) -> bool:
    existing = connection.execute(
        f"SELECT {hash_column} FROM {table} WHERE {key_column} = ?",
        (row[key_column],),
    ).fetchone()
    if existing:
        if str(existing[0]) != str(row[hash_column]):
            raise ImmutableLedgerConflict(
                f"Conflicting immutable Step 9T prospective row for "
                f"{table}.{key_column}={row[key_column]}"
            )
        return False
    columns = list(row)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        [_clean_scalar(row[column]) for column in columns],
    )
    return True


def _read_existing_morning(
    ledger_db: Path,
    session_date: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not ledger_db.exists():
        return None, []
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        connection.row_factory = sqlite3.Row
        batch = connection.execute(
            "SELECT * FROM step9t_prospective_batches WHERE session_date = ?",
            (session_date,),
        ).fetchone()
        if not batch:
            return None, []
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM step9t_prospective_ticker_archetypes "
                "WHERE batch_id = ? ORDER BY ticker",
                (batch["batch_id"],),
            ).fetchall()
        ]
    return dict(batch), rows


def _prospective_status(
    session_date: str,
    now: datetime,
    source_status: str,
    allow_late: bool,
    simulated_clock: bool,
) -> str:
    if simulated_clock:
        return "SIMULATED_POINT_IN_TIME_VERIFICATION_NOT_CONFIRMATORY"
    if allow_late or session_date != now.date().isoformat():
        return "LATE_RECONSTRUCTION_NOT_CONFIRMATORY"
    if "LATE" in str(source_status).upper():
        return "SOURCE_STEP9L_LATE_NOT_CONFIRMATORY"
    return "PROSPECTIVE_SHADOW_OBSERVATION"


def seal_morning_snapshot(
    session_date: str,
    now: datetime,
    source_db: Path = DEFAULT_SOURCE_DB,
    step9l_ledger_db: Path = DEFAULT_STEP9L_LEDGER_DB,
    ledger_db: Path = DEFAULT_LEDGER_DB,
    allow_late: bool = False,
    simulated_clock: bool = False,
    export_outputs_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    freeze = _historical_freeze_provenance()
    source_batch, _, decision_set_hash = _read_step9l_morning(
        session_date, step9l_ledger_db
    )
    prices, source_provenance = _load_prices_canonical(source_db, session_date)
    if str(prices["clock"].max()) < LATEST_MORNING_LABEL:
        raise SourceDataNotReady(
            f"Step 9T morning prices are not ready through {LATEST_MORNING_LABEL}."
        )
    universe = historical._load_universe(
        historical.DEFAULT_CORE_REGISTRY,
        historical.DEFAULT_HOLDOUT_REGISTRY,
    )
    rows = []
    for ticker in universe.to_dict("records"):
        row = classify_ticker_assignment(
            session_date,
            pd.Series(ticker),
            prices[prices["ticker"].eq(str(ticker["ticker"]))],
        )
        rows.append(row)
    archetypes = pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)
    if len(archetypes) != EXPECTED_UNIVERSE_SIZE:
        raise SourceIntegrityError(
            f"Expected {EXPECTED_UNIVERSE_SIZE} prospective ticker rows, found {len(archetypes)}."
        )
    if bool((archetypes["max_source_label_used"] > LATEST_MORNING_LABEL).any()):
        raise SourceIntegrityError("A Step 9T morning row used a bar later than 09:45.")
    transition_state, features = historical.classify_transition(archetypes)
    morning_hash = _morning_price_snapshot_hash(prices, session_date)
    ticker_set_hash = _payload_hash(
        archetypes.sort_values("ticker")["ticker_row_id"].tolist()
    )
    batch_id = f"S9T-{session_date.replace('-', '')}-MORNING"

    existing_batch, existing_rows = _read_existing_morning(ledger_db, session_date)
    if existing_batch:
        comparisons = {
            "historical_freeze_id": freeze["freeze_id"],
            "historical_freeze_artifact_sha256": freeze["artifact_set_sha256"],
            "historical_freeze_manifest_sha256": freeze["manifest_sha256"],
            "source_step9l_batch_id": source_batch["batch_id"],
            "source_step9l_batch_payload_hash": source_batch["batch_payload_hash"],
            "source_step9l_decision_set_hash": decision_set_hash,
            "morning_price_snapshot_hash": morning_hash,
            "source_regime": source_batch["primary_regime"],
            "transition_state": transition_state,
            "ticker_row_count": len(archetypes),
        }
        for field, expected in comparisons.items():
            if str(existing_batch[field]) != str(expected):
                raise ImmutableLedgerConflict(
                    f"Conflicting rerun changed Step 9T prospective field {field}."
                )
        existing_hash = _payload_hash(
            [row["ticker_row_id"] for row in sorted(existing_rows, key=lambda item: item["ticker"])]
        )
        if existing_hash != ticker_set_hash:
            raise ImmutableLedgerConflict(
                "Conflicting rerun changed the Step 9T prospective ticker assignment set."
            )
        if export_outputs_after:
            export_outputs(ledger_db)
        return pd.DataFrame([existing_batch]), pd.DataFrame(existing_rows), False

    if not allow_late and not simulated_clock:
        if session_date != now.date().isoformat():
            raise SourceDataNotReady(
                "A new Step 9T prospective snapshot may only be sealed for the current session."
            )
        if now.time().replace(tzinfo=None) < _clock_to_time(DECISION_TIME):
            raise SourceDataNotReady(
                f"Step 9T prospective snapshot is not allowed before {DECISION_TIME}."
            )
        if now.time().replace(tzinfo=None) > _clock_to_time(ASSIGNMENT_DEADLINE):
            raise SourceDataNotReady(
                f"Step 9T prospective snapshot deadline {ASSIGNMENT_DEADLINE} has passed."
            )
    status = _prospective_status(
        session_date,
        now,
        str(source_batch["prospective_status"]),
        allow_late,
        simulated_clock,
    )
    created = now.strftime("%Y-%m-%d %H:%M:%S%z")
    batch_payload = {
        "batch_id": batch_id,
        "session_date": session_date,
        "prospective_status": status,
        "code_version": CODE_VERSION,
        "historical_freeze_id": freeze["freeze_id"],
        "historical_freeze_artifact_sha256": freeze["artifact_set_sha256"],
        "source_step9l_batch_id": source_batch["batch_id"],
        "source_step9l_batch_payload_hash": source_batch["batch_payload_hash"],
        "source_step9l_decision_set_hash": decision_set_hash,
        "morning_price_snapshot_hash": morning_hash,
        "source_regime": source_batch["primary_regime"],
        "transition_state": transition_state,
        "features": features,
        "ticker_set_hash": ticker_set_hash,
    }
    batch_row = {
        "batch_id": batch_id,
        "experiment_id": EXPERIMENT_ID,
        "session_date": session_date,
        "created_at_stockholm": created,
        "run_mode": "MORNING_TRANSITION_ARCHETYPE_SEAL",
        "prospective_status": status,
        "decision_time": DECISION_TIME,
        "assignment_deadline": ASSIGNMENT_DEADLINE,
        "latest_morning_source_label": LATEST_MORNING_LABEL,
        "standardized_entry_label": ENTRY_LABEL,
        "code_version": CODE_VERSION,
        "historical_freeze_id": freeze["freeze_id"],
        "historical_freeze_artifact_sha256": freeze["artifact_set_sha256"],
        "historical_freeze_manifest_sha256": freeze["manifest_sha256"],
        "source_step9l_db": str(step9l_ledger_db),
        "source_step9l_batch_id": str(source_batch["batch_id"]),
        "source_step9l_batch_payload_hash": str(source_batch["batch_payload_hash"]),
        "source_step9l_decision_set_hash": decision_set_hash,
        "source_price_db": str(source_db),
        "source_duplicate_policy": SOURCE_DUPLICATE_POLICY,
        "source_max_datetime": str(source_provenance["source_max_datetime"]),
        "raw_source_rows": int(source_provenance["raw_row_count"]),
        "canonical_source_rows": int(source_provenance["canonical_row_count"]),
        "conflicting_minute_count": int(source_provenance["conflicting_minute_count"]),
        "morning_price_snapshot_hash": morning_hash,
        "source_regime": str(source_batch["primary_regime"]),
        "source_regime_confidence": float(source_batch["regime_confidence"]),
        "source_confidence_band": str(source_batch["confidence_band"]),
        "source_direction_bias": str(source_batch["direction_bias"]),
        "transition_state": transition_state,
        **features,
        "ticker_row_count": int(len(archetypes)),
        "point_in_time_pass": 1,
        "router_active": 0,
        "order_sent": 0,
        "batch_payload_hash": _payload_hash(batch_payload),
    }
    archetype_rows = []
    for row in rows:
        stored = {"batch_id": batch_id, **row}
        stored["row_payload_hash"] = _payload_hash(
            {key: value for key, value in stored.items() if key != "row_payload_hash"}
        )
        archetype_rows.append(stored)

    ledger_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(
            connection,
            "step9t_prospective_batches",
            "batch_id",
            "batch_payload_hash",
            batch_row,
        )
        for row in archetype_rows:
            _insert_immutable(
                connection,
                "step9t_prospective_ticker_archetypes",
                "ticker_row_id",
                "row_payload_hash",
                row,
            )
        connection.commit()
    if export_outputs_after:
        export_outputs(ledger_db)
    return pd.DataFrame([batch_row]), pd.DataFrame(archetype_rows), inserted


def _read_existing_outcomes(
    ledger_db: Path,
    session_date: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not ledger_db.exists():
        return None, []
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        connection.row_factory = sqlite3.Row
        batch = connection.execute(
            "SELECT * FROM step9t_prospective_outcome_batches WHERE session_date = ?",
            (session_date,),
        ).fetchone()
        if not batch:
            return None, []
        outcomes = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM step9t_prospective_ticker_outcomes "
                "WHERE outcome_batch_id = ? ORDER BY ticker",
                (batch["outcome_batch_id"],),
            ).fetchall()
        ]
    return dict(batch), outcomes


def evaluate_ticker_outcome(
    archetype_row: dict[str, Any],
    ticker_prices: pd.DataFrame,
) -> dict[str, Any]:
    base = {
        "experiment_id": EXPERIMENT_ID,
        "code_version": CODE_VERSION,
        "session_date": str(archetype_row["session_date"]),
        "ticker": str(archetype_row["ticker"]),
        "ticker_row_id": str(archetype_row["ticker_row_id"]),
        "primary_archetype": str(archetype_row["primary_archetype"]),
        "direction": str(archetype_row["direction"]),
        "entry_time": ENTRY_LABEL,
        "point_in_time_pass": int(archetype_row["point_in_time_pass"]),
        "router_active": 0,
        "order_sent": 0,
    }
    if str(archetype_row["morning_status"]) != "MORNING_COMPLETE":
        payload = {
            **base,
            "outcome_status": "MORNING_INCOMPLETE_NO_OUTCOME",
            "entry_price": np.nan,
            "exit_time": "",
            "exit_price": np.nan,
            "session_close_return": np.nan,
            "mfe_return": np.nan,
            "mae_return": np.nan,
            "gross_pnl_sek": np.nan,
            "cost_sek": np.nan,
            "net_pnl_sek": np.nan,
        }
        payload["outcome_id"] = _payload_hash(payload)
        return payload
    bars = _bar_map(ticker_prices)
    if ENTRY_LABEL not in bars:
        payload = {
            **base,
            "outcome_status": "ENTRY_BAR_MISSING_NO_OUTCOME",
            "entry_price": np.nan,
            "exit_time": "",
            "exit_price": np.nan,
            "session_close_return": np.nan,
            "mfe_return": np.nan,
            "mae_return": np.nan,
            "gross_pnl_sek": np.nan,
            "cost_sek": np.nan,
            "net_pnl_sek": np.nan,
        }
        payload["outcome_id"] = _payload_hash(payload)
        return payload
    after_entry = ticker_prices[ticker_prices["clock"] >= ENTRY_LABEL].sort_values("datetime")
    if after_entry.empty or str(after_entry.iloc[-1]["clock"]) < EOD_MINIMUM_LABEL:
        payload = {
            **base,
            "outcome_status": "EOD_INCOMPLETE_NO_OUTCOME",
            "entry_price": float(bars[ENTRY_LABEL].open),
            "exit_time": "",
            "exit_price": np.nan,
            "session_close_return": np.nan,
            "mfe_return": np.nan,
            "mae_return": np.nan,
            "gross_pnl_sek": np.nan,
            "cost_sek": np.nan,
            "net_pnl_sek": np.nan,
        }
        payload["outcome_id"] = _payload_hash(payload)
        return payload
    direction = str(archetype_row["direction"])
    entry = float(bars[ENTRY_LABEL].open)
    last = after_entry.iloc[-1]
    exit_price = float(last["close"])
    exit_time = pd.Timestamp(last["datetime"]).strftime("%H:%M")
    if direction == "LONG":
        close_return = exit_price / entry - 1.0
        mfe = float((after_entry["high"] / entry - 1.0).max())
        mae = float((after_entry["low"] / entry - 1.0).min())
        gross = BASE_NOTIONAL_SEK * close_return
        cost = BASE_NOTIONAL_SEK * ROUND_TRIP_COST_RATE
        status = "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"
    elif direction == "SHORT":
        close_return = 1.0 - exit_price / entry
        mfe = float((1.0 - after_entry["low"] / entry).max())
        mae = float((1.0 - after_entry["high"] / entry).min())
        gross = BASE_NOTIONAL_SEK * close_return
        cost = BASE_NOTIONAL_SEK * ROUND_TRIP_COST_RATE
        status = "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"
    else:
        close_return = 0.0
        mfe = 0.0
        mae = 0.0
        gross = 0.0
        cost = 0.0
        status = "NO_CLEAR_SETUP_ZERO_OUTCOME"
    payload = {
        **base,
        "outcome_status": status,
        "entry_price": entry,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "session_close_return": close_return,
        "mfe_return": mfe,
        "mae_return": mae,
        "gross_pnl_sek": gross,
        "cost_sek": cost,
        "net_pnl_sek": gross - cost,
    }
    payload["outcome_id"] = _payload_hash(payload)
    return payload


def evaluate_eod(
    session_date: str,
    now: datetime,
    source_db: Path = DEFAULT_SOURCE_DB,
    step9l_ledger_db: Path = DEFAULT_STEP9L_LEDGER_DB,
    ledger_db: Path = DEFAULT_LEDGER_DB,
    allow_early: bool = False,
    export_outputs_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    morning_batch, archetype_rows = _read_existing_morning(ledger_db, session_date)
    if not morning_batch or len(archetype_rows) != EXPECTED_UNIVERSE_SIZE:
        raise SourceDataNotReady(
            f"No complete sealed Step 9T prospective morning snapshot exists for {session_date}."
        )
    source_batch, _, decision_set_hash = _read_step9l_morning(session_date, step9l_ledger_db)
    if str(source_batch["batch_payload_hash"]) != str(
        morning_batch["source_step9l_batch_payload_hash"]
    ):
        raise ImmutableLedgerConflict("Step 9L morning batch changed after Step 9T seal.")
    if decision_set_hash != str(morning_batch["source_step9l_decision_set_hash"]):
        raise ImmutableLedgerConflict("Step 9L morning decisions changed after Step 9T seal.")
    if not allow_early:
        if session_date != now.date().isoformat():
            raise SourceDataNotReady("Step 9T EOD may only evaluate the current session.")
        if now.time().replace(tzinfo=None) < _clock_to_time(EOD_TIME):
            raise SourceDataNotReady(
                f"Step 9T EOD evaluation is not allowed before {EOD_TIME} Stockholm time."
            )
    prices, source_provenance = _load_prices_canonical(source_db, session_date)
    if str(prices["clock"].max()) < EOD_MINIMUM_LABEL:
        raise SourceDataNotReady(
            f"Step 9T source prices are incomplete before {EOD_MINIMUM_LABEL}."
        )
    price_hash = _eod_price_snapshot_hash(prices, session_date)
    outcomes = []
    for archetype_row in sorted(archetype_rows, key=lambda item: item["ticker"]):
        outcome = evaluate_ticker_outcome(
            archetype_row,
            prices[prices["ticker"].eq(str(archetype_row["ticker"]))],
        )
        outcomes.append(outcome)
    if len(outcomes) != EXPECTED_UNIVERSE_SIZE:
        raise SourceIntegrityError("Step 9T EOD did not preserve all 29 ticker outcomes.")
    outcome_set_hash = _payload_hash(
        [row["outcome_id"] for row in sorted(outcomes, key=lambda item: item["ticker"])]
    )
    existing_batch, existing_outcomes = _read_existing_outcomes(ledger_db, session_date)
    if existing_batch:
        if str(existing_batch["eod_price_snapshot_hash"]) != price_hash:
            raise ImmutableLedgerConflict("Step 9T EOD price snapshot changed on rerun.")
        existing_set_hash = _payload_hash(
            [row["outcome_id"] for row in sorted(existing_outcomes, key=lambda item: item["ticker"])]
        )
        if existing_set_hash != outcome_set_hash:
            raise ImmutableLedgerConflict("Step 9T prospective EOD outcomes changed on rerun.")
        if export_outputs_after:
            export_outputs(ledger_db)
        return pd.DataFrame([existing_batch]), pd.DataFrame(existing_outcomes), False

    outcome_batch_id = f"S9T-{session_date.replace('-', '')}-EOD"
    stored_outcomes = []
    for outcome in outcomes:
        row = {
            "outcome_batch_id": outcome_batch_id,
            "morning_batch_id": str(morning_batch["batch_id"]),
            **outcome,
        }
        row["row_payload_hash"] = _payload_hash(
            {key: value for key, value in row.items() if key != "row_payload_hash"}
        )
        stored_outcomes.append(row)
    directional = [
        row
        for row in stored_outcomes
        if row["outcome_status"] == "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"
    ]
    zero = [
        row
        for row in stored_outcomes
        if row["outcome_status"] == "NO_CLEAR_SETUP_ZERO_OUTCOME"
    ]
    incomplete = [
        row
        for row in stored_outcomes
        if row["outcome_status"]
        not in {"DIRECTIONAL_COUNTERFACTUAL_COMPLETE", "NO_CLEAR_SETUP_ZERO_OUTCOME"}
    ]
    net_pnl = float(
        sum(float(row["net_pnl_sek"]) for row in directional if row["net_pnl_sek"] is not None)
    )
    batch_payload = {
        "outcome_batch_id": outcome_batch_id,
        "morning_batch_id": morning_batch["batch_id"],
        "session_date": session_date,
        "code_version": CODE_VERSION,
        "eod_price_snapshot_hash": price_hash,
        "outcome_set_hash": outcome_set_hash,
        "directional_outcomes": len(directional),
        "zero_outcomes": len(zero),
        "incomplete_outcomes": len(incomplete),
        "net_standardized_directional_pnl_sek": net_pnl,
    }
    batch_row = {
        "outcome_batch_id": outcome_batch_id,
        "morning_batch_id": str(morning_batch["batch_id"]),
        "session_date": session_date,
        "created_at_stockholm": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "code_version": CODE_VERSION,
        "source_price_db": str(source_db),
        "source_duplicate_policy": SOURCE_DUPLICATE_POLICY,
        "source_max_datetime": str(source_provenance["source_max_datetime"]),
        "eod_price_snapshot_hash": price_hash,
        "eod_complete": 1,
        "ticker_outcome_rows": len(stored_outcomes),
        "directional_outcomes": len(directional),
        "zero_outcomes": len(zero),
        "incomplete_outcomes": len(incomplete),
        "net_standardized_directional_pnl_sek": net_pnl,
        "router_active": 0,
        "order_sent": 0,
        "outcome_payload_hash": _payload_hash(batch_payload),
    }
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(
            connection,
            "step9t_prospective_outcome_batches",
            "outcome_batch_id",
            "outcome_payload_hash",
            batch_row,
        )
        for row in stored_outcomes:
            _insert_immutable(
                connection,
                "step9t_prospective_ticker_outcomes",
                "outcome_id",
                "row_payload_hash",
                row,
            )
        connection.commit()
    if export_outputs_after:
        export_outputs(ledger_db)
    return pd.DataFrame([batch_row]), pd.DataFrame(stored_outcomes), inserted


def _read_table(connection: sqlite3.Connection, table: str) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {table}", connection)


def audit_ledger(ledger_db: Path = DEFAULT_LEDGER_DB) -> pd.DataFrame:
    if not ledger_db.is_file():
        raise FileNotFoundError(ledger_db)
    checks: list[dict[str, Any]] = []
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        batches = _read_table(connection, "step9t_prospective_batches")
        archetypes = _read_table(connection, "step9t_prospective_ticker_archetypes")
        outcome_batches = _read_table(connection, "step9t_prospective_outcome_batches")
        outcomes = _read_table(connection, "step9t_prospective_ticker_outcomes")
    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
    add(
        "router_inactive",
        all(
            frame.empty or int(pd.to_numeric(frame["router_active"], errors="coerce").fillna(0).max()) == 0
            for frame in [batches, archetypes, outcome_batches, outcomes]
        ),
        "All stored router_active values must be zero.",
    )
    add(
        "orders_not_sent",
        all(
            frame.empty or int(pd.to_numeric(frame["order_sent"], errors="coerce").fillna(0).max()) == 0
            for frame in [batches, archetypes, outcome_batches, outcomes]
        ),
        "All stored order_sent values must be zero.",
    )
    add(
        "one_batch_per_session",
        batches.empty or not batches["session_date"].duplicated().any(),
        f"Morning sessions={len(batches)}",
    )
    counts = archetypes.groupby("session_date").size() if not archetypes.empty else pd.Series(dtype=int)
    add(
        "all_morning_sessions_have_29_tickers",
        counts.empty or bool(counts.eq(EXPECTED_UNIVERSE_SIZE).all()),
        f"Ticker counts={counts.to_dict()}",
    )
    add(
        "morning_point_in_time",
        archetypes.empty
        or bool(
            archetypes["max_source_label_used"].fillna("").le(LATEST_MORNING_LABEL).all()
            and pd.to_numeric(archetypes["point_in_time_pass"], errors="coerce").eq(1).all()
        ),
        "No ticker assignment may use data later than 09:45.",
    )
    outcome_counts = outcomes.groupby("session_date").size() if not outcomes.empty else pd.Series(dtype=int)
    add(
        "all_eod_sessions_have_29_outcomes",
        outcome_counts.empty or bool(outcome_counts.eq(EXPECTED_UNIVERSE_SIZE).all()),
        f"Outcome counts={outcome_counts.to_dict()}",
    )
    add(
        "one_outcome_per_ticker_row",
        outcomes.empty or not outcomes["ticker_row_id"].duplicated().any(),
        f"Outcome rows={len(outcomes)}",
    )
    add(
        "frozen_source_policy",
        batches.empty or bool(batches["source_duplicate_policy"].eq(SOURCE_DUPLICATE_POLICY).all()),
        SOURCE_DUPLICATE_POLICY,
    )
    return pd.DataFrame(checks)


def export_outputs(
    ledger_db: Path = DEFAULT_LEDGER_DB,
    output_dir: Path = DEFAULT_EXPORT_DIR,
) -> None:
    if not ledger_db.is_file():
        raise FileNotFoundError(ledger_db)
    output_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ledger_db)) as connection:
        _ensure_schema(connection)
        batches = _read_table(connection, "step9t_prospective_batches")
        archetypes = _read_table(connection, "step9t_prospective_ticker_archetypes")
        outcome_batches = _read_table(connection, "step9t_prospective_outcome_batches")
        outcomes = _read_table(connection, "step9t_prospective_ticker_outcomes")
    batches.to_csv(output_dir / BATCH_EXPORT, index=False)
    archetypes.to_csv(output_dir / ARCHETYPE_EXPORT, index=False)
    outcome_batches.to_csv(output_dir / OUTCOME_BATCH_EXPORT, index=False)
    outcomes.to_csv(output_dir / OUTCOME_EXPORT, index=False)
    audit = audit_ledger(ledger_db)
    audit.to_csv(output_dir / AUDIT_EXPORT, index=False)
    summary = pd.DataFrame(
        [
            {
                "experiment_id": EXPERIMENT_ID,
                "research_status": RESEARCH_STATUS,
                "morning_sessions": int(len(batches)),
                "recognized_regimes": int(batches["source_regime"].nunique()) if not batches.empty else 0,
                "transition_states": int(batches["transition_state"].nunique()) if not batches.empty else 0,
                "ticker_archetype_rows": int(len(archetypes)),
                "eod_sessions": int(len(outcome_batches)),
                "ticker_outcome_rows": int(len(outcomes)),
                "directional_outcomes": int(
                    outcomes["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE").sum()
                )
                if not outcomes.empty
                else 0,
                "net_standardized_directional_pnl_sek": float(
                    pd.to_numeric(
                        outcomes.loc[
                            outcomes["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE"),
                            "net_pnl_sek",
                        ],
                        errors="coerce",
                    )
                    .fillna(0.0)
                    .sum()
                )
                if not outcomes.empty
                else 0.0,
                "router_active": False,
                "orders_sent": False,
                "selection_active": False,
                "audit_pass": bool(audit["passed"].all()),
            }
        ]
    )
    summary.to_csv(output_dir / SUMMARY_EXPORT, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 9T prospective immutable transition/archetype observer."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ["morning", "eod"]:
        sub = subparsers.add_parser(command)
        sub.add_argument("--date", default=None)
        sub.add_argument("--as-of", default=None)
        sub.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
        sub.add_argument("--step9l-ledger-db", type=Path, default=DEFAULT_STEP9L_LEDGER_DB)
        sub.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
        if command == "morning":
            sub.add_argument("--allow-late-reconstruction", action="store_true")
        else:
            sub.add_argument("--allow-early-evaluation", action="store_true")
    export = subparsers.add_parser("export")
    export.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    export.add_argument("--output-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "export":
        export_outputs(args.ledger_db, args.output_dir)
        print("Step 9T prospective immutable ledger exports refreshed.")
        return
    if args.command == "audit":
        audit = audit_ledger(args.ledger_db)
        print(audit.to_string(index=False))
        if not bool(audit["passed"].all()):
            raise SystemExit(1)
        return

    now = _parse_stockholm_datetime(args.as_of)
    target = _target_date(args.date, now)
    if args.command == "morning":
        print("\n=== STEP 9T PROSPECTIVE TRANSITION/ARCHETYPE SNAPSHOT ===")
        print(f"Session date       : {target}")
        print(f"As-of Stockholm    : {now:%Y-%m-%d %H:%M:%S %Z}")
        batches, archetypes, inserted = seal_morning_snapshot(
            session_date=target,
            now=now,
            source_db=args.source_db,
            step9l_ledger_db=args.step9l_ledger_db,
            ledger_db=args.ledger_db,
            allow_late=args.allow_late_reconstruction,
            simulated_clock=bool(args.as_of),
            export_outputs_after=True,
        )
        batch = batches.iloc[0]
        print(
            "Ledger action      : "
            + (
                "SEALED_NEW_TRANSITION_BATCH"
                if inserted
                else "EXISTING_IDENTICAL_TRANSITION_BATCH_RETURNED"
            )
        )
        print(f"Prospective status : {batch['prospective_status']}")
        print(f"Opening regime     : {batch['source_regime']}")
        print(f"Transition state   : {batch['transition_state']}")
        print(
            f"Ticker rows        : {len(archetypes)} / "
            f"{int(batch['valid_ticker_count'])} complete"
        )
        print(f"Latest source used : {LATEST_MORNING_LABEL}")
        print("SELECTION ACTIVE   : FALSE")
        print("ROUTER ACTIVE      : FALSE")
        print("NO ORDER WAS SENT")
        return

    print("\n=== STEP 9T PROSPECTIVE END-OF-DAY OUTCOMES ===")
    print(f"Session date       : {target}")
    print(f"As-of Stockholm    : {now:%Y-%m-%d %H:%M:%S %Z}")
    batches, outcomes, inserted = evaluate_eod(
        session_date=target,
        now=now,
        source_db=args.source_db,
        step9l_ledger_db=args.step9l_ledger_db,
        ledger_db=args.ledger_db,
        allow_early=args.allow_early_evaluation,
        export_outputs_after=True,
    )
    batch = batches.iloc[0]
    print(
        "Ledger action      : "
        + (
            "SEALED_NEW_OUTCOME_BATCH"
            if inserted
            else "EXISTING_IDENTICAL_OUTCOME_BATCH_RETURNED"
        )
    )
    print(f"Ticker outcomes    : {len(outcomes)}")
    print(f"Directional        : {int(batch['directional_outcomes'])}")
    print(f"Zero setup         : {int(batch['zero_outcomes'])}")
    print(f"Incomplete         : {int(batch['incomplete_outcomes'])}")
    print(
        "Net standardized  : "
        f"{float(batch['net_standardized_directional_pnl_sek']):.6f} SEK"
    )
    print("SELECTION ACTIVE   : FALSE")
    print("ROUTER ACTIVE      : FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
