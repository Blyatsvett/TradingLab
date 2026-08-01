import pandas as pd

from core.portfolio import (
    select_portfolio,
    compute_weights,
)


def simulate_portfolio(df, top_n=10, initial_capital=10000):
    """
    Simulate a daily-rebalanced portfolio.

    Returns
    -------
    equity_curve : DataFrame
    daily_returns : DataFrame
    trade_log : DataFrame
    portfolio_history : DataFrame
    """

    equity = initial_capital

    equity_history = []
    return_history = []
    trade_history = []
    portfolio_history = []

    dates = sorted(df["date"].unique())

    print("\nRunning simulation...\n")
    print(f"Trading days: {len(dates)}")

    for i in range(len(dates) - 1):

        today = dates[i]
        tomorrow = dates[i + 1]

        # ----------------------------------
        # Today's universe
        # ----------------------------------
        today_data = df[df["date"] == today].copy()

        # Tomorrow's realized returns
        next_data = df[df["date"] == tomorrow][
            ["ticker", "return"]
        ].copy()

        if len(today_data) == 0 or len(next_data) == 0:
            continue

        # Clean tickers
        today_data["ticker"] = (
            today_data["ticker"]
            .astype(str)
            .str.strip()
            .str.upper()
        )

        next_data["ticker"] = (
            next_data["ticker"]
            .astype(str)
            .str.strip()
            .str.upper()
        )

        # ----------------------------------
        # Select portfolio
        # ----------------------------------
        portfolio = select_portfolio(today_data, top_n)

        if len(portfolio) == 0:
            continue

        # ----------------------------------
        # Compute weights
        # ----------------------------------
        portfolio = compute_weights(portfolio)

        # ----------------------------------
        # Save today's portfolio
        # ----------------------------------
        snapshot = portfolio[
            [
                "ticker",
                "alpha",
                "weight",
            ]
        ].copy()

        snapshot["date"] = today

        portfolio_history.append(snapshot)

        # ----------------------------------
        # Merge tomorrow's returns
        # ----------------------------------
        merged = portfolio.merge(
            next_data,
            on="ticker",
            how="left",
            suffixes=("", "_next"),
        )

        # Safe handling of missing return column
        if "return" not in merged.columns:

            if "return_next" in merged.columns:
                merged["return"] = merged["return_next"]
            else:
                merged["return"] = 0.0

        merged["return"] = merged["return"].fillna(0)

        # ----------------------------------
        # Portfolio return
        # ----------------------------------
        daily_return = (
            merged["weight"] * merged["return"]
        ).sum()

        equity *= (1 + daily_return)

        # ----------------------------------
        # Equity history
        # ----------------------------------
        equity_history.append(
            {
                "date": tomorrow,
                "equity": equity,
            }
        )

        # ----------------------------------
        # Daily returns
        # ----------------------------------
        return_history.append(
            {
                "date": tomorrow,
                "daily_return": daily_return,
            }
        )

        # ----------------------------------
        # Trade log
        # ----------------------------------
        trades = merged[
            [
                "ticker",
                "weight",
                "return",
            ]
        ].copy()

        trades["date"] = tomorrow

        trade_history.append(trades)

    # ----------------------------------
    # Convert lists to DataFrames
    # ----------------------------------

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

    return (
        equity_curve,
        daily_returns,
        trade_log,
        portfolio_history,
    )