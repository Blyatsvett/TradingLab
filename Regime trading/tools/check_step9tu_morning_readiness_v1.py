from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from RegimeTrading.scripts import step9t_prospective_regime_transition_archetype_v1 as step9t
from RegimeTrading.scripts import step9u_prospective_contingency_selector_v1 as step9u


class MorningSafetyError(RuntimeError):
    pass


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(type(value).__name__)


def _write_json(payload: dict[str, Any], path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temp.replace(path)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _session_row_count(path: Path, table: str, session_date: str) -> int:
    if not path.is_file():
        return 0
    with closing(sqlite3.connect(path)) as connection:
        if not _table_exists(connection, table):
            return 0
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE session_date = ?",
                (session_date,),
            ).fetchone()[0]
        )


def compute_readiness(
    session_date: str,
    *,
    source_db: Path = step9t.DEFAULT_SOURCE_DB,
    step9l_ledger_db: Path = step9t.DEFAULT_STEP9L_LEDGER_DB,
    step9t_ledger_db: Path = step9t.DEFAULT_LEDGER_DB,
    step9u_ledger_db: Path = step9u.DEFAULT_LEDGER_DB,
    require_unsealed: bool = True,
) -> dict[str, Any]:
    pd.Timestamp(session_date)
    freeze_t = step9t._historical_freeze_provenance()
    freeze_u = step9u._historical_freeze_provenance()

    if require_unsealed:
        existing_t = _session_row_count(
            step9t_ledger_db, "step9t_prospective_batches", session_date
        )
        existing_u = _session_row_count(
            step9u_ledger_db, "step9u_prospective_assignment_batches", session_date
        )
        if existing_t or existing_u:
            raise MorningSafetyError(
                "The session is already sealed in a real prospective ledger: "
                f"Step9T={existing_t}, Step9U={existing_u}. Do not rerun sealed engines."
            )

    source_batch, _, decision_set_hash = step9t._read_step9l_morning(
        session_date, step9l_ledger_db
    )
    prices, source_provenance = step9t._load_prices_canonical(source_db, session_date)
    if str(prices["clock"].max()) < step9t.LATEST_MORNING_LABEL:
        raise MorningSafetyError(
            f"Morning prices are not ready through {step9t.LATEST_MORNING_LABEL}."
        )

    universe = step9t.historical._load_universe(
        step9t.historical.DEFAULT_CORE_REGISTRY,
        step9t.historical.DEFAULT_HOLDOUT_REGISTRY,
    )
    rows: list[dict[str, Any]] = []
    for ticker in universe.to_dict("records"):
        rows.append(
            step9t.classify_ticker_assignment(
                session_date,
                pd.Series(ticker),
                prices[prices["ticker"].eq(str(ticker["ticker"]))],
            )
        )
    archetypes = pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)
    if len(archetypes) != step9t.EXPECTED_UNIVERSE_SIZE:
        raise MorningSafetyError(
            f"Expected {step9t.EXPECTED_UNIVERSE_SIZE} ticker assignments; "
            f"computed {len(archetypes)}."
        )
    if bool((archetypes["max_source_label_used"] > step9t.LATEST_MORNING_LABEL).any()):
        raise MorningSafetyError("A readiness row used a bar later than 09:45.")

    transition_state, features = step9t.historical.classify_transition(archetypes)
    morning_hash = step9t._morning_price_snapshot_hash(prices, session_date)
    batch_id = f"S9T-{session_date.replace('-', '')}-MORNING"
    stored_archetypes: list[dict[str, Any]] = []
    for row in rows:
        stored = {"batch_id": batch_id, **row}
        stored["row_payload_hash"] = step9t._payload_hash(
            {key: value for key, value in stored.items() if key != "row_payload_hash"}
        )
        stored_archetypes.append(stored)

    ticker_set_hash = step9t._payload_hash(
        [
            row["ticker_row_id"]
            for row in sorted(stored_archetypes, key=lambda item: item["ticker"])
        ]
    )
    synthetic_batch = {
        "source_regime": str(source_batch["primary_regime"]),
        "transition_state": str(transition_state),
    }
    candidates = step9u.build_candidate_assignments(
        synthetic_batch, stored_archetypes
    )
    candidate_set_hash = step9u._payload_hash(
        [
            row["candidate_id"]
            for row in sorted(candidates, key=lambda item: item["ticker"])
        ]
    )
    selected = sorted(
        [row for row in candidates if int(row["selected"]) == 1],
        key=lambda row: int(row["selected_rank"]),
    )

    payload: dict[str, Any] = {
        "status": "READY_FOR_POINT_IN_TIME_SEAL",
        "session_date": session_date,
        "step9t_freeze_id": freeze_t["freeze_id"],
        "step9u_freeze_id": freeze_u["freeze_id"],
        "source_step9l_batch_id": str(source_batch["batch_id"]),
        "source_step9l_batch_payload_hash": str(source_batch["batch_payload_hash"]),
        "source_step9l_decision_set_hash": str(decision_set_hash),
        "morning_price_snapshot_hash": str(morning_hash),
        "source_regime": str(source_batch["primary_regime"]),
        "transition_state": str(transition_state),
        "ticker_set_hash": str(ticker_set_hash),
        "candidate_set_hash": str(candidate_set_hash),
        "ticker_rows": int(len(archetypes)),
        "morning_complete_rows": int(archetypes["morning_status"].eq("MORNING_COMPLETE").sum()),
        "morning_incomplete_rows": int(archetypes["morning_status"].ne("MORNING_COMPLETE").sum()),
        "directional_candidates": int(len(candidates)),
        "selectable_candidates": int(sum(int(row["selection_eligible"]) for row in candidates)),
        "selected_count": int(len(selected)),
        "selected_tickers": [str(row["ticker"]) for row in selected],
        "selected_rule_ids": [str(row["rule_id"]) for row in selected],
        "source_max_datetime": str(source_provenance["source_max_datetime"]),
        "raw_source_rows": int(source_provenance["raw_row_count"]),
        "canonical_source_rows": int(source_provenance["canonical_row_count"]),
        "conflicting_minute_count": int(source_provenance["conflicting_minute_count"]),
        "features": {key: step9t._clean_scalar(value) for key, value in features.items()},
        "mandatory_control_active": False,
        "router_active": False,
        "orders_enabled": False,
    }
    return payload


def verify_sealed(
    session_date: str,
    preview: dict[str, Any],
    *,
    step9t_ledger_db: Path = step9t.DEFAULT_LEDGER_DB,
    step9u_ledger_db: Path = step9u.DEFAULT_LEDGER_DB,
) -> dict[str, Any]:
    source_batch, archetypes = step9u._read_step9t_morning(
        session_date, step9t_ledger_db
    )
    assignment_batch, candidates = step9u._read_existing_assignment(
        step9u_ledger_db, session_date
    )
    if assignment_batch is None:
        raise MorningSafetyError("Step 9U morning assignment was not sealed.")

    comparisons = {
        "source_step9l_batch_id": str(source_batch["source_step9l_batch_id"]),
        "source_step9l_batch_payload_hash": str(source_batch["source_step9l_batch_payload_hash"]),
        "source_step9l_decision_set_hash": str(source_batch["source_step9l_decision_set_hash"]),
        "morning_price_snapshot_hash": str(source_batch["morning_price_snapshot_hash"]),
        "source_regime": str(source_batch["source_regime"]),
        "transition_state": str(source_batch["transition_state"]),
        "ticker_set_hash": step9t._payload_hash(
            [row["ticker_row_id"] for row in sorted(archetypes, key=lambda item: item["ticker"])]
        ),
        "candidate_set_hash": str(assignment_batch["candidate_set_hash"]),
    }
    for key, actual in comparisons.items():
        expected = str(preview[key])
        if str(actual) != expected:
            raise MorningSafetyError(
                f"Sealed ledger differs from the read-only preview for {key}: "
                f"expected={expected}, actual={actual}"
            )

    selected = sorted(
        [row for row in candidates if int(row["selected"]) == 1],
        key=lambda row: int(row["selected_rank"]),
    )
    selected_tickers = [str(row["ticker"]) for row in selected]
    if selected_tickers != list(preview["selected_tickers"]):
        raise MorningSafetyError(
            f"Selected ticker mismatch: preview={preview['selected_tickers']}, "
            f"sealed={selected_tickers}"
        )
    if int(assignment_batch["selected_count"]) != int(preview["selected_count"]):
        raise MorningSafetyError("Selected-count mismatch after sealing.")
    if int(assignment_batch["point_in_time_pass"]) != 1:
        raise MorningSafetyError("Step 9U point-in-time flag is not 1.")
    if any(
        int(assignment_batch[field]) != 0
        for field in ["mandatory_control_active", "router_active", "order_sent"]
    ):
        raise MorningSafetyError("Unsafe Step 9U sealed state detected.")

    audit_t = step9t.audit_ledger(step9t_ledger_db)
    audit_u = step9u.audit_ledger(step9u_ledger_db)
    if not bool(audit_t["passed"].all()):
        raise MorningSafetyError(
            f"Step 9T morning audit failed: {audit_t[~audit_t['passed']].to_dict('records')}"
        )
    if not bool(audit_u["passed"].all()):
        raise MorningSafetyError(
            f"Step 9U morning audit failed: {audit_u[~audit_u['passed']].to_dict('records')}"
        )

    return {
        "status": "SEALED_AND_VERIFIED",
        "session_date": session_date,
        "step9t_batch_id": str(source_batch["batch_id"]),
        "step9u_assignment_batch_id": str(assignment_batch["assignment_batch_id"]),
        "source_regime": str(assignment_batch["source_regime"]),
        "transition_state": str(assignment_batch["transition_state"]),
        "directional_candidates": int(assignment_batch["directional_candidate_rows"]),
        "selectable_candidates": int(assignment_batch["selectable_candidate_rows"]),
        "selected_count": int(assignment_batch["selected_count"]),
        "selected_tickers": selected_tickers,
        "step9t_audit_passed": int(audit_t["passed"].sum()),
        "step9u_audit_passed": int(audit_u["passed"].sum()),
        "mandatory_control_active": False,
        "router_active": False,
        "order_sent": False,
    }


def _print_payload(title: str, payload: dict[str, Any]) -> None:
    print(title)
    for key in [
        "status",
        "session_date",
        "source_regime",
        "transition_state",
        "ticker_rows",
        "morning_complete_rows",
        "morning_incomplete_rows",
        "directional_candidates",
        "selectable_candidates",
        "selected_count",
        "selected_tickers",
        "source_max_datetime",
        "conflicting_minute_count",
        "step9t_batch_id",
        "step9u_assignment_batch_id",
        "step9t_audit_passed",
        "step9u_audit_passed",
    ]:
        if key in payload:
            print(f"{key}: {payload[key]}")
    print("MANDATORY CONTROL ACTIVE: FALSE")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only readiness and post-seal verification for Step 9T -> Step 9U."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    readiness = sub.add_parser("readiness")
    readiness.add_argument("--date", required=True)
    readiness.add_argument("--source-db", type=Path, default=step9t.DEFAULT_SOURCE_DB)
    readiness.add_argument("--step9l-ledger-db", type=Path, default=step9t.DEFAULT_STEP9L_LEDGER_DB)
    readiness.add_argument("--step9t-ledger-db", type=Path, default=step9t.DEFAULT_LEDGER_DB)
    readiness.add_argument("--step9u-ledger-db", type=Path, default=step9u.DEFAULT_LEDGER_DB)
    readiness.add_argument("--allow-existing", action="store_true")
    readiness.add_argument("--json-out", type=Path)

    verify = sub.add_parser("verify-sealed")
    verify.add_argument("--date", required=True)
    verify.add_argument("--preview-json", type=Path, required=True)
    verify.add_argument("--step9t-ledger-db", type=Path, default=step9t.DEFAULT_LEDGER_DB)
    verify.add_argument("--step9u-ledger-db", type=Path, default=step9u.DEFAULT_LEDGER_DB)
    verify.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "readiness":
        payload = compute_readiness(
            args.date,
            source_db=args.source_db,
            step9l_ledger_db=args.step9l_ledger_db,
            step9t_ledger_db=args.step9t_ledger_db,
            step9u_ledger_db=args.step9u_ledger_db,
            require_unsealed=not bool(args.allow_existing),
        )
        _write_json(payload, args.json_out)
        _print_payload("=== STEP 9T -> STEP 9U READ-ONLY MORNING READINESS ===", payload)
        return

    preview = json.loads(args.preview_json.read_text(encoding="utf-8"))
    payload = verify_sealed(
        args.date,
        preview,
        step9t_ledger_db=args.step9t_ledger_db,
        step9u_ledger_db=args.step9u_ledger_db,
    )
    _write_json(payload, args.json_out)
    _print_payload("=== STEP 9T -> STEP 9U SEALED MORNING VERIFICATION ===", payload)


if __name__ == "__main__":
    main()
