import pandas as pd

from Intraday.core.orb_research import (
    load_normalised_intraday_prices,
    run_research_backtest,
    summarize_research_backtest,
)
from Intraday.core.paths import DATA_DIR


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
COST_PER_TRADE = 0.0005

BREAKOUT_START = "09:35"
BREAKOUT_END = "11:00"
R_MULTIPLE = 1.0
MAX_OPENING_RANGE = 0.03
MIN_GAP = 0.0

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

OUTPUT_FILE = DATA_DIR / "orb_ticker_optimization.csv"


def evaluate_tickers(
    prices: pd.DataFrame,
    tickers: list[str],
    label: str,
) -> dict | None:
    trades, equity_curve = run_research_backtest(
        prices=prices,
        allowed_tickers=tickers,
        breakout_start=BREAKOUT_START,
        breakout_end=BREAKOUT_END,
        r_multiple=R_MULTIPLE,
        max_opening_range=MAX_OPENING_RANGE,
        min_gap=MIN_GAP,
        cost_per_trade=COST_PER_TRADE,
        initial_capital=INITIAL_CAPITAL,
        position_size=POSITION_SIZE,
        same_bar_priority=SAME_BAR_PRIORITY,
        eod_exit_time=EOD_EXIT_TIME,
        verbose=False,
    )

    summary = summarize_research_backtest(
        trades=trades,
        equity_curve=equity_curve,
        initial_capital=INITIAL_CAPITAL,
    )

    if summary is None:
        return None

    return {
        "label": label,
        "tickers": ",".join(tickers),
        "ticker_count": len(tickers),
        "trades": summary["trades"],
        "final_equity": summary["final_equity"],
        "total_return": summary["total_return"],
        "win_rate": summary["win_rate"],
        "avg_trade": summary["avg_trade"],
        "max_drawdown": summary["max_drawdown"],
        "profit_factor": summary["profit_factor"],
    }


def main() -> None:
    print("\n=== ORB TICKER OPTIMIZATION ===")
    print("Using shared ORB execution engine.")
    print(f"Breakout window: {BREAKOUT_START} to {BREAKOUT_END}")
    print(f"R multiple: {R_MULTIPLE}")
    print(f"Max opening range: {MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {MIN_GAP:.2%}")
    print(f"Cost per trade: {COST_PER_TRADE:.4%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

    results = []

    # Individual ticker performance
    for ticker in ALL_TICKERS:
        result = evaluate_tickers(
            prices=prices,
            tickers=[ticker],
            label=ticker,
        )

        if result is not None:
            results.append(result)

    # Remove one ticker at a time
    for ticker in ALL_TICKERS:
        tickers = [t for t in ALL_TICKERS if t != ticker]

        result = evaluate_tickers(
            prices=prices,
            tickers=tickers,
            label=f"WITHOUT_{ticker}",
        )

        if result is not None:
            results.append(result)

    # Full basket
    result = evaluate_tickers(
        prices=prices,
        tickers=ALL_TICKERS,
        label="ALL_TICKERS",
    )

    if result is not None:
        results.append(result)

    results_df = pd.DataFrame(results)

    if results_df.empty:
        print("No ticker optimization results found.")
        return

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