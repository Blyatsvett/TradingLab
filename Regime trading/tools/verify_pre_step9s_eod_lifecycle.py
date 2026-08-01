from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from argparse import Namespace
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as step9l
from RegimeTrading.scripts import step9q_powerbi_excel_feed as step9q


SESSION_DATE = "2026-07-27"
MORNING_CLOCK = "2026-07-27 09:46:30"
EOD_CLOCK = "2026-07-27 17:40:00"
EOD_RERUN_CLOCK = "2026-07-27 17:41:00"


class VerificationFailure(AssertionError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> tuple[Path, ...]:
    data = PROJECT_ROOT / "data"
    return (
        data / "intraday_prices.db",
        data / "step9i_shadow_intraday_prices.db",
        data / "step9i_v2_shadow_ledger.db",
        data / "step9l_v3_selected_strategy_shadow_ledger.db",
        PROJECT_ROOT / "config" / "step9q_powerbi_schema_v1.json",
    )


def _snapshot(paths: tuple[Path, ...]) -> dict[Path, tuple[int, str]]:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required protected files are missing: {missing}")
    return {path: (path.stat().st_size, _sha256(path)) for path in paths}


def _assert_snapshot_unchanged(before: dict[Path, tuple[int, str]]) -> None:
    changed: list[str] = []
    for path, expected in before.items():
        actual = (path.stat().st_size, _sha256(path))
        if actual != expected:
            changed.append(str(path))
    if changed:
        raise VerificationFailure(f"Protected real files changed: {changed}")


def _sqlite_uri(path: Path) -> str:
    return f"file:{path.resolve().as_posix()}?mode=ro"


def _read_table_read_only(path: Path, table: str, session_date: str | None = None) -> pd.DataFrame:
    query = f"SELECT * FROM {table}"
    params: tuple[Any, ...] = ()
    if session_date is not None:
        query += " WHERE session_date = ?"
        params = (session_date,)
    with closing(sqlite3.connect(_sqlite_uri(path), uri=True)) as connection:
        frame = pd.read_sql_query(query, connection, params=params)
    return frame


def _canonical_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except ValueError:
            pass
    return value


def _frame_fingerprint(frame: pd.DataFrame, sort_columns: list[str]) -> str:
    ordered = frame.copy()
    if sort_columns:
        ordered = ordered.sort_values(sort_columns, kind="stable")
    records = [
        {column: _canonical_value(row[column]) for column in ordered.columns}
        for row in ordered.to_dict("records")
    ]
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _morning_fingerprint(ledger: Path) -> dict[str, tuple[int, str]]:
    batches = _read_table_read_only(ledger, "shadow_decision_batches", SESSION_DATE)
    decisions = _read_table_read_only(ledger, "shadow_decisions", SESSION_DATE)
    return {
        "shadow_decision_batches": (len(batches), _frame_fingerprint(batches, ["batch_id"])),
        "shadow_decisions": (len(decisions), _frame_fingerprint(decisions, ["decision_id"])),
    }


def _outcome_fingerprint(ledger: Path) -> dict[str, tuple[int, str]]:
    batches = _read_table_read_only(ledger, "shadow_outcome_batches", SESSION_DATE)
    outcomes = _read_table_read_only(ledger, "shadow_outcomes", SESSION_DATE)
    return {
        "shadow_outcome_batches": (len(batches), _frame_fingerprint(batches, ["outcome_batch_id"])),
        "shadow_outcomes": (len(outcomes), _frame_fingerprint(outcomes, ["outcome_id"])),
    }


def _normalise_for_comparison(frame: pd.DataFrame, excluded: set[str], sort_columns: list[str]) -> pd.DataFrame:
    columns = [column for column in frame.columns if column not in excluded]
    result = frame[columns].copy()
    result = result.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    for column in result.columns:
        result[column] = result[column].map(_canonical_value)
    return result


def _assert_reproduces_real_ledger(temp_ledger: Path, real_ledger: Path) -> None:
    temp_decisions = _read_table_read_only(temp_ledger, "shadow_decisions", SESSION_DATE)
    real_decisions = _read_table_read_only(real_ledger, "shadow_decisions", SESSION_DATE)
    temp_outcomes = _read_table_read_only(temp_ledger, "shadow_outcomes", SESSION_DATE)
    real_outcomes = _read_table_read_only(real_ledger, "shadow_outcomes", SESSION_DATE)

    decision_excluded = {"sealed_at_stockholm", "row_payload_hash"}
    outcome_excluded = {"evaluated_at_stockholm", "row_payload_hash"}

    left = _normalise_for_comparison(temp_decisions, decision_excluded, ["decision_id"])
    right = _normalise_for_comparison(real_decisions, decision_excluded, ["decision_id"])
    pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=False, rtol=1e-12, atol=1e-12)

    left = _normalise_for_comparison(temp_outcomes, outcome_excluded, ["outcome_id"])
    right = _normalise_for_comparison(real_outcomes, outcome_excluded, ["outcome_id"])
    pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=False, rtol=1e-12, atol=1e-12)


def _assert_conflicting_duplicate_rejected(ledger: Path) -> None:
    with closing(sqlite3.connect(ledger)) as connection:
        connection.row_factory = sqlite3.Row
        existing = connection.execute(
            "SELECT * FROM shadow_decisions WHERE session_date = ? ORDER BY decision_id LIMIT 1",
            (SESSION_DATE,),
        ).fetchone()
        if existing is None:
            raise VerificationFailure("No sealed morning decision exists for the immutability conflict probe.")
        conflicting = dict(existing)
        conflicting["row_payload_hash"] = "0" * 64
        try:
            step9i.base._insert_immutable(
                connection,
                "shadow_decisions",
                "decision_id",
                "row_payload_hash",
                conflicting,
            )
        except step9i.base.ImmutableLedgerConflict:
            connection.rollback()
            return
        connection.rollback()
        raise VerificationFailure("Conflicting duplicate morning decision was not rejected.")


def _run_engine_lifecycle(
    name: str,
    module: Any,
    real_ledger: Path,
    temp_ledger: Path,
    prices: pd.DataFrame,
    source_db: Path,
    expected_eligible: int,
    expected_guardrails: int,
    expected_completed: int,
) -> dict[str, Any]:
    morning_now = module._parse_stockholm_datetime(MORNING_CLOCK)
    eod_now = module._parse_stockholm_datetime(EOD_CLOCK)
    eod_rerun_now = module._parse_stockholm_datetime(EOD_RERUN_CLOCK)

    batch, decisions, inserted = module.seal_morning_decisions(
        target_date=SESSION_DATE,
        now=morning_now,
        prices=prices,
        ledger_db=temp_ledger,
        source_db=source_db,
        allow_late=False,
        export_outputs_after=False,
        simulated_clock=True,
    )
    if not inserted:
        raise VerificationFailure(f"{name}: fresh temporary morning batch was not inserted.")
    if len(decisions) != 184:
        raise VerificationFailure(f"{name}: expected 184 decisions, received {len(decisions)}.")
    eligible = int(decisions["contract_eligible"].astype(bool).sum())
    guardrails = int(decisions["decision_action"].eq("GUARDRAIL_ACTIVE_AVOID_STRATEGY").sum())
    regime = str(batch.iloc[0]["primary_regime"])
    if regime != "HIGH_VOL_REVERSAL":
        raise VerificationFailure(f"{name}: expected HIGH_VOL_REVERSAL, received {regime}.")
    if eligible != expected_eligible or guardrails != expected_guardrails:
        raise VerificationFailure(
            f"{name}: expected eligible/guardrails {expected_eligible}/{expected_guardrails}, "
            f"received {eligible}/{guardrails}."
        )

    _, repeated_decisions, repeated_inserted = module.seal_morning_decisions(
        target_date=SESSION_DATE,
        now=morning_now,
        prices=prices,
        ledger_db=temp_ledger,
        source_db=source_db,
        allow_late=False,
        export_outputs_after=False,
        simulated_clock=True,
    )
    if repeated_inserted or len(repeated_decisions) != 184:
        raise VerificationFailure(f"{name}: identical morning rerun was not idempotent.")

    morning_before_eod = _morning_fingerprint(temp_ledger)
    _assert_conflicting_duplicate_rejected(temp_ledger)
    if _morning_fingerprint(temp_ledger) != morning_before_eod:
        raise VerificationFailure(f"{name}: immutability conflict probe changed morning rows.")

    _, outcomes, eod_inserted = module.evaluate_eod(
        target_date=SESSION_DATE,
        now=eod_now,
        prices=prices,
        ledger_db=temp_ledger,
        source_db=source_db,
        allow_early=False,
        export_outputs_after=False,
    )
    if not eod_inserted or len(outcomes) != 184:
        raise VerificationFailure(f"{name}: initial EOD evaluation did not seal 184 outcomes.")
    completed = int(outcomes["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED").sum())
    if completed != expected_completed:
        raise VerificationFailure(f"{name}: expected {expected_completed} completed outcomes, received {completed}.")
    if _morning_fingerprint(temp_ledger) != morning_before_eod:
        raise VerificationFailure(f"{name}: EOD evaluation changed sealed morning rows.")

    first_outcome_fingerprint = _outcome_fingerprint(temp_ledger)
    _, repeated_outcomes, repeated_eod_inserted = module.evaluate_eod(
        target_date=SESSION_DATE,
        now=eod_rerun_now,
        prices=prices,
        ledger_db=temp_ledger,
        source_db=source_db,
        allow_early=False,
        export_outputs_after=False,
    )
    if repeated_eod_inserted or len(repeated_outcomes) != 184:
        raise VerificationFailure(f"{name}: EOD rerun was not idempotent.")
    if _outcome_fingerprint(temp_ledger) != first_outcome_fingerprint:
        raise VerificationFailure(f"{name}: EOD rerun changed sealed outcome rows.")
    if _morning_fingerprint(temp_ledger) != morning_before_eod:
        raise VerificationFailure(f"{name}: EOD rerun changed sealed morning rows.")

    _assert_reproduces_real_ledger(temp_ledger, real_ledger)

    primary = outcomes[
        outcomes["test_role"].eq("PRIMARY_HYPOTHESIS")
        & outcomes["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED")
    ].copy()
    guardrail = outcomes[
        outcomes["test_role"].eq("NEGATIVE_GUARDRAIL")
        & outcomes["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED")
    ].copy()
    primary_pnl = float(pd.to_numeric(primary["risk_capped_net_pnl_sek"], errors="coerce").fillna(0.0).sum())
    guardrail_pnl = float(pd.to_numeric(guardrail["risk_capped_net_pnl_sek"], errors="coerce").fillna(0.0).sum())

    return {
        "name": name,
        "decision_rows": len(decisions),
        "eligible_rows": eligible,
        "active_guardrails": guardrails,
        "outcome_rows": len(outcomes),
        "completed_outcomes": completed,
        "primary_completed": len(primary),
        "guardrail_completed": len(guardrail),
        "primary_risk_capped_pnl_sek": primary_pnl,
        "guardrail_risk_capped_pnl_sek": guardrail_pnl,
    }


def _verify_step9q(real_step9i_ledger: Path, real_step9l_ledger: Path, price_db: Path, schema: Path, output: Path) -> dict[str, Any]:
    result = step9q.run(
        Namespace(
            date=SESSION_DATE,
            step9i_ledger=real_step9i_ledger,
            step9l_ledger=real_step9l_ledger,
            price_db=price_db,
            schema=schema,
            output=output,
            stale_after_minutes=15.0,
            require_both_engines=True,
        )
    )
    if not output.exists() or output.stat().st_size <= 0:
        raise VerificationFailure("Step 9Q did not create a valid temporary workbook.")
    if int(result["step9i_rows"]) != 184 or int(result["step9l_rows"]) != 184:
        raise VerificationFailure(
            f"Step 9Q expected 184/184 rows, received {result['step9i_rows']}/{result['step9l_rows']}."
        )
    return result


def main() -> None:
    protected_paths = _protected_paths()
    before = _snapshot(protected_paths)

    data = PROJECT_ROOT / "data"
    price_db = data / "step9i_shadow_intraday_prices.db"
    real_step9i_ledger = data / "step9i_v2_shadow_ledger.db"
    real_step9l_ledger = data / "step9l_v3_selected_strategy_shadow_ledger.db"
    schema = PROJECT_ROOT / "config" / "step9q_powerbi_schema_v1.json"

    prices = step9i.load_shadow_prices(price_db)
    if prices.empty:
        raise VerificationFailure("The shadow price database is empty.")

    with tempfile.TemporaryDirectory(prefix="pre_step9s_eod_lifecycle_") as temp_name:
        temp_root = Path(temp_name)
        temp_step9i = temp_root / "step9i_v2_lifecycle.db"
        temp_step9l = temp_root / "step9l_v3_lifecycle.db"
        temp_step9q = temp_root / "step9q_real_sealed_read_only.xlsx"

        step9i_result = _run_engine_lifecycle(
            name="STEP9I_V2",
            module=step9i,
            real_ledger=real_step9i_ledger,
            temp_ledger=temp_step9i,
            prices=prices,
            source_db=price_db,
            expected_eligible=0,
            expected_guardrails=0,
            expected_completed=0,
        )
        step9l_result = _run_engine_lifecycle(
            name="STEP9L_V3",
            module=step9l,
            real_ledger=real_step9l_ledger,
            temp_ledger=temp_step9l,
            prices=prices,
            source_db=price_db,
            expected_eligible=32,
            expected_guardrails=9,
            expected_completed=4,
        )
        step9q_result = _verify_step9q(
            real_step9i_ledger=real_step9i_ledger,
            real_step9l_ledger=real_step9l_ledger,
            price_db=price_db,
            schema=schema,
            output=temp_step9q,
        )

        _assert_snapshot_unchanged(before)

        print("PRE_STEP9S_EOD_LIFECYCLE_VERIFICATION: PASSED")
        print(f"SESSION_DATE: {SESSION_DATE}")
        print(
            "STEP9I_V2: "
            f"{step9i_result['decision_rows']} morning rows / "
            f"{step9i_result['eligible_rows']} eligible / "
            f"{step9i_result['outcome_rows']} EOD rows / "
            f"{step9i_result['completed_outcomes']} completed trades"
        )
        print(
            "STEP9L_V3: "
            f"{step9l_result['decision_rows']} morning rows / "
            f"{step9l_result['eligible_rows']} eligible / "
            f"{step9l_result['active_guardrails']} active guardrails / "
            f"{step9l_result['outcome_rows']} EOD rows / "
            f"{step9l_result['primary_completed']} primary completed / "
            f"{step9l_result['guardrail_completed']} counterfactual guardrail completed"
        )
        print(
            "STEP9L_V3_PRIMARY_RISK_CAPPED_PNL_SEK: "
            f"{step9l_result['primary_risk_capped_pnl_sek']:.6f}"
        )
        print(
            "STEP9L_V3_COUNTERFACTUAL_GUARDRAIL_PNL_SEK: "
            f"{step9l_result['guardrail_risk_capped_pnl_sek']:.6f}"
        )
        print("MORNING_IMMUTABILITY: PASSED (unchanged through EOD; conflicting duplicate rejected)")
        print("EOD_IDEMPOTENCY: PASSED (identical reruns returned existing outcomes)")
        print("REAL_LEDGER_REPRODUCTION: PASSED (decision/outcome content matches July 27 sealed ledgers)")
        print(
            "STEP9Q_REAL_SEALED_READ_ONLY: PASSED "
            f"({step9q_result['step9i_rows']}/{step9q_result['step9l_rows']} rows; temporary workbook validated)"
        )
        print("PROTECTED_REAL_FILES: BYTE_FOR_BYTE_UNCHANGED")
        print("TEMPORARY_LEDGERS_AND_WORKBOOK: DELETED")
        print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
