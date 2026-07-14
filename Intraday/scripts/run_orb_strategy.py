from Intraday.core.orb_strategy import (
    load_intraday_prices,
    build_orb_trades,
    simulate_orb_equity,
    orb_summary,
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


df = load_intraday_prices()

trades = build_orb_trades(
    df,
    allowed_tickers=ALLOWED_TICKERS,
    breakout_start="09:35",
    breakout_end="11:00",
    r_multiple=1.0,
    max_opening_range=0.02,
    min_gap=0.0,
    cost_per_trade=0.0005,
)

trades, equity_curve = simulate_orb_equity(
    trades,
    initial_capital=10000,
    position_size=0.10,
)

print("\n=== ORB STRATEGY RUN ===")
print(trades.tail(20))

orb_summary(trades, equity_curve)