from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RegimeTrading.core.paths import DATA_DIR, PROJECT_ROOT
from RegimeTrading.core.stage_registry import LEDGER_PATHS


ROOT = PROJECT_ROOT
DATA = DATA_DIR
DEFAULT_PATHS = dict(LEDGER_PATHS)

CONFIRMATORY = "PROSPECTIVE_CONFIRMATORY_ELIGIBLE"
T_STATUS = "PROSPECTIVE_SHADOW_OBSERVATION"
U_STATUS = "PROSPECTIVE_SHADOW_SELECTION"
CLOCK_PATTERN = re.compile(r"^\d{2}:\d{2}$")
IL_MOCK_STATUSES = {
    CONFIRMATORY,
    "HISTORICAL_RECONSTRUCTION_NOT_CONFIRMATORY",
    "LATE_RECONSTRUCTION_NOT_CONFIRMATORY",
    "SIMULATED_CLOCK_RECONSTRUCTION_NOT_CONFIRMATORY",
}
S_MOCK_STATUSES = IL_MOCK_STATUSES | {"SOURCE_STEP9L_NONCONFIRMATORY"}
T_MOCK_STATUSES = {
    T_STATUS,
    "LATE_RECONSTRUCTION_NOT_CONFIRMATORY",
    "SIMULATED_POINT_IN_TIME_VERIFICATION_NOT_CONFIRMATORY",
    "SOURCE_STEP9L_LATE_NOT_CONFIRMATORY",
}
U_MOCK_STATUSES = {
    U_STATUS,
    "LATE_RECONSTRUCTION_NOT_CONFIRMATORY",
    "SIMULATED_POINT_IN_TIME_VERIFICATION_NOT_CONFIRMATORY",
    "SOURCE_STEP9T_NOT_CONFIRMATORY",
}


class MorningV2Error(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise MorningV2Error(f"Unsafe relative path in manifest: {relative}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise MorningV2Error(f"Manifest path escapes project root: {relative}") from exc
    return resolved


def verify_runtime_manifest(manifest_path: Path, root: Path = ROOT) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise MorningV2Error(f"Runtime compatibility manifest is missing: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise MorningV2Error("Runtime compatibility manifest contains no files.")
    checked: list[str] = []
    for relative, expected in sorted(files.items()):
        path = _safe_relative_path(Path(root), str(relative))
        if not path.is_file():
            raise MorningV2Error(f"Required runtime dependency is missing: {relative}")
        actual = _sha256(path)
        if actual.lower() != str(expected).lower():
            raise MorningV2Error(
                f"Runtime dependency differs from the audited source: {relative}"
            )
        checked.append(str(relative))
    exclusive_globs = payload.get("exclusive_globs", {})
    if not isinstance(exclusive_globs, dict):
        raise MorningV2Error("Runtime manifest exclusive_globs must be an object.")
    glob_checks: list[str] = []
    resolved_root = Path(root).resolve()
    for pattern, allowed_values in sorted(exclusive_globs.items()):
        pattern_text = str(pattern).replace("\\", "/")
        pattern_path = Path(pattern_text)
        if pattern_path.is_absolute() or ".." in pattern_path.parts:
            raise MorningV2Error(
                f"Unsafe exclusive glob in runtime manifest: {pattern_text}"
            )
        if not isinstance(allowed_values, list) or not allowed_values:
            raise MorningV2Error(
                f"Exclusive glob has no allowed files: {pattern_text}"
            )
        allowed = {
            str(value).replace("\\", "/") for value in allowed_values
        }
        for relative in allowed:
            _safe_relative_path(resolved_root, relative)
        matched: set[str] = set()
        for path in resolved_root.glob(pattern_text):
            if not path.is_file():
                continue
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(resolved_root).as_posix()
            except ValueError as exc:
                raise MorningV2Error(
                    f"Exclusive glob escaped the project root: {pattern_text}"
                ) from exc
            matched.add(relative)
        if matched != allowed:
            raise MorningV2Error(
                "Runtime exclusive glob inventory differs from the audited "
                f"source: {pattern_text}; expected={sorted(allowed)}; "
                f"actual={sorted(matched)}"
            )
        glob_checks.append(pattern_text)
    return {
        "status": "STEP9_MORNING_V2_RUNTIME_COMPATIBILITY_PASSED",
        "manifest": str(manifest_path),
        "files_checked": len(checked),
        "exclusive_globs_checked": len(glob_checks),
        "router_active": False,
        "orders_enabled": False,
    }


def _ro_connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise MorningV2Error(f"SQLite file is missing: {path}")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _rows(path: Path, table: str, session_date: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with closing(_ro_connect(path)) as con:
        if not _table_exists(con, table):
            return []
        return [
            dict(row)
            for row in con.execute(
                f'SELECT * FROM "{table}" WHERE session_date=?', (session_date,)
            ).fetchall()
        ]


def _single(rows: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    if len(rows) > 1:
        raise MorningV2Error(
            f"{label} has {len(rows)} rows for one session; expected at most one."
        )
    return rows[0] if rows else None


def _count(path: Path, table: str, session_date: str, where: str = "") -> int:
    if not path.is_file():
        return 0
    with closing(_ro_connect(path)) as con:
        if not _table_exists(con, table):
            return 0
        suffix = f" AND ({where})" if where else ""
        return int(
            con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE session_date=?{suffix}',
                (session_date,),
            ).fetchone()[0]
        )


def _selected_tickers(
    path: Path,
    table: str,
    session_date: str,
) -> list[str]:
    if not path.is_file():
        return []
    with closing(_ro_connect(path)) as con:
        if not _table_exists(con, table):
            return []
        columns = {
            str(row[1])
            for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        required = {"session_date", "ticker", "selected", "selected_rank"}
        if not required.issubset(columns):
            return []
        rows = con.execute(
            f'SELECT ticker FROM "{table}" '
            "WHERE session_date=? AND selected=1 "
            "ORDER BY selected_rank, ticker",
            (session_date,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _write_json(payload: dict[str, Any], path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temp, path)


def _price_status(path: Path, session_date: str) -> dict[str, Any]:
    base = {
        "path": str(path),
        "exists": path.is_file(),
        "today_rows": 0,
        "today_tickers": 0,
        "max_datetime_today": "",
        "max_clock_today": "",
        "exact_0940_tickers": 0,
        "exact_0945_tickers": 0,
        "ready_through_0940": False,
        "ready_through_0945": False,
        "sqlite_integrity": "",
    }
    if not path.is_file():
        return base
    with closing(_ro_connect(path)) as con:
        integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
        base["sqlite_integrity"] = integrity
        if integrity.lower() != "ok":
            return base
        if not _table_exists(con, "intraday_prices"):
            return base
        today_rows, today_tickers, max_dt = con.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT ticker), COALESCE(MAX(datetime), '')
            FROM intraday_prices
            WHERE substr(datetime,1,10)=?
            """,
            (session_date,),
        ).fetchone()
        exact_0940 = con.execute(
            """
            SELECT COUNT(DISTINCT ticker) FROM intraday_prices
            WHERE substr(datetime,1,10)=? AND substr(datetime,12,5)='09:40'
            """,
            (session_date,),
        ).fetchone()[0]
        exact_0945 = con.execute(
            """
            SELECT COUNT(DISTINCT ticker) FROM intraday_prices
            WHERE substr(datetime,1,10)=? AND substr(datetime,12,5)='09:45'
            """,
            (session_date,),
        ).fetchone()[0]
    max_dt = str(max_dt)
    max_clock = max_dt[11:16] if len(max_dt) >= 16 else ""
    base.update(
        {
            "today_rows": int(today_rows),
            "today_tickers": int(today_tickers),
            "max_datetime_today": max_dt,
            "max_clock_today": max_clock,
            "exact_0940_tickers": int(exact_0940),
            "exact_0945_tickers": int(exact_0945),
            "ready_through_0940": int(today_tickers) >= 29 and max_clock >= "09:40",
            "ready_through_0945": int(today_tickers) >= 29 and max_clock >= "09:45",
        }
    )
    return base


def _validate_snapshot(
    path: Path,
    session_date: str,
    cutoff: str,
) -> dict[str, Any]:
    if not CLOCK_PATTERN.fullmatch(cutoff):
        raise MorningV2Error(f"Snapshot cutoff must use HH:MM format: {cutoff}")
    result = _price_status(path, session_date)
    if result["sqlite_integrity"].lower() != "ok":
        raise MorningV2Error(f"Snapshot SQLite integrity check failed: {path}")
    if int(result["today_tickers"]) < 29:
        raise MorningV2Error(
            f"Snapshot has {result['today_tickers']}/29 session tickers: {path}"
        )
    if str(result["max_clock_today"]) < cutoff:
        raise MorningV2Error(
            f"Snapshot is not ready through {cutoff}: {path}"
        )
    if str(result["max_clock_today"]) > cutoff:
        raise MorningV2Error(
            f"Snapshot contains a bar later than its {cutoff} cutoff: {path}"
        )
    with closing(_ro_connect(path)) as con:
        future_rows = int(
            con.execute(
                "SELECT COUNT(*) FROM intraday_prices "
                "WHERE substr(datetime,1,10) > ? "
                "OR (substr(datetime,1,10)=? AND substr(datetime,12,5) > ?)",
                (session_date, session_date, cutoff),
            ).fetchone()[0]
        )
    if future_rows:
        raise MorningV2Error(
            f"Snapshot contains {future_rows} rows beyond its point-in-time boundary."
        )
    return result


def status(
    session_date: str,
    *,
    prices: Path = DEFAULT_PATHS["prices"],
    step9i: Path = DEFAULT_PATHS["step9i"],
    step9l: Path = DEFAULT_PATHS["step9l"],
    step9s: Path = DEFAULT_PATHS["step9s"],
    step9r: Path = DEFAULT_PATHS["step9r"],
    step9t: Path = DEFAULT_PATHS["step9t"],
    step9u: Path = DEFAULT_PATHS["step9u"],
) -> dict[str, Any]:
    i = _single(_rows(step9i, "shadow_decision_batches", session_date), "Step 9I")
    l = _single(_rows(step9l, "shadow_decision_batches", session_date), "Step 9L")
    s = _single(_rows(step9s, "step9s_assignments", session_date), "Step 9S")
    r = _single(_rows(step9r, "selector_batches", session_date), "Step 9R")
    t = _single(_rows(step9t, "step9t_prospective_batches", session_date), "Step 9T")
    u = _single(
        _rows(step9u, "step9u_prospective_assignment_batches", session_date),
        "Step 9U",
    )

    payload: dict[str, Any] = {
        "session_date": session_date,
        "prices": _price_status(prices, session_date),
        "step9i": {"sealed": i is not None},
        "step9l": {"sealed": l is not None},
        "step9s": {"sealed": s is not None},
        "step9r": {"sealed": r is not None},
        "step9t": {"sealed": t is not None},
        "step9u": {"sealed": u is not None},
        "router_active": False,
        "orders_enabled": False,
    }
    if i:
        payload["step9i"].update(
            {
                "batch_id": str(i["batch_id"]),
                "prospective_status": str(i["prospective_status"]),
                "run_mode": str(i["run_mode"]),
                "primary_regime": str(i["primary_regime"]),
                "decision_rows": int(i["decision_rows"]),
                "eligible_rows": int(i["eligible_rows"]),
                "active_guardrails": int(i["active_guardrails"]),
                "payload_hash": str(i["batch_payload_hash"]),
                "decision_rows_actual": _count(
                    step9i, "shadow_decisions", session_date
                ),
                "eligible_rows_actual": _count(
                    step9i,
                    "shadow_decisions",
                    session_date,
                    "contract_eligible=1",
                ),
                "active_guardrails_actual": _count(
                    step9i,
                    "shadow_decisions",
                    session_date,
                    "decision_action='GUARDRAIL_ACTIVE_AVOID_STRATEGY'",
                ),
                "point_in_time_failures": _count(
                    step9i, "shadow_decisions", session_date, "point_in_time_pass<>1"
                ),
                "regime_point_in_time_pass": int(i["regime_point_in_time_pass"]),
            }
        )
    if l:
        payload["step9l"].update(
            {
                "batch_id": str(l["batch_id"]),
                "prospective_status": str(l["prospective_status"]),
                "run_mode": str(l["run_mode"]),
                "primary_regime": str(l["primary_regime"]),
                "decision_rows": int(l["decision_rows"]),
                "eligible_rows": int(l["eligible_rows"]),
                "active_guardrails": int(l["active_guardrails"]),
                "payload_hash": str(l["batch_payload_hash"]),
                "decision_rows_actual": _count(
                    step9l, "shadow_decisions", session_date
                ),
                "eligible_rows_actual": _count(
                    step9l,
                    "shadow_decisions",
                    session_date,
                    "contract_eligible=1",
                ),
                "active_guardrails_actual": _count(
                    step9l,
                    "shadow_decisions",
                    session_date,
                    "decision_action='GUARDRAIL_ACTIVE_AVOID_STRATEGY'",
                ),
                "point_in_time_failures": _count(
                    step9l, "shadow_decisions", session_date, "point_in_time_pass<>1"
                ),
                "regime_point_in_time_pass": int(l["regime_point_in_time_pass"]),
            }
        )
    if s:
        payload["step9s"].update(
            {
                "assignment_id": str(s["assignment_id"]),
                "prospective_status": str(s["prospective_status"]),
                "primary_regime": str(s["primary_regime"]),
                "source_step9l_batch_id": str(s["source_step9l_batch_id"]),
                "coverage_plan_rows": _count(
                    step9s, "step9s_coverage_plans", session_date
                ),
                "coverage_plan_point_in_time_failures": _count(
                    step9s,
                    "step9s_coverage_plans",
                    session_date,
                    "point_in_time_pass<>1",
                ),
                "coverage_plan_router_active_rows": _count(
                    step9s,
                    "step9s_coverage_plans",
                    session_date,
                    "router_active<>0",
                ),
                "coverage_plan_order_sent_rows": _count(
                    step9s,
                    "step9s_coverage_plans",
                    session_date,
                    "order_sent<>0",
                ),
                "point_in_time_pass": int(s["point_in_time_pass"]),
                "router_active": int(s["router_active"]),
                "order_sent": int(s["order_sent"]),
            }
        )
    if r:
        payload["step9r"].update(
            {
                "batch_id": str(r["batch_id"]),
                "prospective_status": str(r["prospective_status"]),
                "evidence_eligible": int(r["evidence_eligible"]),
                "candidate_rows": int(r["candidate_rows"]),
                "candidate_rows_actual": _count(
                    step9r, "selector_candidates", session_date
                ),
                "selected_rows": int(r["selected_rows"]),
                "selected_rows_actual": _count(
                    step9r, "selector_candidates", session_date, "selected=1"
                ),
                "payload_hash": str(r["payload_hash"]),
            }
        )
    if t:
        payload["step9t"].update(
            {
                "batch_id": str(t["batch_id"]),
                "prospective_status": str(t["prospective_status"]),
                "source_step9l_batch_id": str(t["source_step9l_batch_id"]),
                "source_regime": str(t["source_regime"]),
                "transition_state": str(t["transition_state"]),
                "ticker_row_count": int(t["ticker_row_count"]),
                "ticker_rows_actual": _count(
                    step9t,
                    "step9t_prospective_ticker_archetypes",
                    session_date,
                ),
                "ticker_point_in_time_failures": _count(
                    step9t,
                    "step9t_prospective_ticker_archetypes",
                    session_date,
                    "point_in_time_pass<>1",
                ),
                "ticker_router_active_rows": _count(
                    step9t,
                    "step9t_prospective_ticker_archetypes",
                    session_date,
                    "router_active<>0",
                ),
                "ticker_order_sent_rows": _count(
                    step9t,
                    "step9t_prospective_ticker_archetypes",
                    session_date,
                    "order_sent<>0",
                ),
                "point_in_time_pass": int(t["point_in_time_pass"]),
                "router_active": int(t["router_active"]),
                "order_sent": int(t["order_sent"]),
                "payload_hash": str(t["batch_payload_hash"]),
            }
        )
    if u:
        selected_tickers = [
            item for item in str(u["selected_tickers"] or "").split("|") if item
        ]
        payload["step9u"].update(
            {
                "assignment_batch_id": str(u["assignment_batch_id"]),
                "prospective_status": str(u["prospective_status"]),
                "source_step9t_batch_id": str(u["source_step9t_batch_id"]),
                "source_regime": str(u["source_regime"]),
                "transition_state": str(u["transition_state"]),
                "candidate_rows": int(u["directional_candidate_rows"]),
                "candidate_rows_actual": _count(
                    step9u,
                    "step9u_prospective_candidates",
                    session_date,
                ),
                "selected_count": int(u["selected_count"]),
                "selected_tickers": selected_tickers,
                "selected_rows_actual": _count(
                    step9u,
                    "step9u_prospective_candidates",
                    session_date,
                    "selected=1",
                ),
                "selected_tickers_actual": _selected_tickers(
                    step9u,
                    "step9u_prospective_candidates",
                    session_date,
                ),
                "candidate_point_in_time_failures": _count(
                    step9u,
                    "step9u_prospective_candidates",
                    session_date,
                    "point_in_time_pass<>1",
                ),
                "candidate_router_active_rows": _count(
                    step9u,
                    "step9u_prospective_candidates",
                    session_date,
                    "router_active<>0",
                ),
                "candidate_order_sent_rows": _count(
                    step9u,
                    "step9u_prospective_candidates",
                    session_date,
                    "order_sent<>0",
                ),
                "mandatory_control_active": int(u["mandatory_control_active"]),
                "point_in_time_pass": int(u["point_in_time_pass"]),
                "router_active": int(u["router_active"]),
                "order_sent": int(u["order_sent"]),
                "payload_hash": str(u["batch_payload_hash"]),
            }
        )

    stages = ["step9i", "step9l", "step9s", "step9r", "step9t", "step9u"]
    payload["sealed_count"] = sum(bool(payload[name]["sealed"]) for name in stages)
    payload["all_sealed"] = payload["sealed_count"] == len(stages)
    payload["regime_consistent"] = bool(
        i
        and l
        and str(i["primary_regime"]) == str(l["primary_regime"])
        and (not s or str(s["primary_regime"]) == str(l["primary_regime"]))
        and (not t or str(t["source_regime"]) == str(l["primary_regime"]))
        and (not u or str(u["source_regime"]) == str(l["primary_regime"]))
    )
    payload["live_complete"] = bool(
        payload["all_sealed"]
        and payload["regime_consistent"]
        and payload["step9i"].get("prospective_status") == CONFIRMATORY
        and payload["step9l"].get("prospective_status") == CONFIRMATORY
        and payload["step9s"].get("prospective_status") == CONFIRMATORY
        and payload["step9r"].get("evidence_eligible") == 1
        and payload["step9t"].get("prospective_status") == T_STATUS
        and payload["step9u"].get("prospective_status") == U_STATUS
    )
    payload["classification"] = (
        "LIVE_COMPLETE"
        if payload["live_complete"]
        else "LIVE_PARTIAL"
        if payload["sealed_count"] > 0
        else "LIVE_FAILED"
    )
    return payload


def verify(session_date: str, stage: str, **paths: Path) -> dict[str, Any]:
    payload = status(session_date, **paths)

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise MorningV2Error(message)

    i = payload["step9i"]
    l = payload["step9l"]
    s = payload["step9s"]
    r = payload["step9r"]
    t = payload["step9t"]
    u = payload["step9u"]

    if stage == "step9i":
        require(i["sealed"], "Step 9I is not sealed.")
        require(i.get("prospective_status") == CONFIRMATORY, "Step 9I is not confirmatory.")
        require(i.get("run_mode") == "MORNING_DECISION_SEAL", "Step 9I run mode is invalid.")
        require(
            i.get("decision_rows") == i.get("decision_rows_actual"),
            "Step 9I decision count does not match its sealed rows.",
        )
        require(i.get("decision_rows") == 184, "Step 9I must preserve 184 decisions.")
        require(
            i.get("eligible_rows") == i.get("eligible_rows_actual"),
            "Step 9I eligible count does not match its sealed rows.",
        )
        require(
            i.get("active_guardrails") == i.get("active_guardrails_actual"),
            "Step 9I guardrail count does not match its sealed rows.",
        )
        require(i.get("point_in_time_failures") == 0, "Step 9I contains a point-in-time failure.")
        require(i.get("regime_point_in_time_pass") == 1, "Step 9I regime point-in-time check failed.")
    elif stage == "step9l":
        require(l["sealed"], "Step 9L is not sealed.")
        require(l.get("prospective_status") == CONFIRMATORY, "Step 9L is not confirmatory.")
        require(l.get("run_mode") == "MORNING_DECISION_SEAL", "Step 9L run mode is invalid.")
        require(
            l.get("decision_rows") == l.get("decision_rows_actual"),
            "Step 9L decision count does not match its sealed rows.",
        )
        require(l.get("decision_rows") == 184, "Step 9L must preserve 184 decisions.")
        require(
            l.get("eligible_rows") == l.get("eligible_rows_actual"),
            "Step 9L eligible count does not match its sealed rows.",
        )
        require(
            l.get("active_guardrails") == l.get("active_guardrails_actual"),
            "Step 9L guardrail count does not match its sealed rows.",
        )
        require(l.get("point_in_time_failures") == 0, "Step 9L contains a point-in-time failure.")
        require(l.get("regime_point_in_time_pass") == 1, "Step 9L regime point-in-time check failed.")
    elif stage == "step9s":
        require(s["sealed"], "Step 9S is not sealed.")
        require(s.get("prospective_status") == CONFIRMATORY, "Step 9S is not confirmatory.")
        require(l["sealed"], "Step 9L dependency is missing.")
        require(s.get("source_step9l_batch_id") == l.get("batch_id"), "Step 9S source batch mismatch.")
        require(s.get("coverage_plan_rows") == 1, "Step 9S must have exactly one control plan.")
        require(
            s.get("coverage_plan_point_in_time_failures") == 0,
            "Step 9S coverage plan contains a point-in-time failure.",
        )
        require(
            s.get("coverage_plan_router_active_rows") == 0
            and s.get("coverage_plan_order_sent_rows") == 0,
            "Unsafe Step 9S coverage-plan state.",
        )
        require(s.get("point_in_time_pass") == 1, "Step 9S point-in-time check failed.")
        require(s.get("router_active") == 0 and s.get("order_sent") == 0, "Unsafe Step 9S state.")
    elif stage == "step9r":
        require(r["sealed"], "Step 9R is not sealed.")
        require(r.get("evidence_eligible") == 1, "Step 9R is not evidence eligible.")
        require(r.get("candidate_rows") == r.get("candidate_rows_actual"), "Step 9R candidate count mismatch.")
        require(r.get("selected_rows") == r.get("selected_rows_actual"), "Step 9R selected count mismatch.")
        require(0 <= int(r.get("selected_rows", -1)) <= 2, "Step 9R selection count is outside 0-2.")
    elif stage == "step9t":
        require(t["sealed"], "Step 9T is not sealed.")
        require(t.get("prospective_status") == T_STATUS, "Step 9T status is not prospective shadow observation.")
        require(l["sealed"], "Step 9L dependency is missing.")
        require(t.get("source_step9l_batch_id") == l.get("batch_id"), "Step 9T source batch mismatch.")
        require(t.get("ticker_row_count") == 29, "Step 9T must preserve 29 ticker rows.")
        require(
            t.get("ticker_rows_actual") == t.get("ticker_row_count"),
            "Step 9T ticker count does not match its sealed rows.",
        )
        require(
            t.get("ticker_point_in_time_failures") == 0,
            "Step 9T ticker rows contain a point-in-time failure.",
        )
        require(
            t.get("ticker_router_active_rows") == 0
            and t.get("ticker_order_sent_rows") == 0,
            "Unsafe Step 9T ticker-row state.",
        )
        require(t.get("point_in_time_pass") == 1, "Step 9T point-in-time check failed.")
        require(t.get("router_active") == 0 and t.get("order_sent") == 0, "Unsafe Step 9T state.")
    elif stage == "step9u":
        require(u["sealed"], "Step 9U is not sealed.")
        require(u.get("prospective_status") == U_STATUS, "Step 9U status is not prospective shadow selection.")
        require(t["sealed"], "Step 9T dependency is missing.")
        require(u.get("source_step9t_batch_id") == t.get("batch_id"), "Step 9U source batch mismatch.")
        require(
            u.get("candidate_rows") == u.get("candidate_rows_actual"),
            "Step 9U candidate count does not match its sealed rows.",
        )
        require(
            u.get("selected_count") == u.get("selected_rows_actual"),
            "Step 9U selected count does not match its sealed rows.",
        )
        require(
            u.get("selected_tickers") == u.get("selected_tickers_actual"),
            "Step 9U selected tickers do not match its sealed rows.",
        )
        require(0 <= int(u.get("selected_count", -1)) <= 2, "Step 9U selected count is outside 0-2.")
        require(
            u.get("candidate_point_in_time_failures") == 0,
            "Step 9U candidate rows contain a point-in-time failure.",
        )
        require(
            u.get("candidate_router_active_rows") == 0
            and u.get("candidate_order_sent_rows") == 0,
            "Unsafe Step 9U candidate-row state.",
        )
        require(u.get("mandatory_control_active") == 0, "Step 9U must not have a mandatory control.")
        require(u.get("point_in_time_pass") == 1, "Step 9U point-in-time check failed.")
        require(u.get("router_active") == 0 and u.get("order_sent") == 0, "Unsafe Step 9U state.")
    elif stage == "all":
        for name in ["step9i", "step9l", "step9s", "step9r", "step9t", "step9u"]:
            verify(session_date, name, **paths)
        require(payload["regime_consistent"], "Morning stages disagree on the detected regime.")
        require(payload["live_complete"], "The full live chain is not complete.")
    else:
        raise MorningV2Error(f"Unknown stage: {stage}")

    payload["verified_stage"] = stage
    payload["verification"] = "PASSED"
    return payload


def verify_mock(session_date: str, **paths: Path) -> dict[str, Any]:
    """Verify a structurally complete, explicitly external mock rehearsal.

    Mock continuations may contain copied confirmatory upstream rows together
    with late-reconstructed downstream rows.  Evidence classification belongs
    to the immutable mock manifest, so this verifier checks structure,
    dependencies, point-in-time payloads, and no-routing safety without
    relabelling the rows as confirmatory.
    """

    payload = status(session_date, **paths)

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise MorningV2Error(message)

    i = payload["step9i"]
    l = payload["step9l"]
    s = payload["step9s"]
    r = payload["step9r"]
    t = payload["step9t"]
    u = payload["step9u"]

    require(payload["all_sealed"], "Mock rehearsal does not contain all six stages.")
    require(payload["regime_consistent"], "Mock stages disagree on the detected regime.")

    for label, node in (("Step 9I", i), ("Step 9L", l)):
        require(
            node.get("prospective_status") in IL_MOCK_STATUSES,
            f"{label} has an unrecognized mock evidence status.",
        )
        require(node.get("run_mode") == "MORNING_DECISION_SEAL", f"{label} run mode is invalid.")
        require(
            node.get("decision_rows") == node.get("decision_rows_actual") == 184,
            f"{label} must contain exactly 184 sealed decision rows.",
        )
        require(node.get("point_in_time_failures") == 0, f"{label} has a point-in-time failure.")
        require(node.get("regime_point_in_time_pass") == 1, f"{label} regime point-in-time check failed.")
        require(
            node.get("eligible_rows") == node.get("eligible_rows_actual"),
            f"{label} eligible count does not match its sealed rows.",
        )
        require(
            node.get("active_guardrails") == node.get("active_guardrails_actual"),
            f"{label} guardrail count does not match its sealed rows.",
        )

    require(
        s.get("prospective_status") in S_MOCK_STATUSES,
        "Step 9S has an unrecognized mock evidence status.",
    )
    require(
        s.get("source_step9l_batch_id") == l.get("batch_id"),
        "Step 9S source batch does not match Step 9L.",
    )
    require(s.get("coverage_plan_rows") == 1, "Step 9S must have exactly one control plan.")
    require(
        s.get("coverage_plan_point_in_time_failures") == 0,
        "Step 9S mock coverage plan contains a point-in-time failure.",
    )
    require(
        s.get("coverage_plan_router_active_rows") == 0
        and s.get("coverage_plan_order_sent_rows") == 0,
        "Unsafe Step 9S mock coverage-plan state.",
    )
    require(s.get("point_in_time_pass") == 1, "Step 9S point-in-time check failed.")
    require(
        s.get("router_active") == 0 and s.get("order_sent") == 0,
        "Unsafe Step 9S mock state.",
    )

    require(
        r.get("candidate_rows") == r.get("candidate_rows_actual"),
        "Step 9R mock candidate count mismatch.",
    )
    require(
        r.get("selected_rows") == r.get("selected_rows_actual"),
        "Step 9R mock selected count mismatch.",
    )
    require(
        0 <= int(r.get("selected_rows", -1)) <= 2,
        "Step 9R mock selection count is outside 0-2.",
    )
    require(
        r.get("prospective_status") in IL_MOCK_STATUSES,
        "Step 9R has an unrecognized mock evidence status.",
    )

    require(
        t.get("prospective_status") in T_MOCK_STATUSES,
        "Step 9T has an unrecognized mock evidence status.",
    )
    require(
        t.get("source_step9l_batch_id") == l.get("batch_id"),
        "Step 9T source batch does not match Step 9L.",
    )
    require(t.get("ticker_row_count") == 29, "Step 9T must contain 29 ticker rows.")
    require(
        t.get("ticker_rows_actual") == t.get("ticker_row_count"),
        "Step 9T mock ticker count does not match its sealed rows.",
    )
    require(
        t.get("ticker_point_in_time_failures") == 0,
        "Step 9T mock ticker rows contain a point-in-time failure.",
    )
    require(
        t.get("ticker_router_active_rows") == 0
        and t.get("ticker_order_sent_rows") == 0,
        "Unsafe Step 9T mock ticker-row state.",
    )
    require(t.get("point_in_time_pass") == 1, "Step 9T point-in-time check failed.")
    require(
        t.get("router_active") == 0 and t.get("order_sent") == 0,
        "Unsafe Step 9T mock state.",
    )

    require(
        u.get("source_step9t_batch_id") == t.get("batch_id"),
        "Step 9U source batch does not match Step 9T.",
    )
    require(
        u.get("prospective_status") in U_MOCK_STATUSES,
        "Step 9U has an unrecognized mock evidence status.",
    )
    require(
        u.get("candidate_rows") == u.get("candidate_rows_actual"),
        "Step 9U mock candidate count does not match its sealed rows.",
    )
    require(
        u.get("selected_count") == u.get("selected_rows_actual"),
        "Step 9U mock selected count does not match its sealed rows.",
    )
    require(
        u.get("selected_tickers") == u.get("selected_tickers_actual"),
        "Step 9U mock selected tickers do not match its sealed rows.",
    )
    require(
        0 <= int(u.get("selected_count", -1)) <= 2,
        "Step 9U mock selected count is outside 0-2.",
    )
    require(
        u.get("candidate_point_in_time_failures") == 0,
        "Step 9U mock candidate rows contain a point-in-time failure.",
    )
    require(
        u.get("candidate_router_active_rows") == 0
        and u.get("candidate_order_sent_rows") == 0,
        "Unsafe Step 9U mock candidate-row state.",
    )
    require(
        u.get("mandatory_control_active") == 0,
        "Step 9U mock state must not activate a mandatory control.",
    )
    require(u.get("point_in_time_pass") == 1, "Step 9U point-in-time check failed.")
    require(
        u.get("router_active") == 0 and u.get("order_sent") == 0,
        "Unsafe Step 9U mock state.",
    )
    require(not payload["router_active"], "Mock payload reports an active router.")
    require(not payload["orders_enabled"], "Mock payload reports enabled orders.")

    payload["mock_complete"] = True
    payload["verified_stage"] = "all"
    payload["verification"] = "PASSED"
    payload["evidence_status"] = "MOCK_REHEARSAL_EXTERNAL_MANIFEST_REQUIRED"
    return payload


def create_snapshot(source: Path, destination: Path, session_date: str, cutoff: str) -> dict[str, Any]:
    source = Path(source)
    destination = Path(destination)
    if source.resolve() == destination.resolve():
        raise MorningV2Error("Snapshot source and destination must be different files.")
    if not CLOCK_PATTERN.fullmatch(cutoff):
        raise MorningV2Error(f"Snapshot cutoff must use HH:MM format: {cutoff}")
    manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    if destination.exists():
        if not manifest.is_file():
            raise MorningV2Error(
                f"Existing immutable snapshot has no manifest and will not be trusted: {destination}"
            )
        recorded = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if str(recorded.get("session_date")) != session_date:
            raise MorningV2Error("Existing snapshot manifest session date conflicts.")
        if str(recorded.get("cutoff")) != cutoff:
            raise MorningV2Error("Existing snapshot manifest cutoff conflicts.")
        actual_hash = _sha256(destination)
        if str(recorded.get("snapshot_sha256")) != actual_hash:
            raise MorningV2Error("Existing immutable snapshot hash does not match its manifest.")
        existing = _validate_snapshot(destination, session_date, cutoff)
        existing.update(
            {
                "snapshot_action": "EXISTING_IMMUTABLE_SNAPSHOT_RETURNED",
                "snapshot_sha256": actual_hash,
                "session_date": session_date,
                "cutoff": cutoff,
            }
        )
        return existing
    if not source.is_file():
        raise MorningV2Error(f"Source price database is missing: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    source_hash_before = _sha256(source)
    fd, temp_name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".tmp", dir=str(destination.parent)
    )
    os.close(fd)
    temp = Path(temp_name)
    temp.unlink(missing_ok=True)
    try:
        with closing(_ro_connect(source)) as src:
            data_version_before = int(src.execute("PRAGMA data_version").fetchone()[0])
            if not _table_exists(src, "intraday_prices"):
                raise MorningV2Error("Source database has no intraday_prices table.")
            table_sql_row = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='intraday_prices'"
            ).fetchone()
            if not table_sql_row or not table_sql_row[0]:
                raise MorningV2Error("Could not read intraday_prices schema.")
            table_sql = str(table_sql_row[0])
            index_sql = [
                str(row[0])
                for row in src.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='intraday_prices' AND sql IS NOT NULL"
                ).fetchall()
            ]
            columns = [str(row[1]) for row in src.execute("PRAGMA table_info(intraday_prices)")]
            quoted = ",".join(f'"{column}"' for column in columns)
            query = (
                f"SELECT {quoted} FROM intraday_prices "
                "WHERE substr(datetime,1,10) < ? "
                "OR (substr(datetime,1,10)=? AND substr(datetime,12,5) <= ?) "
                "ORDER BY ticker, datetime, rowid"
            )
            with closing(sqlite3.connect(temp)) as dest:
                dest.execute(table_sql)
                placeholders = ",".join("?" for _ in columns)
                insert = f"INSERT INTO intraday_prices ({quoted}) VALUES ({placeholders})"
                cursor = src.execute(query, (session_date, session_date, cutoff))
                while True:
                    rows = cursor.fetchmany(5000)
                    if not rows:
                        break
                    dest.executemany(insert, [tuple(row) for row in rows])
                for sql in index_sql:
                    dest.execute(sql)
                dest.commit()
                integrity = dest.execute("PRAGMA integrity_check").fetchone()[0]
                if str(integrity).lower() != "ok":
                    raise MorningV2Error(f"Snapshot integrity check failed: {integrity}")
            data_version_after = int(src.execute("PRAGMA data_version").fetchone()[0])
            if data_version_before != data_version_after:
                raise MorningV2Error(
                    "Source price database changed while the immutable "
                    "snapshot was being created."
                )
        _validate_snapshot(temp, session_date, cutoff)
        source_hash_after = _sha256(source)
        if source_hash_before != source_hash_after:
            raise MorningV2Error("Source price database changed while the immutable snapshot was being created.")
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)

    result = _price_status(destination, session_date)
    result.update(
        {
            "snapshot_action": "CREATED_IMMUTABLE_SNAPSHOT",
            "snapshot_sha256": _sha256(destination),
            "source_sha256": source_hash_before,
            "session_date": session_date,
            "cutoff": cutoff,
        }
    )
    _write_json(result, manifest)
    return result


def _sqlite_source_state(source: Path) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(str(source) + suffix)
        if path.is_file():
            state[suffix or "main"] = {
                "length": path.stat().st_size,
                "sha256": _sha256(path),
            }
    return state


def _stable_raw_sqlite_copy(
    source: Path,
    staging_directory: Path,
    *,
    maximum_attempts: int = 3,
) -> tuple[Path, dict[str, dict[str, Any]]]:
    staging_directory.mkdir(parents=True, exist_ok=True)
    staged_main = staging_directory / source.name
    for attempt in range(1, maximum_attempts + 1):
        for existing in staging_directory.iterdir():
            if existing.is_file():
                existing.unlink()
        before = _sqlite_source_state(source)
        if "main" not in before:
            raise MorningV2Error(f"SQLite source is missing: {source}")
        for suffix in ("", "-wal", "-shm", "-journal"):
            source_part = Path(str(source) + suffix)
            if source_part.is_file():
                shutil.copyfile(source_part, Path(str(staged_main) + suffix))
        after = _sqlite_source_state(source)
        if before != after:
            if attempt == maximum_attempts:
                break
            continue
        copied = _sqlite_source_state(staged_main)
        if copied != before:
            if attempt == maximum_attempts:
                break
            continue
        return staged_main, before
    raise MorningV2Error(
        "SQLite source did not remain byte-stable while its raw validation "
        f"snapshot was copied: {source}"
    )


def sqlite_backup(source: Path, destination: Path) -> dict[str, Any]:
    source = Path(source)
    destination = Path(destination)
    if source.resolve() == destination.resolve():
        raise MorningV2Error(
            "SQLite backup source and destination must be different files."
        )
    if not source.is_file():
        raise MorningV2Error(f"SQLite source is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".tmp", dir=str(destination.parent)
    )
    os.close(fd)
    temp = Path(temp_name)
    temp.unlink(missing_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=destination.name + ".source_snapshot.",
            dir=str(destination.parent),
        )
    )
    source_state: dict[str, dict[str, Any]] = {}
    try:
        staged_source, source_state = _stable_raw_sqlite_copy(source, staging)
        with closing(_ro_connect(staged_source)) as src:
            with closing(sqlite3.connect(temp)) as dest:
                src.backup(dest)
                integrity = str(dest.execute("PRAGMA integrity_check").fetchone()[0])
                if integrity.lower() != "ok":
                    raise MorningV2Error(
                        f"SQLite backup integrity check failed: {integrity}"
                    )
        if _sqlite_source_state(source) != source_state:
            raise MorningV2Error(
                "SQLite source changed after its stable raw validation snapshot "
                f"was created: {source}"
            )
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
    return {
        "status": "SQLITE_READ_ONLY_BACKUP_CREATED",
        "source": str(source),
        "destination": str(destination),
        "source_sha256": source_state["main"]["sha256"],
        "source_file_inventory": source_state,
        "source_opened_directly": False,
        "destination_sha256": _sha256(destination),
        "router_active": False,
        "orders_enabled": False,
    }


PRICE_FIXTURE_COLUMNS = (
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "ticker",
    "source",
    "collected_at_utc",
)


def build_price_fixture_db(
    csv_path: Path,
    fixture_manifest_path: Path,
    destination: Path,
) -> dict[str, Any]:
    csv_path = Path(csv_path)
    fixture_manifest_path = Path(fixture_manifest_path)
    destination = Path(destination)
    for path, label in (
        (csv_path, "CSV"),
        (fixture_manifest_path, "manifest"),
    ):
        if not path.is_file():
            raise MorningV2Error(f"Price fixture {label} is missing: {path}")
    try:
        fixture = json.loads(
            fixture_manifest_path.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise MorningV2Error(
            f"Price fixture manifest is invalid: {fixture_manifest_path}"
        ) from exc
    if fixture.get("purpose") != "ISOLATED_SEMANTIC_EQUIVALENCE_ONLY":
        raise MorningV2Error("Price fixture purpose is not validation-only.")
    if bool(fixture.get("router_active")) or bool(
        fixture.get("orders_enabled")
    ):
        raise MorningV2Error("Price fixture has unsafe routing flags.")
    if tuple(fixture.get("columns", ())) != PRICE_FIXTURE_COLUMNS:
        raise MorningV2Error("Price fixture columns conflict with its contract.")
    csv_hash = _sha256(csv_path)
    if str(fixture.get("csv_sha256", "")).lower() != csv_hash:
        raise MorningV2Error("Price fixture CSV hash does not match its manifest.")
    session_date = str(fixture.get("session_date", ""))
    cutoff = str(fixture.get("cutoff", ""))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", session_date):
        raise MorningV2Error("Price fixture session date is invalid.")
    if not CLOCK_PATTERN.fullmatch(cutoff):
        raise MorningV2Error("Price fixture cutoff is invalid.")

    rows: list[tuple[Any, ...]] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PRICE_FIXTURE_COLUMNS:
            raise MorningV2Error("Price fixture CSV header is invalid.")
        for line_number, row in enumerate(reader, start=2):
            timestamp = str(row["datetime"])
            ticker = str(row["ticker"])
            if timestamp[:10] != session_date or timestamp[11:16] > cutoff:
                raise MorningV2Error(
                    f"Price fixture row {line_number} exceeds its frozen scope."
                )
            if not ticker:
                raise MorningV2Error(
                    f"Price fixture row {line_number} has no ticker."
                )
            try:
                numeric = tuple(
                    float(row[column])
                    for column in ("open", "high", "low", "close")
                )
            except (TypeError, ValueError) as exc:
                raise MorningV2Error(
                    f"Price fixture row {line_number} has invalid OHLC values."
                ) from exc
            rows.append(
                (
                    timestamp,
                    *numeric,
                    ticker,
                    str(row["source"]),
                    str(row["collected_at_utc"]),
                )
            )
    if len(rows) != int(fixture.get("row_count", -1)):
        raise MorningV2Error("Price fixture row count does not match its manifest.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise MorningV2Error(
            f"Price fixture destination already exists: {destination}"
        )
    fd, temp_name = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    os.close(fd)
    temp = Path(temp_name)
    temp.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(temp)) as connection:
            connection.execute(
                """
                CREATE TABLE intraday_prices(
                    datetime TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    ticker TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'UNKNOWN',
                    collected_at_utc TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.executemany(
                "INSERT INTO intraday_prices VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
            connection.execute(
                "CREATE UNIQUE INDEX ux_step9_v2_fixture_price "
                "ON intraday_prices(ticker, datetime)"
            )
            connection.commit()
            integrity = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
            if integrity.lower() != "ok":
                raise MorningV2Error(
                    f"Price fixture SQLite integrity failed: {integrity}"
                )
        status_payload = _price_status(temp, session_date)
        expected = {
            "today_rows": int(fixture.get("row_count", -1)),
            "today_tickers": int(fixture.get("ticker_count", -1)),
            "exact_0945_tickers": int(
                fixture.get("exact_0945_ticker_count", -1)
            ),
        }
        for key, value in expected.items():
            if int(status_payload.get(key, -2)) != value:
                raise MorningV2Error(
                    f"Price fixture {key} conflicts with its manifest."
                )
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)

    result = _price_status(destination, session_date)
    result.update(
        {
            "status": "AUTHENTIC_VALIDATION_PRICE_FIXTURE_MATERIALIZED",
            "fixture_id": str(fixture.get("fixture_id", "")),
            "fixture_csv_sha256": csv_hash,
            "destination_sha256": _sha256(destination),
            "session_date": session_date,
            "cutoff": cutoff,
            "router_active": False,
            "orders_enabled": False,
        }
    )
    return result


def compile_files(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise MorningV2Error("No Python source files were supplied for compilation.")
    compiled: list[str] = []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            raise MorningV2Error(f"Python source file is missing: {path}")
        source = path.read_text(encoding="utf-8-sig")
        compile(source, str(path), "exec", dont_inherit=True)
        compiled.append(str(path))
    return {
        "status": "PYTHON_SOURCE_COMPILE_CHECK_PASSED",
        "files_compiled": len(compiled),
        "bytecode_written": False,
        "router_active": False,
        "orders_enabled": False,
    }


IL_BATCH_FIELDS = (
    "batch_id", "experiment_id", "session_date", "run_mode", "decision_time",
    "seal_deadline", "code_version", "contract_registry_hash", "universe_hash",
    "regime_source_tickers_observed", "holdout_tickers_observed",
    "primary_regime", "regime_confidence", "confidence_band", "direction_bias",
    "research_risk_multiplier", "research_max_concurrent_ideas",
    "regime_point_in_time_pass", "taxonomy_payload_json", "decision_rows",
    "eligible_rows", "active_guardrails",
)
IL_DECISION_FIELDS = (
    "decision_id", "batch_id", "session_date", "contract_id", "test_role",
    "ticker", "company_id", "broad_sector", "primary_regime", "regime_match",
    "ticker_relative_state", "volatility_bucket", "range_state",
    "sector_direction_state", "sector_direction_alignment", "intended_side",
    "contract_eligible", "decision_action", "decision_reason",
    "max_router_source_label", "point_in_time_pass",
)
SENSITIVITY_FIELDS = (
    "sensitivity_id", "session_date", "company_id", "removed_tickers",
    "baseline_regime", "leave_out_regime", "baseline_confidence",
    "leave_out_confidence", "sensitivity_status", "regime_stable",
)
S_ASSIGNMENT_FIELDS = (
    "assignment_id", "experiment_id", "session_date", "run_mode",
    "decision_time", "assignment_deadline", "coverage_entry_start",
    "code_version", "registry_hash", "historical_freeze_id",
    "historical_freeze_artifact_sha256", "source_step9l_batch_id",
    "morning_state_snapshot_hash", "primary_regime", "regime_confidence",
    "confidence_band", "direction_bias", "research_risk_multiplier",
    "taxonomy_payload_json", "natural_strategy_id", "natural_maturity",
    "natural_source_kind", "coverage_control_id", "coverage_plan_id",
    "point_in_time_pass", "router_active", "order_sent",
)
S_PLAN_FIELDS = (
    "plan_id", "assignment_id", "session_date", "primary_regime",
    "coverage_control_id", "idea_type", "direction", "ticker",
    "paired_ticker", "long_ticker", "short_ticker", "primary_candidate_rank",
    "ranking_metric", "candidate_pool_json", "entry_window_start",
    "entry_window_end", "entry_model", "stop_model", "target_model",
    "exit_cutoff", "notional_sek", "cost_rate", "max_router_source_label",
    "point_in_time_pass", "router_active", "order_sent",
)
R_BATCH_FIELDS = (
    "batch_id", "session_date", "experiment_id", "model_version",
    "training_cutoff_date", "training_sessions", "training_candidates",
    "candidate_rows", "selected_rows",
)
R_CANDIDATE_FIELDS = (
    "candidate_id", "batch_id", "session_date", "contract_id", "ticker",
    "test_role", "v3_rank", "ranking_metric", "simple_expected_r",
    "research_rank", "selected", "selection_reason", "model_eligible",
    "row_json",
)
T_BATCH_FIELDS = (
    "batch_id", "experiment_id", "session_date", "run_mode", "decision_time",
    "assignment_deadline", "latest_morning_source_label",
    "standardized_entry_label", "code_version", "historical_freeze_id",
    "historical_freeze_artifact_sha256", "historical_freeze_manifest_sha256",
    "source_step9l_batch_id", "source_duplicate_policy", "raw_source_rows",
    "canonical_source_rows", "conflicting_minute_count",
    "source_regime", "source_regime_confidence",
    "source_confidence_band", "source_direction_bias", "transition_state",
    "valid_ticker_count", "incomplete_ticker_count", "advancer_share",
    "decliner_share", "median_early_return", "median_last5_return",
    "early_loser_count", "early_winner_count",
    "recovery_share_of_early_losers",
    "continuation_share_of_early_winners", "midpoint_reclaim_share",
    "leader_failure_share", "cross_sectional_dispersion", "ticker_row_count",
    "point_in_time_pass", "router_active", "order_sent",
)
T_ARCHETYPE_FIELDS = (
    "ticker_row_id", "batch_id", "experiment_id", "code_version",
    "session_date", "ticker", "company_id", "broad_sector", "universe_role",
    "latest_morning_source_label", "standardized_entry_label",
    "morning_status", "missing_labels", "early_return", "last5_return",
    "opening_range_high", "opening_range_low", "opening_range_midpoint",
    "opening_range_position", "midpoint_reclaimed",
    "bullish_continuation_flag", "bearish_continuation_flag",
    "laggard_recovery_flag", "leader_reversal_flag", "primary_archetype",
    "direction", "max_source_label_used", "point_in_time_pass",
    "router_active", "order_sent",
)
U_BATCH_FIELDS = (
    "assignment_batch_id", "experiment_id", "session_date", "run_mode",
    "decision_time", "assignment_deadline", "standardized_entry_label",
    "code_version", "historical_freeze_id",
    "historical_freeze_artifact_sha256", "historical_freeze_manifest_sha256",
    "source_step9t_batch_id", "source_regime", "transition_state",
    "directional_candidate_rows", "selectable_candidate_rows",
    "blocked_negative_control_rows", "observation_only_rows",
    "selected_count", "selected_tickers", "selected_rule_ids",
    "no_selection_reason", "max_selected_positions",
    "max_positions_per_sector", "candidate_set_hash", "point_in_time_pass",
    "mandatory_control_active", "router_active", "order_sent",
)
U_CANDIDATE_FIELDS = (
    "candidate_id", "assignment_batch_id", "experiment_id", "code_version",
    "session_date", "ticker", "company_id", "broad_sector", "universe_role",
    "source_ticker_row_id", "source_regime", "transition_state",
    "primary_archetype", "direction", "early_return", "last5_return",
    "policy_action", "rule_id", "rule_priority", "signal_strength",
    "selection_eligible", "blocked_reason", "selected", "selected_rank",
    "selection_reason", "point_in_time_pass", "router_active", "order_sent",
)

SEMANTIC_COMPARISON_SPECS: dict[
    str,
    tuple[str, str, tuple[str, ...], dict[str, set[str]]],
] = {
    "step9i_batch": ("step9i", "shadow_decision_batches", IL_BATCH_FIELDS, {}),
    "step9i_decisions": ("step9i", "shadow_decisions", IL_DECISION_FIELDS, {}),
    "step9i_sensitivity": (
        "step9i", "core_regime_sensitivity", SENSITIVITY_FIELDS, {},
    ),
    "step9l_batch": ("step9l", "shadow_decision_batches", IL_BATCH_FIELDS, {}),
    "step9l_decisions": ("step9l", "shadow_decisions", IL_DECISION_FIELDS, {}),
    "step9l_sensitivity": (
        "step9l", "core_regime_sensitivity", SENSITIVITY_FIELDS, {},
    ),
    "step9s_assignment": (
        "step9s", "step9s_assignments", S_ASSIGNMENT_FIELDS, {},
    ),
    "step9s_coverage_plan": (
        "step9s", "step9s_coverage_plans", S_PLAN_FIELDS, {},
    ),
    "step9r_batch": ("step9r", "selector_batches", R_BATCH_FIELDS, {}),
    "step9r_candidates": (
        "step9r",
        "selector_candidates",
        R_CANDIDATE_FIELDS,
        {"row_json": {"prospective_status", "evidence_eligible"}},
    ),
    "step9t_batch": (
        "step9t", "step9t_prospective_batches", T_BATCH_FIELDS, {},
    ),
    "step9t_archetypes": (
        "step9t",
        "step9t_prospective_ticker_archetypes",
        T_ARCHETYPE_FIELDS,
        {},
    ),
    "step9u_batch": (
        "step9u", "step9u_prospective_assignment_batches", U_BATCH_FIELDS, {},
    ),
    "step9u_candidates": (
        "step9u", "step9u_prospective_candidates", U_CANDIDATE_FIELDS, {},
    ),
}


def _semantic_table_rows(
    path: Path,
    table: str,
    session_date: str,
    fields: tuple[str, ...],
    json_exclusions: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    with closing(_ro_connect(path)) as con:
        if not _table_exists(con, table):
            raise MorningV2Error(f"Validation table is missing from {path}: {table}")
        columns = [
            str(row[1])
            for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()
        ]
        if "session_date" not in columns:
            raise MorningV2Error(
                f"Validation table has no session_date column: {table}"
            )
        missing = [column for column in fields if column not in columns]
        if missing:
            raise MorningV2Error(
                f"Validation table is missing semantic columns in {table}: {missing}"
            )
        quoted = ",".join(f'"{column}"' for column in fields)
        rows = con.execute(
            f'SELECT {quoted} FROM "{table}" WHERE session_date=?',
            (session_date,),
        ).fetchall()
    canonical: list[str] = []
    for row in rows:
        payload: dict[str, Any] = {}
        for column in fields:
            value = row[column]
            if column in json_exclusions:
                try:
                    decoded = json.loads(str(value))
                except json.JSONDecodeError as exc:
                    raise MorningV2Error(
                        f"Validation column contains invalid JSON: {table}.{column}"
                    ) from exc
                if not isinstance(decoded, dict):
                    raise MorningV2Error(
                        f"Validation JSON column is not an object: {table}.{column}"
                    )
                for excluded in json_exclusions[column]:
                    decoded.pop(excluded, None)
                value = json.dumps(
                    decoded,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
            payload[column] = value
        canonical.append(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        )
    canonical.sort()
    return list(fields), canonical


def _compare_semantic_table(
    candidate: Path,
    reference: Path,
    table: str,
    session_date: str,
    fields: tuple[str, ...],
    json_exclusions: dict[str, set[str]],
) -> dict[str, Any]:
    candidate_columns, candidate_rows = _semantic_table_rows(
        candidate, table, session_date, fields, json_exclusions
    )
    reference_columns, reference_rows = _semantic_table_rows(
        reference, table, session_date, fields, json_exclusions
    )
    columns_match = candidate_columns == reference_columns
    rows_match = candidate_rows == reference_rows
    return {
        "passed": bool(columns_match and rows_match),
        "table": table,
        "semantic_columns": candidate_columns,
        "candidate_rows": len(candidate_rows),
        "reference_rows": len(reference_rows),
        "columns_match": columns_match,
        "rows_match": rows_match,
    }


def compare_validation(
    session_date: str,
    candidate_i: Path,
    candidate_l: Path,
    candidate_s: Path,
    candidate_r: Path,
    candidate_t: Path,
    candidate_u: Path,
    reference_i: Path,
    reference_l: Path,
    reference_s: Path,
    reference_r: Path,
    reference_t: Path,
    reference_u: Path,
) -> dict[str, Any]:
    database_pairs = {
        "step9i": (candidate_i, reference_i),
        "step9l": (candidate_l, reference_l),
        "step9s": (candidate_s, reference_s),
        "step9r": (candidate_r, reference_r),
        "step9t": (candidate_t, reference_t),
        "step9u": (candidate_u, reference_u),
    }
    comparisons: dict[str, dict[str, Any]] = {}
    for name, (stage, table, fields, json_exclusions) in (
        SEMANTIC_COMPARISON_SPECS.items()
    ):
        candidate, reference = database_pairs[stage]
        comparisons[name] = _compare_semantic_table(
            candidate,
            reference,
            table,
            session_date,
            fields,
            json_exclusions,
        )

    failed = [
        name
        for name, comparison in comparisons.items()
        if not bool(comparison["passed"])
    ]
    return {
        "session_date": session_date,
        "status": "PASSED" if not failed else "FAILED",
        "comparisons": comparisons,
        "failed": failed,
        "comparison_policy": (
            "ALL_DETERMINISTIC_SEMANTIC_COLUMNS_EXCEPT_EXPLICIT_PATH_"
            "TIMESTAMP_AND_SOURCE_FILE_HASH_FIELDS"
        ),
    }


def _path_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prices", type=Path, default=DEFAULT_PATHS["prices"])
    parser.add_argument("--step9i", type=Path, default=DEFAULT_PATHS["step9i"])
    parser.add_argument("--step9l", type=Path, default=DEFAULT_PATHS["step9l"])
    parser.add_argument("--step9s", type=Path, default=DEFAULT_PATHS["step9s"])
    parser.add_argument("--step9r", type=Path, default=DEFAULT_PATHS["step9r"])
    parser.add_argument("--step9t", type=Path, default=DEFAULT_PATHS["step9t"])
    parser.add_argument("--step9u", type=Path, default=DEFAULT_PATHS["step9u"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 9 Morning V2 lightweight support utilities.")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot")
    snap.add_argument("--source-db", type=Path, required=True)
    snap.add_argument("--dest-db", type=Path, required=True)
    snap.add_argument("--date", required=True)
    snap.add_argument("--cutoff", required=True)
    snap.add_argument("--json-out", type=Path)

    stat = sub.add_parser("status")
    stat.add_argument("--date", required=True)
    stat.add_argument("--json-out", type=Path)
    _path_args(stat)

    check = sub.add_parser("verify")
    check.add_argument("--date", required=True)
    check.add_argument(
        "--stage", required=True,
        choices=["step9i", "step9l", "step9s", "step9r", "step9t", "step9u", "all"],
    )
    check.add_argument("--json-out", type=Path)
    _path_args(check)

    mock = sub.add_parser("verify-mock")
    mock.add_argument("--date", required=True)
    mock.add_argument("--json-out", type=Path)
    _path_args(mock)

    runtime = sub.add_parser("runtime-manifest")
    runtime.add_argument("--manifest", type=Path, required=True)
    runtime.add_argument("--root", type=Path, default=ROOT)
    runtime.add_argument("--json-out", type=Path)

    backup = sub.add_parser("sqlite-backup")
    backup.add_argument("--source-db", type=Path, required=True)
    backup.add_argument("--dest-db", type=Path, required=True)
    backup.add_argument("--json-out", type=Path)

    fixture = sub.add_parser("fixture-db")
    fixture.add_argument("--csv", type=Path, required=True)
    fixture.add_argument("--fixture-manifest", type=Path, required=True)
    fixture.add_argument("--dest-db", type=Path, required=True)
    fixture.add_argument("--json-out", type=Path)

    compile_check = sub.add_parser("compile-files")
    compile_check.add_argument("--path", type=Path, action="append", required=True)
    compile_check.add_argument("--json-out", type=Path)

    compare = sub.add_parser("compare-validation")
    compare.add_argument("--date", required=True)
    for prefix in ["candidate", "reference"]:
        for stage in ["i", "l", "s", "r", "t", "u"]:
            compare.add_argument(f"--{prefix}-{stage}", type=Path, required=True)
    compare.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "snapshot":
        payload = create_snapshot(args.source_db, args.dest_db, args.date, args.cutoff)
    elif args.command == "status":
        payload = status(
            args.date,
            prices=args.prices,
            step9i=args.step9i,
            step9l=args.step9l,
            step9s=args.step9s,
            step9r=args.step9r,
            step9t=args.step9t,
            step9u=args.step9u,
        )
    elif args.command == "verify":
        payload = verify(
            args.date,
            args.stage,
            prices=args.prices,
            step9i=args.step9i,
            step9l=args.step9l,
            step9s=args.step9s,
            step9r=args.step9r,
            step9t=args.step9t,
            step9u=args.step9u,
        )
    elif args.command == "verify-mock":
        payload = verify_mock(
            args.date,
            prices=args.prices,
            step9i=args.step9i,
            step9l=args.step9l,
            step9s=args.step9s,
            step9r=args.step9r,
            step9t=args.step9t,
            step9u=args.step9u,
        )
    elif args.command == "runtime-manifest":
        payload = verify_runtime_manifest(args.manifest, root=args.root)
    elif args.command == "sqlite-backup":
        payload = sqlite_backup(args.source_db, args.dest_db)
    elif args.command == "fixture-db":
        payload = build_price_fixture_db(
            args.csv,
            args.fixture_manifest,
            args.dest_db,
        )
    elif args.command == "compile-files":
        payload = compile_files(args.path)
    else:
        payload = compare_validation(
            args.date,
            args.candidate_i,
            args.candidate_l,
            args.candidate_s,
            args.candidate_r,
            args.candidate_t,
            args.candidate_u,
            args.reference_i,
            args.reference_l,
            args.reference_s,
            args.reference_r,
            args.reference_t,
            args.reference_u,
        )
    json_out = getattr(args, "json_out", None)
    _write_json(payload, json_out)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") == "FAILED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
