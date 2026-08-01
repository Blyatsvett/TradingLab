from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as step9l
from RegimeTrading.scripts import step9s_prospective_contingency_shadow_v1 as step9s
from RegimeTrading.scripts import step9r_v1_candidate_ranking_research as step9r
from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as step9t
from RegimeTrading.scripts import step9u_prospective_contingency_selector_v1 as step9u
from RegimeTrading.scripts import step9q_powerbi_excel_feed as step9q


class FullMorningSafetyError(RuntimeError):
    pass


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _rows(path: Path, table: str, session_date: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        if not _table_exists(con, table):
            return []
        return [dict(row) for row in con.execute(
            f"SELECT * FROM {table} WHERE session_date=?", (session_date,)
        ).fetchall()]


def _candidate_count(path: Path, table: str, session_date: str, where: str = "") -> int:
    if not path.is_file():
        return 0
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.execute("PRAGMA query_only=ON")
        if not _table_exists(con, table):
            return 0
        extra = f" AND ({where})" if where else ""
        return int(con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_date=?{extra}", (session_date,)
        ).fetchone()[0])


def _single(rows: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    if len(rows) > 1:
        raise FullMorningSafetyError(f"{label} has {len(rows)} rows for one session; expected at most one.")
    return rows[0] if rows else None


def _price_status(session_date: str) -> dict[str, Any]:
    path = Path(step9i.SHADOW_INTRADAY_DB)
    if not path.is_file():
        return {
            "exists": False,
            "rows_through_0940": 0,
            "tickers_through_0940": 0,
            "max_datetime": "",
            "ready": False,
        }
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.execute("PRAGMA query_only=ON")
        if not _table_exists(con, "intraday_prices"):
            return {
                "exists": True,
                "rows_through_0940": 0,
                "tickers_through_0940": 0,
                "max_datetime": "",
                "ready": False,
            }
        rows, tickers, max_dt = con.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT ticker), COALESCE(MAX(datetime), '')
            FROM intraday_prices
            WHERE substr(datetime, 1, 10)=?
              AND substr(datetime, 12, 5) <= '09:40'
            """,
            (session_date,),
        ).fetchone()
        latest_all = con.execute(
            "SELECT COALESCE(MAX(datetime), '') FROM intraday_prices WHERE substr(datetime,1,10)=?",
            (session_date,),
        ).fetchone()[0]
    return {
        "exists": True,
        "rows_through_0940": int(rows),
        "tickers_through_0940": int(tickers),
        "max_datetime_through_0940": str(max_dt),
        "max_datetime_today": str(latest_all),
        "expected_tickers": len(set(step9i.REGIME_SOURCE_TICKERS) | set(step9i.TRADING_TICKERS)),
        "ready": int(tickers) >= len(set(step9i.REGIME_SOURCE_TICKERS) | set(step9i.TRADING_TICKERS)),
    }


def stage_status(session_date: str) -> dict[str, Any]:
    i_rows = _rows(Path(step9i.SHADOW_LEDGER_DB), "shadow_decision_batches", session_date)
    l_rows = _rows(Path(step9l.SHADOW_LEDGER_DB), "shadow_decision_batches", session_date)
    s_rows = _rows(Path(step9s.DEFAULT_LEDGER_DB), "step9s_assignments", session_date)
    r_rows = _rows(Path(step9r.DEFAULT_PROSPECTIVE_DB), "selector_batches", session_date)
    t_rows = _rows(Path(step9t.DEFAULT_LEDGER_DB), "step9t_prospective_batches", session_date)
    u_rows = _rows(Path(step9u.DEFAULT_LEDGER_DB), "step9u_prospective_assignment_batches", session_date)

    i = _single(i_rows, "Step 9I")
    l = _single(l_rows, "Step 9L")
    s = _single(s_rows, "Step 9S")
    r = _single(r_rows, "Step 9R")
    t = _single(t_rows, "Step 9T")
    u = _single(u_rows, "Step 9U")

    result: dict[str, Any] = {
        "session_date": session_date,
        "prices": _price_status(session_date),
        "step9i": {"sealed": i is not None},
        "step9l": {"sealed": l is not None},
        "step9s": {"sealed": s is not None},
        "step9r": {"sealed": r is not None},
        "step9t": {"sealed": t is not None},
        "step9u": {"sealed": u is not None},
        "step9q": {
            "output_path": str(step9q.DEFAULT_OUTPUT_PATH),
            "output_exists": Path(step9q.DEFAULT_OUTPUT_PATH).is_file(),
        },
    }

    if i:
        result["step9i"].update({
            "batch_id": str(i["batch_id"]),
            "prospective_status": str(i["prospective_status"]),
            "run_mode": str(i["run_mode"]),
            "primary_regime": str(i["primary_regime"]),
            "decision_rows": int(i["decision_rows"]),
            "eligible_rows": int(i["eligible_rows"]),
            "payload_hash": str(i["batch_payload_hash"]),
        })
    if l:
        result["step9l"].update({
            "batch_id": str(l["batch_id"]),
            "prospective_status": str(l["prospective_status"]),
            "run_mode": str(l["run_mode"]),
            "primary_regime": str(l["primary_regime"]),
            "decision_rows": int(l["decision_rows"]),
            "eligible_rows": int(l["eligible_rows"]),
            "payload_hash": str(l["batch_payload_hash"]),
        })
    if s:
        plan_rows = _candidate_count(Path(step9s.DEFAULT_LEDGER_DB), "step9s_coverage_plans", session_date)
        result["step9s"].update({
            "assignment_id": str(s["assignment_id"]),
            "prospective_status": str(s["prospective_status"]),
            "primary_regime": str(s["primary_regime"]),
            "source_step9l_batch_id": str(s["source_step9l_batch_id"]),
            "coverage_plan_rows": int(plan_rows),
            "point_in_time_pass": int(s["point_in_time_pass"]),
            "router_active": int(s["router_active"]),
            "order_sent": int(s["order_sent"]),
        })
    if r:
        candidates = _candidate_count(Path(step9r.DEFAULT_PROSPECTIVE_DB), "selector_candidates", session_date)
        selected = _candidate_count(Path(step9r.DEFAULT_PROSPECTIVE_DB), "selector_candidates", session_date, "selected = 1")
        result["step9r"].update({
            "batch_id": str(r["batch_id"]),
            "prospective_status": str(r["prospective_status"]),
            "evidence_eligible": int(r["evidence_eligible"]),
            "candidate_rows": int(r["candidate_rows"]),
            "candidate_rows_actual": int(candidates),
            "selected_rows": int(r["selected_rows"]),
            "selected_rows_actual": int(selected),
            "payload_hash": str(r["payload_hash"]),
        })
    if t:
        result["step9t"].update({
            "batch_id": str(t["batch_id"]),
            "prospective_status": str(t["prospective_status"]),
            "source_regime": str(t["source_regime"]),
            "transition_state": str(t["transition_state"]),
        })
    if u:
        result["step9u"].update({
            "assignment_batch_id": str(u["assignment_batch_id"]),
            "prospective_status": str(u["prospective_status"]),
            "source_regime": str(u["source_regime"]),
            "transition_state": str(u["transition_state"]),
            "selected_count": int(u["selected_count"]),
            "mandatory_control_active": int(u["mandatory_control_active"]),
            "router_active": int(u["router_active"]),
            "order_sent": int(u["order_sent"]),
        })
    return result


def verify_stage(session_date: str, stage: str) -> dict[str, Any]:
    payload = stage_status(session_date)
    confirmatory = "PROSPECTIVE_CONFIRMATORY_ELIGIBLE"

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise FullMorningSafetyError(message)

    i = payload["step9i"]
    l = payload["step9l"]
    s = payload["step9s"]
    r = payload["step9r"]

    if stage in {"step9i", "step9l", "step9s", "step9r", "upstream"}:
        require(i["sealed"], "Step 9I is not sealed for the session.")
        require(i["prospective_status"] == confirmatory, f"Step 9I status is {i.get('prospective_status')}.")
        require(i["run_mode"] == "MORNING_DECISION_SEAL", "Step 9I run mode is not MORNING_DECISION_SEAL.")
    if stage in {"step9l", "step9s", "step9r", "upstream"}:
        require(l["sealed"], "Step 9L is not sealed for the session.")
        require(l["prospective_status"] == confirmatory, f"Step 9L status is {l.get('prospective_status')}.")
        require(l["run_mode"] == "MORNING_DECISION_SEAL", "Step 9L run mode is not MORNING_DECISION_SEAL.")
        require(i["primary_regime"] == l["primary_regime"], "Step 9I and Step 9L primary regimes disagree.")
    if stage in {"step9s", "step9r", "upstream"}:
        require(s["sealed"], "Step 9S is not sealed for the session.")
        require(s["prospective_status"] == confirmatory, f"Step 9S status is {s.get('prospective_status')}.")
        require(s["source_step9l_batch_id"] == l["batch_id"], "Step 9S does not reference today's Step 9L batch.")
        require(s["coverage_plan_rows"] == 1, "Step 9S must contain exactly one mandatory coverage plan.")
        require(s["point_in_time_pass"] == 1, "Step 9S point-in-time validation failed.")
        require(s["router_active"] == 0 and s["order_sent"] == 0, "Unsafe Step 9S routing state detected.")
    if stage in {"step9r", "upstream"}:
        require(r["sealed"], "Step 9R is not sealed for the session.")
        require(r["prospective_status"] == confirmatory, f"Step 9R status is {r.get('prospective_status')}.")
        require(r["evidence_eligible"] == 1, "Step 9R batch is not evidence eligible.")
        require(r["candidate_rows"] == r["candidate_rows_actual"], "Step 9R candidate count does not reconcile.")
        require(r["selected_rows"] == r["selected_rows_actual"], "Step 9R selected count does not reconcile.")
        require(0 <= r["selected_rows"] <= 2, "Step 9R selected-row count is outside 0-2.")

    payload["verified_stage"] = stage
    payload["status"] = "PASSED"
    payload["step9s_mandatory_control_active"] = bool(s.get("sealed", False))
    payload["step9u_mandatory_control_active"] = bool(payload["step9u"].get("mandatory_control_active", 0))
    payload["router_active"] = False
    payload["order_sent"] = False
    return payload


def write_json(payload: dict[str, Any], path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temp.replace(path)


def print_summary(payload: dict[str, Any]) -> None:
    print("STEP9_FULL_MORNING_CHAIN_STATUS")
    print(f"session_date: {payload['session_date']}")
    print(f"prices_ready: {payload['prices']['ready']}")
    for key in ["step9i", "step9l", "step9s", "step9r", "step9t", "step9u"]:
        print(f"{key}_sealed: {payload[key]['sealed']}")
    if payload["step9i"].get("sealed"):
        print(f"primary_regime: {payload['step9i'].get('primary_regime')}")
    if payload["step9r"].get("sealed"):
        print(f"step9r_candidates_selected: {payload['step9r'].get('candidate_rows')} / {payload['step9r'].get('selected_rows')}")
    if payload["step9u"].get("sealed"):
        print(f"step9u_selected: {payload['step9u'].get('selected_count')}")
    print("STEP 9S MANDATORY BENCHMARK CONTROL: TRUE WHEN STEP 9S IS SEALED")
    print("STEP 9U MANDATORY CONTROL: FALSE")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only status and validation for the complete Step 9 morning chain.")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--date", required=True)
    status.add_argument("--json-out", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("--date", required=True)
    verify.add_argument("--stage", choices=["step9i", "step9l", "step9s", "step9r", "upstream"], required=True)
    verify.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "status":
        payload = stage_status(args.date)
    else:
        payload = verify_stage(args.date, args.stage)
    write_json(payload, args.json_out)
    print_summary(payload)


if __name__ == "__main__":
    main()
