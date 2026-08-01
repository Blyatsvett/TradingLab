from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import DATA_DIR, LEGACY_OUTPUT_DIRS
from RegimeTrading.scripts import step8_provisional_regime_taxonomy as step8
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_prospective_shadow_router as step9i


EXPERIMENT_ID = "STEP9IR_HISTORICAL_WALK_FORWARD_REPLAY_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_HISTORICAL_REPLAY_NOT_CONFIRMATORY"
CODE_VERSION = "STEP9IR_WALK_FORWARD_REPLAY_V1_2026_07_25"
DEFAULT_START_DATE = "2026-05-25"
DEFAULT_END_DATE = "2026-07-24"

OUTPUT_DIR = LEGACY_OUTPUT_DIRS["step9ir_v1"]
REPLAY_LEDGER_DB = OUTPUT_DIR / "step9ir_historical_replay_ledger.db"
RUN_LOG_FILE = OUTPUT_DIR / "step9ir_replay_run_log.csv"
SUMMARY_FILE = OUTPUT_DIR / "step9ir_replay_summary.csv"
DECISION_BATCH_FILE = OUTPUT_DIR / "step9ir_replay_decision_batches.csv"
DECISION_FILE = OUTPUT_DIR / "step9ir_replay_decisions.csv"
OUTCOME_BATCH_FILE = OUTPUT_DIR / "step9ir_replay_outcome_batches.csv"
OUTCOME_FILE = OUTPUT_DIR / "step9ir_replay_outcomes.csv"
DAILY_REGIME_FILE = OUTPUT_DIR / "step9ir_replay_daily_regimes.csv"
DAILY_SUMMARY_FILE = OUTPUT_DIR / "step9ir_replay_daily_summary.csv"
REGIME_STRATEGY_MATRIX_FILE = OUTPUT_DIR / "step9ir_replay_regime_strategy_matrix.csv"
CONTRACT_PERFORMANCE_FILE = OUTPUT_DIR / "step9ir_replay_contract_performance.csv"
TICKER_PERFORMANCE_FILE = OUTPUT_DIR / "step9ir_replay_ticker_performance.csv"
SECTOR_PERFORMANCE_FILE = OUTPUT_DIR / "step9ir_replay_sector_performance.csv"
CUMULATIVE_PNL_FILE = OUTPUT_DIR / "step9ir_replay_cumulative_pnl.csv"
COMPARISON_FILE = OUTPUT_DIR / "step9ir_replay_comparisons.csv"
AUDIT_FILE = OUTPUT_DIR / "step9ir_replay_audit.csv"
CONTRACT_REGISTRY_FILE = OUTPUT_DIR / "step9ir_replay_contract_registry.csv"

FRIENDLY_STRATEGY_NAMES = {
    "RANGE_REJECTION_REVERSION_1_25R_V1": "RANGE_REJECTION",
    "EARLY_MOVE_CONTINUATION_1_5R_V1": "EARLY_CONTINUATION",
    "DELAYED_EARLY_MOVE_REVERSAL_1R_V1": "DELAYED_REVERSAL",
    "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1": "CLOSE_CONFIRMED_ORB",
}

COMPARISON_PAIRS = (
    {
        "comparison_id": "VOL_EXP_ALIGNED_VS_CONTRARIAN_CONTINUATION",
        "left_contract_id": "H_VE_ALIGNED_EARLY_CONTINUATION_V1",
        "right_contract_id": "H_VE_CONTRARIAN_EARLY_CONTINUATION_CONTROL_V1",
        "interpretation": "Does peer-group alignment separate continuation performance during volatility expansion?",
    },
    {
        "comparison_id": "RANGE_LOW_VOL_HIGH_VS_NOT_HIGH_REL_VOL_REVERSAL",
        "left_contract_id": "H_RLV_LAGGARD_HIGH_REL_VOL_DELAYED_REVERSAL_V1",
        "right_contract_id": "H_RLV_LAGGARD_NOT_HIGH_VOL_DELAYED_REVERSAL_CONTROL_V1",
        "interpretation": "Does high relative volatility separate delayed-reversal performance among early laggards?",
    },
    {
        "comparison_id": "VOL_EXP_EARLY_CONTINUATION_VS_CLOSE_CONFIRMED_ORB",
        "left_contract_id": "H_VE_ALIGNED_EARLY_CONTINUATION_V1",
        "right_contract_id": "H_VE_ALIGNED_CLOSE_CONFIRMED_ORB_COMPARATOR_V1",
        "interpretation": "Which execution method performs better on the same aligned volatility-expansion cohort?",
    },
)


def _bool(value: Any) -> bool:
    return step9i._bool(value)


def _num(value: Any, default: float = np.nan) -> float:
    return step9i._num(value, default)


def _contract_registry() -> pd.DataFrame:
    rows = []
    for contract in step9h.CONTRACTS:
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                **contract,
                "strategy_name": FRIENDLY_STRATEGY_NAMES.get(
                    contract["base_challenger_id"], contract["base_challenger_id"]
                ),
                "historical_replay_only": True,
                "confirmatory_evidence": False,
                "router_active": False,
            }
        )
    return pd.DataFrame(rows)


def _date_range_from_prices(prices: pd.DataFrame, start_date: str, end_date: str) -> list[str]:
    if prices.empty:
        return []
    dates = pd.Series(prices["date"].astype(str).unique(), dtype="string")
    return sorted(dates[dates.between(start_date, end_date)].dropna().astype(str).tolist())


def _check_existing_replay_compatibility(ledger_db: Path) -> None:
    if not ledger_db.exists():
        return
    with closing(sqlite3.connect(ledger_db)) as con:
        step9i._ensure_ledger_schema(con)
        existing = pd.read_sql_query(
            "SELECT DISTINCT code_version, contract_registry_hash, universe_hash FROM shadow_decision_batches",
            con,
        )
    if existing.empty:
        return
    expected = (step9i.CODE_VERSION, step9i._registry_hash(), step9i._universe_hash())
    observed = {
        (str(row.code_version), str(row.contract_registry_hash), str(row.universe_hash))
        for row in existing.itertuples(index=False)
    }
    if observed != {expected}:
        raise step9i.ImmutableLedgerConflict(
            "The existing Step 9I-R replay ledger was created with a different Step 9I code, contract registry, "
            "or universe. Rerun with --reset-replay to create a clean non-confirmatory replay ledger."
        )


def run_replay(
    prices: pd.DataFrame,
    start_date: str,
    end_date: str,
    ledger_db: Path = REPLAY_LEDGER_DB,
    source_db: Path = step9i.SHADOW_INTRADAY_DB,
    reset_replay: bool = False,
) -> pd.DataFrame:
    ledger_db = Path(ledger_db)
    if reset_replay and ledger_db.exists():
        ledger_db.unlink()
    _check_existing_replay_compatibility(ledger_db)

    available_dates = _date_range_from_prices(prices, start_date, end_date)
    rows: list[dict[str, Any]] = []
    for session_date in available_dates:
        base = {
            "experiment_id": EXPERIMENT_ID,
            "research_status": RESEARCH_STATUS,
            "requested_start_date": start_date,
            "requested_end_date": end_date,
            "session_date": session_date,
            "morning_status": "NOT_RUN",
            "eod_status": "NOT_RUN",
            "morning_inserted": False,
            "eod_inserted": False,
            "primary_regime": "",
            "decision_rows": 0,
            "eligible_rows": 0,
            "outcome_rows": 0,
            "completed_trades": 0,
            "skip_reason": "",
        }
        morning_now = pd.Timestamp(f"{session_date} 09:47:00", tz=step9i.LOCAL_TZ).to_pydatetime()
        eod_now = pd.Timestamp(f"{session_date} 17:40:00", tz=step9i.LOCAL_TZ).to_pydatetime()
        try:
            morning_batch, decisions, morning_inserted = step9i.seal_morning_decisions(
                target_date=session_date,
                now=morning_now,
                prices=prices,
                ledger_db=ledger_db,
                source_db=source_db,
                allow_late=True,
                export_outputs_after=False,
                simulated_clock=True,
            )
            batch = morning_batch.iloc[0]
            base.update(
                {
                    "morning_status": str(batch["prospective_status"]),
                    "morning_inserted": bool(morning_inserted),
                    "primary_regime": str(batch["primary_regime"]),
                    "decision_rows": int(len(decisions)),
                    "eligible_rows": int(decisions["contract_eligible"].map(_bool).sum()),
                }
            )
        except (step9i.ShadowDataNotReady, step9i.ImmutableLedgerConflict, ValueError) as exc:
            base["morning_status"] = "SKIPPED_MORNING_NOT_READY"
            base["eod_status"] = "SKIPPED_NO_MORNING_BATCH"
            base["skip_reason"] = str(exc)
            rows.append(base)
            continue

        try:
            outcome_batch, outcomes, eod_inserted = step9i.evaluate_eod(
                target_date=session_date,
                now=eod_now,
                prices=prices,
                ledger_db=ledger_db,
                source_db=source_db,
                allow_early=True,
                export_outputs_after=False,
            )
            base.update(
                {
                    "eod_status": "EOD_EVALUATED",
                    "eod_inserted": bool(eod_inserted),
                    "outcome_rows": int(len(outcomes)),
                    "completed_trades": int(outcome_batch.iloc[0]["completed_trades"]),
                }
            )
        except (step9i.ShadowDataNotReady, step9i.ImmutableLedgerConflict, ValueError) as exc:
            base["eod_status"] = "SKIPPED_EOD_NOT_READY"
            base["skip_reason"] = str(exc)
        rows.append(base)
    return pd.DataFrame(rows)


def _read_replay_tables(ledger_db: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not Path(ledger_db).exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    with closing(sqlite3.connect(ledger_db)) as con:
        step9i._ensure_ledger_schema(con)
        batches = pd.read_sql_query("SELECT * FROM shadow_decision_batches ORDER BY session_date", con)
        decisions = pd.read_sql_query(
            "SELECT * FROM shadow_decisions ORDER BY session_date, contract_id, ticker", con
        )
        outcome_batches = pd.read_sql_query("SELECT * FROM shadow_outcome_batches ORDER BY session_date", con)
        outcomes = pd.read_sql_query(
            "SELECT * FROM shadow_outcomes ORDER BY session_date, contract_id, ticker", con
        )
    return batches, decisions, outcome_batches, outcomes


def _completed_trades(outcomes: pd.DataFrame) -> pd.DataFrame:
    if outcomes.empty:
        return outcomes.copy()
    return outcomes[
        outcomes["morning_contract_eligible"].map(_bool)
        & outcomes["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED")
    ].copy()


def _profit_factor(values: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(values[values > 0].sum())
    losses = float(values[values < 0].sum())
    if losses == 0:
        return np.inf if gains > 0 else np.nan
    return gains / abs(losses)


def _performance_group(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    columns = group_columns + [
        "eligible_ticker_contract_rows",
        "candidate_rows",
        "completed_trades",
        "trading_sessions",
        "independent_companies",
        "independent_sectors",
        "net_pnl_risk_capped_sek",
        "average_pnl_per_trade_sek",
        "win_rate",
        "profit_factor",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for keys, group in frame.groupby(group_columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        trades = group[group["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED")].copy()
        pnl = pd.to_numeric(trades["risk_capped_net_pnl_sek"], errors="coerce").dropna()
        row = dict(zip(group_columns, keys))
        row.update(
            {
                "eligible_ticker_contract_rows": int(group["morning_contract_eligible"].map(_bool).sum()),
                "candidate_rows": int(group["candidate_generated"].map(_bool).sum()),
                "completed_trades": int(len(trades)),
                "trading_sessions": int(trades["session_date"].nunique()) if not trades.empty else 0,
                "independent_companies": int(trades["company_id"].nunique()) if not trades.empty else 0,
                "independent_sectors": int(trades["broad_sector"].nunique()) if not trades.empty else 0,
                "net_pnl_risk_capped_sek": float(pnl.sum()) if not pnl.empty else 0.0,
                "average_pnl_per_trade_sek": float(pnl.mean()) if not pnl.empty else np.nan,
                "win_rate": float((pnl > 0).mean()) if not pnl.empty else np.nan,
                "profit_factor": _profit_factor(pnl),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def build_daily_regimes(batches: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "experiment_id", "session_date", "primary_regime", "regime_confidence", "confidence_band",
        "direction_bias", "research_risk_multiplier", "decision_rows", "eligible_rows", "active_guardrails",
        "replay_status", "confirmatory_evidence", "router_active",
    ]
    if batches.empty:
        return pd.DataFrame(columns=columns)
    out = batches[
        [
            "session_date", "primary_regime", "regime_confidence", "confidence_band", "direction_bias",
            "research_risk_multiplier", "decision_rows", "eligible_rows", "active_guardrails", "prospective_status",
        ]
    ].copy()
    out.insert(0, "experiment_id", EXPERIMENT_ID)
    out = out.rename(columns={"prospective_status": "replay_status"})
    out["confirmatory_evidence"] = False
    out["router_active"] = False
    return out[columns]


def build_daily_summary(batches: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "experiment_id", "session_date", "primary_regime", "eligible_ticker_contract_rows", "candidate_rows",
        "completed_trades", "primary_trades", "control_trades", "comparator_trades", "guardrail_counterfactual_trades",
        "primary_net_pnl_sek", "control_net_pnl_sek", "comparator_net_pnl_sek",
        "guardrail_counterfactual_net_pnl_sek", "primary_contracts_with_trades", "all_contracts_with_trades",
        "confirmatory_evidence", "router_active",
    ]
    if batches.empty:
        return pd.DataFrame(columns=columns)
    regime_lookup = batches.set_index("session_date")["primary_regime"].astype(str).to_dict()
    rows = []
    for session_date in batches["session_date"].astype(str).sort_values().unique():
        frame = outcomes[outcomes["session_date"].astype(str).eq(session_date)].copy()
        eligible = frame[frame["morning_contract_eligible"].map(_bool)] if not frame.empty else frame
        trades = eligible[eligible["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED")].copy()
        pnl = pd.to_numeric(trades.get("risk_capped_net_pnl_sek", pd.Series(dtype=float)), errors="coerce")
        by_role = trades.assign(_pnl=pnl).groupby("test_role")["_pnl"].sum().to_dict() if not trades.empty else {}
        count_role = trades.groupby("test_role").size().to_dict() if not trades.empty else {}
        primary_contracts = sorted(trades[trades["test_role"].eq("PRIMARY_HYPOTHESIS")]["contract_id"].unique()) if not trades.empty else []
        all_contracts = sorted(trades["contract_id"].unique()) if not trades.empty else []
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "session_date": session_date,
                "primary_regime": regime_lookup.get(session_date, ""),
                "eligible_ticker_contract_rows": int(eligible["morning_contract_eligible"].map(_bool).sum()) if not eligible.empty else 0,
                "candidate_rows": int(eligible["candidate_generated"].map(_bool).sum()) if not eligible.empty else 0,
                "completed_trades": int(len(trades)),
                "primary_trades": int(count_role.get("PRIMARY_HYPOTHESIS", 0)),
                "control_trades": int(count_role.get("COMPLEMENT_CONTROL", 0)),
                "comparator_trades": int(count_role.get("EXECUTION_COMPARATOR", 0)),
                "guardrail_counterfactual_trades": int(count_role.get("NEGATIVE_GUARDRAIL", 0)),
                "primary_net_pnl_sek": float(by_role.get("PRIMARY_HYPOTHESIS", 0.0)),
                "control_net_pnl_sek": float(by_role.get("COMPLEMENT_CONTROL", 0.0)),
                "comparator_net_pnl_sek": float(by_role.get("EXECUTION_COMPARATOR", 0.0)),
                "guardrail_counterfactual_net_pnl_sek": float(by_role.get("NEGATIVE_GUARDRAIL", 0.0)),
                "primary_contracts_with_trades": "|".join(primary_contracts),
                "all_contracts_with_trades": "|".join(all_contracts),
                "confirmatory_evidence": False,
                "router_active": False,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_contract_performance(outcomes: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    enriched = outcomes.merge(
        registry[
            ["contract_id", "test_role", "primary_regime", "base_challenger_id", "strategy_name", "hypothesis"]
        ],
        on=["contract_id", "test_role"],
        how="left",
        validate="many_to_one",
    ) if not outcomes.empty else outcomes.copy()
    performance = _performance_group(
        enriched,
        ["contract_id", "test_role", "primary_regime", "base_challenger_id", "strategy_name", "hypothesis"],
    )
    if performance.empty:
        return performance
    performance.insert(0, "experiment_id", EXPERIMENT_ID)
    performance["evidence_class"] = RESEARCH_STATUS
    performance["confirmatory_evidence"] = False
    performance["router_active"] = False
    return performance


def build_regime_strategy_matrix(
    batches: pd.DataFrame, outcomes: pd.DataFrame, registry: pd.DataFrame
) -> pd.DataFrame:
    columns = [
        "experiment_id", "observed_regime", "contract_id", "test_role", "required_regime", "strategy_name",
        "locked_regime_match", "observed_regime_sessions", "eligible_ticker_contract_rows", "candidate_rows",
        "completed_trades", "trading_sessions", "independent_companies", "independent_sectors",
        "net_pnl_risk_capped_sek", "average_pnl_per_trade_sek", "win_rate", "profit_factor",
        "historical_replay_only", "confirmatory_evidence", "router_active",
    ]
    session_counts = batches.groupby("primary_regime")["session_date"].nunique().to_dict() if not batches.empty else {}
    regime_lookup = batches.set_index("session_date")["primary_regime"].astype(str).to_dict() if not batches.empty else {}
    frame = outcomes.copy()
    if not frame.empty:
        frame["observed_regime"] = frame["session_date"].astype(str).map(regime_lookup).fillna("")
        frame = frame.merge(
            registry[["contract_id", "test_role", "primary_regime", "strategy_name"]].rename(
                columns={"primary_regime": "required_regime"}
            ),
            on=["contract_id", "test_role"],
            how="left",
            validate="many_to_one",
        )
    grouped = _performance_group(
        frame,
        ["observed_regime", "contract_id", "test_role", "required_regime", "strategy_name"],
    ) if not frame.empty else pd.DataFrame()
    lookup = {
        (str(row.observed_regime), str(row.contract_id)): row._asdict()
        for row in grouped.itertuples(index=False)
    } if not grouped.empty else {}
    rows = []
    for regime in step8.REGIMES:
        for contract in registry.to_dict("records"):
            observed = lookup.get((regime, contract["contract_id"]), {})
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "observed_regime": regime,
                    "contract_id": contract["contract_id"],
                    "test_role": contract["test_role"],
                    "required_regime": contract["primary_regime"],
                    "strategy_name": contract["strategy_name"],
                    "locked_regime_match": regime == contract["primary_regime"],
                    "observed_regime_sessions": int(session_counts.get(regime, 0)),
                    "eligible_ticker_contract_rows": int(observed.get("eligible_ticker_contract_rows", 0)),
                    "candidate_rows": int(observed.get("candidate_rows", 0)),
                    "completed_trades": int(observed.get("completed_trades", 0)),
                    "trading_sessions": int(observed.get("trading_sessions", 0)),
                    "independent_companies": int(observed.get("independent_companies", 0)),
                    "independent_sectors": int(observed.get("independent_sectors", 0)),
                    "net_pnl_risk_capped_sek": float(observed.get("net_pnl_risk_capped_sek", 0.0)),
                    "average_pnl_per_trade_sek": _num(observed.get("average_pnl_per_trade_sek")),
                    "win_rate": _num(observed.get("win_rate")),
                    "profit_factor": _num(observed.get("profit_factor")),
                    "historical_replay_only": True,
                    "confirmatory_evidence": False,
                    "router_active": False,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def build_ticker_sector_performance(
    outcomes: pd.DataFrame, registry: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if outcomes.empty:
        return pd.DataFrame(), pd.DataFrame()
    frame = outcomes.merge(
        registry[["contract_id", "test_role", "primary_regime", "strategy_name"]],
        on=["contract_id", "test_role"],
        how="left",
        validate="many_to_one",
    )
    ticker = _performance_group(
        frame,
        ["contract_id", "test_role", "primary_regime", "strategy_name", "ticker", "company_id", "broad_sector"],
    )
    sector = _performance_group(
        frame,
        ["contract_id", "test_role", "primary_regime", "strategy_name", "broad_sector"],
    )
    for output in (ticker, sector):
        if not output.empty:
            output.insert(0, "experiment_id", EXPERIMENT_ID)
            output["confirmatory_evidence"] = False
            output["router_active"] = False
    return ticker, sector


def build_cumulative_pnl(outcomes: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "experiment_id", "series_id", "series_type", "test_role", "required_regime", "strategy_name",
        "session_date", "daily_net_pnl_sek", "cumulative_net_pnl_sek", "completed_trades_to_date",
        "historical_replay_only", "confirmatory_evidence", "router_active",
    ]
    trades = _completed_trades(outcomes)
    if trades.empty:
        return pd.DataFrame(columns=columns)
    trades = trades.merge(
        registry[["contract_id", "test_role", "primary_regime", "strategy_name"]],
        on=["contract_id", "test_role"],
        how="left",
        validate="many_to_one",
    )
    rows = []
    for contract_id, frame in trades.groupby("contract_id"):
        meta = frame.iloc[0]
        daily = frame.groupby("session_date", as_index=False).agg(
            daily_net_pnl_sek=("risk_capped_net_pnl_sek", "sum"),
            daily_trades=("outcome_id", "size"),
        ).sort_values("session_date")
        daily["cumulative_net_pnl_sek"] = daily["daily_net_pnl_sek"].cumsum()
        daily["completed_trades_to_date"] = daily["daily_trades"].cumsum()
        for row in daily.to_dict("records"):
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "series_id": contract_id,
                    "series_type": "INDIVIDUAL_CONTRACT",
                    "test_role": str(meta["test_role"]),
                    "required_regime": str(meta["primary_regime"]),
                    "strategy_name": str(meta["strategy_name"]),
                    "session_date": row["session_date"],
                    "daily_net_pnl_sek": float(row["daily_net_pnl_sek"]),
                    "cumulative_net_pnl_sek": float(row["cumulative_net_pnl_sek"]),
                    "completed_trades_to_date": int(row["completed_trades_to_date"]),
                    "historical_replay_only": True,
                    "confirmatory_evidence": False,
                    "router_active": False,
                }
            )
    primary = trades[trades["test_role"].eq("PRIMARY_HYPOTHESIS")].copy()
    if not primary.empty:
        daily = primary.groupby("session_date", as_index=False).agg(
            daily_net_pnl_sek=("risk_capped_net_pnl_sek", "sum"),
            daily_trades=("outcome_id", "size"),
        ).sort_values("session_date")
        daily["cumulative_net_pnl_sek"] = daily["daily_net_pnl_sek"].cumsum()
        daily["completed_trades_to_date"] = daily["daily_trades"].cumsum()
        for row in daily.to_dict("records"):
            rows.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "series_id": "PRIMARY_HYPOTHESES_AGGREGATE",
                    "series_type": "NON_PORTFOLIO_PRIMARY_FAMILY_AGGREGATE",
                    "test_role": "PRIMARY_HYPOTHESIS",
                    "required_regime": "MULTIPLE_LOCKED_REGIMES",
                    "strategy_name": "PRIMARY_FAMILY_AGGREGATE",
                    "session_date": row["session_date"],
                    "daily_net_pnl_sek": float(row["daily_net_pnl_sek"]),
                    "cumulative_net_pnl_sek": float(row["cumulative_net_pnl_sek"]),
                    "completed_trades_to_date": int(row["completed_trades_to_date"]),
                    "historical_replay_only": True,
                    "confirmatory_evidence": False,
                    "router_active": False,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def build_comparisons(contract_performance: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "experiment_id", "comparison_id", "left_contract_id", "right_contract_id", "left_trades", "right_trades",
        "left_net_pnl_sek", "right_net_pnl_sek", "net_pnl_difference_left_minus_right_sek",
        "left_profit_factor", "right_profit_factor", "interpretation", "historical_replay_only",
        "confirmatory_evidence", "router_active",
    ]
    lookup = contract_performance.set_index("contract_id").to_dict("index") if not contract_performance.empty else {}
    rows = []
    for pair in COMPARISON_PAIRS:
        left = lookup.get(pair["left_contract_id"], {})
        right = lookup.get(pair["right_contract_id"], {})
        left_net = float(left.get("net_pnl_risk_capped_sek", 0.0))
        right_net = float(right.get("net_pnl_risk_capped_sek", 0.0))
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                **pair,
                "left_trades": int(left.get("completed_trades", 0)),
                "right_trades": int(right.get("completed_trades", 0)),
                "left_net_pnl_sek": left_net,
                "right_net_pnl_sek": right_net,
                "net_pnl_difference_left_minus_right_sek": left_net - right_net,
                "left_profit_factor": _num(left.get("profit_factor")),
                "right_profit_factor": _num(right.get("profit_factor")),
                "historical_replay_only": True,
                "confirmatory_evidence": False,
                "router_active": False,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_audit(
    run_log: pd.DataFrame,
    batches: pd.DataFrame,
    decisions: pd.DataFrame,
    outcome_batches: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> pd.DataFrame:
    base = step9i.build_audit(decisions, outcomes, batches, outcome_batches)
    if not base.empty:
        base["experiment_id"] = EXPERIMENT_ID
        base["interpretation"] = "Historical replay: " + base["interpretation"].astype(str)
    post_cutoff = 0
    if not decisions.empty:
        labels = decisions["max_router_source_label"].astype(str)
        post_cutoff = int((labels.ne("") & labels.gt(step9i.LATEST_ALLOWED_BAR_LABEL)).sum())
    confirmatory_batches = int(
        batches["prospective_status"].astype(str).eq("PROSPECTIVE_CONFIRMATORY_ELIGIBLE").sum()
    ) if not batches.empty else 0
    expected_rows = len(batches) * len(step9h.CONTRACTS) * len(step9i.HOLDOUT_TICKERS)
    row_count_failure = abs(len(decisions) - expected_rows)
    duplicate_sessions = int(batches["session_date"].duplicated().sum()) if not batches.empty else 0
    completed_run_days = int(run_log["eod_status"].eq("EOD_EVALUATED").sum()) if not run_log.empty else 0
    extra = pd.DataFrame(
        [
            {
                "experiment_id": EXPERIMENT_ID,
                "audit_item": "REPLAY_BATCHES_NEVER_CONFIRMATORY",
                "rows_checked": len(batches),
                "failures": confirmatory_batches,
                "audit_pass": confirmatory_batches == 0,
                "interpretation": "Every historical replay batch is permanently excluded from prospective confirmation.",
            },
            {
                "experiment_id": EXPERIMENT_ID,
                "audit_item": "REPLAY_ROUTER_INPUTS_STOP_AT_0940",
                "rows_checked": len(decisions),
                "failures": post_cutoff,
                "audit_pass": post_cutoff == 0,
                "interpretation": "Every replay decision uses same-day source labels no later than 09:40.",
            },
            {
                "experiment_id": EXPERIMENT_ID,
                "audit_item": "REPLAY_DECISION_GRID_COMPLETE",
                "rows_checked": len(decisions),
                "failures": row_count_failure,
                "audit_pass": row_count_failure == 0,
                "interpretation": "Each sealed replay day contains all eight contracts for all 18 holdout tickers.",
            },
            {
                "experiment_id": EXPERIMENT_ID,
                "audit_item": "ONE_REPLAY_BATCH_PER_SESSION",
                "rows_checked": len(batches),
                "failures": duplicate_sessions,
                "audit_pass": duplicate_sessions == 0,
                "interpretation": "The historical replay ledger contains at most one immutable morning batch per session.",
            },
            {
                "experiment_id": EXPERIMENT_ID,
                "audit_item": "COMPLETED_REPLAY_DAYS_HAVE_OUTCOME_BATCHES",
                "rows_checked": completed_run_days,
                "failures": max(0, completed_run_days - len(outcome_batches)),
                "audit_pass": len(outcome_batches) >= completed_run_days,
                "interpretation": "Every run-log day marked EOD evaluated has a sealed replay outcome batch.",
            },
        ]
    )
    return pd.concat([base, extra], ignore_index=True)


def build_summary(
    start_date: str,
    end_date: str,
    run_log: pd.DataFrame,
    batches: pd.DataFrame,
    decisions: pd.DataFrame,
    outcome_batches: pd.DataFrame,
    outcomes: pd.DataFrame,
    audit: pd.DataFrame,
) -> pd.DataFrame:
    trades = _completed_trades(outcomes)
    effective_start = str(batches["session_date"].min()) if not batches.empty else ""
    effective_end = str(batches["session_date"].max()) if not batches.empty else ""
    classification = (
        "HISTORICAL_REPLAY_COMPLETE_NOT_CONFIRMATORY"
        if not batches.empty and not audit.empty and audit["audit_pass"].map(_bool).all()
        else "HISTORICAL_REPLAY_AUDIT_REVIEW_REQUIRED"
        if not batches.empty
        else "HISTORICAL_REPLAY_NO_ELIGIBLE_SESSIONS"
    )
    return pd.DataFrame(
        [
            {
                "experiment_id": EXPERIMENT_ID,
                "research_status": RESEARCH_STATUS,
                "code_version": CODE_VERSION,
                "step9i_code_version": step9i.CODE_VERSION,
                "requested_start_date": start_date,
                "requested_end_date": end_date,
                "effective_start_date": effective_start,
                "effective_end_date": effective_end,
                "available_dates_examined": int(len(run_log)),
                "morning_batches_sealed": int(len(batches)),
                "eod_batches_sealed": int(len(outcome_batches)),
                "regimes_observed": int(batches["primary_regime"].nunique()) if not batches.empty else 0,
                "decision_rows": int(len(decisions)),
                "eligible_ticker_contract_rows": int(decisions["contract_eligible"].map(_bool).sum()) if not decisions.empty else 0,
                "outcome_rows": int(len(outcomes)),
                "completed_trades": int(len(trades)),
                "primary_completed_trades": int(trades["test_role"].eq("PRIMARY_HYPOTHESIS").sum()) if not trades.empty else 0,
                "control_completed_trades": int(trades["test_role"].eq("COMPLEMENT_CONTROL").sum()) if not trades.empty else 0,
                "comparator_completed_trades": int(trades["test_role"].eq("EXECUTION_COMPARATOR").sum()) if not trades.empty else 0,
                "guardrail_counterfactual_trades": int(trades["test_role"].eq("NEGATIVE_GUARDRAIL").sum()) if not trades.empty else 0,
                "audit_pass": bool(not audit.empty and audit["audit_pass"].map(_bool).all()),
                "classification": classification,
                "confirmatory_evidence": False,
                "strategies_promoted": 0,
                "router_active": False,
                "interpretation": (
                    "Exact Step 9I rules replayed day by day using only bars through 09:40, then evaluated on later bars. "
                    "This supports regime-strategy understanding and operational validation but never counts as live prospective evidence."
                ),
            }
        ]
    )


def export_replay_outputs(
    start_date: str,
    end_date: str,
    run_log: pd.DataFrame,
    ledger_db: Path = REPLAY_LEDGER_DB,
) -> dict[str, pd.DataFrame]:
    batches, decisions, outcome_batches, outcomes = _read_replay_tables(ledger_db)
    registry = _contract_registry()
    daily_regimes = build_daily_regimes(batches)
    daily_summary = build_daily_summary(batches, outcomes)
    contract_performance = build_contract_performance(outcomes, registry)
    regime_strategy = build_regime_strategy_matrix(batches, outcomes, registry)
    ticker_performance, sector_performance = build_ticker_sector_performance(outcomes, registry)
    cumulative = build_cumulative_pnl(outcomes, registry)
    comparisons = build_comparisons(contract_performance)
    audit = build_audit(run_log, batches, decisions, outcome_batches, outcomes)
    summary = build_summary(
        start_date, end_date, run_log, batches, decisions, outcome_batches, outcomes, audit
    )

    outputs = {
        str(RUN_LOG_FILE): run_log,
        str(SUMMARY_FILE): summary,
        str(DECISION_BATCH_FILE): batches,
        str(DECISION_FILE): decisions,
        str(OUTCOME_BATCH_FILE): outcome_batches,
        str(OUTCOME_FILE): outcomes,
        str(DAILY_REGIME_FILE): daily_regimes,
        str(DAILY_SUMMARY_FILE): daily_summary,
        str(REGIME_STRATEGY_MATRIX_FILE): regime_strategy,
        str(CONTRACT_PERFORMANCE_FILE): contract_performance,
        str(TICKER_PERFORMANCE_FILE): ticker_performance,
        str(SECTOR_PERFORMANCE_FILE): sector_performance,
        str(CUMULATIVE_PNL_FILE): cumulative,
        str(COMPARISON_FILE): comparisons,
        str(AUDIT_FILE): audit,
        str(CONTRACT_REGISTRY_FILE): registry,
    }
    for path, frame in outputs.items():
        export_csv_for_power_bi(frame, Path(path))
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay the exact frozen Step 9I morning/EOD process across historical sessions."
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--source-db", type=Path, default=step9i.SHADOW_INTRADAY_DB)
    parser.add_argument("--ledger-db", type=Path, default=REPLAY_LEDGER_DB)
    parser.add_argument("--reset-replay", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_date > args.end_date:
        raise ValueError("--start-date must be on or before --end-date.")
    prices = step9i.load_shadow_prices(args.source_db)
    if prices.empty:
        raise step9i.ShadowDataNotReady(
            f"No Step 9I shadow prices were found at {args.source_db}. Run collect_step9i_shadow_data.ps1 first."
        )

    print("\n=== STEP 9I-R HISTORICAL WALK-FORWARD REPLAY ===")
    print(f"Experiment       : {EXPERIMENT_ID}")
    print(f"Research status  : {RESEARCH_STATUS}")
    print(f"Requested window : {args.start_date} through {args.end_date}")
    print(f"Source database  : {args.source_db}")
    print(f"Replay ledger    : {args.ledger_db}")
    print("Each historical day is classified from information available through 09:40, then evaluated using later bars.")
    print("The replay is permanently non-confirmatory and cannot activate the router or alter the live Step 9I ledger.")

    run_log = run_replay(
        prices=prices,
        start_date=args.start_date,
        end_date=args.end_date,
        ledger_db=args.ledger_db,
        source_db=args.source_db,
        reset_replay=args.reset_replay,
    )
    outputs = export_replay_outputs(args.start_date, args.end_date, run_log, args.ledger_db)
    summary = outputs[str(SUMMARY_FILE)].iloc[0]

    print("\n=== STEP 9I-R REPLAY RESULT ===")
    print(f"Available dates examined : {int(summary['available_dates_examined'])}")
    print(f"Morning / EOD batches    : {int(summary['morning_batches_sealed'])}/{int(summary['eod_batches_sealed'])}")
    print(f"Effective replay window  : {summary['effective_start_date']} through {summary['effective_end_date']}")
    print(f"Regimes observed         : {int(summary['regimes_observed'])}")
    print(f"Eligible rows / trades   : {int(summary['eligible_ticker_contract_rows'])}/{int(summary['completed_trades'])}")
    print(f"Audit pass               : {bool(summary['audit_pass'])}")
    print(f"Classification           : {summary['classification']}")
    print("Use step9ir_replay_regime_strategy_matrix.csv and step9ir_replay_contract_performance.csv to inspect the regime-strategy relationship.")


if __name__ == "__main__":
    main()
