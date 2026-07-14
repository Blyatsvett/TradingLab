import pandas as pd

from Intraday.core.paths import DATA_DIR
from Intraday.core.orb_strategy import (
    load_intraday_prices,
    build_orb_trades,
    simulate_orb_equity,
)


TICKERS = [
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "SEB-A.ST",
    "ATCO-A.ST",
]

INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10

OUTPUT_FILE = DATA_DIR / "orb_market_regime_test.csv"


def summarize(label, trades):
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

    gross_profit = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gross_loss = abs(trades.loc[trades["pnl"] < 0, "pnl"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    rolling_peak = equity_curve["equity"].cummax().clip(lower=INITIAL_CAPITAL)
    drawdown = equity_curve["equity"] / rolling_peak - 1
    max_drawdown = drawdown.min()

    return {
        "label": label,
        "trades": len(trades),
        "final_equity": final_equity,
        "total_return": total_return,
        "win_rate": win_rate,
        "avg_trade": avg_trade,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
    }


def main():
    print("\n=== ORB MARKET REGIME FILTER TEST ===")

    df = load_intraday_prices()

    trades = build_orb_trades(
        df=df,
        allowed_tickers=TICKERS,
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

    # Market proxy: average daily gap across selected basket
    market_gap = (
        trades.groupby("date")["gap"]
        .mean()
        .reset_index()
        .rename(columns={"gap": "market_gap"})
    )

    trades = trades.merge(market_gap, on="date", how="left")

    all_trades = trades.copy()
    positive_market = trades[trades["market_gap"] > 0].copy()
    strong_positive_market = trades[trades["market_gap"] > 0.0025].copy()
    negative_market = trades[trades["market_gap"] <= 0].copy()

    results = [
        summarize("ALL_TRADES", all_trades),
        summarize("MARKET_GAP_GT_0", positive_market),
        summarize("MARKET_GAP_GT_0_25", strong_positive_market),
        summarize("MARKET_GAP_LTE_0", negative_market),
    ]

    results = [r for r in results if r is not None]
    results_df = pd.DataFrame(results)

    results_df.to_csv(OUTPUT_FILE, index=False)

    print("\n=== MARKET REGIME RESULTS ===")
    print(results_df.to_string(index=False))
    print(f"\nSaved -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()