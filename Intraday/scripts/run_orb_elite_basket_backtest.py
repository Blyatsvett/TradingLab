from Intraday.core.orb_research import (
    load_normalised_intraday_prices,
    run_research_backtest,
)
from Intraday.core.orb_strategy import orb_summary
from Intraday.core.paths import DATA_DIR


ELITE_BASKET_TICKERS = [
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "SEB-A.ST",
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

TRADES_FILE = DATA_DIR / "orb_elite_basket_trades.csv"
EQUITY_FILE = DATA_DIR / "orb_elite_basket_equity_curve.csv"


def main() -> None:
    print("\n=== ORB ELITE BASKET BACKTEST ===")
    print("Using shared ORB execution engine.")
    print(f"Tickers: {', '.join(ELITE_BASKET_TICKERS)}")
    print(f"Breakout window: {BREAKOUT_START} to {BREAKOUT_END}")
    print(f"R multiple: {R_MULTIPLE}")
    print(f"Max opening range: {MAX_OPENING_RANGE:.2%}")
    print(f"Min gap: {MIN_GAP:.2%}")
    print(f"Cost per trade: {COST_PER_TRADE:.4%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

    trades, equity_curve = run_research_backtest(
        prices=prices,
        allowed_tickers=ELITE_BASKET_TICKERS,
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
        verbose=True,
    )

    if trades.empty:
        print("No trades found.")
        return

    trades.to_csv(TRADES_FILE, index=False)
    equity_curve.to_csv(EQUITY_FILE, index=False)

    orb_summary(
        trades=trades,
        equity_curve=equity_curve,
        initial_capital=INITIAL_CAPITAL,
    )

    print(f"\nSaved elite basket trades -> {TRADES_FILE}")
    print(f"Saved elite basket equity -> {EQUITY_FILE}")


if __name__ == "__main__":
    main()