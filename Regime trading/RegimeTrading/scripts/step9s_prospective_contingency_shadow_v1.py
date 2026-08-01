from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date as date_type, datetime, time
from itertools import combinations
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from RegimeTrading.core.paths import DATA_DIR, FREEZE_DIRS
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path
from RegimeTrading.scripts import step9b_baseline_trade_generation as step9b
from RegimeTrading.scripts import step9d_regime_strategy_challenger_matrix as step9d
from RegimeTrading.scripts import step9s_historical_contingency_replay_v1 as step9s_historical
from RegimeTrading.scripts.research_regime_aware_gap_recovery import build_daily_reference


CONFIG_FILE = Path(__file__).resolve().parents[2] / "config" / "step9s_prospective_contingency_shadow_v1.json"
DEFAULT_LEDGER_DB = DATA_DIR / "step9s_prospective_contingency_shadow_v1.db"
DEFAULT_SOURCE_DB = resolve_stage_path("prices")
DEFAULT_STEP9L_LEDGER_DB = resolve_stage_path("step9l")
DEFAULT_EXPORT_DIR = resolve_stage_output_dir("step9s")
HISTORICAL_FREEZE_ROOT = FREEZE_DIRS["step9s"]

STOCKHOLM = ZoneInfo("Europe/Stockholm")


class Step9SProspectiveError(RuntimeError):
    pass


class SourceIntegrityError(Step9SProspectiveError):
    pass


class SourceDataNotReady(Step9SProspectiveError):
    pass


class ImmutableLedgerConflict(Step9SProspectiveError):
    pass


def _load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    assignments = config.get("assignments", [])
    regimes = [str(row.get("regime", "")) for row in assignments]
    expected = {
        "RECOVERY",
        "TREND_UP",
        "TREND_DOWN",
        "RANGE_LOW_VOL",
        "HIGH_VOL_REVERSAL",
        "HIGH_DISPERSION",
        "VOLATILITY_EXPANSION",
        "DEFENSIVE_MIXED",
        "DATA_LIMITED_DEFENSIVE",
    }
    if len(assignments) != 9 or set(regimes) != expected or len(set(regimes)) != 9:
        raise SourceIntegrityError("Step 9S prospective registry must map exactly the nine recognized regimes.")
    if bool(config.get("router_active")) or bool(config.get("orders_enabled")):
        raise SourceIntegrityError("Step 9S prospective configuration must remain router inactive with orders disabled.")
    return config


CONFIG = _load_config()
EXPERIMENT_ID = str(CONFIG["experiment_id"])
RESEARCH_STATUS = str(CONFIG["research_status"])
CODE_VERSION = str(CONFIG["code_version"])
DECISION_TIME = str(CONFIG["decision_time"])
ASSIGNMENT_DEADLINE = str(CONFIG["assignment_deadline"])
LATEST_ROUTER_SOURCE_LABEL = str(CONFIG["latest_router_source_label"])
ENTRY_WINDOW_START = str(CONFIG["coverage_entry_window_start"])
ENTRY_WINDOW_END = str(CONFIG["coverage_entry_window_end"])
EOD_MINIMUM_LABEL = str(CONFIG["eod_minimum_label"])
EOD_TIME = str(CONFIG["eod_time"])
BASE_NOTIONAL_SEK = float(CONFIG["base_notional_sek"])
ROUND_TRIP_COST_RATE = float(CONFIG["round_trip_cost_rate"])
ASSIGNMENT_REGISTRY: tuple[dict[str, Any], ...] = tuple(dict(row) for row in CONFIG["assignments"])
REGISTRY_BY_REGIME = {str(row["regime"]): dict(row) for row in ASSIGNMENT_REGISTRY}

STEP9L_LEDGER_REGIMES = {
    regime for regime, row in REGISTRY_BY_REGIME.items()
    if row["natural_source_kind"] == "STEP9L_V3_LEDGER"
}

ASSIGNMENT_EXPORT = "step9s_prospective_assignments.csv"
PLAN_EXPORT = "step9s_prospective_coverage_plans.csv"
OUTCOME_BATCH_EXPORT = "step9s_prospective_outcome_batches.csv"
NATURAL_OUTCOME_EXPORT = "step9s_prospective_natural_outcomes.csv"
COVERAGE_OUTCOME_EXPORT = "step9s_prospective_coverage_outcomes.csv"
SUMMARY_EXPORT = "step9s_prospective_summary.csv"
AUDIT_EXPORT = "step9s_prospective_audit.csv"
REGISTRY_EXPORT = "step9s_prospective_assignment_registry.csv"


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _clean_scalar(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_clean_scalar(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date_type)):
        if isinstance(value, date_type) and not isinstance(value, datetime):
            return value.isoformat()
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if pd.isna(value) else float(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _canonical_payload(payload: Any) -> str:
    return json.dumps(_clean_scalar(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _num(value: Any, default: float = np.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if pd.isna(value):
        return False
    return bool(value)


def _parse_stockholm_datetime(value: str | None) -> datetime:
    if value:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            return parsed.tz_localize(STOCKHOLM).to_pydatetime()
        return parsed.tz_convert(STOCKHOLM).to_pydatetime()
    return datetime.now(STOCKHOLM)


def _target_date(value: str | None, now: datetime) -> str:
    target = value or now.date().isoformat()
    pd.Timestamp(target)
    return target


def _clock_to_time(value: str) -> time:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


def _registry_hash() -> str:
    return _payload_hash({"config": CONFIG, "assignments": list(ASSIGNMENT_REGISTRY)})


def _historical_freeze_provenance(root: Path = HISTORICAL_FREEZE_ROOT) -> dict[str, str]:
    if not bool(CONFIG.get("historical_freeze_required", True)):
        return {"freeze_id": "NOT_REQUIRED", "artifact_set_sha256": "NOT_REQUIRED"}
    if not root.is_dir():
        raise SourceDataNotReady(
            f"Historical Step 9S freeze root is missing: {root}. Run the historical audit/freeze gate first."
        )
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    for summary in root.glob("*/step9s_historical_output_freeze_summary.json"):
        try:
            payload = json.loads(summary.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        freeze_id = str(payload.get("freeze_id", summary.parent.name))
        artifact = str(payload.get("artifact_set_sha256", ""))
        if artifact:
            candidates.append((freeze_id, summary, payload))
    if not candidates:
        raise SourceDataNotReady("No valid historical Step 9S freeze summary was found.")
    candidates.sort(key=lambda item: item[0])
    freeze_id, summary, payload = candidates[-1]
    return {
        "freeze_id": freeze_id,
        "artifact_set_sha256": str(payload["artifact_set_sha256"]),
        "freeze_summary_sha256": _sha256(summary),
    }


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _load_prices_read_only(path: Path) -> pd.DataFrame:
    with closing(_readonly_connection(path)) as con:
        prices = pd.read_sql_query(
            "SELECT datetime, open, high, low, close, ticker FROM intraday_prices ORDER BY ticker, datetime",
            con,
        )
    if prices.empty:
        return prices
    prices["datetime"] = pd.to_datetime(prices["datetime"], errors="raise", format="mixed")
    prices["ticker"] = prices["ticker"].astype(str).str.strip()
    for column in ["open", "high", "low", "close"]:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
    prices["open"] = prices["open"].where(prices["open"].notna(), prices["close"])
    prices = prices.dropna(subset=["datetime", "ticker", "high", "low", "close"])
    prices["date"] = prices["datetime"].dt.strftime("%Y-%m-%d")
    prices["clock"] = prices["datetime"].dt.strftime("%H:%M")
    return prices.sort_values(["ticker", "datetime"]).reset_index(drop=True)


def _verify_step9l_batch_hash(row: dict[str, Any]) -> None:
    taxonomy_payload = json.loads(str(row["taxonomy_payload_json"]))
    payload = {
        "batch_id": row["batch_id"],
        "session_date": row["session_date"],
        "prospective_status": row["prospective_status"],
        "code_version": row["code_version"],
        "contract_registry_hash": row["contract_registry_hash"],
        "universe_hash": row["universe_hash"],
        "source_max_datetime": row["source_max_datetime"],
        "taxonomy_payload": taxonomy_payload,
        "decision_rows": int(row["decision_rows"]),
        "eligible_rows": int(row["eligible_rows"]),
        "active_guardrails": int(row["active_guardrails"]),
    }
    if _payload_hash(payload) != str(row["batch_payload_hash"]):
        raise SourceIntegrityError("The sealed Step 9L morning batch payload hash is invalid.")


def _read_step9l_morning(
    session_date: str,
    ledger_db: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    with closing(_readonly_connection(ledger_db)) as con:
        con.row_factory = sqlite3.Row
        batches = con.execute(
            "SELECT * FROM shadow_decision_batches WHERE session_date = ?",
            (session_date,),
        ).fetchall()
        if len(batches) != 1:
            raise SourceDataNotReady(
                f"Expected one sealed Step 9L V3 morning batch for {session_date}; found {len(batches)}."
            )
        batch = dict(batches[0])
        decisions = [
            dict(row) for row in con.execute(
                "SELECT rowid, * FROM shadow_decisions WHERE batch_id = ? ORDER BY rowid",
                (batch["batch_id"],),
            ).fetchall()
        ]
    if batch["experiment_id"] != CONFIG["source_step9l_experiment_id"]:
        raise SourceIntegrityError(f"Unexpected Step 9L experiment: {batch['experiment_id']}")
    if batch["code_version"] != CONFIG["source_step9l_code_version"]:
        raise SourceIntegrityError(f"Unexpected Step 9L code version: {batch['code_version']}")
    if batch["run_mode"] != "MORNING_DECISION_SEAL":
        raise SourceIntegrityError("Step 9L source row is not a morning decision seal.")
    if batch["decision_time"] != DECISION_TIME or not _bool(batch["regime_point_in_time_pass"]):
        raise SourceIntegrityError("Step 9L source regime is not point-in-time eligible.")
    if int(batch["decision_rows"]) != len(decisions):
        raise SourceIntegrityError("Step 9L decision row count does not match the sealed batch.")
    _verify_step9l_batch_hash(batch)
    for row in decisions:
        payload = {key: value for key, value in row.items() if key not in {"rowid", "row_payload_hash"}}
        if _payload_hash(payload) != str(row["row_payload_hash"]):
            raise SourceIntegrityError(f"Invalid Step 9L decision row hash: {row['decision_id']}")
    decision_set_hash = _payload_hash([row["row_payload_hash"] for row in decisions])
    return batch, decisions, decision_set_hash


def _read_step9l_eod(
    session_date: str,
    ledger_db: Path,
    decision_batch_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    with closing(_readonly_connection(ledger_db)) as con:
        con.row_factory = sqlite3.Row
        batches = con.execute(
            "SELECT * FROM shadow_outcome_batches WHERE session_date = ?",
            (session_date,),
        ).fetchall()
        if len(batches) != 1:
            raise SourceDataNotReady(
                f"Run Step 9L V3 EOD first. Expected one Step 9L outcome batch for {session_date}; found {len(batches)}."
            )
        batch = dict(batches[0])
        outcomes = [
            dict(row) for row in con.execute(
                "SELECT rowid, * FROM shadow_outcomes WHERE outcome_batch_id = ? ORDER BY rowid",
                (batch["outcome_batch_id"],),
            ).fetchall()
        ]
    if batch["decision_batch_id"] != decision_batch_id:
        raise SourceIntegrityError("Step 9L EOD batch does not reference the sealed morning batch used by Step 9S.")
    if not _bool(batch["eod_complete"]):
        raise SourceDataNotReady("Step 9L EOD batch is not marked complete.")
    if int(batch["outcome_rows"]) != len(outcomes):
        raise SourceIntegrityError("Step 9L EOD outcome count does not match its sealed batch.")
    for row in outcomes:
        payload = {key: value for key, value in row.items() if key not in {"rowid", "row_payload_hash"}}
        if _payload_hash(payload) != str(row["row_payload_hash"]):
            raise SourceIntegrityError(f"Invalid Step 9L outcome row hash: {row['outcome_id']}")
    payload = {
        "outcome_batch_id": batch["outcome_batch_id"],
        "decision_batch_id": batch["decision_batch_id"],
        "session_date": batch["session_date"],
        "code_version": batch["code_version"],
        "source_max_datetime": batch["source_max_datetime"],
        "outcome_row_hashes": [row["row_payload_hash"] for row in outcomes],
    }
    if _payload_hash(payload) != str(batch["outcome_payload_hash"]):
        raise SourceIntegrityError("The sealed Step 9L EOD batch payload hash is invalid.")
    outcome_set_hash = _payload_hash([row["row_payload_hash"] for row in outcomes])
    return batch, outcomes, outcome_set_hash


def _morning_state(prices: pd.DataFrame, session_date: str) -> pd.DataFrame:
    if prices.empty:
        raise SourceDataNotReady("The Step 9S source price database is empty.")
    scoped = prices[
        prices["date"].lt(session_date)
        | (prices["date"].eq(session_date) & prices["clock"].le(LATEST_ROUTER_SOURCE_LABEL))
    ].copy()
    daily_reference = build_daily_reference(
        scoped.assign(date=pd.to_datetime(scoped["date"]).dt.date)
    )
    state, _ = step9b.build_market_state(
        scoped.assign(date=pd.to_datetime(scoped["date"]).dt.date),
        daily_reference,
        {session_date},
    )
    state = state[state["date"].astype(str).eq(session_date)].copy()
    if state.empty:
        raise SourceDataNotReady(f"No point-in-time Step 9S market state was available for {session_date}.")
    labels = state["max_router_source_label"].dropna().astype(str)
    if labels.empty or labels.max() > LATEST_ROUTER_SOURCE_LABEL:
        raise SourceIntegrityError("Step 9S morning state used data after the 09:40 router cutoff.")
    return state.sort_values("ticker").reset_index(drop=True)


def _state_snapshot_hash(state: pd.DataFrame) -> str:
    columns = [
        "date", "ticker", "previous_close", "early_open", "opening_bar_high",
        "opening_bar_low", "early_high", "early_low", "early_midpoint",
        "early_range_pct", "cutoff_close", "cutoff_return_from_open", "opening_gap",
        "close_0935", "close_0940", "high_0940", "low_0940", "max_router_source_label",
    ]
    rows = state[columns].sort_values("ticker").to_dict("records")
    return _payload_hash(rows)


def _single_candidate_pool(regime: str, state: pd.DataFrame, taxonomy: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in state.to_dict("records"):
        ticker = str(source["ticker"])
        early_open = _num(source.get("early_open"))
        early_high = _num(source.get("early_high"))
        early_low = _num(source.get("early_low"))
        midpoint = _num(source.get("early_midpoint"))
        cutoff_close = _num(source.get("cutoff_close"))
        cutoff_return = _num(source.get("cutoff_return_from_open"), 0.0)
        opening_gap = _num(source.get("opening_gap"))
        close_0935 = _num(source.get("close_0935"))
        close_0940 = _num(source.get("close_0940"))
        early_range_pct = _num(source.get("early_range_pct"), 0.0)
        direction = ""
        score = 0.0
        validity_priority = 0

        if regime == "RECOVERY":
            direction = "LONG"
            valid_gap = np.isfinite(opening_gap) and -0.0200 <= opening_gap <= -0.0010
            valid_levels = (
                np.isfinite(_num(source.get("opening_bar_low")))
                and np.isfinite(_num(source.get("opening_bar_high")))
                and np.isfinite(_num(source.get("previous_close")))
                and _num(source.get("opening_bar_low")) < _num(source.get("opening_bar_high")) < _num(source.get("previous_close"))
            )
            validity_priority = 0 if valid_gap and valid_levels else 1
            score = -opening_gap if np.isfinite(opening_gap) else -999.0
            sort_key = (validity_priority, ticker) if validity_priority == 0 else (1, -score, ticker)
        elif regime == "TREND_UP":
            direction = "LONG"
            score = cutoff_return
            sort_key = (-score, ticker)
        elif regime == "TREND_DOWN":
            direction = "SHORT"
            score = -cutoff_return
            sort_key = (-score, ticker)
        elif regime == "RANGE_LOW_VOL":
            deviation = cutoff_close / midpoint - 1.0 if midpoint > 0 else 0.0
            direction = "SHORT" if deviation >= 0 else "LONG"
            score = abs(deviation)
            sort_key = (-score, ticker)
        elif regime == "HIGH_VOL_REVERSAL":
            initial = close_0935 / early_open - 1.0 if early_open > 0 and np.isfinite(close_0935) else cutoff_return
            final = close_0940 / early_open - 1.0 if early_open > 0 and np.isfinite(close_0940) else cutoff_return
            retracement = abs(initial) - abs(final)
            sign_flip = initial * final < 0
            score = abs(initial) + max(retracement, 0.0) + (abs(initial) if sign_flip else 0.0)
            reference_move = initial if abs(initial) > 1e-12 else final
            direction = "SHORT" if reference_move >= 0 else "LONG"
            sort_key = (-score, ticker)
        elif regime == "VOLATILITY_EXPANSION":
            score = early_range_pct + abs(cutoff_return)
            bias = str(taxonomy.get("direction_bias", "NEUTRAL")).upper()
            direction = "LONG" if bias == "UP" else "SHORT" if bias == "DOWN" else ("LONG" if cutoff_return >= 0 else "SHORT")
            sort_key = (-score, ticker)
        else:
            raise ValueError(f"Unsupported single mandatory-control regime: {regime}")

        rows.append({
            "candidate_rank": 0,
            "sort_key": list(sort_key),
            "primary_regime": regime,
            "idea_type": "SINGLE",
            "direction": direction,
            "ticker": ticker,
            "paired_ticker": "",
            "long_ticker": ticker if direction == "LONG" else "",
            "short_ticker": ticker if direction == "SHORT" else "",
            "ranking_metric": score,
            "validity_priority": validity_priority,
            "previous_close": _num(source.get("previous_close")),
            "opening_gap": opening_gap,
            "early_open": early_open,
            "opening_bar_high": _num(source.get("opening_bar_high")),
            "opening_bar_low": _num(source.get("opening_bar_low")),
            "early_high": early_high,
            "early_low": early_low,
            "early_midpoint": midpoint,
            "early_range_pct": early_range_pct,
            "cutoff_close": cutoff_close,
            "cutoff_return_from_open": cutoff_return,
            "close_0935": close_0935,
            "close_0940": close_0940,
            "high_0940": _num(source.get("high_0940")),
            "low_0940": _num(source.get("low_0940")),
            "max_router_source_label": str(source.get("max_router_source_label", "")),
        })
    rows.sort(key=lambda row: tuple(row["sort_key"]))
    for rank, row in enumerate(rows, start=1):
        row["candidate_rank"] = rank
        row.pop("sort_key", None)
    return rows


def _pair_candidate_pool(regime: str, state: pd.DataFrame) -> list[dict[str, Any]]:
    usable = state.dropna(subset=["cutoff_return_from_open"]).copy()
    if len(usable) < 2:
        raise SourceDataNotReady(f"Fewer than two morning tickers are available for {regime}.")
    if regime == "DEFENSIVE_MIXED" and usable["early_range_pct"].notna().sum() >= 4:
        cap = usable["early_range_pct"].quantile(0.75)
        controlled = usable[usable["early_range_pct"].le(cap)].copy()
        if len(controlled) >= 2:
            usable = controlled
    records = {str(row["ticker"]): row for row in usable.to_dict("records")}
    pairs: list[dict[str, Any]] = []
    for ticker_a, ticker_b in combinations(sorted(records), 2):
        a, b = records[ticker_a], records[ticker_b]
        ret_a = _num(a.get("cutoff_return_from_open"), 0.0)
        ret_b = _num(b.get("cutoff_return_from_open"), 0.0)
        weaker, stronger = (a, b) if (ret_a, ticker_a) <= (ret_b, ticker_b) else (b, a)
        spread = abs(ret_a - ret_b)
        if regime == "HIGH_DISPERSION":
            long_state, short_state = stronger, weaker
            stop_return = -max(0.0015, 0.25 * spread)
            target_return = max(0.0010, 0.25 * spread)
            exit_cutoff = "15:30"
            sort_key = (-spread, str(long_state["ticker"]), str(short_state["ticker"]))
        elif regime == "DEFENSIVE_MIXED":
            long_state, short_state = weaker, stronger
            stop_return = -max(0.0010, 0.125 * spread)
            target_return = max(0.00075, 0.175 * spread)
            exit_cutoff = "14:30"
            sort_key = (-spread, str(long_state["ticker"]), str(short_state["ticker"]))
        elif regime == "DATA_LIMITED_DEFENSIVE":
            ordered_names = sorted([ticker_a, ticker_b])
            long_state, short_state = records[ordered_names[0]], records[ordered_names[1]]
            stop_return = -0.0050
            target_return = 0.0025
            exit_cutoff = "12:00"
            abs_sum = abs(ret_a) + abs(ret_b)
            sort_key = (abs_sum, ordered_names[0], ordered_names[1])
        else:
            raise ValueError(f"Unsupported pair mandatory-control regime: {regime}")
        pairs.append({
            "candidate_rank": 0,
            "sort_key": list(sort_key),
            "primary_regime": regime,
            "idea_type": "PAIR",
            "direction": "LONG_SHORT",
            "ticker": str(long_state["ticker"]),
            "paired_ticker": str(short_state["ticker"]),
            "long_ticker": str(long_state["ticker"]),
            "short_ticker": str(short_state["ticker"]),
            "ranking_metric": spread if regime != "DATA_LIMITED_DEFENSIVE" else -(abs(ret_a) + abs(ret_b)),
            "cutoff_return_from_open": _num(long_state.get("cutoff_return_from_open")),
            "paired_cutoff_return_from_open": _num(short_state.get("cutoff_return_from_open")),
            "pair_stop_return": stop_return,
            "pair_target_return": target_return,
            "exit_cutoff": exit_cutoff,
            "max_router_source_label": max(
                str(long_state.get("max_router_source_label", "")),
                str(short_state.get("max_router_source_label", "")),
            ),
        })
    pairs.sort(key=lambda row: tuple(row["sort_key"]))
    for rank, row in enumerate(pairs, start=1):
        row["candidate_rank"] = rank
        row.pop("sort_key", None)
    return pairs


def _plan_models(regime: str, idea_type: str) -> tuple[str, str, str, str]:
    if idea_type == "PAIR":
        return (
            "FIRST_COMMON_BAR_OPEN_FROM_09_50_THROUGH_10_00",
            "PAIR_RETURN_THRESHOLD_FROM_MORNING_SPREAD",
            "PAIR_RETURN_THRESHOLD_FROM_MORNING_SPREAD",
            {"HIGH_DISPERSION": "15:30", "DEFENSIVE_MIXED": "14:30", "DATA_LIMITED_DEFENSIVE": "12:00"}[regime],
        )
    models = {
        "RECOVERY": ("FIRST_AVAILABLE_BAR_OPEN_FROM_09_50_THROUGH_10_00", "09:30_LOW_OR_MECHANICAL_1R", "PREVIOUS_CLOSE_OR_MECHANICAL_1R", "16:30"),
        "TREND_UP": ("FIRST_AVAILABLE_BAR_OPEN_FROM_09_50_THROUGH_10_00", "STRICT_EARLY_LOW_OR_MECHANICAL_RISK", "1R_FROM_ACTUAL_ENTRY", "16:30"),
        "TREND_DOWN": ("FIRST_AVAILABLE_BAR_OPEN_FROM_09_50_THROUGH_10_00", "STRICT_EARLY_HIGH_OR_MECHANICAL_RISK", "1R_FROM_ACTUAL_ENTRY", "16:30"),
        "RANGE_LOW_VOL": ("FIRST_AVAILABLE_BAR_OPEN_FROM_09_50_THROUGH_10_00", "ONE_EARLY_RANGE_WIDTH_ADVERSE", "STRICT_EARLY_MIDPOINT_OR_1R", "15:30"),
        "HIGH_VOL_REVERSAL": ("FIRST_AVAILABLE_BAR_OPEN_FROM_09_50_THROUGH_10_00", "STRICT_EARLY_EXTREME_OR_MECHANICAL_RISK", "EARLY_OPEN_CAPPED_AT_1R", "16:30"),
        "VOLATILITY_EXPANSION": ("FIRST_AVAILABLE_BAR_OPEN_FROM_09_50_THROUGH_10_00", "EARLY_MIDPOINT_OR_OPPOSITE_BOUNDARY", "1_5R_FROM_ACTUAL_ENTRY", "16:30"),
    }
    return models[regime]


def build_coverage_plan(
    session_date: str,
    taxonomy: dict[str, Any],
    state: pd.DataFrame,
    assignment: dict[str, Any],
) -> dict[str, Any]:
    regime = str(taxonomy["primary_regime"])
    if regime in {"HIGH_DISPERSION", "DEFENSIVE_MIXED", "DATA_LIMITED_DEFENSIVE"}:
        pool = _pair_candidate_pool(regime, state)
    else:
        pool = _single_candidate_pool(regime, state, taxonomy)
    if not pool:
        raise SourceDataNotReady(f"No mandatory coverage candidate could be planned for {session_date} {regime}.")
    if any(str(row.get("max_router_source_label", "")) > LATEST_ROUTER_SOURCE_LABEL for row in pool):
        raise SourceIntegrityError("A mandatory coverage candidate used post-cutoff information.")
    primary = pool[0]
    entry_model, stop_model, target_model, exit_cutoff = _plan_models(regime, primary["idea_type"])
    multiplier = _num(taxonomy.get("research_risk_multiplier"), 1.0)
    if not np.isfinite(multiplier) or multiplier <= 0:
        multiplier = {
            "RECOVERY": 1.0, "TREND_UP": 1.0, "TREND_DOWN": 1.0,
            "RANGE_LOW_VOL": 0.75, "HIGH_VOL_REVERSAL": 0.50,
            "HIGH_DISPERSION": 0.75, "VOLATILITY_EXPANSION": 0.65,
            "DEFENSIVE_MIXED": 0.40, "DATA_LIMITED_DEFENSIVE": 0.25,
        }[regime]
    plan_id = f"S9S-{session_date.replace('-', '')}-COVERAGE-PLAN"
    plan_payload = {
        "plan_id": plan_id,
        "session_date": session_date,
        "primary_regime": regime,
        "coverage_control_id": assignment["mandatory_control_id"],
        "candidate_pool": pool,
        "entry_window_start": ENTRY_WINDOW_START,
        "entry_window_end": ENTRY_WINDOW_END,
        "entry_model": entry_model,
        "stop_model": stop_model,
        "target_model": target_model,
        "exit_cutoff": exit_cutoff,
        "notional_sek": BASE_NOTIONAL_SEK * multiplier,
        "cost_rate": ROUND_TRIP_COST_RATE,
    }
    return {
        "plan_id": plan_id,
        "session_date": session_date,
        "primary_regime": regime,
        "coverage_control_id": assignment["mandatory_control_id"],
        "idea_type": primary["idea_type"],
        "direction": primary["direction"],
        "ticker": primary.get("ticker", ""),
        "paired_ticker": primary.get("paired_ticker", ""),
        "long_ticker": primary.get("long_ticker", ""),
        "short_ticker": primary.get("short_ticker", ""),
        "primary_candidate_rank": int(primary["candidate_rank"]),
        "ranking_metric": _num(primary.get("ranking_metric")),
        "candidate_pool_json": _canonical_payload(pool),
        "entry_window_start": ENTRY_WINDOW_START,
        "entry_window_end": ENTRY_WINDOW_END,
        "entry_model": entry_model,
        "stop_model": stop_model,
        "target_model": target_model,
        "exit_cutoff": exit_cutoff,
        "notional_sek": BASE_NOTIONAL_SEK * multiplier,
        "cost_rate": ROUND_TRIP_COST_RATE,
        "max_router_source_label": max(str(row.get("max_router_source_label", "")) for row in pool),
        "point_in_time_pass": 1,
        "router_active": 0,
        "order_sent": 0,
        "plan_payload_hash": _payload_hash(plan_payload),
    }


def _ensure_ledger_schema(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS step9s_assignments (
            assignment_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            session_date TEXT NOT NULL UNIQUE,
            created_at_stockholm TEXT NOT NULL,
            run_mode TEXT NOT NULL,
            prospective_status TEXT NOT NULL,
            decision_time TEXT NOT NULL,
            assignment_deadline TEXT NOT NULL,
            coverage_entry_start TEXT NOT NULL,
            code_version TEXT NOT NULL,
            registry_hash TEXT NOT NULL,
            historical_freeze_id TEXT NOT NULL,
            historical_freeze_artifact_sha256 TEXT NOT NULL,
            source_step9l_db TEXT NOT NULL,
            source_step9l_batch_id TEXT NOT NULL,
            source_step9l_batch_payload_hash TEXT NOT NULL,
            source_step9l_decision_set_hash TEXT NOT NULL,
            source_price_db TEXT NOT NULL,
            morning_state_snapshot_hash TEXT NOT NULL,
            primary_regime TEXT NOT NULL,
            regime_confidence REAL,
            confidence_band TEXT NOT NULL,
            direction_bias TEXT NOT NULL,
            research_risk_multiplier REAL,
            taxonomy_payload_json TEXT NOT NULL,
            natural_strategy_id TEXT NOT NULL,
            natural_maturity TEXT NOT NULL,
            natural_source_kind TEXT NOT NULL,
            coverage_control_id TEXT NOT NULL,
            coverage_plan_id TEXT NOT NULL UNIQUE,
            point_in_time_pass INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            assignment_payload_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS step9s_coverage_plans (
            plan_id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL UNIQUE,
            primary_regime TEXT NOT NULL,
            coverage_control_id TEXT NOT NULL,
            idea_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            ticker TEXT NOT NULL,
            paired_ticker TEXT NOT NULL,
            long_ticker TEXT NOT NULL,
            short_ticker TEXT NOT NULL,
            primary_candidate_rank INTEGER NOT NULL,
            ranking_metric REAL,
            candidate_pool_json TEXT NOT NULL,
            entry_window_start TEXT NOT NULL,
            entry_window_end TEXT NOT NULL,
            entry_model TEXT NOT NULL,
            stop_model TEXT NOT NULL,
            target_model TEXT NOT NULL,
            exit_cutoff TEXT NOT NULL,
            notional_sek REAL NOT NULL,
            cost_rate REAL NOT NULL,
            max_router_source_label TEXT NOT NULL,
            point_in_time_pass INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            plan_payload_hash TEXT NOT NULL,
            FOREIGN KEY(assignment_id) REFERENCES step9s_assignments(assignment_id)
        );
        CREATE TABLE IF NOT EXISTS step9s_outcome_batches (
            outcome_batch_id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL UNIQUE,
            created_at_stockholm TEXT NOT NULL,
            code_version TEXT NOT NULL,
            source_step9l_outcome_batch_id TEXT NOT NULL,
            source_step9l_outcome_payload_hash TEXT NOT NULL,
            source_step9l_outcome_set_hash TEXT NOT NULL,
            eod_price_snapshot_hash TEXT NOT NULL,
            eod_complete INTEGER NOT NULL,
            natural_status TEXT NOT NULL,
            natural_trade_count INTEGER NOT NULL,
            coverage_trade_count INTEGER NOT NULL,
            natural_net_pnl_sek REAL NOT NULL,
            coverage_net_pnl_sek REAL NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            outcome_payload_hash TEXT NOT NULL,
            FOREIGN KEY(assignment_id) REFERENCES step9s_assignments(assignment_id)
        );
        CREATE TABLE IF NOT EXISTS step9s_natural_outcomes (
            natural_outcome_id TEXT PRIMARY KEY,
            outcome_batch_id TEXT NOT NULL,
            assignment_id TEXT NOT NULL,
            session_date TEXT NOT NULL,
            primary_regime TEXT NOT NULL,
            assigned_strategy_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_trade_id TEXT NOT NULL,
            idea_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            ticker TEXT NOT NULL,
            paired_ticker TEXT NOT NULL,
            long_ticker TEXT NOT NULL,
            short_ticker TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            entry_price REAL,
            stop_price REAL,
            target_price REAL,
            pair_entry_long_price REAL,
            pair_entry_short_price REAL,
            pair_stop_return REAL,
            pair_target_return REAL,
            exit_time TEXT NOT NULL,
            exit_price REAL,
            pair_exit_long_price REAL,
            pair_exit_short_price REAL,
            exit_reason TEXT NOT NULL,
            gross_return REAL,
            notional_sek REAL,
            cost_sek REAL,
            net_pnl_sek REAL,
            point_in_time_pass INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            row_payload_hash TEXT NOT NULL,
            FOREIGN KEY(outcome_batch_id) REFERENCES step9s_outcome_batches(outcome_batch_id),
            FOREIGN KEY(assignment_id) REFERENCES step9s_assignments(assignment_id)
        );
        CREATE TABLE IF NOT EXISTS step9s_coverage_outcomes (
            coverage_outcome_id TEXT PRIMARY KEY,
            outcome_batch_id TEXT NOT NULL UNIQUE,
            assignment_id TEXT NOT NULL UNIQUE,
            plan_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL UNIQUE,
            primary_regime TEXT NOT NULL,
            coverage_control_id TEXT NOT NULL,
            used_candidate_rank INTEGER NOT NULL,
            idea_type TEXT NOT NULL,
            direction TEXT NOT NULL,
            ticker TEXT NOT NULL,
            paired_ticker TEXT NOT NULL,
            long_ticker TEXT NOT NULL,
            short_ticker TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            entry_price REAL,
            stop_price REAL,
            target_price REAL,
            pair_entry_long_price REAL,
            pair_entry_short_price REAL,
            pair_stop_return REAL,
            pair_target_return REAL,
            exit_time TEXT NOT NULL,
            exit_price REAL,
            pair_exit_long_price REAL,
            pair_exit_short_price REAL,
            exit_reason TEXT NOT NULL,
            gross_return REAL NOT NULL,
            risk_pct_at_entry REAL,
            r_multiple_achieved REAL,
            notional_sek REAL NOT NULL,
            cost_sek REAL NOT NULL,
            net_pnl_sek REAL NOT NULL,
            point_in_time_pass INTEGER NOT NULL,
            execution_invariant_pass INTEGER NOT NULL,
            router_active INTEGER NOT NULL,
            order_sent INTEGER NOT NULL,
            row_payload_hash TEXT NOT NULL,
            FOREIGN KEY(outcome_batch_id) REFERENCES step9s_outcome_batches(outcome_batch_id),
            FOREIGN KEY(assignment_id) REFERENCES step9s_assignments(assignment_id),
            FOREIGN KEY(plan_id) REFERENCES step9s_coverage_plans(plan_id)
        );
        """
    )
    for table in [
        "step9s_assignments", "step9s_coverage_plans", "step9s_outcome_batches",
        "step9s_natural_outcomes", "step9s_coverage_outcomes",
    ]:
        con.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_STEP9S_LEDGER_UPDATE_FORBIDDEN'); END"
        )
        con.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_STEP9S_LEDGER_DELETE_FORBIDDEN'); END"
        )


def _insert_immutable(
    con: sqlite3.Connection,
    table: str,
    key_column: str,
    hash_column: str,
    row: dict[str, Any],
) -> bool:
    existing = con.execute(
        f"SELECT {hash_column} FROM {table} WHERE {key_column} = ?",
        (row[key_column],),
    ).fetchone()
    if existing:
        if str(existing[0]) != str(row[hash_column]):
            raise ImmutableLedgerConflict(
                f"Conflicting immutable Step 9S row for {table}.{key_column}={row[key_column]}"
            )
        return False
    columns = list(row)
    placeholders = ",".join("?" for _ in columns)
    con.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        [_clean_scalar(row[column]) for column in columns],
    )
    return True


def _read_existing_assignment(ledger_db: Path, session_date: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not ledger_db.exists():
        return None, None
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        con.row_factory = sqlite3.Row
        assignment = con.execute(
            "SELECT * FROM step9s_assignments WHERE session_date = ?", (session_date,)
        ).fetchone()
        plan = con.execute(
            "SELECT * FROM step9s_coverage_plans WHERE session_date = ?", (session_date,)
        ).fetchone()
    return (dict(assignment) if assignment else None, dict(plan) if plan else None)


def _new_prospective_status(
    session_date: str,
    now: datetime,
    source_status: str,
    allow_late: bool,
    simulated_clock: bool,
) -> str:
    if simulated_clock:
        return "SIMULATED_CLOCK_RECONSTRUCTION_NOT_CONFIRMATORY"
    if source_status != "PROSPECTIVE_CONFIRMATORY_ELIGIBLE":
        return "SOURCE_STEP9L_NONCONFIRMATORY"
    if now.date().isoformat() != session_date or now.time().replace(tzinfo=None) > _clock_to_time(ASSIGNMENT_DEADLINE):
        if not allow_late:
            raise SourceDataNotReady(
                f"Step 9S prospective assignment deadline {ASSIGNMENT_DEADLINE} has passed. "
                "Do not use late reconstruction during a normal morning."
            )
        return "LATE_RECONSTRUCTION_NOT_CONFIRMATORY"
    if now.time().replace(tzinfo=None) < _clock_to_time(DECISION_TIME):
        raise SourceDataNotReady("Step 9S cannot assign before the sealed 09:45 regime decision.")
    return "PROSPECTIVE_CONFIRMATORY_ELIGIBLE"


def seal_morning_assignment(
    session_date: str,
    now: datetime,
    source_db: Path = DEFAULT_SOURCE_DB,
    step9l_ledger_db: Path = DEFAULT_STEP9L_LEDGER_DB,
    ledger_db: Path = DEFAULT_LEDGER_DB,
    allow_late: bool = False,
    simulated_clock: bool = False,
    export_outputs_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    source_batch, _, decision_set_hash = _read_step9l_morning(session_date, step9l_ledger_db)
    regime = str(source_batch["primary_regime"])
    assignment = REGISTRY_BY_REGIME.get(regime)
    if assignment is None:
        raise SourceIntegrityError(f"Unknown recognized regime with no Step 9S assignment: {regime}")
    taxonomy = json.loads(str(source_batch["taxonomy_payload_json"]))
    if str(taxonomy.get("primary_regime")) != regime:
        raise SourceIntegrityError("Step 9L batch regime and taxonomy payload disagree.")
    prices = _load_prices_read_only(source_db)
    state = _morning_state(prices, session_date)
    state_hash = _state_snapshot_hash(state)
    plan = build_coverage_plan(session_date, taxonomy, state, assignment)
    registry_hash = _registry_hash()
    freeze = _historical_freeze_provenance()
    assignment_id = f"S9S-{session_date.replace('-', '')}-ASSIGNMENT"

    existing_assignment, existing_plan = _read_existing_assignment(ledger_db, session_date)
    if existing_assignment or existing_plan:
        if not existing_assignment or not existing_plan:
            raise ImmutableLedgerConflict("Step 9S ledger contains an incomplete morning assignment pair.")
        comparisons = {
            "source_step9l_batch_payload_hash": source_batch["batch_payload_hash"],
            "source_step9l_decision_set_hash": decision_set_hash,
            "registry_hash": registry_hash,
            "morning_state_snapshot_hash": state_hash,
            "primary_regime": regime,
            "natural_strategy_id": assignment["natural_strategy_id"],
            "coverage_control_id": assignment["mandatory_control_id"],
        }
        for field, expected in comparisons.items():
            if str(existing_assignment[field]) != str(expected):
                raise ImmutableLedgerConflict(f"Conflicting rerun changed Step 9S assignment field {field}.")
        if str(existing_plan["plan_payload_hash"]) != str(plan["plan_payload_hash"]):
            raise ImmutableLedgerConflict("Conflicting rerun changed the immutable mandatory coverage plan.")
        assignments = pd.DataFrame([existing_assignment])
        plans = pd.DataFrame([existing_plan])
        if export_outputs_after:
            export_outputs(ledger_db)
        return assignments, plans, False

    status = _new_prospective_status(
        session_date, now, str(source_batch["prospective_status"]), allow_late, simulated_clock
    )
    created = now.strftime("%Y-%m-%d %H:%M:%S%z")
    assignment_payload = {
        "assignment_id": assignment_id,
        "session_date": session_date,
        "prospective_status": status,
        "code_version": CODE_VERSION,
        "registry_hash": registry_hash,
        "historical_freeze_artifact_sha256": freeze["artifact_set_sha256"],
        "source_step9l_batch_id": source_batch["batch_id"],
        "source_step9l_batch_payload_hash": source_batch["batch_payload_hash"],
        "source_step9l_decision_set_hash": decision_set_hash,
        "morning_state_snapshot_hash": state_hash,
        "primary_regime": regime,
        "taxonomy_payload": taxonomy,
        "natural_strategy_id": assignment["natural_strategy_id"],
        "natural_maturity": assignment["natural_maturity"],
        "natural_source_kind": assignment["natural_source_kind"],
        "coverage_control_id": assignment["mandatory_control_id"],
        "coverage_plan_hash": plan["plan_payload_hash"],
    }
    assignment_row = {
        "assignment_id": assignment_id,
        "experiment_id": EXPERIMENT_ID,
        "session_date": session_date,
        "created_at_stockholm": created,
        "run_mode": "MORNING_ASSIGNMENT_SEAL",
        "prospective_status": status,
        "decision_time": DECISION_TIME,
        "assignment_deadline": ASSIGNMENT_DEADLINE,
        "coverage_entry_start": ENTRY_WINDOW_START,
        "code_version": CODE_VERSION,
        "registry_hash": registry_hash,
        "historical_freeze_id": freeze["freeze_id"],
        "historical_freeze_artifact_sha256": freeze["artifact_set_sha256"],
        "source_step9l_db": str(step9l_ledger_db),
        "source_step9l_batch_id": str(source_batch["batch_id"]),
        "source_step9l_batch_payload_hash": str(source_batch["batch_payload_hash"]),
        "source_step9l_decision_set_hash": decision_set_hash,
        "source_price_db": str(source_db),
        "morning_state_snapshot_hash": state_hash,
        "primary_regime": regime,
        "regime_confidence": _num(source_batch.get("regime_confidence")),
        "confidence_band": str(source_batch.get("confidence_band", "")),
        "direction_bias": str(source_batch.get("direction_bias", "")),
        "research_risk_multiplier": _num(source_batch.get("research_risk_multiplier")),
        "taxonomy_payload_json": _canonical_payload(taxonomy),
        "natural_strategy_id": str(assignment["natural_strategy_id"]),
        "natural_maturity": str(assignment["natural_maturity"]),
        "natural_source_kind": str(assignment["natural_source_kind"]),
        "coverage_control_id": str(assignment["mandatory_control_id"]),
        "coverage_plan_id": plan["plan_id"],
        "point_in_time_pass": 1,
        "router_active": 0,
        "order_sent": 0,
        "assignment_payload_hash": _payload_hash(assignment_payload),
    }
    plan_row = {"assignment_id": assignment_id, **plan}

    ledger_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        con.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(
            con, "step9s_assignments", "assignment_id", "assignment_payload_hash", assignment_row
        )
        _insert_immutable(con, "step9s_coverage_plans", "plan_id", "plan_payload_hash", plan_row)
        con.commit()
    if export_outputs_after:
        export_outputs(ledger_db)
    return pd.DataFrame([assignment_row]), pd.DataFrame([plan_row]), inserted


def _target_date_prices(prices: pd.DataFrame, session_date: str) -> pd.DataFrame:
    return prices[prices["date"].eq(session_date)].copy().sort_values(["ticker", "datetime"])


def _eod_price_hash(prices: pd.DataFrame, session_date: str) -> str:
    rows = _target_date_prices(prices, session_date)[
        ["datetime", "open", "high", "low", "close", "ticker"]
    ].to_dict("records")
    return _payload_hash(rows)


def _ensure_eod_ready(prices: pd.DataFrame, session_date: str) -> None:
    day = _target_date_prices(prices, session_date)
    if day.empty:
        raise SourceDataNotReady(f"No EOD price data found for {session_date}.")
    max_label = day["clock"].max()
    if str(max_label) < EOD_MINIMUM_LABEL:
        raise SourceDataNotReady(
            f"EOD price data for {session_date} ends at {max_label}; require at least {EOD_MINIMUM_LABEL}."
        )


def _first_entry_bar(
    prices: pd.DataFrame,
    session_date: str,
    ticker: str,
    start: str = ENTRY_WINDOW_START,
    end: str = ENTRY_WINDOW_END,
) -> pd.Series | None:
    rows = prices[
        prices["date"].eq(session_date)
        & prices["ticker"].eq(ticker)
        & prices["clock"].ge(start)
        & prices["clock"].le(end)
    ].sort_values("datetime")
    return None if rows.empty else rows.iloc[0]


def _execute_coverage(plan: dict[str, Any], assignment: dict[str, Any], prices: pd.DataFrame) -> dict[str, Any]:
    session_date = str(plan["session_date"])
    regime = str(plan["primary_regime"])
    pool = json.loads(str(plan["candidate_pool_json"]))
    notional = float(plan["notional_sek"])
    cost_rate = float(plan["cost_rate"])
    taxonomy = json.loads(str(assignment["taxonomy_payload_json"]))

    for candidate in pool:
        if candidate["idea_type"] == "SINGLE":
            ticker = str(candidate["ticker"])
            entry_bar = _first_entry_bar(prices, session_date, ticker)
            if entry_bar is None:
                continue
            entry_time = pd.Timestamp(entry_bar["datetime"])
            entry_price = _num(entry_bar.get("open"), _num(entry_bar.get("close")))
            source = pd.Series(candidate)
            side, stop, target, exit_cutoff = step9s_historical._single_control_levels(
                source, pd.Series(taxonomy), entry_price
            )
            execution = step9s_historical._execute_single(
                prices=prices,
                date=session_date,
                ticker=ticker,
                side=side,
                entry_time=entry_time,
                entry_price=entry_price,
                stop_price=stop,
                target_price=target,
                exit_cutoff=exit_cutoff,
            )
            risk = entry_price - stop if side == "LONG" else stop - entry_price
            reward = execution["exit_price"] - entry_price if side == "LONG" else entry_price - execution["exit_price"]
            gross_return = float(execution["gross_return"])
            cost = notional * cost_rate
            return {
                "used_candidate_rank": int(candidate["candidate_rank"]),
                "idea_type": "SINGLE",
                "direction": side,
                "ticker": ticker,
                "paired_ticker": "",
                "long_ticker": ticker if side == "LONG" else "",
                "short_ticker": ticker if side == "SHORT" else "",
                "entry_time": str(entry_time),
                "entry_price": entry_price,
                "stop_price": stop,
                "target_price": target,
                "pair_entry_long_price": np.nan,
                "pair_entry_short_price": np.nan,
                "pair_stop_return": np.nan,
                "pair_target_return": np.nan,
                "exit_time": str(execution["exit_time"]),
                "exit_price": execution["exit_price"],
                "pair_exit_long_price": np.nan,
                "pair_exit_short_price": np.nan,
                "exit_reason": execution["exit_reason"],
                "gross_return": gross_return,
                "risk_pct_at_entry": risk / entry_price if entry_price > 0 else np.nan,
                "r_multiple_achieved": reward / risk if risk > 0 else np.nan,
                "notional_sek": notional,
                "cost_sek": cost,
                "net_pnl_sek": notional * gross_return - cost,
            }

        long_ticker = str(candidate["long_ticker"])
        short_ticker = str(candidate["short_ticker"])
        long_rows = _target_date_prices(prices, session_date)
        long_rows = long_rows[long_rows["ticker"].eq(long_ticker)]
        short_rows = _target_date_prices(prices, session_date)
        short_rows = short_rows[short_rows["ticker"].eq(short_ticker)]
        common = step9b._common_pair_bars(long_rows, short_rows)
        entry = step9b._first_bar_between(common, ENTRY_WINDOW_START, ENTRY_WINDOW_END)
        if entry is None:
            continue
        entry_time = pd.Timestamp(entry["datetime"])
        entry_long = _num(entry.get("long_open"), _num(entry.get("long_close")))
        entry_short = _num(entry.get("short_open"), _num(entry.get("short_close")))
        execution = step9b._pair_execution(
            common=common,
            entry_time=entry_time,
            entry_long_price=entry_long,
            entry_short_price=entry_short,
            stop_return=float(candidate["pair_stop_return"]),
            target_return=float(candidate["pair_target_return"]),
            exit_cutoff=str(candidate["exit_cutoff"]),
        )
        if execution is None:
            continue
        gross_return = float(execution.gross_return)
        cost = notional * cost_rate
        return {
            "used_candidate_rank": int(candidate["candidate_rank"]),
            "idea_type": "PAIR",
            "direction": "LONG_SHORT",
            "ticker": long_ticker,
            "paired_ticker": short_ticker,
            "long_ticker": long_ticker,
            "short_ticker": short_ticker,
            "entry_time": str(entry_time),
            "entry_price": np.nan,
            "stop_price": np.nan,
            "target_price": np.nan,
            "pair_entry_long_price": entry_long,
            "pair_entry_short_price": entry_short,
            "pair_stop_return": float(candidate["pair_stop_return"]),
            "pair_target_return": float(candidate["pair_target_return"]),
            "exit_time": str(execution.exit_time),
            "exit_price": np.nan,
            "pair_exit_long_price": execution.exit_long_price,
            "pair_exit_short_price": execution.exit_short_price,
            "exit_reason": execution.exit_reason,
            "gross_return": gross_return,
            "risk_pct_at_entry": abs(float(candidate["pair_stop_return"])),
            "r_multiple_achieved": gross_return / abs(float(candidate["pair_stop_return"])) if float(candidate["pair_stop_return"]) < 0 else np.nan,
            "notional_sek": notional,
            "cost_sek": cost,
            "net_pnl_sek": notional * gross_return - cost,
        }
    raise SourceDataNotReady(
        f"No executable {ENTRY_WINDOW_START}-{ENTRY_WINDOW_END} coverage entry was found for any sealed candidate."
    )


def _normalize_step9l_natural(
    assignment: dict[str, Any],
    outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = [
        row for row in outcomes
        if str(row["contract_id"]) == str(assignment["natural_strategy_id"])
        and str(row["test_role"]) == "PRIMARY_HYPOTHESIS"
        and str(row["outcome_status"]).endswith("TRADE_COMPLETED")
    ]
    rows: list[dict[str, Any]] = []
    for source in selected:
        rows.append({
            "source_kind": "STEP9L_V3_LEDGER",
            "source_trade_id": str(source["outcome_id"]),
            "idea_type": "SINGLE",
            "direction": str(source.get("direction", "")),
            "ticker": str(source.get("ticker", "")),
            "paired_ticker": "",
            "long_ticker": str(source.get("ticker", "")) if source.get("direction") == "LONG" else "",
            "short_ticker": str(source.get("ticker", "")) if source.get("direction") == "SHORT" else "",
            "entry_time": str(source.get("entry_time", "")),
            "entry_price": _num(source.get("entry_price")),
            "stop_price": _num(source.get("stop_price")),
            "target_price": _num(source.get("target_price")),
            "pair_entry_long_price": np.nan,
            "pair_entry_short_price": np.nan,
            "pair_stop_return": np.nan,
            "pair_target_return": np.nan,
            "exit_time": str(source.get("exit_time", "")),
            "exit_price": _num(source.get("exit_price")),
            "pair_exit_long_price": np.nan,
            "pair_exit_short_price": np.nan,
            "exit_reason": str(source.get("exit_reason", "")),
            "gross_return": _num(source.get("gross_return")),
            "notional_sek": np.nan,
            "cost_sek": np.nan,
            "net_pnl_sek": _num(source.get("risk_capped_net_pnl_sek"), 0.0),
            "point_in_time_pass": int(_bool(source.get("point_in_time_pass"))),
        })
    return rows


def _local_natural_trades(
    assignment: dict[str, Any],
    prices: pd.DataFrame,
) -> list[dict[str, Any]]:
    session_date = str(assignment["session_date"])
    regime = str(assignment["primary_regime"])
    taxonomy = json.loads(str(assignment["taxonomy_payload_json"]))
    session = {**taxonomy, "date": session_date, "primary_regime": regime}
    scoped = prices[prices["date"].le(session_date)].copy()
    price_input = scoped.assign(date=pd.to_datetime(scoped["date"]).dt.date)
    daily_reference = build_daily_reference(price_input)
    state, bars_lookup = step9b.build_market_state(price_input, daily_reference, {session_date})
    day_state = state[state["date"].astype(str).eq(session_date)].copy()
    trades: list[dict[str, Any]] = []
    legs: list[dict[str, Any]] = []
    if regime in {"RECOVERY", "TREND_DOWN"}:
        step9b._generate_single_candidates(session, day_state, bars_lookup, trades, legs)
        rows = []
        for source in trades:
            rows.append({
                "source_kind": "STEP9A_LOCAL_SIMULATION",
                "source_trade_id": str(source["trade_id"]),
                "idea_type": str(source.get("idea_type", "SINGLE")),
                "direction": str(source.get("direction", "")),
                "ticker": str(source.get("ticker", "")),
                "paired_ticker": str(source.get("paired_ticker", "")),
                "long_ticker": str(source.get("long_ticker", "")),
                "short_ticker": str(source.get("short_ticker", "")),
                "entry_time": str(source.get("entry_time", "")),
                "entry_price": _num(source.get("entry_price")),
                "stop_price": _num(source.get("stop_price")),
                "target_price": _num(source.get("target_price")),
                "pair_entry_long_price": _num(source.get("pair_entry_long_price")),
                "pair_entry_short_price": _num(source.get("pair_entry_short_price")),
                "pair_stop_return": _num(source.get("pair_stop_return")),
                "pair_target_return": _num(source.get("pair_target_return")),
                "exit_time": str(source.get("exit_time", "")),
                "exit_price": _num(source.get("exit_price")),
                "pair_exit_long_price": _num(source.get("pair_exit_long_price")),
                "pair_exit_short_price": _num(source.get("pair_exit_short_price")),
                "exit_reason": str(source.get("exit_reason", "")),
                "gross_return": _num(source.get("gross_return")),
                "notional_sek": _num(source.get("notional_sek")),
                "cost_sek": _num(source.get("cost_sek")),
                "net_pnl_sek": _num(source.get("net_pnl_sek"), 0.0),
                "point_in_time_pass": int(_bool(source.get("point_in_time_pass"))),
            })
        return rows
    if regime == "DATA_LIMITED_DEFENSIVE":
        step9b._pair_candidate(session, day_state, bars_lookup, trades, legs)
        source_rows = trades
        source_kind = "STEP9A_LOCAL_SIMULATION"
    elif regime == "DEFENSIVE_MIXED":
        challenger = step9d.CHALLENGER_BY_ID["PAIR_SPREAD_CONVERGENCE_V1"]
        step9d._pair_candidate_for_challenger(session, challenger, day_state, bars_lookup, trades, legs)
        source_rows = trades
        source_kind = "STEP9D_LOCAL_SIMULATION"
    else:
        raise ValueError(f"No local natural strategy evaluator for {regime}")
    rows = []
    for source in source_rows:
        rows.append({
            "source_kind": source_kind,
            "source_trade_id": str(source["trade_id"]),
            "idea_type": str(source.get("idea_type", "PAIR")),
            "direction": str(source.get("direction", "LONG_SHORT")),
            "ticker": str(source.get("ticker", "")),
            "paired_ticker": str(source.get("paired_ticker", "")),
            "long_ticker": str(source.get("long_ticker", "")),
            "short_ticker": str(source.get("short_ticker", "")),
            "entry_time": str(source.get("entry_time", "")),
            "entry_price": _num(source.get("entry_price")),
            "stop_price": _num(source.get("stop_price")),
            "target_price": _num(source.get("target_price")),
            "pair_entry_long_price": _num(source.get("pair_entry_long_price")),
            "pair_entry_short_price": _num(source.get("pair_entry_short_price")),
            "pair_stop_return": _num(source.get("pair_stop_return")),
            "pair_target_return": _num(source.get("pair_target_return")),
            "exit_time": str(source.get("exit_time", "")),
            "exit_price": _num(source.get("exit_price")),
            "pair_exit_long_price": _num(source.get("pair_exit_long_price")),
            "pair_exit_short_price": _num(source.get("pair_exit_short_price")),
            "exit_reason": str(source.get("exit_reason", "")),
            "gross_return": _num(source.get("gross_return")),
            "notional_sek": _num(source.get("risk_capped_notional_sek"), _num(source.get("notional_sek"))),
            "cost_sek": _num(source.get("risk_capped_cost_sek"), _num(source.get("cost_sek"))),
            "net_pnl_sek": _num(source.get("risk_capped_net_pnl_sek"), _num(source.get("net_pnl_sek"), 0.0)),
            "point_in_time_pass": int(_bool(source.get("point_in_time_pass"))),
        })
    return rows


def _existing_outcome_batch(ledger_db: Path, session_date: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]:
    if not ledger_db.exists():
        return None, [], None
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        con.row_factory = sqlite3.Row
        batch = con.execute(
            "SELECT * FROM step9s_outcome_batches WHERE session_date = ?", (session_date,)
        ).fetchone()
        if not batch:
            return None, [], None
        natural = [
            dict(row) for row in con.execute(
                "SELECT * FROM step9s_natural_outcomes WHERE outcome_batch_id = ? ORDER BY natural_outcome_id",
                (batch["outcome_batch_id"],),
            ).fetchall()
        ]
        coverage = con.execute(
            "SELECT * FROM step9s_coverage_outcomes WHERE outcome_batch_id = ?",
            (batch["outcome_batch_id"],),
        ).fetchone()
    return dict(batch), natural, dict(coverage) if coverage else None


def evaluate_eod(
    session_date: str,
    now: datetime,
    source_db: Path = DEFAULT_SOURCE_DB,
    step9l_ledger_db: Path = DEFAULT_STEP9L_LEDGER_DB,
    ledger_db: Path = DEFAULT_LEDGER_DB,
    allow_early: bool = False,
    export_outputs_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    assignment, plan = _read_existing_assignment(ledger_db, session_date)
    if not assignment or not plan:
        raise SourceDataNotReady(f"No sealed Step 9S morning assignment exists for {session_date}.")
    source_batch, _, decision_set_hash = _read_step9l_morning(session_date, step9l_ledger_db)
    if str(source_batch["batch_payload_hash"]) != str(assignment["source_step9l_batch_payload_hash"]):
        raise ImmutableLedgerConflict("The source Step 9L morning batch changed after Step 9S assignment.")
    if decision_set_hash != str(assignment["source_step9l_decision_set_hash"]):
        raise ImmutableLedgerConflict("The source Step 9L morning decisions changed after Step 9S assignment.")
    step9l_eod_batch, step9l_outcomes, outcome_set_hash = _read_step9l_eod(
        session_date, step9l_ledger_db, str(source_batch["batch_id"])
    )
    if not allow_early:
        if now.date().isoformat() != session_date or now.time().replace(tzinfo=None) < _clock_to_time(EOD_TIME):
            raise SourceDataNotReady(f"Step 9S EOD evaluation is not allowed before {EOD_TIME} Stockholm time.")
    prices = _load_prices_read_only(source_db)
    _ensure_eod_ready(prices, session_date)
    price_hash = _eod_price_hash(prices, session_date)
    coverage = _execute_coverage(plan, assignment, prices)
    if assignment["natural_source_kind"] == "STEP9L_V3_LEDGER":
        natural = _normalize_step9l_natural(assignment, step9l_outcomes)
    else:
        natural = _local_natural_trades(assignment, prices)

    outcome_batch_id = f"S9S-{session_date.replace('-', '')}-EOD"
    assignment_id = str(assignment["assignment_id"])
    natural_rows: list[dict[str, Any]] = []
    for index, source in enumerate(natural, start=1):
        row = {
            "natural_outcome_id": f"{outcome_batch_id}|NATURAL|{index:03d}|{_payload_hash(source)[:12]}",
            "outcome_batch_id": outcome_batch_id,
            "assignment_id": assignment_id,
            "session_date": session_date,
            "primary_regime": str(assignment["primary_regime"]),
            "assigned_strategy_id": str(assignment["natural_strategy_id"]),
            **source,
            "router_active": 0,
            "order_sent": 0,
        }
        row["row_payload_hash"] = _payload_hash(row)
        natural_rows.append(row)

    coverage_row = {
        "coverage_outcome_id": f"{outcome_batch_id}|MANDATORY",
        "outcome_batch_id": outcome_batch_id,
        "assignment_id": assignment_id,
        "plan_id": str(plan["plan_id"]),
        "session_date": session_date,
        "primary_regime": str(assignment["primary_regime"]),
        "coverage_control_id": str(assignment["coverage_control_id"]),
        **coverage,
        "point_in_time_pass": 1,
        "execution_invariant_pass": 1,
        "router_active": 0,
        "order_sent": 0,
    }
    coverage_row["row_payload_hash"] = _payload_hash(coverage_row)
    natural_net = float(sum(_num(row["net_pnl_sek"], 0.0) for row in natural_rows))
    coverage_net = float(coverage_row["net_pnl_sek"])
    outcome_payload = {
        "outcome_batch_id": outcome_batch_id,
        "assignment_id": assignment_id,
        "session_date": session_date,
        "code_version": CODE_VERSION,
        "source_step9l_outcome_batch_id": step9l_eod_batch["outcome_batch_id"],
        "source_step9l_outcome_payload_hash": step9l_eod_batch["outcome_payload_hash"],
        "source_step9l_outcome_set_hash": outcome_set_hash,
        "eod_price_snapshot_hash": price_hash,
        "natural_row_hashes": [row["row_payload_hash"] for row in natural_rows],
        "coverage_row_hash": coverage_row["row_payload_hash"],
    }
    batch_row = {
        "outcome_batch_id": outcome_batch_id,
        "assignment_id": assignment_id,
        "session_date": session_date,
        "created_at_stockholm": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "code_version": CODE_VERSION,
        "source_step9l_outcome_batch_id": str(step9l_eod_batch["outcome_batch_id"]),
        "source_step9l_outcome_payload_hash": str(step9l_eod_batch["outcome_payload_hash"]),
        "source_step9l_outcome_set_hash": outcome_set_hash,
        "eod_price_snapshot_hash": price_hash,
        "eod_complete": 1,
        "natural_status": "NATURAL_TRADES_COMPLETED" if natural_rows else "NO_NATURAL_TRIGGER_TRADE",
        "natural_trade_count": len(natural_rows),
        "coverage_trade_count": 1,
        "natural_net_pnl_sek": natural_net,
        "coverage_net_pnl_sek": coverage_net,
        "router_active": 0,
        "order_sent": 0,
        "outcome_payload_hash": _payload_hash(outcome_payload),
    }

    existing_batch, existing_natural, existing_coverage = _existing_outcome_batch(ledger_db, session_date)
    if existing_batch:
        if str(existing_batch["outcome_payload_hash"]) != str(batch_row["outcome_payload_hash"]):
            raise ImmutableLedgerConflict("Conflicting Step 9S EOD rerun changed the immutable outcome payload.")
        if not existing_coverage or str(existing_coverage["row_payload_hash"]) != str(coverage_row["row_payload_hash"]):
            raise ImmutableLedgerConflict("Conflicting Step 9S EOD rerun changed the mandatory coverage outcome.")
        existing_hashes = sorted(str(row["row_payload_hash"]) for row in existing_natural)
        current_hashes = sorted(str(row["row_payload_hash"]) for row in natural_rows)
        if existing_hashes != current_hashes:
            raise ImmutableLedgerConflict("Conflicting Step 9S EOD rerun changed natural outcomes.")
        if export_outputs_after:
            export_outputs(ledger_db)
        return pd.DataFrame([existing_batch]), pd.DataFrame(existing_natural), pd.DataFrame([existing_coverage]), False

    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        con.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(
            con, "step9s_outcome_batches", "outcome_batch_id", "outcome_payload_hash", batch_row
        )
        for row in natural_rows:
            _insert_immutable(
                con, "step9s_natural_outcomes", "natural_outcome_id", "row_payload_hash", row
            )
        _insert_immutable(
            con, "step9s_coverage_outcomes", "coverage_outcome_id", "row_payload_hash", coverage_row
        )
        con.commit()
    if export_outputs_after:
        export_outputs(ledger_db)
    return pd.DataFrame([batch_row]), pd.DataFrame(natural_rows), pd.DataFrame([coverage_row]), inserted


def _read_table(con: sqlite3.Connection, table: str) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {table}", con)


def audit_ledger(ledger_db: Path = DEFAULT_LEDGER_DB) -> pd.DataFrame:
    if not ledger_db.is_file():
        return pd.DataFrame([{"check": "ledger_exists", "passed": False, "detail": str(ledger_db)}])
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        assignments = _read_table(con, "step9s_assignments")
        plans = _read_table(con, "step9s_coverage_plans")
        batches = _read_table(con, "step9s_outcome_batches")
        natural = _read_table(con, "step9s_natural_outcomes")
        coverage = _read_table(con, "step9s_coverage_outcomes")
    def any_flag(frames: list[pd.DataFrame], column: str) -> bool:
        series = [frame[column] for frame in frames if column in frame.columns and not frame.empty]
        return bool(pd.concat(series, ignore_index=True).fillna(0).astype(bool).any()) if series else False

    ledger_frames = [assignments, plans, batches, natural, coverage]
    checks = [
        ("sqlite_integrity", integrity == "ok", integrity),
        ("one_assignment_per_session", assignments["session_date"].is_unique if not assignments.empty else True, len(assignments)),
        ("one_plan_per_assignment", len(plans) == len(assignments), f"{len(plans)}/{len(assignments)}"),
        ("one_coverage_outcome_per_eod_session", len(coverage) == len(batches), f"{len(coverage)}/{len(batches)}"),
        ("coverage_count_sealed_as_one", batches["coverage_trade_count"].eq(1).all() if not batches.empty else True, len(batches)),
        ("all_assignment_regimes_known", assignments["primary_regime"].isin(REGISTRY_BY_REGIME).all() if not assignments.empty else True, ""),
        ("all_point_in_time", assignments["point_in_time_pass"].eq(1).all() and plans["point_in_time_pass"].eq(1).all() if not assignments.empty else True, ""),
        ("router_inactive", not any_flag(ledger_frames, "router_active"), ""),
        ("no_orders", not any_flag(ledger_frames, "order_sent"), ""),
    ]
    return pd.DataFrame([{"check": name, "passed": bool(passed), "detail": detail} for name, passed, detail in checks])


def export_outputs(ledger_db: Path = DEFAULT_LEDGER_DB, output_dir: Path = DEFAULT_EXPORT_DIR) -> None:
    if not ledger_db.is_file():
        raise FileNotFoundError(ledger_db)
    output_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        assignments = _read_table(con, "step9s_assignments")
        plans = _read_table(con, "step9s_coverage_plans")
        batches = _read_table(con, "step9s_outcome_batches")
        natural = _read_table(con, "step9s_natural_outcomes")
        coverage = _read_table(con, "step9s_coverage_outcomes")
    assignments.to_csv(output_dir / ASSIGNMENT_EXPORT, index=False)
    plans.to_csv(output_dir / PLAN_EXPORT, index=False)
    batches.to_csv(output_dir / OUTCOME_BATCH_EXPORT, index=False)
    natural.to_csv(output_dir / NATURAL_OUTCOME_EXPORT, index=False)
    coverage.to_csv(output_dir / COVERAGE_OUTCOME_EXPORT, index=False)
    pd.DataFrame(ASSIGNMENT_REGISTRY).to_csv(output_dir / REGISTRY_EXPORT, index=False)
    audit = audit_ledger(ledger_db)
    audit.to_csv(output_dir / AUDIT_EXPORT, index=False)
    summary = pd.DataFrame([{
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "assignment_sessions": int(len(assignments)),
        "recognized_regimes": int(assignments["primary_regime"].nunique()) if not assignments.empty else 0,
        "eod_sessions": int(len(batches)),
        "natural_trades": int(len(natural)),
        "mandatory_coverage_trades": int(len(coverage)),
        "complete_eod_trade_coverage_rate": float(len(coverage) / len(batches)) if len(batches) else np.nan,
        "natural_net_pnl_sek": float(pd.to_numeric(natural.get("net_pnl_sek", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()),
        "mandatory_coverage_net_pnl_sek": float(pd.to_numeric(coverage.get("net_pnl_sek", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()),
        "router_active": False,
        "orders_sent": False,
        "audit_pass": bool(audit["passed"].all()),
    }])
    summary.to_csv(output_dir / SUMMARY_EXPORT, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 9S prospective complete-trade-coverage shadow engine. Research only; no routing."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    morning = subparsers.add_parser("morning")
    morning.add_argument("--date")
    morning.add_argument("--as-of")
    morning.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    morning.add_argument("--step9l-ledger-db", type=Path, default=DEFAULT_STEP9L_LEDGER_DB)
    morning.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    morning.add_argument("--allow-late-reconstruction", action="store_true")

    eod = subparsers.add_parser("eod")
    eod.add_argument("--date")
    eod.add_argument("--as-of")
    eod.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    eod.add_argument("--step9l-ledger-db", type=Path, default=DEFAULT_STEP9L_LEDGER_DB)
    eod.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    eod.add_argument("--allow-early-evaluation", action="store_true")

    export = subparsers.add_parser("export")
    export.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    export.add_argument("--output-dir", type=Path, default=DEFAULT_EXPORT_DIR)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--ledger-db", type=Path, default=DEFAULT_LEDGER_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "export":
        export_outputs(args.ledger_db, args.output_dir)
        print("Step 9S prospective immutable ledger exports refreshed.")
        return
    if args.command == "audit":
        audit = audit_ledger(args.ledger_db)
        print(audit.to_string(index=False))
        if not audit["passed"].all():
            raise SystemExit(1)
        return

    now = _parse_stockholm_datetime(args.as_of)
    target = _target_date(args.date, now)
    if args.command == "morning":
        print("\n=== STEP 9S PROSPECTIVE CONTINGENCY MORNING ASSIGNMENT ===")
        print(f"Experiment         : {EXPERIMENT_ID}")
        print(f"Session date       : {target}")
        print(f"As-of Stockholm    : {now:%Y-%m-%d %H:%M:%S %Z}")
        assignments, plans, inserted = seal_morning_assignment(
            session_date=target,
            now=now,
            source_db=args.source_db,
            step9l_ledger_db=args.step9l_ledger_db,
            ledger_db=args.ledger_db,
            allow_late=args.allow_late_reconstruction,
            simulated_clock=bool(args.as_of),
            export_outputs_after=True,
        )
        assignment = assignments.iloc[0]
        plan = plans.iloc[0]
        print(f"Ledger action      : {'SEALED_NEW_ASSIGNMENT' if inserted else 'EXISTING_IDENTICAL_ASSIGNMENT_RETURNED'}")
        print(f"Prospective status : {assignment['prospective_status']}")
        print(f"Primary regime     : {assignment['primary_regime']} ({float(assignment['regime_confidence']):.1%})")
        print(f"Natural strategy   : {assignment['natural_strategy_id']}")
        print(f"Coverage control   : {assignment['coverage_control_id']}")
        if plan["idea_type"] == "PAIR":
            print(f"Mandatory plan     : LONG {plan['long_ticker']} / SHORT {plan['short_ticker']} from {ENTRY_WINDOW_START}")
        else:
            print(f"Mandatory plan     : {plan['direction']} {plan['ticker']} from {ENTRY_WINDOW_START}")
        print("ROUTER ACTIVE      : FALSE")
        print("NO ORDER WAS SENT")
        return

    print("\n=== STEP 9S PROSPECTIVE CONTINGENCY END-OF-DAY EVALUATION ===")
    print(f"Session date       : {target}")
    print(f"As-of Stockholm    : {now:%Y-%m-%d %H:%M:%S %Z}")
    batches, natural, coverage, inserted = evaluate_eod(
        session_date=target,
        now=now,
        source_db=args.source_db,
        step9l_ledger_db=args.step9l_ledger_db,
        ledger_db=args.ledger_db,
        allow_early=args.allow_early_evaluation,
        export_outputs_after=True,
    )
    batch = batches.iloc[0]
    mandatory = coverage.iloc[0]
    print(f"Ledger action      : {'SEALED_NEW_OUTCOME_BATCH' if inserted else 'EXISTING_IDENTICAL_OUTCOME_RETURNED'}")
    print(f"Natural trades     : {int(batch['natural_trade_count'])} / {float(batch['natural_net_pnl_sek']):.6f} SEK")
    print(f"Mandatory coverage : 1 / {float(batch['coverage_net_pnl_sek']):.6f} SEK")
    print(f"Coverage exit      : {mandatory['exit_reason']} at {mandatory['exit_time']}")
    print("COMPLETE TRADE COVERAGE: PASSED")
    print("ROUTER ACTIVE      : FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
