from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.paths import DATA_DIR, FREEZE_DIRS
from RegimeTrading.core.stage_registry import resolve_stage_output_dir


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "step9u_historical_contingency_selector_v1.json"
STEP9T_DIR = resolve_stage_output_dir("step9t")
STEP9T_FREEZE_DIR = FREEZE_DIRS["step9t"]
STEP9T_FREEZE_MANIFEST = STEP9T_FREEZE_DIR / "STEP9T_HISTORICAL_REPLAY_V1_FREEZE_MANIFEST.json"
STEP9T_SESSION_FILE = STEP9T_DIR / "step9t_session_transitions.csv"
STEP9T_ARCHETYPE_FILE = STEP9T_DIR / "step9t_ticker_archetypes.csv"
STEP9T_OUTCOME_FILE = STEP9T_DIR / "step9t_ticker_outcomes.csv"
STEP9S_DIR = resolve_stage_output_dir("step9s")
STEP9S_SUMMARY_FILE = STEP9S_DIR / "step9s_summary.csv"
DEFAULT_OUTPUT_DIR = resolve_stage_output_dir("step9u")

POLICY_REGISTRY_EXPORT = "step9u_policy_registry.csv"
SESSION_ASSIGNMENTS_EXPORT = "step9u_session_assignments.csv"
CANDIDATES_EXPORT = "step9u_all_candidates.csv"
SELECTED_OUTCOMES_EXPORT = "step9u_selected_outcomes.csv"
PERFORMANCE_EXPORT = "step9u_performance.csv"
REGRET_EXPORT = "step9u_selection_regret.csv"
DAILY_PNL_EXPORT = "step9u_daily_pnl.csv"
BENCHMARK_EXPORT = "step9u_step9s_benchmark_comparison.csv"
AUDIT_EXPORT = "step9u_audit.csv"
SUMMARY_EXPORT = "step9u_summary.csv"
SOURCE_HASH_EXPORT = "step9u_source_hashes.json"


class Step9UError(RuntimeError):
    pass


class Step9USourceError(Step9UError):
    pass


class Step9UIntegrityError(Step9UError):
    pass


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _clean_scalar(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_clean_scalar(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.integer):
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


def _project_relative_source_label(path: Path) -> str:
    """Return a platform-neutral project-relative provenance label."""

    resolved_root = PROJECT_ROOT.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise Step9UIntegrityError(
            f"Source path is outside the project root: {resolved_path}"
        ) from exc


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def _load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    if bool(config.get("router_active")) or bool(config.get("orders_enabled")):
        raise Step9UIntegrityError("Step 9U historical replay must remain router inactive and order disabled.")
    if bool(config.get("mandatory_control_active")):
        raise Step9UIntegrityError("Step 9U V1 must not create a mandatory control book; Step 9S remains the benchmark.")
    if int(config.get("max_selected_positions", 0)) != 2:
        raise Step9UIntegrityError("Step 9U V1 must select at most two shadow positions.")
    if int(config.get("max_positions_per_sector", 0)) != 1:
        raise Step9UIntegrityError("Step 9U V1 sector-diversification limit must equal one.")
    rules = list(config.get("rules", []))
    expected = {
        "HD_MIXED_BCL_AVOID_V1",
        "LRL_AGGREGATE_PROMISING_V1",
        "VE_BCL_BACKOFF_CHALLENGER_V1",
    }
    if {str(rule.get("rule_id")) for rule in rules} != expected:
        raise Step9UIntegrityError("Step 9U V1 rule registry is incomplete or unexpected.")
    return config


CONFIG = _load_config()
EXPERIMENT_ID = str(CONFIG["experiment_id"])
RESEARCH_STATUS = str(CONFIG["research_status"])
CODE_VERSION = str(CONFIG["code_version"])
FREEZE_ID = str(CONFIG["historical_freeze_id"])
ARTIFACT_SET_SHA256 = str(CONFIG["historical_artifact_set_sha256"])
FREEZE_MANIFEST_SHA256 = str(CONFIG["historical_freeze_manifest_sha256"])
MAX_SELECTED_POSITIONS = int(CONFIG["max_selected_positions"])
MAX_POSITIONS_PER_SECTOR = int(CONFIG["max_positions_per_sector"])


def verify_historical_freeze(
    *,
    freeze_manifest: Path = STEP9T_FREEZE_MANIFEST,
    step9t_dir: Path = STEP9T_DIR,
) -> dict[str, Any]:
    if not freeze_manifest.is_file():
        raise FileNotFoundError(freeze_manifest)
    if _sha256(freeze_manifest) != FREEZE_MANIFEST_SHA256:
        raise Step9UIntegrityError("Step 9T freeze manifest hash does not match the pinned Step 9U configuration.")
    manifest = json.loads(freeze_manifest.read_text(encoding="utf-8"))
    if str(manifest.get("freeze_id")) != FREEZE_ID:
        raise Step9UIntegrityError("Unexpected Step 9T historical freeze ID.")
    if str(manifest.get("artifact_set_sha256")) != ARTIFACT_SET_SHA256:
        raise Step9UIntegrityError("Unexpected Step 9T historical artifact-set hash.")
    audit = dict(manifest.get("independent_audit", {}))
    if int(audit.get("passed", -1)) != 30 or int(audit.get("failed", -1)) != 0:
        raise Step9UIntegrityError("Step 9T historical freeze is not independently audited 30/30.")
    if bool(manifest.get("router_active")) or bool(manifest.get("orders_sent")):
        raise Step9UIntegrityError("Unsafe state found in the Step 9T freeze manifest.")
    verified = 0
    for artifact in manifest.get("input_artifacts", []):
        path = step9t_dir / str(artifact["filename"])
        if not path.is_file():
            raise FileNotFoundError(path)
        if _sha256(path) != str(artifact["sha256"]):
            raise Step9UIntegrityError(f"Frozen Step 9T artifact differs: {path}")
        verified += 1
    if verified != 10:
        raise Step9UIntegrityError(f"Expected ten frozen Step 9T input artifacts, verified {verified}.")
    return manifest


def policy_registry() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for order, rule in enumerate(CONFIG["rules"], start=1):
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "code_version": CODE_VERSION,
                "rule_order": order,
                "rule_id": str(rule["rule_id"]),
                "action": str(rule["action"]),
                "priority": int(rule["priority"]),
                "source_regime": str(rule["source_regime"]),
                "transition_state": str(rule["transition_state"]),
                "primary_archetype": str(rule["primary_archetype"]),
                "signal_formula": str(rule["signal_formula"]),
                "evidence_basis": str(rule["evidence_basis"]),
                "historical_design_note": str(rule["historical_design_note"]),
                "prospective_validation_status": "NOT_YET_PROSPECTIVELY_VALIDATED",
                "router_active": False,
                "orders_sent": False,
            }
        )
    return pd.DataFrame(rows)


def _validate_step9t_sources(
    sessions: pd.DataFrame,
    archetypes: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> None:
    session_required = {
        "session_date",
        "source_regime",
        "transition_state",
        "transition_batch_id",
        "router_active",
        "orders_sent",
    }
    archetype_required = {
        "session_date",
        "ticker",
        "broad_sector",
        "morning_status",
        "early_return",
        "last5_return",
        "primary_archetype",
        "direction",
        "source_regime",
        "transition_state",
        "ticker_row_id",
    }
    outcome_required = {
        "ticker_row_id",
        "outcome_status",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "session_close_return",
        "mfe_return",
        "mae_return",
        "gross_pnl_sek",
        "cost_sek",
        "net_pnl_sek",
        "outcome_id",
    }
    for name, frame, required in (
        ("sessions", sessions, session_required),
        ("archetypes", archetypes, archetype_required),
        ("outcomes", outcomes, outcome_required),
    ):
        missing = required.difference(frame.columns)
        if missing:
            raise Step9USourceError(f"Step 9T {name} source is missing columns: {sorted(missing)}")
    if sessions["session_date"].astype(str).duplicated().any():
        raise Step9UIntegrityError("Step 9T session transitions contain duplicate session keys.")
    if archetypes["ticker_row_id"].astype(str).duplicated().any():
        raise Step9UIntegrityError("Step 9T archetypes contain duplicate ticker-row IDs.")
    if outcomes["ticker_row_id"].astype(str).duplicated().any():
        raise Step9UIntegrityError("Step 9T outcomes contain duplicate ticker-row IDs.")
    if set(archetypes["ticker_row_id"].astype(str)) != set(outcomes["ticker_row_id"].astype(str)):
        raise Step9UIntegrityError("Step 9T archetype and outcome IDs do not reconcile one-to-one.")
    if bool(pd.Series(sessions["router_active"]).astype(bool).any()):
        raise Step9UIntegrityError("Step 9T session source unexpectedly has router active rows.")
    if bool(pd.Series(sessions["orders_sent"]).astype(bool).any()):
        raise Step9UIntegrityError("Step 9T session source unexpectedly has order rows.")


def _policy_decision(row: pd.Series) -> dict[str, Any]:
    source_regime = str(row["source_regime"])
    transition_state = str(row["transition_state"])
    archetype = str(row["primary_archetype"])

    if (
        source_regime == "HIGH_DISPERSION"
        and transition_state == "MIXED_TRANSITION"
        and archetype == "BULLISH_CONTINUATION_LONG"
    ):
        return {
            "policy_action": "BLOCKED_NEGATIVE_CONTROL",
            "rule_id": "HD_MIXED_BCL_AVOID_V1",
            "rule_priority": 1000,
            "signal_strength": np.nan,
            "selection_eligible": False,
            "blocked_reason": "FROZEN_NEGATIVE_EXPLORATORY_CELL",
        }

    early_return = float(row["early_return"])
    last5_return = float(row["last5_return"])

    if archetype == "LAGGARD_RECOVERY_LONG":
        return {
            "policy_action": "SELECTABLE_CHALLENGER",
            "rule_id": "LRL_AGGREGATE_PROMISING_V1",
            "rule_priority": 200,
            "signal_strength": max(-early_return, 0.0) + max(last5_return, 0.0),
            "selection_eligible": True,
            "blocked_reason": "",
        }

    if source_regime == "VOLATILITY_EXPANSION" and archetype == "BULLISH_CONTINUATION_LONG":
        return {
            "policy_action": "SELECTABLE_CHALLENGER",
            "rule_id": "VE_BCL_BACKOFF_CHALLENGER_V1",
            "rule_priority": 100,
            "signal_strength": max(early_return, 0.0) + max(last5_return, 0.0),
            "selection_eligible": True,
            "blocked_reason": "",
        }

    return {
        "policy_action": "OBSERVATION_ONLY",
        "rule_id": "NO_SELECT_RULE_V1",
        "rule_priority": 0,
        "signal_strength": np.nan,
        "selection_eligible": False,
        "blocked_reason": "NO_FROZEN_POSITIVE_CHALLENGER_RULE",
    }


def build_candidate_book(
    sessions: pd.DataFrame,
    archetypes: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> pd.DataFrame:
    _validate_step9t_sources(sessions, archetypes, outcomes)
    candidates = archetypes[
        archetypes["morning_status"].astype(str).eq("MORNING_COMPLETE")
        & ~archetypes["direction"].astype(str).eq("NONE")
    ].copy()
    candidates = candidates.rename(
        columns={
            "experiment_id": "source_experiment_id",
            "code_version": "source_code_version",
        }
    )
    outcome_columns = [
        "ticker_row_id",
        "outcome_status",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "session_close_return",
        "mfe_return",
        "mae_return",
        "gross_pnl_sek",
        "cost_sek",
        "net_pnl_sek",
        "outcome_id",
    ]
    candidates = candidates.merge(outcomes[outcome_columns], on="ticker_row_id", how="left", validate="one_to_one")
    decisions = candidates.apply(_policy_decision, axis=1, result_type="expand")
    candidates = pd.concat([candidates.reset_index(drop=True), decisions.reset_index(drop=True)], axis=1)
    candidates["selected"] = False
    candidates["selected_rank"] = pd.Series(pd.NA, index=candidates.index, dtype="Int64")
    candidates["selection_reason"] = "NOT_SELECTED"

    for session_date, group in candidates[candidates["selection_eligible"]].groupby("session_date", sort=True):
        ranked = group.sort_values(
            ["rule_priority", "signal_strength", "ticker"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        selected_indices: list[int] = []
        used_sectors: dict[str, int] = {}
        for index, row in ranked.iterrows():
            sector = str(row["broad_sector"])
            if used_sectors.get(sector, 0) >= MAX_POSITIONS_PER_SECTOR:
                candidates.at[index, "selection_reason"] = "SKIPPED_SECTOR_LIMIT"
                continue
            selected_indices.append(index)
            used_sectors[sector] = used_sectors.get(sector, 0) + 1
            if len(selected_indices) >= MAX_SELECTED_POSITIONS:
                break
        for rank, index in enumerate(selected_indices, start=1):
            candidates.at[index, "selected"] = True
            candidates.at[index, "selected_rank"] = rank
            candidates.at[index, "selection_reason"] = "SELECTED_BY_FROZEN_V1_POLICY"
        remaining = ranked.index.difference(selected_indices)
        for index in remaining:
            if candidates.at[index, "selection_reason"] == "NOT_SELECTED":
                candidates.at[index, "selection_reason"] = "NOT_SELECTED_POSITION_LIMIT"

    candidates["candidate_id"] = candidates.apply(
        lambda row: _payload_hash(
            {
                "experiment_id": EXPERIMENT_ID,
                "session_date": str(row["session_date"]),
                "ticker": str(row["ticker"]),
                "ticker_row_id": str(row["ticker_row_id"]),
                "policy_action": str(row["policy_action"]),
                "rule_id": str(row["rule_id"]),
                "selected": bool(row["selected"]),
                "selected_rank": None if pd.isna(row["selected_rank"]) else int(row["selected_rank"]),
            }
        ),
        axis=1,
    )
    candidates.insert(0, "experiment_id", EXPERIMENT_ID)
    candidates.insert(1, "code_version", CODE_VERSION)
    candidates["historical_status"] = "RETROSPECTIVE_IN_SAMPLE_RULE_DESIGN_NON_CONFIRMATORY"
    candidates["selection_uses_outcome_fields"] = False
    candidates["router_active"] = False
    candidates["orders_sent"] = False
    return candidates.sort_values(["session_date", "selected_rank", "ticker"], na_position="last").reset_index(drop=True)


def build_session_assignments(sessions: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, session in sessions.sort_values("session_date").iterrows():
        date = str(session["session_date"])
        group = candidates[candidates["session_date"].astype(str).eq(date)]
        selected = group[group["selected"]]
        selected_tickers = "|".join(selected.sort_values("selected_rank")["ticker"].astype(str))
        selected_rules = "|".join(selected.sort_values("selected_rank")["rule_id"].astype(str))
        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "code_version": CODE_VERSION,
                "session_date": date,
                "source_regime": str(session["source_regime"]),
                "transition_state": str(session["transition_state"]),
                "transition_batch_id": str(session["transition_batch_id"]),
                "directional_candidate_rows": int(len(group)),
                "selectable_candidate_rows": int(group["selection_eligible"].sum()),
                "blocked_negative_control_rows": int(group["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL").sum()),
                "observation_only_rows": int(group["policy_action"].eq("OBSERVATION_ONLY").sum()),
                "selected_count": int(group["selected"].sum()),
                "selected_tickers": selected_tickers,
                "selected_rule_ids": selected_rules,
                "no_selection_reason": "" if len(selected) else "NO_SELECTABLE_CANDIDATE",
                "mandatory_control_active": False,
                "historical_status": "RETROSPECTIVE_IN_SAMPLE_RULE_DESIGN_NON_CONFIRMATORY",
                "router_active": False,
                "orders_sent": False,
            }
        )
    return pd.DataFrame(rows)


def _performance_rows(candidates: pd.DataFrame) -> pd.DataFrame:
    complete = candidates[candidates["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE")].copy()
    group_specs = [
        ("ALL_DIRECTIONAL_CANDIDATES", [], complete),
        ("SELECTABLE_CANDIDATES", [], complete[complete["selection_eligible"]]),
        ("SELECTED_PORTFOLIO", [], complete[complete["selected"]]),
        ("BLOCKED_NEGATIVE_CONTROL", [], complete[complete["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL")]),
        ("SELECTED_BY_RULE", ["rule_id"], complete[complete["selected"]]),
        ("SELECTED_BY_REGIME", ["source_regime"], complete[complete["selected"]]),
        ("SELECTED_BY_TRANSITION", ["transition_state"], complete[complete["selected"]]),
        ("SELECTED_BY_ARCHETYPE", ["primary_archetype"], complete[complete["selected"]]),
    ]
    records: list[dict[str, Any]] = []
    for scope, group_columns, frame in group_specs:
        if group_columns:
            iterator = frame.groupby(group_columns, dropna=False, sort=True)
        else:
            iterator = [((), frame)]
        for key, group in iterator:
            if group.empty:
                continue
            keys = key if isinstance(key, tuple) else (key,)
            values = dict(zip(group_columns, keys))
            pnl = pd.to_numeric(group["net_pnl_sek"], errors="coerce")
            wins = int((pnl > 0).sum())
            losses = int((pnl <= 0).sum())
            gross_profit = float(pnl[pnl > 0].sum())
            gross_loss = float(-pnl[pnl < 0].sum())
            records.append(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "scope": scope,
                    "source_regime": values.get("source_regime", "ALL"),
                    "transition_state": values.get("transition_state", "ALL"),
                    "primary_archetype": values.get("primary_archetype", "ALL"),
                    "rule_id": values.get("rule_id", "ALL"),
                    "sessions": int(group["session_date"].nunique()),
                    "outcomes": int(len(group)),
                    "wins": wins,
                    "losses_or_nonpositive": losses,
                    "win_rate": float(wins / len(group)),
                    "net_pnl_sek": float(pnl.sum()),
                    "average_pnl_sek": float(pnl.mean()),
                    "median_pnl_sek": float(pnl.median()),
                    "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else np.inf,
                    "average_mfe_return": float(pd.to_numeric(group["mfe_return"], errors="coerce").mean()),
                    "average_mae_return": float(pd.to_numeric(group["mae_return"], errors="coerce").mean()),
                }
            )
    return pd.DataFrame(records)


def _selection_regret(candidates: pd.DataFrame) -> pd.DataFrame:
    """Future-information opportunity-cost diagnostic under the live constraints.

    The oracle may select zero, one, or two positive-outcome candidates and must
    obey the same one-position-per-sector constraint as Step 9U. This makes the
    oracle a feasible upper bound and keeps selection_regret_sek non-negative.
    The oracle is diagnostic only and never affects historical or prospective
    selection.
    """

    rows: list[dict[str, Any]] = []
    oracle_contract = "UP_TO_2_POSITIVE_MAX_1_PER_SECTOR_V1"

    for session_date, group in candidates.groupby("session_date", sort=True):
        eligible = group[
            group["selection_eligible"]
            & group["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE")
        ].copy()
        eligible["net_pnl_sek"] = pd.to_numeric(eligible["net_pnl_sek"], errors="coerce")

        selected = eligible[eligible["selected"]].copy()
        selected_pnl = float(selected["net_pnl_sek"].sum())

        oracle_rows: list[pd.Series] = []
        used_sectors: set[str] = set()
        ranked_oracle = eligible.sort_values(
            ["net_pnl_sek", "ticker"],
            ascending=[False, True],
            kind="mergesort",
        )
        for _, candidate in ranked_oracle.iterrows():
            if float(candidate["net_pnl_sek"]) <= 0.0:
                continue
            sector = str(candidate["broad_sector"])
            if sector in used_sectors:
                continue
            oracle_rows.append(candidate)
            used_sectors.add(sector)
            if len(oracle_rows) >= MAX_SELECTED_POSITIONS:
                break

        oracle = pd.DataFrame(oracle_rows, columns=eligible.columns)
        oracle_pnl = float(pd.to_numeric(oracle.get("net_pnl_sek"), errors="coerce").sum()) if not oracle.empty else 0.0
        regret = oracle_pnl - selected_pnl
        if regret < -1e-9:
            raise Step9UIntegrityError(
                f"Feasible future-information oracle fell below selected P&L for {session_date}: {regret}"
            )

        rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "session_date": str(session_date),
                "eligible_complete_outcomes": int(len(eligible)),
                "selected_complete_outcomes": int(len(selected)),
                "selected_net_pnl_sek": selected_pnl,
                "oracle_top2_net_pnl_sek": oracle_pnl,
                "selection_regret_sek": max(0.0, regret),
                "selected_tickers": "|".join(selected.sort_values("selected_rank")["ticker"].astype(str)),
                "oracle_tickers": "|".join(oracle["ticker"].astype(str)) if not oracle.empty else "",
                "oracle_positions": int(len(oracle)),
                "oracle_contract": oracle_contract,
                "oracle_is_future_information_diagnostic_only": True,
            }
        )
    return pd.DataFrame(rows)


def _daily_pnl(assignments: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    complete = candidates[
        candidates["selected"]
        & candidates["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE")
    ].copy()
    grouped = (
        complete.groupby("session_date", sort=True)
        .agg(
            complete_selected_outcomes=("ticker", "size"),
            winning_outcomes=("net_pnl_sek", lambda values: int((pd.to_numeric(values, errors="coerce") > 0).sum())),
            net_pnl_sek=("net_pnl_sek", "sum"),
        )
        .reset_index()
    )
    daily = assignments[["session_date", "source_regime", "transition_state", "selected_count"]].merge(
        grouped, on="session_date", how="left", validate="one_to_one"
    )
    daily["complete_selected_outcomes"] = daily["complete_selected_outcomes"].fillna(0).astype(int)
    daily["winning_outcomes"] = daily["winning_outcomes"].fillna(0).astype(int)
    daily["net_pnl_sek"] = pd.to_numeric(daily["net_pnl_sek"], errors="coerce").fillna(0.0)
    daily["traded_session"] = daily["complete_selected_outcomes"].gt(0)
    daily["positive_session"] = daily["net_pnl_sek"].gt(0)
    daily["cumulative_net_pnl_sek"] = daily["net_pnl_sek"].cumsum()
    daily["running_peak_net_pnl_sek"] = daily["cumulative_net_pnl_sek"].cummax()
    daily["drawdown_sek"] = daily["cumulative_net_pnl_sek"] - daily["running_peak_net_pnl_sek"]
    daily.insert(0, "experiment_id", EXPERIMENT_ID)
    return daily


def _benchmark_comparison(summary: dict[str, Any], step9s_summary_file: Path) -> pd.DataFrame:
    rows = [
        {
            "engine": "STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1",
            "book": "SELECTED_STANDARDIZED_0950_TO_EOD",
            "sessions": int(summary["sessions"]),
            "sessions_with_trades": int(summary["selected_sessions"]),
            "trades": int(summary["selected_candidates"]),
            "complete_outcomes": int(summary["selected_complete_outcomes"]),
            "net_pnl_sek": float(summary["selected_net_pnl_sek"]),
            "execution_contract": "STEP9T_STANDARDIZED_0950_OPEN_TO_EOD_CLOSE",
            "direct_pnl_comparison_allowed": False,
            "comparison_note": "Step 9U uses standardized Step 9T outcomes; Step 9S uses its own contract-specific entries, stops and targets.",
        }
    ]
    if step9s_summary_file.is_file():
        step9s = pd.read_csv(step9s_summary_file)
        if len(step9s) != 1:
            raise Step9USourceError("Step 9S historical summary must contain exactly one row.")
        row = step9s.iloc[0]
        rows.extend(
            [
                {
                    "engine": "STEP9S_HISTORICAL_CONTINGENCY_REPLAY_V1",
                    "book": "NATURAL_STRATEGY_BOOK",
                    "sessions": int(row["sessions"]),
                    "sessions_with_trades": int(row["natural_sessions_with_trades"]),
                    "trades": int(row["natural_trades"]),
                    "complete_outcomes": int(row["natural_trades"]),
                    "net_pnl_sek": float(row["natural_net_pnl_sek"]),
                    "execution_contract": "STEP9S_FROZEN_CONTRACT_SPECIFIC",
                    "direct_pnl_comparison_allowed": False,
                    "comparison_note": "Frozen benchmark shown for context only; execution contracts differ.",
                },
                {
                    "engine": "STEP9S_HISTORICAL_CONTINGENCY_REPLAY_V1",
                    "book": "MANDATORY_COVERAGE_CONTROL_BOOK",
                    "sessions": int(row["sessions"]),
                    "sessions_with_trades": int(row["mandatory_coverage_sessions"]),
                    "trades": int(row["mandatory_coverage_trades"]),
                    "complete_outcomes": int(row["mandatory_coverage_trades"]),
                    "net_pnl_sek": float(row["mandatory_coverage_net_pnl_sek"]),
                    "execution_contract": "STEP9S_FROZEN_CONTRACT_SPECIFIC",
                    "direct_pnl_comparison_allowed": False,
                    "comparison_note": "Frozen mandatory control shown for coverage context only; execution contracts differ.",
                },
            ]
        )
    return pd.DataFrame(rows)


def _audit(
    sessions: pd.DataFrame,
    archetypes: pd.DataFrame,
    outcomes: pd.DataFrame,
    candidates: pd.DataFrame,
    assignments: pd.DataFrame,
) -> pd.DataFrame:
    selected = candidates[candidates["selected"]]
    checks = [
        ("historical_freeze_id", FREEZE_ID == "92b274cb24cad391", FREEZE_ID),
        ("historical_artifact_set", ARTIFACT_SET_SHA256.startswith(FREEZE_ID), ARTIFACT_SET_SHA256),
        ("session_count", len(sessions) == 62, len(sessions)),
        ("session_keys_unique", not sessions["session_date"].duplicated().any(), int(sessions["session_date"].duplicated().sum())),
        ("archetype_rows", len(archetypes) == 1798, len(archetypes)),
        ("outcome_rows", len(outcomes) == 1798, len(outcomes)),
        ("archetype_ids_unique", not archetypes["ticker_row_id"].duplicated().any(), int(archetypes["ticker_row_id"].duplicated().sum())),
        ("outcome_ids_unique", not outcomes["ticker_row_id"].duplicated().any(), int(outcomes["ticker_row_id"].duplicated().sum())),
        ("archetype_outcome_one_to_one", set(archetypes["ticker_row_id"]) == set(outcomes["ticker_row_id"]), "one_to_one"),
        ("candidate_rows_preserved", len(candidates) == 970, len(candidates)),
        ("candidate_ids_unique", not candidates["candidate_id"].duplicated().any(), int(candidates["candidate_id"].duplicated().sum())),
        ("selectable_candidates", int(candidates["selection_eligible"].sum()) == 158, int(candidates["selection_eligible"].sum())),
        ("blocked_negative_controls", int(candidates["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL").sum()) == 79, int(candidates["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL").sum())),
        ("selected_candidates", int(candidates["selected"].sum()) == 73, int(candidates["selected"].sum())),
        ("selected_sessions", int(selected["session_date"].nunique()) == 43, int(selected["session_date"].nunique())),
        ("max_two_positions", int(selected.groupby("session_date").size().max()) <= 2, int(selected.groupby("session_date").size().max())),
        ("max_one_per_sector", int(selected.groupby(["session_date", "broad_sector"]).size().max()) <= 1, int(selected.groupby(["session_date", "broad_sector"]).size().max())),
        ("selected_are_eligible", bool(selected["selection_eligible"].all()), int((~selected["selection_eligible"]).sum())),
        ("blocked_never_selected", not bool(candidates.loc[candidates["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL"), "selected"].any()), int(candidates.loc[candidates["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL"), "selected"].sum())),
        ("observation_never_selected", not bool(candidates.loc[candidates["policy_action"].eq("OBSERVATION_ONLY"), "selected"].any()), int(candidates.loc[candidates["policy_action"].eq("OBSERVATION_ONLY"), "selected"].sum())),
        ("selection_no_outcome_fields", not bool(candidates["selection_uses_outcome_fields"].any()), int(candidates["selection_uses_outcome_fields"].sum())),
        ("all_sessions_assigned", len(assignments) == len(sessions), len(assignments)),
        ("assignment_keys_unique", not assignments["session_date"].duplicated().any(), int(assignments["session_date"].duplicated().sum())),
        ("router_inactive_candidates", not bool(candidates["router_active"].any()), int(candidates["router_active"].sum())),
        ("orders_absent_candidates", not bool(candidates["orders_sent"].any()), int(candidates["orders_sent"].sum())),
        ("router_inactive_assignments", not bool(assignments["router_active"].any()), int(assignments["router_active"].sum())),
        ("orders_absent_assignments", not bool(assignments["orders_sent"].any()), int(assignments["orders_sent"].sum())),
        ("mandatory_control_disabled", not bool(assignments["mandatory_control_active"].any()), int(assignments["mandatory_control_active"].sum())),
        ("historical_status_nonconfirmatory", candidates["historical_status"].eq("RETROSPECTIVE_IN_SAMPLE_RULE_DESIGN_NON_CONFIRMATORY").all(), int((~candidates["historical_status"].eq("RETROSPECTIVE_IN_SAMPLE_RULE_DESIGN_NON_CONFIRMATORY")).sum())),
        ("selected_outcome_linkage", selected["outcome_id"].notna().all(), int(selected["outcome_id"].isna().sum())),
    ]
    return pd.DataFrame(
        [
            {
                "check_id": check_id,
                "passed": bool(passed),
                "observed": observed,
            }
            for check_id, passed, observed in checks
        ]
    )


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def run_historical_replay(
    *,
    step9t_dir: Path = STEP9T_DIR,
    freeze_manifest: Path = STEP9T_FREEZE_MANIFEST,
    step9s_summary_file: Path = STEP9S_SUMMARY_FILE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    write_outputs: bool = True,
) -> dict[str, Any]:
    manifest = verify_historical_freeze(freeze_manifest=freeze_manifest, step9t_dir=step9t_dir)
    sessions = _read_csv(step9t_dir / STEP9T_SESSION_FILE.name)
    archetypes = _read_csv(step9t_dir / STEP9T_ARCHETYPE_FILE.name)
    outcomes = _read_csv(step9t_dir / STEP9T_OUTCOME_FILE.name)
    candidates = build_candidate_book(sessions, archetypes, outcomes)
    assignments = build_session_assignments(sessions, candidates)
    selected_outcomes = candidates[candidates["selected"]].copy().reset_index(drop=True)
    performance = _performance_rows(candidates)
    regret = _selection_regret(candidates)
    daily_pnl = _daily_pnl(assignments, candidates)

    complete_selected = selected_outcomes[
        selected_outcomes["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE")
    ]
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "code_version": CODE_VERSION,
        "historical_freeze_id": FREEZE_ID,
        "historical_artifact_set_sha256": ARTIFACT_SET_SHA256,
        "sessions": int(len(sessions)),
        "regimes": int(sessions["source_regime"].nunique()),
        "transition_states": int(sessions["transition_state"].nunique()),
        "directional_candidate_rows": int(len(candidates)),
        "selectable_candidates": int(candidates["selection_eligible"].sum()),
        "blocked_negative_controls": int(candidates["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL").sum()),
        "selected_candidates": int(candidates["selected"].sum()),
        "selected_sessions": int(selected_outcomes["session_date"].nunique()),
        "selected_complete_outcomes": int(len(complete_selected)),
        "selected_incomplete_outcomes": int(len(selected_outcomes) - len(complete_selected)),
        "selected_net_pnl_sek": float(pd.to_numeric(complete_selected["net_pnl_sek"], errors="coerce").sum()),
        "selected_average_pnl_sek": float(pd.to_numeric(complete_selected["net_pnl_sek"], errors="coerce").mean()),
        "selected_win_rate": float((pd.to_numeric(complete_selected["net_pnl_sek"], errors="coerce") > 0).mean()),
        "selected_complete_traded_sessions": int(daily_pnl["traded_session"].sum()),
        "selected_positive_sessions": int(daily_pnl["positive_session"].sum()),
        "selected_positive_session_rate": float(
            daily_pnl.loc[daily_pnl["traded_session"], "positive_session"].mean()
        ),
        "selected_max_drawdown_sek": float(daily_pnl["drawdown_sek"].min()),
        "selected_best_session_pnl_sek": float(daily_pnl["net_pnl_sek"].max()),
        "selected_worst_session_pnl_sek": float(daily_pnl["net_pnl_sek"].min()),
        "mandatory_control_active": False,
        "selection_is_historical_replay_only": True,
        "prospective_validation_status": "NOT_YET_PROSPECTIVELY_VALIDATED",
        "audit_pass": False,
        "router_active": False,
        "orders_sent": False,
    }
    benchmark = _benchmark_comparison(summary, step9s_summary_file)
    audit = _audit(sessions, archetypes, outcomes, candidates, assignments)
    summary["audit_pass"] = bool(audit["passed"].all())
    if not summary["audit_pass"]:
        failed = audit.loc[~audit["passed"], "check_id"].tolist()
        raise Step9UIntegrityError(f"Step 9U historical audit failed: {failed}")

    source_files = [
        step9t_dir / STEP9T_SESSION_FILE.name,
        step9t_dir / STEP9T_ARCHETYPE_FILE.name,
        step9t_dir / STEP9T_OUTCOME_FILE.name,
        freeze_manifest,
        CONFIG_FILE,
    ]
    if step9s_summary_file.is_file():
        source_files.append(step9s_summary_file)

    source_paths = {
        _project_relative_source_label(source_file): _sha256(source_file)
        for source_file in source_files
    }

    if write_outputs:
        output_dir.mkdir(parents=True, exist_ok=True)
        _atomic_csv(policy_registry(), output_dir / POLICY_REGISTRY_EXPORT)
        _atomic_csv(assignments, output_dir / SESSION_ASSIGNMENTS_EXPORT)
        _atomic_csv(candidates, output_dir / CANDIDATES_EXPORT)
        _atomic_csv(selected_outcomes, output_dir / SELECTED_OUTCOMES_EXPORT)
        _atomic_csv(performance, output_dir / PERFORMANCE_EXPORT)
        _atomic_csv(regret, output_dir / REGRET_EXPORT)
        _atomic_csv(daily_pnl, output_dir / DAILY_PNL_EXPORT)
        _atomic_csv(benchmark, output_dir / BENCHMARK_EXPORT)
        _atomic_csv(audit, output_dir / AUDIT_EXPORT)
        _atomic_csv(pd.DataFrame([summary]), output_dir / SUMMARY_EXPORT)
        (output_dir / SOURCE_HASH_EXPORT).write_text(
            json.dumps(
                {
                    "experiment_id": EXPERIMENT_ID,
                    "freeze_id": FREEZE_ID,
                    "artifact_set_sha256": ARTIFACT_SET_SHA256,
                    "source_hashes": source_paths,
                    "freeze_manifest": manifest,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    return {
        "summary": summary,
        "policy_registry": policy_registry(),
        "assignments": assignments,
        "candidates": candidates,
        "selected_outcomes": selected_outcomes,
        "performance": performance,
        "regret": regret,
        "daily_pnl": daily_pnl,
        "benchmark": benchmark,
        "audit": audit,
    }


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 9U V1 historical contingency selector replay")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = _parse_args(argv)
    result = run_historical_replay(output_dir=args.output_dir)
    summary = result["summary"]
    print("STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1: PASSED")
    print(f"HISTORICAL_FREEZE_ID: {summary['historical_freeze_id']}")
    print(f"SESSIONS_REGIMES_TRANSITIONS: {summary['sessions']}/{summary['regimes']}/{summary['transition_states']}")
    print(f"DIRECTIONAL_CANDIDATE_ROWS: {summary['directional_candidate_rows']}")
    print(f"SELECTABLE_CANDIDATES: {summary['selectable_candidates']}")
    print(f"BLOCKED_NEGATIVE_CONTROLS: {summary['blocked_negative_controls']}")
    print(f"SELECTED_CANDIDATES_SESSIONS: {summary['selected_candidates']}/{summary['selected_sessions']}")
    print(f"SELECTED_COMPLETE_INCOMPLETE: {summary['selected_complete_outcomes']}/{summary['selected_incomplete_outcomes']}")
    print(f"SELECTED_NET_STANDARDIZED_PNL_SEK: {summary['selected_net_pnl_sek']:.6f}")
    print(f"SELECTED_AVERAGE_PNL_SEK: {summary['selected_average_pnl_sek']:.6f}")
    print(f"SELECTED_WIN_RATE: {summary['selected_win_rate']:.6f}")
    print(f"SELECTED_POSITIVE_SESSION_RATE: {summary['selected_positive_session_rate']:.6f}")
    print(f"SELECTED_MAX_DRAWDOWN_SEK: {summary['selected_max_drawdown_sek']:.6f}")
    print("HISTORICAL STATUS: RETROSPECTIVE IN-SAMPLE RULE DESIGN / NON-CONFIRMATORY")
    print("MANDATORY CONTROL ACTIVE: FALSE")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
