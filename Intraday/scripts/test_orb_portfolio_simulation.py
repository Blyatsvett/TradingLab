import pandas as pd

from Intraday.core.paths import DATA_DIR
from Intraday.core.orb_strategy import (
    load_intraday_prices,
    build_orb_trades,
)


TICKERS = [
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "SEB-A.ST",
    "ATCO-A.ST",
]

INITIAL_CAPITAL = 10000
COST_PER_TRADE = 0.0005

OUTPUT_FILE = DATA_DIR / "orb_portfolio_simulation.csv"


def simulate_portfolio(trades, max_positions):
    trades = trades.sort_values("entry_time").reset_index(drop=True).copy()

    equity = INITIAL_CAPITAL
    open_positions = []
    closed_trades = []
    equity_curve = []

    for _, trade in trades.iterrows():
        entry_time = trade["entry_time"]

        still_open = []

        for pos in open_positions:
            if pos["exit_time"] <= entry_time:
                pnl = pos["position_size_sek"] * pos["net_return"]
                equity += pnl

                pos["pnl_sek"] = pnl
                pos["equity_after_trade"] = equity
                closed_trades.append(pos)

                equity_curve.append({
                    "trade_number": len(closed_trades),
                    "time": pos["exit_time"],
                    "equity": equity,
                })
            else:
                still_open.append(pos)

        open_positions = still_open

        if len(open_positions) < max_positions:
            new_position = trade.to_dict()

            # IMPORTANT:
            # Position size is locked at ENTRY time.
            # This avoids lookahead bias from sizing at exit.
            new_position["position_size_sek"] = equity / max_positions

            open_positions.append(new_position)

    for pos in sorted(open_positions, key=lambda x: x["exit_time"]):
        pnl = pos["position_size_sek"] * pos["net_return"]
        equity += pnl

        pos["pnl_sek"] = pnl
        pos["equity_after_trade"] = equity
        closed_trades.append(pos)

        equity_curve.append({
            "trade_number": len(closed_trades),
            "time": pos["exit_time"],
            "equity": equity,
        })

    closed_df = pd.DataFrame(closed_trades)
    equity_df = pd.DataFrame(equity_curve)

    return closed_df, equity_df


def max_drawdown(equity_df):
    if len(equity_df) == 0:
        return None

    rolling_peak = equity_df["equity"].cummax().clip(lower=INITIAL_CAPITAL)
    drawdown = equity_df["equity"] / rolling_peak - 1

    return drawdown.min()


def summarize(label, closed_df, equity_df):
    if len(closed_df) == 0:
        return None

    final_equity = equity_df["equity"].iloc[-1]
    total_return = final_equity / INITIAL_CAPITAL - 1
    win_rate = (closed_df["net_return"] > 0).mean()
    avg_trade = closed_df["net_return"].mean()
    dd = max_drawdown(equity_df)

    gross_profit = closed_df.loc[closed_df["pnl_sek"] > 0, "pnl_sek"].sum()
    gross_loss = abs(closed_df.loc[closed_df["pnl_sek"] < 0, "pnl_sek"].sum())

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    return {
        "scenario": label,
        "max_positions": label,
        "trades_taken": len(closed_df),
        "final_equity": final_equity,
        "total_return": total_return,
        "win_rate": win_rate,
        "avg_trade": avg_trade,
        "profit_factor": profit_factor,
        "max_drawdown": dd,
    }


def main():
    print("\n=== ORB PORTFOLIO SIMULATION — AUDITED ===")

    df = load_intraday_prices()

    trades = build_orb_trades(
        df=df,
        allowed_tickers=TICKERS,
        breakout_start="09:35",
        breakout_end="11:00",
        r_multiple=1.0,
        max_opening_range=0.03,
        min_gap=0.0,
        cost_per_trade=COST_PER_TRADE,
    )

    if len(trades) == 0:
        print("No trades found.")
        return

    results = []

    for max_positions in [1, 2, 3, 5]:
        closed_df, equity_df = simulate_portfolio(
            trades,
            max_positions=max_positions,
        )

        result = summarize(
            label=max_positions,
            closed_df=closed_df,
            equity_df=equity_df,
        )

        results.append(result)

        closed_file = DATA_DIR / f"orb_portfolio_trades_max_{max_positions}.csv"
        equity_file = DATA_DIR / f"orb_portfolio_equity_max_{max_positions}.csv"

        closed_df.to_csv(closed_file, index=False)
        equity_df.to_csv(equity_file, index=False)

        print(f"\n--- MAX POSITIONS: {max_positions} ---")
        print(f"Trades taken : {len(closed_df)}")
        print(f"Final equity : {equity_df['equity'].iloc[-1]:.2f}")

    results_df = pd.DataFrame(results)
    results_df.to_csv(OUTPUT_FILE, index=False)

    print("\n=== PORTFOLIO SIMULATION SUMMARY ===")
    print(results_df.to_string(index=False))

    print(f"\nSaved summary -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()