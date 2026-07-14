import os
import sqlite3
import pandas as pd

from Intraday.core.paths import DATA_DIR


POWERBI_DB = DATA_DIR / "powerbi.db"


TABLES = {
    "paper_trades": DATA_DIR / "paper_trades.csv",
    "paper_equity_curve": DATA_DIR / "paper_equity_curve.csv",
    "paper_account_equity_curve": DATA_DIR / "paper_account_equity_curve.csv",
    "orb_signals_latest": DATA_DIR / "orb_signals_latest.csv",
    "orb_signal_history": DATA_DIR / "orb_signal_history.csv",
    "orb_backtest_trades": DATA_DIR / "orb_backtest_trades.csv",
    "orb_backtest_equity_curve": DATA_DIR / "orb_backtest_equity_curve.csv",
    "orb_parameter_optimization": DATA_DIR / "orb_parameter_optimization.csv",
    "orb_ticker_optimization": DATA_DIR / "orb_ticker_optimization.csv",
    "orb_portfolio_simulation": DATA_DIR / "orb_portfolio_simulation.csv",
    
}


DATE_COLUMNS = [
    "date",
    "entry_time",
    "exit_time",
    "created_at",
    "breakout_time",
    "last_bar",
    "time",
]


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    TEXT_COLUMNS = [
        "trade_id",
        "ticker",
        "side",
        "status",
        "exit_reason",
        "strategy_version",
        "breakout_time_bucket",
        "label",
        "tickers",
        "scenario",
    ]

    for col in TEXT_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(str)

    for col in df.columns:
        if col in DATE_COLUMNS:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

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
        "gross_return",
        "net_return",
        "pnl",
        "final_equity",
        "total_return",
        "win_rate",
        "avg_trade",
        "max_drawdown",
        "profit_factor",
        "r_multiple",
        "max_opening_range",
        "min_gap",
        "trades",
        "ticker_count",
        "trades_taken",
        "max_positions",
    ]

    for col in numeric_candidates:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df = df.fillna("")

    return df


def export_table(conn, table_name, csv_path):
    if not os.path.exists(csv_path):
        print(f"Skipping missing file: {csv_path}")
        return

    df = pd.read_csv(csv_path)
    df = clean_dataframe(df)

    df.to_sql(table_name, conn, if_exists="replace", index=False)

    print(f"Exported {table_name}: {len(df)} rows")


def main():
    print("\n=== EXPORT POWER BI DATABASE ===")
    print(f"Database: {POWERBI_DB}")

    conn = sqlite3.connect(POWERBI_DB)

    for table_name, csv_path in TABLES.items():
        export_table(conn, table_name, csv_path)

    conn.close()

    print(f"\nSaved Power BI database -> {POWERBI_DB}")


if __name__ == "__main__":
    main()