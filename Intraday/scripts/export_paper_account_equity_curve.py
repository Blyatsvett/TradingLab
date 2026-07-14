import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import ORB_INITIAL_CAPITAL
from Intraday.core.paths import DATA_DIR, PAPER_TRADES


OUTPUT_FILE = DATA_DIR / "paper_account_equity_curve.csv"
INITIAL_CAPITAL = float(ORB_INITIAL_CAPITAL)


def main() -> None:
    print("\n=== EXPORT PAPER ACCOUNT EQUITY CURVE ===")

    trades = pd.read_csv(PAPER_TRADES)

    if trades.empty:
        print("No paper trades found.")
        return

    required_columns = [
        "trade_id",
        "date",
        "ticker",
        "status",
        "exit_time",
        "pnl_sek",
        "strategy_version",
    ]

    for column in required_columns:
        if column not in trades.columns:
            trades[column] = ""

    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")
    trades["pnl_sek"] = pd.to_numeric(trades["pnl_sek"], errors="coerce").fillna(0.0)

    closed_trades = trades[
        trades["status"].astype(str).str.upper() == "CLOSED"
    ].copy()

    closed_trades = closed_trades.dropna(subset=["exit_time"]).copy()

    output_columns = [
        "account_trade_number",
        "exit_time",
        "date",
        "ticker",
        "strategy_version",
        "pnl_sek",
        "account_equity",
        "account_rolling_peak",
        "account_drawdown_sek",
        "account_drawdown_pct",
        "is_baseline",
    ]

    if closed_trades.empty:
        empty_output = pd.DataFrame(columns=output_columns)
        export_csv_for_power_bi(empty_output, OUTPUT_FILE)
        print("No closed paper trades found.")
        print(f"Saved -> {OUTPUT_FILE}")
        return

    closed_trades = closed_trades.sort_values(
        ["exit_time", "trade_id"],
        kind="stable",
    ).reset_index(drop=True)

    first_exit_time = closed_trades["exit_time"].iloc[0]
    baseline_time = first_exit_time - pd.Timedelta(seconds=1)

    baseline = pd.DataFrame(
        [
            {
                "account_trade_number": 0,
                "exit_time": baseline_time,
                "date": baseline_time.date(),
                "ticker": "START",
                "strategy_version": "ACCOUNT",
                "pnl_sek": 0.0,
                "account_equity": INITIAL_CAPITAL,
                "account_rolling_peak": INITIAL_CAPITAL,
                "account_drawdown_sek": 0.0,
                "account_drawdown_pct": 0.0,
                "is_baseline": True,
            }
        ]
    )

    closed_trades["account_trade_number"] = range(1, len(closed_trades) + 1)
    closed_trades["account_equity"] = INITIAL_CAPITAL + closed_trades["pnl_sek"].cumsum()
    closed_trades["account_rolling_peak"] = closed_trades["account_equity"].cummax()

    # Make sure the initial 10,000 SEK is included in the peak calculation.
    closed_trades["account_rolling_peak"] = closed_trades["account_rolling_peak"].clip(
        lower=INITIAL_CAPITAL
    )

    closed_trades["account_drawdown_sek"] = (
        closed_trades["account_equity"] - closed_trades["account_rolling_peak"]
    )

    closed_trades["account_drawdown_pct"] = (
        closed_trades["account_drawdown_sek"]
        / closed_trades["account_rolling_peak"]
    )

    closed_trades["is_baseline"] = False

    account_curve = closed_trades[
        [
            "account_trade_number",
            "exit_time",
            "date",
            "ticker",
            "strategy_version",
            "pnl_sek",
            "account_equity",
            "account_rolling_peak",
            "account_drawdown_sek",
            "account_drawdown_pct",
            "is_baseline",
        ]
    ].copy()

    account_curve = pd.concat(
        [baseline, account_curve],
        ignore_index=True,
    )

    account_curve = account_curve[output_columns].copy()

    export_csv_for_power_bi(account_curve, OUTPUT_FILE)

    print(f"Rows exported: {len(account_curve)}")
    print(f"Final account equity: {account_curve['account_equity'].iloc[-1]:.2f} SEK")
    print(f"Max drawdown: {account_curve['account_drawdown_pct'].min():.2%}")
    print(f"Saved -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()