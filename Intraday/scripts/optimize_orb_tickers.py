import pandas as pd

from Intraday.core.paths import DATA_DIR
from Intraday.core.orb_strategy import (
    load_intraday_prices,
    build_orb_trades,
    simulate_orb_equity,
)


ALL_TICKERS = [
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "ATCO-A.ST",
    "EVO.ST",
    "SEB-A.ST",
    "ABB.ST",
]

INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10

OUTPUT_FILE = DATA_DIR / "orb_ticker_optimization.csv"


def calculate_max_drawdown(equity_curve):
    if len(equity_curve) == 0:
        return None

    rolling_peak = equity_curve["equity"].cummax().clip(lower=INITIAL_CAPITAL)
    drawdown = equity_curve["equity"] / rolling_peak - 1
    return drawdown.min()


def evaluate_tickers(tickers, label):
    df = load_intraday_prices()

    trades = build_orb_trades(
        df=df,
        allowed_tickers=tickers,
        breakout_start="09:35",
        breakout_end="11:00",
        r_multiple=1.0,
        max_opening_range=0.03,
        min_gap=0.0,
        cost_per_trade=0.0005,
    )

    if len(trades) == 0:
        return None

    trades = trades.sort_values("entry_time").reset_index(drop=True)

    trades, equity_curve = simulate_orb_equity(
        trades,
        initial_capital=INITIAL_CAPITAL,
        position_size=POSITION_SIZE,
    )

    final_equity = equity_curve["equity"].iloc[-1]
    total_return = final_equity / INITIAL_CAPITAL - 1
    win_rate = (trades["net_return"] > 0).mean()
    avg_trade = trades["net_return"].mean()
    max_dd = calculate_max_drawdown(equity_curve)

    gross_profit = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gross_loss = abs(trades.loc[trades["pnl"] < 0, "pnl"].sum())

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    return {
        "label": label,
        "tickers": ",".join(tickers),
        "ticker_count": len(tickers),
        "trades": len(trades),
        "final_equity": final_equity,
        "total_return": total_return,
        "win_rate": win_rate,
        "avg_trade": avg_trade,
        "max_drawdown": max_dd,
        "profit_factor": profit_factor,
    }


def main():
    print("\n=== ORB TICKER OPTIMIZATION ===")

    results = []

    # Individual ticker performance
    for ticker in ALL_TICKERS:
        result = evaluate_tickers([ticker], ticker)
        if result:
            results.append(result)

    # Remove one ticker at a time
    for ticker in ALL_TICKERS:
        tickers = [t for t in ALL_TICKERS if t != ticker]
        result = evaluate_tickers(tickers, f"WITHOUT_{ticker}")
        if result:
            results.append(result)

    # Full basket
    result = evaluate_tickers(ALL_TICKERS, "ALL_TICKERS")
    if result:
        results.append(result)

    results_df = pd.DataFrame(results)

    results_df = results_df.sort_values(
        ["total_return", "profit_factor", "trades"],
        ascending=[False, False, False],
    )

    results_df.to_csv(OUTPUT_FILE, index=False)

    print("\n=== TICKER OPTIMIZATION RESULTS ===")
    print(results_df.to_string(index=False))

    print(f"\nSaved ticker optimization -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()