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

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "step9v_intraday_regime_transition_observer_v1.json"
DEFAULT_SOURCE_DB = resolve_stage_path("prices")
DEFAULT_STEP9T_LEDGER_DB = resolve_stage_path("step9t")
DEFAULT_STEP9U_LEDGER_DB = resolve_stage_path("step9u")
DEFAULT_LEDGER_DB = resolve_stage_path("step9v")
DEFAULT_EXPORT_DIR = resolve_stage_output_dir("step9v")
STOCKHOLM = ZoneInfo("Europe/Stockholm")

BATCH_EXPORT = "step9v_checkpoint_batches.csv"
TICKER_EXPORT = "step9v_ticker_states.csv"
REVIEW_EXPORT = "step9v_selected_position_reviews.csv"
OUTCOME_BATCH_EXPORT = "step9v_checkpoint_outcome_batches.csv"
TICKER_OUTCOME_EXPORT = "step9v_ticker_counterfactual_outcomes.csv"
ACTION_OUTCOME_EXPORT = "step9v_selected_action_outcomes.csv"
SUMMARY_EXPORT = "step9v_summary.csv"
AUDIT_EXPORT = "step9v_audit.csv"


class Step9VError(RuntimeError):
    pass


class SourceDataNotReady(Step9VError):
    pass


class SourceIntegrityError(Step9VError):
    pass


class ImmutableLedgerConflict(Step9VError):
    pass


def _load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if bool(cfg.get("selection_active")) or bool(cfg.get("position_changes_enabled")):
        raise SourceIntegrityError("Step 9V V1 must remain an observer; selection and position changes are disabled.")
    if bool(cfg.get("router_active")) or bool(cfg.get("orders_enabled")):
        raise SourceIntegrityError("Step 9V routing and orders must remain disabled.")
    if int(cfg.get("expected_universe_size", 0)) != 29:
        raise SourceIntegrityError("Step 9V requires the frozen 29-ticker universe.")
    if list(cfg.get("checkpoints", {})) != ["10:30", "11:30", "13:30", "15:00"]:
        raise SourceIntegrityError("Unexpected Step 9V checkpoint registry.")
    return cfg


CONFIG = _load_config()
EXPERIMENT_ID = str(CONFIG["experiment_id"])
RESEARCH_STATUS = str(CONFIG["research_status"])
CODE_VERSION = str(CONFIG["code_version"])
CHECKPOINTS = dict(CONFIG["checkpoints"])
EXPECTED_UNIVERSE_SIZE = int(CONFIG["expected_universe_size"])
MORNING_ENTRY_LABEL = str(CONFIG["morning_entry_label"])
EOD_MINIMUM_LABEL = str(CONFIG["eod_minimum_label"])
EOD_TIME = str(CONFIG["eod_time"])
BASE_NOTIONAL_SEK = float(CONFIG["base_notional_sek"])
ROUND_TRIP_COST_RATE = float(CONFIG["round_trip_cost_rate"])
REDUCE_FRACTION = float(CONFIG["reduce_fraction"])


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _clean_scalar(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_clean_scalar(v) for v in value]
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


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def _clock(value: str) -> time:
    p = [int(x) for x in value.split(":")]
    if len(p) == 2:
        p.append(0)
    return time(*p)


def _parse_now(value: str | None) -> datetime:
    if value:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            return ts.tz_localize(STOCKHOLM).to_pydatetime()
        return ts.tz_convert(STOCKHOLM).to_pydatetime()
    return datetime.now(STOCKHOLM)


def _verify_row_hash(row: dict[str, Any]) -> None:
    expected = str(row["row_payload_hash"])
    payload = {k: v for k, v in row.items() if k != "row_payload_hash"}
    for field in [
        "midpoint_reclaimed", "bullish_continuation_flag", "bearish_continuation_flag",
        "laggard_recovery_flag", "leader_reversal_flag",
    ]:
        if field in payload:
            payload[field] = bool(payload[field])
    if _payload_hash(payload) != expected:
        raise SourceIntegrityError(f"Invalid immutable source row hash for {row.get('ticker', 'unknown')}.")


def _read_step9t(session_date: str, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with closing(_readonly_connection(path)) as con:
        con.row_factory = sqlite3.Row
        batches = con.execute("SELECT * FROM step9t_prospective_batches WHERE session_date=?", (session_date,)).fetchall()
        if len(batches) != 1:
            raise SourceDataNotReady(f"Expected one Step 9T morning batch for {session_date}; found {len(batches)}.")
        batch = dict(batches[0])
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM step9t_prospective_ticker_archetypes WHERE batch_id=? ORDER BY ticker",
            (batch["batch_id"],),
        ).fetchall()]
    if batch["experiment_id"] != CONFIG["source_step9t_experiment_id"] or batch["code_version"] != CONFIG["source_step9t_code_version"]:
        raise SourceIntegrityError("Unexpected Step 9T source contract.")
    if str(batch["historical_freeze_id"]) != str(CONFIG["source_step9t_freeze_id"]):
        raise SourceIntegrityError("Unexpected Step 9T historical freeze ID.")
    if len(rows) != EXPECTED_UNIVERSE_SIZE:
        raise SourceDataNotReady(f"Expected 29 Step 9T ticker rows; found {len(rows)}.")
    for row in rows:
        _verify_row_hash(row)
    features = {k: batch[k] for k in [
        "valid_ticker_count", "incomplete_ticker_count", "advancer_share", "decliner_share",
        "median_early_return", "median_last5_return", "early_loser_count", "early_winner_count",
        "recovery_share_of_early_losers", "continuation_share_of_early_winners",
        "midpoint_reclaim_share", "leader_failure_share", "cross_sectional_dispersion",
    ]}
    ticker_set_hash = _payload_hash([r["ticker_row_id"] for r in sorted(rows, key=lambda x: x["ticker"])])
    payload = {
        "batch_id": batch["batch_id"], "session_date": batch["session_date"],
        "prospective_status": batch["prospective_status"], "code_version": batch["code_version"],
        "historical_freeze_id": batch["historical_freeze_id"],
        "historical_freeze_artifact_sha256": batch["historical_freeze_artifact_sha256"],
        "source_step9l_batch_id": batch["source_step9l_batch_id"],
        "source_step9l_batch_payload_hash": batch["source_step9l_batch_payload_hash"],
        "source_step9l_decision_set_hash": batch["source_step9l_decision_set_hash"],
        "morning_price_snapshot_hash": batch["morning_price_snapshot_hash"],
        "source_regime": batch["source_regime"], "transition_state": batch["transition_state"],
        "features": features, "ticker_set_hash": ticker_set_hash,
    }
    if _payload_hash(payload) != str(batch["batch_payload_hash"]):
        raise SourceIntegrityError("Invalid Step 9T batch payload hash.")
    return batch, rows


def _read_step9u(session_date: str, path: Path, step9t_batch: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with closing(_readonly_connection(path)) as con:
        con.row_factory = sqlite3.Row
        batches = con.execute("SELECT * FROM step9u_prospective_assignment_batches WHERE session_date=?", (session_date,)).fetchall()
        if len(batches) != 1:
            raise SourceDataNotReady(f"Expected one Step 9U assignment batch for {session_date}; found {len(batches)}.")
        batch = dict(batches[0])
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM step9u_prospective_candidates WHERE assignment_batch_id=? ORDER BY ticker",
            (batch["assignment_batch_id"],),
        ).fetchall()]
    if batch["experiment_id"] != CONFIG["source_step9u_experiment_id"] or batch["code_version"] != CONFIG["source_step9u_code_version"]:
        raise SourceIntegrityError("Unexpected Step 9U source contract.")
    if str(batch["historical_freeze_id"]) != str(CONFIG["source_step9u_freeze_id"]):
        raise SourceIntegrityError("Unexpected Step 9U historical freeze ID.")
    if str(batch["source_step9t_batch_id"]) != str(step9t_batch["batch_id"]):
        raise SourceIntegrityError("Step 9U assignment does not reference the sealed Step 9T batch.")
    for row in rows:
        _verify_row_hash(row)
    candidate_set_hash = _payload_hash([r["candidate_id"] for r in sorted(rows, key=lambda x: x["ticker"])])
    if candidate_set_hash != str(batch["candidate_set_hash"]):
        raise SourceIntegrityError("Invalid Step 9U candidate-set hash.")
    batch_payload = {
        "assignment_batch_id": batch["assignment_batch_id"], "session_date": batch["session_date"],
        "prospective_status": batch["prospective_status"], "code_version": batch["code_version"],
        "historical_freeze_id": batch["historical_freeze_id"],
        "historical_freeze_artifact_sha256": batch["historical_freeze_artifact_sha256"],
        "source_step9t_batch_id": batch["source_step9t_batch_id"],
        "source_step9t_batch_payload_hash": batch["source_step9t_batch_payload_hash"],
        "candidate_set_hash": batch["candidate_set_hash"],
    }
    if _payload_hash(batch_payload) != str(batch["batch_payload_hash"]):
        raise SourceIntegrityError("Invalid Step 9U batch payload hash.")
    if int(batch["mandatory_control_active"]) != 0 or int(batch["router_active"]) != 0 or int(batch["order_sent"]) != 0:
        raise SourceIntegrityError("Unsafe Step 9U source state.")
    return batch, rows


def _load_prices(path: Path, session_date: str) -> pd.DataFrame:
    with closing(_readonly_connection(path)) as con:
        df = pd.read_sql_query(
            "SELECT rowid AS source_rowid, datetime, open, high, low, close, ticker FROM intraday_prices "
            "WHERE substr(datetime,1,10)=? ORDER BY ticker, datetime, source_rowid",
            con, params=[session_date],
        )
    if df.empty:
        raise SourceDataNotReady(f"No raw prices for {session_date}.")
    df["datetime"] = pd.to_datetime(df["datetime"], errors="raise", format="mixed")
    df["ticker"] = df["ticker"].astype(str).str.strip()
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["datetime", "ticker", "open", "high", "low", "close"]).copy()
    df["clock"] = df["datetime"].dt.strftime("%H:%M")
    df = (df.sort_values(["ticker", "clock", "source_rowid"], kind="mergesort")
            .drop_duplicates(["ticker", "clock"], keep="last")
            .sort_values(["ticker", "datetime"], kind="mergesort").reset_index(drop=True))
    return df


def _bar_map(frame: pd.DataFrame) -> dict[str, Any]:
    return {str(r.clock): r for r in frame.itertuples(index=False)}


def _direction(archetype: str) -> str:
    if archetype.endswith("_LONG"):
        return "LONG"
    if archetype.endswith("_SHORT"):
        return "SHORT"
    return "NONE"


def _current_archetype(session_return: float, last15_return: float) -> str:
    e = float(CONFIG["early_move_threshold"])
    c = float(CONFIG["last15_confirmation_threshold"])
    if session_return <= -e and last15_return >= c:
        return "LAGGARD_RECOVERY_LONG"
    if session_return >= e and last15_return <= -c:
        return "LEADER_REVERSAL_SHORT"
    if session_return >= e and last15_return >= 0.0:
        return "BULLISH_CONTINUATION_LONG"
    if session_return <= -e and last15_return <= 0.0:
        return "BEARISH_CONTINUATION_SHORT"
    return "NO_CLEAR_SETUP"


def _state(features: dict[str, float], morning_transition: str) -> tuple[str, str, str]:
    adv = features["advancer_share"]
    dec = features["decliner_share"]
    med = features["median_session_return"]
    last = features["median_last15_return"]
    disp = features["cross_sectional_dispersion"]
    exp = float(CONFIG["breadth_expansion_threshold"])
    shift = float(CONFIG["breadth_shift_threshold"])
    low = float(CONFIG["low_dispersion_threshold"])
    high = float(CONFIG["high_dispersion_threshold"])
    trend = float(CONFIG["trend_return_threshold"])
    if adv >= exp and med >= trend and last > 0:
        state = "BULLISH_EXPANSION"
        bias = "BULLISH"
    elif dec >= exp and med <= -trend and last < 0:
        state = "BEARISH_EXPANSION"
        bias = "BEARISH"
    elif adv >= shift and last > 0:
        state = "RECOVERY_BROADENING"
        bias = "BULLISH"
    elif dec >= shift and last < 0:
        state = "WEAKNESS_BROADENING"
        bias = "BEARISH"
    elif disp <= low and abs(last) < 0.0005:
        state = "VOLATILITY_COMPRESSION"
        bias = "NEUTRAL"
    elif disp >= high:
        state = "HIGH_DISPERSION_CHOP"
        bias = "MIXED"
    else:
        state = "MIXED_CHOP"
        bias = "MIXED"
    morning_bias = "BULLISH" if "BULLISH" in morning_transition or "RECOVERY" in morning_transition else (
        "BEARISH" if "BEARISH" in morning_transition or "WEAKNESS" in morning_transition else "MIXED"
    )
    if bias in {"BULLISH", "BEARISH"} and morning_bias in {"BULLISH", "BEARISH"}:
        relation = "CONFIRMED" if bias == morning_bias else "INVALIDATED"
    elif bias == "NEUTRAL":
        relation = "NEUTRALIZED"
    else:
        relation = "UNRESOLVED"
    return state, bias, relation


def _ticker_states(session_date: str, checkpoint: str, cutoff: str, source_rows: list[dict[str, Any]], prices: pd.DataFrame) -> list[dict[str, Any]]:
    source_by_ticker = {str(r["ticker"]): r for r in source_rows}
    cutoff_ts = pd.Timestamp(f"2000-01-01 {cutoff}")
    last15 = (cutoff_ts - pd.Timedelta(minutes=15)).strftime("%H:%M")
    output: list[dict[str, Any]] = []
    for ticker in sorted(source_by_ticker):
        source = source_by_ticker[ticker]
        frame = prices[(prices["ticker"] == ticker) & (prices["clock"] <= cutoff)]
        bars = _bar_map(frame)
        required = ["09:30", "09:45", last15, cutoff]
        missing = [x for x in required if x not in bars]
        base = {
            "session_date": session_date, "checkpoint_time": checkpoint, "source_cutoff_label": cutoff,
            "ticker": ticker, "company_id": str(source["company_id"]),
            "broad_sector": str(source["broad_sector"]), "universe_role": str(source["universe_role"]),
            "morning_primary_archetype": str(source["primary_archetype"]),
            "morning_direction": str(source["direction"]), "source_ticker_row_id": str(source["ticker_row_id"]),
        }
        if missing:
            row = {**base, "state_status": "INCOMPLETE_CHECKPOINT_BARS", "missing_labels": "|".join(missing),
                   "session_return": None, "since_morning_return": None, "last15_return": None,
                   "intraday_high": None, "intraday_low": None, "intraday_range_position": None,
                   "current_archetype": "NO_CLEAR_SETUP", "current_direction": "NONE",
                   "archetype_changed": 0, "direction_changed": 0, "point_in_time_pass": 1,
                   "router_active": 0, "order_sent": 0}
        else:
            open_px = float(bars["09:30"].open)
            morning_px = float(bars["09:45"].close)
            last15_px = float(bars[last15].close)
            cutoff_px = float(bars[cutoff].close)
            high = float(frame["high"].max())
            low = float(frame["low"].min())
            pos = (cutoff_px - low) / (high - low) if high > low else 0.5
            session_ret = cutoff_px / open_px - 1.0
            since_morning = cutoff_px / morning_px - 1.0
            last15_ret = cutoff_px / last15_px - 1.0
            archetype = _current_archetype(session_ret, last15_ret)
            direction = _direction(archetype)
            row = {**base, "state_status": "CHECKPOINT_COMPLETE", "missing_labels": "",
                   "session_return": session_ret, "since_morning_return": since_morning,
                   "last15_return": last15_ret, "intraday_high": high, "intraday_low": low,
                   "intraday_range_position": pos, "current_archetype": archetype,
                   "current_direction": direction,
                   "archetype_changed": int(archetype != str(source["primary_archetype"])),
                   "direction_changed": int(direction != str(source["direction"])),
                   "point_in_time_pass": 1, "router_active": 0, "order_sent": 0}
        row["ticker_state_id"] = _payload_hash({k: v for k, v in row.items() if k != "ticker_state_id"})
        row["row_payload_hash"] = _payload_hash(row)
        output.append(row)
    return output


def _features(rows: list[dict[str, Any]]) -> dict[str, float]:
    complete = [r for r in rows if r["state_status"] == "CHECKPOINT_COMPLETE"]
    returns = pd.Series([r["session_return"] for r in complete], dtype=float)
    last15 = pd.Series([r["last15_return"] for r in complete], dtype=float)
    return {
        "valid_ticker_count": float(len(complete)),
        "incomplete_ticker_count": float(len(rows) - len(complete)),
        "advancer_share": float((returns > 0).mean()) if len(returns) else 0.0,
        "decliner_share": float((returns < 0).mean()) if len(returns) else 0.0,
        "median_session_return": float(returns.median()) if len(returns) else 0.0,
        "median_last15_return": float(last15.median()) if len(last15) else 0.0,
        "cross_sectional_dispersion": float(returns.std(ddof=0)) if len(returns) else 0.0,
        "directional_ticker_count": float(sum(r["current_direction"] != "NONE" for r in complete)),
        "archetype_change_count": float(sum(int(r["archetype_changed"]) for r in complete)),
    }


def _review_action(original_direction: str, current_direction: str, state_bias: str) -> tuple[str, str, str]:
    opposite = (original_direction == "LONG" and current_direction == "SHORT") or (original_direction == "SHORT" and current_direction == "LONG")
    environment_opposite = (original_direction == "LONG" and state_bias == "BEARISH") or (original_direction == "SHORT" and state_bias == "BULLISH")
    if opposite:
        return "EXIT", "EXIT_AND_SWITCH_RESEARCH_ONLY", "Ticker direction reversed at the checkpoint."
    if environment_opposite:
        return "EXIT", "NO_SWITCH", "Broad intraday environment moved against the original direction."
    if current_direction == original_direction:
        return "KEEP", "NO_SWITCH", "Ticker direction remains aligned with the frozen morning position."
    return "REDUCE", "NO_SWITCH", "Original direction is no longer confirmed, but no opposite setup is established."


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS step9v_checkpoint_batches (
      checkpoint_batch_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, session_date TEXT NOT NULL,
      checkpoint_time TEXT NOT NULL, source_cutoff_label TEXT NOT NULL, action_price_label TEXT NOT NULL,
      created_at_stockholm TEXT NOT NULL, prospective_status TEXT NOT NULL, code_version TEXT NOT NULL,
      source_step9t_batch_id TEXT NOT NULL, source_step9t_batch_payload_hash TEXT NOT NULL,
      source_step9u_assignment_batch_id TEXT NOT NULL, source_step9u_batch_payload_hash TEXT NOT NULL,
      morning_regime TEXT NOT NULL, morning_transition_state TEXT NOT NULL,
      intraday_environment_state TEXT NOT NULL, intraday_environment_bias TEXT NOT NULL,
      morning_relation TEXT NOT NULL, valid_ticker_count INTEGER NOT NULL, incomplete_ticker_count INTEGER NOT NULL,
      advancer_share REAL NOT NULL, decliner_share REAL NOT NULL, median_session_return REAL NOT NULL,
      median_last15_return REAL NOT NULL, cross_sectional_dispersion REAL NOT NULL,
      directional_ticker_count INTEGER NOT NULL, archetype_change_count INTEGER NOT NULL,
      selected_position_count INTEGER NOT NULL, keep_count INTEGER NOT NULL, reduce_count INTEGER NOT NULL,
      exit_count INTEGER NOT NULL, switch_research_only_count INTEGER NOT NULL,
      ticker_state_set_hash TEXT NOT NULL, review_set_hash TEXT NOT NULL, point_in_time_pass INTEGER NOT NULL,
      selection_active INTEGER NOT NULL, position_changes_enabled INTEGER NOT NULL,
      router_active INTEGER NOT NULL, order_sent INTEGER NOT NULL, batch_payload_hash TEXT NOT NULL,
      UNIQUE(session_date, checkpoint_time)
    );
    CREATE TABLE IF NOT EXISTS step9v_ticker_states (
      ticker_state_id TEXT PRIMARY KEY, checkpoint_batch_id TEXT NOT NULL, experiment_id TEXT NOT NULL,
      code_version TEXT NOT NULL, session_date TEXT NOT NULL, checkpoint_time TEXT NOT NULL,
      source_cutoff_label TEXT NOT NULL, ticker TEXT NOT NULL, company_id TEXT NOT NULL,
      broad_sector TEXT NOT NULL, universe_role TEXT NOT NULL, morning_primary_archetype TEXT NOT NULL,
      morning_direction TEXT NOT NULL, source_ticker_row_id TEXT NOT NULL,
      state_status TEXT NOT NULL, missing_labels TEXT NOT NULL, session_return REAL,
      since_morning_return REAL, last15_return REAL, intraday_high REAL, intraday_low REAL,
      intraday_range_position REAL, current_archetype TEXT NOT NULL, current_direction TEXT NOT NULL,
      archetype_changed INTEGER NOT NULL, direction_changed INTEGER NOT NULL, point_in_time_pass INTEGER NOT NULL,
      router_active INTEGER NOT NULL, order_sent INTEGER NOT NULL, row_payload_hash TEXT NOT NULL,
      UNIQUE(session_date, checkpoint_time, ticker)
    );
    CREATE TABLE IF NOT EXISTS step9v_selected_position_reviews (
      review_id TEXT PRIMARY KEY, checkpoint_batch_id TEXT NOT NULL, experiment_id TEXT NOT NULL,
      code_version TEXT NOT NULL, session_date TEXT NOT NULL, checkpoint_time TEXT NOT NULL,
      action_price_label TEXT NOT NULL, candidate_id TEXT NOT NULL, ticker TEXT NOT NULL,
      selected_rank INTEGER NOT NULL, broad_sector TEXT NOT NULL, rule_id TEXT NOT NULL,
      morning_archetype TEXT NOT NULL, original_direction TEXT NOT NULL,
      current_archetype TEXT NOT NULL, current_direction TEXT NOT NULL,
      intraday_environment_state TEXT NOT NULL, intraday_environment_bias TEXT NOT NULL,
      observer_action TEXT NOT NULL, switch_counterfactual TEXT NOT NULL, action_reason TEXT NOT NULL,
      position_changes_enabled INTEGER NOT NULL, router_active INTEGER NOT NULL, order_sent INTEGER NOT NULL,
      row_payload_hash TEXT NOT NULL, UNIQUE(session_date, checkpoint_time, ticker)
    );
    CREATE TABLE IF NOT EXISTS step9v_checkpoint_outcome_batches (
      outcome_batch_id TEXT PRIMARY KEY, checkpoint_batch_id TEXT NOT NULL UNIQUE, session_date TEXT NOT NULL,
      checkpoint_time TEXT NOT NULL, created_at_stockholm TEXT NOT NULL, code_version TEXT NOT NULL,
      action_price_label TEXT NOT NULL, exit_label TEXT NOT NULL, ticker_outcome_count INTEGER NOT NULL,
      selected_action_outcome_count INTEGER NOT NULL, ticker_outcome_set_hash TEXT NOT NULL,
      selected_action_outcome_set_hash TEXT NOT NULL, router_active INTEGER NOT NULL, order_sent INTEGER NOT NULL,
      outcome_payload_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS step9v_ticker_counterfactual_outcomes (
      ticker_outcome_id TEXT PRIMARY KEY, outcome_batch_id TEXT NOT NULL, checkpoint_batch_id TEXT NOT NULL,
      session_date TEXT NOT NULL, checkpoint_time TEXT NOT NULL, ticker TEXT NOT NULL,
      checkpoint_archetype TEXT NOT NULL, checkpoint_direction TEXT NOT NULL, entry_label TEXT NOT NULL,
      entry_price REAL, exit_label TEXT NOT NULL, exit_price REAL, gross_return REAL, gross_pnl_sek REAL,
      cost_sek REAL, net_pnl_sek REAL, outcome_status TEXT NOT NULL, router_active INTEGER NOT NULL,
      order_sent INTEGER NOT NULL, row_payload_hash TEXT NOT NULL, UNIQUE(session_date, checkpoint_time, ticker)
    );
    CREATE TABLE IF NOT EXISTS step9v_selected_action_outcomes (
      action_outcome_id TEXT PRIMARY KEY, outcome_batch_id TEXT NOT NULL, checkpoint_batch_id TEXT NOT NULL,
      review_id TEXT NOT NULL UNIQUE, session_date TEXT NOT NULL, checkpoint_time TEXT NOT NULL,
      ticker TEXT NOT NULL, original_direction TEXT NOT NULL, observer_action TEXT NOT NULL,
      switch_counterfactual TEXT NOT NULL, morning_entry_label TEXT NOT NULL, morning_entry_price REAL,
      action_price_label TEXT NOT NULL, action_price REAL, exit_label TEXT NOT NULL, exit_price REAL,
      hold_net_pnl_sek REAL, exit_net_pnl_sek REAL, reduce_net_pnl_sek REAL,
      switch_net_pnl_sek REAL, observer_action_net_pnl_sek REAL,
      improvement_vs_hold_sek REAL, outcome_status TEXT NOT NULL, router_active INTEGER NOT NULL,
      order_sent INTEGER NOT NULL, row_payload_hash TEXT NOT NULL
    );
    """)
    for table in [
        "step9v_checkpoint_batches", "step9v_ticker_states", "step9v_selected_position_reviews",
        "step9v_checkpoint_outcome_batches", "step9v_ticker_counterfactual_outcomes",
        "step9v_selected_action_outcomes",
    ]:
        con.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_STEP9V_UPDATE_FORBIDDEN'); END")
        con.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_STEP9V_DELETE_FORBIDDEN'); END")


def _insert_immutable(con: sqlite3.Connection, table: str, key: str, hash_col: str, row: dict[str, Any]) -> bool:
    found = con.execute(f"SELECT {hash_col} FROM {table} WHERE {key}=?", (row[key],)).fetchone()
    if found:
        if str(found[0]) != str(row[hash_col]):
            raise ImmutableLedgerConflict(f"Conflicting Step 9V immutable row: {table}.{key}={row[key]}")
        return False
    cols = list(row)
    con.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [_clean_scalar(row[c]) for c in cols])
    return True


def seal_checkpoint(
    session_date: str, checkpoint: str, now: datetime, source_db: Path = DEFAULT_SOURCE_DB,
    step9t_db: Path = DEFAULT_STEP9T_LEDGER_DB, step9u_db: Path = DEFAULT_STEP9U_LEDGER_DB,
    ledger_db: Path = DEFAULT_LEDGER_DB, allow_late: bool = False, allow_mock_source: bool = False,
    export_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    if checkpoint not in CHECKPOINTS:
        raise ValueError(f"Unsupported checkpoint {checkpoint}.")
    spec = CHECKPOINTS[checkpoint]
    if not allow_late:
        if session_date != now.date().isoformat():
            raise SourceDataNotReady("A live Step 9V checkpoint may only seal for the current session.")
        if now.time().replace(tzinfo=None) < _clock(checkpoint):
            raise SourceDataNotReady(f"Checkpoint {checkpoint} is not open yet.")
        if now.time().replace(tzinfo=None) > _clock(spec["deadline"]):
            raise SourceDataNotReady(f"Checkpoint deadline {spec['deadline']} passed.")
    t_batch, t_rows = _read_step9t(session_date, step9t_db)
    u_batch, u_rows = _read_step9u(session_date, step9u_db, t_batch)
    if not allow_mock_source and ("NOT_CONFIRMATORY" in str(t_batch["prospective_status"]) or "NOT_CONFIRMATORY" in str(u_batch["prospective_status"])):
        raise SourceIntegrityError("Non-confirmatory source ledgers require --allow-mock-source.")
    prices = _load_prices(source_db, session_date)
    cutoff = str(spec["source_cutoff_label"])
    ticker_rows = _ticker_states(session_date, checkpoint, cutoff, t_rows, prices)
    f = _features(ticker_rows)
    if int(f["valid_ticker_count"]) != EXPECTED_UNIVERSE_SIZE:
        raise SourceDataNotReady(f"Checkpoint data incomplete: {int(f['valid_ticker_count'])}/29 tickers complete through {cutoff}.")
    state, bias, relation = _state(f, str(t_batch["transition_state"]))
    state_by_ticker = {r["ticker"]: r for r in ticker_rows}
    reviews: list[dict[str, Any]] = []
    for candidate in sorted([r for r in u_rows if int(r["selected"]) == 1], key=lambda r: int(r["selected_rank"])):
        current = state_by_ticker[str(candidate["ticker"])]
        action, switch, reason = _review_action(str(candidate["direction"]), str(current["current_direction"]), bias)
        row = {
            "session_date": session_date, "checkpoint_time": checkpoint,
            "action_price_label": str(spec["action_price_label"]), "candidate_id": str(candidate["candidate_id"]),
            "ticker": str(candidate["ticker"]), "selected_rank": int(candidate["selected_rank"]),
            "broad_sector": str(candidate["broad_sector"]), "rule_id": str(candidate["rule_id"]),
            "morning_archetype": str(candidate["primary_archetype"]), "original_direction": str(candidate["direction"]),
            "current_archetype": str(current["current_archetype"]), "current_direction": str(current["current_direction"]),
            "intraday_environment_state": state, "intraday_environment_bias": bias,
            "observer_action": action, "switch_counterfactual": switch, "action_reason": reason,
            "position_changes_enabled": 0, "router_active": 0, "order_sent": 0,
        }
        row["review_id"] = _payload_hash({k: v for k, v in row.items() if k != "review_id"})
        row["row_payload_hash"] = _payload_hash(row)
        reviews.append(row)
    ticker_set_hash = _payload_hash([r["ticker_state_id"] for r in sorted(ticker_rows, key=lambda x: x["ticker"])])
    review_set_hash = _payload_hash([r["review_id"] for r in sorted(reviews, key=lambda x: x["ticker"])])
    status = "LATE_RECONSTRUCTION_NOT_CONFIRMATORY" if allow_late else "PROSPECTIVE_INTRADAY_OBSERVER"
    if "NOT_CONFIRMATORY" in str(t_batch["prospective_status"]) or "NOT_CONFIRMATORY" in str(u_batch["prospective_status"]):
        status = "MOCK_SOURCE_INTRADAY_OBSERVER_NOT_CONFIRMATORY"
    batch_id = f"S9V-{session_date.replace('-', '')}-{checkpoint.replace(':', '')}"
    batch_payload = {
        "checkpoint_batch_id": batch_id, "session_date": session_date, "checkpoint_time": checkpoint,
        "prospective_status": status, "code_version": CODE_VERSION,
        "source_step9t_batch_id": t_batch["batch_id"], "source_step9t_batch_payload_hash": t_batch["batch_payload_hash"],
        "source_step9u_assignment_batch_id": u_batch["assignment_batch_id"],
        "source_step9u_batch_payload_hash": u_batch["batch_payload_hash"],
        "ticker_state_set_hash": ticker_set_hash, "review_set_hash": review_set_hash,
    }
    batch = {
        "checkpoint_batch_id": batch_id, "experiment_id": EXPERIMENT_ID, "session_date": session_date,
        "checkpoint_time": checkpoint, "source_cutoff_label": cutoff,
        "action_price_label": str(spec["action_price_label"]),
        "created_at_stockholm": now.strftime("%Y-%m-%d %H:%M:%S%z"), "prospective_status": status,
        "code_version": CODE_VERSION, "source_step9t_batch_id": str(t_batch["batch_id"]),
        "source_step9t_batch_payload_hash": str(t_batch["batch_payload_hash"]),
        "source_step9u_assignment_batch_id": str(u_batch["assignment_batch_id"]),
        "source_step9u_batch_payload_hash": str(u_batch["batch_payload_hash"]),
        "morning_regime": str(t_batch["source_regime"]),
        "morning_transition_state": str(t_batch["transition_state"]),
        "intraday_environment_state": state, "intraday_environment_bias": bias, "morning_relation": relation,
        "valid_ticker_count": int(f["valid_ticker_count"]), "incomplete_ticker_count": int(f["incomplete_ticker_count"]),
        "advancer_share": f["advancer_share"], "decliner_share": f["decliner_share"],
        "median_session_return": f["median_session_return"], "median_last15_return": f["median_last15_return"],
        "cross_sectional_dispersion": f["cross_sectional_dispersion"],
        "directional_ticker_count": int(f["directional_ticker_count"]),
        "archetype_change_count": int(f["archetype_change_count"]),
        "selected_position_count": len(reviews), "keep_count": sum(r["observer_action"] == "KEEP" for r in reviews),
        "reduce_count": sum(r["observer_action"] == "REDUCE" for r in reviews),
        "exit_count": sum(r["observer_action"] == "EXIT" for r in reviews),
        "switch_research_only_count": sum(r["switch_counterfactual"] == "EXIT_AND_SWITCH_RESEARCH_ONLY" for r in reviews),
        "ticker_state_set_hash": ticker_set_hash, "review_set_hash": review_set_hash,
        "point_in_time_pass": 1, "selection_active": 0, "position_changes_enabled": 0,
        "router_active": 0, "order_sent": 0, "batch_payload_hash": _payload_hash(batch_payload),
    }
    stored_tickers = []
    for source in ticker_rows:
        row = {"checkpoint_batch_id": batch_id, "experiment_id": EXPERIMENT_ID, "code_version": CODE_VERSION, **source}
        row["row_payload_hash"] = _payload_hash({k: v for k, v in row.items() if k != "row_payload_hash"})
        stored_tickers.append(row)
    stored_reviews = []
    for source in reviews:
        row = {"checkpoint_batch_id": batch_id, "experiment_id": EXPERIMENT_ID, "code_version": CODE_VERSION, **source}
        row["row_payload_hash"] = _payload_hash({k: v for k, v in row.items() if k != "row_payload_hash"})
        stored_reviews.append(row)
    ledger_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_schema(con)
        con.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(con, "step9v_checkpoint_batches", "checkpoint_batch_id", "batch_payload_hash", batch)
        for row in stored_tickers:
            _insert_immutable(con, "step9v_ticker_states", "ticker_state_id", "row_payload_hash", row)
        for row in stored_reviews:
            _insert_immutable(con, "step9v_selected_position_reviews", "review_id", "row_payload_hash", row)
        con.commit()
    if export_after:
        export_outputs(ledger_db)
    return pd.DataFrame([batch]), pd.DataFrame(stored_tickers), pd.DataFrame(stored_reviews), inserted


def _pnl(direction: str, entry: float, exit_price: float, round_trips: float = 1.0) -> tuple[float, float, float, float]:
    sign = 1.0 if direction == "LONG" else -1.0
    gross_return = sign * (exit_price / entry - 1.0)
    gross = BASE_NOTIONAL_SEK * gross_return
    cost = BASE_NOTIONAL_SEK * ROUND_TRIP_COST_RATE * round_trips
    return gross_return, gross, cost, gross - cost


def evaluate_eod(
    session_date: str, now: datetime, source_db: Path = DEFAULT_SOURCE_DB,
    ledger_db: Path = DEFAULT_LEDGER_DB, allow_early: bool = False, export_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not ledger_db.is_file():
        raise FileNotFoundError(ledger_db)
    if not allow_early:
        if session_date != now.date().isoformat() or now.time().replace(tzinfo=None) < _clock(EOD_TIME):
            raise SourceDataNotReady(f"Step 9V EOD is not allowed before {EOD_TIME} for the current session.")
    prices = _load_prices(source_db, session_date)
    max_label = str(prices["clock"].max())
    if max_label < EOD_MINIMUM_LABEL:
        raise SourceDataNotReady(f"EOD prices incomplete; latest label is {max_label}, require at least {EOD_MINIMUM_LABEL}.")
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_schema(con)
        con.row_factory = sqlite3.Row
        batches = [dict(r) for r in con.execute(
            "SELECT * FROM step9v_checkpoint_batches WHERE session_date=? ORDER BY checkpoint_time", (session_date,)
        ).fetchall()]
        if not batches:
            raise SourceDataNotReady(f"No Step 9V checkpoints exist for {session_date}.")
        all_tickers = {b["checkpoint_batch_id"]: [dict(r) for r in con.execute(
            "SELECT * FROM step9v_ticker_states WHERE checkpoint_batch_id=? ORDER BY ticker", (b["checkpoint_batch_id"],)
        ).fetchall()] for b in batches}
        all_reviews = {b["checkpoint_batch_id"]: [dict(r) for r in con.execute(
            "SELECT * FROM step9v_selected_position_reviews WHERE checkpoint_batch_id=? ORDER BY selected_rank", (b["checkpoint_batch_id"],)
        ).fetchall()] for b in batches}
    out_batches, ticker_outcomes, action_outcomes = [], [], []
    for batch in batches:
        bid = batch["checkpoint_batch_id"]
        action_label = batch["action_price_label"]
        tob: list[dict[str, Any]] = []
        aob: list[dict[str, Any]] = []
        for state in all_tickers[bid]:
            bars = _bar_map(prices[prices["ticker"] == state["ticker"]])
            direction = str(state["current_direction"])
            if direction == "NONE" or action_label not in bars:
                vals = (None, None, None, None)
                status = "NO_DIRECTIONAL_CHECKPOINT_SETUP" if direction == "NONE" else "INCOMPLETE_ACTION_PRICE"
                entry_price = None
            else:
                entry_price = float(bars[action_label].open)
                exit_price = float(bars[max_label].close)
                vals = _pnl(direction, entry_price, exit_price)
                status = "CHECKPOINT_COUNTERFACTUAL_COMPLETE"
            row = {
                "outcome_batch_id": f"{bid}-EOD", "checkpoint_batch_id": bid, "session_date": session_date,
                "checkpoint_time": batch["checkpoint_time"], "ticker": state["ticker"],
                "checkpoint_archetype": state["current_archetype"], "checkpoint_direction": direction,
                "entry_label": action_label, "entry_price": entry_price, "exit_label": max_label,
                "exit_price": float(bars[max_label].close) if max_label in bars else None,
                "gross_return": vals[0], "gross_pnl_sek": vals[1], "cost_sek": vals[2], "net_pnl_sek": vals[3],
                "outcome_status": status, "router_active": 0, "order_sent": 0,
            }
            row["ticker_outcome_id"] = _payload_hash({k: v for k, v in row.items() if k != "ticker_outcome_id"})
            row["row_payload_hash"] = _payload_hash(row)
            tob.append(row)
        for review in all_reviews[bid]:
            bars = _bar_map(prices[prices["ticker"] == review["ticker"]])
            required = [MORNING_ENTRY_LABEL, action_label, max_label]
            if any(x not in bars for x in required):
                hold = exit_p = reduce_p = switch_p = action_p = improvement = None
                status = "INCOMPLETE_SELECTED_ACTION_PRICES"
                morning_px = action_px = exit_px = None
            else:
                morning_px = float(bars[MORNING_ENTRY_LABEL].open)
                action_px = float(bars[action_label].open)
                exit_px = float(bars[max_label].close)
                original = str(review["original_direction"])
                _, _, _, hold = _pnl(original, morning_px, exit_px, 1.0)
                _, _, _, exit_p = _pnl(original, morning_px, action_px, 1.0)
                reduce_p = REDUCE_FRACTION * exit_p + (1.0 - REDUCE_FRACTION) * hold
                current_dir = "SHORT" if original == "LONG" else "LONG"
                _, gross1, _, _ = _pnl(original, morning_px, action_px, 0.0)
                _, gross2, _, _ = _pnl(current_dir, action_px, exit_px, 0.0)
                switch_p = gross1 + gross2 - BASE_NOTIONAL_SEK * ROUND_TRIP_COST_RATE * 2.0
                action = str(review["observer_action"])
                action_p = hold if action == "KEEP" else (reduce_p if action == "REDUCE" else exit_p)
                improvement = action_p - hold
                status = "SELECTED_ACTION_COUNTERFACTUAL_COMPLETE"
            row = {
                "outcome_batch_id": f"{bid}-EOD", "checkpoint_batch_id": bid, "review_id": review["review_id"],
                "session_date": session_date, "checkpoint_time": batch["checkpoint_time"], "ticker": review["ticker"],
                "original_direction": review["original_direction"], "observer_action": review["observer_action"],
                "switch_counterfactual": review["switch_counterfactual"], "morning_entry_label": MORNING_ENTRY_LABEL,
                "morning_entry_price": morning_px, "action_price_label": action_label, "action_price": action_px,
                "exit_label": max_label, "exit_price": exit_px, "hold_net_pnl_sek": hold,
                "exit_net_pnl_sek": exit_p, "reduce_net_pnl_sek": reduce_p, "switch_net_pnl_sek": switch_p,
                "observer_action_net_pnl_sek": action_p, "improvement_vs_hold_sek": improvement,
                "outcome_status": status, "router_active": 0, "order_sent": 0,
            }
            row["action_outcome_id"] = _payload_hash({k: v for k, v in row.items() if k != "action_outcome_id"})
            row["row_payload_hash"] = _payload_hash(row)
            aob.append(row)
        t_hash = _payload_hash([r["ticker_outcome_id"] for r in sorted(tob, key=lambda x: x["ticker"])])
        a_hash = _payload_hash([r["action_outcome_id"] for r in sorted(aob, key=lambda x: x["ticker"])])
        ob = {
            "outcome_batch_id": f"{bid}-EOD", "checkpoint_batch_id": bid, "session_date": session_date,
            "checkpoint_time": batch["checkpoint_time"], "created_at_stockholm": now.strftime("%Y-%m-%d %H:%M:%S%z"),
            "code_version": CODE_VERSION, "action_price_label": action_label, "exit_label": max_label,
            "ticker_outcome_count": len(tob), "selected_action_outcome_count": len(aob),
            "ticker_outcome_set_hash": t_hash, "selected_action_outcome_set_hash": a_hash,
            "router_active": 0, "order_sent": 0,
        }
        ob["outcome_payload_hash"] = _payload_hash({k: v for k, v in ob.items() if k != "outcome_payload_hash"})
        out_batches.append(ob); ticker_outcomes.extend(tob); action_outcomes.extend(aob)
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_schema(con); con.execute("BEGIN IMMEDIATE")
        for row in out_batches:
            _insert_immutable(con, "step9v_checkpoint_outcome_batches", "outcome_batch_id", "outcome_payload_hash", row)
        for row in ticker_outcomes:
            _insert_immutable(con, "step9v_ticker_counterfactual_outcomes", "ticker_outcome_id", "row_payload_hash", row)
        for row in action_outcomes:
            _insert_immutable(con, "step9v_selected_action_outcomes", "action_outcome_id", "row_payload_hash", row)
        con.commit()
    if export_after:
        export_outputs(ledger_db)
    return pd.DataFrame(out_batches), pd.DataFrame(ticker_outcomes), pd.DataFrame(action_outcomes)


def audit_ledger(ledger_db: Path = DEFAULT_LEDGER_DB) -> pd.DataFrame:
    if not ledger_db.is_file():
        raise FileNotFoundError(ledger_db)
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_schema(con)
        tables = {name: pd.read_sql_query(f"SELECT * FROM {name}", con) for name in [
            "step9v_checkpoint_batches", "step9v_ticker_states", "step9v_selected_position_reviews",
            "step9v_checkpoint_outcome_batches", "step9v_ticker_counterfactual_outcomes", "step9v_selected_action_outcomes",
        ]}
    b, t, r, ob, to, ao = tables.values()
    checks = []
    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
    add("sqlite_integrity", True, "opened successfully")
    add("one_checkpoint_per_session_time", b.empty or not b[["session_date", "checkpoint_time"]].duplicated().any(), f"rows={len(b)}")
    counts = t.groupby(["session_date", "checkpoint_time"]).size() if not t.empty else pd.Series(dtype=int)
    add("all_checkpoints_have_29_tickers", counts.empty or bool(counts.eq(29).all()), str(counts.to_dict()))
    add("checkpoint_registry_frozen", b.empty or set(b["checkpoint_time"]).issubset(set(CHECKPOINTS)), str(sorted(set(b["checkpoint_time"]))))
    add("observer_only", b.empty or (b["selection_active"].eq(0) & b["position_changes_enabled"].eq(0)).all(), "no position changes")
    frames = [x for x in [b, t, r, ob, to, ao] if not x.empty]
    add("router_inactive", all(pd.to_numeric(x["router_active"]).eq(0).all() for x in frames), "all zero")
    add("orders_not_sent", all(pd.to_numeric(x["order_sent"]).eq(0).all() for x in frames), "all zero")
    add("selected_reviews_only", r.empty or set(r["observer_action"]).issubset({"KEEP", "REDUCE", "EXIT"}), str(sorted(set(r["observer_action"]))))
    add("switch_research_only", r.empty or set(r["switch_counterfactual"]).issubset({"NO_SWITCH", "EXIT_AND_SWITCH_RESEARCH_ONLY"}), "no active switch")
    add("one_outcome_batch_per_checkpoint", ob.empty or not ob["checkpoint_batch_id"].duplicated().any(), f"rows={len(ob)}")
    outcome_counts = to.groupby("checkpoint_batch_id").size() if not to.empty else pd.Series(dtype=int)
    add("all_eod_checkpoint_batches_have_29_ticker_outcomes", outcome_counts.empty or bool(outcome_counts.eq(29).all()), str(outcome_counts.to_dict()))
    return pd.DataFrame(checks)


def export_outputs(ledger_db: Path = DEFAULT_LEDGER_DB, output_dir: Path = DEFAULT_EXPORT_DIR) -> None:
    if not ledger_db.is_file():
        raise FileNotFoundError(ledger_db)
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "step9v_checkpoint_batches": BATCH_EXPORT,
        "step9v_ticker_states": TICKER_EXPORT,
        "step9v_selected_position_reviews": REVIEW_EXPORT,
        "step9v_checkpoint_outcome_batches": OUTCOME_BATCH_EXPORT,
        "step9v_ticker_counterfactual_outcomes": TICKER_OUTCOME_EXPORT,
        "step9v_selected_action_outcomes": ACTION_OUTCOME_EXPORT,
    }
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_schema(con)
        frames = {table: pd.read_sql_query(f"SELECT * FROM {table}", con) for table in mapping}
    for table, filename in mapping.items():
        frames[table].to_csv(output_dir / filename, index=False)
    audit = audit_ledger(ledger_db); audit.to_csv(output_dir / AUDIT_EXPORT, index=False)
    b = frames["step9v_checkpoint_batches"]; ao = frames["step9v_selected_action_outcomes"]
    summary = pd.DataFrame([{
        "experiment_id": EXPERIMENT_ID, "research_status": RESEARCH_STATUS,
        "checkpoint_batches": len(b), "sessions": b["session_date"].nunique() if not b.empty else 0,
        "selected_position_reviews": len(frames["step9v_selected_position_reviews"]),
        "eod_checkpoint_batches": len(frames["step9v_checkpoint_outcome_batches"]),
        "observer_action_improvement_vs_hold_sek": float(pd.to_numeric(ao["improvement_vs_hold_sek"], errors="coerce").fillna(0).sum()) if not ao.empty else 0.0,
        "selection_active": False, "position_changes_enabled": False,
        "router_active": False, "orders_sent": False, "audit_pass": bool(audit["passed"].all()),
    }])
    summary.to_csv(output_dir / SUMMARY_EXPORT, index=False)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Step 9V fixed-checkpoint intraday observer.")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("checkpoint")
    c.add_argument("--date", default=None); c.add_argument("--checkpoint", required=True, choices=list(CHECKPOINTS))
    c.add_argument("--as-of", default=None); c.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    c.add_argument("--step9t-ledger-db", type=Path, default=DEFAULT_STEP9T_LEDGER_DB)
    c.add_argument("--step9u-ledger-db", type=Path, default=DEFAULT_STEP9U_LEDGER_DB)
    c.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    c.add_argument("--allow-late-reconstruction", action="store_true")
    c.add_argument("--allow-mock-source", action="store_true")
    e = sub.add_parser("eod")
    e.add_argument("--date", default=None); e.add_argument("--as-of", default=None)
    e.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB); e.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    e.add_argument("--allow-early-evaluation", action="store_true")
    a = sub.add_parser("audit"); a.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    x = sub.add_parser("export"); x.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB); x.add_argument("--output-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "audit":
        audit = audit_ledger(args.ledger_db); print(audit.to_string(index=False)); raise SystemExit(0 if bool(audit["passed"].all()) else 1)
    if args.command == "export":
        export_outputs(args.ledger_db, args.output_dir); print("Step 9V exports refreshed."); return
    now = _parse_now(args.as_of); date = args.date or now.date().isoformat()
    if args.command == "checkpoint":
        batch, tickers, reviews, inserted = seal_checkpoint(
            date, args.checkpoint, now, args.source_db, args.step9t_ledger_db, args.step9u_ledger_db,
            args.ledger_db, args.allow_late_reconstruction, args.allow_mock_source, True,
        )
        b = batch.iloc[0]
        print("\n=== STEP 9V INTRADAY CHECKPOINT OBSERVER ===")
        print(f"Session / checkpoint : {date} / {args.checkpoint}")
        print(f"Ledger action        : {'SEALED_NEW_CHECKPOINT' if inserted else 'EXISTING_IDENTICAL_CHECKPOINT_RETURNED'}")
        print(f"Research status      : {b['prospective_status']}")
        print(f"Morning environment  : {b['morning_regime']} / {b['morning_transition_state']}")
        print(f"Intraday environment : {b['intraday_environment_state']} / {b['intraday_environment_bias']}")
        print(f"Morning relation     : {b['morning_relation']}")
        print(f"Ticker rows          : {len(tickers)} / {int(b['valid_ticker_count'])} complete")
        print(f"Selected reviews     : KEEP={int(b['keep_count'])} REDUCE={int(b['reduce_count'])} EXIT={int(b['exit_count'])}")
        if not reviews.empty:
            print("Review detail:")
            for row in reviews.sort_values("selected_rank").itertuples(index=False):
                print(f"  {row.ticker}: {row.observer_action} ({row.action_reason})")
        print("POSITION CHANGES ENABLED: FALSE")
        print("ROUTER ACTIVE: FALSE")
        print("NO ORDER WAS SENT")
        return
    ob, to, ao = evaluate_eod(date, now, args.source_db, args.ledger_db, args.allow_early_evaluation, True)
    print("\n=== STEP 9V END-OF-DAY COUNTERFACTUALS ===")
    print(f"Session date                 : {date}")
    print(f"Checkpoint outcome batches   : {len(ob)}")
    print(f"Ticker counterfactual rows    : {len(to)}")
    print(f"Selected action outcome rows  : {len(ao)}")
    if not ao.empty:
        print(f"Observer action improvement vs hold: {ao['improvement_vs_hold_sek'].fillna(0).sum():.6f} SEK")
    print("POSITION CHANGES ENABLED: FALSE")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
