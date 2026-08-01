from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from RegimeTrading.core.paths import legacy_output_path
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path
from RegimeTrading.scripts.step9s_historical_contingency_replay_v1 import (
    BASELINE_CANDIDATE_FILE,
    BASELINE_TRADE_FILE,
    PRICE_DB,
    TAXONOMY_FILE,
)


EXPERIMENT_ID = "STEP9S_HISTORICAL_CONTINGENCY_REPLAY_V1"
FREEZE_VERSION = "STEP9S_HISTORICAL_OUTPUT_AUDIT_FREEZE_V1_2026_07_28"
EXPECTED_REGIMES = {
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
EXPECTED_OUTPUT_NAMES = (
    "step9s_assignment_registry.csv",
    "step9s_session_assignments.csv",
    "step9s_natural_trades.csv",
    "step9s_mandatory_coverage_trades.csv",
    "step9s_all_trades.csv",
    "step9s_performance.csv",
    "step9s_audit.csv",
    "step9s_source_hashes.json",
    "step9s_summary.csv",
)
EXPECTED_SUMMARY = {
    "sessions": 60,
    "regimes": 9,
    "natural_trades": 59,
    "natural_sessions_with_trades": 38,
    "mandatory_coverage_trades": 60,
    "mandatory_coverage_sessions": 60,
    "complete_trade_coverage_rate": 1.0,
    "natural_net_pnl_sek": 39.577580,
    "mandatory_coverage_net_pnl_sek": -46.896768,
}
FLOAT_TOLERANCE = 1e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _truthy(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _check_close(actual: float, expected: float, tolerance: float = FLOAT_TOLERANCE) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance)


def _load_outputs(output_dir: Path) -> dict[str, Any]:
    missing = [name for name in EXPECTED_OUTPUT_NAMES if not (output_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing Step 9S output files: {missing}")
    return {
        "registry": pd.read_csv(output_dir / "step9s_assignment_registry.csv"),
        "assignments": pd.read_csv(output_dir / "step9s_session_assignments.csv"),
        "natural": pd.read_csv(output_dir / "step9s_natural_trades.csv"),
        "coverage": pd.read_csv(output_dir / "step9s_mandatory_coverage_trades.csv"),
        "all_trades": pd.read_csv(output_dir / "step9s_all_trades.csv"),
        "performance": pd.read_csv(output_dir / "step9s_performance.csv"),
        "audit": pd.read_csv(output_dir / "step9s_audit.csv"),
        "source_hashes": json.loads((output_dir / "step9s_source_hashes.json").read_text(encoding="utf-8")),
        "summary": pd.read_csv(output_dir / "step9s_summary.csv"),
    }


def _source_path_map(project_root: Path, registry: pd.DataFrame) -> dict[str, Path]:
    mapping = {
        "taxonomy": TAXONOMY_FILE,
        "baseline_candidates": BASELINE_CANDIDATE_FILE,
        "baseline_trades": BASELINE_TRADE_FILE,
        "price_db": PRICE_DB,
    }
    for row in registry.itertuples(index=False):
        mapping[f"natural_{row.regime}"] = legacy_output_path(str(row.natural_source_file))
    return mapping


def _protected_paths(project_root: Path, source_paths: dict[str, Path]) -> list[Path]:
    candidates = list(source_paths.values()) + [
        project_root / "RegimeTrading/scripts/step9s_historical_contingency_replay_v1.py",
        project_root / "config/step9s_historical_contingency_replay_v1.json",
        resolve_stage_path("step9i"),
        resolve_stage_path("step9l"),
        resolve_stage_path("prices"),
    ]
    result: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        path = path.resolve()
        if path.is_file() and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _performance_recompute(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (book, regime), group in trades.groupby(["trade_book", "primary_regime"], dropna=False):
        pnl = pd.to_numeric(group["net_pnl_sek"], errors="coerce")
        gains = pnl[pnl > 0].sum()
        losses = -pnl[pnl < 0].sum()
        rows.append(
            {
                "trade_book": book,
                "primary_regime": regime,
                "sessions_with_trades": int(group["date"].astype(str).nunique()),
                "trades": int(len(group)),
                "winning_trades": int((pnl > 0).sum()),
                "losing_or_nonpositive_trades": int((pnl <= 0).sum()),
                "win_rate": float((pnl > 0).mean()),
                "net_pnl_sek": float(pnl.sum()),
                "average_pnl_sek": float(pnl.mean()),
                "median_pnl_sek": float(pnl.median()),
                "profit_factor": float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else np.nan),
            }
        )
    return pd.DataFrame(rows).sort_values(["trade_book", "primary_regime"]).reset_index(drop=True)


def _performance_matches(recomputed: pd.DataFrame, published: pd.DataFrame) -> bool:
    fields = [
        "trade_book",
        "primary_regime",
        "sessions_with_trades",
        "trades",
        "winning_trades",
        "losing_or_nonpositive_trades",
        "win_rate",
        "net_pnl_sek",
        "average_pnl_sek",
        "median_pnl_sek",
        "profit_factor",
    ]
    left = recomputed[fields].copy()
    right = published[fields].sort_values(["trade_book", "primary_regime"]).reset_index(drop=True)
    if len(left) != len(right):
        return False
    for col in ["trade_book", "primary_regime"]:
        if not left[col].astype(str).equals(right[col].astype(str)):
            return False
    for col in ["sessions_with_trades", "trades", "winning_trades", "losing_or_nonpositive_trades"]:
        if not pd.to_numeric(left[col]).equals(pd.to_numeric(right[col])):
            return False
    for col in ["win_rate", "net_pnl_sek", "average_pnl_sek", "median_pnl_sek", "profit_factor"]:
        a = pd.to_numeric(left[col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(right[col], errors="coerce").to_numpy(dtype=float)
        finite = np.isfinite(a) & np.isfinite(b)
        if not np.allclose(a[finite], b[finite], rtol=0.0, atol=FLOAT_TOLERANCE):
            return False
        if not np.array_equal(np.isposinf(a), np.isposinf(b)):
            return False
        if not np.array_equal(np.isnan(a), np.isnan(b)):
            return False
    return True


def _geometry_checks(trades: pd.DataFrame) -> tuple[bool, bool, bool]:
    entry = pd.to_datetime(trades["entry_time"], errors="coerce")
    exit_ = pd.to_datetime(trades["exit_time"], errors="coerce")
    timestamps_valid = bool(entry.notna().all() and exit_.notna().all() and (exit_ >= entry).all())
    same_session = bool((entry.dt.strftime("%Y-%m-%d") == trades["date"].astype(str)).all() and (exit_.dt.strftime("%Y-%m-%d") == trades["date"].astype(str)).all())

    singles = trades[trades["idea_type"].astype(str).eq("SINGLE")].copy()
    single_valid = True
    if not singles.empty:
        direction = singles["direction"].astype(str).str.upper()
        entry_price = pd.to_numeric(singles["entry_price"], errors="coerce")
        stop = pd.to_numeric(singles["stop_price"], errors="coerce")
        target = pd.to_numeric(singles["target_price"], errors="coerce")
        long_ok = direction.eq("LONG") & (stop < entry_price) & (entry_price < target)
        short_ok = direction.eq("SHORT") & (target < entry_price) & (entry_price < stop)
        single_valid = bool((long_ok | short_ok).all())

    pairs = trades[trades["idea_type"].astype(str).eq("PAIR")].copy()
    pair_valid = True
    if not pairs.empty:
        long_ticker = pairs["long_ticker"].astype(str)
        short_ticker = pairs["short_ticker"].astype(str)
        long_entry = pd.to_numeric(pairs["pair_entry_long_price"], errors="coerce")
        short_entry = pd.to_numeric(pairs["pair_entry_short_price"], errors="coerce")
        stop_ret = pd.to_numeric(pairs["pair_stop_return"], errors="coerce")
        target_ret = pd.to_numeric(pairs["pair_target_return"], errors="coerce")
        pair_valid = bool(
            long_ticker.ne("").all()
            and short_ticker.ne("").all()
            and long_ticker.ne(short_ticker).all()
            and np.isfinite(long_entry).all()
            and np.isfinite(short_entry).all()
            and (long_entry > 0).all()
            and (short_entry > 0).all()
            and (stop_ret < 0).all()
            and (target_ret > 0).all()
        )
    return timestamps_valid and same_session, single_valid, pair_valid


def _latest_boundary_manifest(project_root: Path) -> Path | None:
    matches = sorted((project_root / "logs").glob("pre_step9s_boundary_freeze_*.csv")) if (project_root / "logs").exists() else []
    return matches[-1] if matches else None


def audit_and_freeze(project_root: Path, freeze_root: Path | None = None) -> dict[str, Any]:
    project_root = project_root.resolve()
    output_dir = resolve_stage_output_dir("step9s")
    outputs = _load_outputs(output_dir)
    registry = outputs["registry"]
    assignments = outputs["assignments"]
    natural = outputs["natural"]
    coverage = outputs["coverage"]
    all_trades = outputs["all_trades"]
    performance = outputs["performance"]
    published_audit = outputs["audit"]
    summary = outputs["summary"]

    source_paths = _source_path_map(project_root, registry)
    missing_sources = sorted(str(path) for path in source_paths.values() if not path.is_file())
    if missing_sources:
        raise RuntimeError(f"Missing Step 9S source files: {missing_sources}")

    protected = _protected_paths(project_root, source_paths)
    protected_before = {path: sha256(path) for path in protected}

    taxonomy = pd.read_csv(source_paths["taxonomy"])
    taxonomy["date"] = taxonomy["date"].astype(str)
    taxonomy_map = taxonomy.set_index("date")["primary_regime"].astype(str).to_dict()
    registry_strategy = registry.set_index("regime")["natural_strategy_id"].astype(str).to_dict()
    registry_control = registry.set_index("regime")["mandatory_control_id"].astype(str).to_dict()

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    add("nine_unique_regimes", len(registry) == 9 and registry["regime"].is_unique and set(registry["regime"].astype(str)) == EXPECTED_REGIMES, f"rows={len(registry)}")
    add("registry_router_inactive", not _truthy(registry["router_active"]).any() and not _truthy(registry["orders_sent"]).any(), "registry router/order flags false")
    add("one_assignment_per_taxonomy_session", len(assignments) == taxonomy["date"].nunique() and assignments["date"].astype(str).is_unique and set(assignments["date"].astype(str)) == set(taxonomy["date"]), f"assignments={len(assignments)} taxonomy_sessions={taxonomy['date'].nunique()}")
    assignment_regime_match = all(taxonomy_map.get(str(row.date)) == str(row.primary_regime) for row in assignments.itertuples(index=False))
    add("assignment_regime_matches_taxonomy", assignment_regime_match, "date-to-regime crosswalk")
    assignment_strategy_match = all(registry_strategy.get(str(row.primary_regime)) == str(row.assigned_strategy_id) for row in assignments.itertuples(index=False))
    assignment_control_match = all(registry_control.get(str(row.primary_regime)) == str(row.coverage_control_id) for row in assignments.itertuples(index=False))
    add("assignment_strategy_matches_registry", assignment_strategy_match, "natural strategy IDs")
    add("assignment_control_matches_registry", assignment_control_match, "coverage control IDs")

    coverage_counts = coverage.groupby(coverage["date"].astype(str)).size()
    add("exactly_one_mandatory_trade_per_session", len(coverage) == len(assignments) and coverage_counts.eq(1).all() and set(coverage_counts.index) == set(assignments["date"].astype(str)), f"coverage_trades={len(coverage)}")
    add("all_nine_regimes_have_coverage_trades", set(coverage["primary_regime"].astype(str)) == EXPECTED_REGIMES, f"covered_regimes={coverage['primary_regime'].nunique()}")
    add("coverage_ids_unique", coverage["trade_id"].astype(str).is_unique, f"unique={coverage['trade_id'].nunique()}")
    add("natural_ids_unique", natural["trade_id"].astype(str).is_unique, f"unique={natural['trade_id'].nunique()}")
    add("combined_ids_unique", all_trades["trade_id"].astype(str).is_unique, f"unique={all_trades['trade_id'].nunique()}")

    expected_combined_ids = set(natural["trade_id"].astype(str)) | set(coverage["trade_id"].astype(str))
    add("combined_book_is_exact_union", len(all_trades) == len(natural) + len(coverage) and set(all_trades["trade_id"].astype(str)) == expected_combined_ids, f"all={len(all_trades)} natural={len(natural)} coverage={len(coverage)}")
    add("trade_books_separated", set(natural["trade_book"].astype(str)) == {"NATURAL_STRATEGY_BOOK"} and set(coverage["trade_book"].astype(str)) == {"MANDATORY_COVERAGE_CONTROL_BOOK"}, "book labels")
    add("trade_labels_separated", set(natural["trade_label"].astype(str)) == {"NATURAL_TRIGGER_TRADE"} and set(coverage["trade_label"].astype(str)) == {"MANDATORY_COVERAGE_CONTROL_TRADE"}, "trade labels")

    natural_regime_match = all(taxonomy_map.get(str(row.date)) == str(row.primary_regime) for row in natural.itertuples(index=False))
    coverage_regime_match = all(taxonomy_map.get(str(row.date)) == str(row.primary_regime) for row in coverage.itertuples(index=False))
    add("all_trade_regimes_match_taxonomy", natural_regime_match and coverage_regime_match, "natural and mandatory books")
    natural_strategy_match = all(registry_strategy.get(str(row.primary_regime)) == str(row.assigned_strategy_id) for row in natural.itertuples(index=False))
    coverage_strategy_match = all(registry_strategy.get(str(row.primary_regime)) == str(row.assigned_strategy_id) for row in coverage.itertuples(index=False))
    coverage_control_match = all(registry_control.get(str(row.primary_regime)) == str(row.coverage_control_id) for row in coverage.itertuples(index=False))
    add("all_trade_assignments_match_registry", natural_strategy_match and coverage_strategy_match and coverage_control_match, "strategy/control crosswalk")

    numeric_fields = ["gross_return", "notional_sek", "cost_sek", "net_pnl_sek"]
    finite_natural = all(np.isfinite(pd.to_numeric(natural[col], errors="coerce")).all() for col in numeric_fields)
    finite_coverage = all(np.isfinite(pd.to_numeric(coverage[col], errors="coerce")).all() for col in numeric_fields)
    add("finite_trade_economics", finite_natural and finite_coverage, ",".join(numeric_fields))
    add("positive_notionals_nonnegative_costs", (pd.to_numeric(all_trades["notional_sek"], errors="coerce") > 0).all() and (pd.to_numeric(all_trades["cost_sek"], errors="coerce") >= 0).all(), "all trades")

    natural_time, natural_single, natural_pair = _geometry_checks(natural)
    coverage_time, coverage_single, coverage_pair = _geometry_checks(coverage)
    add("valid_entry_exit_timestamps", natural_time and coverage_time, "same session and exit >= entry")
    add("valid_single_trade_geometry", natural_single and coverage_single, "LONG stop<entry<target; SHORT target<entry<stop")
    add("valid_pair_trade_geometry", natural_pair and coverage_pair, "distinct legs and valid pair thresholds")
    coverage_entry_clock = pd.to_datetime(coverage["entry_time"], errors="coerce").dt.strftime("%H:%M")
    add("mandatory_entries_exactly_0945", coverage_entry_clock.eq("09:45").all(), f"entry_clocks={sorted(coverage_entry_clock.dropna().unique().tolist())}")

    point_in_time = _truthy(all_trades["point_in_time_pass"]).all()
    execution_pass = _truthy(all_trades["execution_invariant_pass"]).all()
    no_route = not _truthy(all_trades["router_active"]).any()
    no_orders = not _truthy(all_trades["order_sent"]).any()
    add("all_point_in_time_checks_pass", point_in_time, "published trade flags")
    add("all_execution_invariants_pass", execution_pass, "published trade flags")
    add("router_inactive_and_no_orders", no_route and no_orders, "all trade rows")
    add("published_internal_audit_passes", _truthy(published_audit["passed"]).all(), f"checks={len(published_audit)}")

    recomputed_performance = _performance_recompute(all_trades)
    add("performance_table_reconciles", _performance_matches(recomputed_performance, performance), f"rows={len(performance)}")
    natural_pnl = float(pd.to_numeric(natural["net_pnl_sek"], errors="coerce").sum())
    coverage_pnl = float(pd.to_numeric(coverage["net_pnl_sek"], errors="coerce").sum())
    summary_row = summary.iloc[0]
    summary_checks = {
        "sessions": int(summary_row["sessions"]) == EXPECTED_SUMMARY["sessions"],
        "regimes": int(summary_row["regimes"]) == EXPECTED_SUMMARY["regimes"],
        "natural_trades": int(summary_row["natural_trades"]) == EXPECTED_SUMMARY["natural_trades"],
        "natural_sessions_with_trades": int(summary_row["natural_sessions_with_trades"]) == EXPECTED_SUMMARY["natural_sessions_with_trades"],
        "mandatory_coverage_trades": int(summary_row["mandatory_coverage_trades"]) == EXPECTED_SUMMARY["mandatory_coverage_trades"],
        "mandatory_coverage_sessions": int(summary_row["mandatory_coverage_sessions"]) == EXPECTED_SUMMARY["mandatory_coverage_sessions"],
        "complete_trade_coverage_rate": _check_close(summary_row["complete_trade_coverage_rate"], EXPECTED_SUMMARY["complete_trade_coverage_rate"]),
        "natural_net_pnl_sek": _check_close(summary_row["natural_net_pnl_sek"], natural_pnl) and _check_close(natural_pnl, EXPECTED_SUMMARY["natural_net_pnl_sek"]),
        "mandatory_coverage_net_pnl_sek": _check_close(summary_row["mandatory_coverage_net_pnl_sek"], coverage_pnl) and _check_close(coverage_pnl, EXPECTED_SUMMARY["mandatory_coverage_net_pnl_sek"]),
    }
    add("published_summary_matches_frozen_result", all(summary_checks.values()), json.dumps(summary_checks, sort_keys=True))

    actual_source_hashes = {key: sha256(path) for key, path in source_paths.items()}
    add("source_hash_manifest_matches_live_sources", outputs["source_hashes"] == actual_source_hashes, f"sources={len(actual_source_hashes)}")

    with tempfile.TemporaryDirectory(prefix="step9s_freeze_replay_") as temp_name:
        temp_dir = Path(temp_name)
        import sys
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from RegimeTrading.scripts import step9s_historical_contingency_replay_v1 as step9s
        rerun = step9s.run_replay(project_root / "data", temp_dir)
        deterministic = all((output_dir / name).read_bytes() == (temp_dir / name).read_bytes() for name in EXPECTED_OUTPUT_NAMES)
        add("replay_is_byte_deterministic", deterministic, f"rerun_sessions={rerun['sessions']}")

    audit_df = pd.DataFrame(checks)
    failures = audit_df.loc[~audit_df["passed"]]
    if not failures.empty:
        raise RuntimeError("Step 9S historical output audit failed: " + "; ".join(f"{row.check}: {row.detail}" for row in failures.itertuples(index=False)))

    protected_after_replay = {path: sha256(path) for path in protected}
    if protected_before != protected_after_replay:
        changed = [str(path) for path in protected if protected_before[path] != protected_after_replay[path]]
        raise RuntimeError(f"Protected files changed during audit replay: {changed}")

    manifest_paths: list[tuple[str, Path]] = []
    manifest_paths.extend(("STEP9S_OUTPUT", output_dir / name) for name in EXPECTED_OUTPUT_NAMES)
    unique_source_paths = sorted(set(source_paths.values()), key=lambda p: str(p))
    manifest_paths.extend(("REPLAY_SOURCE", path) for path in unique_source_paths)
    manifest_paths.extend(
        [
            ("STEP9S_CODE", project_root / "RegimeTrading/scripts/step9s_historical_contingency_replay_v1.py"),
            ("STEP9S_CONFIG", project_root / "config/step9s_historical_contingency_replay_v1.json"),
        ]
    )
    boundary = _latest_boundary_manifest(project_root)
    if boundary is not None:
        manifest_paths.append(("PRE_STEP9S_BOUNDARY_CONTEXT", boundary))

    manifest_rows = []
    for role, path in manifest_paths:
        relative = path.resolve().relative_to(project_root).as_posix()
        stat = path.stat()
        manifest_rows.append(
            {
                "role": role,
                "relative_path": relative,
                "size_bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "sha256": sha256(path),
            }
        )
    manifest_df = pd.DataFrame(manifest_rows).sort_values(["role", "relative_path"]).reset_index(drop=True)
    artifact_set_payload = "\n".join(f"{row.role}|{row.relative_path}|{row.sha256}" for row in manifest_df.itertuples(index=False))
    artifact_set_sha256 = hashlib.sha256(artifact_set_payload.encode("utf-8")).hexdigest()
    freeze_id = artifact_set_sha256[:16]

    if freeze_root is None:
        freeze_dir = output_dir / "freeze_v1" / freeze_id
    else:
        freeze_dir = freeze_root.resolve() / freeze_id
    freeze_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = freeze_dir / "step9s_historical_output_freeze_manifest.csv"
    audit_path = freeze_dir / "step9s_historical_output_audit.csv"
    regime_summary_path = freeze_dir / "step9s_historical_regime_book_summary.csv"
    observations_path = freeze_dir / "step9s_historical_research_observations.csv"
    summary_path = freeze_dir / "step9s_historical_output_freeze_summary.json"

    regime_summary = _performance_recompute(all_trades)
    exact_overlap_keys = [
        "date", "primary_regime", "idea_type", "direction", "ticker", "paired_ticker",
        "long_ticker", "short_ticker", "entry_time", "exit_time", "net_pnl_sek",
    ]
    overlaps = natural.merge(coverage, on=exact_overlap_keys, how="inner", suffixes=("_natural", "_coverage"))
    observations = pd.DataFrame(
        [
            {
                "observation": "RETROSPECTIVE_ASSEMBLED_NATURAL_BOOK",
                "severity": "RESEARCH_INTERPRETATION",
                "detail": "Natural-book P&L combines frozen historical research outputs selected across multiple prior studies; it is not unseen prospective performance.",
            },
            {
                "observation": "REGIME_NOTIONALS_DIFFER",
                "severity": "RESEARCH_INTERPRETATION",
                "detail": "Mandatory-control notional varies by regime (250 to 1000 SEK); raw regime P&L is not equal-exposure performance.",
            },
            {
                "observation": "CROSS_BOOK_EXACT_OVERLAPS",
                "severity": "EXPECTED_TWO_BOOK_BEHAVIOR",
                "detail": f"{len(overlaps)} natural/control trade records are economically identical and remain intentionally separated by book labels.",
            },
            {
                "observation": "MANDATORY_CONTROL_NEGATIVE_AGGREGATE",
                "severity": "RESEARCH_RESULT",
                "detail": f"Mandatory-control book net P&L is {coverage_pnl:.6f} SEK; this is knowledge-producing control evidence, not a gate failure.",
            },
        ]
    )

    manifest_df.to_csv(manifest_path, index=False)
    audit_df.to_csv(audit_path, index=False)
    regime_summary.to_csv(regime_summary_path, index=False)
    observations.to_csv(observations_path, index=False)

    freeze_summary = {
        "freeze_version": FREEZE_VERSION,
        "freeze_id": freeze_id,
        "artifact_set_sha256": artifact_set_sha256,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": EXPERIMENT_ID,
        "historical_output_files": len(EXPECTED_OUTPUT_NAMES),
        "manifest_rows": len(manifest_df),
        "blocking_checks": len(audit_df),
        "blocking_checks_passed": int(audit_df["passed"].sum()),
        "sessions": int(summary_row["sessions"]),
        "regimes": int(summary_row["regimes"]),
        "natural_trades": int(summary_row["natural_trades"]),
        "natural_sessions_with_trades": int(summary_row["natural_sessions_with_trades"]),
        "natural_net_pnl_sek": natural_pnl,
        "mandatory_coverage_trades": int(summary_row["mandatory_coverage_trades"]),
        "mandatory_coverage_sessions": int(summary_row["mandatory_coverage_sessions"]),
        "mandatory_coverage_net_pnl_sek": coverage_pnl,
        "complete_trade_coverage_rate": float(summary_row["complete_trade_coverage_rate"]),
        "exact_cross_book_overlaps": int(len(overlaps)),
        "protected_files_byte_for_byte_unchanged": True,
        "replay_byte_deterministic": True,
        "router_active": False,
        "orders_sent": False,
    }
    summary_path.write_text(json.dumps(freeze_summary, indent=2, sort_keys=True), encoding="utf-8")

    protected_final = {path: sha256(path) for path in protected}
    if protected_before != protected_final:
        changed = [str(path) for path in protected if protected_before[path] != protected_final[path]]
        shutil.rmtree(freeze_dir, ignore_errors=True)
        raise RuntimeError(f"Protected files changed while writing freeze artifacts: {changed}")

    return {
        **freeze_summary,
        "freeze_directory": str(freeze_dir),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and freeze Step 9S historical contingency replay outputs.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--freeze-root", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = audit_and_freeze(args.project_root, args.freeze_root)
    print("STEP9S_HISTORICAL_OUTPUT_AUDIT_FREEZE_V1: PASSED")
    print(f"Freeze ID: {result['freeze_id']}")
    print(f"Sessions/regimes: {result['sessions']}/{result['regimes']}")
    print(f"Natural book: {result['natural_trades']} trades / {result['natural_sessions_with_trades']} sessions / {result['natural_net_pnl_sek']:.6f} SEK")
    print(f"Mandatory coverage book: {result['mandatory_coverage_trades']} trades / {result['mandatory_coverage_sessions']} sessions / {result['mandatory_coverage_net_pnl_sek']:.6f} SEK")
    print(f"Complete trade coverage: {result['complete_trade_coverage_rate']:.1%}")
    print(f"Blocking checks: {result['blocking_checks_passed']}/{result['blocking_checks']} passed")
    print(f"Exact cross-book overlaps: {result['exact_cross_book_overlaps']} (labelled and retained)")
    print(f"Artifact-set SHA-256: {result['artifact_set_sha256']}")
    print(f"Freeze directory: {result['freeze_directory']}")
    print("PROTECTED REAL FILES: BYTE-FOR-BYTE UNCHANGED")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
