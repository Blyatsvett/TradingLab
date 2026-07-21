from __future__ import annotations

from itertools import combinations

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.market_regime import (
    attach_market_regime,
    calculate_daily_market_regime,
)
from Intraday.core.orb_config import (
    ORB_ALLOWED_TICKERS,
    ORB_BREAKOUT_END,
    ORB_BREAKOUT_START,
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_MAX_OPEN_POSITIONS,
    ORB_MAX_OPENING_RANGE,
    ORB_MIN_GAP,
    ORB_POSITION_SIZE,
    ORB_R_MULTIPLE,
)
from Intraday.core.orb_execution import execute_long_orb_trade
from Intraday.core.orb_research import (
    build_research_trades,
    load_normalised_intraday_prices,
    filter_to_completed_research_sessions,
)
from Intraday.core.paths import DATA_DIR


OUTPUT_SUMMARY_FILE = DATA_DIR / "intraday_strategy_lab_summary.csv"
OUTPUT_TRADES_FILE = DATA_DIR / "intraday_strategy_lab_trades.csv"
OUTPUT_EQUITY_FILE = DATA_DIR / "intraday_strategy_lab_equity_curve.csv"
OUTPUT_DAILY_FILE = DATA_DIR / "intraday_strategy_lab_daily_summary.csv"
OUTPUT_OVERLAP_FILE = DATA_DIR / "intraday_strategy_lab_overlap.csv"
OUTPUT_REGIME_SUMMARY_FILE = DATA_DIR / "intraday_strategy_lab_regime_summary.csv"
OUTPUT_CANDIDATES_FILE = DATA_DIR / "intraday_strategy_lab_candidates.csv"
OUTPUT_MARKET_REGIME_FILE = DATA_DIR / "intraday_strategy_lab_market_regime.csv"

SAME_BAR_PRIORITY = "STOP"

# Research/backtest convention:
# use final available bar of the day for EOD closes.
EOD_EXIT_TIME = None

LAB_STRATEGY_VERSION = "INTRADAY_STRATEGY_LAB_V1"

ORB_BREAKOUT_NAME = "01_ORB_BREAKOUT_BASELINE"
ORB_PULLBACK_NAME = "02_ORB_PULLBACK_RETEST"
VWAP_RECLAIM_NAME = "03_VWAP_RECLAIM"
GAP_DOWN_RECOVERY_NAME = "04_GAP_DOWN_RECOVERY"
PREVIOUS_DAY_HIGH_BREAKOUT_NAME = "05_PREVIOUS_DAY_HIGH_BREAKOUT"

OPENING_RANGE_START = "09:30"
OPENING_RANGE_END = ORB_BREAKOUT_START

PULLBACK_RETEST_END = "12:00"
VWAP_RECLAIM_START = "09:45"
VWAP_RECLAIM_END = "13:00"
GAP_RECOVERY_START = "09:45"
GAP_RECOVERY_END = "13:00"
PREV_HIGH_BREAKOUT_START = "09:45"
PREV_HIGH_BREAKOUT_END = "14:00"

MIN_GAP_DOWN_FOR_RECOVERY = -0.005
MAX_ACCEPTED_TRADE_RISK_PCT = 0.035

EXIT_REASON_MAP = {
    "STOP_HIT": "stop",
    "TARGET_HIT": "target",
    "CLOSED_EOD": "close",
    "OPEN_NO_BARS": "open_no_bars",
    "OPEN_NO_EXIT": "open_no_exit",
}


def detect_timestamp_column(df: pd.DataFrame) -> str:
    for col in ["timestamp", "datetime", "date_time", "time"]:
        if col in df.columns:
            return col

    raise ValueError(
        "Could not find a timestamp column. Expected one of: "
        "timestamp, datetime, date_time, time"
    )


def prepare_prices(
    prices: pd.DataFrame,
    allowed_tickers: list[str] | None = None,
) -> pd.DataFrame:
    df = prices.copy()

    timestamp_col = detect_timestamp_column(df)

    df["timestamp"] = pd.to_datetime(df[timestamp_col], errors="coerce")
    df = df.dropna(subset=["timestamp"])

    df["date"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["time"] = df["timestamp"].dt.strftime("%H:%M")

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "volume" not in df.columns:
        df["volume"] = 0.0

    if allowed_tickers is not None:
        df = df[df["ticker"].isin(allowed_tickers)].copy()

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values(["ticker", "timestamp"]).reset_index(drop=True)

    return df


def calculate_daily_references(prices: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for (ticker, trade_date), day in prices.groupby(["ticker", "date"]):
        day = day.sort_values("timestamp").copy()

        if day.empty:
            continue

        rows.append(
            {
                "ticker": ticker,
                "date": trade_date,
                "day_open": float(day.iloc[0]["open"]),
                "day_high": float(day["high"].max()),
                "day_low": float(day["low"].min()),
                "day_close": float(day.iloc[-1]["close"]),
            }
        )

    daily = pd.DataFrame(rows)

    if daily.empty:
        return daily

    daily = daily.sort_values(["ticker", "date"]).reset_index(drop=True)

    daily["previous_close"] = daily.groupby("ticker")["day_close"].shift(1)
    daily["previous_high"] = daily.groupby("ticker")["day_high"].shift(1)
    daily["previous_low"] = daily.groupby("ticker")["day_low"].shift(1)

    daily["gap_pct"] = (daily["day_open"] / daily["previous_close"]) - 1.0
    daily["gap_pct"] = daily["gap_pct"].fillna(0.0)

    return daily


def calculate_day_vwap(day: pd.DataFrame) -> pd.Series:
    day = day.copy()

    typical_price = (
        pd.to_numeric(day["high"], errors="coerce")
        + pd.to_numeric(day["low"], errors="coerce")
        + pd.to_numeric(day["close"], errors="coerce")
    ) / 3.0

    volume = pd.to_numeric(day["volume"], errors="coerce").fillna(0.0)

    fallback_vwap = typical_price.expanding(min_periods=1).mean()

    if volume.sum() <= 0:
        return (
            pd.to_numeric(fallback_vwap, errors="coerce")
            .ffill()
            .bfill()
            .astype(float)
        )

    cumulative_dollar_volume = (typical_price * volume).cumsum()
    cumulative_volume = volume.cumsum()

    vwap = cumulative_dollar_volume / cumulative_volume.where(cumulative_volume > 0)

    vwap = pd.to_numeric(vwap, errors="coerce")
    vwap = vwap.fillna(fallback_vwap)
    vwap = vwap.ffill().bfill()

    return vwap.astype(float)


def get_opening_range(day: pd.DataFrame) -> dict | None:
    opening = day[
        (day["time"] >= OPENING_RANGE_START)
        & (day["time"] <= OPENING_RANGE_END)
    ].copy()

    if opening.empty:
        opening = day.head(1).copy()

    if opening.empty:
        return None

    opening_high = float(opening["high"].max())
    opening_low = float(opening["low"].min())
    opening_open = float(opening.iloc[0]["open"])

    if opening_open <= 0:
        return None

    opening_range_pct = (opening_high - opening_low) / opening_open

    return {
        "opening_high": opening_high,
        "opening_low": opening_low,
        "opening_open": opening_open,
        "opening_range_pct": opening_range_pct,
    }


def safe_execute_long_trade(
    strategy_name: str,
    ticker: str,
    trade_date: str,
    setup_name: str,
    entry_time,
    entry_price: float,
    stop_price: float,
    target_price: float,
    bars: pd.DataFrame,
    extra_fields: dict | None = None,
) -> dict | None:
    if extra_fields is None:
        extra_fields = {}

    if entry_price <= 0 or stop_price <= 0 or target_price <= 0:
        return None

    if stop_price >= entry_price:
        return None

    if target_price <= entry_price:
        return None

    risk_pct = (entry_price - stop_price) / entry_price

    if risk_pct <= 0:
        return None

    if risk_pct > MAX_ACCEPTED_TRADE_RISK_PCT:
        return None

    result = execute_long_orb_trade(
        entry_time=entry_time,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        bars=bars,
        timestamp_col="timestamp",
        close_if_no_hit=True,
        same_bar_priority=SAME_BAR_PRIORITY,
        eod_exit_time=EOD_EXIT_TIME,
    )

    if result.exit_time is None or result.exit_price is None:
        return None

    gross_return = float(result.pnl_pct)
    net_return = gross_return - ORB_COST_PER_TRADE

    exit_reason = EXIT_REASON_MAP.get(result.exit_reason, str(result.exit_reason))

    row = {
        "strategy_name": strategy_name,
        "strategy_version": LAB_STRATEGY_VERSION,
        "setup_name": setup_name,
        "date": trade_date,
        "ticker": ticker,
        "side": "LONG",
        "entry_time": entry_time,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "exit_time": result.exit_time,
        "exit_price": result.exit_price,
        "exit_reason": exit_reason,
        "gross_return": gross_return,
        "net_return": net_return,
        "trade_duration_minutes": result.trade_duration_minutes,
        "risk_per_share": result.risk_per_share,
        "risk_pct": risk_pct,
        "target_return_pct": (target_price - entry_price) / entry_price,
        "r_multiple_achieved": result.r_multiple_achieved,
        "cost_per_trade": ORB_COST_PER_TRADE,
    }

    row.update(extra_fields)

    row["trade_key"] = (
        row["date"]
        + "_"
        + row["ticker"]
        + "_"
        + row["strategy_name"]
        + "_"
        + pd.to_datetime(row["entry_time"]).strftime("%H:%M:%S")
    )

    return row


def build_orb_breakout_candidates(
    raw_prices: pd.DataFrame,
    allowed_tickers: list[str] | None = None,
) -> pd.DataFrame:
    if allowed_tickers is None:
        prepared = prepare_prices(raw_prices, allowed_tickers=None)
        allowed_tickers = sorted(prepared["ticker"].dropna().unique())

    trades = build_research_trades(
        prices=raw_prices,
        allowed_tickers=allowed_tickers,
        breakout_start=ORB_BREAKOUT_START,
        breakout_end=ORB_BREAKOUT_END,
        r_multiple=ORB_R_MULTIPLE,
        max_opening_range=ORB_MAX_OPENING_RANGE,
        min_gap=ORB_MIN_GAP,
        cost_per_trade=ORB_COST_PER_TRADE,
        same_bar_priority=SAME_BAR_PRIORITY,
        eod_exit_time=EOD_EXIT_TIME,
        verbose=True,
    )

    if trades.empty:
        return trades

    trades = trades.copy()
    trades["strategy_name"] = ORB_BREAKOUT_NAME
    trades["strategy_version"] = LAB_STRATEGY_VERSION
    trades["setup_name"] = "opening_range_breakout"
    trades["side"] = "LONG"

    trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")

    if "date" not in trades.columns:
        trades["date"] = trades["entry_time"].dt.strftime("%Y-%m-%d")
    else:
        trades["date"] = pd.to_datetime(trades["date"], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )

    if "gross_return" not in trades.columns:
        trades["gross_return"] = trades["net_return"] + ORB_COST_PER_TRADE

    trades["exit_reason"] = trades["exit_reason"].astype(str).str.lower()

    trades["trade_key"] = (
        trades["date"].astype(str)
        + "_"
        + trades["ticker"].astype(str)
        + "_"
        + trades["strategy_name"].astype(str)
        + "_"
        + trades["entry_time"].dt.strftime("%H:%M:%S")
    )

    return trades


def build_orb_pullback_candidates(prices: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for (ticker, trade_date), day in prices.groupby(["ticker", "date"]):
        day = day.sort_values("timestamp").copy()

        opening = get_opening_range(day)

        if opening is None:
            continue

        if opening["opening_range_pct"] > ORB_MAX_OPENING_RANGE:
            continue

        breakout_window = day[
            (day["time"] >= ORB_BREAKOUT_START)
            & (day["time"] <= ORB_BREAKOUT_END)
        ].copy()

        breakout_bars = breakout_window[
            breakout_window["high"] >= opening["opening_high"]
        ].copy()

        if breakout_bars.empty:
            continue

        breakout_bar = breakout_bars.iloc[0]
        breakout_time = breakout_bar["timestamp"]

        retest_window = day[
            (day["timestamp"] > breakout_time)
            & (day["time"] <= PULLBACK_RETEST_END)
        ].copy()

        if retest_window.empty:
            continue

        retest_bars = retest_window[
            (retest_window["low"] <= opening["opening_high"])
            & (retest_window["close"] >= opening["opening_high"])
        ].copy()

        if retest_bars.empty:
            continue

        entry_bar = retest_bars.iloc[0]

        entry_time = entry_bar["timestamp"]
        entry_price = float(entry_bar["close"])
        stop_price = float(min(opening["opening_low"], entry_bar["low"]))
        target_price = entry_price + ORB_R_MULTIPLE * (entry_price - stop_price)

        row = safe_execute_long_trade(
            strategy_name=ORB_PULLBACK_NAME,
            ticker=ticker,
            trade_date=trade_date,
            setup_name="orb_breakout_pullback_retest",
            entry_time=entry_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            bars=day,
            extra_fields={
                "opening_high": opening["opening_high"],
                "opening_low": opening["opening_low"],
                "opening_range_pct": opening["opening_range_pct"],
                "breakout_time": breakout_time,
                "breakout_price": float(breakout_bar["high"]),
            },
        )

        if row is not None:
            rows.append(row)

    return pd.DataFrame(rows)


def build_vwap_reclaim_candidates(prices: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for (ticker, trade_date), day in prices.groupby(["ticker", "date"]):
        day = day.sort_values("timestamp").copy()
        day["vwap"] = calculate_day_vwap(day)

        signal_window = day[
            (day["time"] >= VWAP_RECLAIM_START)
            & (day["time"] <= VWAP_RECLAIM_END)
        ].copy()

        if len(signal_window) < 2:
            continue

        signal_window["previous_close"] = signal_window["close"].shift(1)
        signal_window["previous_vwap"] = signal_window["vwap"].shift(1)

        reclaim_bars = signal_window[
            (signal_window["previous_close"] <= signal_window["previous_vwap"])
            & (signal_window["close"] > signal_window["vwap"])
            & (signal_window["close"] > signal_window["open"])
        ].copy()

        if reclaim_bars.empty:
            continue

        entry_bar = reclaim_bars.iloc[0]
        entry_time = entry_bar["timestamp"]
        entry_price = float(entry_bar["close"])

        prior_bars = day[day["timestamp"] <= entry_time].tail(4)
        stop_price = float(min(prior_bars["low"].min(), entry_bar["vwap"]))

        target_price = entry_price + ORB_R_MULTIPLE * (entry_price - stop_price)

        row = safe_execute_long_trade(
            strategy_name=VWAP_RECLAIM_NAME,
            ticker=ticker,
            trade_date=trade_date,
            setup_name="vwap_reclaim_long",
            entry_time=entry_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            bars=day,
            extra_fields={
                "entry_vwap": float(entry_bar["vwap"]),
                "opening_range_pct": get_opening_range(day)["opening_range_pct"]
                if get_opening_range(day) is not None
                else 0.0,
            },
        )

        if row is not None:
            rows.append(row)

    return pd.DataFrame(rows)


def build_gap_down_recovery_candidates(
    prices: pd.DataFrame,
    daily_refs: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    ref_lookup = {
        (row["ticker"], row["date"]): row
        for _, row in daily_refs.dropna(subset=["previous_close"]).iterrows()
    }

    for (ticker, trade_date), day in prices.groupby(["ticker", "date"]):
        key = (ticker, trade_date)

        if key not in ref_lookup:
            continue

        ref = ref_lookup[key]
        previous_close = float(ref["previous_close"])
        day_open = float(ref["day_open"])
        gap_pct = float(ref["gap_pct"])

        if gap_pct > MIN_GAP_DOWN_FOR_RECOVERY:
            continue

        day = day.sort_values("timestamp").copy()
        day["vwap"] = calculate_day_vwap(day)

        stabilization_window = day[
            (day["time"] >= OPENING_RANGE_START)
            & (day["time"] <= GAP_RECOVERY_START)
        ].copy()

        if stabilization_window.empty:
            continue

        stabilization_low = float(stabilization_window["low"].min())

        signal_window = day[
            (day["time"] >= GAP_RECOVERY_START)
            & (day["time"] <= GAP_RECOVERY_END)
        ].copy()

        if signal_window.empty:
            continue

        recovery_bars = signal_window[
            (signal_window["close"] > day_open)
            & (signal_window["close"] > signal_window["vwap"])
        ].copy()

        if recovery_bars.empty:
            continue

        entry_bar = recovery_bars.iloc[0]
        entry_time = entry_bar["timestamp"]
        entry_price = float(entry_bar["close"])
        stop_price = stabilization_low

        # Gap-fill target: previous close.
        target_price = previous_close

        row = safe_execute_long_trade(
            strategy_name=GAP_DOWN_RECOVERY_NAME,
            ticker=ticker,
            trade_date=trade_date,
            setup_name="gap_down_recovery_gap_fill",
            entry_time=entry_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            bars=day,
            extra_fields={
                "previous_close": previous_close,
                "day_open": day_open,
                "gap_pct": gap_pct,
                "entry_vwap": float(entry_bar["vwap"]),
                "opening_range_pct": get_opening_range(day)["opening_range_pct"]
                if get_opening_range(day) is not None
                else 0.0,
            },
        )

        if row is not None:
            rows.append(row)

    return pd.DataFrame(rows)


def build_previous_day_high_breakout_candidates(
    prices: pd.DataFrame,
    daily_refs: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    ref_lookup = {
        (row["ticker"], row["date"]): row
        for _, row in daily_refs.dropna(subset=["previous_high"]).iterrows()
    }

    for (ticker, trade_date), day in prices.groupby(["ticker", "date"]):
        key = (ticker, trade_date)

        if key not in ref_lookup:
            continue

        ref = ref_lookup[key]
        previous_high = float(ref["previous_high"])

        day = day.sort_values("timestamp").copy()

        signal_window = day[
            (day["time"] >= PREV_HIGH_BREAKOUT_START)
            & (day["time"] <= PREV_HIGH_BREAKOUT_END)
        ].copy()

        breakout_bars = signal_window[
            (signal_window["high"] >= previous_high)
            & (signal_window["close"] > previous_high)
        ].copy()

        if breakout_bars.empty:
            continue

        entry_bar = breakout_bars.iloc[0]
        entry_time = entry_bar["timestamp"]
        entry_price = float(entry_bar["close"])

        prior_bars = day[day["timestamp"] <= entry_time]
        stop_price = float(prior_bars["low"].min())
        target_price = entry_price + ORB_R_MULTIPLE * (entry_price - stop_price)

        row = safe_execute_long_trade(
            strategy_name=PREVIOUS_DAY_HIGH_BREAKOUT_NAME,
            ticker=ticker,
            trade_date=trade_date,
            setup_name="previous_day_high_breakout",
            entry_time=entry_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            bars=day,
            extra_fields={
                "previous_high": previous_high,
                "opening_range_pct": get_opening_range(day)["opening_range_pct"]
                if get_opening_range(day) is not None
                else 0.0,
            },
        )

        if row is not None:
            rows.append(row)

    return pd.DataFrame(rows)


def normalise_candidate_columns(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates

    df = candidates.copy()

    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")

    if "date" not in df.columns:
        df["date"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    else:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )

    required_defaults = {
        "side": "LONG",
        "setup_name": "",
        "strategy_version": LAB_STRATEGY_VERSION,
        "gross_return": 0.0,
        "net_return": 0.0,
        "risk_pct": 0.0,
        "target_return_pct": 0.0,
        "opening_range_pct": 0.0,
        "gap_pct": 0.0,
        "cost_per_trade": ORB_COST_PER_TRADE,
    }

    for col, default in required_defaults.items():
        if col not in df.columns:
            df[col] = default

    numeric_columns = [
        "entry_price",
        "exit_price",
        "stop_price",
        "target_price",
        "gross_return",
        "net_return",
        "risk_pct",
        "target_return_pct",
        "opening_range_pct",
        "gap_pct",
        "trade_duration_minutes",
        "risk_per_share",
        "r_multiple_achieved",
        "cost_per_trade",
    ]

    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if {"entry_price", "stop_price"}.issubset(df.columns):
        calculated_risk_pct = (
            (df["entry_price"] - df["stop_price"]) / df["entry_price"]
        )

        df["risk_pct"] = calculated_risk_pct.where(
            calculated_risk_pct > 0,
            df["risk_pct"],
        )

    if {"entry_price", "target_price"}.issubset(df.columns):
        calculated_target_return_pct = (
            (df["target_price"] - df["entry_price"]) / df["entry_price"]
        )

        df["target_return_pct"] = calculated_target_return_pct.where(
            calculated_target_return_pct > 0,
            df["target_return_pct"],
        )

    df["risk_pct"] = pd.to_numeric(df["risk_pct"], errors="coerce").fillna(0.0)
    df["target_return_pct"] = pd.to_numeric(
        df["target_return_pct"],
        errors="coerce",
    ).fillna(0.0)

    df["exit_reason"] = df["exit_reason"].astype(str).str.lower()

    df["trade_key"] = (
        df["date"].astype(str)
        + "_"
        + df["ticker"].astype(str)
        + "_"
        + df["strategy_name"].astype(str)
        + "_"
        + df["entry_time"].dt.strftime("%H:%M:%S")
    )

    df = df.sort_values(["strategy_name", "date", "entry_time", "ticker"])
    df = df.reset_index(drop=True)
    df["candidate_number"] = df.groupby("strategy_name").cumcount() + 1

    return df


def can_accept_interval(
    accepted_intervals: list[dict],
    candidate_entry,
    candidate_exit,
    max_positions: int,
) -> bool:
    candidate_entry = pd.to_datetime(candidate_entry)
    candidate_exit = pd.to_datetime(candidate_exit)

    events = []

    for interval in accepted_intervals:
        events.append((pd.to_datetime(interval["entry_time"]), 1))
        events.append((pd.to_datetime(interval["exit_time"]), -1))

    events.append((candidate_entry, 1))
    events.append((candidate_exit, -1))

    # At identical timestamps, close before opening.
    events = sorted(events, key=lambda x: (x[0], x[1]))

    active = 0
    max_active = 0

    for _, change in events:
        active += change
        max_active = max(max_active, active)

    return max_active <= max_positions


def select_trades_by_strategy(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates

    selected_rows = []

    for (strategy_name, trade_date), day in candidates.groupby(
        ["strategy_name", "date"]
    ):
        day = day.copy()
        day = day.sort_values(["entry_time", "ticker"])

        accepted_intervals = []
        selection_rank = 0

        for _, trade in day.iterrows():
            can_accept = can_accept_interval(
                accepted_intervals=accepted_intervals,
                candidate_entry=trade["entry_time"],
                candidate_exit=trade["exit_time"],
                max_positions=ORB_MAX_OPEN_POSITIONS,
            )

            if not can_accept:
                continue

            selection_rank += 1

            row = trade.to_dict()
            row["selection_rank"] = selection_rank
            row["max_open_positions"] = ORB_MAX_OPEN_POSITIONS
            row["selected_by_strategy_lab"] = True

            selected_rows.append(row)

            accepted_intervals.append(
                {
                    "entry_time": trade["entry_time"],
                    "exit_time": trade["exit_time"],
                }
            )

    selected = pd.DataFrame(selected_rows)

    if selected.empty:
        return selected

    selected = selected.sort_values(["strategy_name", "entry_time", "ticker"])
    selected = selected.reset_index(drop=True)
    selected["selected_trade_number"] = selected.groupby("strategy_name").cumcount() + 1

    return selected


def calculate_profit_factor(pnl: pd.Series) -> float:
    pnl = pd.to_numeric(pnl, errors="coerce").dropna()

    gains = pnl[pnl > 0].sum()
    losses = pnl[pnl < 0].sum()

    if losses == 0:
        if gains > 0:
            return 999.0
        return 0.0

    return float(gains / abs(losses))


def build_equity_curve(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for strategy_name, strategy_trades in trades.groupby("strategy_name"):
        strategy_trades = strategy_trades.sort_values("entry_time").reset_index(
            drop=True
        )

        equity = ORB_INITIAL_CAPITAL
        peak_equity = ORB_INITIAL_CAPITAL

        rows.append(
            {
                "strategy_name": strategy_name,
                "trade_number": 0,
                "date": "",
                "ticker": "START",
                "entry_time": "",
                "exit_time": "",
                "net_return": 0.0,
                "account_return": 0.0,
                "pnl_sek": 0.0,
                "equity": equity,
                "cumulative_return": 0.0,
                "drawdown_pct": 0.0,
                "position_size_pct": ORB_POSITION_SIZE,
                "is_baseline": True,
            }
        )

        for idx, trade in strategy_trades.iterrows():
            account_return = float(trade["net_return"]) * ORB_POSITION_SIZE
            pnl_sek = ORB_INITIAL_CAPITAL * account_return

            equity += pnl_sek
            peak_equity = max(peak_equity, equity)

            cumulative_return = (equity / ORB_INITIAL_CAPITAL) - 1.0
            drawdown_pct = (equity / peak_equity) - 1.0

            rows.append(
                {
                    "strategy_name": strategy_name,
                    "trade_number": idx + 1,
                    "date": trade["date"],
                    "ticker": trade["ticker"],
                    "entry_time": trade["entry_time"],
                    "exit_time": trade["exit_time"],
                    "net_return": trade["net_return"],
                    "account_return": account_return,
                    "pnl_sek": pnl_sek,
                    "equity": equity,
                    "cumulative_return": cumulative_return,
                    "drawdown_pct": drawdown_pct,
                    "position_size_pct": ORB_POSITION_SIZE,
                    "is_baseline": False,
                }
            )

    return pd.DataFrame(rows)


def build_summary(trades: pd.DataFrame, equity_curve: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for strategy_name, strategy_trades in trades.groupby("strategy_name"):
        strategy_trades = strategy_trades.copy()

        strategy_equity = equity_curve[
            equity_curve["strategy_name"].eq(strategy_name)
        ].copy()

        trade_count = len(strategy_trades)
        active_days = strategy_trades["date"].nunique()

        pnl_sek = strategy_trades["net_return"] * ORB_POSITION_SIZE * ORB_INITIAL_CAPITAL

        final_equity = (
            float(strategy_equity["equity"].iloc[-1])
            if not strategy_equity.empty
            else ORB_INITIAL_CAPITAL
        )

        total_return = (final_equity / ORB_INITIAL_CAPITAL) - 1.0

        exit_reasons = strategy_trades["exit_reason"].astype(str).str.lower()

        rows.append(
            {
                "strategy_name": strategy_name,
                "strategy_version": LAB_STRATEGY_VERSION,
                "selected_trades": trade_count,
                "active_days": active_days,
                "first_date": strategy_trades["date"].min(),
                "last_date": strategy_trades["date"].max(),
                "final_equity": final_equity,
                "total_return": total_return,
                "total_pnl_sek": float(pnl_sek.sum()),
                "win_rate": float((strategy_trades["net_return"] > 0).mean())
                if trade_count > 0
                else 0.0,
                "avg_trade": float(strategy_trades["net_return"].mean())
                if trade_count > 0
                else 0.0,
                "median_trade": float(strategy_trades["net_return"].median())
                if trade_count > 0
                else 0.0,
                "best_trade": float(strategy_trades["net_return"].max())
                if trade_count > 0
                else 0.0,
                "worst_trade": float(strategy_trades["net_return"].min())
                if trade_count > 0
                else 0.0,
                "profit_factor": calculate_profit_factor(pnl_sek),
                "max_drawdown": float(strategy_equity["drawdown_pct"].min())
                if not strategy_equity.empty
                else 0.0,
                "avg_risk_pct": float(strategy_trades["risk_pct"].mean())
                if trade_count > 0
                else 0.0,
                "max_risk_pct": float(strategy_trades["risk_pct"].max())
                if trade_count > 0
                else 0.0,
                "target_count": int((exit_reasons == "target").sum()),
                "stop_count": int((exit_reasons == "stop").sum()),
                "close_count": int((exit_reasons == "close").sum()),
                "other_exit_count": int(
                    (~exit_reasons.isin(["target", "stop", "close"])).sum()
                ),
            }
        )

    summary = pd.DataFrame(rows)

    if summary.empty:
        return summary

    summary = summary.sort_values(
        ["total_return", "profit_factor"],
        ascending=[False, False],
    ).reset_index(drop=True)

    summary["strategy_rank"] = summary.index + 1

    return summary


def build_daily_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    rows = []

    for (strategy_name, trade_date), day in trades.groupby(["strategy_name", "date"]):
        pnl_sek = day["net_return"] * ORB_POSITION_SIZE * ORB_INITIAL_CAPITAL

        rows.append(
            {
                "strategy_name": strategy_name,
                "date": trade_date,
                "trades": int(len(day)),
                "winners": int((day["net_return"] > 0).sum()),
                "losers": int((day["net_return"] < 0).sum()),
                "daily_net_return_sum": float(day["net_return"].sum()),
                "daily_account_return": float(
                    (day["net_return"] * ORB_POSITION_SIZE).sum()
                ),
                "daily_pnl_sek": float(pnl_sek.sum()),
                "avg_trade": float(day["net_return"].mean()),
                "best_trade": float(day["net_return"].max()),
                "worst_trade": float(day["net_return"].min()),
                "tickers": ", ".join(sorted(day["ticker"].unique())),
            }
        )

    daily = pd.DataFrame(rows)

    daily = daily.sort_values(["strategy_name", "date"]).reset_index(drop=True)

    daily["cumulative_account_return"] = daily.groupby("strategy_name")[
        "daily_account_return"
    ].cumsum()

    return daily


def build_overlap(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    rows = []

    strategy_names = sorted(trades["strategy_name"].unique())

    for strategy_a, strategy_b in combinations(strategy_names, 2):
        trades_a = trades[trades["strategy_name"].eq(strategy_a)].copy()
        trades_b = trades[trades["strategy_name"].eq(strategy_b)].copy()

        date_set_a = set(trades_a["date"])
        date_set_b = set(trades_b["date"])

        ticker_date_set_a = set(zip(trades_a["date"], trades_a["ticker"]))
        ticker_date_set_b = set(zip(trades_b["date"], trades_b["ticker"]))

        rows.append(
            {
                "strategy_a": strategy_a,
                "strategy_b": strategy_b,
                "strategy_a_trades": len(trades_a),
                "strategy_b_trades": len(trades_b),
                "same_active_dates": len(date_set_a.intersection(date_set_b)),
                "strategy_a_active_dates": len(date_set_a),
                "strategy_b_active_dates": len(date_set_b),
                "same_ticker_dates": len(
                    ticker_date_set_a.intersection(ticker_date_set_b)
                ),
                "strategy_a_ticker_dates": len(ticker_date_set_a),
                "strategy_b_ticker_dates": len(ticker_date_set_b),
            }
        )

    return pd.DataFrame(rows)


def build_regime_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()

    regime_dimensions = [
        "market_gap_regime",
        "market_trend_regime",
        "market_breadth_regime",
        "market_volatility_regime",
        "composite_regime",
    ]

    rows = []

    for dimension in regime_dimensions:
        if dimension not in trades.columns:
            continue

        for (strategy_name, regime_value), group in trades.groupby(
            ["strategy_name", dimension]
        ):
            pnl_sek = group["net_return"] * ORB_POSITION_SIZE * ORB_INITIAL_CAPITAL

            rows.append(
                {
                    "strategy_name": strategy_name,
                    "regime_dimension": dimension,
                    "regime_value": regime_value,
                    "trades": int(len(group)),
                    "active_days": int(group["date"].nunique()),
                    "total_account_return": float(
                        (group["net_return"] * ORB_POSITION_SIZE).sum()
                    ),
                    "total_pnl_sek": float(pnl_sek.sum()),
                    "win_rate": float((group["net_return"] > 0).mean()),
                    "avg_trade": float(group["net_return"].mean()),
                    "profit_factor": calculate_profit_factor(pnl_sek),
                    "best_trade": float(group["net_return"].max()),
                    "worst_trade": float(group["net_return"].min()),
                }
            )

    regime_summary = pd.DataFrame(rows)

    if regime_summary.empty:
        return regime_summary

    regime_summary = regime_summary.sort_values(
        ["strategy_name", "regime_dimension", "total_account_return"],
        ascending=[True, True, False],
    ).reset_index(drop=True)

    return regime_summary


def main() -> None:
    print("\n=== INTRADAY STRATEGY LAB ===")
    print("Research-only. This does not modify ORB paper/live trading.")
    print("Long-only strategies only. No shorts.")
    print(f"Strategy version: {LAB_STRATEGY_VERSION}")
    print(f"Tickers: {', '.join(ORB_ALLOWED_TICKERS)}")
    print(f"Initial capital: {ORB_INITIAL_CAPITAL:.2f} SEK")
    print(f"Position size: {ORB_POSITION_SIZE:.2%}")
    print(f"Max open positions per strategy: {ORB_MAX_OPEN_POSITIONS}")
    print(f"Trade cost: {ORB_COST_PER_TRADE:.4%}")
    print(f"Same-bar priority: {SAME_BAR_PRIORITY}")
    print(f"EOD exit time: {EOD_EXIT_TIME}")

    raw_prices = load_normalised_intraday_prices()
    raw_prices = filter_to_completed_research_sessions(
    raw_prices,
    verbose=True,
)
    prices = prepare_prices(raw_prices, allowed_tickers=ORB_ALLOWED_TICKERS)
    daily_refs = calculate_daily_references(prices)

    market_regime = calculate_daily_market_regime(raw_prices)

    strategy_candidate_frames = []

    print("\n--- Building ORB breakout baseline candidates ---")
    orb_breakout = build_orb_breakout_candidates(
        raw_prices,
        allowed_tickers=ORB_ALLOWED_TICKERS,
    )
    print(f"{ORB_BREAKOUT_NAME}: {len(orb_breakout)} candidates")
    strategy_candidate_frames.append(orb_breakout)

    print("\n--- Building ORB pullback/retest candidates ---")
    orb_pullback = build_orb_pullback_candidates(prices)
    print(f"{ORB_PULLBACK_NAME}: {len(orb_pullback)} candidates")
    strategy_candidate_frames.append(orb_pullback)

    print("\n--- Building VWAP reclaim candidates ---")
    vwap_reclaim = build_vwap_reclaim_candidates(prices)
    print(f"{VWAP_RECLAIM_NAME}: {len(vwap_reclaim)} candidates")
    strategy_candidate_frames.append(vwap_reclaim)

    print("\n--- Building gap-down recovery candidates ---")
    gap_recovery = build_gap_down_recovery_candidates(prices, daily_refs)
    print(f"{GAP_DOWN_RECOVERY_NAME}: {len(gap_recovery)} candidates")
    strategy_candidate_frames.append(gap_recovery)

    print("\n--- Building previous-day high breakout candidates ---")
    prev_high_breakout = build_previous_day_high_breakout_candidates(
        prices,
        daily_refs,
    )
    print(f"{PREVIOUS_DAY_HIGH_BREAKOUT_NAME}: {len(prev_high_breakout)} candidates")
    strategy_candidate_frames.append(prev_high_breakout)

    non_empty_frames = [
        frame for frame in strategy_candidate_frames if frame is not None and not frame.empty
    ]

    if not non_empty_frames:
        print("No strategy candidates created.")
        return

    candidates = pd.concat(non_empty_frames, ignore_index=True)
    candidates = normalise_candidate_columns(candidates)
    candidates = attach_market_regime(candidates, market_regime, date_col="date")

    selected_trades = select_trades_by_strategy(candidates)
    selected_trades = attach_market_regime(
        selected_trades,
        market_regime,
        date_col="date",
    )

    equity_curve = build_equity_curve(selected_trades)
    summary = build_summary(selected_trades, equity_curve)
    daily_summary = build_daily_summary(selected_trades)
    daily_summary = attach_market_regime(
        daily_summary,
        market_regime,
        date_col="date",
    )

    overlap = build_overlap(selected_trades)
    regime_summary = build_regime_summary(selected_trades)

    export_csv_for_power_bi(summary, OUTPUT_SUMMARY_FILE)
    export_csv_for_power_bi(selected_trades, OUTPUT_TRADES_FILE)
    export_csv_for_power_bi(equity_curve, OUTPUT_EQUITY_FILE)
    export_csv_for_power_bi(daily_summary, OUTPUT_DAILY_FILE)
    export_csv_for_power_bi(overlap, OUTPUT_OVERLAP_FILE)
    export_csv_for_power_bi(regime_summary, OUTPUT_REGIME_SUMMARY_FILE)
    export_csv_for_power_bi(candidates, OUTPUT_CANDIDATES_FILE)
    export_csv_for_power_bi(market_regime, OUTPUT_MARKET_REGIME_FILE)

    print("\n=== STRATEGY LAB SUMMARY ===")

    summary_columns = [
        "strategy_rank",
        "strategy_name",
        "selected_trades",
        "active_days",
        "total_return",
        "win_rate",
        "avg_trade",
        "profit_factor",
        "max_drawdown",
        "avg_risk_pct",
        "max_risk_pct",
        "target_count",
        "stop_count",
        "close_count",
    ]

    print(summary[summary_columns].to_string(index=False))

    print("\n=== STRATEGY LAB REGIME SUMMARY ===")

    if regime_summary.empty:
        print("No regime summary produced.")
    else:
        display_regime = regime_summary[
            regime_summary["regime_dimension"].eq("composite_regime")
        ].copy()

        regime_columns = [
            "strategy_name",
            "regime_value",
            "trades",
            "active_days",
            "total_account_return",
            "win_rate",
            "avg_trade",
            "profit_factor",
        ]

        print(display_regime[regime_columns].to_string(index=False))

    print("\n=== STRATEGY LAB OVERLAP ===")

    if overlap.empty:
        print("No overlap summary produced.")
    else:
        print(overlap.to_string(index=False))

    print(f"\nSaved summary        -> {OUTPUT_SUMMARY_FILE}")
    print(f"Saved trades         -> {OUTPUT_TRADES_FILE}")
    print(f"Saved equity         -> {OUTPUT_EQUITY_FILE}")
    print(f"Saved daily summary  -> {OUTPUT_DAILY_FILE}")
    print(f"Saved overlap        -> {OUTPUT_OVERLAP_FILE}")
    print(f"Saved regime summary -> {OUTPUT_REGIME_SUMMARY_FILE}")
    print(f"Saved candidates     -> {OUTPUT_CANDIDATES_FILE}")
    print(f"Saved market regime  -> {OUTPUT_MARKET_REGIME_FILE}")


if __name__ == "__main__":
    main()