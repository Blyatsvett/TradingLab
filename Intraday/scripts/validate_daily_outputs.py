import sys
from pathlib import Path

import pandas as pd

from Intraday.core.orb_config import ORB_INITIAL_CAPITAL
from Intraday.core.paths import (
    DATA_DIR,
    ORB_SIGNAL_HISTORY,
    ORB_SIGNALS_LATEST,
    PAPER_EQUITY_CURVE,
    PAPER_TRADES,
)


POWERBI_WORKBOOK = DATA_DIR / "powerbi_exports.xlsx"
PAPER_ACCOUNT_EQUITY_CURVE = DATA_DIR / "paper_account_equity_curve.csv"
STRATEGY_CONFIG_SNAPSHOT = DATA_DIR / "strategy_config_snapshot.csv"
WORKFLOW_RUN_AUDIT = DATA_DIR / "workflow_run_audit.csv"

STRATEGY_LAB_SHADOW_TRADES = DATA_DIR / "strategy_lab_shadow_trades.csv"
STRATEGY_LAB_SHADOW_LATEST_TRADES = DATA_DIR / "strategy_lab_shadow_latest_trades.csv"
STRATEGY_LAB_SHADOW_DAILY_SUMMARY = DATA_DIR / "strategy_lab_shadow_daily_summary.csv"
STRATEGY_LAB_SHADOW_SUMMARY = DATA_DIR / "strategy_lab_shadow_summary.csv"
STRATEGY_LAB_SHADOW_EQUITY_CURVE = DATA_DIR / "strategy_lab_shadow_equity_curve.csv"
STRATEGY_LAB_SHADOW_STATUS = DATA_DIR / "strategy_lab_shadow_status.csv"

INITIAL_CAPITAL = float(ORB_INITIAL_CAPITAL)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")

    return pd.read_csv(path)


def check_required_files(errors: list[str], warnings: list[str]) -> None:
    required_files = [
        PAPER_TRADES,
        PAPER_EQUITY_CURVE,
        PAPER_ACCOUNT_EQUITY_CURVE,
        ORB_SIGNALS_LATEST,
        ORB_SIGNAL_HISTORY,
        POWERBI_WORKBOOK,
        STRATEGY_CONFIG_SNAPSHOT,
        WORKFLOW_RUN_AUDIT,
        STRATEGY_LAB_SHADOW_TRADES,
        STRATEGY_LAB_SHADOW_LATEST_TRADES,
        STRATEGY_LAB_SHADOW_DAILY_SUMMARY,
        STRATEGY_LAB_SHADOW_SUMMARY,
        STRATEGY_LAB_SHADOW_EQUITY_CURVE,
        STRATEGY_LAB_SHADOW_STATUS,
    ]

    for path in required_files:
        if not path.exists():
            errors.append(f"Missing required file: {path}")
        elif path.stat().st_size == 0:
            errors.append(f"File exists but is empty: {path}")

    if POWERBI_WORKBOOK.exists():
        workbook_mtime = POWERBI_WORKBOOK.stat().st_mtime

        source_files = [
            PAPER_TRADES,
            PAPER_EQUITY_CURVE,
            PAPER_ACCOUNT_EQUITY_CURVE,
            ORB_SIGNALS_LATEST,
            ORB_SIGNAL_HISTORY,
            STRATEGY_CONFIG_SNAPSHOT,
            WORKFLOW_RUN_AUDIT,
            STRATEGY_LAB_SHADOW_TRADES,
            STRATEGY_LAB_SHADOW_LATEST_TRADES,
            STRATEGY_LAB_SHADOW_DAILY_SUMMARY,
            STRATEGY_LAB_SHADOW_SUMMARY,
            STRATEGY_LAB_SHADOW_EQUITY_CURVE,
            STRATEGY_LAB_SHADOW_STATUS,
        ]

        for path in source_files:
            if path.exists() and path.stat().st_mtime > workbook_mtime:
                warnings.append(
                    "Power BI workbook may be stale. "
                    f"{path.name} is newer than {POWERBI_WORKBOOK.name}."
                )


def check_signal_outputs(errors: list[str], warnings: list[str]) -> None:
    check_start_errors = len(errors)

    latest = read_csv(ORB_SIGNALS_LATEST)
    history = read_csv(ORB_SIGNAL_HISTORY)

    if latest.empty:
        errors.append("orb_signals_latest is empty.")

    if history.empty:
        errors.append("orb_signal_history is empty.")

    required_signal_columns = [
        "signal_key",
        "scan_date",
        "ticker",
        "status",
        "gap",
        "opening_range_pct",
        "last_bar",
    ]

    for table_name, df in [
        ("orb_signals_latest", latest),
        ("orb_signal_history", history),
    ]:
        for column in required_signal_columns:
            if column not in df.columns:
                errors.append(f"{table_name} missing required column: {column}")

    if len(errors) > check_start_errors:
        return

    for table_name, df in [
        ("orb_signals_latest", latest),
        ("orb_signal_history", history),
    ]:
        for column in ["signal_key", "scan_date", "ticker", "status"]:
            missing = df[column].isna().sum()

            if missing > 0:
                errors.append(
                    f"{table_name} has {missing} missing values in {column}."
                )

    latest_duplicate_keys = latest["signal_key"].duplicated().sum()

    if latest_duplicate_keys > 0:
        errors.append(
            f"orb_signals_latest has {latest_duplicate_keys} duplicate signal_key rows."
        )

    history_duplicate_keys = history["signal_key"].duplicated().sum()

    if history_duplicate_keys > 0:
        errors.append(
            f"orb_signal_history has {history_duplicate_keys} duplicate signal_key rows."
        )

    history_duplicate_scan_ticker = history.duplicated(
        subset=["scan_date", "ticker"]
    ).sum()

    if history_duplicate_scan_ticker > 0:
        errors.append(
            "orb_signal_history has duplicate scan_date + ticker rows: "
            f"{history_duplicate_scan_ticker}"
        )

    latest_statuses = set(latest["status"].dropna().astype(str).unique())
    allowed_statuses = {"INVALID", "NOT_TRIGGERED", "TRIGGERED"}

    unexpected_statuses = latest_statuses - allowed_statuses

    if unexpected_statuses:
        warnings.append(
            "orb_signals_latest has unexpected statuses: "
            f"{sorted(unexpected_statuses)}"
        )

    unique_latest_dates = latest["scan_date"].dropna().unique()

    if len(unique_latest_dates) != 1:
        warnings.append(
            "orb_signals_latest should usually contain exactly one scan_date, "
            f"but found {len(unique_latest_dates)}: {unique_latest_dates}"
        )


def check_paper_trades(errors: list[str], warnings: list[str]) -> None:
    check_start_errors = len(errors)

    trades = read_csv(PAPER_TRADES)

    if trades.empty:
        warnings.append("paper_trades is empty. This may be okay before first trade.")
        return

    required_columns = [
        "trade_id",
        "date",
        "ticker",
        "status",
        "pnl_sek",
        "strategy_version",
        "initial_capital",
        "position_size_pct",
        "max_open_positions",
        "capital_model",
    ]

    for column in required_columns:
        if column not in trades.columns:
            errors.append(f"paper_trades missing required column: {column}")

    if len(errors) > check_start_errors:
        return

    duplicate_trade_ids = trades["trade_id"].duplicated().sum()

    if duplicate_trade_ids > 0:
        errors.append(f"paper_trades has {duplicate_trade_ids} duplicate trade_id rows.")

    allowed_statuses = {"OPEN", "CLOSED"}
    observed_statuses = set(
        trades["status"].dropna().astype(str).str.upper().unique()
    )

    unexpected_statuses = observed_statuses - allowed_statuses

    if unexpected_statuses:
        errors.append(
            f"paper_trades has unexpected statuses: {sorted(unexpected_statuses)}"
        )

    missing_strategy = trades["strategy_version"].isna().sum()

    if missing_strategy > 0:
        warnings.append(
            f"paper_trades has {missing_strategy} rows missing strategy_version."
        )

    trades["initial_capital"] = pd.to_numeric(
        trades["initial_capital"],
        errors="coerce",
    )

    trades["position_size_pct"] = pd.to_numeric(
        trades["position_size_pct"],
        errors="coerce",
    )

    trades["max_open_positions"] = pd.to_numeric(
        trades["max_open_positions"],
        errors="coerce",
    )

    if trades["initial_capital"].isna().any():
        errors.append("paper_trades has missing or invalid initial_capital values.")

    if trades["position_size_pct"].isna().any():
        errors.append("paper_trades has missing or invalid position_size_pct values.")

    if trades["max_open_positions"].isna().any():
        errors.append("paper_trades has missing or invalid max_open_positions values.")

    if (trades["initial_capital"] <= 0).any():
        errors.append("paper_trades has initial_capital values <= 0.")

    if (trades["position_size_pct"] <= 0).any():
        errors.append("paper_trades has position_size_pct values <= 0.")

    if (trades["max_open_positions"] <= 0).any():
        errors.append("paper_trades has max_open_positions values <= 0.")

    blank_capital_model = trades["capital_model"].isna() | (
        trades["capital_model"].astype(str).str.strip() == ""
    )

    if blank_capital_model.any():
        errors.append("paper_trades has blank capital_model values.")

    closed = trades[trades["status"].astype(str).str.upper() == "CLOSED"].copy()

    if not closed.empty:
        closed["pnl_sek"] = pd.to_numeric(
            closed["pnl_sek"],
            errors="coerce",
        )

        missing_pnl = closed["pnl_sek"].isna().sum()

        if missing_pnl > 0:
            errors.append(f"Closed paper trades have {missing_pnl} missing pnl_sek.")


def check_strategy_equity_curve(errors: list[str], warnings: list[str]) -> None:
    check_start_errors = len(errors)

    curve = read_csv(PAPER_EQUITY_CURVE)

    if curve.empty:
        warnings.append("paper_equity_curve is empty.")
        return

    required_columns = [
        "trade_number",
        "strategy_version",
        "equity",
        "drawdown_pct",
        "is_baseline",
    ]

    for column in required_columns:
        if column not in curve.columns:
            errors.append(f"paper_equity_curve missing required column: {column}")

    if len(errors) > check_start_errors:
        return

    curve["trade_number"] = pd.to_numeric(
        curve["trade_number"],
        errors="coerce",
    )

    curve["equity"] = pd.to_numeric(
        curve["equity"],
        errors="coerce",
    )

    duplicate_strategy_trade_number = curve.duplicated(
        subset=["strategy_version", "trade_number"]
    ).sum()

    if duplicate_strategy_trade_number > 0:
        errors.append(
            "paper_equity_curve has duplicate strategy_version + trade_number rows: "
            f"{duplicate_strategy_trade_number}"
        )

    baseline = curve[curve["trade_number"] == 0].copy()

    if baseline.empty:
        errors.append("paper_equity_curve has no baseline rows with trade_number = 0.")
        return

    for _, row in baseline.iterrows():
        strategy_version = row["strategy_version"]
        equity = row["equity"]

        if abs(equity - INITIAL_CAPITAL) > 0.01:
            errors.append(
                "paper_equity_curve baseline equity is not initial capital for "
                f"{strategy_version}: {equity}"
            )

    baseline_counts = baseline.groupby("strategy_version").size()
    bad_baselines = baseline_counts[baseline_counts != 1]

    if not bad_baselines.empty:
        errors.append(
            "paper_equity_curve should have exactly one baseline row per strategy. "
            f"Bad counts: {bad_baselines.to_dict()}"
        )


def check_account_equity_curve(errors: list[str], warnings: list[str]) -> None:
    check_start_errors = len(errors)

    trades = read_csv(PAPER_TRADES)
    account_curve = read_csv(PAPER_ACCOUNT_EQUITY_CURVE)

    if account_curve.empty:
        warnings.append("paper_account_equity_curve is empty.")
        return

    required_columns = [
        "account_trade_number",
        "account_equity",
        "account_drawdown_pct",
        "pnl_sek",
        "is_baseline",
    ]

    for column in required_columns:
        if column not in account_curve.columns:
            errors.append(
                f"paper_account_equity_curve missing required column: {column}"
            )

    if len(errors) > check_start_errors:
        return

    account_curve["account_trade_number"] = pd.to_numeric(
        account_curve["account_trade_number"],
        errors="coerce",
    )

    account_curve["account_equity"] = pd.to_numeric(
        account_curve["account_equity"],
        errors="coerce",
    )

    account_curve["pnl_sek"] = pd.to_numeric(
        account_curve["pnl_sek"],
        errors="coerce",
    ).fillna(0.0)

    duplicate_trade_numbers = account_curve["account_trade_number"].duplicated().sum()

    if duplicate_trade_numbers > 0:
        errors.append(
            "paper_account_equity_curve has duplicate account_trade_number rows: "
            f"{duplicate_trade_numbers}"
        )

    baseline = account_curve[account_curve["account_trade_number"] == 0]

    if len(baseline) != 1:
        errors.append(
            "paper_account_equity_curve should have exactly one baseline row. "
            f"Found: {len(baseline)}"
        )
    else:
        baseline_equity = float(baseline["account_equity"].iloc[0])

        if abs(baseline_equity - INITIAL_CAPITAL) > 0.01:
            errors.append(
                "paper_account_equity_curve baseline equity is not initial capital: "
                f"{baseline_equity}"
            )

    if trades.empty:
        return

    trades["pnl_sek"] = pd.to_numeric(
        trades.get("pnl_sek", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0.0)

    closed = trades[
        trades["status"].astype(str).str.upper() == "CLOSED"
    ].copy()

    expected_trade_rows = len(closed)
    actual_trade_rows = len(account_curve[account_curve["account_trade_number"] > 0])

    if expected_trade_rows != actual_trade_rows:
        errors.append(
            "paper_account_equity_curve trade row count does not match closed trades. "
            f"Expected {expected_trade_rows}, got {actual_trade_rows}."
        )

    expected_final_equity = INITIAL_CAPITAL + closed["pnl_sek"].sum()

    last_row = account_curve.sort_values("account_trade_number").tail(1)
    actual_final_equity = float(last_row["account_equity"].iloc[0])

    if abs(expected_final_equity - actual_final_equity) > 0.01:
        errors.append(
            "paper_account_equity_curve final equity does not reconcile with "
            "closed paper trade PnL. "
            f"Expected {expected_final_equity:.2f}, got {actual_final_equity:.2f}."
        )


def check_strategy_config_snapshot(errors: list[str], warnings: list[str]) -> None:
    check_start_errors = len(errors)

    snapshot = read_csv(STRATEGY_CONFIG_SNAPSHOT)

    if snapshot.empty:
        errors.append("strategy_config_snapshot is empty.")
        return

    required_columns = [
        "exported_at",
        "strategy_version",
        "display_order",
        "setting_key",
        "setting_label",
        "value",
        "value_numeric",
        "value_type",
        "display_value",
        "description",
    ]

    for column in required_columns:
        if column not in snapshot.columns:
            errors.append(f"strategy_config_snapshot missing required column: {column}")

    if len(errors) > check_start_errors:
        return

    required_setting_keys = {
        "ORB_STRATEGY_VERSION",
        "ORB_ALLOWED_TICKERS",
        "ORB_ALLOWED_TICKER_COUNT",
        "ORB_MAX_OPEN_POSITIONS",
        "POSITION_RULE",
        "ORB_BREAKOUT_START",
        "ORB_BREAKOUT_END",
        "ORB_R_MULTIPLE",
        "ORB_MAX_OPENING_RANGE",
        "ORB_MIN_GAP",
        "ORB_COST_PER_TRADE",
        "ORB_INITIAL_CAPITAL",
        "ORB_POSITION_SIZE",
        "PAPER_POSITION_SIZE_SEK",
        "CAPITAL_MODEL",
    }

    observed_setting_keys = set(
        snapshot["setting_key"].dropna().astype(str).str.strip()
    )

    missing_settings = required_setting_keys - observed_setting_keys

    if missing_settings:
        errors.append(
            "strategy_config_snapshot missing settings: "
            f"{sorted(missing_settings)}"
        )

    duplicate_settings = snapshot["setting_key"].duplicated().sum()

    if duplicate_settings > 0:
        errors.append(
            f"strategy_config_snapshot has {duplicate_settings} duplicate setting_key rows."
        )

    blank_display_values = snapshot["display_value"].isna() | (
        snapshot["display_value"].astype(str).str.strip() == ""
    )

    if blank_display_values.any():
        errors.append("strategy_config_snapshot has blank display_value rows.")

    strategy_versions = snapshot["strategy_version"].dropna().unique()

    if len(strategy_versions) != 1:
        warnings.append(
            "strategy_config_snapshot should usually have exactly one strategy_version, "
            f"but found {len(strategy_versions)}: {strategy_versions}"
        )


def check_workflow_run_audit(errors: list[str], warnings: list[str]) -> None:
    check_start_errors = len(errors)

    audit = read_csv(WORKFLOW_RUN_AUDIT)

    if audit.empty:
        errors.append("workflow_run_audit is empty.")
        return

    required_columns = [
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

    for column in required_columns:
        if column not in audit.columns:
            errors.append(f"workflow_run_audit missing required column: {column}")

    if len(errors) > check_start_errors:
        return

    duplicate_run_ids = audit["run_id"].duplicated().sum()

    if duplicate_run_ids > 0:
        errors.append(f"workflow_run_audit has {duplicate_run_ids} duplicate run_id rows.")

    latest = audit.sort_values("run_timestamp").tail(1).copy()
    status = str(latest["validation_status"].iloc[0]).upper().strip()

    if status != "PASSED":
        errors.append(
            "Latest workflow_run_audit validation_status is not PASSED: "
            f"{status}"
        )

    numeric_columns = [
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
    ]

    for column in numeric_columns:
        converted = pd.to_numeric(audit[column], errors="coerce")

        if converted.isna().any():
            errors.append(f"workflow_run_audit has invalid numeric values in {column}.")


def check_strategy_lab_shadow_outputs(
    errors: list[str],
    warnings: list[str],
) -> None:
    check_start_errors = len(errors)

    expected_shadow_ids = {
        "ORB_PRODUCTION_REFERENCE_CURRENT_BASKET",
        "PDH_ACTIVE_BEST5",
        "PDH_DIAGNOSTIC_ALL_DOWNLOADED",
        "GAP_RECOVERY_WATCH_BEST7",
        "PULLBACK_DIAGNOSTIC_ALL_DOWNLOADED",
        "VWAP_DIAGNOSTIC_BEST5",
    }

    required_shadow_files = {
        "strategy_lab_shadow_trades": STRATEGY_LAB_SHADOW_TRADES,
        "strategy_lab_shadow_latest_trades": STRATEGY_LAB_SHADOW_LATEST_TRADES,
        "strategy_lab_shadow_daily_summary": STRATEGY_LAB_SHADOW_DAILY_SUMMARY,
        "strategy_lab_shadow_summary": STRATEGY_LAB_SHADOW_SUMMARY,
        "strategy_lab_shadow_equity_curve": STRATEGY_LAB_SHADOW_EQUITY_CURVE,
        "strategy_lab_shadow_status": STRATEGY_LAB_SHADOW_STATUS,
    }

    loaded_tables: dict[str, pd.DataFrame] = {}

    for name, path in required_shadow_files.items():
        if not path.exists():
            errors.append(f"Missing Strategy Lab shadow file: {path}")
            continue

        if path.stat().st_size == 0:
            errors.append(f"Strategy Lab shadow file exists but is empty: {path}")
            continue

        try:
            df = pd.read_csv(path)
        except Exception as exc:
            errors.append(f"Could not read Strategy Lab shadow file {path}: {exc}")
            continue

        loaded_tables[name] = df

        if name != "strategy_lab_shadow_latest_trades" and df.empty:
            errors.append(f"Strategy Lab shadow file is empty: {path}")

    if len(errors) > check_start_errors:
        return

    status = loaded_tables["strategy_lab_shadow_status"]
    summary = loaded_tables["strategy_lab_shadow_summary"]
    trades = loaded_tables["strategy_lab_shadow_trades"]
    equity = loaded_tables["strategy_lab_shadow_equity_curve"]
    daily_summary = loaded_tables["strategy_lab_shadow_daily_summary"]
    latest_trades = loaded_tables["strategy_lab_shadow_latest_trades"]

    if len(status) != 6:
        errors.append(
            f"strategy_lab_shadow_status should have 6 rows, found {len(status)}"
        )

    if len(summary) != 6:
        errors.append(
            f"strategy_lab_shadow_summary should have 6 rows, found {len(summary)}"
        )

    required_identity_columns = [
        "shadow_strategy_id",
        "research_tier",
        "summary_role",
        "strategy_name",
    ]

    for table_name, df in [
        ("strategy_lab_shadow_status", status),
        ("strategy_lab_shadow_summary", summary),
        ("strategy_lab_shadow_trades", trades),
        ("strategy_lab_shadow_equity_curve", equity),
        ("strategy_lab_shadow_daily_summary", daily_summary),
    ]:
        missing_columns = [
            column for column in required_identity_columns
            if column not in df.columns
        ]

        if missing_columns:
            errors.append(f"{table_name} missing required columns: {missing_columns}")

    if len(errors) > check_start_errors:
        return

    status_ids = set(status["shadow_strategy_id"].dropna().astype(str))
    summary_ids = set(summary["shadow_strategy_id"].dropna().astype(str))
    trade_ids = set(trades["shadow_strategy_id"].dropna().astype(str))
    equity_ids = set(equity["shadow_strategy_id"].dropna().astype(str))
    daily_ids = set(daily_summary["shadow_strategy_id"].dropna().astype(str))

    missing_status_ids = expected_shadow_ids - status_ids
    missing_summary_ids = expected_shadow_ids - summary_ids
    missing_trade_ids = expected_shadow_ids - trade_ids
    missing_equity_ids = expected_shadow_ids - equity_ids
    missing_daily_ids = expected_shadow_ids - daily_ids

    if missing_status_ids:
        errors.append(
            f"strategy_lab_shadow_status missing IDs: {sorted(missing_status_ids)}"
        )

    if missing_summary_ids:
        errors.append(
            f"strategy_lab_shadow_summary missing IDs: {sorted(missing_summary_ids)}"
        )

    if missing_trade_ids:
        errors.append(
            f"strategy_lab_shadow_trades missing IDs: {sorted(missing_trade_ids)}"
        )

    if missing_equity_ids:
        errors.append(
            f"strategy_lab_shadow_equity_curve missing IDs: {sorted(missing_equity_ids)}"
        )

    if missing_daily_ids:
        errors.append(
            f"strategy_lab_shadow_daily_summary missing IDs: {sorted(missing_daily_ids)}"
        )

    if "ready_for_monday" not in status.columns:
        errors.append("strategy_lab_shadow_status missing ready_for_monday column")
    else:
        ready_values = (
            status["ready_for_monday"]
            .astype(str)
            .str.strip()
            .str.lower()
        )

        not_ready = status.loc[
            ~ready_values.isin(["true", "1", "yes"]),
            "shadow_strategy_id",
        ].tolist()

        if not_ready:
            errors.append(
                f"These shadow strategies are not ready for Monday: {not_ready}"
            )

    if "latest_data_date" not in status.columns:
        errors.append("strategy_lab_shadow_status missing latest_data_date column")
    elif status["latest_data_date"].isna().any():
        errors.append("strategy_lab_shadow_status contains blank latest_data_date")

    required_summary_numeric_columns = [
        "selected_trades",
        "latest_trade_count",
        "total_account_return",
        "profit_factor",
        "max_drawdown",
        "win_rate",
    ]

    for column in required_summary_numeric_columns:
        if column not in summary.columns:
            errors.append(f"strategy_lab_shadow_summary missing required column: {column}")
            continue

        converted = pd.to_numeric(summary[column], errors="coerce")

        if converted.isna().any():
            errors.append(
                f"strategy_lab_shadow_summary has invalid numeric values in {column}"
            )

    if "date" not in trades.columns:
        errors.append("strategy_lab_shadow_trades missing date column")

    if "account_return" not in trades.columns:
        errors.append("strategy_lab_shadow_trades missing account_return column")

    if "equity" not in equity.columns:
        errors.append("strategy_lab_shadow_equity_curve missing equity column")

    if latest_trades.empty:
        warnings.append(
            "strategy_lab_shadow_latest_trades is empty. "
            "This can be okay on a no-signal day."
        )


def main() -> None:
    print("\n=== VALIDATE DAILY OUTPUTS ===")

    errors: list[str] = []
    warnings: list[str] = []

    checks = [
        ("Required files", check_required_files),
        ("Signal outputs", check_signal_outputs),
        ("Paper trades", check_paper_trades),
        ("Strategy equity curve", check_strategy_equity_curve),
        ("Account equity curve", check_account_equity_curve),
        ("Strategy config snapshot", check_strategy_config_snapshot),
        ("Workflow run audit", check_workflow_run_audit),
        ("Strategy Lab shadow outputs", check_strategy_lab_shadow_outputs),
    ]

    for label, check_function in checks:
        try:
            check_function(errors, warnings)
            print(f"OK: {label}")
        except Exception as exc:
            errors.append(f"{label} check failed with exception: {exc}")
            print(f"FAILED: {label}")

    if warnings:
        print("\n=== WARNINGS ===")
        for warning in warnings:
            print(f"WARNING: {warning}")

    if errors:
        print("\n=== ERRORS ===")
        for error in errors:
            print(f"ERROR: {error}")

        print("\nValidation failed.")
        sys.exit(1)

    print("\nAll daily output validation checks passed.")


if __name__ == "__main__":
    main()