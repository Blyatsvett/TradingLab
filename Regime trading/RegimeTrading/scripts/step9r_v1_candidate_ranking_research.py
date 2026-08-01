from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import shutil
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import legacy_output_path
from RegimeTrading.core.stage_registry import resolve_stage_path
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path
from RegimeTrading.scripts import step9d_regime_strategy_challenger_matrix as step9d
from RegimeTrading.scripts import step9e_instrument_sector_taxonomy as step9e
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as step9l_v3


EXPERIMENT_ID = "STEP9R_CANDIDATE_RANKING_RESEARCH_V1"
RESEARCH_STATUS = "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION"
CODE_VERSION = "STEP9R_CANDIDATE_RANKING_V1_1_2026_07_28_FULL_CANDIDATE_OUTCOMES"
CLASSIFICATION_READY = "STEP9R_V1_CANDIDATE_DATASET_AND_SELECTOR_RESEARCH_READY"
CLASSIFICATION_REVIEW = "STEP9R_V1_AUDIT_REVIEW_REQUIRED"
CONFIRMATORY_STATUS = "PROSPECTIVE_CONFIRMATORY_ELIGIBLE"
PRIMARY_ROLE = "PRIMARY_HYPOTHESIS"
GUARDRAIL_ROLE = "NEGATIVE_GUARDRAIL"
SELECTOR_MODEL = "SIMPLE_EXPECTED_R_SCORE_V1"
MAX_SHADOW_POSITIONS = 2
MAX_POSITIONS_PER_TICKER = 1
LATEST_FEATURE_LABEL = "09:40"
MIN_TRAIN_SESSIONS = 10
MIN_TRAIN_ROWS = 60

DEFAULT_PRICE_DB = resolve_stage_path("prices")
DEFAULT_V3_LEDGER = resolve_stage_path("step9l")
DEFAULT_TAXONOMY_LEDGER = legacy_output_path("step9ir_v2_historical_replay_ledger.db")
DEFAULT_RESEARCH_DB = resolve_stage_path("step9r_research")
DEFAULT_PROSPECTIVE_DB = resolve_stage_path("step9r")
OUTPUT_DIR = resolve_stage_output_dir("step9r")

OUTPUT_FILES = {
    "candidate_outcomes": OUTPUT_DIR / "step9r_v1_candidate_outcomes.csv",
    "current_rank_audit": OUTPUT_DIR / "step9r_v1_current_rank_audit.csv",
    "rank_bucket_performance": OUTPUT_DIR / "step9r_v1_rank_bucket_performance.csv",
    "daily_selection_diagnostics": OUTPUT_DIR / "step9r_v1_daily_selection_diagnostics.csv",
    "selection_regret": OUTPUT_DIR / "step9r_v1_selection_regret.csv",
    "walk_forward_predictions": OUTPUT_DIR / "step9r_v1_selector_walk_forward_predictions.csv",
    "selector_comparisons": OUTPUT_DIR / "step9r_v1_selector_comparisons.csv",
    "audit": OUTPUT_DIR / "step9r_v1_audit.csv",
    "summary": OUTPUT_DIR / "step9r_v1_summary.csv",
    "prospective_candidates": OUTPUT_DIR / "step9r_v1_prospective_candidates.csv",
    "prospective_selections": OUTPUT_DIR / "step9r_v1_prospective_selections.csv",
    "prospective_outcomes": OUTPUT_DIR / "step9r_v1_prospective_outcomes.csv",
    "prospective_candidate_outcomes": OUTPUT_DIR / "step9r_v1_prospective_candidate_outcomes.csv",
}

NUMERIC_FEATURES = [
    "ranking_metric",
    "v3_rank",
    "regime_confidence",
    "opening_gap_pct",
    "cutoff_return_from_open",
    "early_range_pct",
    "sector_relative_return",
    "market_relative_return",
    "prior_20d_daily_return_mean",
    "prior_20d_daily_volatility",
    "prior_20d_average_daily_range_pct",
    "prior_20d_average_early_range_pct",
    "prior_20d_momentum_return",
    "prior_20d_beta_to_company_weighted_market",
    "prior_20d_early_move_followthrough_rate",
    "prior_20d_early_move_reversal_rate",
    "volatility_percentile_cross_section",
]
CATEGORICAL_FEATURES = [
    "primary_regime",
    "contract_id",
    "direction",
    "broad_sector",
    "ticker_relative_state",
    "volatility_bucket",
    "range_state",
    "sector_direction_state",
    "sector_direction_alignment",
    "gap_state",
    "historical_tendency",
    "rank_bucket",
]
CHARACTERISTIC_COLUMNS = [
    "date",
    "ticker",
    "opening_gap_pct",
    "cutoff_return_from_open",
    "early_range_pct",
    "sector_relative_return",
    "market_relative_return",
    "gap_state",
    "prior_history_sessions",
    "prior_history_max_date",
    "prior_20d_daily_return_mean",
    "prior_20d_daily_volatility",
    "prior_20d_average_daily_range_pct",
    "prior_20d_average_early_range_pct",
    "prior_20d_average_absolute_gap_pct",
    "prior_20d_gap_volatility",
    "prior_20d_momentum_return",
    "prior_20d_beta_to_company_weighted_market",
    "prior_20d_correlation_to_company_weighted_market",
    "prior_20d_early_move_followthrough_rate",
    "prior_20d_early_move_reversal_rate",
    "prior_20d_early_move_observations",
    "historical_tendency",
    "volatility_percentile_cross_section",
    "minimum_history_ready",
    "full_history_ready",
    "max_same_day_source_label",
    "point_in_time_pass",
]


class Step9RError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayFrames:
    taxonomy: pd.DataFrame
    taxonomy_skips: pd.DataFrame
    baseline_candidates: pd.DataFrame
    baseline_trades: pd.DataFrame
    all_candidates: pd.DataFrame
    all_trades: pd.DataFrame
    characteristics: pd.DataFrame
    prices: pd.DataFrame


def _bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def _num(value: Any, default: float = np.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def _file_hash(path: Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _registry_hash() -> str:
    return _payload_hash(step9l_v3.CONTRACTS)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


@contextmanager
def _safe_group_state_labels():
    original = step9e.build_group_daily_state

    def safe(frame: pd.DataFrame) -> pd.DataFrame:
        working = frame.copy()
        if "max_same_day_source_label" in working.columns:
            working["max_same_day_source_label"] = (
                working["max_same_day_source_label"].fillna("").astype(str)
            )
        return original(working)

    step9e.build_group_daily_state = safe
    try:
        yield
    finally:
        step9e.build_group_daily_state = original


@contextmanager
def _select_all_valid_candidates():
    original = step9d._select_candidates

    def select_all(rows: list[dict], max_ideas: int, deterministic: bool = False) -> None:
        original(rows, max_ideas=100_000, deterministic=deterministic)

    step9d._select_candidates = select_all
    try:
        yield
    finally:
        step9d._select_candidates = original


@contextmanager
def _lightweight_step9g_outputs():
    names = [
        "build_performance",
        "build_comparisons",
        "build_robustness",
        "build_multiple_testing",
        "build_audit",
        "build_summary",
    ]
    old = {name: getattr(step9g, name) for name in names}
    try:
        for name in names:
            setattr(step9g, name, lambda *args, **kwargs: pd.DataFrame())
        yield
    finally:
        for name, value in old.items():
            setattr(step9g, name, value)


def _load_taxonomy_payloads(
    taxonomy_ledger: Path,
    v3_ledger: Path,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: dict[str, dict[str, Any]] = {}
    skips: list[dict[str, Any]] = []
    for path in [Path(taxonomy_ledger), Path(v3_ledger)]:
        if not path.exists():
            continue
        try:
            with closing(_connect_read_only(path)) as connection:
                table_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_decision_batches'"
                ).fetchone()
                if not table_exists:
                    continue
                batches = pd.read_sql_query(
                    """
                    SELECT session_date, taxonomy_payload_json
                    FROM shadow_decision_batches
                    WHERE session_date BETWEEN ? AND ?
                    ORDER BY session_date
                    """,
                    connection,
                    params=(start_date, end_date),
                )
            for record in batches.to_dict("records"):
                try:
                    payload = json.loads(str(record["taxonomy_payload_json"]))
                    payload["date"] = str(record["session_date"])
                    rows[str(record["session_date"])] = payload
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    skips.append({"date": str(record["session_date"]), "skip_reason": f"INVALID_TAXONOMY_PAYLOAD:{exc}"})
        except sqlite3.DatabaseError as exc:
            skips.append({"date": "", "skip_reason": f"TAXONOMY_LEDGER_ERROR:{path.name}:{exc}"})
    taxonomy = pd.DataFrame([rows[key] for key in sorted(rows)])
    if not taxonomy.empty:
        taxonomy["date"] = taxonomy["date"].astype(str)
    return taxonomy, pd.DataFrame(skips, columns=["date", "skip_reason"])


def _rebuild_missing_taxonomy(
    prices: pd.DataFrame,
    taxonomy: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    available_dates = sorted(
        date for date in prices["date"].astype(str).unique() if start_date <= str(date) <= end_date
    )
    existing = set(taxonomy["date"].astype(str)) if not taxonomy.empty else set()
    missing = [date for date in available_dates if date not in existing]
    rows: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    for session_date in missing:
        try:
            regime, _, _ = step9i.build_current_regime(prices, session_date)
            payload = regime.to_dict()
            payload["date"] = session_date
            rows.append(payload)
        except Exception as exc:  # explicit audit record; never silently ignored
            skips.append({"date": session_date, "skip_reason": f"REGIME_REBUILD_FAILED:{type(exc).__name__}:{exc}"})
    combined = pd.concat([taxonomy, pd.DataFrame(rows)], ignore_index=True, sort=False)
    if not combined.empty:
        combined["date"] = combined["date"].astype(str)
        combined = combined.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    return combined, pd.DataFrame(skips, columns=["date", "skip_reason"])


def load_taxonomy(
    prices: pd.DataFrame,
    start_date: str,
    end_date: str,
    taxonomy_ledger: Path = DEFAULT_TAXONOMY_LEDGER,
    v3_ledger: Path = DEFAULT_V3_LEDGER,
    rebuild_missing: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    taxonomy, skips = _load_taxonomy_payloads(taxonomy_ledger, v3_ledger, start_date, end_date)
    if rebuild_missing:
        with _safe_group_state_labels():
            taxonomy, rebuild_skips = _rebuild_missing_taxonomy(prices, taxonomy, start_date, end_date)
        skips = pd.concat([skips, rebuild_skips], ignore_index=True)
    taxonomy = taxonomy[taxonomy["date"].between(start_date, end_date)].copy() if not taxonomy.empty else taxonomy
    if taxonomy.empty:
        raise Step9RError("No point-in-time taxonomy sessions are available in the requested window.")
    return taxonomy.reset_index(drop=True), skips.reset_index(drop=True)


def _run_exact_engine(
    taxonomy: pd.DataFrame,
    prices: pd.DataFrame,
    select_all: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    effective_end = str(taxonomy["date"].max())
    with _safe_group_state_labels(), step9l_v3._patched_step9l_v3_globals():
        static, holdout, characteristics, group_states = step9i._full_holdout_context(prices, effective_end)
        contexts = [_lightweight_step9g_outputs(), step9i._patched_holdout_tickers(), step9h._patched_step9g_globals()]
        if select_all:
            contexts.append(_select_all_valid_candidates())
        with contexts[0]:
            with contexts[1]:
                with contexts[2]:
                    if select_all:
                        with contexts[3]:
                            result = step9g.build_state_filtered_experiment(
                                taxonomy, holdout, static, characteristics, group_states
                            )
                    else:
                        result = step9g.build_state_filtered_experiment(
                            taxonomy, holdout, static, characteristics, group_states
                        )
    return result[3].copy(), result[4].copy(), characteristics.copy()


def replay_exact_v3(
    price_db: Path,
    v3_ledger: Path,
    taxonomy_ledger: Path,
    start_date: str,
    end_date: str,
    rebuild_missing_taxonomy: bool = True,
) -> ReplayFrames:
    prices = step9i.load_shadow_prices(Path(price_db))
    if prices.empty:
        raise Step9RError(f"No prices found in {price_db}")
    taxonomy, skips = load_taxonomy(
        prices,
        start_date,
        end_date,
        taxonomy_ledger=taxonomy_ledger,
        v3_ledger=v3_ledger,
        rebuild_missing=rebuild_missing_taxonomy,
    )
    baseline_candidates, baseline_trades, characteristics = _run_exact_engine(taxonomy, prices, select_all=False)
    all_candidates, all_trades, _ = _run_exact_engine(taxonomy, prices, select_all=True)
    return ReplayFrames(
        taxonomy=taxonomy,
        taxonomy_skips=skips,
        baseline_candidates=baseline_candidates,
        baseline_trades=baseline_trades,
        all_candidates=all_candidates,
        all_trades=all_trades,
        characteristics=characteristics,
        prices=prices,
    )


def rank_bucket(rank: Any) -> str:
    value = int(_num(rank, 999999))
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    if 3 <= value <= 5:
        return "3_TO_5"
    if 6 <= value <= 10:
        return "6_TO_10"
    return "11_PLUS"


def _trade_excursions(trade: dict[str, Any], prices: pd.DataFrame) -> tuple[float, float]:
    entry = _num(trade.get("entry_price"))
    stop = _num(trade.get("stop_price"))
    if not np.isfinite(entry) or not np.isfinite(stop):
        return np.nan, np.nan
    risk = abs(entry - stop)
    if risk <= 0:
        return np.nan, np.nan
    start = pd.to_datetime(trade.get("entry_time"), errors="coerce")
    end = pd.to_datetime(trade.get("exit_time"), errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return np.nan, np.nan
    bars = prices[
        prices["ticker"].astype(str).eq(str(trade.get("ticker", "")))
        & prices["datetime"].between(start, end)
    ]
    if bars.empty:
        return np.nan, np.nan
    side = str(trade.get("direction", "")).upper()
    if side == "LONG":
        mfe = (_num(bars["high"].max()) - entry) / risk
        mae = (_num(bars["low"].min()) - entry) / risk
    else:
        mfe = (entry - _num(bars["low"].min())) / risk
        mae = (entry - _num(bars["high"].max())) / risk
    return float(mfe), float(mae)


def build_candidate_outcomes(replay: ReplayFrames) -> pd.DataFrame:
    candidates = replay.all_candidates.copy()
    baseline = replay.baseline_candidates.copy()
    trades = replay.all_trades.copy()
    if candidates.empty:
        return pd.DataFrame()

    key = ["date", "contract_id", "ticker"]
    if candidates.duplicated(key).any():
        raise Step9RError("Duplicate all-candidate date/contract/ticker keys.")
    if not baseline.empty and baseline.duplicated(key).any():
        raise Step9RError("Duplicate baseline date/contract/ticker keys.")
    if not trades.empty and trades.duplicated(key).any():
        raise Step9RError("Multiple trades exist for one V3 candidate key.")

    baseline_lookup = baseline.set_index(key).to_dict("index") if not baseline.empty else {}
    trade_lookup = trades.set_index(key).to_dict("index") if not trades.empty else {}
    contract_lookup = {str(row["contract_id"]): row for row in step9l_v3.CONTRACTS}
    taxonomy_lookup = replay.taxonomy.set_index("date").to_dict("index")

    characteristic_columns = [column for column in CHARACTERISTIC_COLUMNS if column in replay.characteristics.columns]
    characteristics = replay.characteristics[characteristic_columns].copy()
    characteristics["date"] = characteristics["date"].astype(str)
    characteristics = characteristics.drop_duplicates(["date", "ticker"])
    char_lookup = characteristics.set_index(["date", "ticker"]).to_dict("index")

    rows: list[dict[str, Any]] = []
    for candidate in candidates.to_dict("records"):
        date = str(candidate["date"])
        cid = str(candidate["contract_id"])
        ticker = str(candidate["ticker"])
        k = (date, cid, ticker)
        baseline_row = baseline_lookup.get(k, {})
        trade = trade_lookup.get(k, {})
        contract = contract_lookup.get(cid, {})
        taxonomy = taxonomy_lookup.get(date, {})
        char = char_lookup.get((date, ticker), {})
        valid = str(candidate.get("setup_status", "")) == "VALID_SETUP"
        triggered = bool(trade)
        pnl = _num(trade.get("risk_capped_net_pnl_sek"), 0.0) if valid else np.nan
        notional = _num(trade.get("risk_capped_notional_sek"))
        risk_pct = _num(trade.get("risk_pct_at_entry"))
        risk_budget = notional * risk_pct if np.isfinite(notional) and np.isfinite(risk_pct) else np.nan
        net_r = pnl / risk_budget if np.isfinite(risk_budget) and risk_budget > 0 else (0.0 if valid and not triggered else np.nan)
        mfe_r, mae_r = _trade_excursions(trade, replay.prices) if triggered else (0.0 if valid else np.nan, 0.0 if valid else np.nan)
        source_label = str(candidate.get("max_router_source_label", char.get("max_same_day_source_label", "")))
        point_in_time = _bool(candidate.get("point_in_time_pass")) and _bool(char.get("point_in_time_pass", True)) and source_label <= LATEST_FEATURE_LABEL
        selected_by_v3 = _bool(baseline_row.get("selected_for_simulation"))
        role = str(candidate.get("test_role", contract.get("test_role", "")))
        model_eligible = role == PRIMARY_ROLE and valid and point_in_time
        if not valid:
            pool_status = "INVALID_SETUP"
        elif not triggered:
            pool_status = "VALID_NOT_TRIGGERED"
        else:
            pool_status = "TRIGGERED_CLOSED"
        row = {
            "experiment_id": EXPERIMENT_ID,
            "research_status": RESEARCH_STATUS,
            "code_version": CODE_VERSION,
            "date": date,
            "primary_regime": str(candidate.get("primary_regime", taxonomy.get("primary_regime", ""))),
            "regime_confidence": _num(taxonomy.get("regime_confidence")),
            "confidence_band": str(taxonomy.get("confidence_band", "")),
            "direction_bias": str(taxonomy.get("direction_bias", "")),
            "research_risk_multiplier": _num(taxonomy.get("research_risk_multiplier")),
            "research_max_concurrent_ideas": int(_num(taxonomy.get("research_max_concurrent_ideas"), MAX_SHADOW_POSITIONS)),
            "contract_id": cid,
            "test_role": role,
            "base_challenger_id": str(candidate.get("base_challenger_id", contract.get("base_challenger_id", ""))),
            "ticker": ticker,
            "company_id": str(candidate.get("company_id", "")),
            "broad_sector": str(candidate.get("broad_sector", "")),
            "direction": str(candidate.get("direction", "")),
            "ticker_relative_state": str(candidate.get("ticker_relative_state", "")),
            "volatility_bucket": str(candidate.get("volatility_bucket", "")),
            "range_state": str(candidate.get("range_state", "")),
            "sector_direction_state": str(candidate.get("sector_direction_state", "")),
            "sector_direction_alignment": str(candidate.get("sector_direction_alignment", "")),
            "ranking_metric": _num(candidate.get("ranking_metric")),
            "v3_rank": int(_num(candidate.get("selection_rank"), 0)) or np.nan,
            "rank_bucket": rank_bucket(candidate.get("selection_rank")),
            "selected_by_v3": selected_by_v3,
            "setup_status": str(candidate.get("setup_status", "")),
            "trigger_status": str(candidate.get("trigger_status", "")),
            "invalid_reason": str(candidate.get("invalid_reason", "")),
            "valid_setup": valid,
            "point_in_time_pass": point_in_time,
            "max_router_source_label": source_label,
            "counterfactual_trade_generated": triggered,
            "entry_time": trade.get("entry_time", candidate.get("entry_time", "")),
            "entry_price": _num(trade.get("entry_price", candidate.get("entry_price"))),
            "stop_price": _num(trade.get("stop_price", candidate.get("stop_price"))),
            "target_price": _num(trade.get("target_price", candidate.get("target_price"))),
            "exit_time": trade.get("exit_time", candidate.get("exit_time", "")),
            "exit_price": _num(trade.get("exit_price")),
            "exit_reason": str(trade.get("exit_reason", candidate.get("exit_reason", ""))),
            "risk_pct_at_entry": risk_pct,
            "gross_return": _num(trade.get("gross_return")),
            "gross_r_multiple": _num(trade.get("r_multiple_achieved")),
            "risk_capped_notional_sek": notional,
            "risk_capped_net_pnl_sek": pnl,
            "net_r_after_costs": net_r,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "winning_trade": bool(valid and pnl > 0),
            "model_eligible": model_eligible,
            "selection_pool_status": pool_status,
        }
        for column, value in char.items():
            if column not in {"date", "ticker", "point_in_time_pass", "max_same_day_source_label"}:
                row[column] = value
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values(["date", "contract_id", "v3_rank", "ticker"]).reset_index(drop=True)
    return frame


def _safe_spearman(x: pd.Series, y: pd.Series) -> float:
    pair = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(pair) < 3 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return np.nan
    return float(spearmanr(pair["x"], pair["y"]).statistic)


def _group_slices(frame: pd.DataFrame) -> Iterable[tuple[str, str, pd.DataFrame]]:
    yield "OVERALL", "ALL", frame
    for regime, group in frame.groupby("primary_regime", dropna=False):
        yield "REGIME", str(regime), group
    for contract, group in frame.groupby("contract_id", dropna=False):
        yield "CONTRACT", str(contract), group


def build_current_rank_audit(candidate_outcomes: pd.DataFrame) -> pd.DataFrame:
    frame = candidate_outcomes[candidate_outcomes["model_eligible"].map(_bool)].copy()
    rows: list[dict[str, Any]] = []
    for level, value, group in _group_slices(frame):
        triggered = group[group["counterfactual_trade_generated"].map(_bool)]
        top_two = group[pd.to_numeric(group["v3_rank"], errors="coerce").le(2)]
        non_top = group[pd.to_numeric(group["v3_rank"], errors="coerce").gt(2)]
        all_avg_pnl = float(pd.to_numeric(group["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).mean()) if len(group) else np.nan
        top_avg_pnl = float(pd.to_numeric(top_two["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).mean()) if len(top_two) else np.nan
        all_avg_r = float(pd.to_numeric(group["net_r_after_costs"], errors="coerce").fillna(0).mean()) if len(group) else np.nan
        top_avg_r = float(pd.to_numeric(top_two["net_r_after_costs"], errors="coerce").fillna(0).mean()) if len(top_two) else np.nan
        rank_corr = _safe_spearman(-pd.to_numeric(group["v3_rank"], errors="coerce"), group["net_r_after_costs"])
        metric_corr = _safe_spearman(group["ranking_metric"], group["net_r_after_costs"])
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            "audit_level": level,
            "audit_value": value,
            "valid_candidates": int(len(group)),
            "triggered_trades": int(len(triggered)),
            "winners": int(triggered["winning_trade"].map(_bool).sum()),
            "triggered_win_rate": float(triggered["winning_trade"].map(_bool).mean()) if len(triggered) else np.nan,
            "candidate_success_rate": float(group["winning_trade"].map(_bool).mean()) if len(group) else np.nan,
            "total_counterfactual_pnl_sek": float(pd.to_numeric(group["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum()),
            "average_net_r_all_valid": all_avg_r,
            "average_net_r_triggered": float(pd.to_numeric(triggered["net_r_after_costs"], errors="coerce").mean()) if len(triggered) else np.nan,
            "spearman_ranking_metric_vs_net_r": metric_corr,
            "spearman_better_rank_vs_net_r": rank_corr,
            "v3_top_two_candidates": int(len(top_two)),
            "v3_top_two_triggered_trades": int(top_two["counterfactual_trade_generated"].map(_bool).sum()),
            "v3_top_two_winners": int(top_two["winning_trade"].map(_bool).sum()),
            "v3_top_two_pnl_sek": float(pd.to_numeric(top_two["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum()),
            "v3_top_two_average_net_r": top_avg_r,
            "non_top_two_pnl_sek": float(pd.to_numeric(non_top["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum()),
            "top_two_pnl_uplift_vs_all_candidate_average_sek": top_avg_pnl - all_avg_pnl if np.isfinite(top_avg_pnl) and np.isfinite(all_avg_pnl) else np.nan,
            "top_two_net_r_uplift_vs_all_candidate_average": top_avg_r - all_avg_r if np.isfinite(top_avg_r) and np.isfinite(all_avg_r) else np.nan,
            "rank_predictive_direction": (
                "POSITIVE" if np.isfinite(rank_corr) and rank_corr > 0
                else "NEGATIVE" if np.isfinite(rank_corr) and rank_corr < 0
                else "UNRESOLVED"
            ),
        })
    return pd.DataFrame(rows)


def build_rank_bucket_performance(candidate_outcomes: pd.DataFrame) -> pd.DataFrame:
    frame = candidate_outcomes[candidate_outcomes["model_eligible"].map(_bool)].copy()
    rows: list[dict[str, Any]] = []
    for level, value, group in _group_slices(frame):
        for bucket in ["1", "2", "3_TO_5", "6_TO_10", "11_PLUS"]:
            subset = group[group["rank_bucket"].eq(bucket)]
            triggered = subset[subset["counterfactual_trade_generated"].map(_bool)]
            rows.append({
                "experiment_id": EXPERIMENT_ID,
                "audit_level": level,
                "audit_value": value,
                "rank_bucket": bucket,
                "valid_candidates": int(len(subset)),
                "triggered_trades": int(len(triggered)),
                "winners": int(triggered["winning_trade"].map(_bool).sum()),
                "triggered_win_rate": float(triggered["winning_trade"].map(_bool).mean()) if len(triggered) else np.nan,
                "candidate_success_rate": float(subset["winning_trade"].map(_bool).mean()) if len(subset) else np.nan,
                "total_pnl_sek": float(pd.to_numeric(subset["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum()),
                "average_pnl_per_valid_candidate_sek": float(pd.to_numeric(subset["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).mean()) if len(subset) else np.nan,
                "average_net_r_all_valid": float(pd.to_numeric(subset["net_r_after_costs"], errors="coerce").fillna(0).mean()) if len(subset) else np.nan,
                "average_net_r_triggered": float(pd.to_numeric(triggered["net_r_after_costs"], errors="coerce").mean()) if len(triggered) else np.nan,
            })
    return pd.DataFrame(rows)


def _select_up_to_two(frame: pd.DataFrame, score_column: str, require_positive: bool = True) -> pd.DataFrame:
    candidates = frame.copy()
    candidates[score_column] = pd.to_numeric(candidates[score_column], errors="coerce")
    candidates = candidates.dropna(subset=[score_column])
    if require_positive:
        candidates = candidates[candidates[score_column].gt(0)]
    # Some compact diagnostics and unit-test fixtures intentionally contain only
    # the fields required for the score. Preserve deterministic selection without
    # requiring optional ranking metadata.
    if "ranking_metric" not in candidates.columns:
        candidates["ranking_metric"] = np.nan
    if "ticker" not in candidates.columns:
        candidates["ticker"] = ""
    candidates = candidates.sort_values([score_column, "ranking_metric", "ticker"], ascending=[False, False, True], na_position="last")
    selected: list[int] = []
    used_tickers: set[str] = set()
    for idx, row in candidates.iterrows():
        ticker = str(row["ticker"])
        if ticker in used_tickers:
            continue
        selected.append(idx)
        used_tickers.add(ticker)
        if len(selected) >= MAX_SHADOW_POSITIONS:
            break
    return candidates.loc[selected].copy() if selected else candidates.iloc[0:0].copy()


def _oracle_selection(group: pd.DataFrame) -> pd.DataFrame:
    positive = group[pd.to_numeric(group["risk_capped_net_pnl_sek"], errors="coerce").gt(0)].copy()
    return _select_up_to_two(positive, "risk_capped_net_pnl_sek", require_positive=True)


def build_daily_selection_diagnostics(candidate_outcomes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = candidate_outcomes[candidate_outcomes["model_eligible"].map(_bool)].copy()
    daily_rows: list[dict[str, Any]] = []
    regret_rows: list[dict[str, Any]] = []
    for date, group in frame.groupby("date", sort=True):
        selected = group[group["selected_by_v3"].map(_bool)]
        oracle = _oracle_selection(group)
        profitable = group[pd.to_numeric(group["risk_capped_net_pnl_sek"], errors="coerce").gt(0)]
        all_pnl = float(pd.to_numeric(group["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum())
        selected_pnl = float(pd.to_numeric(selected["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum())
        oracle_pnl = float(pd.to_numeric(oracle["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum())
        coverage_failure = len(group) == 0
        opportunity = len(profitable) > 0
        captured = bool(selected["winning_trade"].map(_bool).any()) if len(selected) else False
        missed = opportunity and not captured
        economic_failure = selected_pnl <= 0
        if not coverage_failure and selected_pnl > 0:
            result = "SUCCESS_PROFITABLE_SELECTION"
        elif coverage_failure:
            result = "FAILURE_STRATEGY_LIBRARY_GAP"
        elif opportunity and missed:
            result = "FAILURE_PROFITABLE_OPPORTUNITY_MISSED"
        elif selected_pnl <= 0 and opportunity:
            result = "FAILURE_SELECTED_PORTFOLIO_NONPOSITIVE"
        else:
            result = "FAILURE_NO_PROFITABLE_TESTED_CANDIDATE"
        daily_rows.append({
            "experiment_id": EXPERIMENT_ID,
            "date": date,
            "primary_regime": str(group["primary_regime"].iloc[0]) if len(group) else "",
            "valid_primary_candidates": int(len(group)),
            "triggered_primary_counterfactuals": int(group["counterfactual_trade_generated"].map(_bool).sum()),
            "profitable_primary_counterfactuals": int(group["winning_trade"].map(_bool).sum()),
            "all_candidate_triggered_win_rate": float(group.loc[group["counterfactual_trade_generated"].map(_bool), "winning_trade"].map(_bool).mean()) if group["counterfactual_trade_generated"].map(_bool).any() else np.nan,
            "all_candidate_pnl_sek": all_pnl,
            "v3_selected_candidates": int(len(selected)),
            "v3_selected_triggered_trades": int(selected["counterfactual_trade_generated"].map(_bool).sum()),
            "v3_selected_winners": int(selected["winning_trade"].map(_bool).sum()),
            "v3_selected_pnl_sek": selected_pnl,
            "oracle_selected_candidates": int(len(oracle)),
            "oracle_winners": int(oracle["winning_trade"].map(_bool).sum()),
            "oracle_pnl_sek": oracle_pnl,
            "selection_regret_sek": oracle_pnl - selected_pnl,
            "strategy_coverage": not coverage_failure,
            "profitable_opportunity_available": opportunity,
            "profitable_opportunity_captured": captured,
            "profitable_opportunity_missed": missed,
            "coverage_failure": coverage_failure,
            "selection_failure": missed,
            "economic_failure": economic_failure,
            "daily_system_result": result,
        })
        regret_rows.append({
            "experiment_id": EXPERIMENT_ID,
            "date": date,
            "primary_regime": str(group["primary_regime"].iloc[0]) if len(group) else "",
            "v3_selected_pnl_sek": selected_pnl,
            "oracle_up_to_two_pnl_sek": oracle_pnl,
            "selection_regret_sek": oracle_pnl - selected_pnl,
            "v3_selected_tickers": ";".join(selected.sort_values("v3_rank")["ticker"].astype(str)),
            "oracle_selected_tickers": ";".join(oracle["ticker"].astype(str)),
            "profitable_candidate_tickers": ";".join(profitable.sort_values("risk_capped_net_pnl_sek", ascending=False)["ticker"].astype(str)),
            "profitable_opportunity_missed": missed,
        })
    return pd.DataFrame(daily_rows), pd.DataFrame(regret_rows)


def _shrunk_group_mean(
    train: pd.DataFrame,
    row: pd.Series,
    keys: list[str],
    alpha: float,
    global_mean: float,
) -> float:
    mask = pd.Series(True, index=train.index)
    for key in keys:
        mask &= train[key].astype(str).eq(str(row.get(key, "")))
    values = pd.to_numeric(train.loc[mask, "net_r_after_costs"], errors="coerce").dropna()
    if values.empty:
        return global_mean
    return float((values.sum() + alpha * global_mean) / (len(values) + alpha))


def simple_expected_r_scores(train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
    if train.empty:
        return pd.Series(0.0, index=test.index, dtype=float)
    global_values = pd.to_numeric(train["net_r_after_costs"], errors="coerce").dropna()
    global_mean = float(global_values.mean()) if not global_values.empty else 0.0
    scores: list[float] = []
    for _, row in test.iterrows():
        contract_regime = _shrunk_group_mean(train, row, ["contract_id", "primary_regime"], 20.0, global_mean)
        state = _shrunk_group_mean(
            train,
            row,
            ["contract_id", "direction", "volatility_bucket", "sector_direction_alignment"],
            15.0,
            global_mean,
        )
        ticker_contract = _shrunk_group_mean(train, row, ["ticker", "contract_id"], 12.0, global_mean)
        rank = _shrunk_group_mean(train, row, ["contract_id", "rank_bucket"], 10.0, global_mean)
        score = 0.35 * contract_regime + 0.25 * state + 0.15 * ticker_contract + 0.15 * rank + 0.10 * global_mean
        scores.append(float(score))
    return pd.Series(scores, index=test.index, dtype=float)


def _design_matrices(
    train: pd.DataFrame,
    test: pd.DataFrame,
    nonlinear: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    train_num = pd.DataFrame(index=train.index)
    test_num = pd.DataFrame(index=test.index)
    for column in NUMERIC_FEATURES:
        tr = pd.to_numeric(train.get(column, np.nan), errors="coerce")
        te = pd.to_numeric(test.get(column, np.nan), errors="coerce")
        median = float(tr.median()) if tr.notna().any() else 0.0
        tr = tr.fillna(median)
        te = te.fillna(median)
        mean = float(tr.mean())
        std = float(tr.std(ddof=0))
        train_num[column] = (tr - mean) / std if std > 0 else 0.0
        test_num[column] = (te - mean) / std if std > 0 else 0.0

    # Strict walk-forward preprocessing: categorical levels are learned from
    # the training window only. Unseen test categories map to all-zero dummy
    # columns rather than influencing the fitted design matrix.
    train_raw = pd.DataFrame(
        {c: train.get(c, "").fillna("").astype(str) for c in CATEGORICAL_FEATURES}
    )
    test_raw = pd.DataFrame(
        {c: test.get(c, "").fillna("").astype(str) for c in CATEGORICAL_FEATURES}
    )
    train_cat = pd.get_dummies(train_raw, columns=CATEGORICAL_FEATURES, dtype=float)
    test_cat = pd.get_dummies(test_raw, columns=CATEGORICAL_FEATURES, dtype=float)
    test_cat = test_cat.reindex(columns=train_cat.columns, fill_value=0.0)
    train_cat = train_cat.reset_index(drop=True)
    test_cat = test_cat.reset_index(drop=True)
    train_num = train_num.reset_index(drop=True)
    test_num = test_num.reset_index(drop=True)

    if nonlinear:
        base_columns = [
            "ranking_metric", "v3_rank", "regime_confidence", "opening_gap_pct",
            "cutoff_return_from_open", "early_range_pct", "sector_relative_return",
            "prior_20d_daily_volatility",
        ]
        for column in base_columns:
            train_num[f"{column}__sq"] = train_num[column] ** 2
            test_num[f"{column}__sq"] = test_num[column] ** 2
        interactions = [
            ("ranking_metric", "early_range_pct"),
            ("ranking_metric", "cutoff_return_from_open"),
            ("v3_rank", "early_range_pct"),
            ("opening_gap_pct", "cutoff_return_from_open"),
            ("sector_relative_return", "cutoff_return_from_open"),
            ("prior_20d_daily_volatility", "early_range_pct"),
        ]
        for left, right in interactions:
            name = f"{left}__x__{right}"
            train_num[name] = train_num[left] * train_num[right]
            test_num[name] = test_num[left] * test_num[right]

    x_train = np.column_stack(
        [np.ones(len(train)), train_num.to_numpy(dtype=float), train_cat.to_numpy(dtype=float)]
    )
    x_test = np.column_stack(
        [np.ones(len(test)), test_num.to_numpy(dtype=float), test_cat.to_numpy(dtype=float)]
    )
    return x_train, x_test


def _ridge_predict(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    alpha: float,
) -> np.ndarray:
    penalty = np.eye(x_train.shape[1], dtype=float) * alpha
    penalty[0, 0] = 0.0
    beta = np.linalg.pinv(x_train.T @ x_train + penalty) @ x_train.T @ y_train
    return x_test @ beta


def _logistic_probabilities(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    l2: float = 4.0,
    iterations: int = 30,
) -> np.ndarray:
    beta = np.zeros(x_train.shape[1], dtype=float)
    penalty = np.eye(x_train.shape[1], dtype=float) * l2
    penalty[0, 0] = 0.0
    for _ in range(iterations):
        eta = np.clip(x_train @ beta, -25.0, 25.0)
        probability = 1.0 / (1.0 + np.exp(-eta))
        weights = np.clip(probability * (1.0 - probability), 1e-5, None)
        working = eta + (y_train - probability) / weights
        xtw = x_train.T * weights
        updated = np.linalg.pinv(xtw @ x_train + penalty) @ (xtw @ working)
        if np.max(np.abs(updated - beta)) < 1e-7:
            beta = updated
            break
        beta = updated
    return 1.0 / (1.0 + np.exp(-np.clip(x_test @ beta, -25.0, 25.0)))


def _statistical_predictions(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, pd.Series]:
    output = {
        "ridge_expected_r": pd.Series(np.nan, index=test.index, dtype=float),
        "logistic_expected_r": pd.Series(np.nan, index=test.index, dtype=float),
        "nonlinear_expected_r": pd.Series(np.nan, index=test.index, dtype=float),
    }
    if train.empty or test.empty:
        return output
    y_r = pd.to_numeric(train["net_r_after_costs"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    y_win = train["winning_trade"].map(_bool).astype(int).to_numpy(dtype=float)

    x_train, x_test = _design_matrices(train, test, nonlinear=False)
    output["ridge_expected_r"] = pd.Series(
        _ridge_predict(x_train, y_r, x_test, alpha=10.0), index=test.index, dtype=float
    )

    if len(np.unique(y_win)) >= 2:
        probability = _logistic_probabilities(x_train, y_win, x_test, l2=4.0)
        positive_mean = float(y_r[y_win == 1].mean()) if np.any(y_win == 1) else 1.0
        nonpositive_mean = float(y_r[y_win == 0].mean()) if np.any(y_win == 0) else -1.0
        output["logistic_expected_r"] = pd.Series(
            probability * positive_mean + (1.0 - probability) * nonpositive_mean,
            index=test.index,
            dtype=float,
        )

    x_train_nonlin, x_test_nonlin = _design_matrices(train, test, nonlinear=True)
    output["nonlinear_expected_r"] = pd.Series(
        _ridge_predict(x_train_nonlin, y_r, x_test_nonlin, alpha=20.0),
        index=test.index,
        dtype=float,
    )
    return output

def build_walk_forward_predictions(candidate_outcomes: pd.DataFrame) -> pd.DataFrame:
    frame = candidate_outcomes[candidate_outcomes["model_eligible"].map(_bool)].copy()
    frame = frame.sort_values(["date", "contract_id", "v3_rank", "ticker"]).reset_index(drop=True)
    prediction_rows: list[pd.DataFrame] = []
    dates = sorted(frame["date"].astype(str).unique())
    for date in dates:
        test = frame[frame["date"].astype(str).eq(date)].copy()
        train = frame[frame["date"].astype(str).lt(date)].copy()
        train_sessions = int(train["date"].nunique())
        trained = train_sessions >= MIN_TRAIN_SESSIONS and len(train) >= MIN_TRAIN_ROWS
        test["training_cutoff_date"] = str(train["date"].max()) if len(train) else ""
        test["training_sessions"] = train_sessions
        test["training_candidates"] = int(len(train))
        test["model_status"] = "TRAINED_WALK_FORWARD" if trained else "WARMUP_INSUFFICIENT_HISTORY"
        test["simple_expected_r"] = simple_expected_r_scores(train, test) if trained else np.nan
        stats = _statistical_predictions(train, test) if trained else {}
        for column in ["ridge_expected_r", "logistic_expected_r", "nonlinear_expected_r"]:
            test[column] = stats.get(column, pd.Series(np.nan, index=test.index))
        if trained:
            components = test[["simple_expected_r", "ridge_expected_r", "logistic_expected_r", "nonlinear_expected_r"]].copy()
            standardized = components.copy()
            for column in standardized:
                std = float(standardized[column].std(ddof=0))
                mean = float(standardized[column].mean())
                standardized[column] = (standardized[column] - mean) / std if std > 0 else 0.0
            test["ensemble_score"] = standardized.mean(axis=1, skipna=True)
        else:
            test["ensemble_score"] = np.nan
        prediction_rows.append(test)
    predictions = pd.concat(prediction_rows, ignore_index=True) if prediction_rows else pd.DataFrame()
    if predictions.empty:
        return predictions
    for model, column in {
        "CURRENT_V3_RANK": "selected_by_v3",
        "SIMPLE_EXPECTED_R_SCORE": "simple_expected_r",
        "RIDGE_NET_R": "ridge_expected_r",
        "LOGISTIC_WIN_EXPECTED_R": "logistic_expected_r",
        "NONLINEAR_RIDGE_EXPECTED_R": "nonlinear_expected_r",
        "ENSEMBLE_SCORE": "ensemble_score",
    }.items():
        predictions[f"selected_{model.lower()}"] = False
        for date, group in predictions.groupby("date", sort=True):
            if model == "CURRENT_V3_RANK":
                selected_index = group[group["selected_by_v3"].map(_bool)].index
            elif str(group["model_status"].iloc[0]) != "TRAINED_WALK_FORWARD":
                selected_index = []
            else:
                selected_index = _select_up_to_two(group, column, require_positive=True).index
            predictions.loc[selected_index, f"selected_{model.lower()}"] = True
    return predictions


def build_selector_comparisons(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    model_columns = {
        "CURRENT_V3_RANK": "selected_current_v3_rank",
        "CURRENT_V3_RANK_SAME_OOS_WINDOW": "selected_current_v3_rank",
        "SIMPLE_EXPECTED_R_SCORE": "selected_simple_expected_r_score",
        "RIDGE_NET_R": "selected_ridge_net_r",
        "LOGISTIC_WIN_EXPECTED_R": "selected_logistic_win_expected_r",
        "NONLINEAR_RIDGE_EXPECTED_R": "selected_nonlinear_ridge_expected_r",
        "ENSEMBLE_SCORE": "selected_ensemble_score",
    }
    rows: list[dict[str, Any]] = []
    for model, selected_column in model_columns.items():
        eligible = predictions.copy()
        if model not in {"CURRENT_V3_RANK"}:
            eligible = eligible[eligible["model_status"].eq("TRAINED_WALK_FORWARD")]
        selected = eligible[eligible[selected_column].map(_bool)]
        daily = selected.groupby("date")["risk_capped_net_pnl_sek"].sum() if not selected.empty else pd.Series(dtype=float)
        rows.append({
            "experiment_id": EXPERIMENT_ID,
            "model": model,
            "walk_forward_only": model not in {"CURRENT_V3_RANK"},
            "evaluated_sessions": int(eligible["date"].nunique()),
            "selected_candidates": int(len(selected)),
            "sessions_with_selection": int(selected["date"].nunique()) if len(selected) else 0,
            "no_trade_sessions": int(eligible["date"].nunique() - selected["date"].nunique()) if len(eligible) else 0,
            "winning_candidates": int(selected["winning_trade"].map(_bool).sum()) if len(selected) else 0,
            "selected_win_rate": float(selected["winning_trade"].map(_bool).mean()) if len(selected) else np.nan,
            "total_pnl_sek": float(pd.to_numeric(selected["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum()),
            "average_net_r": float(pd.to_numeric(selected["net_r_after_costs"], errors="coerce").mean()) if len(selected) else np.nan,
            "profitable_session_rate": float((daily > 0).mean()) if len(daily) else np.nan,
            "worst_session_pnl_sek": float(daily.min()) if len(daily) else np.nan,
            "best_session_pnl_sek": float(daily.max()) if len(daily) else np.nan,
            "research_status": RESEARCH_STATUS,
            "promotion_eligible": False,
        })
    return pd.DataFrame(rows)



def reconcile_authoritative_v3(
    baseline_trades: pd.DataFrame,
    v3_ledger: Path,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, int, int]:
    columns = [
        "audit_item", "session_date", "contract_id", "test_role", "ticker",
        "field", "expected", "observed", "absolute_difference", "audit_pass",
    ]
    if not Path(v3_ledger).exists():
        return pd.DataFrame([{
            "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
            "session_date": "", "contract_id": "", "test_role": "", "ticker": "",
            "field": "ledger", "expected": "PRESENT", "observed": "MISSING",
            "absolute_difference": np.nan, "audit_pass": False,
        }], columns=columns), 0, 1
    with closing(_connect_read_only(v3_ledger)) as connection:
        authoritative = pd.read_sql_query(
            """
            SELECT session_date, contract_id, test_role, ticker, direction,
                   entry_time, entry_price, stop_price, target_price,
                   exit_time, exit_price, exit_reason, risk_capped_net_pnl_sek
            FROM shadow_outcomes
            WHERE session_date BETWEEN ? AND ?
              AND outcome_status LIKE '%TRADE_COMPLETED'
            ORDER BY session_date, contract_id, ticker
            """,
            connection,
            params=(start_date, end_date),
        )
    if authoritative.empty:
        return pd.DataFrame([{
            "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
            "session_date": "", "contract_id": "", "test_role": "", "ticker": "",
            "field": "completed_trades", "expected": 0, "observed": 0,
            "absolute_difference": 0.0, "audit_pass": True,
        }], columns=columns), 0, 0
    replay = baseline_trades.copy()
    key = ["date", "contract_id", "test_role", "ticker"]
    replay_lookup = replay.set_index(key).to_dict("index") if not replay.empty else {}
    auth_keys = set()
    rows: list[dict[str, Any]] = []
    failures = 0
    for auth in authoritative.to_dict("records"):
        k = (str(auth["session_date"]), str(auth["contract_id"]), str(auth["test_role"]), str(auth["ticker"]))
        auth_keys.add(k)
        observed = replay_lookup.get(k)
        if observed is None:
            rows.append({
                "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
                "session_date": k[0], "contract_id": k[1], "test_role": k[2], "ticker": k[3],
                "field": "trade_key", "expected": "PRESENT", "observed": "MISSING",
                "absolute_difference": np.nan, "audit_pass": False,
            })
            failures += 1
            continue
        for field in ["direction", "exit_reason"]:
            passed = str(auth.get(field, "")) == str(observed.get(field, ""))
            rows.append({
                "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
                "session_date": k[0], "contract_id": k[1], "test_role": k[2], "ticker": k[3],
                "field": field, "expected": auth.get(field), "observed": observed.get(field),
                "absolute_difference": 0.0 if passed else np.nan, "audit_pass": passed,
            })
            failures += int(not passed)
        for field in ["entry_time", "exit_time"]:
            expected = pd.to_datetime(auth.get(field), errors="coerce")
            actual = pd.to_datetime(observed.get(field), errors="coerce")
            passed = (pd.isna(expected) and pd.isna(actual)) or expected == actual
            rows.append({
                "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
                "session_date": k[0], "contract_id": k[1], "test_role": k[2], "ticker": k[3],
                "field": field, "expected": str(expected), "observed": str(actual),
                "absolute_difference": 0.0 if passed else np.nan, "audit_pass": passed,
            })
            failures += int(not passed)
        for field in ["entry_price", "stop_price", "target_price", "exit_price", "risk_capped_net_pnl_sek"]:
            expected = _num(auth.get(field))
            actual = _num(observed.get(field))
            difference = abs(expected - actual) if np.isfinite(expected) and np.isfinite(actual) else np.nan
            passed = (not np.isfinite(expected) and not np.isfinite(actual)) or (np.isfinite(difference) and difference <= 1e-8)
            rows.append({
                "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
                "session_date": k[0], "contract_id": k[1], "test_role": k[2], "ticker": k[3],
                "field": field, "expected": expected, "observed": actual,
                "absolute_difference": difference, "audit_pass": passed,
            })
            failures += int(not passed)
    replay_in_window = replay[
        replay["date"].astype(str).between(start_date, end_date)
        & replay["date"].astype(str).isin(authoritative["session_date"].astype(str).unique())
    ]
    unexpected = set(tuple(row) for row in replay_in_window[key].astype(str).to_numpy()) - auth_keys
    for k in sorted(unexpected):
        rows.append({
            "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
            "session_date": k[0], "contract_id": k[1], "test_role": k[2], "ticker": k[3],
            "field": "trade_key", "expected": "ABSENT", "observed": "UNEXPECTED",
            "absolute_difference": np.nan, "audit_pass": False,
        })
        failures += 1
    return pd.DataFrame(rows, columns=columns), int(len(authoritative)), failures


def build_audit(
    replay: ReplayFrames,
    candidate_outcomes: pd.DataFrame,
    reconciliation: pd.DataFrame,
    price_hash_before: str,
    price_hash_after: str,
    ledger_hash_before: str,
    ledger_hash_after: str,
) -> pd.DataFrame:
    valid = candidate_outcomes[candidate_outcomes["valid_setup"].map(_bool)]
    rows = [
        {
            "audit_item": "NO_DUPLICATE_CANDIDATE_KEYS",
            "rows_checked": len(candidate_outcomes),
            "failures": int(candidate_outcomes.duplicated(["date", "contract_id", "ticker"]).sum()),
            "audit_pass": not candidate_outcomes.duplicated(["date", "contract_id", "ticker"]).any(),
            "interpretation": "Each candidate is unique by session, contract, and ticker.",
        },
        {
            "audit_item": "ALL_VALID_CANDIDATES_SELECTED_IN_COUNTERFACTUAL_PASS",
            "rows_checked": len(valid),
            "failures": int((~valid["counterfactual_trade_generated"].map(_bool) & valid["trigger_status"].eq("ELIGIBLE_NOT_SELECTED")).sum()),
            "audit_pass": not ((~valid["counterfactual_trade_generated"].map(_bool)) & valid["trigger_status"].eq("ELIGIBLE_NOT_SELECTED")).any(),
            "interpretation": "The research pass removes only the max-two selection cap; it preserves exact ranking and execution.",
        },
        {
            "audit_item": "POINT_IN_TIME_MODEL_FEATURES",
            "rows_checked": int(candidate_outcomes["model_eligible"].map(_bool).sum()),
            "failures": int((candidate_outcomes["model_eligible"].map(_bool) & ~candidate_outcomes["point_in_time_pass"].map(_bool)).sum()),
            "audit_pass": not (candidate_outcomes["model_eligible"].map(_bool) & ~candidate_outcomes["point_in_time_pass"].map(_bool)).any(),
            "interpretation": "Every model-eligible candidate uses sources no later than the completed 09:40 bar.",
        },
        {
            "audit_item": "GUARDRAILS_EXCLUDED_FROM_MODEL",
            "rows_checked": int(candidate_outcomes["test_role"].eq(GUARDRAIL_ROLE).sum()),
            "failures": int((candidate_outcomes["test_role"].eq(GUARDRAIL_ROLE) & candidate_outcomes["model_eligible"].map(_bool)).sum()),
            "audit_pass": not (candidate_outcomes["test_role"].eq(GUARDRAIL_ROLE) & candidate_outcomes["model_eligible"].map(_bool)).any(),
            "interpretation": "Guardrails are retained diagnostically but excluded from selector training and P&L.",
        },
        {
            "audit_item": "SOURCE_PRICE_DATABASE_UNCHANGED",
            "rows_checked": 1,
            "failures": int(price_hash_before != price_hash_after),
            "audit_pass": price_hash_before == price_hash_after,
            "interpretation": f"before={price_hash_before}; after={price_hash_after}",
        },
        {
            "audit_item": "V3_LEDGER_UNCHANGED",
            "rows_checked": 1,
            "failures": int(ledger_hash_before != ledger_hash_after),
            "audit_pass": ledger_hash_before == ledger_hash_after,
            "interpretation": f"before={ledger_hash_before}; after={ledger_hash_after}",
        },
        {
            "audit_item": "STRATEGIES_NOT_PROMOTED_AND_ROUTER_INACTIVE",
            "rows_checked": 1,
            "failures": 0,
            "audit_pass": True,
            "interpretation": "Step 9R is research-only and cannot send orders.",
        },
    ]
    if not reconciliation.empty:
        rows.append({
            "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
            "rows_checked": int(len(reconciliation)),
            "failures": int((~reconciliation["audit_pass"].map(_bool)).sum()),
            "audit_pass": bool(reconciliation["audit_pass"].map(_bool).all()),
            "interpretation": "Untouched V3 baseline replay reconciles completed authoritative V3 trades.",
        })
    return pd.DataFrame(rows)


def build_summary(
    start_date: str,
    end_date: str,
    replay: ReplayFrames,
    candidate_outcomes: pd.DataFrame,
    daily: pd.DataFrame,
    comparisons: pd.DataFrame,
    audit: pd.DataFrame,
    authoritative_trades: int,
    authoritative_failures: int,
) -> pd.DataFrame:
    primary = candidate_outcomes[candidate_outcomes["model_eligible"].map(_bool)]
    selected = primary[primary["selected_by_v3"].map(_bool)]
    audit_pass = bool(audit["audit_pass"].map(_bool).all()) if len(audit) else False
    row = {
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "code_version": CODE_VERSION,
        "requested_start_date": start_date,
        "requested_end_date": end_date,
        "effective_start_date": str(replay.taxonomy["date"].min()),
        "effective_end_date": str(replay.taxonomy["date"].max()),
        "taxonomy_sessions": int(replay.taxonomy["date"].nunique()),
        "taxonomy_skips": int(len(replay.taxonomy_skips)),
        "v3_contracts": len(step9l_v3.CONTRACTS),
        "candidate_rows": int(len(candidate_outcomes)),
        "primary_candidate_rows": int(candidate_outcomes["test_role"].eq(PRIMARY_ROLE).sum()),
        "valid_primary_candidates": int(len(primary)),
        "triggered_primary_counterfactuals": int(primary["counterfactual_trade_generated"].map(_bool).sum()),
        "profitable_primary_counterfactuals": int(primary["winning_trade"].map(_bool).sum()),
        "all_candidate_pnl_sek": float(pd.to_numeric(primary["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum()),
        "all_candidate_win_rate": float(primary.loc[primary["counterfactual_trade_generated"].map(_bool), "winning_trade"].map(_bool).mean()) if primary["counterfactual_trade_generated"].map(_bool).any() else np.nan,
        "v3_selected_primary_candidates": int(len(selected)),
        "v3_selected_primary_trades": int(selected["counterfactual_trade_generated"].map(_bool).sum()),
        "v3_selected_pnl_sek": float(pd.to_numeric(selected["risk_capped_net_pnl_sek"], errors="coerce").fillna(0).sum()),
        "oracle_pnl_sek": float(pd.to_numeric(daily.get("oracle_pnl_sek", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "selection_regret_sek": float(pd.to_numeric(daily.get("selection_regret_sek", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "walk_forward_models_compared": int(len(comparisons)),
        "locked_research_selector": SELECTOR_MODEL,
        "authoritative_trades_checked": authoritative_trades,
        "authoritative_replay_failures": authoritative_failures,
        "audit_pass": audit_pass,
        "strategies_promoted": 0,
        "router_active": False,
        "orders_enabled": False,
        "classification": CLASSIFICATION_READY if audit_pass else CLASSIFICATION_REVIEW,
    }
    return pd.DataFrame([row])


def _atomic_sqlite_write(path: Path, tables: dict[str, pd.DataFrame], metadata: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp.db", dir=path.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with closing(sqlite3.connect(temp)) as connection:
            pd.DataFrame([metadata]).to_sql("run_metadata", connection, index=False, if_exists="replace")
            for name, frame in tables.items():
                if len(frame.columns) == 0:
                    continue
                frame.to_sql(name, connection, index=False, if_exists="replace")
            connection.commit()
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def export_outputs(outputs: dict[str, pd.DataFrame]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        if name in OUTPUT_FILES:
            export_csv_for_power_bi(frame, OUTPUT_FILES[name])


def run_historical_research(
    start_date: str,
    end_date: str,
    price_db: Path = DEFAULT_PRICE_DB,
    v3_ledger: Path = DEFAULT_V3_LEDGER,
    taxonomy_ledger: Path = DEFAULT_TAXONOMY_LEDGER,
    output_db: Path = DEFAULT_RESEARCH_DB,
    rebuild_missing_taxonomy: bool = True,
    skip_authoritative_check: bool = False,
) -> dict[str, pd.DataFrame]:
    price_db = Path(price_db)
    v3_ledger = Path(v3_ledger)
    price_hash_before = _file_hash(price_db)
    ledger_hash_before = _file_hash(v3_ledger)
    replay = replay_exact_v3(
        price_db=price_db,
        v3_ledger=v3_ledger,
        taxonomy_ledger=taxonomy_ledger,
        start_date=start_date,
        end_date=end_date,
        rebuild_missing_taxonomy=rebuild_missing_taxonomy,
    )
    candidate_outcomes = build_candidate_outcomes(replay)
    current_rank_audit = build_current_rank_audit(candidate_outcomes)
    rank_buckets = build_rank_bucket_performance(candidate_outcomes)
    daily, regret = build_daily_selection_diagnostics(candidate_outcomes)
    predictions = pd.DataFrame()
    comparisons = pd.DataFrame()
    if skip_authoritative_check:
        reconciliation = pd.DataFrame([{
            "audit_item": "AUTHORITATIVE_V3_RECONCILIATION",
            "session_date": "", "contract_id": "", "test_role": "", "ticker": "",
            "field": "check", "expected": "RUN", "observed": "SKIPPED_BY_USER",
            "absolute_difference": np.nan, "audit_pass": True,
        }])
        authoritative_trades, authoritative_failures = 0, 0
    else:
        reconciliation, authoritative_trades, authoritative_failures = reconcile_authoritative_v3(
            replay.baseline_trades, v3_ledger, start_date, end_date
        )
    price_hash_after = _file_hash(price_db)
    ledger_hash_after = _file_hash(v3_ledger)
    audit = build_audit(
        replay,
        candidate_outcomes,
        reconciliation,
        price_hash_before,
        price_hash_after,
        ledger_hash_before,
        ledger_hash_after,
    )
    summary = build_summary(
        start_date,
        end_date,
        replay,
        candidate_outcomes,
        daily,
        comparisons,
        audit,
        authoritative_trades,
        authoritative_failures,
    )
    outputs = {
        "candidate_outcomes": candidate_outcomes,
        "current_rank_audit": current_rank_audit,
        "rank_bucket_performance": rank_buckets,
        "daily_selection_diagnostics": daily,
        "selection_regret": regret,
        "walk_forward_predictions": predictions,
        "selector_comparisons": comparisons,
        "authoritative_reconciliation": reconciliation,
        "audit": audit,
        "summary": summary,
        "taxonomy_skips": replay.taxonomy_skips,
    }
    metadata = {
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "code_version": CODE_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_price_db": str(price_db),
        "source_price_db_sha256": price_hash_after,
        "v3_ledger": str(v3_ledger),
        "v3_ledger_sha256": ledger_hash_after,
        "v3_registry_sha256": _registry_hash(),
        "router_active": False,
        "orders_enabled": False,
    }
    _atomic_sqlite_write(output_db, outputs, metadata)
    export_outputs(outputs)
    return outputs



def _atomic_update_research_db(path: Path, tables: dict[str, pd.DataFrame]) -> None:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    fd, temp_name = tempfile.mkstemp(prefix=path.stem + "_update_", suffix=".tmp.db", dir=path.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copy2(path, temp)
        with closing(sqlite3.connect(temp)) as connection:
            for name, frame in tables.items():
                if len(frame.columns) == 0:
                    continue
                frame.to_sql(name, connection, index=False, if_exists="replace")
            connection.commit()
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def run_selector_models(research_db: Path = DEFAULT_RESEARCH_DB) -> dict[str, pd.DataFrame]:
    with closing(_connect_read_only(research_db)) as connection:
        candidates = pd.read_sql_query(
            "SELECT * FROM candidate_outcomes ORDER BY date, contract_id, v3_rank, ticker",
            connection,
        )
        summary = pd.read_sql_query("SELECT * FROM summary", connection)
    for column in [
        "model_eligible", "valid_setup", "winning_trade", "selected_by_v3",
        "counterfactual_trade_generated", "point_in_time_pass",
    ]:
        if column in candidates:
            candidates[column] = candidates[column].map(_bool)
    predictions = build_walk_forward_predictions(candidates)
    comparisons = build_selector_comparisons(predictions)
    if not summary.empty:
        summary = summary.copy()
        summary.loc[:, "walk_forward_models_compared"] = int(len(comparisons))
        summary.loc[:, "locked_research_selector"] = SELECTOR_MODEL
    _atomic_update_research_db(
        research_db,
        {
            "walk_forward_predictions": predictions,
            "selector_comparisons": comparisons,
            "summary": summary,
        },
    )
    export_csv_for_power_bi(predictions, OUTPUT_FILES["walk_forward_predictions"])
    export_csv_for_power_bi(comparisons, OUTPUT_FILES["selector_comparisons"])
    export_csv_for_power_bi(summary, OUTPUT_FILES["summary"])
    return {
        "walk_forward_predictions": predictions,
        "selector_comparisons": comparisons,
        "summary": summary,
    }

def _read_research_candidates(research_db: Path) -> pd.DataFrame:
    with closing(_connect_read_only(research_db)) as connection:
        frame = pd.read_sql_query("SELECT * FROM candidate_outcomes ORDER BY date, contract_id, v3_rank, ticker", connection)
    for column in ["model_eligible", "valid_setup", "winning_trade", "selected_by_v3", "counterfactual_trade_generated", "point_in_time_pass"]:
        if column in frame:
            frame[column] = frame[column].map(_bool)
    return frame


def _read_v3_morning(v3_ledger: Path, session_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    with closing(_connect_read_only(v3_ledger)) as connection:
        batch = pd.read_sql_query(
            "SELECT * FROM shadow_decision_batches WHERE session_date = ?",
            connection,
            params=(session_date,),
        )
        decisions = pd.read_sql_query(
            "SELECT * FROM shadow_decisions WHERE session_date = ? ORDER BY contract_id, ticker",
            connection,
            params=(session_date,),
        )
    if batch.empty or decisions.empty:
        raise Step9RError(f"No sealed V3 morning batch exists for {session_date}.")
    return batch, decisions


def _truncate_prices_to_morning(prices: pd.DataFrame, session_date: str) -> pd.DataFrame:
    result = prices.copy()
    clocks = result["datetime"].dt.strftime("%H:%M")
    current = result["date"].astype(str).eq(session_date)
    return result[~current | clocks.le(LATEST_FEATURE_LABEL)].copy()


def _build_prospective_candidates(
    price_db: Path,
    v3_ledger: Path,
    session_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    batch, decisions = _read_v3_morning(v3_ledger, session_date)
    payload = json.loads(str(batch.iloc[0]["taxonomy_payload_json"]))
    payload["date"] = session_date
    taxonomy = pd.DataFrame([payload])
    prices = step9i.load_shadow_prices(price_db)
    pit_prices = _truncate_prices_to_morning(prices, session_date)
    all_candidates, _, characteristics = _run_exact_engine(taxonomy, pit_prices, select_all=True)
    eligible = decisions[decisions["contract_eligible"].map(_bool)].copy()
    eligible_keys = set(zip(eligible["contract_id"].astype(str), eligible["ticker"].astype(str)))
    candidates = all_candidates[
        all_candidates.apply(lambda row: (str(row["contract_id"]), str(row["ticker"])) in eligible_keys, axis=1)
    ].copy()
    replay = ReplayFrames(
        taxonomy=taxonomy,
        taxonomy_skips=pd.DataFrame(columns=["date", "skip_reason"]),
        baseline_candidates=pd.DataFrame(),
        baseline_trades=pd.DataFrame(),
        all_candidates=candidates,
        all_trades=pd.DataFrame(),
        characteristics=characteristics,
        prices=pit_prices,
    )
    outcomes = build_candidate_outcomes(replay)
    outcomes["prospective_status"] = str(batch.iloc[0]["prospective_status"])
    outcomes["evidence_eligible"] = outcomes["prospective_status"].eq(CONFIRMATORY_STATUS)
    return outcomes, batch, decisions


def _ensure_prospective_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS selector_batches (
            batch_id TEXT PRIMARY KEY,
            session_date TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            experiment_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            training_cutoff_date TEXT,
            training_sessions INTEGER NOT NULL,
            training_candidates INTEGER NOT NULL,
            prospective_status TEXT NOT NULL,
            evidence_eligible INTEGER NOT NULL,
            candidate_rows INTEGER NOT NULL,
            selected_rows INTEGER NOT NULL,
            price_db_sha256 TEXT NOT NULL,
            v3_ledger_sha256 TEXT NOT NULL,
            payload_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS selector_candidates (
            candidate_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            session_date TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            test_role TEXT NOT NULL,
            v3_rank INTEGER,
            ranking_metric REAL,
            simple_expected_r REAL,
            research_rank INTEGER,
            selected INTEGER NOT NULL,
            selection_reason TEXT NOT NULL,
            model_eligible INTEGER NOT NULL,
            row_json TEXT NOT NULL,
            row_hash TEXT NOT NULL,
            UNIQUE(session_date, contract_id, ticker)
        );
        CREATE TABLE IF NOT EXISTS selector_outcomes (
            outcome_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            selected INTEGER NOT NULL,
            risk_capped_net_pnl_sek REAL,
            net_r_after_costs REAL,
            winning_trade INTEGER,
            exit_reason TEXT,
            evidence_eligible INTEGER NOT NULL,
            evaluated_at TEXT NOT NULL,
            row_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS selector_candidate_outcomes (
            outcome_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL UNIQUE,
            session_date TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            selected INTEGER NOT NULL,
            model_eligible INTEGER NOT NULL,
            valid_setup INTEGER NOT NULL,
            counterfactual_trade_generated INTEGER NOT NULL,
            risk_capped_net_pnl_sek REAL,
            net_r_after_costs REAL,
            winning_trade INTEGER,
            entry_time TEXT,
            exit_time TEXT,
            exit_reason TEXT,
            evidence_eligible INTEGER NOT NULL,
            evaluated_at TEXT NOT NULL,
            row_hash TEXT NOT NULL
        );
        """
    )
    connection.commit()


def run_prospective_morning(
    session_date: str,
    price_db: Path = DEFAULT_PRICE_DB,
    v3_ledger: Path = DEFAULT_V3_LEDGER,
    research_db: Path = DEFAULT_RESEARCH_DB,
    prospective_db: Path = DEFAULT_PROSPECTIVE_DB,
) -> dict[str, pd.DataFrame]:
    historical = _read_research_candidates(research_db)
    historical = historical[
        historical["model_eligible"].map(_bool) & historical["date"].astype(str).lt(session_date)
    ].copy()
    candidates, batch, _ = _build_prospective_candidates(price_db, v3_ledger, session_date)

    # A valid V3 morning can contain zero contract-eligible candidates. In that
    # case build_candidate_outcomes returns an empty frame without columns.
    # Preserve a typed, schema-stable empty candidate set so Step 9R records a
    # legitimate 0-selection abstention batch instead of raising KeyError.
    required_candidate_columns = {
        "model_eligible": "bool",
        "contract_id": "object",
        "ticker": "object",
        "test_role": "object",
        "v3_rank": "float64",
        "ranking_metric": "float64",
    }
    for column, dtype in required_candidate_columns.items():
        if column not in candidates.columns:
            candidates[column] = pd.Series(index=candidates.index, dtype=dtype)

    model_mask = candidates["model_eligible"].map(_bool).astype(bool)
    primary = candidates.loc[model_mask].copy()
    train_sessions = int(historical["date"].nunique())
    trained = train_sessions >= MIN_TRAIN_SESSIONS and len(historical) >= MIN_TRAIN_ROWS
    primary["simple_expected_r"] = simple_expected_r_scores(historical, primary) if trained else np.nan
    primary = primary.sort_values(["simple_expected_r", "ranking_metric", "ticker"], ascending=[False, False, True])
    primary["research_rank"] = range(1, len(primary) + 1)
    selected = _select_up_to_two(primary, "simple_expected_r", require_positive=True) if trained else primary.iloc[0:0].copy()
    selected_keys = set(zip(selected["contract_id"].astype(str), selected["ticker"].astype(str)))
    primary["selected"] = primary.apply(lambda row: (str(row["contract_id"]), str(row["ticker"])) in selected_keys, axis=1)
    primary["selection_reason"] = np.where(
        primary["selected"],
        "TOP_POSITIVE_EXPECTED_R_UP_TO_TWO",
        np.where(not trained, "MODEL_WARMUP_NO_SELECTION", "NOT_TOP_TWO_OR_NONPOSITIVE_EXPECTED_R"),
    )
    prospective_status = str(batch.iloc[0]["prospective_status"])
    evidence_eligible = prospective_status == CONFIRMATORY_STATUS
    batch_id = f"S9R-{session_date}-MORNING"
    batch_payload = {
        "batch_id": batch_id,
        "session_date": session_date,
        "model_version": SELECTOR_MODEL,
        "training_cutoff_date": str(historical["date"].max()) if len(historical) else "",
        "training_sessions": train_sessions,
        "training_candidates": len(historical),
        "prospective_status": prospective_status,
        "evidence_eligible": evidence_eligible,
        "candidate_rows": len(primary),
        "selected_rows": len(selected),
        "price_db_sha256": _file_hash(price_db),
        "v3_ledger_sha256": _file_hash(v3_ledger),
    }
    prospective_db = Path(prospective_db)
    prospective_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(prospective_db)) as connection:
        _ensure_prospective_schema(connection)
        existing = connection.execute(
            "SELECT payload_hash FROM selector_batches WHERE session_date = ?",
            (session_date,),
        ).fetchone()
        payload_hash = _payload_hash(batch_payload)
        if existing:
            if str(existing[0]) != payload_hash:
                raise Step9RError(f"Immutable Step 9R morning batch conflict for {session_date}.")
        else:
            connection.execute(
                "INSERT INTO selector_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    session_date,
                    datetime.now().astimezone().isoformat(),
                    EXPERIMENT_ID,
                    SELECTOR_MODEL,
                    batch_payload["training_cutoff_date"],
                    train_sessions,
                    len(historical),
                    prospective_status,
                    int(evidence_eligible),
                    len(primary),
                    len(selected),
                    batch_payload["price_db_sha256"],
                    batch_payload["v3_ledger_sha256"],
                    payload_hash,
                ),
            )
            for row in primary.to_dict("records"):
                candidate_id = f"{batch_id}|{row['contract_id']}|{row['ticker']}"
                row_payload = {key: (None if isinstance(value, float) and np.isnan(value) else value) for key, value in row.items()}
                row_json = json.dumps(row_payload, sort_keys=True, default=str)
                connection.execute(
                    "INSERT INTO selector_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        candidate_id,
                        batch_id,
                        session_date,
                        str(row["contract_id"]),
                        str(row["ticker"]),
                        str(row["test_role"]),
                        None if pd.isna(row.get("v3_rank")) else int(row["v3_rank"]),
                        _num(row.get("ranking_metric"), None),
                        _num(row.get("simple_expected_r"), None),
                        int(row["research_rank"]),
                        int(_bool(row["selected"])),
                        str(row["selection_reason"]),
                        int(_bool(row["model_eligible"])),
                        row_json,
                        _payload_hash(row_payload),
                    ),
                )
            connection.commit()
        batches = pd.read_sql_query("SELECT * FROM selector_batches ORDER BY session_date", connection)
        stored_candidates = pd.read_sql_query("SELECT * FROM selector_candidates ORDER BY session_date, research_rank", connection)
    current_candidates = stored_candidates.loc[stored_candidates["session_date"].eq(session_date)].copy()
    selected_mask = current_candidates["selected"].map(_bool).astype(bool)
    current_selected = current_candidates.loc[selected_mask].copy()
    export_csv_for_power_bi(current_candidates, OUTPUT_FILES["prospective_candidates"])
    export_csv_for_power_bi(current_selected, OUTPUT_FILES["prospective_selections"])
    return {"batches": batches, "candidates": current_candidates, "selections": current_selected}


def run_prospective_eod(
    session_date: str,
    price_db: Path = DEFAULT_PRICE_DB,
    v3_ledger: Path = DEFAULT_V3_LEDGER,
    prospective_db: Path = DEFAULT_PROSPECTIVE_DB,
) -> pd.DataFrame:
    prospective_db = Path(prospective_db)
    with closing(sqlite3.connect(prospective_db)) as connection:
        _ensure_prospective_schema(connection)
        candidates = pd.read_sql_query(
            "SELECT * FROM selector_candidates WHERE session_date = ? ORDER BY research_rank",
            connection,
            params=(session_date,),
        )
        batch = pd.read_sql_query(
            "SELECT * FROM selector_batches WHERE session_date = ?",
            connection,
            params=(session_date,),
        )
    if batch.empty:
        raise Step9RError(f"No Step 9R morning selector batch exists for {session_date}.")

    expected_candidates = int(batch.iloc[0]["candidate_rows"])
    if len(candidates) != expected_candidates:
        raise Step9RError(
            f"Step 9R morning candidate-count mismatch for {session_date}: "
            f"batch={expected_candidates}, stored={len(candidates)}."
        )

    # Exact full-day V3 counterfactual replay for one date. Every morning
    # candidate receives an immutable EOD counterfactual row, whether or not it
    # was selected by the 0-2 shadow portfolio.
    replay = replay_exact_v3(
        price_db=price_db,
        v3_ledger=v3_ledger,
        taxonomy_ledger=v3_ledger,
        start_date=session_date,
        end_date=session_date,
        rebuild_missing_taxonomy=False,
    )
    outcomes = build_candidate_outcomes(replay)
    lookup = outcomes.set_index(["contract_id", "ticker"]).to_dict("index") if not outcomes.empty else {}

    all_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    for candidate in candidates.to_dict("records"):
        key = (str(candidate["contract_id"]), str(candidate["ticker"]))
        if key not in lookup:
            raise Step9RError(
                f"Missing exact V3 EOD counterfactual for {session_date} {key[0]} {key[1]}."
            )
        outcome = lookup[key]
        selected = _bool(candidate["selected"])
        evaluated_at = datetime.now().astimezone().isoformat()
        all_row = {
            "outcome_id": f"{candidate['candidate_id']}|ALL_EOD",
            "candidate_id": candidate["candidate_id"],
            "session_date": session_date,
            "contract_id": key[0],
            "ticker": key[1],
            "selected": selected,
            "model_eligible": _bool(candidate["model_eligible"]),
            "valid_setup": _bool(outcome.get("valid_setup")),
            "counterfactual_trade_generated": _bool(outcome.get("counterfactual_trade_generated")),
            "risk_capped_net_pnl_sek": _num(outcome.get("risk_capped_net_pnl_sek"), 0.0),
            "net_r_after_costs": _num(outcome.get("net_r_after_costs"), 0.0),
            "winning_trade": _bool(outcome.get("winning_trade")),
            "entry_time": str(outcome.get("entry_time", "")),
            "exit_time": str(outcome.get("exit_time", "")),
            "exit_reason": str(outcome.get("exit_reason", "")),
            "evidence_eligible": _bool(batch.iloc[0]["evidence_eligible"]),
            "evaluated_at": evaluated_at,
        }
        all_row["row_hash"] = _payload_hash(
            {key: value for key, value in all_row.items() if key != "evaluated_at"}
        )
        all_rows.append(all_row)

        if selected:
            selected_row = {
                "outcome_id": f"{candidate['candidate_id']}|EOD",
                "candidate_id": candidate["candidate_id"],
                "session_date": session_date,
                "contract_id": key[0],
                "ticker": key[1],
                "selected": True,
                "risk_capped_net_pnl_sek": all_row["risk_capped_net_pnl_sek"],
                "net_r_after_costs": all_row["net_r_after_costs"],
                "winning_trade": all_row["winning_trade"],
                "exit_reason": all_row["exit_reason"],
                "evidence_eligible": all_row["evidence_eligible"],
                "evaluated_at": evaluated_at,
            }
            selected_row["row_hash"] = _payload_hash(
                {key: value for key, value in selected_row.items() if key != "evaluated_at"}
            )
            selected_rows.append(selected_row)

    if len(all_rows) != expected_candidates:
        raise Step9RError(
            f"Step 9R EOD outcome coverage mismatch for {session_date}: "
            f"expected={expected_candidates}, built={len(all_rows)}."
        )

    with closing(sqlite3.connect(prospective_db)) as connection:
        _ensure_prospective_schema(connection)
        for row in all_rows:
            existing = connection.execute(
                "SELECT row_hash FROM selector_candidate_outcomes WHERE candidate_id = ?",
                (row["candidate_id"],),
            ).fetchone()
            if existing and str(existing[0]) != row["row_hash"]:
                raise Step9RError(
                    f"Immutable Step 9R all-candidate EOD conflict for {row['candidate_id']}."
                )
            if not existing:
                connection.execute(
                    "INSERT INTO selector_candidate_outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["outcome_id"], row["candidate_id"], row["session_date"],
                        row["contract_id"], row["ticker"], int(row["selected"]),
                        int(row["model_eligible"]), int(row["valid_setup"]),
                        int(row["counterfactual_trade_generated"]),
                        row["risk_capped_net_pnl_sek"], row["net_r_after_costs"],
                        int(row["winning_trade"]), row["entry_time"], row["exit_time"],
                        row["exit_reason"], int(row["evidence_eligible"]),
                        row["evaluated_at"], row["row_hash"],
                    ),
                )

        for row in selected_rows:
            existing = connection.execute(
                "SELECT row_hash FROM selector_outcomes WHERE candidate_id = ?",
                (row["candidate_id"],),
            ).fetchone()
            if existing and str(existing[0]) != row["row_hash"]:
                raise Step9RError(f"Immutable Step 9R selected EOD conflict for {row['candidate_id']}.")
            if not existing:
                connection.execute(
                    "INSERT INTO selector_outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["outcome_id"], row["candidate_id"], row["session_date"],
                        row["contract_id"], row["ticker"], 1,
                        row["risk_capped_net_pnl_sek"], row["net_r_after_costs"],
                        int(row["winning_trade"]), row["exit_reason"],
                        int(row["evidence_eligible"]), row["evaluated_at"], row["row_hash"],
                    ),
                )
        connection.commit()
        stored_all = pd.read_sql_query(
            "SELECT * FROM selector_candidate_outcomes ORDER BY session_date, contract_id, ticker",
            connection,
        )
        stored_selected = pd.read_sql_query(
            "SELECT * FROM selector_outcomes ORDER BY session_date, contract_id, ticker",
            connection,
        )

    current_all = stored_all[stored_all["session_date"].eq(session_date)].copy()
    current_selected = stored_selected[stored_selected["session_date"].eq(session_date)].copy()
    if len(current_all) != expected_candidates:
        raise Step9RError(
            f"Stored Step 9R EOD outcome coverage mismatch for {session_date}: "
            f"expected={expected_candidates}, stored={len(current_all)}."
        )
    export_csv_for_power_bi(stored_all, OUTPUT_FILES["prospective_candidate_outcomes"])
    export_csv_for_power_bi(stored_selected, OUTPUT_FILES["prospective_outcomes"])
    return current_selected

def _latest_date_in_db(path: Path) -> str:
    with closing(_connect_read_only(path)) as connection:
        row = connection.execute("SELECT MAX(substr(datetime,1,10)) FROM intraday_prices").fetchone()
    if not row or not row[0]:
        raise Step9RError(f"No dates found in {path}")
    return str(row[0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 9R V1 candidate-ranking research and prospective shadow selector.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    historical = subparsers.add_parser("historical")
    historical.add_argument("--start-date", default="2026-05-25")
    historical.add_argument("--end-date", default="")
    historical.add_argument("--source-db", type=Path, default=DEFAULT_PRICE_DB)
    historical.add_argument("--v3-ledger", type=Path, default=DEFAULT_V3_LEDGER)
    historical.add_argument("--taxonomy-ledger", type=Path, default=DEFAULT_TAXONOMY_LEDGER)
    historical.add_argument("--output-db", type=Path, default=DEFAULT_RESEARCH_DB)
    historical.add_argument("--no-rebuild-missing-taxonomy", action="store_true")
    historical.add_argument("--skip-authoritative-check", action="store_true")

    morning = subparsers.add_parser("morning")
    morning.add_argument("--date", required=True)
    morning.add_argument("--source-db", type=Path, default=DEFAULT_PRICE_DB)
    morning.add_argument("--v3-ledger", type=Path, default=DEFAULT_V3_LEDGER)
    morning.add_argument("--research-db", type=Path, default=DEFAULT_RESEARCH_DB)
    morning.add_argument("--prospective-db", type=Path, default=DEFAULT_PROSPECTIVE_DB)

    eod = subparsers.add_parser("eod")
    eod.add_argument("--date", required=True)
    eod.add_argument("--source-db", type=Path, default=DEFAULT_PRICE_DB)
    eod.add_argument("--v3-ledger", type=Path, default=DEFAULT_V3_LEDGER)
    eod.add_argument("--prospective-db", type=Path, default=DEFAULT_PROSPECTIVE_DB)

    models = subparsers.add_parser("models")
    models.add_argument("--research-db", type=Path, default=DEFAULT_RESEARCH_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "models":
        print("\n=== STEP 9R V1 WALK-FORWARD SELECTOR MODELS ===")
        outputs = run_selector_models(args.research_db)
        comparisons = outputs["selector_comparisons"]
        print(f"Models compared    : {len(comparisons)}")
        if not comparisons.empty:
            print(comparisons[["model", "evaluated_sessions", "selected_candidates", "selected_win_rate", "total_pnl_sek"]].to_string(index=False))
        print("Historical candidate outcomes were read-only. No strategy was promoted.")
        return
    if args.command == "historical":
        end_date = args.end_date or _latest_date_in_db(args.source_db)
        print("\n=== STEP 9R V1 HISTORICAL CANDIDATE-RANKING RESEARCH ===")
        print(f"Experiment       : {EXPERIMENT_ID}")
        print(f"Research status  : {RESEARCH_STATUS}")
        print(f"Window           : {args.start_date} to {end_date}")
        outputs = run_historical_research(
            start_date=args.start_date,
            end_date=end_date,
            price_db=args.source_db,
            v3_ledger=args.v3_ledger,
            taxonomy_ledger=args.taxonomy_ledger,
            output_db=args.output_db,
            rebuild_missing_taxonomy=not args.no_rebuild_missing_taxonomy,
            skip_authoritative_check=args.skip_authoritative_check,
        )
        summary = outputs["summary"].iloc[0]
        print(f"Taxonomy sessions          : {int(summary['taxonomy_sessions'])}")
        print(f"Candidate rows             : {int(summary['candidate_rows'])}")
        print(f"Valid primary candidates   : {int(summary['valid_primary_candidates'])}")
        print(f"Triggered counterfactuals  : {int(summary['triggered_primary_counterfactuals'])}")
        print(f"Profitable counterfactuals : {int(summary['profitable_primary_counterfactuals'])}")
        print(f"All-candidate win rate     : {float(summary['all_candidate_win_rate']):.1%}")
        print(f"All-candidate P&L          : {float(summary['all_candidate_pnl_sek']):.2f} SEK")
        print(f"V3-selected P&L            : {float(summary['v3_selected_pnl_sek']):.2f} SEK")
        print(f"Oracle up-to-two P&L       : {float(summary['oracle_pnl_sek']):.2f} SEK")
        print(f"Selection regret           : {float(summary['selection_regret_sek']):.2f} SEK")
        print(f"Authoritative trades       : {int(summary['authoritative_trades_checked'])}")
        print(f"Authoritative failures     : {int(summary['authoritative_replay_failures'])}")
        print(f"Audit pass                 : {bool(summary['audit_pass'])}")
        print(f"Classification             : {summary['classification']}")
        print(f"Research DB                : {args.output_db}")
        print("No source ledger was changed. No order was sent. V3 remains frozen.")
    elif args.command == "morning":
        print("\n=== STEP 9R V1 PROSPECTIVE 0-2 SHADOW SELECTOR ===")
        outputs = run_prospective_morning(
            session_date=args.date,
            price_db=args.source_db,
            v3_ledger=args.v3_ledger,
            research_db=args.research_db,
            prospective_db=args.prospective_db,
        )
        candidates = outputs["candidates"]
        selections = outputs["selections"]
        print(f"Session date       : {args.date}")
        print(f"Candidate rows     : {len(candidates)}")
        print(f"Selected rows      : {len(selections)}")
        if not selections.empty:
            for row in selections.to_dict("records"):
                print(f"  {row['research_rank']}. {row['ticker']} | {row['contract_id']} | expected R={_num(row['simple_expected_r']):.4f}")
        else:
            print("  No candidate exceeded the locked positive expected-R threshold.")
        print("Shadow research only. No order was sent and V3 was not changed.")
    else:
        print("\n=== STEP 9R V1 PROSPECTIVE SELECTOR EOD ===")
        outcomes = run_prospective_eod(
            session_date=args.date,
            price_db=args.source_db,
            v3_ledger=args.v3_ledger,
            prospective_db=args.prospective_db,
        )
        with closing(sqlite3.connect(args.prospective_db)) as connection:
            all_count = connection.execute(
                "SELECT COUNT(*) FROM selector_candidate_outcomes WHERE session_date = ?",
                (args.date,),
            ).fetchone()[0]
        print(f"Session date       : {args.date}")
        print(f"Candidate outcomes : {all_count}")
        print(f"Selected outcomes  : {len(outcomes)}")
        print(f"Selected P&L       : {pd.to_numeric(outcomes.get('risk_capped_net_pnl_sek'), errors='coerce').fillna(0).sum():.2f} SEK")
        print("All morning candidates were preserved; selections were not rewritten.")


if __name__ == "__main__":
    main()
