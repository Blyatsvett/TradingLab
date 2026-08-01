from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from Intraday.core.export_utils import export_csv_for_power_bi
from Intraday.core.paths import DATA_DIR, INTRADAY_DB
from Intraday.core.orb_execution import execute_long_orb_trade


STRATEGY_ID = "REGIME_AWARE_GAP_RECOVERY_V1"
RESEARCH_STATUS = "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION"

STOCKHOLM_TZ = "Europe/Stockholm"

INITIAL_CAPITAL = 10000
POSITION_SIZE_PCT = 0.10

OPENING_RANGE_START = "09:30"
OPENING_RANGE_END = "09:35"

REGIME_CUTOFF_TIME = "09:45"
ENTRY_START = "09:45"
ENTRY_END = "13:00"
EOD_EXIT_TIME = "16:30"

MIN_GAP_DOWN = -0.0200
MAX_GAP_DOWN = -0.0010

MAX_OPENING_RANGE_PCT = 0.0300
MAX_RISK_PCT = 0.0350
MIN_REWARD_RISK = 0.50

SAME_BAR_PRIORITY = "STOP"

GAP_RECOVERY_TICKERS = [
    "ATCO-A.ST",
    "ATCO-B.ST",
    "AZN.ST",
    "BOL.ST",
    "EVO.ST",
    "SAND.ST",
    "SWED-A.ST",
]

SUMMARY_FILE = DATA_DIR / "regime_gap_recovery_summary.csv"
TRADES_FILE = DATA_DIR / "regime_gap_recovery_trades.csv"
DAILY_FILE = DATA_DIR / "regime_gap_recovery_daily.csv"
LATEST_FILE = DATA_DIR / "regime_gap_recovery_latest.csv"
CANDIDATES_FILE = DATA_DIR / "regime_gap_recovery_candidates.csv"


def parse_local_datetime(series: pd.Series) -> pd.Series:
    text = series.astype(str)

    has_timezone = text.str.contains(
        r"([+-]\d{2}:\d{2}|[+-]\d{4}|Z)$",
        regex=True,
        na=False,
    ).any()

    if has_timezone:
        parsed = pd.to_datetime(text, errors="coerce", utc=True)
        return parsed.dt.tz_convert(STOCKHOLM_TZ).dt.tz_localize(None)

    return pd.to_datetime(text, errors="coerce")


def load_prices() -> pd.DataFrame:
    if not Path(INTRADAY_DB).exists():
        raise FileNotFoundError(f"Missing database: {INTRADAY_DB}")

    conn = sqlite3.connect(INTRADAY_DB)

    try:
        prices = pd.read_sql("SELECT * FROM intraday_prices", conn)
    finally:
        conn.close()

    if prices.empty:
        raise ValueError("intraday_prices table is empty.")

    prices.columns = [str(col).strip().lower() for col in prices.columns]

    required = ["ticker", "datetime", "high", "low", "close"]

    for col in required:
        if col not in prices.columns:
            raise ValueError(f"intraday_prices missing required column: {col}")

    if "open" not in prices.columns:
        prices["open"] = prices["close"]

    prices["ticker"] = prices["ticker"].astype(str)
    prices["datetime"] = parse_local_datetime(prices["datetime"])

    for col in ["open", "high", "low", "close"]:
        prices[col] = pd.to_numeric(prices[col], errors="coerce")

    prices = prices.dropna(
        subset=[
            "ticker",
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]
    ).copy()

    prices["date"] = prices["datetime"].dt.strftime("%Y-%m-%d")
    prices["clock"] = prices["datetime"].dt.strftime("%H:%M")

    prices = prices.sort_values(["ticker", "datetime"]).reset_index(drop=True)

    return attach_previous_close(prices)


def attach_previous_close(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.copy()

    daily_close = (
        prices.sort_values(["ticker", "datetime"])
        .groupby(["ticker", "date"], as_index=False)
        .last()[["ticker", "date", "close"]]
        .rename(columns={"close": "daily_close"})
    )

    daily_close = daily_close.sort_values(["ticker", "date"]).reset_index(drop=True)
    daily_close["previous_close"] = daily_close.groupby("ticker")["daily_close"].shift(1)

    output = prices.merge(
        daily_close[["ticker", "date", "previous_close"]],
        on=["ticker", "date"],
        how="left",
    )

    return output


def classify_early_regime(
    breadth_above_open: float,
    median_return_from_open: float,
    positive_gap_breadth: float,
    sample_size: int,
) -> str:
    if sample_size < 5:
        return "INSUFFICIENT_DATA"

    if breadth_above_open >= 0.55 and median_return_from_open >= 0:
        return "EARLY_BROAD_STRENGTH"

    if breadth_above_open >= 0.45 and median_return_from_open >= -0.001:
        return "EARLY_STABLE_RECOVERY"

    if positive_gap_breadth >= 0.55 and median_return_from_open >= -0.002:
        return "EARLY_GAP_SUPPORT"

    return "EARLY_WEAK_OR_UNFAVORABLE"


def is_favorable_regime(regime: str) -> bool:
    return regime in [
        "EARLY_BROAD_STRENGTH",
        "EARLY_STABLE_RECOVERY",
        "EARLY_GAP_SUPPORT",
    ]


def build_early_regime_table(prices: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for (date, ticker), day in prices.groupby(["date", "ticker"]):
        day = day.sort_values("datetime").copy()

        early = day[day["clock"] <= REGIME_CUTOFF_TIME].copy()

        if early.empty:
            continue

        previous_close = day["previous_close"].dropna()

        if previous_close.empty:
            continue

        previous_close_value = float(previous_close.iloc[0])
        open_price = float(day.iloc[0]["open"])
        early_close = float(early.iloc[-1]["close"])

        if previous_close_value == 0 or open_price == 0:
            continue

        gap = (open_price - previous_close_value) / previous_close_value
        return_from_open = (early_close - open_price) / open_price

        rows.append(
            {
                "date": date,
                "ticker": ticker,
                "gap": gap,
                "return_from_open": return_from_open,
                "above_open": early_close > open_price,
                "positive_gap": gap >= 0,
            }
        )

    ticker_state = pd.DataFrame(rows)

    if ticker_state.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "early_market_regime",
                "sample_size",
                "breadth_above_open",
                "positive_gap_breadth",
                "median_return_from_open",
                "median_gap",
            ]
        )

    regime_rows = []

    for date, group in ticker_state.groupby("date"):
        sample_size = len(group)
        breadth_above_open = float(group["above_open"].mean())
        positive_gap_breadth = float(group["positive_gap"].mean())
        median_return_from_open = float(group["return_from_open"].median())
        median_gap = float(group["gap"].median())

        early_market_regime = classify_early_regime(
            breadth_above_open=breadth_above_open,
            median_return_from_open=median_return_from_open,
            positive_gap_breadth=positive_gap_breadth,
            sample_size=sample_size,
        )

        regime_rows.append(
            {
                "date": date,
                "early_market_regime": early_market_regime,
                "sample_size": sample_size,
                "breadth_above_open": breadth_above_open,
                "positive_gap_breadth": positive_gap_breadth,
                "median_return_from_open": median_return_from_open,
                "median_gap": median_gap,
            }
        )

    return pd.DataFrame(regime_rows).sort_values("date").reset_index(drop=True)


def get_latest_date_and_clock(prices: pd.DataFrame) -> tuple[str, str]:
    latest_date = prices["date"].max()
    latest_clock = prices.loc[prices["date"] == latest_date, "clock"].max()
    return latest_date, latest_clock


def get_completed_dates(prices: pd.DataFrame) -> set[str]:
    latest_date, latest_clock = get_latest_date_and_clock(prices)

    all_dates = set(prices["date"].dropna().unique())

    if latest_clock < EOD_EXIT_TIME:
        all_dates.discard(latest_date)

    return all_dates


def get_first_trigger_bar(
    day: pd.DataFrame,
    entry_trigger: float,
) -> pd.Series | None:
    entry_window = day[
        (day["clock"] >= ENTRY_START)
        & (day["clock"] <= ENTRY_END)
    ].copy()

    if entry_window.empty:
        return None

    triggered = entry_window[entry_window["high"] >= entry_trigger].copy()

    if triggered.empty:
        return None

    triggered = triggered.sort_values("datetime").reset_index(drop=True)

    return triggered.iloc[0]


def build_candidates(
    prices: pd.DataFrame,
    regime_table: pd.DataFrame,
) -> pd.DataFrame:
    regime_lookup = {
        row["date"]: row.to_dict()
        for _, row in regime_table.iterrows()
    }

    rows = []

    trade_prices = prices[prices["ticker"].isin(GAP_RECOVERY_TICKERS)].copy()

    for (ticker, date), day in trade_prices.groupby(["ticker", "date"]):
        day = day.sort_values("datetime").copy()

        previous_close_values = day["previous_close"].dropna()

        if previous_close_values.empty:
            continue

        previous_close = float(previous_close_values.iloc[0])
        open_price = float(day.iloc[0]["open"])

        if previous_close == 0 or open_price == 0:
            continue

        gap = (open_price - previous_close) / previous_close

        if gap >= 0:
            continue

        opening_range = day[
            (day["clock"] >= OPENING_RANGE_START)
            & (day["clock"] < OPENING_RANGE_END)
        ].copy()

        if opening_range.empty:
            rows.append(
                build_candidate_row(
                    date=date,
                    ticker=ticker,
                    gap=gap,
                    previous_close=previous_close,
                    open_price=open_price,
                    entry_trigger=None,
                    stop_price=None,
                    target_price=None,
                    opening_range_pct=None,
                    risk_pct=None,
                    reward_risk=None,
                    early_market_regime="UNKNOWN",
                    favorable_regime=False,
                    candidate_status="INVALID",
                    invalid_reason="MISSING_OPENING_RANGE",
                    entry_time=None,
                    entry_price=None,
                    would_cross_entry_anyway=False,
                    theoretical_entry_time=None,
                    current_price=float(day.iloc[-1]["close"]),
                    last_bar=day.iloc[-1]["datetime"],
                )
            )
            continue

        entry_trigger = float(opening_range["high"].max())
        stop_price = float(opening_range["low"].min())
        target_price = previous_close

        risk_per_share = entry_trigger - stop_price
        reward_per_share = target_price - entry_trigger

        if entry_trigger == 0:
            continue

        opening_range_pct = (entry_trigger - stop_price) / entry_trigger
        risk_pct = risk_per_share / entry_trigger

        reward_risk = None

        if risk_per_share > 0:
            reward_risk = reward_per_share / risk_per_share

        regime_info = regime_lookup.get(date, {})
        early_market_regime = regime_info.get("early_market_regime", "UNKNOWN")
        favorable_regime = is_favorable_regime(early_market_regime)

        invalid_reason = ""
        candidate_status = "VALID_NOT_TRIGGERED"

        if gap < MIN_GAP_DOWN:
            candidate_status = "INVALID"
            invalid_reason = "GAP_TOO_DEEP"
        elif gap > MAX_GAP_DOWN:
            candidate_status = "INVALID"
            invalid_reason = "GAP_NOT_NEGATIVE_ENOUGH"
        elif opening_range_pct > MAX_OPENING_RANGE_PCT:
            candidate_status = "INVALID"
            invalid_reason = "OPENING_RANGE_TOO_WIDE"
        elif risk_pct > MAX_RISK_PCT:
            candidate_status = "INVALID"
            invalid_reason = "RISK_TOO_HIGH"
        elif target_price <= entry_trigger:
            candidate_status = "INVALID"
            invalid_reason = "TARGET_NOT_ABOVE_ENTRY"
        elif reward_risk is None or reward_risk < MIN_REWARD_RISK:
            candidate_status = "INVALID"
            invalid_reason = "REWARD_RISK_TOO_LOW"
        elif not favorable_regime:
            candidate_status = "INVALID"
            invalid_reason = "UNFAVORABLE_EARLY_REGIME"

        trigger_bar = get_first_trigger_bar(
            day=day,
            entry_trigger=entry_trigger,
        )

        would_cross_entry_anyway = trigger_bar is not None
        theoretical_entry_time = trigger_bar["datetime"] if trigger_bar is not None else None

        entry_time = None
        entry_price = None

        if candidate_status == "VALID_NOT_TRIGGERED" and trigger_bar is not None:
            candidate_status = "TRIGGERED"
            entry_time = trigger_bar["datetime"]
            entry_price = entry_trigger

        rows.append(
            build_candidate_row(
                date=date,
                ticker=ticker,
                gap=gap,
                previous_close=previous_close,
                open_price=open_price,
                entry_trigger=entry_trigger,
                stop_price=stop_price,
                target_price=target_price,
                opening_range_pct=opening_range_pct,
                risk_pct=risk_pct,
                reward_risk=reward_risk,
                early_market_regime=early_market_regime,
                favorable_regime=favorable_regime,
                candidate_status=candidate_status,
                invalid_reason=invalid_reason,
                entry_time=entry_time,
                entry_price=entry_price,
                would_cross_entry_anyway=would_cross_entry_anyway,
                theoretical_entry_time=theoretical_entry_time,
                current_price=float(day.iloc[-1]["close"]),
                last_bar=day.iloc[-1]["datetime"],
            )
        )

    if not rows:
        return empty_candidates()

    return pd.DataFrame(rows).sort_values(["date", "ticker"]).reset_index(drop=True)


def build_candidate_row(
    date: str,
    ticker: str,
    gap: float,
    previous_close: float,
    open_price: float,
    entry_trigger: float | None,
    stop_price: float | None,
    target_price: float | None,
    opening_range_pct: float | None,
    risk_pct: float | None,
    reward_risk: float | None,
    early_market_regime: str,
    favorable_regime: bool,
    candidate_status: str,
    invalid_reason: str,
    entry_time,
    entry_price: float | None,
    would_cross_entry_anyway: bool,
    theoretical_entry_time,
    current_price: float,
    last_bar,
) -> dict:
    distance_to_entry = None
    distance_to_target = None

    if entry_trigger is not None:
        distance_to_entry = entry_trigger - current_price

    if target_price is not None:
        distance_to_target = target_price - current_price

    return {
        "strategy_id": STRATEGY_ID,
        "research_status": RESEARCH_STATUS,
        "date": date,
        "ticker": ticker,
        "candidate_status": candidate_status,
        "invalid_reason": invalid_reason,
        "gap": gap,
        "gap_pct": gap * 100,
        "previous_close": previous_close,
        "open_price": open_price,
        "current_price": current_price,
        "entry_trigger": entry_trigger,
        "entry_time": entry_time,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "opening_range_pct": opening_range_pct,
        "opening_range_pct_points": None if opening_range_pct is None else opening_range_pct * 100,
        "risk_pct": risk_pct,
        "risk_pct_points": None if risk_pct is None else risk_pct * 100,
        "reward_risk": reward_risk,
        "early_market_regime": early_market_regime,
        "favorable_regime": favorable_regime,
        "would_cross_entry_anyway": would_cross_entry_anyway,
        "theoretical_entry_time": theoretical_entry_time,
        "distance_to_entry": distance_to_entry,
        "distance_to_target": distance_to_target,
        "last_bar": last_bar,
        "target_mode": "PREVIOUS_CLOSE_GAP_FILL",
        "entry_window": f"{ENTRY_START}-{ENTRY_END}",
        "eod_exit_time": EOD_EXIT_TIME,
    }


def empty_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
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
        ]
    )


def execute_research_trades(
    candidates: pd.DataFrame,
    prices: pd.DataFrame,
    completed_dates: set[str],
) -> pd.DataFrame:
    rows = []

    triggered = candidates[
        (candidates["candidate_status"] == "TRIGGERED")
        & (candidates["date"].isin(completed_dates))
    ].copy()

    for _, candidate in triggered.iterrows():
        ticker = candidate["ticker"]
        date = candidate["date"]

        day_bars = prices[
            (prices["ticker"] == ticker)
            & (prices["date"] == date)
        ].copy()

        if day_bars.empty:
            continue

        entry_time = pd.to_datetime(candidate["entry_time"], errors="coerce")

        if pd.isna(entry_time):
            continue

        result = execute_long_orb_trade(
            entry_time=entry_time,
            entry_price=float(candidate["entry_price"]),
            stop_price=float(candidate["stop_price"]),
            target_price=float(candidate["target_price"]),
            bars=day_bars,
            timestamp_col="datetime",
            close_if_no_hit=True,
            same_bar_priority=SAME_BAR_PRIORITY,
            eod_exit_time=EOD_EXIT_TIME,
        )

        if result.status != "CLOSED":
            continue

        position_size_sek = INITIAL_CAPITAL * POSITION_SIZE_PCT
        pnl_sek = position_size_sek * result.pnl_pct
        account_return = POSITION_SIZE_PCT * result.pnl_pct

        rows.append(
            {
                "strategy_id": STRATEGY_ID,
                "research_status": RESEARCH_STATUS,
                "date": date,
                "ticker": ticker,
                "entry_time": entry_time,
                "entry_price": float(candidate["entry_price"]),
                "stop_price": float(candidate["stop_price"]),
                "target_price": float(candidate["target_price"]),
                "exit_time": result.exit_time,
                "exit_price": result.exit_price,
                "exit_reason": result.exit_reason,
                "pnl_pct": result.pnl_pct,
                "position_size_sek": position_size_sek,
                "pnl_sek": pnl_sek,
                "account_return": account_return,
                "trade_duration_minutes": result.trade_duration_minutes,
                "risk_per_share": result.risk_per_share,
                "r_multiple_achieved": result.r_multiple_achieved,
                "gap": candidate["gap"],
                "gap_pct": candidate["gap_pct"],
                "opening_range_pct": candidate["opening_range_pct"],
                "opening_range_pct_points": candidate["opening_range_pct_points"],
                "risk_pct": candidate["risk_pct"],
                "risk_pct_points": candidate["risk_pct_points"],
                "reward_risk": candidate["reward_risk"],
                "early_market_regime": candidate["early_market_regime"],
                "target_mode": candidate["target_mode"],
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
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
            ]
        )

    return pd.DataFrame(rows).sort_values(["date", "entry_time", "ticker"]).reset_index(drop=True)


def calculate_summary(candidates: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    total_candidates = len(candidates)
    valid_candidates = int(candidates["candidate_status"].isin(["VALID_NOT_TRIGGERED", "TRIGGERED"]).sum()) if not candidates.empty else 0
    triggered_candidates = int((candidates["candidate_status"] == "TRIGGERED").sum()) if not candidates.empty else 0

    if trades.empty:
        return pd.DataFrame(
            [
                {
                    "strategy_id": STRATEGY_ID,
                    "research_status": RESEARCH_STATUS,
                    "total_candidates": total_candidates,
                    "valid_candidates": valid_candidates,
                    "triggered_candidates": triggered_candidates,
                    "completed_trades": 0,
                    "win_rate": 0,
                    "total_pnl_sek": 0,
                    "total_account_return": 0,
                    "profit_factor": 0,
                    "avg_r_multiple": 0,
                    "note": "Research-only regime-aware negative-gap recovery strategy. Not production.",
                }
            ]
        )

    wins = trades[trades["pnl_sek"] > 0]
    losses = trades[trades["pnl_sek"] < 0]

    gross_profit = wins["pnl_sek"].sum()
    gross_loss = losses["pnl_sek"].sum()

    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    else:
        profit_factor = 0

    return pd.DataFrame(
        [
            {
                "strategy_id": STRATEGY_ID,
                "research_status": RESEARCH_STATUS,
                "total_candidates": total_candidates,
                "valid_candidates": valid_candidates,
                "triggered_candidates": triggered_candidates,
                "completed_trades": len(trades),
                "win_rate": len(wins) / len(trades),
                "total_pnl_sek": trades["pnl_sek"].sum(),
                "total_account_return": trades["account_return"].sum(),
                "profit_factor": profit_factor,
                "avg_r_multiple": trades["r_multiple_achieved"].mean(),
                "note": "Research-only regime-aware negative-gap recovery strategy. Not production.",
            }
        ]
    )


def calculate_daily_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "strategy_id",
                "date",
                "trades",
                "wins",
                "losses",
                "win_rate",
                "daily_pnl_sek",
                "daily_account_return",
            ]
        )

    rows = []

    for date, group in trades.groupby("date"):
        wins = int((group["pnl_sek"] > 0).sum())
        losses = int((group["pnl_sek"] < 0).sum())
        trades_count = len(group)

        rows.append(
            {
                "strategy_id": STRATEGY_ID,
                "date": date,
                "trades": trades_count,
                "wins": wins,
                "losses": losses,
                "win_rate": wins / trades_count if trades_count else 0,
                "daily_pnl_sek": group["pnl_sek"].sum(),
                "daily_account_return": group["account_return"].sum(),
            }
        )

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def main() -> None:
    print("\n=== REGIME-AWARE GAP RECOVERY RESEARCH ===")
    print("Research only. Production ORB is unchanged.")
    print(f"Strategy id: {STRATEGY_ID}")

    prices = load_prices()
    latest_date, latest_clock = get_latest_date_and_clock(prices)

    print(f"Latest session in data: {latest_date} {latest_clock}")
    print(f"Tickers in strategy watchlist: {len(GAP_RECOVERY_TICKERS)}")

    regime_table = build_early_regime_table(prices)
    candidates = build_candidates(prices=prices, regime_table=regime_table)

    completed_dates = get_completed_dates(prices)
    trades = execute_research_trades(
        candidates=candidates,
        prices=prices,
        completed_dates=completed_dates,
    )

    summary = calculate_summary(candidates=candidates, trades=trades)
    daily = calculate_daily_summary(trades=trades)

    latest_candidates = candidates[candidates["date"] == latest_date].copy()

    export_csv_for_power_bi(summary, SUMMARY_FILE)
    export_csv_for_power_bi(trades, TRADES_FILE)
    export_csv_for_power_bi(daily, DAILY_FILE)
    export_csv_for_power_bi(latest_candidates, LATEST_FILE)
    export_csv_for_power_bi(candidates, CANDIDATES_FILE)

    print("\n=== SUMMARY ===")
    print(summary.to_string(index=False))

    print("\n=== LATEST CANDIDATES ===")
    if latest_candidates.empty:
        print("No latest negative-gap candidates.")
    else:
        print(latest_candidates.to_string(index=False))

    print(f"\nSaved summary    -> {SUMMARY_FILE}")
    print(f"Saved trades     -> {TRADES_FILE}")
    print(f"Saved daily      -> {DAILY_FILE}")
    print(f"Saved latest     -> {LATEST_FILE}")
    print(f"Saved candidates -> {CANDIDATES_FILE}")


if __name__ == "__main__":
    main()