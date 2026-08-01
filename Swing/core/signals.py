"""Canonical signal selection and signal-to-execution alignment."""

from __future__ import annotations

import pandas as pd

from core.config import StrategyConfig


SIGNAL_OUTPUT_COLUMNS = [
    "signal_date",
    "execution_date",
    "ticker",
    "alpha",
    "momentum",
    "stock_regime",
    "target_weight",
    "selection_rank",
]


def build_target_portfolios(
    features: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
    config: StrategyConfig,
) -> pd.DataFrame:
    """Select securities at close T for execution at open T+1."""

    calendar = pd.DatetimeIndex(pd.to_datetime(trading_calendar)).sort_values().unique()
    if len(calendar) < 2:
        return pd.DataFrame(columns=SIGNAL_OUTPUT_COLUMNS)

    next_session = pd.Series(calendar[1:], index=calendar[:-1])
    eligible = features[features["eligible"] & features["alpha"].notna()].copy()
    eligible["execution_date"] = eligible["date"].map(next_session)
    eligible = eligible.dropna(subset=["execution_date"])

    selected = (
        eligible.sort_values(["date", "alpha", "ticker"], ascending=[True, False, True])
        .groupby("date", group_keys=False)
        .head(config.top_n)
        .copy()
    )
    selected["selection_rank"] = selected.groupby("date").cumcount() + 1
    selected["target_weight"] = 1.0 / selected.groupby("date")["ticker"].transform("count")
    selected = selected.rename(columns={"date": "signal_date"})

    return selected[SIGNAL_OUTPUT_COLUMNS].sort_values(
        ["execution_date", "selection_rank"]
    ).reset_index(drop=True)
