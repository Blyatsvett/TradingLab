from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from RegimeTrading.core.paths import DATA_DIR, INTRADAY_DB, legacy_output_path
from RegimeTrading.core.stage_registry import resolve_stage_output_dir


EXPERIMENT_ID = "STEP9S_HISTORICAL_CONTINGENCY_REPLAY_V1"
RESEARCH_STATUS = "RESEARCH_ONLY_HISTORICAL_REPLAY_NOT_ROUTER_ACTIVE"
CODE_VERSION = "STEP9S_HISTORICAL_CONTINGENCY_REPLAY_V1_2026_07_28"
LATEST_ROUTER_SOURCE_LABEL = "09:40"
COVERAGE_TRADE_LABEL = "MANDATORY_COVERAGE_CONTROL_TRADE"
NATURAL_TRADE_LABEL = "NATURAL_TRIGGER_TRADE"

TAXONOMY_FILE = legacy_output_path("regime_daily_taxonomy.csv")
BASELINE_CANDIDATE_FILE = legacy_output_path("regime_playbook_baseline_candidates.csv")
BASELINE_TRADE_FILE = legacy_output_path("regime_playbook_baseline_trades.csv")
PRICE_DB = INTRADAY_DB

DEFAULT_OUTPUT_DIR = resolve_stage_output_dir("step9s")

ASSIGNMENT_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "regime": "RECOVERY",
        "natural_strategy_id": "STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH",
        "natural_maturity": "PROVISIONAL_NEGATIVE_TOO_FEW_TRADES",
        "natural_source_file": "regime_playbook_baseline_trades.csv",
        "natural_source_field": "playbook_id",
        "natural_source_value": "STRICT_POINT_IN_TIME_GAP_RECOVERY_V2_RESEARCH",
        "mandatory_control_id": "RECOVERY_MANDATORY_0945_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_IDEA",
    },
    {
        "regime": "TREND_UP",
        "natural_strategy_id": "L3_TU_ALIGNED_DELAYED_REVERSAL_1R_V1",
        "natural_maturity": "FROZEN_PROSPECTIVE_CHALLENGER",
        "natural_source_file": "step9o_trades.csv",
        "natural_source_field": "contract_id",
        "natural_source_value": "O_TU_ALIGNED_DELAYED_REVERSAL_ALL_V1",
        "mandatory_control_id": "TREND_UP_MANDATORY_0945_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_IDEA",
    },
    {
        "regime": "TREND_DOWN",
        "natural_strategy_id": "TREND_DOWN_MOMENTUM_CONTINUATION_V1_RESEARCH",
        "natural_maturity": "NEGATIVE_DIAGNOSTIC_CONTROL_NO_BETTER_STRATEGY",
        "natural_source_file": "regime_playbook_baseline_trades.csv",
        "natural_source_field": "playbook_id",
        "natural_source_value": "TREND_DOWN_MOMENTUM_CONTINUATION_V1_RESEARCH",
        "mandatory_control_id": "TREND_DOWN_MANDATORY_0945_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_IDEA",
    },
    {
        "regime": "RANGE_LOW_VOL",
        "natural_strategy_id": "L_RLV_GROUP_ALIGNED_LAGGARD_DELAYED_REVERSAL_V1",
        "natural_maturity": "FROZEN_SELECTED_PROSPECTIVE_STRATEGY",
        "natural_source_file": "step9j_v2_challenger_trades.csv",
        "natural_source_field": "contract_id",
        "natural_source_value": "J_RLV_CONTRARIAN_LAGGARD_DELAYED_REVERSAL_V1",
        "mandatory_control_id": "RANGE_LOW_VOL_MANDATORY_0945_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_IDEA",
    },
    {
        "regime": "HIGH_VOL_REVERSAL",
        "natural_strategy_id": "L2_HVR_DIRECTIONAL_BREAKOUT_2R_V1",
        "natural_maturity": "FROZEN_PROSPECTIVE_CHALLENGER",
        "natural_source_file": "step9m_trades.csv",
        "natural_source_field": "contract_id",
        "natural_source_value": "M_HVR_DIRECTIONAL_BREAKOUT_2R_V1",
        "mandatory_control_id": "HIGH_VOL_REVERSAL_MANDATORY_0945_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_IDEA",
    },
    {
        "regime": "HIGH_DISPERSION",
        "natural_strategy_id": "L_HD_CONTRARIAN_LAGGARD_MIDPOINT_CATCHUP_V1",
        "natural_maturity": "FROZEN_PROSPECTIVE_CHALLENGER",
        "natural_source_file": "step9k_trades.csv",
        "natural_source_field": "contract_id",
        "natural_source_value": "K_HD_CONTRARIAN_LAGGARD_CATCHUP_V1",
        "mandatory_control_id": "HIGH_DISPERSION_MANDATORY_PAIR_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_PAIR",
    },
    {
        "regime": "VOLATILITY_EXPANSION",
        "natural_strategy_id": "L_VE_ALIGNED_CLOSE_CONFIRMED_ORB_V1",
        "natural_maturity": "FROZEN_SELECTED_PROSPECTIVE_STRATEGY",
        "natural_source_file": "step9j_v2_challenger_trades.csv",
        "natural_source_field": "contract_id",
        "natural_source_value": "J_VE_ALIGNED_CLOSE_ORB_V1",
        "mandatory_control_id": "VOLATILITY_EXPANSION_MANDATORY_0945_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_IDEA",
    },
    {
        "regime": "DEFENSIVE_MIXED",
        "natural_strategy_id": "PAIR_SPREAD_CONVERGENCE_V1",
        "natural_maturity": "PROMISING_PROVISIONAL_TOO_FEW_SESSIONS",
        "natural_source_file": "regime_challenger_trades.csv",
        "natural_source_field": "challenger_id",
        "natural_source_value": "PAIR_SPREAD_CONVERGENCE_V1",
        "mandatory_control_id": "DEFENSIVE_MIXED_MANDATORY_PAIR_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_PAIR",
    },
    {
        "regime": "DATA_LIMITED_DEFENSIVE",
        "natural_strategy_id": "DATA_LIMITED_STATIC_HEDGE_PROXY_V1_RESEARCH",
        "natural_maturity": "DETERMINISTIC_DIAGNOSTIC_CONTROL_NOT_ECONOMICALLY_VALIDATED",
        "natural_source_file": "regime_playbook_baseline_trades.csv",
        "natural_source_field": "playbook_id",
        "natural_source_value": "DATA_LIMITED_STATIC_HEDGE_PROXY_V1_RESEARCH",
        "mandatory_control_id": "DATA_LIMITED_DEFENSIVE_MANDATORY_HEDGE_CONTROL_V1",
        "mandatory_control_source": "STEP9A_SELECTED_PAIR",
    },
)
REGISTRY_BY_REGIME = {row["regime"]: dict(row) for row in ASSIGNMENT_REGISTRY}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def _num(value: Any, default: float = np.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def _load_prices_read_only(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        prices = pd.read_sql_query(
            "SELECT datetime, open, high, low, close, volume, ticker FROM intraday_prices",
            connection,
        )
    prices["datetime"] = pd.to_datetime(prices["datetime"], errors="raise")
    prices["date"] = prices["datetime"].dt.strftime("%Y-%m-%d")
    prices["clock"] = prices["datetime"].dt.strftime("%H:%M")
    return prices.sort_values(["date", "ticker", "datetime"]).reset_index(drop=True)


def _first_bar(prices: pd.DataFrame, date: str, ticker: str, start: str = "09:45", end: str = "10:00") -> pd.Series | None:
    rows = prices[
        prices["date"].eq(date)
        & prices["ticker"].eq(ticker)
        & prices["clock"].ge(start)
        & prices["clock"].le(end)
    ].sort_values("datetime")
    return None if rows.empty else rows.iloc[0]


def _trade_bars(prices: pd.DataFrame, date: str, ticker: str, entry_time: pd.Timestamp, exit_cutoff: str) -> pd.DataFrame:
    return prices[
        prices["date"].eq(date)
        & prices["ticker"].eq(ticker)
        & prices["datetime"].ge(entry_time)
        & prices["clock"].le(exit_cutoff)
    ].sort_values("datetime")


def _execute_single(
    prices: pd.DataFrame,
    date: str,
    ticker: str,
    side: str,
    entry_time: pd.Timestamp,
    entry_price: float,
    stop_price: float,
    target_price: float,
    exit_cutoff: str,
) -> dict[str, Any]:
    bars = _trade_bars(prices, date, ticker, entry_time, exit_cutoff)
    if bars.empty:
        raise RuntimeError(f"No executable bars for {date} {ticker}")
    side = side.upper()
    for _, bar in bars.iterrows():
        high = _num(bar["high"])
        low = _num(bar["low"])
        if side == "LONG":
            stop_hit = low <= stop_price
            target_hit = high >= target_price
        else:
            stop_hit = high >= stop_price
            target_hit = low <= target_price
        if stop_hit:
            exit_price = stop_price
            reason = "STOP_HIT"
        elif target_hit:
            exit_price = target_price
            reason = "TARGET_HIT"
        else:
            continue
        exit_time = pd.Timestamp(bar["datetime"])
        gross_return = exit_price / entry_price - 1.0 if side == "LONG" else entry_price / exit_price - 1.0
        return {
            "exit_time": exit_time,
            "exit_price": float(exit_price),
            "exit_reason": reason,
            "gross_return": float(gross_return),
            "trade_duration_minutes": (exit_time - entry_time).total_seconds() / 60.0,
        }
    last = bars.iloc[-1]
    exit_time = pd.Timestamp(last["datetime"])
    exit_price = _num(last["close"])
    gross_return = exit_price / entry_price - 1.0 if side == "LONG" else entry_price / exit_price - 1.0
    return {
        "exit_time": exit_time,
        "exit_price": float(exit_price),
        "exit_reason": "TIME_EXIT",
        "gross_return": float(gross_return),
        "trade_duration_minutes": (exit_time - entry_time).total_seconds() / 60.0,
    }


def _normalize_natural_trade(row: pd.Series, registry: dict[str, Any]) -> dict[str, Any]:
    net_pnl = _num(row.get("risk_capped_net_pnl_sek"), _num(row.get("net_pnl_sek")))
    notional = _num(row.get("risk_capped_notional_sek"), _num(row.get("notional_sek")))
    cost = _num(row.get("risk_capped_cost_sek"), _num(row.get("cost_sek")))
    return {
        "experiment_id": EXPERIMENT_ID,
        "trade_book": "NATURAL_STRATEGY_BOOK",
        "trade_label": NATURAL_TRADE_LABEL,
        "date": str(row["date"]),
        "primary_regime": registry["regime"],
        "assigned_strategy_id": registry["natural_strategy_id"],
        "source_strategy_id": str(row.get(registry["natural_source_field"], registry["natural_source_value"])),
        "source_file": registry["natural_source_file"],
        "trade_id": f"NATURAL|{registry['natural_strategy_id']}|{row.get('trade_id', row.name)}",
        "idea_type": str(row.get("idea_type", "SINGLE")),
        "direction": str(row.get("direction", "")),
        "ticker": row.get("ticker", ""),
        "paired_ticker": row.get("paired_ticker", ""),
        "long_ticker": row.get("long_ticker", ""),
        "short_ticker": row.get("short_ticker", ""),
        "entry_time": row.get("entry_time", ""),
        "entry_price": row.get("entry_price", np.nan),
        "stop_price": row.get("stop_price", np.nan),
        "target_price": row.get("target_price", np.nan),
        "pair_entry_long_price": row.get("pair_entry_long_price", np.nan),
        "pair_entry_short_price": row.get("pair_entry_short_price", np.nan),
        "pair_stop_return": row.get("pair_stop_return", np.nan),
        "pair_target_return": row.get("pair_target_return", np.nan),
        "exit_time": row.get("exit_time", ""),
        "exit_price": row.get("exit_price", np.nan),
        "pair_exit_long_price": row.get("pair_exit_long_price", np.nan),
        "pair_exit_short_price": row.get("pair_exit_short_price", np.nan),
        "exit_reason": row.get("exit_reason", ""),
        "gross_return": _num(row.get("gross_return")),
        "notional_sek": notional,
        "cost_sek": cost,
        "net_pnl_sek": net_pnl,
        "point_in_time_pass": bool(row.get("point_in_time_pass", True)),
        "execution_invariant_pass": bool(row.get("execution_invariant_pass", True)),
        "router_active": False,
        "order_sent": False,
    }


def build_natural_trade_book(data_dir: Path, taxonomy_dates: set[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cache: dict[str, pd.DataFrame] = {}
    for registry in ASSIGNMENT_REGISTRY:
        filename = registry["natural_source_file"]
        if filename not in cache:
            source_path = (
                legacy_output_path(filename)
                if data_dir.resolve() == DATA_DIR.resolve()
                else data_dir / filename
            )
            cache[filename] = _read_csv(source_path)
        source = cache[filename]
        field = registry["natural_source_field"]
        value = registry["natural_source_value"]
        selected = source[source[field].astype(str).eq(value)].copy()
        if "primary_regime" in selected.columns:
            selected = selected[selected["primary_regime"].astype(str).eq(registry["regime"])]
        selected = selected[selected["date"].astype(str).isin(taxonomy_dates)]
        for _, row in selected.iterrows():
            rows.append(_normalize_natural_trade(row, registry))
    return pd.DataFrame(rows)


def _single_control_levels(candidate: pd.Series, taxonomy_row: pd.Series, actual_entry: float) -> tuple[str, float, float, str]:
    regime = str(candidate["primary_regime"])
    side = str(candidate.get("direction", "")).upper()
    early_low = _num(candidate.get("early_low"))
    early_high = _num(candidate.get("early_high"))
    midpoint = _num(candidate.get("early_midpoint"))
    early_open = _num(candidate.get("early_open"))
    width = early_high - early_low
    exit_cutoff = "16:30"

    if side == "TWO_SIDED":
        bias = str(taxonomy_row.get("direction_bias", "NEUTRAL")).upper()
        side = "LONG" if bias == "UP" else "SHORT" if bias == "DOWN" else ("LONG" if _num(candidate.get("cutoff_return_from_open")) >= 0 else "SHORT")

    if regime == "RECOVERY":
        stop = _num(candidate.get("stop_price"))
        target = _num(candidate.get("target_price"))
        if not stop < actual_entry < target:
            risk = max(actual_entry - stop if np.isfinite(stop) else 0.0, actual_entry * 0.003)
            stop = actual_entry - risk
            target = actual_entry + risk
    elif regime == "TREND_UP":
        side = "LONG"
        stop = early_low
        if stop >= actual_entry:
            stop = actual_entry - max(width, actual_entry * 0.003)
        target = actual_entry + (actual_entry - stop)
    elif regime == "TREND_DOWN":
        side = "SHORT"
        stop = early_high
        if stop <= actual_entry:
            stop = actual_entry + max(width, actual_entry * 0.003)
        target = actual_entry - (stop - actual_entry)
    elif regime == "RANGE_LOW_VOL":
        exit_cutoff = "15:30"
        if side == "SHORT":
            stop = early_high + width
            target = midpoint
            if not target < actual_entry < stop:
                stop = actual_entry + max(width, actual_entry * 0.003)
                target = actual_entry - (stop - actual_entry)
        else:
            side = "LONG"
            stop = early_low - width
            target = midpoint
            if not stop < actual_entry < target:
                stop = actual_entry - max(width, actual_entry * 0.003)
                target = actual_entry + (actual_entry - stop)
    elif regime == "HIGH_VOL_REVERSAL":
        stop = _num(candidate.get("stop_price"), early_low if side == "LONG" else early_high)
        if side == "LONG":
            if stop >= actual_entry:
                stop = actual_entry - max(width, actual_entry * 0.003)
            risk = actual_entry - stop
            target = min(early_open, actual_entry + risk) if early_open > actual_entry else actual_entry + risk
        else:
            side = "SHORT"
            if stop <= actual_entry:
                stop = actual_entry + max(width, actual_entry * 0.003)
            risk = stop - actual_entry
            target = max(early_open, actual_entry - risk) if early_open < actual_entry else actual_entry - risk
    elif regime == "VOLATILITY_EXPANSION":
        if side == "LONG":
            stop = midpoint if midpoint < actual_entry else early_low
            if stop >= actual_entry:
                stop = actual_entry - max(width, actual_entry * 0.003)
            target = actual_entry + 1.5 * (actual_entry - stop)
        else:
            side = "SHORT"
            stop = midpoint if midpoint > actual_entry else early_high
            if stop <= actual_entry:
                stop = actual_entry + max(width, actual_entry * 0.003)
            target = actual_entry - 1.5 * (stop - actual_entry)
    else:
        raise ValueError(f"Unsupported single control regime: {regime}")

    valid = (side == "LONG" and stop < actual_entry < target) or (side == "SHORT" and target < actual_entry < stop)
    if not valid or not all(np.isfinite([actual_entry, stop, target])):
        raise RuntimeError(f"Invalid forced control levels: {candidate['date']} {regime} {side} {stop} {actual_entry} {target}")
    return side, float(stop), float(target), exit_cutoff


def build_mandatory_coverage_book(
    taxonomy: pd.DataFrame,
    candidates: pd.DataFrame,
    baseline_trades: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    taxonomy_lookup = taxonomy.set_index("date")
    selected = candidates[candidates["selected_for_simulation"].fillna(False).astype(bool)].copy()
    selected["selection_rank"] = pd.to_numeric(selected["selection_rank"], errors="coerce")

    for date, taxonomy_row in taxonomy.sort_values("date").set_index("date").iterrows():
        regime = str(taxonomy_row["primary_regime"])
        registry = REGISTRY_BY_REGIME.get(regime)
        if registry is None:
            raise RuntimeError(f"Unknown recognized regime: {regime}")
        day_candidates = selected[selected["date"].astype(str).eq(str(date))].sort_values(["selection_rank", "ticker"], na_position="last")
        if day_candidates.empty:
            raise RuntimeError(f"No selected Step 9A coverage candidate for {date} {regime}")
        candidate = day_candidates.iloc[0]
        if str(candidate.get("max_router_source_label", "")) > LATEST_ROUTER_SOURCE_LABEL:
            raise RuntimeError(f"Post-cutoff candidate source for {date} {regime}")
        if not bool(candidate.get("point_in_time_pass", True)):
            raise RuntimeError(f"Point-in-time failure for {date} {regime}")

        if str(candidate.get("idea_type")) == "PAIR":
            trade = baseline_trades[
                baseline_trades["date"].astype(str).eq(str(date))
                & baseline_trades["idea_id"].astype(str).eq(str(candidate["idea_id"]))
            ]
            if len(trade) != 1:
                raise RuntimeError(f"Expected one baseline pair trade for {date} {regime}; found {len(trade)}")
            source = trade.iloc[0]
            rows.append({
                "experiment_id": EXPERIMENT_ID,
                "trade_book": "MANDATORY_COVERAGE_CONTROL_BOOK",
                "trade_label": COVERAGE_TRADE_LABEL,
                "date": str(date),
                "primary_regime": regime,
                "assigned_strategy_id": registry["natural_strategy_id"],
                "coverage_control_id": registry["mandatory_control_id"],
                "source_strategy_id": str(candidate["playbook_id"]),
                "source_candidate_id": str(candidate["idea_id"]),
                "trade_id": f"COVERAGE|{date}|{regime}|PAIR1",
                "idea_type": "PAIR",
                "direction": "LONG_SHORT",
                "ticker": source.get("ticker", ""),
                "paired_ticker": source.get("paired_ticker", ""),
                "long_ticker": source.get("long_ticker", ""),
                "short_ticker": source.get("short_ticker", ""),
                "entry_time": source.get("entry_time", ""),
                "entry_price": np.nan,
                "stop_price": np.nan,
                "target_price": np.nan,
                "pair_entry_long_price": source.get("pair_entry_long_price", np.nan),
                "pair_entry_short_price": source.get("pair_entry_short_price", np.nan),
                "pair_stop_return": source.get("pair_stop_return", np.nan),
                "pair_target_return": source.get("pair_target_return", np.nan),
                "exit_time": source.get("exit_time", ""),
                "exit_price": np.nan,
                "pair_exit_long_price": source.get("pair_exit_long_price", np.nan),
                "pair_exit_short_price": source.get("pair_exit_short_price", np.nan),
                "exit_reason": source.get("exit_reason", ""),
                "gross_return": _num(source.get("gross_return")),
                "notional_sek": _num(source.get("notional_sek")),
                "cost_sek": _num(source.get("cost_sek")),
                "net_pnl_sek": _num(source.get("net_pnl_sek")),
                "point_in_time_pass": True,
                "execution_invariant_pass": True,
                "router_active": False,
                "order_sent": False,
            })
            continue

        ticker = str(candidate["ticker"])
        entry_bar = _first_bar(prices, str(date), ticker)
        if entry_bar is None:
            raise RuntimeError(f"No 09:45-10:00 coverage entry bar for {date} {ticker}")
        entry_time = pd.Timestamp(entry_bar["datetime"])
        entry_price = _num(entry_bar["open"], _num(entry_bar["close"]))
        side, stop_price, target_price, exit_cutoff = _single_control_levels(candidate, taxonomy_lookup.loc[str(date)], entry_price)
        execution = _execute_single(
            prices=prices,
            date=str(date),
            ticker=ticker,
            side=side,
            entry_time=entry_time,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            exit_cutoff=exit_cutoff,
        )
        multiplier = _num(taxonomy_row.get("research_risk_multiplier"), _num(candidate.get("research_risk_multiplier"), 1.0))
        if not np.isfinite(multiplier):
            multiplier = {
                "RECOVERY": 1.0,
                "TREND_UP": 1.0,
                "TREND_DOWN": 1.0,
                "RANGE_LOW_VOL": 0.75,
                "HIGH_VOL_REVERSAL": 0.50,
                "VOLATILITY_EXPANSION": 0.65,
            }.get(regime, 1.0)
        notional = 1000.0 * multiplier
        cost = notional * 0.0005
        net_pnl = notional * execution["gross_return"] - cost
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            "trade_book": "MANDATORY_COVERAGE_CONTROL_BOOK",
            "trade_label": COVERAGE_TRADE_LABEL,
            "date": str(date),
            "primary_regime": regime,
            "assigned_strategy_id": registry["natural_strategy_id"],
            "coverage_control_id": registry["mandatory_control_id"],
            "source_strategy_id": str(candidate["playbook_id"]),
            "source_candidate_id": str(candidate["idea_id"]),
            "trade_id": f"COVERAGE|{date}|{regime}|{ticker}",
            "idea_type": "SINGLE",
            "direction": side,
            "ticker": ticker,
            "paired_ticker": "",
            "long_ticker": ticker if side == "LONG" else "",
            "short_ticker": ticker if side == "SHORT" else "",
            "entry_time": entry_time,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "pair_entry_long_price": np.nan,
            "pair_entry_short_price": np.nan,
            "pair_stop_return": np.nan,
            "pair_target_return": np.nan,
            "exit_time": execution["exit_time"],
            "exit_price": execution["exit_price"],
            "pair_exit_long_price": np.nan,
            "pair_exit_short_price": np.nan,
            "exit_reason": execution["exit_reason"],
            "gross_return": execution["gross_return"],
            "notional_sek": notional,
            "cost_sek": cost,
            "net_pnl_sek": net_pnl,
            "point_in_time_pass": True,
            "execution_invariant_pass": True,
            "router_active": False,
            "order_sent": False,
        })
    return pd.DataFrame(rows)


def _performance(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    groups = []
    for (book, regime), group in trades.groupby(["trade_book", "primary_regime"], dropna=False):
        pnl = pd.to_numeric(group["net_pnl_sek"], errors="coerce").fillna(0.0)
        gains = pnl[pnl > 0].sum()
        losses = -pnl[pnl < 0].sum()
        groups.append({
            "experiment_id": EXPERIMENT_ID,
            "trade_book": book,
            "primary_regime": regime,
            "sessions_with_trades": int(group["date"].nunique()),
            "trades": int(len(group)),
            "winning_trades": int((pnl > 0).sum()),
            "losing_or_nonpositive_trades": int((pnl <= 0).sum()),
            "win_rate": float((pnl > 0).mean()),
            "net_pnl_sek": float(pnl.sum()),
            "average_pnl_sek": float(pnl.mean()),
            "median_pnl_sek": float(pnl.median()),
            "profit_factor": float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else np.nan),
        })
    return pd.DataFrame(groups).sort_values(["trade_book", "primary_regime"]).reset_index(drop=True)


def _assignments(taxonomy: pd.DataFrame, natural: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    natural_counts = natural.groupby("date").size().to_dict() if not natural.empty else {}
    coverage_counts = coverage.groupby("date").size().to_dict() if not coverage.empty else {}
    rows = []
    for _, tax in taxonomy.sort_values("date").iterrows():
        date = str(tax["date"])
        regime = str(tax["primary_regime"])
        registry = REGISTRY_BY_REGIME[regime]
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            "date": date,
            "primary_regime": regime,
            "regime_confidence": tax.get("regime_confidence", np.nan),
            "confidence_band": tax.get("confidence_band", ""),
            "assigned_strategy_id": registry["natural_strategy_id"],
            "natural_maturity": registry["natural_maturity"],
            "coverage_control_id": registry["mandatory_control_id"],
            "natural_trade_count": int(natural_counts.get(date, 0)),
            "mandatory_coverage_trade_count": int(coverage_counts.get(date, 0)),
            "complete_trade_coverage_pass": int(coverage_counts.get(date, 0)) == 1,
            "router_active": False,
            "order_sent": False,
        })
    return pd.DataFrame(rows)


def _audit(
    taxonomy: pd.DataFrame,
    assignments: pd.DataFrame,
    natural: pd.DataFrame,
    coverage: pd.DataFrame,
    source_hashes_before: dict[str, str],
    source_hashes_after: dict[str, str],
) -> pd.DataFrame:
    recognized = set(taxonomy["primary_regime"].astype(str))
    expected = set(REGISTRY_BY_REGIME)
    checks = {
        "registry_covers_exactly_nine_regimes": len(expected) == 9,
        "all_observed_regimes_are_mapped": recognized.issubset(expected),
        "one_assignment_per_session": len(assignments) == taxonomy["date"].nunique() and assignments["date"].is_unique,
        "exactly_one_mandatory_trade_per_session": len(coverage) == taxonomy["date"].nunique() and coverage.groupby("date").size().eq(1).all(),
        "mandatory_trade_all_sessions_covered": set(coverage["date"].astype(str)) == set(taxonomy["date"].astype(str)),
        "mandatory_trade_point_in_time_pass": bool(coverage["point_in_time_pass"].fillna(False).astype(bool).all()),
        "mandatory_trade_execution_invariant_pass": bool(coverage["execution_invariant_pass"].fillna(False).astype(bool).all()),
        "natural_trade_point_in_time_pass": bool(natural["point_in_time_pass"].fillna(False).astype(bool).all()) if not natural.empty else True,
        "natural_trade_execution_invariant_pass": bool(natural["execution_invariant_pass"].fillna(False).astype(bool).all()) if not natural.empty else True,
        "router_inactive": not bool(pd.concat([natural["router_active"], coverage["router_active"]]).fillna(False).astype(bool).any()),
        "no_orders": not bool(pd.concat([natural["order_sent"], coverage["order_sent"]]).fillna(False).astype(bool).any()),
        "source_files_unchanged": source_hashes_before == source_hashes_after,
    }
    return pd.DataFrame([{"check": key, "passed": bool(value)} for key, value in checks.items()])


def run_replay(data_dir: Path = DATA_DIR, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    if data_dir.resolve() == DATA_DIR.resolve():
        source_paths = {
            "taxonomy": TAXONOMY_FILE,
            "baseline_candidates": BASELINE_CANDIDATE_FILE,
            "baseline_trades": BASELINE_TRADE_FILE,
            "price_db": PRICE_DB,
        }
    else:
        source_paths = {
            "taxonomy": data_dir / TAXONOMY_FILE.name,
            "baseline_candidates": data_dir / BASELINE_CANDIDATE_FILE.name,
            "baseline_trades": data_dir / BASELINE_TRADE_FILE.name,
            "price_db": data_dir / PRICE_DB.name,
        }
    for row in ASSIGNMENT_REGISTRY:
        source_filename = row["natural_source_file"]
        source_paths[f"natural_{row['regime']}"] = (
            legacy_output_path(source_filename)
            if data_dir.resolve() == DATA_DIR.resolve()
            else data_dir / source_filename
        )
    unique_sources = {key: path for key, path in source_paths.items()}
    source_hashes_before = {key: _sha256(path) for key, path in unique_sources.items()}

    taxonomy = _read_csv(source_paths["taxonomy"])
    taxonomy["date"] = taxonomy["date"].astype(str)
    candidates = _read_csv(source_paths["baseline_candidates"])
    baseline_trades = _read_csv(source_paths["baseline_trades"])
    prices = _load_prices_read_only(source_paths["price_db"])

    natural = build_natural_trade_book(data_dir, set(taxonomy["date"]))
    coverage = build_mandatory_coverage_book(taxonomy, candidates, baseline_trades, prices)
    assignments = _assignments(taxonomy, natural, coverage)
    combined = pd.concat([natural, coverage], ignore_index=True, sort=False)
    performance = _performance(combined)

    source_hashes_after = {key: _sha256(path) for key, path in unique_sources.items()}
    audit = _audit(taxonomy, assignments, natural, coverage, source_hashes_before, source_hashes_after)
    if not bool(audit["passed"].all()):
        failures = audit.loc[~audit["passed"], "check"].tolist()
        raise RuntimeError(f"Step 9S historical replay audit failed: {failures}")

    output_dir.mkdir(parents=True, exist_ok=True)
    registry = pd.DataFrame(ASSIGNMENT_REGISTRY)
    registry["experiment_id"] = EXPERIMENT_ID
    registry["research_status"] = RESEARCH_STATUS
    registry["code_version"] = CODE_VERSION
    registry["natural_book"] = "TRIGGER_BASED_SEPARATE_BOOK"
    registry["coverage_book"] = "EXACTLY_ONE_MANDATORY_SHADOW_TRADE_PER_SESSION"
    registry["router_active"] = False
    registry["orders_sent"] = False

    registry.to_csv(output_dir / "step9s_assignment_registry.csv", index=False)
    assignments.to_csv(output_dir / "step9s_session_assignments.csv", index=False)
    natural.to_csv(output_dir / "step9s_natural_trades.csv", index=False)
    coverage.to_csv(output_dir / "step9s_mandatory_coverage_trades.csv", index=False)
    combined.to_csv(output_dir / "step9s_all_trades.csv", index=False)
    performance.to_csv(output_dir / "step9s_performance.csv", index=False)
    audit.to_csv(output_dir / "step9s_audit.csv", index=False)
    (output_dir / "step9s_source_hashes.json").write_text(
        json.dumps(source_hashes_before, indent=2, sort_keys=True), encoding="utf-8"
    )

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "code_version": CODE_VERSION,
        "sessions": int(taxonomy["date"].nunique()),
        "regimes": int(taxonomy["primary_regime"].nunique()),
        "natural_trades": int(len(natural)),
        "natural_sessions_with_trades": int(natural["date"].nunique()) if not natural.empty else 0,
        "mandatory_coverage_trades": int(len(coverage)),
        "mandatory_coverage_sessions": int(coverage["date"].nunique()),
        "complete_trade_coverage_rate": float(coverage["date"].nunique() / taxonomy["date"].nunique()),
        "natural_net_pnl_sek": float(pd.to_numeric(natural["net_pnl_sek"], errors="coerce").fillna(0).sum()) if not natural.empty else 0.0,
        "mandatory_coverage_net_pnl_sek": float(pd.to_numeric(coverage["net_pnl_sek"], errors="coerce").fillna(0).sum()),
        "audit_pass": True,
        "router_active": False,
        "orders_sent": False,
    }
    pd.DataFrame([summary]).to_csv(output_dir / "step9s_summary.csv", index=False)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 9S historical contingency replay with complete mandatory shadow trade coverage.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_replay(args.data_dir, args.output_dir)
    print("STEP9S_HISTORICAL_CONTINGENCY_REPLAY_V1: PASSED")
    print(f"Sessions/regimes: {result['sessions']}/{result['regimes']}")
    print(f"Natural trades/sessions: {result['natural_trades']}/{result['natural_sessions_with_trades']}")
    print(f"Mandatory coverage trades/sessions: {result['mandatory_coverage_trades']}/{result['mandatory_coverage_sessions']}")
    print(f"Complete trade coverage: {result['complete_trade_coverage_rate']:.1%}")
    print(f"Natural P&L: {result['natural_net_pnl_sek']:.6f} SEK")
    print(f"Mandatory coverage P&L: {result['mandatory_coverage_net_pnl_sek']:.6f} SEK")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
