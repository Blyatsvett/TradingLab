import itertools

import pandas as pd

from Intraday.core.orb_research import (
    load_normalised_intraday_prices,
    run_research_backtest,
    summarize_research_backtest,
)
from Intraday.core.paths import DATA_DIR


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
COST_PER_TRADE = 0.0005

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

OUTPUT_FILE = DATA_DIR / "orb_parameter_optimization.csv"


R_MULTIPLES = [0.5, 1.0, 1.5, 2.0]
MAX_OPENING_RANGES = [0.01, 0.015, 0.02, 0.03]
MIN_GAPS = [0.0, 0.0025, 0.005, 0.01]
BREAKOUT_WINDOWS = [
    ("09:35", "10:00"),
    ("09:35", "10:30"),
    ("09:35", "11:00"),
]


def main() -> None:
    print("\n=== ORB PARAMETER OPTIMIZATION ===")
    print("Using shared ORB execution engine.")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    prices = load_normalised_intraday_prices()

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

    for i, (r_multiple, max_range, min_gap, window) in enumerate(
        combinations,
        start=1,
    ):
        breakout_start, breakout_end = window

        trades, equity_curve = run_research_backtest(
            prices=prices,
            allowed_tickers=ALLOWED_TICKERS,
            breakout_start=breakout_start,
            breakout_end=breakout_end,
            r_multiple=r_multiple,
            max_opening_range=max_range,
            min_gap=min_gap,
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
            continue

        results.append(
            {
                "r_multiple": r_multiple,
                "max_opening_range": max_range,
                "min_gap": min_gap,
                "breakout_start": breakout_start,
                "breakout_end": breakout_end,
                "trades": summary["trades"],
                "final_equity": summary["final_equity"],
                "total_return": summary["total_return"],
                "win_rate": summary["win_rate"],
                "avg_trade": summary["avg_trade"],
                "max_drawdown": summary["max_drawdown"],
                "profit_factor": summary["profit_factor"],
            }
        )

        print(
            f"{i}/{len(combinations)} "
            f"R={r_multiple}, range={max_range:.2%}, gap={min_gap:.2%}, "
            f"{breakout_start}-{breakout_end} "
            f"=> return={summary['total_return']:.2%}, trades={summary['trades']}"
        )

    results_df = pd.DataFrame(results)

    if results_df.empty:
        print("No optimization results found.")
        return

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