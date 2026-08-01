"""Leakage-aware feature and realized-return construction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import StrategyConfig


FEATURE_COLUMNS = [
    "date",
    "ticker",
    "close",
    "momentum",
    "stock_regime",
    "eligible",
    "alpha",
]


def _cross_sectional_zscore(series: pd.Series) -> pd.Series:
    standard_deviation = series.std(ddof=1)
    if pd.isna(standard_deviation) or standard_deviation == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / standard_deviation


def build_feature_table(prices: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Build predictors using information available after each session close."""

    frame = prices.sort_values(["ticker", "date"]).copy()
    ticker_group = frame.groupby("ticker", sort=False)

    frame["momentum"] = ticker_group["close"].pct_change(config.momentum_window)
    frame["regime_return"] = ticker_group["close"].pct_change(config.regime_window)
    frame["stock_regime"] = np.select(
        [
            frame["regime_return"] > config.bull_threshold,
            frame["regime_return"] < config.bear_threshold,
        ],
        ["bull", "bear"],
        default="sideways",
    )
    frame["eligible"] = frame["momentum"].notna()
    if config.exclude_bear_regime:
        frame["eligible"] &= frame["stock_regime"] != "bear"

    frame["alpha"] = frame.groupby("date", group_keys=False)["momentum"].transform(
        _cross_sectional_zscore
    )

    return frame[FEATURE_COLUMNS].sort_values(["date", "ticker"]).reset_index(drop=True)


def build_return_table(prices: pd.DataFrame) -> pd.DataFrame:
    """Build realized returns separately from predictors.

    ``open_to_next_open_return`` is the canonical continuously-held swing return:
    positions entered at the open of session T are marked at the open of T+1.
    """

    frame = prices.sort_values(["ticker", "date"]).copy()
    ticker_group = frame.groupby("ticker", sort=False)
    frame["next_date"] = ticker_group["date"].shift(-1)
    frame["next_open"] = ticker_group["open"].shift(-1)
    frame["open_to_next_open_return"] = frame["next_open"] / frame["open"] - 1.0
    frame["close_to_close_return"] = ticker_group["close"].pct_change()
    frame["open_to_close_return"] = frame["close"] / frame["open"] - 1.0
    frame["close_to_next_open_return"] = frame["next_open"] / frame["close"] - 1.0

    columns = [
        "date",
        "next_date",
        "ticker",
        "open",
        "close",
        "next_open",
        "open_to_next_open_return",
        "open_to_close_return",
        "close_to_next_open_return",
        "close_to_close_return",
    ]
    return frame[columns].sort_values(["date", "ticker"]).reset_index(drop=True)
