import itertools
import pandas as pd

from Intraday.core.paths import DATA_DIR
from Intraday.core.orb_strategy import (
    load_intraday_prices,
    build_orb_trades,
    simulate_orb_equity,
)


ALLOWED_TICKERS = [
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

OUTPUT_FILE = DATA_DIR / "orb_parameter_optimization.csv"


R_MULTIPLES = [0.5, 1.0, 1.5, 2.0]
MAX_OPENING_RANGES = [0.01, 0.015, 0.02, 0.03]
MIN_GAPS = [0.0, 0.0025, 0.005, 0.01]
BREAKOUT_WINDOWS = [
    ("09:35", "10:00"),
    ("09:35", "10:30"),
    ("09:35", "11:00"),
]


def max_drawdown(equity_curve):
    if len(equity_curve) == 0:
        return None

    rolling_peak = equity_curve["equity"].cummax().clip(lower=INITIAL_CAPITAL)
    drawdown = equity_curve["equity"] / rolling_peak - 1

    return drawdown.min()


def main():
    print("\n=== ORB PARAMETER OPTIMIZATION ===")

    df = load_intraday_prices()

    results = []

    combinations = list(
        itertools.product(
            R_MULTIPLES,
            MAX_OPENING_RANGES,
            MIN_GAPS,
            BREAKOUT_WINDOWS,
        )
    )

    print(f"Testing combinations: {len(combinations)}")

    for i, (r_multiple, max_range, min_gap, window) in enumerate(combinations, start=1):
        breakout_start, breakout_end = window

        trades = build_orb_trades(
            df=df,
            allowed_tickers=ALLOWED_TICKERS,
            breakout_start=breakout_start,
            breakout_end=breakout_end,
            r_multiple=r_multiple,
            max_opening_range=max_range,
            min_gap=min_gap,
            cost_per_trade=0.0005,
        )

        if len(trades) == 0:
            continue

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
        dd = max_drawdown(equity_curve)

        profit_factor = (
            trades.loc[trades["pnl"] > 0, "pnl"].sum()
            / abs(trades.loc[trades["pnl"] < 0, "pnl"].sum())
            if abs(trades.loc[trades["pnl"] < 0, "pnl"].sum()) > 0
            else None
        )

        results.append({
            "r_multiple": r_multiple,
            "max_opening_range": max_range,
            "min_gap": min_gap,
            "breakout_start": breakout_start,
            "breakout_end": breakout_end,
            "trades": len(trades),
            "final_equity": final_equity,
            "total_return": total_return,
            "win_rate": win_rate,
            "avg_trade": avg_trade,
            "max_drawdown": dd,
            "profit_factor": profit_factor,
        })

        print(
            f"{i}/{len(combinations)} "
            f"R={r_multiple}, range={max_range:.2%}, gap={min_gap:.2%}, "
            f"{breakout_start}-{breakout_end} "
            f"=> return={total_return:.2%}, trades={len(trades)}"
        )

    results_df = pd.DataFrame(results)

    results_df = results_df.sort_values(
        ["total_return", "profit_factor", "trades"],
        ascending=[False, False, False],
    )

    results_df.to_csv(OUTPUT_FILE, index=False)

    print("\n=== TOP 10 PARAMETER SETS ===")
    print(results_df.head(10).to_string(index=False))

    print(f"\nSaved optimization results -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()