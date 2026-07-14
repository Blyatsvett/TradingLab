import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.orb_config import ORB_INITIAL_CAPITAL
from Intraday.core.paths import PAPER_EQUITY_CURVE, PAPER_TRADES


INITIAL_CAPITAL = float(ORB_INITIAL_CAPITAL)


def ensure_columns(trades: pd.DataFrame) -> pd.DataFrame:
    """Ensure older trade records can still be summarized safely."""
    trades = trades.copy()

    required_text_columns = [
        "trade_id",
        "ticker",
        "status",
        "exit_reason",
        "strategy_version",
        "exit_time",
    ]

    required_numeric_columns = [
        "pnl_pct",
        "pnl_sek",
        "r_multiple_achieved",
    ]

    for column in required_text_columns:
        if column not in trades.columns:
            trades[column] = ""

    for column in required_numeric_columns:
        if column not in trades.columns:
            trades[column] = 0.0

    trades["strategy_version"] = (
        trades["strategy_version"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "UNVERSIONED")
    )

    for column in required_numeric_columns:
        trades[column] = pd.to_numeric(trades[column], errors="coerce").fillna(0.0)

    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")

    return trades


def build_strategy_equity_curve(
    closed_trades: pd.DataFrame,
    initial_capital: float,
) -> pd.DataFrame:
    """
    Build one independent equity curve per strategy version.

    Each strategy starts at the same initial capital so that filtering a
    strategy version in Power BI produces a comparable standalone curve.
    """
    output_columns = [
        "trade_number",
        "exit_time",
        "ticker",
        "pnl_sek",
        "strategy_version",
        "equity",
        "rolling_peak",
        "drawdown_sek",
        "drawdown_pct",
        "is_baseline",
    ]

    if closed_trades.empty:
        return pd.DataFrame(columns=output_columns)

    valid_trades = closed_trades.dropna(subset=["exit_time"]).copy()

    if valid_trades.empty:
        return pd.DataFrame(columns=output_columns)

    curve_parts = []

    for strategy_version, strategy_trades in valid_trades.groupby(
        "strategy_version",
        sort=True,
    ):
        strategy_trades = (
            strategy_trades
            .sort_values(["exit_time", "trade_id"], kind="stable")
            .reset_index(drop=True)
        )

        first_exit_time = strategy_trades["exit_time"].iloc[0]
        baseline_time = first_exit_time - pd.Timedelta(seconds=1)

        # Baseline row: every strategy begins independently at 10,000 SEK.
        baseline = pd.DataFrame(
            [
                {
                    "trade_number": 0,
                    "exit_time": baseline_time,
                    "ticker": "START",
                    "pnl_sek": 0.0,
                    "strategy_version": strategy_version,
                    "equity": initial_capital,
                    "rolling_peak": initial_capital,
                    "drawdown_sek": 0.0,
                    "drawdown_pct": 0.0,
                    "is_baseline": True,
                }
            ]
        )

        strategy_trades["trade_number"] = range(1, len(strategy_trades) + 1)

        # This is intentionally non-compounding because the paper-trade
        # engine currently uses a fixed 1,000 SEK position size per trade.
        strategy_trades["equity"] = (
            initial_capital + strategy_trades["pnl_sek"].cumsum()
        )

        # Include initial capital in the peak calculation so a first loss
        # correctly shows a drawdown from 10,000 SEK.
        equity_with_baseline = pd.concat(
            [
                pd.Series([initial_capital]),
                strategy_trades["equity"],
            ],
            ignore_index=True,
        )

        rolling_peak_with_baseline = equity_with_baseline.cummax()

        strategy_trades["rolling_peak"] = (
            rolling_peak_with_baseline.iloc[1:].to_numpy()
        )

        strategy_trades["drawdown_sek"] = (
            strategy_trades["equity"] - strategy_trades["rolling_peak"]
        )

        strategy_trades["drawdown_pct"] = (
            strategy_trades["drawdown_sek"] / strategy_trades["rolling_peak"]
        )

        strategy_trades["is_baseline"] = False

        trade_rows = strategy_trades[
            [
                "trade_number",
                "exit_time",
                "ticker",
                "pnl_sek",
                "strategy_version",
                "equity",
                "rolling_peak",
                "drawdown_sek",
                "drawdown_pct",
                "is_baseline",
            ]
        ].copy()

        curve_parts.append(baseline)
        curve_parts.append(trade_rows)

    equity_curve = pd.concat(curve_parts, ignore_index=True)

    return equity_curve.sort_values(
        ["strategy_version", "trade_number"],
        kind="stable",
    ).reset_index(drop=True)


def print_summary(trades: pd.DataFrame, closed_trades: pd.DataFrame) -> None:
    total_trades = len(trades)
    open_trades = int((trades["status"] == "OPEN").sum())
    closed_trade_count = len(closed_trades)

    print("\n=== PAPER TRADE SUMMARY ===")
    print(f"Total trades  : {total_trades}")
    print(f"Open trades   : {open_trades}")
    print(f"Closed trades : {closed_trade_count}")

    if closed_trades.empty:
        print("\nNo closed trades available yet.")
        return

    win_rate = (closed_trades["pnl_pct"] > 0).mean()

    print("\n=== CLOSED TRADE STATS ===")
    print(f"Win rate       : {win_rate:.2%}")
    print(f"Avg trade      : {closed_trades['pnl_pct'].mean():.4%}")
    print(f"Total PnL %    : {closed_trades['pnl_pct'].sum():.4%}")
    print(f"Best trade %   : {closed_trades['pnl_pct'].max():.4%}")
    print(f"Worst trade %  : {closed_trades['pnl_pct'].min():.4%}")

    total_pnl_sek = closed_trades["pnl_sek"].sum()
    final_equity = INITIAL_CAPITAL + total_pnl_sek

    print("\n=== SEK PNL ===")
    print(f"Total PnL SEK  : {total_pnl_sek:.2f}")
    print(f"Avg PnL SEK    : {closed_trades['pnl_sek'].mean():.2f}")
    print(f"Best PnL SEK   : {closed_trades['pnl_sek'].max():.2f}")
    print(f"Worst PnL SEK  : {closed_trades['pnl_sek'].min():.2f}")
    print(f"Final equity   : {final_equity:.2f} SEK")

    print("\n=== BY STRATEGY VERSION ===")
    by_strategy = (
        closed_trades.groupby("strategy_version")
        .agg(
            trades=("pnl_pct", "count"),
            win_rate=("pnl_pct", lambda values: (values > 0).mean()),
            avg_pct=("pnl_pct", "mean"),
            total_pct=("pnl_pct", "sum"),
            total_sek=("pnl_sek", "sum"),
        )
        .sort_values("total_sek", ascending=False)
    )
    print(by_strategy)

    print("\n=== BY TICKER ===")
    by_ticker = (
        closed_trades.groupby("ticker")
        .agg(
            trades=("pnl_pct", "count"),
            avg_pct=("pnl_pct", "mean"),
            total_pct=("pnl_pct", "sum"),
            total_sek=("pnl_sek", "sum"),
        )
        .sort_values("total_sek", ascending=False)
    )
    print(by_ticker)

    print("\n=== EXIT REASONS ===")
    print(closed_trades["exit_reason"].value_counts())


def main() -> None:
    trades = pd.read_csv(PAPER_TRADES)
    trades = ensure_columns(trades)

    closed_trades = trades[
        trades["status"].astype(str).str.upper() == "CLOSED"
    ].copy()

    print_summary(trades, closed_trades)

    equity_curve = build_strategy_equity_curve(
        closed_trades=closed_trades,
        initial_capital=INITIAL_CAPITAL,
    )

    export_csv_for_power_bi(equity_curve, PAPER_EQUITY_CURVE)

    print(f"\nSaved equity curve -> {PAPER_EQUITY_CURVE}")

    if not equity_curve.empty:
        print("\n=== EQUITY CURVE CHECK ===")
        print(
            equity_curve[
                [
                    "strategy_version",
                    "trade_number",
                    "ticker",
                    "pnl_sek",
                    "equity",
                    "drawdown_pct",
                    "is_baseline",
                ]
            ].to_string(index=False)
        )


if __name__ == "__main__":
    main()