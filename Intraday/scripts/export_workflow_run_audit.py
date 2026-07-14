from datetime import datetime
from pathlib import Path

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import ORB_INITIAL_CAPITAL
from Intraday.core.paths import (
    DATA_DIR,
    ORB_SIGNAL_HISTORY,
    ORB_SIGNALS_LATEST,
    PAPER_TRADES,
)


PAPER_ACCOUNT_EQUITY_CURVE = DATA_DIR / "paper_account_equity_curve.csv"
POWERBI_WORKBOOK = DATA_DIR / "powerbi_exports.xlsx"
OUTPUT_PATH = DATA_DIR / "workflow_run_audit.csv"

INITIAL_CAPITAL = float(ORB_INITIAL_CAPITAL)

OUTPUT_COLUMNS = [
    "run_id",
    "run_timestamp",
    "latest_scan_date",
    "latest_last_bar",
    "latest_signal_rows",
    "invalid_signals",
    "not_triggered_signals",
    "triggered_signals",
    "signal_history_rows",
    "unique_signal_history_rows",
    "paper_trades",
    "open_trades",
    "closed_trades",
    "final_account_equity",
    "account_total_pnl",
    "account_max_drawdown_pct",
    "strategy_versions",
    "powerbi_workbook_exists",
    "validation_status",
    "validation_message",
]


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()

    return pd.read_csv(path)


def count_status(df: pd.DataFrame, status: str) -> int:
    if df.empty or "status" not in df.columns:
        return 0

    return int(
        (
            df["status"]
            .astype(str)
            .str.upper()
            .str.strip()
            == status.upper()
        ).sum()
    )


def get_latest_scan_date(signals: pd.DataFrame) -> str:
    if signals.empty or "scan_date" not in signals.columns:
        return ""

    values = signals["scan_date"].dropna().astype(str)

    if values.empty:
        return ""

    return str(values.max())


def get_latest_last_bar(signals: pd.DataFrame) -> str:
    if signals.empty or "last_bar" not in signals.columns:
        return ""

    values = signals["last_bar"].dropna().astype(str)

    if values.empty:
        return ""

    return str(values.max())


def get_strategy_versions(trades: pd.DataFrame) -> str:
    if trades.empty or "strategy_version" not in trades.columns:
        return ""

    versions = (
        trades["strategy_version"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    versions = sorted([version for version in versions.unique() if version])

    return ", ".join(versions)


def get_account_stats(
    trades: pd.DataFrame,
    account_curve: pd.DataFrame,
    errors: list[str],
) -> tuple[float, float, float]:
    if trades.empty:
        return INITIAL_CAPITAL, 0.0, 0.0

    if "status" not in trades.columns or "pnl_sek" not in trades.columns:
        errors.append("paper_trades missing status or pnl_sek for account audit.")
        return INITIAL_CAPITAL, 0.0, 0.0

    trades = trades.copy()
    trades["pnl_sek"] = pd.to_numeric(
        trades["pnl_sek"],
        errors="coerce",
    ).fillna(0.0)

    closed = trades[
        trades["status"].astype(str).str.upper().str.strip() == "CLOSED"
    ]

    expected_final_equity = INITIAL_CAPITAL + float(closed["pnl_sek"].sum())
    expected_total_pnl = float(closed["pnl_sek"].sum())

    if account_curve.empty:
        errors.append("paper_account_equity_curve is missing or empty.")
        return expected_final_equity, expected_total_pnl, 0.0

    account_curve = account_curve.copy()

    if "account_trade_number" not in account_curve.columns:
        errors.append("paper_account_equity_curve missing account_trade_number.")
        return expected_final_equity, expected_total_pnl, 0.0

    if "account_equity" not in account_curve.columns:
        errors.append("paper_account_equity_curve missing account_equity.")
        return expected_final_equity, expected_total_pnl, 0.0

    account_curve["account_trade_number"] = pd.to_numeric(
        account_curve["account_trade_number"],
        errors="coerce",
    )

    account_curve["account_equity"] = pd.to_numeric(
        account_curve["account_equity"],
        errors="coerce",
    )

    account_curve = account_curve.dropna(subset=["account_trade_number"])

    if account_curve.empty:
        errors.append("paper_account_equity_curve has no valid account_trade_number rows.")
        return expected_final_equity, expected_total_pnl, 0.0

    last_row = account_curve.sort_values("account_trade_number").tail(1)
    actual_final_equity = float(last_row["account_equity"].iloc[0])

    if abs(expected_final_equity - actual_final_equity) > 0.01:
        errors.append(
            "Account equity does not reconcile with closed paper trade PnL. "
            f"Expected {expected_final_equity:.2f}, got {actual_final_equity:.2f}."
        )

    max_drawdown_pct = 0.0

    if "account_drawdown_pct" in account_curve.columns:
        account_curve["account_drawdown_pct"] = pd.to_numeric(
            account_curve["account_drawdown_pct"],
            errors="coerce",
        )

        if not account_curve["account_drawdown_pct"].dropna().empty:
            max_drawdown_pct = float(account_curve["account_drawdown_pct"].min())

    return actual_final_equity, expected_total_pnl, max_drawdown_pct


def build_audit_row() -> dict:
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    errors: list[str] = []

    required_files = [
        ORB_SIGNALS_LATEST,
        ORB_SIGNAL_HISTORY,
        PAPER_TRADES,
        PAPER_ACCOUNT_EQUITY_CURVE,
    ]

    for path in required_files:
        if not path.exists():
            errors.append(f"Missing required file: {path.name}")
        elif path.stat().st_size == 0:
            errors.append(f"Required file is empty: {path.name}")

    latest_signals = read_csv_if_exists(ORB_SIGNALS_LATEST)
    signal_history = read_csv_if_exists(ORB_SIGNAL_HISTORY)
    paper_trades = read_csv_if_exists(PAPER_TRADES)
    account_curve = read_csv_if_exists(PAPER_ACCOUNT_EQUITY_CURVE)

    if latest_signals.empty:
        errors.append("orb_signals_latest is empty.")

    if signal_history.empty:
        errors.append("orb_signal_history is empty.")

    signal_history_rows = len(signal_history)
    unique_signal_history_rows = 0

    if not signal_history.empty and {"scan_date", "ticker"}.issubset(signal_history.columns):
        unique_signal_history_rows = len(
            signal_history.drop_duplicates(subset=["scan_date", "ticker"])
        )

        if signal_history_rows != unique_signal_history_rows:
            errors.append(
                "orb_signal_history contains duplicate scan_date + ticker rows."
            )

    final_account_equity, account_total_pnl, account_max_drawdown_pct = get_account_stats(
        trades=paper_trades,
        account_curve=account_curve,
        errors=errors,
    )

    validation_status = "PASSED" if not errors else "FAILED"
    validation_message = "Audit checks passed." if not errors else " | ".join(errors)

    return {
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "latest_scan_date": get_latest_scan_date(latest_signals),
        "latest_last_bar": get_latest_last_bar(latest_signals),
        "latest_signal_rows": len(latest_signals),
        "invalid_signals": count_status(latest_signals, "INVALID"),
        "not_triggered_signals": count_status(latest_signals, "NOT_TRIGGERED"),
        "triggered_signals": count_status(latest_signals, "TRIGGERED"),
        "signal_history_rows": signal_history_rows,
        "unique_signal_history_rows": unique_signal_history_rows,
        "paper_trades": len(paper_trades),
        "open_trades": count_status(paper_trades, "OPEN"),
        "closed_trades": count_status(paper_trades, "CLOSED"),
        "final_account_equity": final_account_equity,
        "account_total_pnl": account_total_pnl,
        "account_max_drawdown_pct": account_max_drawdown_pct,
        "strategy_versions": get_strategy_versions(paper_trades),
        "powerbi_workbook_exists": POWERBI_WORKBOOK.exists(),
        "validation_status": validation_status,
        "validation_message": validation_message,
    }


def load_existing_audit() -> pd.DataFrame:
    if not OUTPUT_PATH.exists() or OUTPUT_PATH.stat().st_size == 0:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    existing = pd.read_csv(OUTPUT_PATH, dtype={"run_id": str})

    for column in OUTPUT_COLUMNS:
        if column not in existing.columns:
            existing[column] = ""

    return existing[OUTPUT_COLUMNS]


def main() -> None:
    print("\n=== EXPORT WORKFLOW RUN AUDIT ===")

    audit_row = build_audit_row()
    existing = load_existing_audit()

    output = pd.concat(
        [
            existing,
            pd.DataFrame([audit_row]),
        ],
        ignore_index=True,
    )

    output = output.drop_duplicates(subset=["run_id"], keep="last")
    output = output.tail(500)

    export_csv_for_power_bi(
        output,
        OUTPUT_PATH,
        columns=OUTPUT_COLUMNS,
    )

    print(f"Rows in audit history: {len(output)}")
    print(f"Latest run id: {audit_row['run_id']}")
    print(f"Latest scan date: {audit_row['latest_scan_date']}")
    print(f"Triggered signals: {audit_row['triggered_signals']}")
    print(f"Paper trades: {audit_row['paper_trades']}")
    print(f"Open trades: {audit_row['open_trades']}")
    print(f"Closed trades: {audit_row['closed_trades']}")
    print(f"Final account equity: {audit_row['final_account_equity']:.2f} SEK")
    print(f"Validation status: {audit_row['validation_status']}")
    print(f"Saved -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()