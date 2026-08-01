from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, LEGACY_OUTPUT_DIRS
from RegimeTrading.scripts.research_regime_aware_gap_recovery import STRATEGY_ID


VALIDATION_STEP = "V1_VALIDATION_STEP_6_RECONCILIATION_GATE"
VALIDATION_STATUS = "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION"
RECONCILIATION_MODEL_ID = "STEP1_TO_STEP6_SAME_RUN_EXACT_RECONCILIATION_V1"
PNL_TOLERANCE_SEK = 0.000001

OUTPUT_DIR = LEGACY_OUTPUT_DIRS["v1_validation"]
PORTFOLIO_SUMMARY_FILE = OUTPUT_DIR / "v1_validation_portfolio_summary.csv"
PORTFOLIO_LEDGER_FILE = OUTPUT_DIR / "v1_validation_portfolio_trade_ledger.csv"
PORTFOLIO_EQUITY_FILE = OUTPUT_DIR / "v1_validation_portfolio_equity_curve.csv"
EXPOSURE_SUMMARY_FILE = OUTPUT_DIR / "v1_validation_exposure_efficiency_summary.csv"
EXPOSURE_POSITION_FILE = OUTPUT_DIR / "v1_validation_exposure_position_detail.csv"
EXPOSURE_DAILY_FILE = OUTPUT_DIR / "v1_validation_exposure_daily.csv"
POSITION_SIZE_SCENARIOS_FILE = OUTPUT_DIR / "v1_validation_position_size_scenarios.csv"
RECONCILIATION_FILE = OUTPUT_DIR / "v1_validation_exposure_reconciliation.csv"

RECONCILIATION_COLUMNS = [
    "strategy_id",
    "validation_step",
    "validation_status",
    "reconciliation_model_id",
    "pnl_tolerance_sek",
    "portfolio_summary_pnl_sek",
    "portfolio_ledger_closed_pnl_sek",
    "portfolio_equity_final_pnl_sek",
    "exposure_summary_pnl_sek",
    "exposure_position_closed_pnl_sek",
    "exposure_daily_pnl_sek",
    "position_size_baseline_pnl_sek",
    "max_absolute_pnl_difference_sek",
    "portfolio_summary_selected_closed",
    "portfolio_ledger_selected_closed",
    "exposure_summary_selected_closed",
    "exposure_position_selected_closed",
    "portfolio_summary_selected_open",
    "portfolio_ledger_selected_open",
    "exposure_summary_selected_open",
    "exposure_position_selected_open",
    "missing_exposure_trade_count",
    "extra_exposure_trade_count",
    "duplicate_exposure_trade_count",
    "missing_exposure_trade_ids",
    "extra_exposure_trade_ids",
    "duplicate_exposure_trade_ids",
    "pnl_reconciled",
    "closed_count_reconciled",
    "open_count_reconciled",
    "trade_identity_reconciled",
    "reconciliation_passed",
    "reconciliation_status",
    "likely_explanation",
    "generated_at_utc",
]


@dataclass(frozen=True)
class ReconciliationResult:
    report: pd.DataFrame
    passed: bool


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required reconciliation input is missing: {path}")
    return pd.read_csv(path)


def _numeric_scalar(frame: pd.DataFrame, column: str, default: float = np.nan) -> float:
    if frame.empty or column not in frame.columns:
        return float(default)
    value = pd.to_numeric(frame.iloc[0][column], errors="coerce")
    return float(value) if pd.notna(value) else float(default)


def _int_scalar(frame: pd.DataFrame, column: str, default: int = -1) -> int:
    value = _numeric_scalar(frame, column, float(default))
    return int(value) if np.isfinite(value) else int(default)


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _selected_ledger(ledger: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return ledger.copy()
    if "selected_for_portfolio" in ledger.columns:
        return ledger[_bool_series(ledger["selected_for_portfolio"])].copy()
    if "selection_status" in ledger.columns:
        return ledger[
            ledger["selection_status"].fillna("").astype(str).str.startswith("SELECTED")
        ].copy()
    return ledger.iloc[0:0].copy()


def _closed_exposure(position_detail: pd.DataFrame) -> pd.DataFrame:
    if position_detail.empty:
        return position_detail.copy()
    if "is_realized_closed_position" in position_detail.columns:
        return position_detail[_bool_series(position_detail["is_realized_closed_position"])].copy()
    return position_detail[
        position_detail.get("selection_status", pd.Series(index=position_detail.index, dtype=str))
        .fillna("")
        .astype(str)
        .eq("SELECTED_CLOSED")
    ].copy()


def _open_exposure(position_detail: pd.DataFrame) -> pd.DataFrame:
    if position_detail.empty:
        return position_detail.copy()
    if "is_open_position" in position_detail.columns:
        return position_detail[_bool_series(position_detail["is_open_position"])].copy()
    return position_detail[
        position_detail.get("selection_status", pd.Series(index=position_detail.index, dtype=str))
        .fillna("")
        .astype(str)
        .eq("SELECTED_OPEN")
    ].copy()


def _sum(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum())


def _final_equity_pnl(equity: pd.DataFrame) -> float:
    if equity.empty:
        return 0.0
    if "cumulative_pnl_sek" in equity.columns:
        values = pd.to_numeric(equity["cumulative_pnl_sek"], errors="coerce").dropna()
        if not values.empty:
            return float(values.iloc[-1])
    if "pnl_sek" in equity.columns:
        return _sum(equity, "pnl_sek")
    return np.nan


def _baseline_sizing_pnl(sizing: pd.DataFrame) -> float:
    if sizing.empty or "scaled_realized_pnl_sek" not in sizing.columns:
        return np.nan
    if "scenario_id" in sizing.columns:
        current = sizing[sizing["scenario_id"].astype(str).eq("CURRENT_V1")]
        if not current.empty:
            return _numeric_scalar(current, "scaled_realized_pnl_sek")
    return _numeric_scalar(sizing, "scaled_realized_pnl_sek")


def _trade_id_set(frame: pd.DataFrame) -> set[int]:
    if frame.empty or "source_trade_row" not in frame.columns:
        return set()
    values = pd.to_numeric(frame["source_trade_row"], errors="coerce").dropna().astype(int)
    return set(values.tolist())


def _duplicate_trade_ids(frame: pd.DataFrame) -> list[int]:
    if frame.empty or "source_trade_row" not in frame.columns:
        return []
    values = pd.to_numeric(frame["source_trade_row"], errors="coerce").dropna().astype(int)
    return sorted(values[values.duplicated(keep=False)].unique().tolist())


def _format_ids(values: set[int] | list[int]) -> str:
    return ";".join(str(value) for value in sorted(values))


def build_reconciliation(
    portfolio_summary: pd.DataFrame,
    portfolio_ledger: pd.DataFrame,
    portfolio_equity: pd.DataFrame,
    exposure_summary: pd.DataFrame,
    exposure_positions: pd.DataFrame,
    exposure_daily: pd.DataFrame,
    sizing_scenarios: pd.DataFrame,
    tolerance_sek: float = PNL_TOLERANCE_SEK,
) -> ReconciliationResult:
    selected = _selected_ledger(portfolio_ledger)
    selected_closed = selected[
        selected.get("selection_status", pd.Series(index=selected.index, dtype=str))
        .fillna("")
        .astype(str)
        .eq("SELECTED_CLOSED")
    ].copy()
    selected_open = selected[
        selected.get("selection_status", pd.Series(index=selected.index, dtype=str))
        .fillna("")
        .astype(str)
        .eq("SELECTED_OPEN")
    ].copy()
    exposure_closed = _closed_exposure(exposure_positions)
    exposure_open = _open_exposure(exposure_positions)

    pnl_values = {
        "portfolio_summary_pnl_sek": _numeric_scalar(
            portfolio_summary, "total_realized_pnl_sek"
        ),
        "portfolio_ledger_closed_pnl_sek": _sum(selected_closed, "portfolio_pnl_sek"),
        "portfolio_equity_final_pnl_sek": _final_equity_pnl(portfolio_equity),
        "exposure_summary_pnl_sek": _numeric_scalar(exposure_summary, "realized_pnl_sek"),
        "exposure_position_closed_pnl_sek": _sum(exposure_closed, "realized_pnl_sek"),
        "exposure_daily_pnl_sek": _sum(exposure_daily, "realized_pnl_sek"),
        "position_size_baseline_pnl_sek": _baseline_sizing_pnl(sizing_scenarios),
    }
    finite_pnl = [value for value in pnl_values.values() if np.isfinite(value)]
    max_difference = (
        float(max(finite_pnl) - min(finite_pnl)) if finite_pnl else np.inf
    )
    pnl_reconciled = len(finite_pnl) == len(pnl_values) and max_difference <= tolerance_sek

    closed_counts = {
        "portfolio_summary_selected_closed": _int_scalar(
            portfolio_summary, "selected_closed_trades"
        ),
        "portfolio_ledger_selected_closed": int(len(selected_closed)),
        "exposure_summary_selected_closed": _int_scalar(
            exposure_summary, "selected_closed_positions"
        ),
        "exposure_position_selected_closed": int(len(exposure_closed)),
    }
    open_counts = {
        "portfolio_summary_selected_open": _int_scalar(
            portfolio_summary, "selected_open_trades"
        ),
        "portfolio_ledger_selected_open": int(len(selected_open)),
        "exposure_summary_selected_open": _int_scalar(
            exposure_summary, "selected_open_positions"
        ),
        "exposure_position_selected_open": int(len(exposure_open)),
    }
    closed_count_reconciled = len(set(closed_counts.values())) == 1
    open_count_reconciled = len(set(open_counts.values())) == 1

    selected_ids = _trade_id_set(selected)
    exposure_ids = _trade_id_set(exposure_positions)
    missing_ids = selected_ids - exposure_ids
    extra_ids = exposure_ids - selected_ids
    duplicate_ids = _duplicate_trade_ids(exposure_positions)
    identity_reconciled = not missing_ids and not extra_ids and not duplicate_ids

    passed = bool(
        pnl_reconciled
        and closed_count_reconciled
        and open_count_reconciled
        and identity_reconciled
    )

    if passed:
        status = "PASS_EXACT_SAME_RUN_RECONCILIATION"
        explanation = (
            "Step 1 and Step 6 use the same current portfolio ledger and reconcile exactly. "
            "Any difference from an earlier printed result came from a different data snapshot or run."
        )
    elif not identity_reconciled:
        status = "FAIL_TRADE_IDENTITY_MISMATCH"
        explanation = "At least one selected portfolio trade is missing, duplicated, or unexpectedly added in Step 6."
    elif not closed_count_reconciled or not open_count_reconciled:
        status = "FAIL_POSITION_COUNT_MISMATCH"
        explanation = "Step 1 and Step 6 disagree on selected closed or open position counts."
    else:
        status = "FAIL_PNL_MISMATCH"
        explanation = "Step 1 and Step 6 disagree on realized PnL within the same run."

    row = {
        "strategy_id": STRATEGY_ID,
        "validation_step": VALIDATION_STEP,
        "validation_status": VALIDATION_STATUS,
        "reconciliation_model_id": RECONCILIATION_MODEL_ID,
        "pnl_tolerance_sek": tolerance_sek,
        **pnl_values,
        "max_absolute_pnl_difference_sek": max_difference,
        **closed_counts,
        **open_counts,
        "missing_exposure_trade_count": len(missing_ids),
        "extra_exposure_trade_count": len(extra_ids),
        "duplicate_exposure_trade_count": len(duplicate_ids),
        "missing_exposure_trade_ids": _format_ids(missing_ids),
        "extra_exposure_trade_ids": _format_ids(extra_ids),
        "duplicate_exposure_trade_ids": _format_ids(duplicate_ids),
        "pnl_reconciled": pnl_reconciled,
        "closed_count_reconciled": closed_count_reconciled,
        "open_count_reconciled": open_count_reconciled,
        "trade_identity_reconciled": identity_reconciled,
        "reconciliation_passed": passed,
        "reconciliation_status": status,
        "likely_explanation": explanation,
        "generated_at_utc": _now_utc(),
    }
    return ReconciliationResult(
        report=pd.DataFrame([row], columns=RECONCILIATION_COLUMNS), passed=passed
    )


def run_reconciliation() -> ReconciliationResult:
    return build_reconciliation(
        _load_csv(PORTFOLIO_SUMMARY_FILE),
        _load_csv(PORTFOLIO_LEDGER_FILE),
        _load_csv(PORTFOLIO_EQUITY_FILE),
        _load_csv(EXPOSURE_SUMMARY_FILE),
        _load_csv(EXPOSURE_POSITION_FILE),
        _load_csv(EXPOSURE_DAILY_FILE),
        _load_csv(POSITION_SIZE_SCENARIOS_FILE),
    )


def main() -> None:
    print("\n=== V1 VALIDATION SUITE - STEP 6 RECONCILIATION GATE ===")
    print(f"Model           : {RECONCILIATION_MODEL_ID}")
    print(f"PnL tolerance   : {PNL_TOLERANCE_SEK:.6f} SEK")
    print("Compares Step 1 and Step 6 outputs generated from the same current files.")

    result = run_reconciliation()
    export_csv_for_power_bi(result.report, RECONCILIATION_FILE)
    print(f"Saved {RECONCILIATION_FILE.name}: {len(result.report)} rows")

    row = result.report.iloc[0]
    print("\n=== STEP 6 RECONCILIATION RESULT ===")
    print(f"Step 1 summary PnL         : {float(row['portfolio_summary_pnl_sek']):.6f} SEK")
    print(f"Step 1 ledger PnL          : {float(row['portfolio_ledger_closed_pnl_sek']):.6f} SEK")
    print(f"Step 1 equity PnL          : {float(row['portfolio_equity_final_pnl_sek']):.6f} SEK")
    print(f"Step 6 summary PnL         : {float(row['exposure_summary_pnl_sek']):.6f} SEK")
    print(f"Step 6 position-detail PnL : {float(row['exposure_position_closed_pnl_sek']):.6f} SEK")
    print(f"Step 6 daily PnL           : {float(row['exposure_daily_pnl_sek']):.6f} SEK")
    print(f"Maximum PnL difference     : {float(row['max_absolute_pnl_difference_sek']):.9f} SEK")
    print(f"Closed positions           : {int(row['portfolio_summary_selected_closed'])}")
    print(f"Open positions             : {int(row['portfolio_summary_selected_open'])}")
    print(f"Missing/extra/duplicates   : {int(row['missing_exposure_trade_count'])}/{int(row['extra_exposure_trade_count'])}/{int(row['duplicate_exposure_trade_count'])}")
    print(f"Status                     : {row['reconciliation_status']}")

    if not result.passed:
        raise RuntimeError(
            "Step 6 reconciliation failed. Review v1_validation_exposure_reconciliation.csv."
        )

    print("Step 1 and Step 6 reconcile exactly for the current workflow run.")


if __name__ == "__main__":
    main()
