import os
import pandas as pd

from Intraday.core.paths import DATA_DIR


OUTPUT_FILE = DATA_DIR / "powerbi_exports.xlsx"

TABLES = {
    "paper_trades": DATA_DIR / "paper_trades.csv",
    "paper_equity_curve": DATA_DIR / "paper_equity_curve.csv",
    "paper_account_equity_curve": DATA_DIR / "paper_account_equity_curve.csv",
    "strategy_config_snapshot": DATA_DIR / "strategy_config_snapshot.csv",
    "workflow_run_audit": DATA_DIR / "workflow_run_audit.csv",
    "orb_signals_latest": DATA_DIR / "orb_signals_latest.csv",
    "orb_signal_history": DATA_DIR / "orb_signal_history.csv",
    "orb_backtest_trades": DATA_DIR / "orb_backtest_trades.csv",
    "orb_backtest_equity_curve": DATA_DIR / "orb_backtest_equity_curve.csv",
    "orb_parameter_optimization": DATA_DIR / "orb_parameter_optimization.csv",
    "orb_ticker_optimization": DATA_DIR / "orb_ticker_optimization.csv",
    "orb_portfolio_simulation": DATA_DIR / "orb_portfolio_simulation.csv",
    "orb_risk_filter_shadow_summary": DATA_DIR / "orb_risk_filter_shadow_summary.csv",
    "orb_risk_filter_shadow_report": DATA_DIR / "orb_risk_filter_shadow_report.csv",
    "orb_risk_filter_shadow_candidates": DATA_DIR / "orb_risk_filter_shadow_candidates.csv",
    "orb_position_sizing_shadow_summary": DATA_DIR / "orb_position_sizing_shadow_summary.csv",
    "orb_position_sizing_shadow_report": DATA_DIR / "orb_position_sizing_shadow_report.csv",
    "orb_position_sizing_shadow_daily_summary": DATA_DIR / "orb_position_sizing_shadow_daily_summary.csv",
    "orb_position_sizing_shadow_trades": DATA_DIR / "orb_position_sizing_shadow_trades.csv",
    "orb_position_sizing_shadow_equity_curve": DATA_DIR / "orb_position_sizing_shadow_equity_curve.csv",
}


def clean_dataframe(df):
    df = df.copy()

    numeric_candidates = [
        "entry_price",
        "stop_price",
        "target_price",
        "exit_price",
        "current_price",
        "entry_trigger",
        "risk_pct",
        "target_return_pct",
        "gap",
        "opening_range_pct",
        "breakout_price",
        "pnl_pct",
        "position_size_sek",
        "pnl_sek",
        "equity",
        "rolling_peak",
        "drawdown_sek",
        "drawdown_pct",
        "trade_duration_minutes",
        "risk_per_share",
        "r_multiple_achieved",
        "signal_rank",
        "display_order",
        "value_numeric",
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

    for col in numeric_candidates:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def main():
    print("\n=== EXPORT POWER BI WORKBOOK ===")
    print(f"Output file: {OUTPUT_FILE}")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        for sheet_name, csv_path in TABLES.items():
            if not os.path.exists(csv_path):
                print(f"Skipping missing file: {csv_path}")
                continue

            df = pd.read_csv(csv_path)
            df = clean_dataframe(df)

            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

            print(f"Exported {sheet_name}: {len(df)} rows")

    print(f"\nSaved workbook -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()