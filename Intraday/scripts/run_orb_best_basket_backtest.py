from Intraday.core.paths import DATA_DIR
from Intraday.core.orb_strategy import (
    load_intraday_prices,
    build_orb_trades,
    simulate_orb_equity,
    orb_summary,
)


BEST_BASKET_TICKERS = [
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "SEB-A.ST",
    "ATCO-A.ST",
]

INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10

TRADES_FILE = DATA_DIR / "orb_best_basket_trades.csv"
EQUITY_FILE = DATA_DIR / "orb_best_basket_equity_curve.csv"


def main():
    print("\n=== ORB BEST BASKET BACKTEST ===")

    df = load_intraday_prices()

    trades = build_orb_trades(
        df=df,
        allowed_tickers=BEST_BASKET_TICKERS,
        breakout_start="09:35",
        breakout_end="11:00",
        r_multiple=1.0,
        max_opening_range=0.03,
        min_gap=0.0,
        cost_per_trade=0.0005,
    )

    if len(trades) == 0:
        print("No trades found.")
        return

    trades = trades.sort_values("entry_time").reset_index(drop=True)
    trades["trade_number"] = trades.index + 1

    trades, equity_curve = simulate_orb_equity(
        trades,
        initial_capital=INITIAL_CAPITAL,
        position_size=POSITION_SIZE,
    )

    equity_curve = equity_curve.reset_index(drop=True)
    equity_curve["trade_number"] = equity_curve.index + 1

    equity_curve["rolling_peak"] = (
        equity_curve["equity"]
        .cummax()
        .clip(lower=INITIAL_CAPITAL)
    )

    equity_curve["drawdown_sek"] = (
        equity_curve["equity"] - equity_curve["rolling_peak"]
    )

    equity_curve["drawdown_pct"] = (
        equity_curve["equity"] / equity_curve["rolling_peak"] - 1
    )

    trades.to_csv(TRADES_FILE, index=False)
    equity_curve.to_csv(EQUITY_FILE, index=False)

    orb_summary(
        trades=trades,
        equity_curve=equity_curve,
        initial_capital=INITIAL_CAPITAL,
    )

    print(f"\nSaved best basket trades -> {TRADES_FILE}")
    print(f"Saved best basket equity -> {EQUITY_FILE}")


if __name__ == "__main__":
    main()