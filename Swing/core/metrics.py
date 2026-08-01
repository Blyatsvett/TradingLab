import numpy as np


def performance_summary(
    equity_curve,
    daily_returns,
    initial_capital=10000,
):
    """
    Compute and print portfolio performance statistics.
    """

    if len(equity_curve) == 0:
        print("No simulation results.")
        return

    final_equity = equity_curve["equity"].iloc[-1]

    total_return = (
        final_equity / initial_capital - 1
    )

    n_days = len(daily_returns)

    years = n_days / 252

    cagr = (
        (final_equity / initial_capital) ** (1 / years)
        - 1
    )

    vol = (
        daily_returns["daily_return"].std()
        * np.sqrt(252)
    )

    sharpe = (
        daily_returns["daily_return"].mean()
        / daily_returns["daily_return"].std()
        * np.sqrt(252)
    )

    running_max = equity_curve["equity"].cummax()

    drawdown = (
        equity_curve["equity"] - running_max
    ) / running_max

    max_drawdown = drawdown.min()

    win_rate = (
        (daily_returns["daily_return"] > 0)
        .mean()
    )

    print("\n")
    print("=" * 40)
    print("TRADINGLAB PERFORMANCE REPORT")
    print("=" * 40)

    print(f"Final Equity      : {final_equity:,.2f} SEK")
    print(f"Total Return      : {total_return:.2%}")
    print(f"CAGR              : {cagr:.2%}")
    print(f"Annual Volatility : {vol:.2%}")
    print(f"Sharpe Ratio      : {sharpe:.2f}")
    print(f"Max Drawdown      : {max_drawdown:.2%}")
    print(f"Win Rate          : {win_rate:.2%}")

    print("=" * 40)