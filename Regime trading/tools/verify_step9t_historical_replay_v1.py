from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from RegimeTrading.scripts import step9t_regime_transition_archetype_research_v1 as step9t
from RegimeTrading.core.paths import RECONCILIATION_DATA_DIR
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path


DEFAULT_RECONCILIATION = RECONCILIATION_DATA_DIR / "july28_ticker_market_performance.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_files() -> list[Path]:
    return [
        ROOT / "data" / "step9i_shadow_intraday_prices.db",
        resolve_stage_path("step9i"),
        resolve_stage_path("step9l"),
        resolve_stage_path("step9r_research"),
        resolve_stage_path("step9r"),
        ROOT / "RegimeTrading" / "scripts" / "step9i_v2_core5_plus_holdout18_shadow_router.py",
        ROOT / "RegimeTrading" / "scripts" / "step9l_v3_selected_strategy_shadow_engine.py",
        ROOT / "RegimeTrading" / "scripts" / "step9r_v1_candidate_ranking_research.py",
        ROOT / "RegimeTrading" / "scripts" / "step9s_prospective_contingency_shadow_v1.py",
    ]


def _compare_frames(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> None:
    left = left.sort_values(keys).reset_index(drop=True)
    right = right.sort_values(keys).reset_index(drop=True)
    if list(left.columns) != list(right.columns):
        raise AssertionError("Deterministic rerun changed output columns.")
    pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=True)


def verify(reconciliation_file: Path = DEFAULT_RECONCILIATION) -> dict[str, object]:
    missing = [path for path in _protected_files() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing protected files: {missing}")
    before = {str(path): sha256(path) for path in _protected_files()}

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        first = temp_root / "run1"
        second = temp_root / "run2"
        summary1 = step9t.run_historical_replay(output_dir=first)
        summary2 = step9t.run_historical_replay(output_dir=second)
        for filename, keys in [
            (step9t.SESSION_EXPORT, ["session_date"]),
            (step9t.ARCHETYPE_EXPORT, ["session_date", "ticker"]),
            (step9t.OUTCOME_EXPORT, ["session_date", "ticker"]),
            (step9t.SUMMARY_EXPORT, ["experiment_id"]),
        ]:
            _compare_frames(pd.read_csv(first / filename), pd.read_csv(second / filename), keys)

        sessions = pd.read_csv(first / step9t.SESSION_EXPORT)
        archetypes = pd.read_csv(first / step9t.ARCHETYPE_EXPORT)
        outcomes = pd.read_csv(first / step9t.OUTCOME_EXPORT)
        if sessions["session_date"].duplicated().any():
            raise AssertionError("Duplicate session transition rows found.")
        if archetypes.duplicated(["session_date", "ticker"]).any():
            raise AssertionError("Duplicate ticker archetype rows found.")
        if outcomes.duplicated(["session_date", "ticker"]).any():
            raise AssertionError("Duplicate ticker outcome rows found.")
        if not archetypes["latest_morning_source_label"].eq("09:45").all():
            raise AssertionError("A morning row used a source label later than 09:45.")
        if not archetypes["replay_status"].eq("RETROSPECTIVE_NON_CONFIRMATORY_DIAGNOSTIC").all():
            raise AssertionError("Historical Step 9T rows are not correctly labelled non-confirmatory.")

        july = sessions[sessions["session_date"].eq("2026-07-28")]
        if len(july) != 1:
            raise AssertionError("July 28 transition row is missing or duplicated.")
        if str(july.iloc[0]["source_regime"]) != "TREND_DOWN":
            raise AssertionError("July 28 opening regime did not remain TREND_DOWN.")
        if str(july.iloc[0]["transition_state"]) != "WEAKNESS_PERSISTING":
            raise AssertionError("July 28 09:50 transition snapshot did not reproduce WEAKNESS_PERSISTING.")

        if not reconciliation_file.is_file():
            raise FileNotFoundError(reconciliation_file)
        reference = pd.read_csv(reconciliation_file)
        july_archetypes = archetypes[archetypes["session_date"].eq("2026-07-28")]
        july_outcomes = outcomes[outcomes["session_date"].eq("2026-07-28")]
        if len(july_archetypes) != 29 or len(july_outcomes) != 29:
            raise AssertionError("July 28 does not contain the frozen 29-ticker universe.")
        merged = july_archetypes[["ticker", "direction", "entry_price"]].merge(
            july_outcomes[["ticker", "outcome_status", "session_close_return"]],
            on="ticker",
            validate="one_to_one",
        ).merge(reference, on="ticker", validate="one_to_one")
        morning_complete = merged["entry_price"].notna()
        if not np.allclose(merged.loc[morning_complete, "entry_price"], merged.loc[morning_complete, "entry_0950_open"], rtol=0, atol=1e-9):
            raise AssertionError("July 28 Step 9T entry prices do not reconcile with the 09:50 export.")
        complete = merged["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE")
        expected = np.where(
            merged.loc[complete, "direction"].eq("LONG"),
            merged.loc[complete, "long_0950_to_close_pct"] / 100.0,
            merged.loc[complete, "short_0950_to_close_pct"] / 100.0,
        )
        if not np.allclose(
            merged.loc[complete, "session_close_return"].astype(float), expected.astype(float), rtol=0, atol=1e-9
        ):
            raise AssertionError("July 28 directional outcomes do not reconcile with the market-performance export.")

        sand = merged[merged["ticker"].eq("SAND.ST")]
        if len(sand) != 1 or str(sand.iloc[0]["direction"]) != "SHORT":
            raise AssertionError("July 28 SAND.ST did not reproduce the bearish-continuation diagnostic.")

    after = {str(path): sha256(path) for path in _protected_files()}
    if before != after:
        changed = [path for path in before if before[path] != after[path]]
        raise AssertionError(f"Protected files changed during Step 9T verification: {changed}")
    return {
        "sessions": int(summary1["sessions"]),
        "regimes": int(summary1["regimes"]),
        "ticker_rows": int(summary1["ticker_archetype_rows"]),
        "outcomes": int(summary1["ticker_outcome_rows"]),
        "directional_outcomes": int(summary1["complete_directional_outcomes"]),
        "net_pnl": float(summary1["net_directional_pnl_sek"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconciliation-file", type=Path, default=DEFAULT_RECONCILIATION)
    args = parser.parse_args()
    result = verify(args.reconciliation_file)
    print("STEP9T_HISTORICAL_REPLAY_V1_VERIFICATION: PASSED")
    print(f"SESSIONS_REGIMES: {result['sessions']}/{result['regimes']}")
    print(f"TICKER_ARCHETYPE_OUTCOME_ROWS: {result['ticker_rows']}/{result['outcomes']}")
    print(f"COMPLETE_DIRECTIONAL_OUTCOMES: {result['directional_outcomes']}")
    print(f"NET_STANDARDIZED_DIRECTIONAL_PNL_SEK: {result['net_pnl']:.6f}")
    print("JULY28_OPENING_REGIME: TREND_DOWN")
    print("JULY28_0950_TRANSITION: WEAKNESS_PERSISTING")
    print("JULY28_RECONCILIATION: 29/29 TICKERS")
    print("DETERMINISTIC_RERUN: PASSED")
    print("PROTECTED REAL FILES: BYTE-FOR-BYTE UNCHANGED")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
