"""Run a research-only transaction-cost stress test for Step 9R.

The selector, candidate universe, and historical outcomes are unchanged. The
analysis reconstructs gross P&L and the already-realized baseline cost burden
from the Step 9R candidate-outcome export, then applies a cost multiplier to
the same V3-selected primary rows. It is deliberately read-only with respect
to canonical data and never enables routing or orders.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTCOME_FILE = PROJECT_ROOT / "data/outputs/research/step9r/step9r_v1_candidate_outcomes.csv"
SUMMARY_FILE = PROJECT_ROOT / "data/outputs/research/step9r/step9r_v1_summary.csv"
CONFIG_FILE = PROJECT_ROOT / "config/step9r_candidate_ranking_research_v1.json"
REGISTRY_FILE = PROJECT_ROOT / "config/stage_registry.json"
PATHS_FILE = PROJECT_ROOT / "config/paths.json"
PRICE_DB = PROJECT_ROOT / "data/source/market/step9i_shadow_intraday_prices.db"

PRIMARY_ROLE = "PRIMARY_HYPOTHESIS"
LATEST_FEATURE_LABEL = "09:40"
MULTIPLIERS = (1.0, 1.5, 2.0, 3.0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float(row: dict[str, str], key: str) -> float | None:
    value = str(row.get(key, "")).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def _max_drawdown(daily: dict[str, float]) -> float:
    running = 0.0
    peak = 0.0
    drawdown = 0.0
    for session in sorted(daily):
        running += daily[session]
        peak = max(peak, running)
        drawdown = min(drawdown, running - peak)
    return float(drawdown)


def run(output_path: Path | None = None, as_of: str | None = None) -> dict[str, Any]:
    if as_of is None:
        as_of = date.today().isoformat()
    required = (OUTCOME_FILE, SUMMARY_FILE, CONFIG_FILE, REGISTRY_FILE, PATHS_FILE, PRICE_DB)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing baseline inputs: " + ", ".join(missing))

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if config.get("router_active") is not False or config.get("orders_enabled") is not False:
        raise RuntimeError("Step 9R configuration is not research-only.")

    rows: list[dict[str, Any]] = []
    with OUTCOME_FILE.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("test_role") != PRIMARY_ROLE or not _bool(row.get("selected_by_v3", "")):
                continue
            if not _bool(row.get("model_eligible", "")) or not _bool(row.get("point_in_time_pass", "")):
                raise RuntimeError("Selected Step 9R primary row failed a point-in-time/model-eligibility contract.")
            if str(row.get("max_router_source_label", "")) > LATEST_FEATURE_LABEL:
                raise RuntimeError("Selected Step 9R primary row uses a post-cutoff feature label.")

            gross_return = _float(row, "gross_return")
            notional = _float(row, "risk_capped_notional_sek")
            net_pnl = _float(row, "risk_capped_net_pnl_sek")
            if gross_return is None or notional is None or net_pnl is None:
                continue
            gross_pnl = gross_return * notional
            baseline_cost = gross_pnl - net_pnl
            rows.append(
                {
                    "date": str(row["date"]),
                    "ticker": str(row["ticker"]),
                    "gross_pnl_sek": gross_pnl,
                    "baseline_cost_sek": baseline_cost,
                    "baseline_net_pnl_sek": net_pnl,
                }
            )

    if not rows:
        raise RuntimeError("No selected primary Step 9R outcomes were available for stress testing.")

    daily_baseline: dict[str, float] = defaultdict(float)
    daily_stress: dict[float, dict[str, float]] = {
        multiplier: defaultdict(float) for multiplier in MULTIPLIERS
    }
    metrics: dict[str, dict[str, float]] = {}
    for multiplier in MULTIPLIERS:
        stress_pnl = sum(
            row["gross_pnl_sek"] - multiplier * row["baseline_cost_sek"] for row in rows
        )
        daily = daily_stress[multiplier]
        for row in rows:
            daily[row["date"]] += row["gross_pnl_sek"] - multiplier * row["baseline_cost_sek"]
        metrics[str(multiplier)] = {
            "net_pnl_sek": float(stress_pnl),
            "positive_sessions": float(sum(value > 0 for value in daily.values())),
            "sessions": float(len(daily)),
            "max_drawdown_sek": _max_drawdown(daily),
        }
        if multiplier == 1.0:
            daily_baseline.update(daily)

    for row in rows:
        daily_baseline[row["date"]] += 0.0

    source_hashes = {
        _relative(path): _sha256(path)
        for path in required
    }
    result: dict[str, Any] = {
        "analysis": "STEP9R_SELECTED_PRIMARY_COST_STRESS_V1",
        "as_of": as_of,
        "hypothesis": "The Step 9R V3-selected primary research book remains positive when its realized baseline transaction-cost burden is doubled.",
        "selection_rule_unchanged": True,
        "research_only": True,
        "router_active": False,
        "orders_enabled": False,
        "selector_model": config.get("selector_model"),
        "effective_start_date": "2026-05-25",
        "effective_end_date": "2026-07-27",
        "selected_primary_triggered_rows": len(rows),
        "selected_primary_sessions": len({row["date"] for row in rows}),
        "baseline_gross_pnl_sek": float(sum(row["gross_pnl_sek"] for row in rows)),
        "baseline_cost_burden_sek": float(sum(row["baseline_cost_sek"] for row in rows)),
        "scenarios": metrics,
        "hypothesis_result": "SUPPORTED" if metrics["2.0"]["net_pnl_sek"] > 0 else "NOT_SUPPORTED",
        "source_hashes": source_hashes,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data/outputs/research/step9r_cost_stress/step9r_cost_stress_20260801.json",
    )
    args = parser.parse_args()
    result = run(args.output, args.as_of)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
