from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from argparse import Namespace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as step9l
from RegimeTrading.scripts import step9q_powerbi_excel_feed as step9q


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> tuple[Path, Path, Path, Path]:
    data_dir = PROJECT_ROOT / "data"
    return (
        data_dir / "step9i_shadow_intraday_prices.db",
        data_dir / "step9i_v2_shadow_ledger.db",
        data_dir / "step9l_v3_selected_strategy_shadow_ledger.db",
        PROJECT_ROOT / "config" / "step9q_powerbi_schema_v1.json",
    )


def _snapshot(paths: tuple[Path, ...]) -> dict[Path, str]:
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
    return {path: _sha256(path) for path in paths}


def _assert_unchanged(before: dict[Path, str]) -> None:
    changed = [str(path) for path, digest in before.items() if _sha256(path) != digest]
    if changed:
        raise AssertionError(f"Protected files changed during verification: {changed}")


def verify_step9i(source_db: Path) -> None:
    prices = step9i.load_shadow_prices(source_db)
    with tempfile.TemporaryDirectory(prefix="step9e_verify_step9i_") as temp_name:
        ledger = Path(temp_name) / "step9i_validation.db"
        batch, decisions, inserted = step9i.seal_morning_decisions(
            target_date="2026-07-28",
            now=step9i._parse_stockholm_datetime("2026-07-28 09:46:07"),
            prices=prices,
            ledger_db=ledger,
            source_db=source_db,
            allow_late=False,
            export_outputs_after=False,
            simulated_clock=True,
        )
        assert inserted
        assert len(decisions) == 184
        assert int(decisions["contract_eligible"].astype(bool).sum()) == 0
        assert str(batch.iloc[0]["primary_regime"]) == "TREND_DOWN"
        _, repeated, repeated_inserted = step9i.seal_morning_decisions(
            target_date="2026-07-28",
            now=step9i._parse_stockholm_datetime("2026-07-28 09:46:07"),
            prices=prices,
            ledger_db=ledger,
            source_db=source_db,
            allow_late=False,
            export_outputs_after=False,
            simulated_clock=True,
        )
        assert not repeated_inserted
        assert len(repeated) == 184
    print("STEP9I_FRESH_MORNING_VALIDATION: PASSED")
    print("184 decisions / 0 eligible / TREND_DOWN; identical rerun returned existing batch")


def verify_step9l(source_db: Path) -> None:
    prices = step9l.load_shadow_prices(source_db)
    with tempfile.TemporaryDirectory(prefix="step9e_verify_step9l_") as temp_name:
        ledger = Path(temp_name) / "step9l_validation.db"
        batch, decisions, inserted = step9l.seal_morning_decisions(
            target_date="2026-07-28",
            now=step9l._parse_stockholm_datetime("2026-07-28 09:46:59"),
            prices=prices,
            ledger_db=ledger,
            source_db=source_db,
            allow_late=False,
            export_outputs_after=False,
            simulated_clock=True,
        )
        assert inserted
        assert len(decisions) == 184
        assert int(decisions["contract_eligible"].astype(bool).sum()) == 0
        assert str(batch.iloc[0]["primary_regime"]) == "TREND_DOWN"
        _, repeated, repeated_inserted = step9l.seal_morning_decisions(
            target_date="2026-07-28",
            now=step9l._parse_stockholm_datetime("2026-07-28 09:46:59"),
            prices=prices,
            ledger_db=ledger,
            source_db=source_db,
            allow_late=False,
            export_outputs_after=False,
            simulated_clock=True,
        )
        assert not repeated_inserted
        assert len(repeated) == 184
    print("STEP9L_FRESH_MORNING_VALIDATION: PASSED")
    print("184 decisions / 0 eligible / TREND_DOWN; identical rerun returned existing batch")


def verify_step9q(source_db: Path, step9i_ledger: Path, step9l_ledger: Path, schema: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="step9e_verify_step9q_") as temp_name:
        output = Path(temp_name) / "step9q_validation.xlsx"
        result = step9q.run(
            Namespace(
                date="2026-07-28",
                step9i_ledger=step9i_ledger,
                step9l_ledger=step9l_ledger,
                price_db=source_db,
                schema=schema,
                output=output,
                stale_after_minutes=15.0,
                require_both_engines=True,
            )
        )
        assert output.exists()
        assert result["step9i_rows"] == 184
        assert result["step9l_rows"] == 184
    print("STEP9Q_READ_ONLY_VALIDATION: PASSED")
    print(f"Step 9I/Step 9L rows: {result['step9i_rows']}/{result['step9l_rows']}; temporary workbook validated")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only isolated validation for the Step 9E source-label reliability patch.")
    parser.add_argument("stage", choices=["step9i", "step9l", "step9q"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db, step9i_ledger, step9l_ledger, schema = _protected_paths()
    protected = (source_db, step9i_ledger, step9l_ledger)
    before = _snapshot(protected)

    if args.stage == "step9i":
        verify_step9i(source_db)
    elif args.stage == "step9l":
        verify_step9l(source_db)
    else:
        verify_step9q(source_db, step9i_ledger, step9l_ledger, schema)

    _assert_unchanged(before)
    print("PROTECTED_DATABASE_HASHES: UNCHANGED")
    print("No real ledger was written and no order was sent.")


if __name__ == "__main__":
    main()
