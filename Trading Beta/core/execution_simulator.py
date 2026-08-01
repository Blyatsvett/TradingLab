import pandas as pd

from core.portfolio import select_portfolio, compute_weights


def simulate_intraday_execution(df, top_n=10, initial_capital=10000):
    """
    Realistic daily execution simulator:

    Signal is built using close(T)
    Trade is entered at open(T+1)
    Trade is exited at close(T+1)

    Uses intraday_return = close / open - 1
    """

    equity = initial_capital

    equity_history = []
    return_history = []
    trade_history = []
    portfolio_history = []

    dates = sorted(df["date"].unique())

    print("\nRunning intraday execution simulation...")
    print(f"Trading days: {len(dates)}")

    for i in range(len(dates) - 1):

        signal_day = dates[i]
        execution_day = dates[i + 1]

        signal_data = df[df["date"] == signal_day].copy()

        execution_data = (
            df[df["date"] == execution_day][["ticker", "intraday_return"]]
            .copy()
            .rename(columns={"intraday_return": "future_intraday_return"})
        )

        if len(signal_data) == 0 or len(execution_data) == 0:
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
            ]
        ].copy()

        snapshot["signal_date"] = signal_day
        snapshot["execution_date"] = execution_day

        portfolio_history.append(snapshot)

        merged = portfolio.merge(
            execution_data,
            on="ticker",
            how="left",
        )

        merged["future_intraday_return"] = merged["future_intraday_return"].fillna(0)

        daily_return = (
        merged["weight"] * merged["future_intraday_return"]
        ).sum()

        equity *= (1 + daily_return)

        equity_history.append({
            "date": execution_day,
            "equity": equity,
        })

        return_history.append({
            "date": execution_day,
            "daily_return": daily_return,
        })

        trades = merged[
            [
                "ticker",
                "weight",
                "intraday_return",
            ]
        ].copy()

        trades["signal_date"] = signal_day
        trades["execution_date"] = execution_day

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