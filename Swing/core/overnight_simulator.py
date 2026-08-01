import pandas as pd

from core.portfolio import select_portfolio, compute_weights


def simulate_overnight_execution(df, top_n=10, initial_capital=10000):
    """
    Overnight execution simulator.

    Signal is built using close(T).
    Portfolio is assumed entered at close(T).
    Exit is at open(T+1).

    Uses overnight_return = next_open / close - 1.
    """

    equity = initial_capital

    equity_history = []
    return_history = []
    trade_history = []
    portfolio_history = []

    dates = sorted(df["date"].unique())

    print("\nRunning overnight execution simulation...")
    print(f"Trading days: {len(dates)}")

    for i in range(len(dates) - 1):

        signal_day = dates[i]

        signal_data = df[df["date"] == signal_day].copy()

        if len(signal_data) == 0:
            continue

        portfolio = select_portfolio(signal_data, top_n)

        if len(portfolio) == 0:
            continue

        portfolio = compute_weights(portfolio)

        snapshot = portfolio[
            [
                "ticker",
                "alpha",
                "weight",
                "overnight_return",
            ]
        ].copy()

        snapshot["signal_date"] = signal_day

        portfolio_history.append(snapshot)

        portfolio["overnight_return"] = portfolio["overnight_return"].fillna(0)

        daily_return = (
            portfolio["weight"] * portfolio["overnight_return"]
        ).sum()

        equity *= (1 + daily_return)

        equity_history.append({
            "date": signal_day,
            "equity": equity,
        })

        return_history.append({
            "date": signal_day,
            "daily_return": daily_return,
        })

        trades = portfolio[
            [
                "ticker",
                "weight",
                "overnight_return",
            ]
        ].copy()

        trades["signal_date"] = signal_day

        trade_history.append(trades)

    equity_curve = pd.DataFrame(equity_history)
    daily_returns = pd.DataFrame(return_history)

    trade_log = (
        pd.concat(trade_history, ignore_index=True)
        if trade_history
        else pd.DataFrame()
    )

    portfolio_history = (
        pd.concat(portfolio_history, ignore_index=True)
        if portfolio_history
        else pd.DataFrame()
    )

    return equity_curve, daily_returns, trade_log, portfolio_history