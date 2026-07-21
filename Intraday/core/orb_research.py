from __future__ import annotations

import pandas as pd

from Intraday.core.orb_execution import execute_long_orb_trade
from Intraday.core.orb_strategy import (
    build_orb_trades,
    load_intraday_prices,
    simulate_orb_equity,
)


SHARED_TO_RESEARCH_EXIT_REASON = {
    "STOP_HIT": "stop",
    "TARGET_HIT": "target",
    "CLOSED_EOD": "close",
}


# Research/backtest outputs should use completed sessions only.
# Production/paper can still use live intraday data from the current day.
RESEARCH_COMPLETED_SESSION_TIME = "16:30"


def normalise_prices(df: pd.DataFrame) -> pd.DataFrame:
    prices = df.copy()

    required_columns = [
        "ticker",
        "datetime",
        "high",
        "low",
        "close",
    ]

    for column in required_columns:
        if column not in prices.columns:
            raise ValueError(f"Intraday prices missing required column: {column}")

    prices["ticker"] = prices["ticker"].astype(str)
    prices["datetime"] = pd.to_datetime(prices["datetime"], errors="coerce")

    for column in ["high", "low", "close"]:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")

    prices = prices.dropna(
        subset=[
            "ticker",
            "datetime",
            "high",
            "low",
            "close",
        ]
    )

    prices = prices.sort_values(["ticker", "datetime"]).reset_index(drop=True)

    return prices


def load_normalised_intraday_prices() -> pd.DataFrame:
    return normalise_prices(load_intraday_prices())


def filter_to_completed_research_sessions(
    prices: pd.DataFrame,
    completion_time: str = RESEARCH_COMPLETED_SESSION_TIME,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Exclude the latest session from research/backtest calculations when that
    session is still incomplete.

    This is intentionally research-only.

    Production/paper trading may use today's live intraday bars.
    Strategy Lab/backtests should not try to close trades from an unfinished
    trading day, because a trade opened during the live session may have no
    post-entry bars yet.
    """

    if prices.empty:
        return prices.copy()

    output = normalise_prices(prices)

    timestamp_text = output["datetime"].astype(str)

    session_dates = pd.to_datetime(
        timestamp_text.str.slice(0, 10),
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")

    session_times = timestamp_text.str.extract(r"(\d{2}:\d{2})")[0]

    valid_mask = session_dates.notna() & session_times.notna()

    if not valid_mask.any():
        if verbose:
            print(
                "Research session filter: could not parse session dates/times. "
                "Using prices unchanged."
            )
        return output.reset_index(drop=True)

    latest_date = session_dates[valid_mask].max()
    latest_date_mask = session_dates.eq(latest_date)
    latest_time = session_times[latest_date_mask & valid_mask].max()

    if latest_time < completion_time:
        filtered = output.loc[~latest_date_mask].copy()

        if verbose:
            print(
                "Research session filter: excluded incomplete latest session "
                f"{latest_date}. Latest bar was {latest_time}; "
                f"completion threshold is {completion_time}."
            )
            print(
                f"Research rows before filter: {len(output)} | "
                f"after filter: {len(filtered)}"
            )

        return filtered.reset_index(drop=True)

    if verbose:
        print(
            "Research session filter: latest session appears complete "
            f"({latest_date}, latest bar {latest_time})."
        )

    return output.reset_index(drop=True)


def reexecute_trade_with_shared_engine(
    trade: pd.Series,
    prices: pd.DataFrame,
    cost_per_trade: float,
    same_bar_priority: str = "STOP",
    eod_exit_time: str | None = None,
) -> dict:
    ticker = str(trade["ticker"])
    entry_time = pd.to_datetime(trade["entry_time"], errors="coerce")

    if pd.isna(entry_time):
        raise ValueError(f"Invalid entry_time for ticker={ticker}: {trade['entry_time']}")

    bars = prices[
        (prices["ticker"] == ticker)
        & (prices["datetime"].dt.date == entry_time.date())
    ].copy()

    if bars.empty:
        raise ValueError(
            f"No intraday bars found for ticker={ticker}, date={entry_time.date()}"
        )

    result = execute_long_orb_trade(
        entry_time=entry_time,
        entry_price=float(trade["entry_price"]),
        stop_price=float(trade["stop_price"]),
        target_price=float(trade["target_price"]),
        bars=bars,
        timestamp_col="datetime",
        close_if_no_hit=True,
        same_bar_priority=same_bar_priority,
        eod_exit_time=eod_exit_time,
    )

    if result.status != "CLOSED":
        raise ValueError(
            "Shared execution engine did not close research trade: "
            f"ticker={ticker}, entry_time={entry_time}, reason={result.exit_reason}"
        )

    research_exit_reason = SHARED_TO_RESEARCH_EXIT_REASON.get(
        result.exit_reason,
        result.exit_reason,
    )

    return {
        "exit_time": result.exit_time,
        "exit_price": result.exit_price,
        "exit_reason": research_exit_reason,
        "gross_return": result.pnl_pct,
        "net_return": result.pnl_pct - cost_per_trade,
    }


def reexecute_trades_with_shared_engine(
    trades: pd.DataFrame,
    prices: pd.DataFrame,
    cost_per_trade: float,
    same_bar_priority: str = "STOP",
    eod_exit_time: str | None = None,
    verbose: bool = False,
) -> pd.DataFrame:
    trades = trades.copy()

    if trades.empty:
        return trades

    changed_exit_count = 0

    for idx, trade in trades.iterrows():
        original_exit_reason = str(trade.get("exit_reason", ""))
        original_exit_price = pd.to_numeric(
            trade.get("exit_price", 0),
            errors="coerce",
        )

        execution = reexecute_trade_with_shared_engine(
            trade=trade,
            prices=prices,
            cost_per_trade=cost_per_trade,
            same_bar_priority=same_bar_priority,
            eod_exit_time=eod_exit_time,
        )

        trades.loc[idx, "exit_time"] = execution["exit_time"]
        trades.loc[idx, "exit_price"] = execution["exit_price"]
        trades.loc[idx, "exit_reason"] = execution["exit_reason"]
        trades.loc[idx, "gross_return"] = execution["gross_return"]
        trades.loc[idx, "net_return"] = execution["net_return"]

        new_exit_reason = str(execution["exit_reason"])
        new_exit_price = float(execution["exit_price"])

        if (
            original_exit_reason != new_exit_reason
            or pd.isna(original_exit_price)
            or abs(float(original_exit_price) - new_exit_price) > 0.01
        ):
            changed_exit_count += 1

    if verbose:
        print(f"Trades re-executed with shared engine: {len(trades)}")
        print(
            "Trades with changed exit reason/price vs old builder output: "
            f"{changed_exit_count}"
        )

    return trades


def build_research_trades(
    prices: pd.DataFrame,
    allowed_tickers: list[str],
    breakout_start: str,
    breakout_end: str,
    r_multiple: float,
    max_opening_range: float,
    min_gap: float,
    cost_per_trade: float,
    same_bar_priority: str = "STOP",
    eod_exit_time: str | None = None,
    verbose: bool = False,
    completed_sessions_only: bool = True,
) -> pd.DataFrame:
    prices = normalise_prices(prices)

    if completed_sessions_only:
        prices = filter_to_completed_research_sessions(
            prices,
            verbose=verbose,
        )

    trades = build_orb_trades(
        df=prices,
        allowed_tickers=allowed_tickers,
        breakout_start=breakout_start,
        breakout_end=breakout_end,
        r_multiple=r_multiple,
        max_opening_range=max_opening_range,
        min_gap=min_gap,
        cost_per_trade=cost_per_trade,
    )

    if trades.empty:
        return trades

    trades = trades.sort_values("entry_time").reset_index(drop=True)

    trades = reexecute_trades_with_shared_engine(
        trades=trades,
        prices=prices,
        cost_per_trade=cost_per_trade,
        same_bar_priority=same_bar_priority,
        eod_exit_time=eod_exit_time,
        verbose=verbose,
    )

    return trades


def add_equity_curve_fields(
    equity_curve: pd.DataFrame,
    initial_capital: float,
) -> pd.DataFrame:
    equity_curve = equity_curve.copy().reset_index(drop=True)

    if equity_curve.empty:
        return equity_curve

    equity_curve["trade_number"] = equity_curve.index + 1
    equity_curve["rolling_peak"] = equity_curve["equity"].cummax().clip(
        lower=initial_capital
    )
    equity_curve["drawdown_sek"] = equity_curve["equity"] - equity_curve["rolling_peak"]
    equity_curve["drawdown_pct"] = (
        equity_curve["equity"] / equity_curve["rolling_peak"] - 1
    )

    return equity_curve


def run_research_backtest(
    prices: pd.DataFrame,
    allowed_tickers: list[str],
    breakout_start: str,
    breakout_end: str,
    r_multiple: float,
    max_opening_range: float,
    min_gap: float,
    cost_per_trade: float,
    initial_capital: float,
    position_size: float,
    same_bar_priority: str = "STOP",
    eod_exit_time: str | None = None,
    verbose: bool = False,
    completed_sessions_only: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = normalise_prices(prices)

    if completed_sessions_only:
        prices = filter_to_completed_research_sessions(
            prices,
            verbose=verbose,
        )

    trades = build_research_trades(
        prices=prices,
        allowed_tickers=allowed_tickers,
        breakout_start=breakout_start,
        breakout_end=breakout_end,
        r_multiple=r_multiple,
        max_opening_range=max_opening_range,
        min_gap=min_gap,
        cost_per_trade=cost_per_trade,
        same_bar_priority=same_bar_priority,
        eod_exit_time=eod_exit_time,
        verbose=verbose,
        completed_sessions_only=False,
    )

    if trades.empty:
        return trades, pd.DataFrame()

    trades = trades.sort_values("entry_time").reset_index(drop=True)
    trades["trade_number"] = trades.index + 1

    trades, equity_curve = simulate_orb_equity(
        trades,
        initial_capital=initial_capital,
        position_size=position_size,
    )

    equity_curve = add_equity_curve_fields(
        equity_curve=equity_curve,
        initial_capital=initial_capital,
    )

    return trades, equity_curve


def calculate_max_drawdown(
    equity_curve: pd.DataFrame,
    initial_capital: float,
) -> float | None:
    if equity_curve.empty:
        return None

    if "drawdown_pct" in equity_curve.columns:
        return equity_curve["drawdown_pct"].min()

    rolling_peak = equity_curve["equity"].cummax().clip(lower=initial_capital)
    drawdown = equity_curve["equity"] / rolling_peak - 1

    return drawdown.min()


def calculate_profit_factor(trades: pd.DataFrame) -> float | None:
    if trades.empty or "pnl" not in trades.columns:
        return None

    gross_profit = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gross_loss = abs(trades.loc[trades["pnl"] < 0, "pnl"].sum())

    if gross_loss <= 0:
        return None

    return gross_profit / gross_loss


def summarize_research_backtest(
    trades: pd.DataFrame,
    equity_curve: pd.DataFrame,
    initial_capital: float,
) -> dict | None:
    if trades.empty or equity_curve.empty:
        return None

    final_equity = equity_curve["equity"].iloc[-1]
    total_return = final_equity / initial_capital - 1
    win_rate = (trades["net_return"] > 0).mean()
    avg_trade = trades["net_return"].mean()
    max_dd = calculate_max_drawdown(
        equity_curve=equity_curve,
        initial_capital=initial_capital,
    )
    profit_factor = calculate_profit_factor(trades)

    return {
        "trades": len(trades),
        "final_equity": final_equity,
        "total_return": total_return,
        "win_rate": win_rate,
        "avg_trade": avg_trade,
        "max_drawdown": max_dd,
        "profit_factor": profit_factor,
    }