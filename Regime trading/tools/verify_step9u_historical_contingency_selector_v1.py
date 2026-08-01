from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

# When this verifier is launched as ``python tools\verify_...py``, Python
# places the tools directory rather than the project root at sys.path[0].
# Add the project root explicitly before importing the RegimeTrading package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path
from RegimeTrading.scripts import step9u_historical_contingency_selector_v1 as step9u


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    protected = [
        resolve_stage_output_dir("step9t") / "step9t_session_transitions.csv",
        resolve_stage_output_dir("step9t") / "step9t_ticker_archetypes.csv",
        resolve_stage_output_dir("step9t") / "step9t_ticker_outcomes.csv",
        step9u.STEP9T_FREEZE_MANIFEST,
        step9u.STEP9S_SUMMARY_FILE,
        resolve_stage_path("step9i"),
        resolve_stage_path("step9l"),
    ]
    protected = [path for path in protected if path.is_file()]
    before = {path: _hash(path) for path in protected}

    with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
        first_dir = Path(first_temp) / "output"
        second_dir = Path(second_temp) / "output"
        first = step9u.run_historical_replay(output_dir=first_dir)
        second = step9u.run_historical_replay(output_dir=second_dir)
        first_files = sorted(path.name for path in first_dir.iterdir() if path.is_file())
        second_files = sorted(path.name for path in second_dir.iterdir() if path.is_file())
        if first_files != second_files:
            raise RuntimeError("Step 9U deterministic replay file sets differ.")
        for name in first_files:
            if _hash(first_dir / name) != _hash(second_dir / name):
                raise RuntimeError(f"Step 9U deterministic replay mismatch: {name}")

    after = {path: _hash(path) for path in protected}
    if before != after:
        changed = [str(path) for path in protected if before[path] != after[path]]
        raise RuntimeError(f"Protected source files changed: {changed}")

    summary = first["summary"]
    candidates = first["candidates"]
    selected = first["selected_outcomes"]
    audit = first["audit"]
    performance = first["performance"]
    regret = first["regret"]

    if len(audit) != 30 or not bool(audit["passed"].all()):
        raise RuntimeError("Step 9U independent audit is not 30/30.")
    if len(regret) != 62 or not bool(regret["selection_regret_sek"].ge(-1e-12).all()):
        raise RuntimeError("Step 9U feasible-oracle opportunity cost is invalid.")
    if not bool(regret["oracle_positions"].between(0, 2).all()):
        raise RuntimeError("Step 9U oracle position count is invalid.")
    if not bool(regret["oracle_contract"].eq("UP_TO_2_POSITIVE_MAX_1_PER_SECTOR_V1").all()):
        raise RuntimeError("Step 9U oracle contract label is invalid.")
    if abs(float(regret["selection_regret_sek"].sum()) - 354.76753198836883) > 1e-9:
        raise RuntimeError("Unexpected Step 9U feasible-oracle opportunity cost.")
    if int(summary["sessions"]) != 62 or int(summary["regimes"]) != 9 or int(summary["transition_states"]) != 6:
        raise RuntimeError("Unexpected Step 9U session/regime/transition counts.")
    if len(candidates) != 970 or int(candidates["selection_eligible"].sum()) != 158:
        raise RuntimeError("Unexpected Step 9U candidate counts.")
    if int(candidates["policy_action"].eq("BLOCKED_NEGATIVE_CONTROL").sum()) != 79:
        raise RuntimeError("Unexpected Step 9U blocked-control count.")
    if len(selected) != 73 or selected["session_date"].nunique() != 43:
        raise RuntimeError("Unexpected Step 9U selected counts.")
    complete = selected[selected["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE")]
    if len(complete) != 71:
        raise RuntimeError("Unexpected Step 9U completed selected outcomes.")
    if abs(float(complete["net_pnl_sek"].sum()) - 388.29973148050374) > 1e-9:
        raise RuntimeError("Unexpected Step 9U selected standardized P&L.")
    july28 = candidates[candidates["session_date"].astype(str).eq("2026-07-28")]
    if int(july28["selected"].sum()) != 0:
        raise RuntimeError("July 28 should have no historical Step 9U selection.")
    selected_perf = performance[performance["scope"].eq("SELECTED_PORTFOLIO")]
    if len(selected_perf) != 1:
        raise RuntimeError("Step 9U selected performance summary missing.")

    print("STEP9U_HISTORICAL_CONTINGENCY_SELECTOR_V1_VERIFICATION: PASSED")
    print(f"HISTORICAL_FREEZE_ID: {summary['historical_freeze_id']}")
    print(f"SESSIONS_REGIMES_TRANSITIONS: {summary['sessions']}/{summary['regimes']}/{summary['transition_states']}")
    print(f"DIRECTIONAL_CANDIDATE_ROWS: {len(candidates)}")
    print(f"SELECTABLE_CANDIDATES: {int(candidates['selection_eligible'].sum())}")
    print(f"BLOCKED_NEGATIVE_CONTROLS: {int(candidates['policy_action'].eq('BLOCKED_NEGATIVE_CONTROL').sum())}")
    print(f"SELECTED_CANDIDATES_SESSIONS: {len(selected)}/{selected['session_date'].nunique()}")
    print(f"SELECTED_COMPLETE_INCOMPLETE: {len(complete)}/{len(selected) - len(complete)}")
    print(f"SELECTED_NET_STANDARDIZED_PNL_SEK: {float(complete['net_pnl_sek'].sum()):.6f}")
    print("JULY28_SELECTIONS: 0")
    print("DETERMINISTIC_RERUN: PASSED")
    print("INDEPENDENT_AUDIT: 30/30 PASSED")
    print("FEASIBLE_ORACLE_REGRET: PASSED / 354.767532 SEK")
    print("PROTECTED REAL FILES: BYTE-FOR-BYTE UNCHANGED")
    print("MANDATORY CONTROL ACTIVE: FALSE")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
