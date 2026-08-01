from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from RegimeTrading.core.nasdaq_config import (
    INSTRUMENT_BY_TICKER,
    NASDAQ_FORWARD_DB,
    NASDAQ_YAHOO_DECISION_COMPARISON_CSV,
    NASDAQ_YAHOO_DECISION_SUMMARY_CSV,
    PRIMARY_BAR_MODE,
)
from RegimeTrading.core.nasdaq_database import connect_database, initialize_database
from RegimeTrading.core.paths import INTRADAY_DB
from RegimeTrading.scripts import research_regime_aware_gap_recovery as gap


COMPARISON_METHOD = "SHARED_YAHOO_PREVIOUS_CLOSE_AND_EARLY_REGIME"
COMPARISON_STATUS = "SHADOW_DATA_QUALITY_ONLY_NOT_STRATEGY_INPUT"
YAHOO_SOURCE = "YAHOO_LOCAL_INTRADAY"
NASDAQ_SOURCE = "NASDAQ_PRIMARY_XSTO_CLOB"

DETAIL_COLUMNS = [
    "strategy_id",
    "comparison_status",
    "comparison_method",
    "date",
    "ticker",
    "sector_group",
    "common_cutoff",
    "shared_early_market_regime",
    "shared_favorable_regime",
    "shared_previous_close",
    "yahoo_first_bar",
    "nasdaq_first_bar",
    "yahoo_last_bar",
    "nasdaq_last_bar",
    "opening_range_ready_both",
    "regime_ready_both",
    "entry_window_complete_both",
    "eod_complete_both",
    "setup_comparable",
    "trigger_state_comparable",
    "trigger_final_comparable",
    "outcome_comparable",
    "yahoo_candidate_status",
    "nasdaq_candidate_status",
    "yahoo_decision_class",
    "nasdaq_decision_class",
    "current_decision_class_match",
    "yahoo_invalid_reason",
    "nasdaq_invalid_reason",
    "invalid_reason_match",
    "yahoo_gap",
    "nasdaq_gap",
    "gap_diff_bps",
    "gap_band_match",
    "yahoo_open_price",
    "nasdaq_open_price",
    "open_price_diff_bps",
    "yahoo_entry_trigger",
    "nasdaq_entry_trigger",
    "entry_trigger_diff_bps",
    "entry_trigger_within_1bp",
    "yahoo_stop_price",
    "nasdaq_stop_price",
    "stop_price_diff_bps",
    "stop_price_within_1bp",
    "yahoo_target_price",
    "nasdaq_target_price",
    "target_price_diff_bps",
    "target_price_within_1bp",
    "yahoo_would_cross_entry",
    "nasdaq_would_cross_entry",
    "current_trigger_state_match",
    "final_trigger_decision_match",
    "yahoo_theoretical_entry_time",
    "nasdaq_theoretical_entry_time",
    "entry_time_diff_minutes",
    "entry_time_within_5m",
    "yahoo_exit_reason",
    "nasdaq_exit_reason",
    "exit_reason_match",
    "yahoo_exit_price",
    "nasdaq_exit_price",
    "exit_price_diff_bps",
    "yahoo_pnl_pct",
    "nasdaq_pnl_pct",
    "pnl_diff_bps",
    "overall_current_decision_match",
    "generated_at_utc",
]

SUMMARY_COLUMNS = [
    "strategy_id",
    "comparison_status",
    "comparison_method",
    "comparison_group",
    "ticker",
    "sector_group",
    "ticker_day_rows",
    "setup_comparable_rows",
    "current_decision_class_match_rate",
    "invalid_reason_match_rate",
    "entry_trigger_within_1bp_rate",
    "stop_price_within_1bp_rate",
    "trigger_state_comparable_rows",
    "current_trigger_state_match_rate",
    "trigger_final_comparable_rows",
    "final_trigger_decision_match_rate",
    "both_triggered_rows",
    "entry_time_within_5m_rate",
    "outcome_comparable_rows",
    "exit_reason_match_rate",
    "overall_current_decision_match_rate",
    "first_comparison_date",
    "last_comparison_date",
    "generated_at_utc",
]


def now_utc_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_datetime(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce")


def _bool_value(value) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _diff_bps(left, right) -> float:
    try:
        left_value = float(left)
        right_value = float(right)
    except (TypeError, ValueError):
        return np.nan
    if not np.isfinite(left_value) or not np.isfinite(right_value) or right_value == 0:
        return np.nan
    return (left_value / right_value - 1.0) * 10000.0


def _clock_at_least(timestamp_value, clock: str) -> bool:
    if timestamp_value is None or pd.isna(timestamp_value):
        return False
    return pd.Timestamp(timestamp_value).strftime("%H:%M") >= clock


def _clock_at_most(timestamp_value, clock: str) -> bool:
    if timestamp_value is None or pd.isna(timestamp_value):
        return False
    return pd.Timestamp(timestamp_value).strftime("%H:%M") <= clock


def _decision_class(status) -> str:
    text = "" if status is None or pd.isna(status) else str(status)
    if text == "INVALID":
        return "INVALID"
    if text.startswith("WAITING_"):
        return "WAITING"
    if text in {"MONITORING", "NOT_TRIGGERED"}:
        return "VALID_NOT_TRIGGERED"
    if text == "TRIGGERED_OPEN":
        return "TRIGGERED_OPEN"
    if text == "TRIGGERED_CLOSED":
        return "TRIGGERED_CLOSED"
    return "MISSING"


def _gap_band(gap_value) -> str:
    try:
        value = float(gap_value)
    except (TypeError, ValueError):
        return "MISSING"
    if not np.isfinite(value):
        return "MISSING"
    if value >= 0:
        return "NOT_NEGATIVE"
    if value < gap.MIN_GAP:
        return "TOO_LARGE"
    if value > gap.MAX_GAP:
        return "TOO_SMALL"
    return "IN_RANGE"


def load_nasdaq_prices() -> pd.DataFrame:
    initialize_database(NASDAQ_FORWARD_DB)
    with closing(connect_database(NASDAQ_FORWARD_DB)) as connection:
        prices = pd.read_sql_query(
            """
            SELECT ticker, datetime, open, high, low, close, volume
            FROM nasdaq_5m_bars
            WHERE source_mode = ?
            ORDER BY ticker, datetime
            """,
            connection,
            params=[PRIMARY_BAR_MODE],
        )
    if prices.empty:
        return prices
    prices["datetime"] = _to_datetime(prices["datetime"])
    for column in ["open", "high", "low", "close", "volume"]:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
    prices = prices.dropna(subset=["ticker", "datetime", "high", "low", "close"])
    prices["open"] = prices["open"].where(prices["open"].notna(), prices["close"])
    prices["ticker"] = prices["ticker"].astype(str).str.strip()
    prices["date"] = prices["datetime"].dt.date
    return prices.sort_values(["ticker", "datetime"]).reset_index(drop=True)


def common_cutoffs_by_date(
    yahoo: pd.DataFrame,
    nasdaq: pd.DataFrame,
) -> dict:
    yahoo_selected = yahoo[yahoo["ticker"].isin(gap.GAP_RECOVERY_TICKERS)]
    yahoo_max = yahoo_selected.groupby("date")["datetime"].max()
    nasdaq_max = nasdaq.groupby("date")["datetime"].max()
    common_dates = yahoo_max.index.intersection(nasdaq_max.index)
    return {
        session_date: min(yahoo_max.loc[session_date], nasdaq_max.loc[session_date])
        for session_date in common_dates
    }


def trim_to_common_cutoff(
    prices: pd.DataFrame,
    cutoffs: dict,
) -> pd.DataFrame:
    if prices.empty or not cutoffs:
        return prices.iloc[0:0].copy()
    kept = []
    for session_date, cutoff in cutoffs.items():
        day = prices[(prices["date"] == session_date) & (prices["datetime"] <= cutoff)]
        if not day.empty:
            kept.append(day)
    if not kept:
        return prices.iloc[0:0].copy()
    return pd.concat(kept, ignore_index=True).sort_values(["ticker", "datetime"])


def provider_session_coverage(prices: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(columns=["date", "ticker"])
    grouped = (
        prices.groupby(["date", "ticker"], as_index=False)
        .agg(
            first_bar=("datetime", "min"),
            last_bar=("datetime", "max"),
            bar_count=("datetime", "nunique"),
        )
    )
    return grouped.rename(
        columns={
            "first_bar": f"{prefix}_first_bar",
            "last_bar": f"{prefix}_last_bar",
            "bar_count": f"{prefix}_bar_count",
        }
    )


def shared_nasdaq_reference(
    nasdaq_prices: pd.DataFrame,
    yahoo_reference: pd.DataFrame,
) -> pd.DataFrame:
    nasdaq_reference = gap.build_daily_reference(nasdaq_prices)
    shared_close = yahoo_reference[["ticker", "date", "previous_close"]].rename(
        columns={"previous_close": "shared_previous_close"}
    )
    result = nasdaq_reference.drop(columns=["previous_close"], errors="ignore").merge(
        shared_close,
        on=["ticker", "date"],
        how="left",
    )
    return result.rename(columns={"shared_previous_close": "previous_close"})


def prepare_candidates_and_trades() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    if not INTRADAY_DB.exists():
        raise FileNotFoundError(
            f"Yahoo/local intraday database not found: {INTRADAY_DB}. "
            "Run sync_intraday_database first."
        )

    nasdaq_all = load_nasdaq_prices()
    if nasdaq_all.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}

    yahoo_all = gap.load_intraday_prices(INTRADAY_DB)
    if yahoo_all.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}

    # Keep the previous Yahoo session available for the shared previous-close anchor.
    first_nasdaq_date = nasdaq_all["date"].min()
    date_values = sorted(yahoo_all["date"].unique())
    earlier_dates = [value for value in date_values if value < first_nasdaq_date]
    start_date = earlier_dates[-1] if earlier_dates else first_nasdaq_date
    yahoo_window = yahoo_all[yahoo_all["date"] >= start_date].copy()

    cutoffs = common_cutoffs_by_date(yahoo_window, nasdaq_all)
    yahoo_trimmed = trim_to_common_cutoff(yahoo_window, cutoffs)
    nasdaq_trimmed = trim_to_common_cutoff(nasdaq_all, cutoffs)

    yahoo_reference_full = gap.build_daily_reference(yahoo_window)
    yahoo_reference_trimmed = gap.build_daily_reference(yahoo_trimmed)

    # Preserve the true previous close from the untrimmed Yahoo window.
    prior_close = yahoo_reference_full[["ticker", "date", "previous_close"]]
    yahoo_reference = yahoo_reference_trimmed.drop(
        columns=["previous_close"], errors="ignore"
    ).merge(prior_close, on=["ticker", "date"], how="left")

    shared_regime = gap.calculate_early_market_regime(
        yahoo_trimmed,
        yahoo_reference,
    )
    nasdaq_reference = shared_nasdaq_reference(nasdaq_trimmed, yahoo_reference)

    yahoo_candidates, yahoo_trades = gap.build_candidates_and_trades(
        yahoo_trimmed,
        yahoo_reference,
        shared_regime,
    )
    nasdaq_candidates, nasdaq_trades = gap.build_candidates_and_trades(
        nasdaq_trimmed,
        nasdaq_reference,
        shared_regime,
    )

    common_date_strings = {value.isoformat() for value in cutoffs}
    yahoo_candidates = yahoo_candidates[
        yahoo_candidates["date"].astype(str).isin(common_date_strings)
        & yahoo_candidates["ticker"].isin(gap.GAP_RECOVERY_TICKERS)
    ].copy()
    nasdaq_candidates = nasdaq_candidates[
        nasdaq_candidates["date"].astype(str).isin(common_date_strings)
        & nasdaq_candidates["ticker"].isin(gap.GAP_RECOVERY_TICKERS)
    ].copy()
    yahoo_trades = yahoo_trades[
        yahoo_trades["date"].astype(str).isin(common_date_strings)
    ].copy()
    nasdaq_trades = nasdaq_trades[
        nasdaq_trades["date"].astype(str).isin(common_date_strings)
    ].copy()

    coverage = provider_session_coverage(yahoo_trimmed, "yahoo").merge(
        provider_session_coverage(nasdaq_trimmed, "nasdaq"),
        on=["date", "ticker"],
        how="outer",
    )
    coverage["date"] = coverage["date"].astype(str)
    cutoff_frame = pd.DataFrame(
        [
            {"date": date_value.isoformat(), "common_cutoff": cutoff}
            for date_value, cutoff in cutoffs.items()
        ]
    )
    coverage = coverage.merge(cutoff_frame, on="date", how="left")
    return (
        yahoo_candidates,
        nasdaq_candidates,
        pd.concat(
            [
                yahoo_trades.assign(provider="yahoo"),
                nasdaq_trades.assign(provider="nasdaq"),
            ],
            ignore_index=True,
        ),
        {"coverage": coverage, "regime": shared_regime},
    )


def build_detail() -> pd.DataFrame:
    yahoo_candidates, nasdaq_candidates, trades, context = prepare_candidates_and_trades()
    if yahoo_candidates.empty and nasdaq_candidates.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    candidate_fields = [
        "date",
        "ticker",
        "candidate_status",
        "invalid_reason",
        "gap",
        "previous_close",
        "open_price",
        "entry_trigger",
        "stop_price",
        "target_price",
        "early_market_regime",
        "favorable_regime",
        "would_cross_entry_anyway",
        "theoretical_entry_time",
    ]
    yahoo = yahoo_candidates[candidate_fields].rename(
        columns={column: f"yahoo_{column}" for column in candidate_fields if column not in {"date", "ticker"}}
    )
    nasdaq = nasdaq_candidates[candidate_fields].rename(
        columns={column: f"nasdaq_{column}" for column in candidate_fields if column not in {"date", "ticker"}}
    )
    detail = yahoo.merge(nasdaq, on=["date", "ticker"], how="outer")
    detail = detail.merge(context["coverage"], on=["date", "ticker"], how="left")

    trade_fields = ["date", "ticker", "exit_reason", "exit_price", "pnl_pct"]
    yahoo_trades = trades[trades["provider"].eq("yahoo")][trade_fields].rename(
        columns={column: f"yahoo_{column}" for column in trade_fields if column not in {"date", "ticker"}}
    )
    nasdaq_trades = trades[trades["provider"].eq("nasdaq")][trade_fields].rename(
        columns={column: f"nasdaq_{column}" for column in trade_fields if column not in {"date", "ticker"}}
    )
    detail = detail.merge(yahoo_trades, on=["date", "ticker"], how="left")
    detail = detail.merge(nasdaq_trades, on=["date", "ticker"], how="left")

    detail["strategy_id"] = gap.STRATEGY_ID
    detail["comparison_status"] = COMPARISON_STATUS
    detail["comparison_method"] = COMPARISON_METHOD
    detail["sector_group"] = detail["ticker"].map(
        lambda ticker: INSTRUMENT_BY_TICKER.get(ticker).sector_group
        if ticker in INSTRUMENT_BY_TICKER
        else ""
    )
    detail["shared_early_market_regime"] = detail["yahoo_early_market_regime"].where(
        detail["yahoo_early_market_regime"].notna(), detail["nasdaq_early_market_regime"]
    )
    detail["shared_favorable_regime"] = detail["yahoo_favorable_regime"].where(
        detail["yahoo_favorable_regime"].notna(), detail["nasdaq_favorable_regime"]
    )
    detail["shared_previous_close"] = detail["yahoo_previous_close"].where(
        detail["yahoo_previous_close"].notna(), detail["nasdaq_previous_close"]
    )

    detail["opening_range_ready_both"] = detail.apply(
        lambda row: _clock_at_most(row.get("yahoo_first_bar"), gap.OPENING_RANGE_START)
        and _clock_at_most(row.get("nasdaq_first_bar"), gap.OPENING_RANGE_START)
        and _clock_at_least(row.get("yahoo_last_bar"), gap.OPENING_RANGE_END)
        and _clock_at_least(row.get("nasdaq_last_bar"), gap.OPENING_RANGE_END),
        axis=1,
    )
    detail["regime_ready_both"] = detail.apply(
        lambda row: _clock_at_least(row.get("yahoo_last_bar"), gap.REGIME_CUTOFF_TIME)
        and _clock_at_least(row.get("nasdaq_last_bar"), gap.REGIME_CUTOFF_TIME),
        axis=1,
    )
    detail["entry_window_complete_both"] = detail.apply(
        lambda row: _clock_at_least(row.get("yahoo_last_bar"), gap.ENTRY_WINDOW_END)
        and _clock_at_least(row.get("nasdaq_last_bar"), gap.ENTRY_WINDOW_END),
        axis=1,
    )
    detail["eod_complete_both"] = detail.apply(
        lambda row: _clock_at_least(row.get("yahoo_last_bar"), gap.EOD_EXIT_TIME)
        and _clock_at_least(row.get("nasdaq_last_bar"), gap.EOD_EXIT_TIME),
        axis=1,
    )
    detail["setup_comparable"] = (
        detail["opening_range_ready_both"]
        & detail["regime_ready_both"]
        & detail["shared_previous_close"].notna()
        & detail["yahoo_candidate_status"].notna()
        & detail["nasdaq_candidate_status"].notna()
    )
    detail["yahoo_decision_class"] = detail["yahoo_candidate_status"].map(_decision_class)
    detail["nasdaq_decision_class"] = detail["nasdaq_candidate_status"].map(_decision_class)
    both_strategy_actionable = (
        detail["setup_comparable"]
        & ~detail["yahoo_decision_class"].isin(["INVALID", "WAITING", "MISSING"])
        & ~detail["nasdaq_decision_class"].isin(["INVALID", "WAITING", "MISSING"])
    )
    detail["trigger_state_comparable"] = both_strategy_actionable
    detail["trigger_final_comparable"] = (
        both_strategy_actionable & detail["entry_window_complete_both"]
    )

    detail["current_decision_class_match"] = (
        detail["setup_comparable"]
        & detail["yahoo_decision_class"].eq(detail["nasdaq_decision_class"])
    )
    detail["invalid_reason_match"] = (
        detail["setup_comparable"]
        & detail["yahoo_invalid_reason"].fillna("").eq(
            detail["nasdaq_invalid_reason"].fillna("")
        )
    )

    for output_name, yahoo_column, nasdaq_column in [
        ("gap_diff_bps", "yahoo_gap", "nasdaq_gap"),
        ("open_price_diff_bps", "yahoo_open_price", "nasdaq_open_price"),
        ("entry_trigger_diff_bps", "yahoo_entry_trigger", "nasdaq_entry_trigger"),
        ("stop_price_diff_bps", "yahoo_stop_price", "nasdaq_stop_price"),
        ("target_price_diff_bps", "yahoo_target_price", "nasdaq_target_price"),
        ("exit_price_diff_bps", "yahoo_exit_price", "nasdaq_exit_price"),
    ]:
        detail[output_name] = detail.apply(
            lambda row, left=yahoo_column, right=nasdaq_column: _diff_bps(
                row.get(left), row.get(right)
            ),
            axis=1,
        )

    detail["gap_band_match"] = detail["yahoo_gap"].map(_gap_band).eq(
        detail["nasdaq_gap"].map(_gap_band)
    )
    detail["entry_trigger_within_1bp"] = detail["entry_trigger_diff_bps"].abs().le(1.0)
    detail["stop_price_within_1bp"] = detail["stop_price_diff_bps"].abs().le(1.0)
    detail["target_price_within_1bp"] = detail["target_price_diff_bps"].abs().le(1.0)

    detail["yahoo_would_cross_entry"] = detail["yahoo_would_cross_entry_anyway"].map(_bool_value)
    detail["nasdaq_would_cross_entry"] = detail["nasdaq_would_cross_entry_anyway"].map(_bool_value)
    yahoo_strategy_triggered = detail["yahoo_candidate_status"].isin(
        ["TRIGGERED_OPEN", "TRIGGERED_CLOSED"]
    )
    nasdaq_strategy_triggered = detail["nasdaq_candidate_status"].isin(
        ["TRIGGERED_OPEN", "TRIGGERED_CLOSED"]
    )
    detail["current_trigger_state_match"] = (
        detail["trigger_state_comparable"]
        & yahoo_strategy_triggered.eq(nasdaq_strategy_triggered)
    )
    detail["final_trigger_decision_match"] = (
        detail["trigger_final_comparable"]
        & yahoo_strategy_triggered.eq(nasdaq_strategy_triggered)
    )

    yahoo_entry = pd.to_datetime(detail["yahoo_theoretical_entry_time"], errors="coerce")
    nasdaq_entry = pd.to_datetime(detail["nasdaq_theoretical_entry_time"], errors="coerce")
    detail["entry_time_diff_minutes"] = (
        (nasdaq_entry - yahoo_entry).dt.total_seconds() / 60.0
    )
    both_strategy_triggered = yahoo_strategy_triggered & nasdaq_strategy_triggered
    detail["entry_time_within_5m"] = (
        both_strategy_triggered
        & detail["entry_time_diff_minutes"].abs().le(5.0)
    )

    yahoo_closed = detail["yahoo_exit_reason"].fillna("").ne("")
    nasdaq_closed = detail["nasdaq_exit_reason"].fillna("").ne("")
    detail["outcome_comparable"] = (
        both_strategy_triggered
        & ((yahoo_closed & nasdaq_closed) | detail["eod_complete_both"])
    )
    detail["exit_reason_match"] = (
        detail["outcome_comparable"]
        & detail["yahoo_exit_reason"].fillna("").eq(
            detail["nasdaq_exit_reason"].fillna("")
        )
    )
    detail["pnl_diff_bps"] = (
        pd.to_numeric(detail["nasdaq_pnl_pct"], errors="coerce")
        - pd.to_numeric(detail["yahoo_pnl_pct"], errors="coerce")
    ) * 10000.0

    price_levels_match = (
        detail["entry_trigger_within_1bp"].fillna(False)
        & detail["stop_price_within_1bp"].fillna(False)
        & detail["target_price_within_1bp"].fillna(False)
    )
    trigger_component_match = (
        ~detail["trigger_state_comparable"] | detail["current_trigger_state_match"]
    )
    detail["overall_current_decision_match"] = (
        detail["setup_comparable"]
        & detail["current_decision_class_match"]
        & detail["invalid_reason_match"]
        & detail["gap_band_match"]
        & price_levels_match
        & trigger_component_match
        & (~detail["outcome_comparable"] | detail["exit_reason_match"])
    )
    detail["generated_at_utc"] = now_utc_text()

    rename_map = {
        "yahoo_would_cross_entry_anyway": "_drop_yahoo_cross",
        "nasdaq_would_cross_entry_anyway": "_drop_nasdaq_cross",
    }
    detail = detail.rename(columns=rename_map)
    for column in DETAIL_COLUMNS:
        if column not in detail.columns:
            detail[column] = np.nan
    return detail[DETAIL_COLUMNS].sort_values(["date", "ticker"]).reset_index(drop=True)


def _rate(frame: pd.DataFrame, column: str, mask=None) -> float:
    selected = frame if mask is None else frame[mask]
    if selected.empty:
        return np.nan
    return float(selected[column].fillna(False).astype(bool).mean())


def summary_row(frame: pd.DataFrame, group: str, ticker: str = "") -> dict:
    sector = ""
    if ticker and ticker in INSTRUMENT_BY_TICKER:
        sector = INSTRUMENT_BY_TICKER[ticker].sector_group
    setup = frame["setup_comparable"].fillna(False).astype(bool)
    trigger_state = frame["trigger_state_comparable"].fillna(False).astype(bool)
    trigger_final = frame["trigger_final_comparable"].fillna(False).astype(bool)
    both_triggered = frame["yahoo_candidate_status"].isin(
        ["TRIGGERED_OPEN", "TRIGGERED_CLOSED"]
    ) & frame["nasdaq_candidate_status"].isin(
        ["TRIGGERED_OPEN", "TRIGGERED_CLOSED"]
    )
    outcome = frame["outcome_comparable"].fillna(False).astype(bool)
    invalid_both = setup & frame["yahoo_decision_class"].eq("INVALID") & frame[
        "nasdaq_decision_class"
    ].eq("INVALID")

    return {
        "strategy_id": gap.STRATEGY_ID,
        "comparison_status": COMPARISON_STATUS,
        "comparison_method": COMPARISON_METHOD,
        "comparison_group": group,
        "ticker": ticker,
        "sector_group": sector,
        "ticker_day_rows": int(len(frame)),
        "setup_comparable_rows": int(setup.sum()),
        "current_decision_class_match_rate": _rate(
            frame, "current_decision_class_match", setup
        ),
        "invalid_reason_match_rate": _rate(frame, "invalid_reason_match", invalid_both),
        "entry_trigger_within_1bp_rate": _rate(
            frame, "entry_trigger_within_1bp", setup
        ),
        "stop_price_within_1bp_rate": _rate(frame, "stop_price_within_1bp", setup),
        "trigger_state_comparable_rows": int(trigger_state.sum()),
        "current_trigger_state_match_rate": _rate(
            frame, "current_trigger_state_match", trigger_state
        ),
        "trigger_final_comparable_rows": int(trigger_final.sum()),
        "final_trigger_decision_match_rate": _rate(
            frame, "final_trigger_decision_match", trigger_final
        ),
        "both_triggered_rows": int(both_triggered.sum()),
        "entry_time_within_5m_rate": _rate(frame, "entry_time_within_5m", both_triggered),
        "outcome_comparable_rows": int(outcome.sum()),
        "exit_reason_match_rate": _rate(frame, "exit_reason_match", outcome),
        "overall_current_decision_match_rate": _rate(
            frame, "overall_current_decision_match", setup
        ),
        "first_comparison_date": str(frame["date"].min()) if not frame.empty else "",
        "last_comparison_date": str(frame["date"].max()) if not frame.empty else "",
        "generated_at_utc": now_utc_text(),
    }


def build_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    rows = [summary_row(detail, "ALL")]
    for ticker, ticker_frame in detail.groupby("ticker", sort=True):
        rows.append(summary_row(ticker_frame, "TICKER", str(ticker)))
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def main() -> None:
    print("\n=== COMPARE GAP RECOVERY STRATEGY DECISIONS ===")
    print(f"Yahoo database  : {INTRADAY_DB}")
    print(f"Nasdaq database : {NASDAQ_FORWARD_DB}")
    print(f"Method          : {COMPARISON_METHOD}")
    print("V1 research input remains Yahoo and is not changed.")

    detail = build_detail()
    summary = build_summary(detail)
    detail.to_csv(NASDAQ_YAHOO_DECISION_COMPARISON_CSV, index=False)
    summary.to_csv(NASDAQ_YAHOO_DECISION_SUMMARY_CSV, index=False)

    print(f"Ticker-day rows       : {len(detail)}")
    if not summary.empty:
        all_row = summary[summary["comparison_group"].eq("ALL")].iloc[0]
        print(f"Setup comparable rows : {int(all_row['setup_comparable_rows'])}")
        print(f"Final trigger rows    : {int(all_row['trigger_final_comparable_rows'])}")
        print(f"Outcome rows          : {int(all_row['outcome_comparable_rows'])}")
        value = all_row["overall_current_decision_match_rate"]
        print(
            "Current decision match: "
            + (f"{float(value):.2%}" if pd.notna(value) else "not available")
        )
    print(f"Saved -> {NASDAQ_YAHOO_DECISION_COMPARISON_CSV.name}")
    print(f"Saved -> {NASDAQ_YAHOO_DECISION_SUMMARY_CSV.name}")


if __name__ == "__main__":
    main()
