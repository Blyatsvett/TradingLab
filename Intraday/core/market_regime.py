from __future__ import annotations

import pandas as pd


REQUIRED_PRICE_COLUMNS = {
    "ticker",
    "open",
    "high",
    "low",
    "close",
}


def detect_timestamp_column(df: pd.DataFrame) -> str:
    candidates = [
        "timestamp",
        "datetime",
        "date_time",
        "time",
    ]

    for col in candidates:
        if col in df.columns:
            return col

    raise ValueError(
        "Could not find a timestamp column. Expected one of: "
        "timestamp, datetime, date_time, time"
    )


def normalise_intraday_prices_for_regime(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.copy()

    missing = REQUIRED_PRICE_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required price columns: {sorted(missing)}")

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

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values(["ticker", "timestamp"]).reset_index(drop=True)

    return df


def calculate_daily_vwap(day: pd.DataFrame) -> float:
    day = day.copy()

    if "volume" not in day.columns or day["volume"].fillna(0).sum() <= 0:
        return float(day["close"].mean())

    typical_price = (day["high"] + day["low"] + day["close"]) / 3.0
    dollar_volume = typical_price * day["volume"]

    return float(dollar_volume.sum() / day["volume"].sum())


def classify_gap_regime(avg_gap: float) -> str:
    if avg_gap >= 0.005:
        return "strong_gap_up"
    if avg_gap >= 0.001:
        return "gap_up"
    if avg_gap <= -0.005:
        return "strong_gap_down"
    if avg_gap <= -0.001:
        return "gap_down"
    return "flat_open"


def classify_trend_regime(avg_day_return: float) -> str:
    if avg_day_return >= 0.005:
        return "strong_up"
    if avg_day_return >= 0.001:
        return "up"
    if avg_day_return <= -0.005:
        return "strong_down"
    if avg_day_return <= -0.001:
        return "down"
    return "flat"


def classify_breadth_regime(breadth_positive: float) -> str:
    if breadth_positive >= 0.70:
        return "broad_strength"
    if breadth_positive <= 0.30:
        return "broad_weakness"
    return "mixed"


def classify_volatility_regime(avg_full_day_range_pct: float) -> str:
    if avg_full_day_range_pct >= 0.025:
        return "high_volatility"
    if avg_full_day_range_pct <= 0.012:
        return "low_volatility"
    return "normal_volatility"


def classify_opening_range_regime(avg_opening_range_pct: float) -> str:
    if avg_opening_range_pct >= 0.012:
        return "wide_opening_range"
    if avg_opening_range_pct <= 0.005:
        return "narrow_opening_range"
    return "normal_opening_range"


def build_ticker_daily_regime_inputs(
    prices: pd.DataFrame,
    opening_range_start: str = "09:30",
    opening_range_end: str = "10:00",
) -> pd.DataFrame:
    df = normalise_intraday_prices_for_regime(prices)

    ticker_day_rows = []

    for (ticker, trade_date), day in df.groupby(["ticker", "date"]):
        day = day.sort_values("timestamp").copy()

        if day.empty:
            continue

        first_bar = day.iloc[0]
        last_bar = day.iloc[-1]

        opening_window = day[
            (day["time"] >= opening_range_start)
            & (day["time"] <= opening_range_end)
        ].copy()

        if opening_window.empty:
            opening_window = day.head(1).copy()

        first_open = float(first_bar["open"])
        last_close = float(last_bar["close"])

        day_high = float(day["high"].max())
        day_low = float(day["low"].min())

        opening_high = float(opening_window["high"].max())
        opening_low = float(opening_window["low"].min())

        day_vwap = calculate_daily_vwap(day)

        ticker_day_rows.append(
            {
                "date": trade_date,
                "ticker": ticker,
                "first_timestamp": first_bar["timestamp"],
                "last_timestamp": last_bar["timestamp"],
                "first_open": first_open,
                "last_close": last_close,
                "day_high": day_high,
                "day_low": day_low,
                "opening_high": opening_high,
                "opening_low": opening_low,
                "day_vwap": day_vwap,
                "day_return_from_open": (
                    (last_close / first_open) - 1.0
                    if first_open > 0
                    else 0.0
                ),
                "full_day_range_pct": (
                    (day_high - day_low) / first_open
                    if first_open > 0
                    else 0.0
                ),
                "opening_range_pct": (
                    (opening_high - opening_low) / first_open
                    if first_open > 0
                    else 0.0
                ),
                "close_above_open": last_close > first_open,
                "close_above_vwap": last_close > day_vwap,
            }
        )

    ticker_daily = pd.DataFrame(ticker_day_rows)

    if ticker_daily.empty:
        return ticker_daily

    ticker_daily = ticker_daily.sort_values(["ticker", "date"]).reset_index(drop=True)

    ticker_daily["previous_close"] = ticker_daily.groupby("ticker")[
        "last_close"
    ].shift(1)

    ticker_daily["gap_pct"] = (
        ticker_daily["first_open"] / ticker_daily["previous_close"] - 1.0
    )

    ticker_daily["gap_pct"] = ticker_daily["gap_pct"].fillna(0.0)

    ticker_daily["return_from_previous_close"] = (
        ticker_daily["last_close"] / ticker_daily["previous_close"] - 1.0
    )

    ticker_daily["return_from_previous_close"] = ticker_daily[
        "return_from_previous_close"
    ].fillna(ticker_daily["day_return_from_open"])

    ticker_daily["close_above_previous_close"] = (
        ticker_daily["last_close"] > ticker_daily["previous_close"]
    )

    ticker_daily["close_above_previous_close"] = ticker_daily[
        "close_above_previous_close"
    ].fillna(False)

    return ticker_daily


def calculate_daily_market_regime(
    prices: pd.DataFrame,
    opening_range_start: str = "09:30",
    opening_range_end: str = "10:00",
) -> pd.DataFrame:
    ticker_daily = build_ticker_daily_regime_inputs(
        prices=prices,
        opening_range_start=opening_range_start,
        opening_range_end=opening_range_end,
    )

    if ticker_daily.empty:
        return pd.DataFrame()

    rows = []

    for trade_date, day in ticker_daily.groupby("date"):
        day = day.copy()

        n_tickers = int(day["ticker"].nunique())

        avg_gap_pct = float(day["gap_pct"].mean())
        median_gap_pct = float(day["gap_pct"].median())

        avg_day_return_from_open = float(day["day_return_from_open"].mean())
        median_day_return_from_open = float(day["day_return_from_open"].median())

        avg_return_from_previous_close = float(
            day["return_from_previous_close"].mean()
        )

        median_return_from_previous_close = float(
            day["return_from_previous_close"].median()
        )

        avg_full_day_range_pct = float(day["full_day_range_pct"].mean())
        median_full_day_range_pct = float(day["full_day_range_pct"].median())

        avg_opening_range_pct = float(day["opening_range_pct"].mean())
        median_opening_range_pct = float(day["opening_range_pct"].median())

        breadth_positive_from_open = float(day["close_above_open"].mean())
        breadth_positive_from_previous_close = float(
            day["close_above_previous_close"].mean()
        )
        breadth_above_vwap = float(day["close_above_vwap"].mean())

        up_from_open_count = int(day["close_above_open"].sum())
        up_from_previous_close_count = int(day["close_above_previous_close"].sum())
        above_vwap_count = int(day["close_above_vwap"].sum())

        market_gap_regime = classify_gap_regime(avg_gap_pct)
        market_trend_regime = classify_trend_regime(avg_return_from_previous_close)
        market_intraday_trend_regime = classify_trend_regime(
            avg_day_return_from_open
        )
        market_breadth_regime = classify_breadth_regime(
            breadth_positive_from_previous_close
        )
        market_intraday_breadth_regime = classify_breadth_regime(
            breadth_positive_from_open
        )
        market_vwap_breadth_regime = classify_breadth_regime(breadth_above_vwap)
        market_volatility_regime = classify_volatility_regime(
            avg_full_day_range_pct
        )
        opening_range_regime = classify_opening_range_regime(
            avg_opening_range_pct
        )

        composite_regime = (
            market_trend_regime
            + "__"
            + market_volatility_regime
            + "__"
            + market_breadth_regime
        )

        rows.append(
            {
                "date": trade_date,
                "n_tickers": n_tickers,
                "avg_gap_pct": avg_gap_pct,
                "median_gap_pct": median_gap_pct,
                "avg_day_return_from_open": avg_day_return_from_open,
                "median_day_return_from_open": median_day_return_from_open,
                "avg_return_from_previous_close": avg_return_from_previous_close,
                "median_return_from_previous_close": (
                    median_return_from_previous_close
                ),
                "avg_full_day_range_pct": avg_full_day_range_pct,
                "median_full_day_range_pct": median_full_day_range_pct,
                "avg_opening_range_pct": avg_opening_range_pct,
                "median_opening_range_pct": median_opening_range_pct,
                "breadth_positive_from_open": breadth_positive_from_open,
                "breadth_positive_from_previous_close": (
                    breadth_positive_from_previous_close
                ),
                "breadth_above_vwap": breadth_above_vwap,
                "up_from_open_count": up_from_open_count,
                "up_from_previous_close_count": up_from_previous_close_count,
                "above_vwap_count": above_vwap_count,
                "market_gap_regime": market_gap_regime,
                "market_trend_regime": market_trend_regime,
                "market_intraday_trend_regime": market_intraday_trend_regime,
                "market_breadth_regime": market_breadth_regime,
                "market_intraday_breadth_regime": (
                    market_intraday_breadth_regime
                ),
                "market_vwap_breadth_regime": market_vwap_breadth_regime,
                "market_volatility_regime": market_volatility_regime,
                "opening_range_regime": opening_range_regime,
                "composite_regime": composite_regime,
                "regime_use": "DIAGNOSTIC_ONLY",
            }
        )

    regime = pd.DataFrame(rows)

    regime = regime.sort_values("date").reset_index(drop=True)
    regime["regime_row_number"] = regime.index + 1

    return regime


def attach_market_regime(
    df: pd.DataFrame,
    market_regime: pd.DataFrame,
    date_col: str = "date",
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    if market_regime.empty:
        return df.copy()

    output = df.copy()
    regime = market_regime.copy()

    output[date_col] = pd.to_datetime(output[date_col], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    regime["date"] = pd.to_datetime(regime["date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )

    regime_columns = [
        "date",
        "n_tickers",
        "avg_gap_pct",
        "avg_day_return_from_open",
        "avg_return_from_previous_close",
        "avg_full_day_range_pct",
        "avg_opening_range_pct",
        "breadth_positive_from_open",
        "breadth_positive_from_previous_close",
        "breadth_above_vwap",
        "market_gap_regime",
        "market_trend_regime",
        "market_intraday_trend_regime",
        "market_breadth_regime",
        "market_intraday_breadth_regime",
        "market_vwap_breadth_regime",
        "market_volatility_regime",
        "opening_range_regime",
        "composite_regime",
        "regime_use",
    ]

    existing_regime_columns = [
        col for col in regime_columns if col in regime.columns
    ]

    output = output.merge(
        regime[existing_regime_columns],
        left_on=date_col,
        right_on="date",
        how="left",
        suffixes=("", "_regime"),
    )

    if date_col != "date" and "date_regime" in output.columns:
        output = output.drop(columns=["date_regime"])

    return output