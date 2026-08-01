from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, time
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.research_config import (
    ORB_ALLOWED_TICKERS,
    ORB_COST_PER_TRADE,
    ORB_INITIAL_CAPITAL,
    ORB_POSITION_SIZE,
)
from RegimeTrading.core.execution import execute_long_orb_trade
from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, legacy_output_path


STRATEGY_ID = "REGIME_AWARE_GAP_RECOVERY_V1"
RESEARCH_STATUS = "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION"
FORWARD_MONITORING_START_DATE = "2026-07-20"

GAP_RECOVERY_RESEARCH_TICKERS = [
    "ATCO-A.ST",
    "ATCO-B.ST",
    "AZN.ST",
    "BOL.ST",
    "EVO.ST",
    "SAND.ST",
    "SWED-A.ST",
]

FROZEN_ORB_TICKERS = list(ORB_ALLOWED_TICKERS)

GAP_RECOVERY_TICKERS = sorted(
    set(GAP_RECOVERY_RESEARCH_TICKERS + FROZEN_ORB_TICKERS)
)

MIN_GAP = -0.0200
MAX_GAP = -0.0010
OPENING_RANGE_START = "09:30"
OPENING_RANGE_END = "09:35"
REGIME_CUTOFF_TIME = "09:45"
ENTRY_WINDOW_START = "09:45"
ENTRY_WINDOW_END = "13:00"
EOD_EXIT_TIME = "16:30"
SAME_BAR_PRIORITY = "STOP"
TARGET_MODE = "PREVIOUS_CLOSE_GAP_FILL"
ENTRY_WINDOW_LABEL = f"{ENTRY_WINDOW_START}-{ENTRY_WINDOW_END}"
LOCAL_TIMEZONE = ZoneInfo("Europe/Stockholm")

MIN_REGIME_SAMPLE_SIZE = 5
BROAD_STRENGTH_BREADTH = 0.67
BROAD_STRENGTH_MEDIAN_RETURN = 0.0010
STABLE_RECOVERY_BREADTH = 0.55
STABLE_RECOVERY_MEDIAN_RETURN = 0.0000
GAP_SUPPORT_POSITIVE_GAP_BREADTH = 0.55
GAP_SUPPORT_MIN_MEDIAN_GAP = 0.0000
GAP_SUPPORT_MIN_BREADTH = 0.45

FAVORABLE_REGIMES = {
    "EARLY_BROAD_STRENGTH",
    "EARLY_STABLE_RECOVERY",
    "EARLY_GAP_SUPPORT",
}

SUMMARY_FILE = legacy_output_path("regime_gap_recovery_summary.csv")
TRADES_FILE = legacy_output_path("regime_gap_recovery_trades.csv")
DAILY_FILE = legacy_output_path("regime_gap_recovery_daily.csv")
LATEST_FILE = legacy_output_path("regime_gap_recovery_latest.csv")
CANDIDATES_FILE = legacy_output_path("regime_gap_recovery_candidates.csv")

FORWARD_SUMMARY_FILE = legacy_output_path("regime_gap_recovery_forward_summary.csv")
FORWARD_TRADES_FILE = legacy_output_path("regime_gap_recovery_forward_trades.csv")
FORWARD_DAILY_FILE = legacy_output_path("regime_gap_recovery_forward_daily.csv")
FORWARD_CANDIDATES_FILE = legacy_output_path("regime_gap_recovery_forward_candidates.csv")

CANDIDATE_COLUMNS = [
    "strategy_id",
    "research_status",
    "date",
    "ticker",
    "candidate_status",
    "invalid_reason",
    "gap",
    "gap_pct",
    "previous_close",
    "open_price",
    "current_price",
    "entry_trigger",
    "entry_time",
    "entry_price",
    "stop_price",
    "target_price",
    "opening_range_pct",
    "opening_range_pct_points",
    "risk_pct",
    "risk_pct_points",
    "reward_risk",
    "early_market_regime",
    "favorable_regime",
    "would_cross_entry_anyway",
    "theoretical_entry_time",
    "distance_to_entry",
    "distance_to_target",
    "last_bar",
    "target_mode",
    "entry_window",
    "eod_exit_time",
    "is_frozen_orb_ticker",
    "is_original_gap_watchlist_ticker",
    "research_universe",
]

TRADE_COLUMNS = [
    "strategy_id",
    "research_status",
    "date",
    "ticker",
    "entry_time",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_time",
    "exit_price",
    "exit_reason",
    "pnl_pct",
    "position_size_sek",
    "pnl_sek",
    "account_return",
    "trade_duration_minutes",
    "risk_per_share",
    "r_multiple_achieved",
    "gap",
    "gap_pct",
    "opening_range_pct",
    "opening_range_pct_points",
    "risk_pct",
    "risk_pct_points",
    "reward_risk",
    "early_market_regime",
    "target_mode",
    "is_frozen_orb_ticker",
    "is_original_gap_watchlist_ticker",
    "research_universe",
]

SUMMARY_COLUMNS = [
    "strategy_id",
    "research_status",
    "total_candidates",
    "valid_candidates",
    "triggered_candidates",
    "completed_trades",
    "win_rate",
    "total_pnl_sek",
    "total_account_return",
    "profit_factor",
    "avg_r_multiple",
    "forward_monitoring_start_date",
    "forward_monitoring_end_date",
]

DAILY_COLUMNS = [
    "strategy_id",
    "research_status",
    "date",
    "total_candidates",
    "valid_candidates",
    "triggered_candidates",
    "completed_trades",
    "wins",
    "losses",
    "win_rate",
    "total_pnl_sek",
    "total_account_return",
    "profit_factor",
    "avg_r_multiple",
    "cumulative_pnl_sek",
    "cumulative_account_return",
]


def _parse_datetimes(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip()
    has_timezone_suffix = text.str.contains(
        r"(?:Z|[+-]\d{2}:?\d{2})$",
        regex=True,
        na=False,
    ).any()

    parse_kwargs = {"errors": "coerce"}
    try:
        if has_timezone_suffix:
            parsed = pd.to_datetime(text, format="mixed", utc=True, **parse_kwargs)
            return parsed.dt.tz_convert(LOCAL_TIMEZONE).dt.tz_localize(None)

        return pd.to_datetime(text, format="mixed", **parse_kwargs)
    except (TypeError, ValueError):
        if has_timezone_suffix:
            parsed = pd.to_datetime(text, utc=True, **parse_kwargs)
            return parsed.dt.tz_convert(LOCAL_TIMEZONE).dt.tz_localize(None)

        return pd.to_datetime(text, **parse_kwargs)


def _clock_mask(values: pd.Series, start: str, end: str, include_end: bool) -> pd.Series:
    clocks = values.dt.strftime("%H:%M")
    if include_end:
        return clocks.ge(start) & clocks.le(end)
    return clocks.ge(start) & clocks.lt(end)


def _safe_float(value, default=np.nan) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso_timestamp(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _research_universe(ticker: str) -> str:
    in_frozen = ticker in FROZEN_ORB_TICKERS
    in_watchlist = ticker in GAP_RECOVERY_RESEARCH_TICKERS

    if in_frozen and in_watchlist:
        return "FROZEN_ORB_AND_GAP_WATCHLIST"
    if in_frozen:
        return "FROZEN_ORB"
    return "GAP_RECOVERY_WATCHLIST"


def load_intraday_prices(db_path: Path = INTRADAY_DB) -> pd.DataFrame:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Intraday database not found: {db_path}")

    query = """
        SELECT datetime, open, high, low, close, ticker
        FROM intraday_prices
        ORDER BY ticker, datetime
    """

    with closing(sqlite3.connect(db_path)) as connection:
        prices = pd.read_sql_query(query, connection)

    if prices.empty:
        return prices

    prices["datetime"] = _parse_datetimes(prices["datetime"])
    prices["ticker"] = prices["ticker"].astype(str).str.strip()

    for column in ["open", "high", "low", "close"]:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")

    prices["open"] = prices["open"].where(prices["open"].notna(), prices["close"])
    prices = prices.dropna(subset=["datetime", "ticker", "high", "low", "close"])
    prices = prices.sort_values(["ticker", "datetime"]).reset_index(drop=True)
    prices["date"] = prices["datetime"].dt.date

    return prices


def build_daily_reference(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(
            columns=["ticker", "date", "open_price", "daily_close", "previous_close"]
        )

    daily = (
        prices.groupby(["ticker", "date"], as_index=False)
        .agg(
            open_price=("open", "first"),
            fallback_open=("close", "first"),
            daily_close=("close", "last"),
        )
        .sort_values(["ticker", "date"])
        .reset_index(drop=True)
    )

    daily["open_price"] = daily["open_price"].where(
        daily["open_price"].notna(),
        daily["fallback_open"],
    )
    daily["previous_close"] = daily.groupby("ticker")["daily_close"].shift(1)

    return daily.drop(columns=["fallback_open"])


def classify_early_regime(
    sample_size: int,
    breadth_above_open: float,
    median_return_from_open: float,
    positive_gap_breadth: float,
    median_gap: float,
) -> str:
    if sample_size < MIN_REGIME_SAMPLE_SIZE:
        return "INSUFFICIENT_DATA"

    if (
        breadth_above_open >= BROAD_STRENGTH_BREADTH
        and median_return_from_open >= BROAD_STRENGTH_MEDIAN_RETURN
    ):
        return "EARLY_BROAD_STRENGTH"

    if (
        breadth_above_open >= STABLE_RECOVERY_BREADTH
        and median_return_from_open >= STABLE_RECOVERY_MEDIAN_RETURN
    ):
        return "EARLY_STABLE_RECOVERY"

    if (
        positive_gap_breadth >= GAP_SUPPORT_POSITIVE_GAP_BREADTH
        and median_gap >= GAP_SUPPORT_MIN_MEDIAN_GAP
        and breadth_above_open >= GAP_SUPPORT_MIN_BREADTH
    ):
        return "EARLY_GAP_SUPPORT"

    return "EARLY_WEAK_OR_UNFAVORABLE"


def calculate_early_market_regime(
    prices: pd.DataFrame,
    daily_reference: pd.DataFrame,
) -> pd.DataFrame:
    if prices.empty or daily_reference.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "early_market_regime",
                "favorable_regime",
                "sample_size",
                "breadth_above_open",
                "median_return_from_open",
                "positive_gap_breadth",
                "median_gap",
            ]
        )

    cutoff = prices[
        prices["datetime"].dt.strftime("%H:%M").le(REGIME_CUTOFF_TIME)
    ].copy()

    if cutoff.empty:
        return pd.DataFrame()

    cutoff_last = (
        cutoff.groupby(["ticker", "date"], as_index=False)
        .agg(cutoff_price=("close", "last"))
    )

    regime_input = cutoff_last.merge(
        daily_reference[
            ["ticker", "date", "open_price", "previous_close"]
        ],
        on=["ticker", "date"],
        how="left",
    )

    regime_input = regime_input.dropna(
        subset=["cutoff_price", "open_price", "previous_close"]
    )
    regime_input = regime_input[
        (regime_input["cutoff_price"] > 0)
        & (regime_input["open_price"] > 0)
        & (regime_input["previous_close"] > 0)
    ].copy()

    if regime_input.empty:
        return pd.DataFrame()

    regime_input["return_from_open"] = (
        regime_input["cutoff_price"] / regime_input["open_price"] - 1.0
    )
    regime_input["gap"] = (
        regime_input["open_price"] / regime_input["previous_close"] - 1.0
    )
    regime_input["above_open"] = regime_input["return_from_open"] > 0
    regime_input["positive_gap"] = regime_input["gap"] >= 0

    regime = (
        regime_input.groupby("date", as_index=False)
        .agg(
            sample_size=("ticker", "nunique"),
            breadth_above_open=("above_open", "mean"),
            median_return_from_open=("return_from_open", "median"),
            positive_gap_breadth=("positive_gap", "mean"),
            median_gap=("gap", "median"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )

    regime["early_market_regime"] = regime.apply(
        lambda row: classify_early_regime(
            sample_size=int(row["sample_size"]),
            breadth_above_open=float(row["breadth_above_open"]),
            median_return_from_open=float(row["median_return_from_open"]),
            positive_gap_breadth=float(row["positive_gap_breadth"]),
            median_gap=float(row["median_gap"]),
        ),
        axis=1,
    )
    regime["favorable_regime"] = regime["early_market_regime"].isin(
        FAVORABLE_REGIMES
    )

    return regime


def _first_crossing_bar(bars: pd.DataFrame, trigger: float) -> pd.Series | None:
    if bars.empty or pd.isna(trigger):
        return None

    crossed = bars[bars["high"] >= trigger]
    if crossed.empty:
        return None

    return crossed.iloc[0]


def _current_session_state(session_date, last_bar_time: pd.Timestamp) -> tuple[bool, bool]:
    now = datetime.now(LOCAL_TIMEZONE)
    today = now.date()
    is_current_day = session_date == today

    if not is_current_day:
        return False, True

    eod_cutoff = datetime.combine(today, time.fromisoformat(EOD_EXIT_TIME), LOCAL_TIMEZONE)
    last_bar_reached_eod = last_bar_time.strftime("%H:%M") >= EOD_EXIT_TIME
    can_finalize_eod = now >= eod_cutoff and last_bar_reached_eod

    return True, can_finalize_eod


def _entry_window_complete(session_date, last_bar_time: pd.Timestamp) -> bool:
    now = datetime.now(LOCAL_TIMEZONE)
    if session_date != now.date():
        return True

    entry_end = datetime.combine(
        now.date(),
        time.fromisoformat(ENTRY_WINDOW_END),
        LOCAL_TIMEZONE,
    )
    return now >= entry_end and last_bar_time.strftime("%H:%M") >= ENTRY_WINDOW_END


def _regime_cutoff_complete(session_date, last_bar_time: pd.Timestamp) -> bool:
    now = datetime.now(LOCAL_TIMEZONE)
    if session_date != now.date():
        return True

    cutoff = datetime.combine(
        now.date(),
        time.fromisoformat(REGIME_CUTOFF_TIME),
        LOCAL_TIMEZONE,
    )
    return now >= cutoff and last_bar_time.strftime("%H:%M") >= REGIME_CUTOFF_TIME


def _opening_range_complete(session_date, last_bar_time: pd.Timestamp) -> bool:
    now = datetime.now(LOCAL_TIMEZONE)
    if session_date != now.date():
        return True

    cutoff = datetime.combine(
        now.date(),
        time.fromisoformat(OPENING_RANGE_END),
        LOCAL_TIMEZONE,
    )
    return now >= cutoff and last_bar_time.strftime("%H:%M") >= OPENING_RANGE_END


def _execute_triggered_trade(
    session_bars: pd.DataFrame,
    entry_bar: pd.Series,
    entry_price: float,
    stop_price: float,
    target_price: float,
    close_if_no_hit: bool,
):
    reported_entry_time = pd.Timestamp(entry_bar["datetime"])

    # The shared helper evaluates bars strictly after entry_time. Moving the
    # helper timestamp back by one microsecond includes the trigger bar and
    # enforces conservative STOP priority when bar ordering is unknowable.
    helper_entry_time = reported_entry_time - pd.Timedelta(microseconds=1)

    result = execute_long_orb_trade(
        entry_time=helper_entry_time,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        bars=session_bars,
        timestamp_col="datetime",
        close_if_no_hit=close_if_no_hit,
        same_bar_priority=SAME_BAR_PRIORITY,
        eod_exit_time=EOD_EXIT_TIME,
    )

    return reported_entry_time, result


def build_candidates_and_trades(
    prices: pd.DataFrame,
    daily_reference: pd.DataFrame,
    early_regime: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidate_rows: list[dict] = []
    trade_rows: list[dict] = []

    if prices.empty:
        return (
            pd.DataFrame(columns=CANDIDATE_COLUMNS),
            pd.DataFrame(columns=TRADE_COLUMNS),
        )

    regime_lookup = early_regime.set_index("date").to_dict("index") if not early_regime.empty else {}
    reference_lookup = daily_reference.set_index(["ticker", "date"]).to_dict("index")

    research_prices = prices[prices["ticker"].isin(GAP_RECOVERY_TICKERS)].copy()

    for (ticker, session_date), session_bars in research_prices.groupby(
        ["ticker", "date"],
        sort=True,
    ):
        session_bars = session_bars.sort_values("datetime").reset_index(drop=True)
        if session_bars.empty:
            continue

        last_bar_row = session_bars.iloc[-1]
        last_bar_time = pd.Timestamp(last_bar_row["datetime"])
        current_price = _safe_float(last_bar_row["close"])

        reference = reference_lookup.get((ticker, session_date), {})
        open_price = _safe_float(reference.get("open_price"))
        previous_close = _safe_float(reference.get("previous_close"))

        gap = np.nan
        if previous_close > 0 and open_price > 0:
            gap = open_price / previous_close - 1.0

        gap_pct = gap * 100.0 if pd.notna(gap) else np.nan

        opening_range_bars = session_bars[
            _clock_mask(
                session_bars["datetime"],
                OPENING_RANGE_START,
                OPENING_RANGE_END,
                include_end=False,
            )
        ].copy()

        entry_trigger = np.nan
        stop_price = np.nan
        target_price = previous_close
        opening_range_pct = np.nan
        risk_pct = np.nan
        reward_risk = np.nan

        if not opening_range_bars.empty:
            entry_trigger = _safe_float(opening_range_bars["high"].max())
            stop_price = _safe_float(opening_range_bars["low"].min())

            if open_price > 0:
                opening_range_pct = (entry_trigger - stop_price) / open_price

            if entry_trigger > 0 and stop_price < entry_trigger:
                risk_pct = (entry_trigger - stop_price) / entry_trigger
                risk_per_share = entry_trigger - stop_price
                if pd.notna(target_price) and risk_per_share > 0:
                    reward_risk = (target_price - entry_trigger) / risk_per_share

        regime_row = regime_lookup.get(session_date, {})
        early_market_regime = regime_row.get(
            "early_market_regime",
            "INSUFFICIENT_DATA",
        )
        favorable_regime = bool(
            regime_row.get("favorable_regime", False)
        )

        entry_window_bars = session_bars[
            _clock_mask(
                session_bars["datetime"],
                ENTRY_WINDOW_START,
                ENTRY_WINDOW_END,
                include_end=True,
            )
        ].copy()

        theoretical_entry_bar = _first_crossing_bar(
            entry_window_bars,
            entry_trigger,
        )
        would_cross_entry_anyway = theoretical_entry_bar is not None
        theoretical_entry_time = (
            _iso_timestamp(theoretical_entry_bar["datetime"])
            if theoretical_entry_bar is not None
            else ""
        )

        reasons: list[str] = []

        if pd.isna(previous_close) or previous_close <= 0:
            reasons.append("MISSING_PREVIOUS_CLOSE")
        if pd.isna(open_price) or open_price <= 0:
            reasons.append("MISSING_OPEN_PRICE")

        if pd.notna(gap):
            if gap >= 0:
                reasons.append("GAP_NOT_NEGATIVE")
            elif gap < MIN_GAP:
                reasons.append("GAP_TOO_LARGE")
            elif gap > MAX_GAP:
                reasons.append("GAP_TOO_SMALL")

        opening_range_ready = _opening_range_complete(session_date, last_bar_time)
        regime_ready = _regime_cutoff_complete(session_date, last_bar_time)

        if opening_range_bars.empty:
            reasons.append("MISSING_OPENING_RANGE")
        elif pd.isna(entry_trigger) or pd.isna(stop_price) or stop_price >= entry_trigger:
            reasons.append("INVALID_OPENING_RANGE")

        if (
            pd.notna(target_price)
            and pd.notna(entry_trigger)
            and target_price <= entry_trigger
        ):
            reasons.append("TARGET_NOT_ABOVE_ENTRY")

        if regime_ready and not favorable_regime:
            reasons.append("UNFAVORABLE_EARLY_MARKET_REGIME")

        actionable_reasons = list(reasons)

        waiting_status = ""
        if session_date == datetime.now(LOCAL_TIMEZONE).date():
            if not opening_range_ready:
                waiting_status = "WAITING_FOR_OPENING_RANGE"
                actionable_reasons = [
                    reason
                    for reason in actionable_reasons
                    if reason not in {"MISSING_OPENING_RANGE", "INVALID_OPENING_RANGE"}
                ]
            elif not regime_ready:
                waiting_status = "WAITING_FOR_REGIME"
                actionable_reasons = [
                    reason
                    for reason in actionable_reasons
                    if reason != "UNFAVORABLE_EARLY_MARKET_REGIME"
                ]

        valid_setup = len(actionable_reasons) == 0 and not waiting_status
        candidate_status = "INVALID"
        invalid_reason = ";".join(actionable_reasons)
        entry_time = ""
        entry_price = np.nan

        if waiting_status and len(actionable_reasons) == 0:
            candidate_status = waiting_status
            invalid_reason = ""
        elif valid_setup:
            if theoretical_entry_bar is None:
                if _entry_window_complete(session_date, last_bar_time):
                    candidate_status = "NOT_TRIGGERED"
                else:
                    candidate_status = "MONITORING"
                invalid_reason = ""
            else:
                entry_price = entry_trigger
                reported_entry_time, execution = _execute_triggered_trade(
                    session_bars=session_bars,
                    entry_bar=theoretical_entry_bar,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    close_if_no_hit=_current_session_state(
                        session_date,
                        last_bar_time,
                    )[1],
                )
                entry_time = _iso_timestamp(reported_entry_time)

                if execution.status == "CLOSED":
                    candidate_status = "TRIGGERED_CLOSED"
                else:
                    candidate_status = "TRIGGERED_OPEN"

                gross_pnl_pct = float(execution.pnl_pct)
                is_closed = execution.status == "CLOSED"
                net_pnl_pct = (
                    gross_pnl_pct - float(ORB_COST_PER_TRADE)
                    if is_closed
                    else 0.0
                )
                position_size_sek = float(ORB_INITIAL_CAPITAL) * float(ORB_POSITION_SIZE)
                pnl_sek = position_size_sek * net_pnl_pct
                account_return = pnl_sek / float(ORB_INITIAL_CAPITAL)

                exit_time_value = execution.exit_time if is_closed else ""
                exit_price_value = execution.exit_price if is_closed else np.nan
                exit_reason_value = execution.exit_reason if is_closed else ""

                duration_minutes = 0.0
                if is_closed and exit_time_value:
                    duration_minutes = (
                        pd.Timestamp(exit_time_value) - reported_entry_time
                    ).total_seconds() / 60.0

                trade_rows.append(
                    {
                        "strategy_id": STRATEGY_ID,
                        "research_status": RESEARCH_STATUS,
                        "date": session_date.isoformat(),
                        "ticker": ticker,
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "stop_price": stop_price,
                        "target_price": target_price,
                        "exit_time": exit_time_value,
                        "exit_price": exit_price_value,
                        "exit_reason": exit_reason_value,
                        "pnl_pct": net_pnl_pct,
                        "position_size_sek": position_size_sek,
                        "pnl_sek": pnl_sek,
                        "account_return": account_return,
                        "trade_duration_minutes": duration_minutes,
                        "risk_per_share": max(entry_price - stop_price, 0.0),
                        "r_multiple_achieved": (
                            float(execution.r_multiple_achieved)
                            if is_closed
                            else 0.0
                        ),
                        "gap": gap,
                        "gap_pct": gap_pct,
                        "opening_range_pct": opening_range_pct,
                        "opening_range_pct_points": (
                            opening_range_pct * 100.0
                            if pd.notna(opening_range_pct)
                            else np.nan
                        ),
                        "risk_pct": risk_pct,
                        "risk_pct_points": (
                            risk_pct * 100.0 if pd.notna(risk_pct) else np.nan
                        ),
                        "reward_risk": reward_risk,
                        "early_market_regime": early_market_regime,
                        "target_mode": TARGET_MODE,
                        "is_frozen_orb_ticker": ticker in FROZEN_ORB_TICKERS,
                        "is_original_gap_watchlist_ticker": (
                            ticker in GAP_RECOVERY_RESEARCH_TICKERS
                        ),
                        "research_universe": _research_universe(ticker),
                    }
                )

        distance_to_entry = np.nan
        distance_to_target = np.nan
        if current_price > 0 and pd.notna(entry_trigger):
            distance_to_entry = entry_trigger / current_price - 1.0
        if current_price > 0 and pd.notna(target_price):
            distance_to_target = target_price / current_price - 1.0

        candidate_rows.append(
            {
                "strategy_id": STRATEGY_ID,
                "research_status": RESEARCH_STATUS,
                "date": session_date.isoformat(),
                "ticker": ticker,
                "candidate_status": candidate_status,
                "invalid_reason": invalid_reason,
                "gap": gap,
                "gap_pct": gap_pct,
                "previous_close": previous_close,
                "open_price": open_price,
                "current_price": current_price,
                "entry_trigger": entry_trigger,
                "entry_time": entry_time,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "opening_range_pct": opening_range_pct,
                "opening_range_pct_points": (
                    opening_range_pct * 100.0
                    if pd.notna(opening_range_pct)
                    else np.nan
                ),
                "risk_pct": risk_pct,
                "risk_pct_points": (
                    risk_pct * 100.0 if pd.notna(risk_pct) else np.nan
                ),
                "reward_risk": reward_risk,
                "early_market_regime": early_market_regime,
                "favorable_regime": favorable_regime,
                "would_cross_entry_anyway": would_cross_entry_anyway,
                "theoretical_entry_time": theoretical_entry_time,
                "distance_to_entry": distance_to_entry,
                "distance_to_target": distance_to_target,
                "last_bar": _iso_timestamp(last_bar_time),
                "target_mode": TARGET_MODE,
                "entry_window": ENTRY_WINDOW_LABEL,
                "eod_exit_time": EOD_EXIT_TIME,
                "is_frozen_orb_ticker": ticker in FROZEN_ORB_TICKERS,
                "is_original_gap_watchlist_ticker": (
                    ticker in GAP_RECOVERY_RESEARCH_TICKERS
                ),
                "research_universe": _research_universe(ticker),
            }
        )

    candidates = pd.DataFrame(candidate_rows, columns=CANDIDATE_COLUMNS)
    trades = pd.DataFrame(trade_rows, columns=TRADE_COLUMNS)

    if not candidates.empty:
        candidates = candidates.sort_values(["date", "ticker"]).reset_index(drop=True)
    if not trades.empty:
        trades = trades.sort_values(["date", "entry_time", "ticker"]).reset_index(drop=True)

    return candidates, trades


def _profit_factor(pnl_values: Iterable[float]) -> float:
    pnl = pd.Series(list(pnl_values), dtype="float64").dropna()
    if pnl.empty:
        return np.nan

    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())

    if gross_loss == 0:
        return np.nan

    return float(gross_profit / gross_loss)


def build_summary(
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    negative_gap_candidates = candidates[
        pd.to_numeric(candidates.get("gap"), errors="coerce") < 0
    ].copy() if not candidates.empty else candidates.copy()

    valid_statuses = {
        "MONITORING",
        "NOT_TRIGGERED",
        "TRIGGERED_OPEN",
        "TRIGGERED_CLOSED",
    }
    triggered_statuses = {"TRIGGERED_OPEN", "TRIGGERED_CLOSED"}

    completed = trades[
        trades["exit_reason"].fillna("").astype(str).ne("")
    ].copy() if not trades.empty else trades.copy()

    completed_pnl = pd.to_numeric(completed.get("pnl_sek"), errors="coerce")
    completed_account_return = pd.to_numeric(
        completed.get("account_return"),
        errors="coerce",
    )
    completed_r = pd.to_numeric(
        completed.get("r_multiple_achieved"),
        errors="coerce",
    )

    end_date = ""
    if not candidates.empty:
        forward_dates = candidates[
            candidates["date"].astype(str) >= FORWARD_MONITORING_START_DATE
        ]["date"]
        if not forward_dates.empty:
            end_date = str(forward_dates.max())

    row = {
        "strategy_id": STRATEGY_ID,
        "research_status": RESEARCH_STATUS,
        "total_candidates": int(len(negative_gap_candidates)),
        "valid_candidates": int(
            negative_gap_candidates["candidate_status"].isin(valid_statuses).sum()
        ) if not negative_gap_candidates.empty else 0,
        "triggered_candidates": int(
            negative_gap_candidates["candidate_status"].isin(triggered_statuses).sum()
        ) if not negative_gap_candidates.empty else 0,
        "completed_trades": int(len(completed)),
        "win_rate": (
            float((completed_pnl > 0).mean()) if len(completed) else np.nan
        ),
        "total_pnl_sek": float(completed_pnl.sum()) if len(completed) else 0.0,
        "total_account_return": (
            float(completed_account_return.sum()) if len(completed) else 0.0
        ),
        "profit_factor": _profit_factor(completed_pnl),
        "avg_r_multiple": (
            float(completed_r.mean()) if len(completed) else np.nan
        ),
        "forward_monitoring_start_date": FORWARD_MONITORING_START_DATE,
        "forward_monitoring_end_date": end_date,
    }

    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def build_daily(
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    dates = sorted(candidates["date"].dropna().astype(str).unique())
    rows: list[dict] = []

    valid_statuses = {
        "MONITORING",
        "NOT_TRIGGERED",
        "TRIGGERED_OPEN",
        "TRIGGERED_CLOSED",
    }
    triggered_statuses = {"TRIGGERED_OPEN", "TRIGGERED_CLOSED"}

    for date_value in dates:
        day_candidates = candidates[candidates["date"].astype(str) == date_value]
        day_negative = day_candidates[
            pd.to_numeric(day_candidates["gap"], errors="coerce") < 0
        ]
        day_trades = trades[
            trades["date"].astype(str) == date_value
        ] if not trades.empty else trades.copy()
        day_completed = day_trades[
            day_trades["exit_reason"].fillna("").astype(str).ne("")
        ] if not day_trades.empty else day_trades.copy()

        pnl_sek = pd.to_numeric(day_completed.get("pnl_sek"), errors="coerce")
        account_return = pd.to_numeric(
            day_completed.get("account_return"),
            errors="coerce",
        )
        r_multiple = pd.to_numeric(
            day_completed.get("r_multiple_achieved"),
            errors="coerce",
        )

        rows.append(
            {
                "strategy_id": STRATEGY_ID,
                "research_status": RESEARCH_STATUS,
                "date": date_value,
                "total_candidates": int(len(day_negative)),
                "valid_candidates": int(
                    day_negative["candidate_status"].isin(valid_statuses).sum()
                ),
                "triggered_candidates": int(
                    day_negative["candidate_status"].isin(triggered_statuses).sum()
                ),
                "completed_trades": int(len(day_completed)),
                "wins": int((pnl_sek > 0).sum()),
                "losses": int((pnl_sek < 0).sum()),
                "win_rate": (
                    float((pnl_sek > 0).mean()) if len(day_completed) else np.nan
                ),
                "total_pnl_sek": float(pnl_sek.sum()) if len(day_completed) else 0.0,
                "total_account_return": (
                    float(account_return.sum()) if len(day_completed) else 0.0
                ),
                "profit_factor": _profit_factor(pnl_sek),
                "avg_r_multiple": (
                    float(r_multiple.mean()) if len(day_completed) else np.nan
                ),
            }
        )

    daily = pd.DataFrame(rows)
    daily["cumulative_pnl_sek"] = daily["total_pnl_sek"].cumsum()
    daily["cumulative_account_return"] = daily[
        "total_account_return"
    ].cumsum()

    return daily[DAILY_COLUMNS]


def export_outputs(
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    daily: pd.DataFrame,
) -> None:
    summary = build_summary(candidates, trades)

    latest = pd.DataFrame(columns=CANDIDATE_COLUMNS)
    if not candidates.empty:
        latest_date = candidates["date"].max()
        latest = candidates[candidates["date"] == latest_date].copy()

    forward_candidates = candidates[
        candidates["date"].astype(str) >= FORWARD_MONITORING_START_DATE
    ].copy() if not candidates.empty else candidates.copy()
    forward_trades = trades[
        trades["date"].astype(str) >= FORWARD_MONITORING_START_DATE
    ].copy() if not trades.empty else trades.copy()
    forward_daily = daily[
        daily["date"].astype(str) >= FORWARD_MONITORING_START_DATE
    ].copy() if not daily.empty else daily.copy()
    forward_summary = build_summary(forward_candidates, forward_trades)

    output_map = {
        SUMMARY_FILE: summary,
        TRADES_FILE: trades,
        DAILY_FILE: daily,
        LATEST_FILE: latest,
        CANDIDATES_FILE: candidates,
        FORWARD_SUMMARY_FILE: forward_summary,
        FORWARD_TRADES_FILE: forward_trades,
        FORWARD_DAILY_FILE: forward_daily,
        FORWARD_CANDIDATES_FILE: forward_candidates,
    }

    for path, dataframe in output_map.items():
        export_csv_for_power_bi(dataframe, path)
        print(f"Saved {path.name}: {len(dataframe)} rows")


def main() -> None:
    print("\n=== REGIME-AWARE GAP RECOVERY RESEARCH ===")
    print(f"Strategy: {STRATEGY_ID}")
    print(f"Status  : {RESEARCH_STATUS}")
    print("Frozen ORB metadata is read from an isolated research snapshot; production is not imported or modified.")

    prices = load_intraday_prices()
    if prices.empty:
        print("No intraday price rows found.")
        export_outputs(
            candidates=pd.DataFrame(columns=CANDIDATE_COLUMNS),
            trades=pd.DataFrame(columns=TRADE_COLUMNS),
            daily=pd.DataFrame(columns=DAILY_COLUMNS),
        )
        return

    daily_reference = build_daily_reference(prices)
    early_regime = calculate_early_market_regime(prices, daily_reference)
    candidates, trades = build_candidates_and_trades(
        prices=prices,
        daily_reference=daily_reference,
        early_regime=early_regime,
    )
    daily = build_daily(candidates, trades)

    export_outputs(candidates, trades, daily)

    print(f"Database rows loaded : {len(prices)}")
    print(f"Research tickers     : {len(GAP_RECOVERY_TICKERS)}")
    print(f"Candidate rows       : {len(candidates)}")
    print(f"Triggered trade rows : {len(trades)}")
    print("Research export complete.")


if __name__ == "__main__":
    main()
