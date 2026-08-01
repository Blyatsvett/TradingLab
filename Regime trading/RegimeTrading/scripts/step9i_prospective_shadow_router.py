from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import date as date_type
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.core.stage_registry import resolve_stage_path
from RegimeTrading.scripts.research_regime_aware_gap_recovery import load_intraday_prices
from RegimeTrading.scripts import step7_regime_feature_foundation as step7
from RegimeTrading.scripts import step8_provisional_regime_taxonomy as step8
from RegimeTrading.scripts import step9b_baseline_trade_generation as step9b
from RegimeTrading.scripts import step9e_instrument_sector_taxonomy as step9e
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h


EXPERIMENT_ID = "PROSPECTIVE_SHADOW_ROUTER_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_PROSPECTIVE_SHADOW_NOT_ROUTER_ACTIVE"
CODE_VERSION = "STEP9I_PROSPECTIVE_SHADOW_V1_LOCKED_2026_07_24"
SHADOW_UNIVERSE_VERSION = "STEP9I_REGIME_SOURCE_PLUS_STEP9H_HOLDOUT_V1"
DECISION_TIME = "09:45"
LATEST_ALLOWED_BAR_LABEL = "09:40"
SEAL_DEADLINE = "09:49:30"
EOD_MINIMUM_LABEL = "16:25"
LOCAL_TZ = ZoneInfo("Europe/Stockholm")

SHADOW_INTRADAY_DB = resolve_stage_path("prices")
SHADOW_LEDGER_DB = DATA_DIR / "step9i_shadow_ledger.db"

DECISION_BATCH_FILE = DATA_DIR / "step9i_shadow_decision_batches.csv"
DECISION_FILE = DATA_DIR / "step9i_shadow_decisions.csv"
OUTCOME_BATCH_FILE = DATA_DIR / "step9i_shadow_outcome_batches.csv"
OUTCOME_FILE = DATA_DIR / "step9i_shadow_outcomes.csv"
PERFORMANCE_FILE = DATA_DIR / "step9i_shadow_performance.csv"
MULTIPLE_TESTING_FILE = DATA_DIR / "step9i_shadow_multiple_testing.csv"
AUDIT_FILE = DATA_DIR / "step9i_shadow_audit.csv"
SUMMARY_FILE = DATA_DIR / "step9i_shadow_summary.csv"
CONTRACT_REGISTRY_FILE = DATA_DIR / "step9i_shadow_contract_registry.csv"

MIN_TRADES = 30
MIN_SESSIONS = 15
MIN_COMPANIES = 10
MIN_SECTORS = 4
BOOTSTRAP_ITERATIONS = 5000
SIGN_FLIP_ITERATIONS = 10000
RANDOM_SEED = 20260724

REGIME_SOURCE_TICKERS = tuple(step9b.GAP_RECOVERY_TICKERS)
HOLDOUT_TICKERS = tuple(row["ticker"] for row in step9h.HOLDOUT_INSTRUMENTS)


class ImmutableLedgerConflict(RuntimeError):
    pass


class ShadowDataNotReady(RuntimeError):
    pass


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _clean_scalar(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_clean_scalar(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date_type)):
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S") if not isinstance(value, date_type) or isinstance(value, datetime) else value.isoformat()
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


def _canonical_payload(payload: dict[str, Any]) -> str:
    clean = {str(key): _clean_scalar(value) for key, value in sorted(payload.items())}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def _registry_hash() -> str:
    rows = [{k: _clean_scalar(v) for k, v in row.items()} for row in step9h.CONTRACTS]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _universe_hash() -> str:
    rows = sorted(list(REGIME_SOURCE_TICKERS) + list(HOLDOUT_TICKERS))
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def _bool(value: Any) -> bool:
    return step9g._bool(value)


def _num(value: Any, default: float = np.nan) -> float:
    return step9g._num(value, default)


def _now_stockholm() -> datetime:
    return datetime.now(LOCAL_TZ)


def _parse_stockholm_datetime(value: str | None) -> datetime:
    if not value:
        return _now_stockholm()
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(LOCAL_TZ)
    else:
        parsed = parsed.tz_convert(LOCAL_TZ)
    return parsed.to_pydatetime()


def _target_date(value: str | None, now: datetime) -> str:
    return str(pd.Timestamp(value).date()) if value else now.date().isoformat()


def _clock_tuple(value: str) -> time:
    return datetime.strptime(value, "%H:%M:%S" if value.count(":") == 2 else "%H:%M").time()


def _prospective_status(target_date: str, now: datetime, allow_late: bool) -> str:
    if target_date != now.date().isoformat():
        return "HISTORICAL_RECONSTRUCTION_NOT_CONFIRMATORY"
    if now.time() < _clock_tuple(DECISION_TIME):
        raise ShadowDataNotReady(f"The locked router decision time is {DECISION_TIME}; current Stockholm time is {now:%H:%M:%S}.")
    if now.time() <= _clock_tuple(SEAL_DEADLINE):
        return "PROSPECTIVE_CONFIRMATORY_ELIGIBLE"
    if allow_late:
        return "LATE_RECONSTRUCTION_NOT_CONFIRMATORY"
    raise ShadowDataNotReady(
        f"The prospective seal deadline {SEAL_DEADLINE} has passed. Rerun with --allow-late-reconstruction only for a clearly labelled non-confirmatory reconstruction."
    )


def _ensure_ledger_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shadow_decision_batches (
            batch_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            session_date TEXT NOT NULL UNIQUE,
            created_at_stockholm TEXT NOT NULL,
            run_mode TEXT NOT NULL,
            prospective_status TEXT NOT NULL,
            decision_time TEXT NOT NULL,
            seal_deadline TEXT NOT NULL,
            code_version TEXT NOT NULL,
            contract_registry_hash TEXT NOT NULL,
            universe_hash TEXT NOT NULL,
            source_db TEXT NOT NULL,
            source_max_datetime TEXT NOT NULL,
            regime_source_tickers_observed INTEGER NOT NULL,
            holdout_tickers_observed INTEGER NOT NULL,
            primary_regime TEXT NOT NULL,
            regime_confidence REAL,
            confidence_band TEXT NOT NULL,
            direction_bias TEXT NOT NULL,
            research_risk_multiplier REAL,
            research_max_concurrent_ideas INTEGER,
            regime_point_in_time_pass INTEGER NOT NULL,
            taxonomy_payload_json TEXT NOT NULL,
            decision_rows INTEGER NOT NULL,
            eligible_rows INTEGER NOT NULL,
            active_guardrails INTEGER NOT NULL,
            batch_payload_hash TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shadow_decisions (
            decision_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            session_date TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            test_role TEXT NOT NULL,
            ticker TEXT NOT NULL,
            company_id TEXT NOT NULL,
            broad_sector TEXT NOT NULL,
            primary_regime TEXT NOT NULL,
            regime_match INTEGER NOT NULL,
            ticker_relative_state TEXT NOT NULL,
            volatility_bucket TEXT NOT NULL,
            range_state TEXT NOT NULL,
            sector_direction_state TEXT NOT NULL,
            sector_direction_alignment TEXT NOT NULL,
            intended_side TEXT NOT NULL,
            contract_eligible INTEGER NOT NULL,
            decision_action TEXT NOT NULL,
            decision_reason TEXT NOT NULL,
            max_router_source_label TEXT NOT NULL,
            point_in_time_pass INTEGER NOT NULL,
            sealed_at_stockholm TEXT NOT NULL,
            row_payload_hash TEXT NOT NULL,
            UNIQUE(session_date, contract_id, ticker),
            FOREIGN KEY(batch_id) REFERENCES shadow_decision_batches(batch_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shadow_outcome_batches (
            outcome_batch_id TEXT PRIMARY KEY,
            decision_batch_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL UNIQUE,
            created_at_stockholm TEXT NOT NULL,
            code_version TEXT NOT NULL,
            source_db TEXT NOT NULL,
            source_max_datetime TEXT NOT NULL,
            eod_complete INTEGER NOT NULL,
            decision_rows INTEGER NOT NULL,
            outcome_rows INTEGER NOT NULL,
            completed_trades INTEGER NOT NULL,
            outcome_payload_hash TEXT NOT NULL,
            FOREIGN KEY(decision_batch_id) REFERENCES shadow_decision_batches(batch_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS shadow_outcomes (
            outcome_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL UNIQUE,
            outcome_batch_id TEXT NOT NULL,
            session_date TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            test_role TEXT NOT NULL,
            ticker TEXT NOT NULL,
            company_id TEXT NOT NULL,
            broad_sector TEXT NOT NULL,
            morning_contract_eligible INTEGER NOT NULL,
            candidate_generated INTEGER NOT NULL,
            selected_for_simulation INTEGER NOT NULL,
            setup_status TEXT NOT NULL,
            trigger_status TEXT NOT NULL,
            outcome_status TEXT NOT NULL,
            direction TEXT NOT NULL,
            signal_time TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            entry_price REAL,
            stop_price REAL,
            target_price REAL,
            exit_time TEXT NOT NULL,
            exit_price REAL,
            exit_reason TEXT NOT NULL,
            gross_return REAL,
            risk_pct_at_entry REAL,
            r_multiple_achieved REAL,
            equal_net_pnl_sek REAL,
            risk_capped_net_pnl_sek REAL,
            point_in_time_pass INTEGER NOT NULL,
            evaluated_at_stockholm TEXT NOT NULL,
            row_payload_hash TEXT NOT NULL,
            FOREIGN KEY(decision_id) REFERENCES shadow_decisions(decision_id),
            FOREIGN KEY(outcome_batch_id) REFERENCES shadow_outcome_batches(outcome_batch_id)
        )
        """
    )
    connection.commit()


def _read_table(connection: sqlite3.Connection, table: str) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {table}", connection)


def _insert_immutable(
    connection: sqlite3.Connection,
    table: str,
    key_column: str,
    hash_column: str,
    row: dict[str, Any],
) -> bool:
    existing = connection.execute(
        f"SELECT {hash_column} FROM {table} WHERE {key_column} = ?", (row[key_column],)
    ).fetchone()
    if existing:
        if str(existing[0]) != str(row[hash_column]):
            raise ImmutableLedgerConflict(
                f"Immutable conflict in {table} for {key_column}={row[key_column]}. Existing ledger data was not changed."
            )
        return False
    columns = list(row)
    placeholders = ",".join(["?"] * len(columns))
    connection.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        tuple(_clean_scalar(row[column]) for column in columns),
    )
    return True


def load_shadow_prices(db_path: Path = SHADOW_INTRADAY_DB) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "ticker", "date"])
    return load_intraday_prices(db_path)


def _point_in_time_prices(prices: pd.DataFrame, target_date: str) -> pd.DataFrame:
    frame = prices.copy()
    if frame.empty:
        return frame
    frame["date_str"] = frame["date"].astype(str)
    clocks = frame["datetime"].dt.strftime("%H:%M")
    mask = frame["date_str"].lt(target_date) | (
        frame["date_str"].eq(target_date) & clocks.le(LATEST_ALLOWED_BAR_LABEL)
    )
    return frame[mask].drop(columns=["date_str"]).copy()


def _prices_through_date(prices: pd.DataFrame, target_date: str) -> pd.DataFrame:
    frame = prices.copy()
    if frame.empty:
        return frame
    return frame[frame["date"].astype(str).le(target_date)].copy()


@contextmanager
def _patched_regime_source_tickers():
    old_feature = list(step7.GAP_RECOVERY_TICKERS)
    try:
        step7.GAP_RECOVERY_TICKERS = list(REGIME_SOURCE_TICKERS)
        yield
    finally:
        step7.GAP_RECOVERY_TICKERS = old_feature


@contextmanager
def _patched_holdout_tickers():
    old = list(step9b.GAP_RECOVERY_TICKERS)
    try:
        step9b.GAP_RECOVERY_TICKERS = list(HOLDOUT_TICKERS)
        yield
    finally:
        step9b.GAP_RECOVERY_TICKERS = old


def build_current_regime(prices: pd.DataFrame, target_date: str) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    regime_prices = prices[prices["ticker"].isin(REGIME_SOURCE_TICKERS)].copy()
    pit = _point_in_time_prices(regime_prices, target_date)
    if pit.empty or target_date not in set(pit["date"].astype(str)):
        raise ShadowDataNotReady(f"No regime-source bars are available for {target_date} through {LATEST_ALLOWED_BAR_LABEL}.")
    with _patched_regime_source_tickers():
        foundation = step7.build_feature_foundation(pit)
    taxonomy = step8.build_daily_taxonomy(foundation.daily_features)
    target = taxonomy[taxonomy["date"].astype(str).eq(target_date)]
    if target.empty:
        raise ShadowDataNotReady(f"The frozen taxonomy could not classify {target_date}.")
    row = target.iloc[-1]
    if not _bool(row.get("point_in_time_safe")) or not _bool(row.get("minimum_regime_feature_ready")):
        raise ShadowDataNotReady(
            f"Regime inputs for {target_date} failed minimum point-in-time readiness: {row.get('feature_row_status', '')}."
        )
    return row, foundation.daily_features, foundation.audit


def build_morning_decisions(prices: pd.DataFrame, target_date: str) -> tuple[pd.Series, pd.DataFrame, dict[str, int]]:
    taxonomy_row, _, _ = build_current_regime(prices, target_date)
    static = step9h.build_holdout_static()
    pit_holdout = _point_in_time_prices(prices[prices["ticker"].isin(HOLDOUT_TICKERS)].copy(), target_date)
    if pit_holdout.empty:
        raise ShadowDataNotReady("No Step 9H holdout bars are available in the Step 9I shadow database.")

    characteristics, _, _, _ = step9e.build_point_in_time_characteristics(pit_holdout, static)
    characteristics["date"] = characteristics["date"].astype(str)
    strict_keys = step9h._strict_early_complete_keys(pit_holdout)
    strict_keys["date"] = strict_keys["date"].astype(str)
    execution_characteristics = characteristics.merge(
        strict_keys.assign(strict_early_complete=True),
        on=["date", "ticker"],
        how="inner",
        validate="one_to_one",
    ).drop(columns=["strict_early_complete"])

    daily = step9e._daily_input(pit_holdout, static)
    if not daily.empty:
        daily["date"] = daily["date"].astype(str)
        daily = daily.merge(strict_keys, on=["date", "ticker"], how="inner", validate="one_to_one")
    group_states = step9e.build_group_daily_state(daily) if not daily.empty else pd.DataFrame(columns=step9e.GROUP_STATE_COLUMNS)
    daily_reference = step9b.build_daily_reference(pit_holdout)
    with _patched_holdout_tickers():
        raw_states, _ = step9b.build_market_state(pit_holdout, daily_reference, {target_date})
    states = step9g.enrich_market_states(raw_states, static, execution_characteristics, group_states)
    states = states[states["date"].astype(str).eq(target_date)].copy()
    if not states.empty:
        states["date"] = states["date"].astype(str)

    static_lookup = static.set_index("ticker").to_dict("index")
    state_lookup = states.set_index("ticker").to_dict("index") if not states.empty else {}
    strict_target_tickers = set(strict_keys[strict_keys["date"].eq(target_date)]["ticker"].astype(str))
    primary_regime = str(taxonomy_row["primary_regime"])
    rows: list[dict[str, Any]] = []

    for contract in step9h.CONTRACTS:
        regime_match = primary_regime == contract["primary_regime"]
        for ticker in HOLDOUT_TICKERS:
            metadata = static_lookup[ticker]
            context = dict(state_lookup.get(ticker, {}))
            has_state = bool(context)
            strict_complete = ticker in strict_target_tickers
            intended_side = step9g._intended_side(contract["base_challenger_id"], context) if has_state else ""
            alignment = step9g._direction_alignment(intended_side, context.get("sector_direction_state", "")) if has_state else ""
            context["contract_sector_alignment"] = alignment
            point_safe = _bool(context.get("taxonomy_point_in_time_pass")) if has_state else False
            state_match = False
            if has_state and regime_match:
                state_match = bool(step9g._contract_mask(pd.DataFrame([context]), contract).iloc[0])
            eligible = bool(regime_match and has_state and point_safe and state_match)

            if not strict_complete or not has_state:
                action = "DATA_INCOMPLETE_NO_SHADOW_DECISION"
                reason = "Exact 09:30/09:35/09:40 inputs or prior history were unavailable for this ticker-day."
            elif not regime_match:
                action = "INELIGIBLE_REGIME_MISMATCH"
                reason = f"Observed regime {primary_regime}; contract requires {contract['primary_regime']}."
            elif not point_safe:
                action = "INELIGIBLE_POINT_IN_TIME_AUDIT"
                reason = "Ticker or sector state did not pass the locked point-in-time audit."
            elif not state_match:
                action = "INELIGIBLE_STATE_FILTER"
                reason = "The pre-registered ticker, volatility, or group-alignment filter was not met."
            elif contract["test_role"] == "NEGATIVE_GUARDRAIL":
                action = "GUARDRAIL_ACTIVE_AVOID_STRATEGY"
                reason = "The pre-registered negative guardrail is active; the avoided strategy is evaluated counterfactually after close."
            else:
                action = "ELIGIBLE_FOR_EOD_TRIGGER_EVALUATION"
                reason = "Regime and pre-registered state filters are satisfied; no future trigger information was used."

            rows.append(
                {
                    "session_date": target_date,
                    "contract_id": contract["contract_id"],
                    "test_role": contract["test_role"],
                    "ticker": ticker,
                    "company_id": metadata["company_id"],
                    "broad_sector": metadata["broad_sector"],
                    "primary_regime": primary_regime,
                    "regime_match": regime_match,
                    "ticker_relative_state": str(context.get("ticker_relative_state", "")),
                    "volatility_bucket": str(context.get("volatility_bucket", "")),
                    "range_state": str(context.get("range_state", "")),
                    "sector_direction_state": str(context.get("sector_direction_state", "")),
                    "sector_direction_alignment": alignment,
                    "intended_side": intended_side,
                    "contract_eligible": eligible,
                    "decision_action": action,
                    "decision_reason": reason,
                    "max_router_source_label": str(context.get("max_router_source_label", "")),
                    "point_in_time_pass": point_safe,
                }
            )

    observed = prices[prices["date"].astype(str).eq(target_date)].copy()
    coverage = {
        "regime_source_tickers_observed": int(observed[observed["ticker"].isin(REGIME_SOURCE_TICKERS)]["ticker"].nunique()),
        "holdout_tickers_observed": int(observed[observed["ticker"].isin(HOLDOUT_TICKERS)]["ticker"].nunique()),
    }
    return taxonomy_row, pd.DataFrame(rows), coverage


def _taxonomy_payload(row: pd.Series) -> dict[str, Any]:
    keep = [
        "date", "primary_regime", "secondary_regime", "primary_score", "secondary_score",
        "score_margin", "regime_confidence", "confidence_band", "direction_bias",
        "research_risk_multiplier", "research_max_concurrent_ideas", "point_in_time_safe",
        "minimum_regime_feature_ready", "full_regime_feature_ready", "feature_row_status",
        "classification_reason", "decision_time", "latest_allowed_bar_label",
    ]
    return {key: _clean_scalar(row.get(key)) for key in keep}


def seal_morning_decisions(
    target_date: str,
    now: datetime,
    prices: pd.DataFrame,
    ledger_db: Path = SHADOW_LEDGER_DB,
    source_db: Path = SHADOW_INTRADAY_DB,
    allow_late: bool = False,
    export_outputs_after: bool = True,
    simulated_clock: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    ledger_db = Path(ledger_db)
    if ledger_db.exists():
        with closing(sqlite3.connect(ledger_db)) as existing_con:
            _ensure_ledger_schema(existing_con)
            existing_batch = pd.read_sql_query(
                "SELECT * FROM shadow_decision_batches WHERE session_date = ?",
                existing_con,
                params=(target_date,),
            )
            if not existing_batch.empty:
                existing_decisions = pd.read_sql_query(
                    "SELECT * FROM shadow_decisions WHERE batch_id = ? ORDER BY contract_id, ticker",
                    existing_con,
                    params=(str(existing_batch.iloc[0]["batch_id"]),),
                )
                if export_outputs_after:
                    export_shadow_outputs(ledger_db)
                return existing_batch, existing_decisions, False

    status = (
        "SIMULATED_CLOCK_RECONSTRUCTION_NOT_CONFIRMATORY"
        if simulated_clock
        else _prospective_status(target_date, now, allow_late)
    )
    taxonomy_row, decisions, coverage = build_morning_decisions(prices, target_date)
    if decisions.empty:
        raise ShadowDataNotReady("No shadow decision rows were generated; the immutable ledger was not sealed.")

    batch_id = f"S9I-{target_date.replace('-', '')}-MORNING"
    sealed_at = now.strftime("%Y-%m-%d %H:%M:%S%z")
    source_max = prices[prices["date"].astype(str).le(target_date)]["datetime"].max()
    taxonomy_payload = _taxonomy_payload(taxonomy_row)
    batch_payload = {
        "batch_id": batch_id,
        "session_date": target_date,
        "prospective_status": status,
        "code_version": CODE_VERSION,
        "contract_registry_hash": _registry_hash(),
        "universe_hash": _universe_hash(),
        "source_max_datetime": _clean_scalar(source_max),
        "taxonomy_payload": taxonomy_payload,
        "decision_rows": int(len(decisions)),
        "eligible_rows": int(decisions["contract_eligible"].map(_bool).sum()),
        "active_guardrails": int(decisions["decision_action"].eq("GUARDRAIL_ACTIVE_AVOID_STRATEGY").sum()),
    }
    batch_row = {
        "batch_id": batch_id,
        "experiment_id": EXPERIMENT_ID,
        "session_date": target_date,
        "created_at_stockholm": sealed_at,
        "run_mode": "MORNING_DECISION_SEAL",
        "prospective_status": status,
        "decision_time": DECISION_TIME,
        "seal_deadline": SEAL_DEADLINE,
        "code_version": CODE_VERSION,
        "contract_registry_hash": _registry_hash(),
        "universe_hash": _universe_hash(),
        "source_db": str(source_db),
        "source_max_datetime": str(_clean_scalar(source_max) or ""),
        **coverage,
        "primary_regime": str(taxonomy_row["primary_regime"]),
        "regime_confidence": _num(taxonomy_row.get("regime_confidence")),
        "confidence_band": str(taxonomy_row.get("confidence_band", "")),
        "direction_bias": str(taxonomy_row.get("direction_bias", "")),
        "research_risk_multiplier": _num(taxonomy_row.get("research_risk_multiplier")),
        "research_max_concurrent_ideas": int(_num(taxonomy_row.get("research_max_concurrent_ideas"), 0)),
        "regime_point_in_time_pass": int(_bool(taxonomy_row.get("point_in_time_safe"))),
        "taxonomy_payload_json": _canonical_payload(taxonomy_payload),
        "decision_rows": len(decisions),
        "eligible_rows": int(decisions["contract_eligible"].map(_bool).sum()),
        "active_guardrails": int(decisions["decision_action"].eq("GUARDRAIL_ACTIVE_AVOID_STRATEGY").sum()),
        "batch_payload_hash": _payload_hash(batch_payload),
    }

    decision_rows: list[dict[str, Any]] = []
    for source in decisions.to_dict("records"):
        decision_id = f"{batch_id}|{source['contract_id']}|{source['ticker']}"
        row = {
            "decision_id": decision_id,
            "batch_id": batch_id,
            **{key: int(value) if key in {"regime_match", "contract_eligible", "point_in_time_pass"} else value for key, value in source.items()},
            "sealed_at_stockholm": sealed_at,
        }
        row["row_payload_hash"] = _payload_hash(row)
        decision_rows.append(row)

    ledger_db.parent.mkdir(parents=True, exist_ok=True)
    inserted = False
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        con.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(con, "shadow_decision_batches", "batch_id", "batch_payload_hash", batch_row)
        for row in decision_rows:
            _insert_immutable(con, "shadow_decisions", "decision_id", "row_payload_hash", row)
        con.commit()
        batches = _read_table(con, "shadow_decision_batches")
        stored = _read_table(con, "shadow_decisions")
    if export_outputs_after:
        export_shadow_outputs(ledger_db)
    return batches[batches["batch_id"].eq(batch_id)], stored[stored["batch_id"].eq(batch_id)], inserted


def _full_holdout_context(prices: pd.DataFrame, target_date: str):
    static = step9h.build_holdout_static()
    holdout = _prices_through_date(prices[prices["ticker"].isin(HOLDOUT_TICKERS)].copy(), target_date)
    characteristics, _, _, _ = step9e.build_point_in_time_characteristics(holdout, static)
    characteristics["date"] = characteristics["date"].astype(str)
    strict_keys = step9h._strict_early_complete_keys(holdout)
    strict_keys["date"] = strict_keys["date"].astype(str)
    execution_characteristics = characteristics.merge(
        strict_keys.assign(strict_early_complete=True), on=["date", "ticker"], how="inner", validate="one_to_one"
    ).drop(columns=["strict_early_complete"])
    daily = step9e._daily_input(holdout, static)
    if not daily.empty:
        daily["date"] = daily["date"].astype(str)
        daily = daily.merge(strict_keys, on=["date", "ticker"], how="inner", validate="one_to_one")
    group_states = step9e.build_group_daily_state(daily) if not daily.empty else pd.DataFrame(columns=step9e.GROUP_STATE_COLUMNS)
    return static, holdout, execution_characteristics, group_states


def _eod_complete(prices: pd.DataFrame, target_date: str, tickers: Iterable[str]) -> tuple[bool, list[str]]:
    frame = prices[prices["date"].astype(str).eq(target_date) & prices["ticker"].isin(list(tickers))].copy()
    incomplete: list[str] = []
    for ticker in sorted(set(tickers)):
        day = frame[frame["ticker"].eq(ticker)]
        max_label = day["datetime"].dt.strftime("%H:%M").max() if not day.empty else ""
        if not max_label or max_label < EOD_MINIMUM_LABEL:
            incomplete.append(ticker)
    return len(incomplete) == 0, incomplete


def evaluate_eod(
    target_date: str,
    now: datetime,
    prices: pd.DataFrame,
    ledger_db: Path = SHADOW_LEDGER_DB,
    source_db: Path = SHADOW_INTRADAY_DB,
    allow_early: bool = False,
    export_outputs_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    ledger_db = Path(ledger_db)
    if ledger_db.exists():
        with closing(sqlite3.connect(ledger_db)) as existing_con:
            _ensure_ledger_schema(existing_con)
            existing_batch = pd.read_sql_query(
                "SELECT * FROM shadow_outcome_batches WHERE session_date = ?",
                existing_con,
                params=(target_date,),
            )
            if not existing_batch.empty:
                existing_outcomes = pd.read_sql_query(
                    "SELECT * FROM shadow_outcomes WHERE outcome_batch_id = ? ORDER BY contract_id, ticker",
                    existing_con,
                    params=(str(existing_batch.iloc[0]["outcome_batch_id"]),),
                )
                if export_outputs_after:
                    export_shadow_outputs(ledger_db)
                return existing_batch, existing_outcomes, False

    if target_date == now.date().isoformat() and now.time() < time(17, 35) and not allow_early:
        raise ShadowDataNotReady("End-of-day evaluation is locked until 17:35 Stockholm time.")

    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        batch = pd.read_sql_query(
            "SELECT * FROM shadow_decision_batches WHERE session_date = ?", con, params=(target_date,)
        )
        decisions = pd.read_sql_query(
            "SELECT * FROM shadow_decisions WHERE session_date = ? ORDER BY contract_id, ticker", con, params=(target_date,)
        )
    if batch.empty or decisions.empty:
        raise ShadowDataNotReady(f"No immutable morning decision batch exists for {target_date}.")

    eligible_tickers = decisions[decisions["contract_eligible"].astype(bool)]["ticker"].unique().tolist()
    complete, incomplete = _eod_complete(prices, target_date, eligible_tickers)
    if eligible_tickers and not complete:
        raise ShadowDataNotReady(
            f"EOD bars are incomplete through {EOD_MINIMUM_LABEL} for: {', '.join(incomplete)}. The outcome ledger was not sealed."
        )

    taxonomy_payload = json.loads(str(batch.iloc[0]["taxonomy_payload_json"]))
    taxonomy_payload["date"] = target_date
    taxonomy = pd.DataFrame([taxonomy_payload])
    static, holdout, characteristics, group_states = _full_holdout_context(prices, target_date)
    with step9h._patched_step9g_globals():
        core = step9g.build_state_filtered_experiment(taxonomy, holdout, static, characteristics, group_states)
    candidates = core[3]
    trades = core[4]
    if not candidates.empty:
        candidates = candidates[candidates["date"].astype(str).eq(target_date)].copy()
    if not trades.empty:
        trades = trades[trades["date"].astype(str).eq(target_date)].copy()

    candidate_lookup = {
        (str(row["contract_id"]), str(row["ticker"])): row
        for row in candidates.to_dict("records")
    } if not candidates.empty else {}
    trade_lookup = {
        (str(row["contract_id"]), str(row["ticker"])): row
        for row in trades.to_dict("records")
    } if not trades.empty else {}

    morning_eligible_keys = {
        (str(row["contract_id"]), str(row["ticker"]))
        for row in decisions[decisions["contract_eligible"].astype(bool)].to_dict("records")
    }
    unexpected_candidates = set(candidate_lookup).difference(morning_eligible_keys)
    unexpected_trades = set(trade_lookup).difference(morning_eligible_keys)
    if unexpected_candidates or unexpected_trades:
        raise ImmutableLedgerConflict(
            "EOD engine eligibility differs from the immutable morning ledger; no outcomes were sealed. "
            f"Unexpected candidates={sorted(unexpected_candidates)}, unexpected trades={sorted(unexpected_trades)}"
        )

    outcome_batch_id = f"S9I-{target_date.replace('-', '')}-EOD"
    evaluated_at = now.strftime("%Y-%m-%d %H:%M:%S%z")
    outcome_rows: list[dict[str, Any]] = []
    for decision in decisions.to_dict("records"):
        key = (str(decision["contract_id"]), str(decision["ticker"]))
        candidate = candidate_lookup.get(key, {})
        trade = trade_lookup.get(key, {})
        morning_eligible = _bool(decision["contract_eligible"])
        has_candidate = bool(candidate)
        has_trade = bool(trade)
        if not morning_eligible:
            outcome_status = "NOT_ELIGIBLE_MORNING"
        elif str(decision["test_role"]) == "NEGATIVE_GUARDRAIL" and has_trade:
            outcome_status = "COUNTERFACTUAL_GUARDRAIL_TRADE_COMPLETED"
        elif has_trade:
            outcome_status = "HYPOTHETICAL_TRADE_COMPLETED"
        elif has_candidate:
            outcome_status = "ELIGIBLE_NO_COMPLETED_TRADE"
        else:
            outcome_status = "ELIGIBLE_NO_CANDIDATE_GENERATED"

        point_safe = _bool(decision["point_in_time_pass"])
        if has_candidate:
            point_safe = point_safe and _bool(candidate.get("point_in_time_pass"))
        if has_trade:
            point_safe = point_safe and _bool(trade.get("point_in_time_pass"))

        base = {
            "outcome_id": str(decision["decision_id"]),
            "decision_id": str(decision["decision_id"]),
            "outcome_batch_id": outcome_batch_id,
            "session_date": target_date,
            "contract_id": str(decision["contract_id"]),
            "test_role": str(decision["test_role"]),
            "ticker": str(decision["ticker"]),
            "company_id": str(decision["company_id"]),
            "broad_sector": str(decision["broad_sector"]),
            "morning_contract_eligible": int(morning_eligible),
            "candidate_generated": int(has_candidate),
            "selected_for_simulation": int(_bool(candidate.get("selected_for_simulation"))),
            "setup_status": str(candidate.get("setup_status", "")),
            "trigger_status": str(candidate.get("trigger_status", "")),
            "outcome_status": outcome_status,
            "direction": str(trade.get("direction", candidate.get("direction", decision.get("intended_side", "")))),
            "signal_time": str(candidate.get("signal_time", "")),
            "entry_time": str(trade.get("entry_time", candidate.get("entry_time", ""))),
            "entry_price": _num(trade.get("entry_price", candidate.get("entry_price"))),
            "stop_price": _num(trade.get("stop_price", candidate.get("stop_price"))),
            "target_price": _num(trade.get("target_price", candidate.get("target_price"))),
            "exit_time": str(trade.get("exit_time", "")),
            "exit_price": _num(trade.get("exit_price")),
            "exit_reason": str(trade.get("exit_reason", "")),
            "gross_return": _num(trade.get("gross_return")),
            "risk_pct_at_entry": _num(trade.get("risk_pct_at_entry")),
            "r_multiple_achieved": _num(trade.get("r_multiple_achieved")),
            "equal_net_pnl_sek": _num(trade.get("equal_net_pnl_sek")),
            "risk_capped_net_pnl_sek": _num(trade.get("risk_capped_net_pnl_sek")),
            "point_in_time_pass": int(point_safe),
            "evaluated_at_stockholm": evaluated_at,
        }
        base["row_payload_hash"] = _payload_hash(base)
        outcome_rows.append(base)

    outcome_payload = {
        "outcome_batch_id": outcome_batch_id,
        "decision_batch_id": str(batch.iloc[0]["batch_id"]),
        "session_date": target_date,
        "code_version": CODE_VERSION,
        "source_max_datetime": _clean_scalar(prices[prices["date"].astype(str).le(target_date)]["datetime"].max()),
        "outcome_row_hashes": [row["row_payload_hash"] for row in outcome_rows],
    }
    outcome_batch = {
        "outcome_batch_id": outcome_batch_id,
        "decision_batch_id": str(batch.iloc[0]["batch_id"]),
        "session_date": target_date,
        "created_at_stockholm": evaluated_at,
        "code_version": CODE_VERSION,
        "source_db": str(source_db),
        "source_max_datetime": str(outcome_payload["source_max_datetime"] or ""),
        "eod_complete": int(complete),
        "decision_rows": len(decisions),
        "outcome_rows": len(outcome_rows),
        "completed_trades": int(sum(row["outcome_status"].endswith("TRADE_COMPLETED") for row in outcome_rows)),
        "outcome_payload_hash": _payload_hash(outcome_payload),
    }

    inserted = False
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        con.execute("BEGIN IMMEDIATE")
        inserted = _insert_immutable(
            con, "shadow_outcome_batches", "outcome_batch_id", "outcome_payload_hash", outcome_batch
        )
        for row in outcome_rows:
            _insert_immutable(con, "shadow_outcomes", "outcome_id", "row_payload_hash", row)
        con.commit()
        batches = _read_table(con, "shadow_outcome_batches")
        stored = _read_table(con, "shadow_outcomes")
    if export_outputs_after:
        export_shadow_outputs(ledger_db)
    return batches[batches["outcome_batch_id"].eq(outcome_batch_id)], stored[stored["outcome_batch_id"].eq(outcome_batch_id)], inserted


def _profit_factor(values: pd.Series) -> float:
    pnl = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl < 0].sum()))
    return np.nan if losses == 0 else gains / losses


def _cluster_bootstrap(frame: pd.DataFrame, cluster: str, direction: str, seed: int) -> tuple[float, float, float]:
    if frame.empty:
        return np.nan, np.nan, np.nan
    grouped = frame.groupby(cluster)["risk_capped_net_pnl_sek"].sum().dropna()
    if grouped.empty:
        return np.nan, np.nan, np.nan
    values = grouped.to_numpy(float)
    rng = np.random.default_rng(seed)
    sampled = values[rng.integers(0, len(values), size=(BOOTSTRAP_ITERATIONS, len(values)))].sum(axis=1)
    probability = float(np.mean(sampled > 0)) if direction == "POSITIVE" else float(np.mean(sampled < 0))
    return float(np.quantile(sampled, 0.025)), float(np.quantile(sampled, 0.975)), probability


def _sign_flip(values: np.ndarray, direction: str, seed: int) -> float:
    if len(values) == 0:
        return np.nan
    observed = float(values.sum())
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(SIGN_FLIP_ITERATIONS, len(values)))
    simulated = (signs * values).sum(axis=1)
    if direction == "NEGATIVE":
        return float((1 + np.sum(simulated <= observed)) / (SIGN_FLIP_ITERATIONS + 1))
    return float((1 + np.sum(simulated >= observed)) / (SIGN_FLIP_ITERATIONS + 1))


def _bh_adjust(series: pd.Series) -> pd.Series:
    valid = series.dropna().sort_values()
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if valid.empty:
        return out
    m = len(valid)
    adjusted = []
    running = 1.0
    for rank_from_end, (idx, p) in enumerate(reversed(list(valid.items())), start=1):
        rank = m - rank_from_end + 1
        running = min(running, float(p) * m / rank)
        adjusted.append((idx, min(1.0, running)))
    for idx, value in adjusted:
        out.loc[idx] = value
    return out


def build_performance(decisions: pd.DataFrame, outcomes: pd.DataFrame, batches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "experiment_id", "contract_id", "test_role", "prospective_trades", "prospective_sessions",
        "independent_companies", "independent_sectors", "net_pnl_risk_capped_sek", "win_rate",
        "profit_factor", "date_bootstrap_ci_lower_95_sek", "date_bootstrap_ci_upper_95_sek",
        "date_bootstrap_probability_intended_direction", "company_bootstrap_ci_lower_95_sek",
        "company_bootstrap_ci_upper_95_sek", "company_bootstrap_probability_intended_direction",
        "one_sided_sign_flip_p_value", "bh_adjusted_q_value_primary_family", "leave_one_date_worst_sek",
        "leave_one_company_worst_sek", "leave_one_sector_worst_sek", "sample_gate_ready",
        "statistical_gate_ready", "advancement_status", "router_active",
    ]
    multiple_columns = [
        "experiment_id", "contract_id", "test_role", "prospective_trades", "one_sided_sign_flip_p_value",
        "bh_adjusted_q_value_primary_family", "multiplicity_family", "interpretation",
    ]
    if decisions.empty or outcomes.empty or batches.empty:
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=multiple_columns)

    prospective_batch_ids = set(
        batches[batches["prospective_status"].eq("PROSPECTIVE_CONFIRMATORY_ELIGIBLE")]["batch_id"].astype(str)
    )
    prospective_decisions = decisions[decisions["batch_id"].astype(str).isin(prospective_batch_ids)].copy()
    merged = outcomes.merge(
        prospective_decisions[["decision_id", "contract_eligible"]], on="decision_id", how="inner", validate="one_to_one"
    )
    trades = merged[
        merged["contract_eligible"].astype(bool)
        & merged["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED")
    ].copy()

    rows = []
    for index, contract in enumerate(step9h.CONTRACTS):
        cid = contract["contract_id"]
        frame = trades[trades["contract_id"].eq(cid)].copy()
        role = contract["test_role"]
        direction = "NEGATIVE" if role == "NEGATIVE_GUARDRAIL" else "POSITIVE"
        pnl = pd.to_numeric(frame.get("risk_capped_net_pnl_sek", pd.Series(dtype=float)), errors="coerce").dropna()
        net = float(pnl.sum()) if not pnl.empty else 0.0
        date_lo, date_hi, date_prob = _cluster_bootstrap(frame, "session_date", direction, RANDOM_SEED + index)
        comp_lo, comp_hi, comp_prob = _cluster_bootstrap(frame, "company_id", direction, RANDOM_SEED + 100 + index)
        loo_date = [net - float(value) for value in frame.groupby("session_date")["risk_capped_net_pnl_sek"].sum()] if not frame.empty else []
        loo_company = [net - float(value) for value in frame.groupby("company_id")["risk_capped_net_pnl_sek"].sum()] if not frame.empty else []
        loo_sector = [net - float(value) for value in frame.groupby("broad_sector")["risk_capped_net_pnl_sek"].sum()] if not frame.empty else []
        sample_ready = (
            len(frame) >= MIN_TRADES
            and frame["session_date"].nunique() >= MIN_SESSIONS
            and frame["company_id"].nunique() >= MIN_COMPANIES
            and frame["broad_sector"].nunique() >= MIN_SECTORS
        )
        profit_factor = _profit_factor(pnl)
        eligible_role = role in {"PRIMARY_HYPOTHESIS", "NEGATIVE_GUARDRAIL"}
        if direction == "NEGATIVE":
            statistical = (
                eligible_role and sample_ready and net < 0 and (pd.isna(profit_factor) or profit_factor < 1.0)
                and date_hi < 0 and comp_hi < 0 and max(loo_date or [np.inf]) < 0
                and max(loo_company or [np.inf]) < 0 and max(loo_sector or [np.inf]) < 0
            )
        else:
            statistical = (
                eligible_role and sample_ready and net > 0 and profit_factor > 1.0
                and date_lo > 0 and comp_lo > 0 and min(loo_date or [-np.inf]) > 0
                and min(loo_company or [-np.inf]) > 0 and min(loo_sector or [-np.inf]) > 0
            )
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "contract_id": cid,
                "test_role": role,
                "prospective_trades": len(frame),
                "prospective_sessions": int(frame["session_date"].nunique()) if not frame.empty else 0,
                "independent_companies": int(frame["company_id"].nunique()) if not frame.empty else 0,
                "independent_sectors": int(frame["broad_sector"].nunique()) if not frame.empty else 0,
                "net_pnl_risk_capped_sek": net,
                "win_rate": float((pnl > 0).mean()) if not pnl.empty else np.nan,
                "profit_factor": profit_factor,
                "date_bootstrap_ci_lower_95_sek": date_lo,
                "date_bootstrap_ci_upper_95_sek": date_hi,
                "date_bootstrap_probability_intended_direction": date_prob,
                "company_bootstrap_ci_lower_95_sek": comp_lo,
                "company_bootstrap_ci_upper_95_sek": comp_hi,
                "company_bootstrap_probability_intended_direction": comp_prob,
                "one_sided_sign_flip_p_value": _sign_flip(pnl.to_numpy(float), direction, RANDOM_SEED + 200 + index),
                "bh_adjusted_q_value_primary_family": np.nan,
                "leave_one_date_worst_sek": min(loo_date) if direction == "POSITIVE" and loo_date else max(loo_date) if loo_date else np.nan,
                "leave_one_company_worst_sek": min(loo_company) if direction == "POSITIVE" and loo_company else max(loo_company) if loo_company else np.nan,
                "leave_one_sector_worst_sek": min(loo_sector) if direction == "POSITIVE" and loo_sector else max(loo_sector) if loo_sector else np.nan,
                "sample_gate_ready": sample_ready,
                "statistical_gate_ready": statistical,
                "advancement_status": "READY_FOR_HUMAN_CONFIRMATORY_REVIEW" if statistical else "PROSPECTIVE_SAMPLE_ACCUMULATING",
                "router_active": False,
            }
        )
    performance = pd.DataFrame(rows, columns=columns)
    primary_mask = performance["test_role"].eq("PRIMARY_HYPOTHESIS")
    performance.loc[primary_mask, "bh_adjusted_q_value_primary_family"] = _bh_adjust(
        performance.loc[primary_mask, "one_sided_sign_flip_p_value"]
    )
    performance.loc[
        primary_mask & performance["bh_adjusted_q_value_primary_family"].gt(0.10), "statistical_gate_ready"
    ] = False
    performance.loc[
        primary_mask & ~performance["statistical_gate_ready"].astype(bool), "advancement_status"
    ] = "PROSPECTIVE_SAMPLE_ACCUMULATING"

    multiple = performance[primary_mask][[
        "experiment_id", "contract_id", "test_role", "prospective_trades", "one_sided_sign_flip_p_value",
        "bh_adjusted_q_value_primary_family",
    ]].copy()
    multiple["multiplicity_family"] = "THREE_LOCKED_STEP9I_PRIMARY_CONTRACTS"
    multiple["interpretation"] = "Prospective-only BH correction; no result automatically activates the router."
    return performance, multiple[multiple_columns]


def build_audit(
    decisions: pd.DataFrame,
    outcomes: pd.DataFrame,
    batches: pd.DataFrame,
    outcome_batches: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    decision_hash_fail = 0
    for row in decisions.to_dict("records"):
        payload = {key: value for key, value in row.items() if key != "row_payload_hash"}
        if _payload_hash(payload) != str(row["row_payload_hash"]):
            decision_hash_fail += 1
    outcome_hash_fail = 0
    for row in outcomes.to_dict("records"):
        payload = {key: value for key, value in row.items() if key != "row_payload_hash"}
        if _payload_hash(payload) != str(row["row_payload_hash"]):
            outcome_hash_fail += 1
    orphan = 0
    if not outcomes.empty:
        orphan = int((~outcomes["decision_id"].isin(set(decisions["decision_id"]))).sum())
    ineligible_trades = int(
        (
            ~outcomes.get("morning_contract_eligible", pd.Series(dtype=bool)).astype(bool)
            & outcomes.get("outcome_status", pd.Series(dtype=str)).astype(str).str.endswith("TRADE_COMPLETED")
        ).sum()
    ) if not outcomes.empty else 0
    prospective_late = 0
    if not batches.empty:
        prospective = batches[
            batches.get("prospective_status", pd.Series(index=batches.index, dtype=str))
            .astype(str)
            .eq("PROSPECTIVE_CONFIRMATORY_ELIGIBLE")
        ]
        for raw_created_at in prospective.get(
            "created_at_stockholm", pd.Series(index=prospective.index, dtype=object)
        ):
            # A confirmatory batch must carry a valid seal timestamp. Blank or invalid
            # timestamps are audit failures; non-confirmatory replay batches never enter
            # this loop and therefore cannot crash the shared Step 9I audit.
            if pd.isna(raw_created_at) or not str(raw_created_at).strip():
                prospective_late += 1
                continue
            try:
                timestamp = pd.Timestamp(raw_created_at)
                local_timestamp = (
                    timestamp.tz_convert(LOCAL_TZ)
                    if timestamp.tzinfo is not None
                    else timestamp
                )
                if local_timestamp.time() > _clock_tuple(SEAL_DEADLINE):
                    prospective_late += 1
            except (TypeError, ValueError, OverflowError):
                prospective_late += 1
    checks = [
        ("IMMUTABLE_DECISION_ROW_HASHES", len(decisions), decision_hash_fail, "Every exported decision matches its sealed row hash."),
        ("IMMUTABLE_OUTCOME_ROW_HASHES", len(outcomes), outcome_hash_fail, "Every exported outcome matches its sealed row hash."),
        ("OUTCOMES_HAVE_MORNING_DECISIONS", len(outcomes), orphan, "No outcome exists without a prior immutable morning decision."),
        ("INELIGIBLE_DECISIONS_CANNOT_TRADE", len(outcomes), ineligible_trades, "Only morning-eligible ticker-contract pairs may produce simulated trades."),
        ("PROSPECTIVE_BATCHES_SEALED_BEFORE_DEADLINE", len(batches), prospective_late, "Confirmatory batches were sealed no later than 09:49:30 Stockholm time."),
        ("ROUTER_REMAINS_INACTIVE", len(batches) + len(outcome_batches), 0, "Step 9I is shadow-only and cannot place or route orders."),
    ]
    for item, checked, failures, interpretation in checks:
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            "audit_item": item,
            "rows_checked": checked,
            "failures": failures,
            "audit_pass": failures == 0,
            "interpretation": interpretation,
        })
    return pd.DataFrame(rows)


def build_summary(
    decisions: pd.DataFrame,
    outcomes: pd.DataFrame,
    batches: pd.DataFrame,
    outcome_batches: pd.DataFrame,
    performance: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    prospective_batches = int(batches["prospective_status"].eq("PROSPECTIVE_CONFIRMATORY_ELIGIBLE").sum()) if not batches.empty else 0
    late_batches = int(batches["prospective_status"].ne("PROSPECTIVE_CONFIRMATORY_ELIGIBLE").sum()) if not batches.empty else 0
    completed_trades = int(outcomes["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED").sum()) if not outcomes.empty else 0
    audits_pass = bool(audit["audit_pass"].astype(bool).all()) if not audit.empty else True
    statistical_ready = int(performance["statistical_gate_ready"].astype(bool).sum()) if not performance.empty else 0
    if not batches.empty and audits_pass:
        classification = "PROSPECTIVE_SHADOW_LEDGER_ACTIVE_SAMPLE_ACCUMULATING"
    elif batches.empty:
        classification = "AWAITING_FIRST_PROSPECTIVE_MORNING_SEAL"
    else:
        classification = "SHADOW_LEDGER_AUDIT_REVIEW_REQUIRED"
    return pd.DataFrame([{
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "code_version": CODE_VERSION,
        "contract_registry_hash": _registry_hash(),
        "universe_hash": _universe_hash(),
        "decision_batches": len(batches),
        "prospective_confirmatory_batches": prospective_batches,
        "non_confirmatory_batches": late_batches,
        "decision_rows": len(decisions),
        "eligible_decision_rows": int(decisions["contract_eligible"].astype(bool).sum()) if not decisions.empty else 0,
        "outcome_batches": len(outcome_batches),
        "outcome_rows": len(outcomes),
        "completed_shadow_trades": completed_trades,
        "contracts_statistically_ready": statistical_ready,
        "audit_pass": audits_pass,
        "strategies_promoted": 0,
        "router_active": False,
        "classification": classification,
    }])


def contract_registry() -> pd.DataFrame:
    rows = []
    for contract in step9h.CONTRACTS:
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            **contract,
            "code_version": CODE_VERSION,
            "locked_before_first_prospective_outcome": True,
            "minimum_trades": MIN_TRADES,
            "minimum_sessions": MIN_SESSIONS,
            "minimum_companies": MIN_COMPANIES,
            "minimum_sectors": MIN_SECTORS,
            "router_active": False,
        })
    return pd.DataFrame(rows)


def export_shadow_outputs(ledger_db: Path = SHADOW_LEDGER_DB) -> None:
    ledger_db = Path(ledger_db)
    if not ledger_db.exists():
        batches = pd.DataFrame()
        decisions = pd.DataFrame()
        outcome_batches = pd.DataFrame()
        outcomes = pd.DataFrame()
    else:
        with closing(sqlite3.connect(ledger_db)) as con:
            _ensure_ledger_schema(con)
            batches = _read_table(con, "shadow_decision_batches")
            decisions = _read_table(con, "shadow_decisions")
            outcome_batches = _read_table(con, "shadow_outcome_batches")
            outcomes = _read_table(con, "shadow_outcomes")
    performance, multiple = build_performance(decisions, outcomes, batches)
    audit = build_audit(decisions, outcomes, batches, outcome_batches)
    summary = build_summary(decisions, outcomes, batches, outcome_batches, performance, audit)
    outputs = [
        (batches, DECISION_BATCH_FILE), (decisions, DECISION_FILE),
        (outcome_batches, OUTCOME_BATCH_FILE), (outcomes, OUTCOME_FILE),
        (performance, PERFORMANCE_FILE), (multiple, MULTIPLE_TESTING_FILE),
        (audit, AUDIT_FILE), (summary, SUMMARY_FILE), (contract_registry(), CONTRACT_REGISTRY_FILE),
    ]
    for frame, path in outputs:
        export_csv_for_power_bi(frame, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 9I prospective shadow router and immutable outcome evaluator.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    morning = subparsers.add_parser("morning", help="Seal point-in-time morning decisions.")
    morning.add_argument("--date")
    morning.add_argument("--as-of", help="Stockholm timestamp used for deterministic testing or reconstruction.")
    morning.add_argument("--source-db", type=Path, default=SHADOW_INTRADAY_DB)
    morning.add_argument("--ledger-db", type=Path, default=SHADOW_LEDGER_DB)
    morning.add_argument("--allow-late-reconstruction", action="store_true")
    eod = subparsers.add_parser("eod", help="Evaluate a previously sealed morning batch after close.")
    eod.add_argument("--date")
    eod.add_argument("--as-of")
    eod.add_argument("--source-db", type=Path, default=SHADOW_INTRADAY_DB)
    eod.add_argument("--ledger-db", type=Path, default=SHADOW_LEDGER_DB)
    eod.add_argument("--allow-early-evaluation", action="store_true")
    export = subparsers.add_parser("export", help="Re-export immutable ledgers and cumulative diagnostics.")
    export.add_argument("--ledger-db", type=Path, default=SHADOW_LEDGER_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "export":
        export_shadow_outputs(args.ledger_db)
        print("Step 9I immutable ledger exports refreshed.")
        return

    now = _parse_stockholm_datetime(args.as_of)
    target = _target_date(args.date, now)
    prices = load_shadow_prices(args.source_db)
    if prices.empty:
        raise ShadowDataNotReady(
            f"No Step 9I shadow data found at {args.source_db}. Run .\\collect_step9i_shadow_data.ps1 first."
        )

    if args.command == "morning":
        print("\n=== STEP 9I PROSPECTIVE MORNING SHADOW SEAL ===")
        print(f"Experiment      : {EXPERIMENT_ID}")
        print(f"Session date    : {target}")
        print(f"As-of Stockholm : {now:%Y-%m-%d %H:%M:%S %Z}")
        print(f"Decision cutoff : completed start-labelled bars through {LATEST_ALLOWED_BAR_LABEL}")
        batches, decisions, inserted = seal_morning_decisions(
            target, now, prices, args.ledger_db, args.source_db, args.allow_late_reconstruction, True, bool(args.as_of)
        )
        row = batches.iloc[0]
        print(f"Ledger action   : {'SEALED_NEW_BATCH' if inserted else 'EXISTING_IDENTICAL_BATCH_RETURNED'}")
        print(f"Prospective status : {row['prospective_status']}")
        print(f"Primary regime     : {row['primary_regime']} ({float(row['regime_confidence']):.1%})")
        print(f"Decisions / eligible: {len(decisions)}/{int(decisions['contract_eligible'].astype(bool).sum())}")
        print(f"Active guardrails  : {int(decisions['decision_action'].eq('GUARDRAIL_ACTIVE_AVOID_STRATEGY').sum())}")
        print("No orders were sent. The morning ledger is immutable.")
    else:
        print("\n=== STEP 9I END-OF-DAY SHADOW EVALUATION ===")
        print(f"Session date    : {target}")
        print(f"As-of Stockholm : {now:%Y-%m-%d %H:%M:%S %Z}")
        batches, outcomes, inserted = evaluate_eod(
            target, now, prices, args.ledger_db, args.source_db, args.allow_early_evaluation
        )
        print(f"Ledger action   : {'SEALED_NEW_OUTCOME_BATCH' if inserted else 'EXISTING_IDENTICAL_BATCH_RETURNED'}")
        print(f"Outcome rows    : {len(outcomes)}")
        print(f"Completed trades: {int(outcomes['outcome_status'].astype(str).str.endswith('TRADE_COMPLETED').sum())}")
        print("Morning decisions were read-only and were not rewritten.")


if __name__ == "__main__":
    main()
