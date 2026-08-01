from dataclasses import asdict, dataclass
from typing import Optional

import pandas as pd


STOP_HIT = "STOP_HIT"
TARGET_HIT = "TARGET_HIT"
CLOSED_EOD = "CLOSED_EOD"
OPEN_NO_BARS = "OPEN_NO_BARS"
OPEN_NO_EXIT = "OPEN_NO_EXIT"
DEFAULT_EOD_EXIT_TIME = "16:30"


@dataclass
class OrbExecutionResult:
    status: str
    exit_time: str
    exit_price: float
    exit_reason: str
    pnl_pct: float
    trade_duration_minutes: float
    risk_per_share: float
    r_multiple_achieved: float

    def to_dict(self) -> dict:
        return asdict(self)


def empty_open_result(
    entry_price: float,
    stop_price: float,
    reason: str,
) -> OrbExecutionResult:
    risk_per_share = max(float(entry_price) - float(stop_price), 0.0)

    return OrbExecutionResult(
        status="OPEN",
        exit_time="",
        exit_price=0.0,
        exit_reason=reason,
        pnl_pct=0.0,
        trade_duration_minutes=0.0,
        risk_per_share=risk_per_share,
        r_multiple_achieved=0.0,
    )


def closed_result(
    entry_time,
    entry_price: float,
    stop_price: float,
    exit_time,
    exit_price: float,
    exit_reason: str,
) -> OrbExecutionResult:
    entry_time = pd.to_datetime(entry_time)
    exit_time = pd.to_datetime(exit_time)

    entry_price = float(entry_price)
    stop_price = float(stop_price)
    exit_price = float(exit_price)

    pnl_pct = (exit_price / entry_price) - 1.0
    duration_minutes = (exit_time - entry_time).total_seconds() / 60.0
    risk_per_share = max(entry_price - stop_price, 0.0)

    if risk_per_share > 0:
        r_multiple_achieved = (exit_price - entry_price) / risk_per_share
    else:
        r_multiple_achieved = 0.0

    return OrbExecutionResult(
        status="CLOSED",
        exit_time=exit_time.strftime("%Y-%m-%d %H:%M:%S"),
        exit_price=exit_price,
        exit_reason=exit_reason,
        pnl_pct=pnl_pct,
        trade_duration_minutes=duration_minutes,
        risk_per_share=risk_per_share,
        r_multiple_achieved=r_multiple_achieved,
    )


def find_timestamp_column(bars: pd.DataFrame) -> str:
    candidates = [
        "datetime",
        "timestamp",
        "date_time",
        "Datetime",
        "Timestamp",
        "time",
        "Time",
    ]

    for column in candidates:
        if column in bars.columns:
            return column

    raise ValueError(
        "Could not find timestamp column in bars. "
        "Expected one of: datetime, timestamp, date_time, time."
    )


def normalise_bars(
    bars: pd.DataFrame,
    timestamp_col: Optional[str] = None,
) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame()

    bars = bars.copy()

    if timestamp_col is None:
        timestamp_col = find_timestamp_column(bars)

    required_columns = [timestamp_col, "high", "low", "close"]

    for column in required_columns:
        if column not in bars.columns:
            raise ValueError(f"Bars missing required column: {column}")

    bars["bar_time"] = pd.to_datetime(
        bars[timestamp_col],
        errors="coerce",
    )

    for column in ["high", "low", "close"]:
        bars[column] = pd.to_numeric(
            bars[column],
            errors="coerce",
        )

    bars = bars.dropna(
        subset=[
            "bar_time",
            "high",
            "low",
            "close",
        ]
    )

    bars = bars.sort_values("bar_time").reset_index(drop=True)

    return bars


def execute_long_orb_trade(
    entry_time,
    entry_price: float,
    stop_price: float,
    target_price: float,
    bars: pd.DataFrame,
    timestamp_col: Optional[str] = None,
    close_if_no_hit: bool = True,
    same_bar_priority: str = "STOP",
    eod_exit_time: Optional[str] = DEFAULT_EOD_EXIT_TIME,
) -> OrbExecutionResult:
    """
    Shared ORB long-trade execution logic.

    Rules:
    - Only bars strictly after entry_time are evaluated.
    - If eod_exit_time is set, only bars up to that clock time are evaluated.
    - Stop hit if bar low <= stop_price.
    - Target hit if bar high >= target_price.
    - If both stop and target hit in the same bar, default is conservative STOP first.
    - If no stop/target hit and close_if_no_hit=True, exit at last available bar close.
    - If no stop/target hit and close_if_no_hit=False, trade remains OPEN.
    """

    entry_time = pd.to_datetime(entry_time)
    entry_price = float(entry_price)
    stop_price = float(stop_price)
    target_price = float(target_price)

    normalised = normalise_bars(
        bars=bars,
        timestamp_col=timestamp_col,
    )

    if normalised.empty:
        return empty_open_result(
            entry_price=entry_price,
            stop_price=stop_price,
            reason=OPEN_NO_BARS,
        )

    trade_bars = normalised[
        normalised["bar_time"] > entry_time
    ].copy()

    if eod_exit_time is not None:
        eod_cutoff = pd.to_datetime(
            f"{entry_time.date()} {eod_exit_time}",
            errors="coerce",
        )

        if not pd.isna(eod_cutoff):
            trade_bars = trade_bars[
                trade_bars["bar_time"] <= eod_cutoff
            ].copy()

    if trade_bars.empty:
        return empty_open_result(
            entry_price=entry_price,
            stop_price=stop_price,
            reason=OPEN_NO_BARS,
        )

    same_bar_priority = same_bar_priority.upper().strip()

    for _, bar in trade_bars.iterrows():
        bar_time = bar["bar_time"]
        high = float(bar["high"])
        low = float(bar["low"])

        stop_hit = low <= stop_price
        target_hit = high >= target_price

        if stop_hit and target_hit:
            if same_bar_priority == "TARGET":
                return closed_result(
                    entry_time=entry_time,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    exit_time=bar_time,
                    exit_price=target_price,
                    exit_reason=TARGET_HIT,
                )

            return closed_result(
                entry_time=entry_time,
                entry_price=entry_price,
                stop_price=stop_price,
                exit_time=bar_time,
                exit_price=stop_price,
                exit_reason=STOP_HIT,
            )

        if stop_hit:
            return closed_result(
                entry_time=entry_time,
                entry_price=entry_price,
                stop_price=stop_price,
                exit_time=bar_time,
                exit_price=stop_price,
                exit_reason=STOP_HIT,
            )

        if target_hit:
            return closed_result(
                entry_time=entry_time,
                entry_price=entry_price,
                stop_price=stop_price,
                exit_time=bar_time,
                exit_price=target_price,
                exit_reason=TARGET_HIT,
            )

    if not close_if_no_hit:
        return empty_open_result(
            entry_price=entry_price,
            stop_price=stop_price,
            reason=OPEN_NO_EXIT,
        )

    last_bar = trade_bars.tail(1).iloc[0]

    return closed_result(
        entry_time=entry_time,
        entry_price=entry_price,
        stop_price=stop_price,
        exit_time=last_bar["bar_time"],
        exit_price=float(last_bar["close"]),
        exit_reason=CLOSED_EOD,
    )