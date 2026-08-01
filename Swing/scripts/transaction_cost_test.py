from core.data_loader import load_prices
from core.alpha_model import build_alpha
from core.simulator import simulate_portfolio
from core.metrics import performance_summary

import pandas as pd


def calculate_turnover(portfolio_history):
    dates = sorted(portfolio_history["date"].unique())
    turnover_rows = []

    for i in range(1, len(dates)):
        prev_date = dates[i - 1]
        curr_date = dates[i]

        prev_port = portfolio_history[
            portfolio_history["date"] == prev_date
        ][["ticker", "weight"]].rename(columns={"weight": "prev_weight"})

        curr_port = portfolio_history[
            portfolio_history["date"] == curr_date
        ][["ticker", "weight"]].rename(columns={"weight": "curr_weight"})

        merged = prev_port.merge(
            curr_port,
            on="ticker",
            how="outer"
        ).fillna(0)

        turnover = (
            merged["curr_weight"] - merged["prev_weight"]
        ).abs().sum()

        turnover_rows.append({
            "date": curr_date,
            "turnover": turnover
        })

    return pd.DataFrame(turnover_rows)


def apply_transaction_costs(daily_returns, turnover, cost_rate):
    df = daily_returns.merge(
        turnover,
        on="date",
        how="left"
    )

    df["turnover"] = df["turnover"].fillna(0)

    df["cost"] = df["turnover"] * cost_rate

    df["net_daily_return"] = (
        df["daily_return"] - df["cost"]
    )

    equity = 10000
    equity_history = []

    for _, row in df.iterrows():
        equity *= (1 + row["net_daily_return"])

        equity_history.append({
            "date": row["date"],
            "equity": equity
        })

    equity_curve = pd.DataFrame(equity_history)

    net_returns = df[["date", "net_daily_return"]].rename(
        columns={"net_daily_return": "daily_return"}
    )

    return equity_curve, net_returns


df = load_prices()
df = build_alpha(df)

equity_curve, daily_returns, trade_log, portfolio_history = simulate_portfolio(df)

turnover = calculate_turnover(portfolio_history)

cost_rates = [0.0000, 0.0005, 0.0010, 0.0020]

for cost_rate in cost_rates:
    print("\n")
    print("=" * 60)
    print(f"TRANSACTION COST TEST: {cost_rate:.2%} per turnover")
    print("=" * 60)

    net_equity, net_returns = apply_transaction_costs(
        daily_returns,
        turnover,
        cost_rate
    )

    performance_summary(
        net_equity,
        net_returns
    )