from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from RegimeTrading.core.paths import DATA_DIR
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9k_high_dispersion_strategy_research as step9k


EXPERIMENT_ID = "STEP9L_SELECTED_STRATEGY_SHADOW_ENGINE_V1"
RESEARCH_STATUS = "SIMULATION_ONLY_PROSPECTIVE_SELECTED_STRATEGIES_NOT_ROUTER_ACTIVE"
CODE_VERSION = "STEP9L_SELECTED_STRATEGIES_V1_LOCKED_2026_07_26"
SHADOW_UNIVERSE_VERSION = "STEP9L_REGIME_SOURCE11_TRADABLE23_SELECTED3_GUARDRAILS2"

SHADOW_INTRADAY_DB = step9i.SHADOW_INTRADAY_DB
SHADOW_LEDGER_DB = DATA_DIR / "step9l_selected_strategy_shadow_ledger.db"

DECISION_BATCH_FILE = DATA_DIR / "step9l_shadow_decision_batches.csv"
DECISION_FILE = DATA_DIR / "step9l_shadow_decisions.csv"
OUTCOME_BATCH_FILE = DATA_DIR / "step9l_shadow_outcome_batches.csv"
OUTCOME_FILE = DATA_DIR / "step9l_shadow_outcomes.csv"
PERFORMANCE_FILE = DATA_DIR / "step9l_shadow_performance.csv"
MULTIPLE_TESTING_FILE = DATA_DIR / "step9l_shadow_multiple_testing.csv"
AUDIT_FILE = DATA_DIR / "step9l_shadow_audit.csv"
SUMMARY_FILE = DATA_DIR / "step9l_shadow_summary.csv"
CONTRACT_REGISTRY_FILE = DATA_DIR / "step9l_shadow_contract_registry.csv"
SEGMENTED_DECISION_FILE = DATA_DIR / "step9l_shadow_decisions_segmented.csv"
SEGMENTED_OUTCOME_FILE = DATA_DIR / "step9l_shadow_outcomes_segmented.csv"
SEGMENT_PERFORMANCE_FILE = DATA_DIR / "step9l_shadow_segment_performance.csv"
UNIVERSE_SUMMARY_FILE = DATA_DIR / "step9l_shadow_universe_summary.csv"
SELF_INFLUENCE_FILE = DATA_DIR / "step9l_core5_regime_sensitivity.csv"


# Frozen before the first Step 9L prospective observation. The three primary
# contracts are positive research strategies. The two guardrails are evaluated
# counterfactually and never create orders.
CONTRACTS = [
    {
        "contract_id": "L_VE_ALIGNED_CLOSE_CONFIRMED_ORB_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "VOLATILITY_EXPANSION",
        "base_challenger_id": "ORB_CONTINUATION_CLOSE_CONFIRMED_1R_V1",
        "cohort_id": "L_VE_GROUP_ALIGNED",
        "comparison_group": "L_SELECTED_POSITIVE_STRATEGIES",
        "ticker_relative_states": "ANY",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "During volatility expansion, a group-aligned stock continues only after a completed close beyond the strict opening range.",
        "economic_interpretation": "Alignment selects direction and close confirmation reduces false early entries.",
        "selection_status": "SELECTED_PROSPECTIVE_STRATEGY",
        "historical_source": "STEP9J_V2",
    },
    {
        "contract_id": "L_RLV_GROUP_ALIGNED_LAGGARD_DELAYED_REVERSAL_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "RANGE_LOW_VOL",
        "base_challenger_id": "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
        "cohort_id": "L_RLV_EARLY_LAGGARD_GROUP_ALIGNED",
        "comparison_group": "L_SELECTED_POSITIVE_STRATEGIES",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "A quiet-market early laggard reverses after delayed confirmation when its early move is aligned with its sector.",
        "economic_interpretation": "This reproduces the actual winning Step 9J cohort after correcting the old trade-direction alignment label.",
        "selection_status": "SELECTED_PROSPECTIVE_STRATEGY_LABEL_CORRECTED",
        "historical_source": "STEP9J_V2_SEMANTIC_ALIGNMENT_CORRECTION",
    },
    {
        "contract_id": "L_HD_CONTRARIAN_LAGGARD_MIDPOINT_CATCHUP_V1",
        "test_role": "PRIMARY_HYPOTHESIS",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": step9k.LAGGARD_CATCHUP_ID,
        "cohort_id": "L_HD_EARLY_LAGGARD_CONTRARIAN",
        "comparison_group": "L_SELECTED_POSITIVE_STRATEGIES",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "CONTRARIAN_TO_GROUP",
        "hypothesis": "A high-dispersion early laggard catches up after midpoint confirmation when its early move conflicts with its sector.",
        "economic_interpretation": "Prospective test of the recent isolated-laggard catch-up effect.",
        "selection_status": "PROSPECTIVE_CHALLENGER",
        "historical_source": "STEP9K",
    },
    {
        "contract_id": "L_HD_EARLY_LEADER_CONTINUATION_AVOID_V1",
        "test_role": "NEGATIVE_GUARDRAIL",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": "EARLY_MOVE_CONTINUATION_1_5R_V1",
        "cohort_id": "L_HD_EARLY_LEADER",
        "comparison_group": "L_HIGH_DISPERSION_GUARDRAILS",
        "ticker_relative_states": "EARLY_LEADER",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ANY",
        "hypothesis": "High-dispersion early leaders should not be chased with early continuation.",
        "economic_interpretation": "Counterfactual guardrail retained from Step 9I and reinforced in Step 9K.",
        "selection_status": "FROZEN_AVOIDANCE_GUARDRAIL",
        "historical_source": "STEP9I_V2_AND_STEP9K",
    },
    {
        "contract_id": "L_HD_ALIGNED_LAGGARD_CATCHUP_AVOID_V1",
        "test_role": "NEGATIVE_GUARDRAIL",
        "primary_regime": "HIGH_DISPERSION",
        "base_challenger_id": step9k.LAGGARD_CATCHUP_ID,
        "cohort_id": "L_HD_EARLY_LAGGARD_ALIGNED",
        "comparison_group": "L_HIGH_DISPERSION_GUARDRAILS",
        "ticker_relative_states": "EARLY_LAGGARD",
        "volatility_buckets": "ANY",
        "sector_alignment_states": "ALIGNED_WITH_GROUP",
        "hypothesis": "High-dispersion early laggards should not be traded for catch-up when their early weakness is confirmed by their sector.",
        "economic_interpretation": "Counterfactual guardrail discovered in Step 9K.",
        "selection_status": "FROZEN_AVOIDANCE_GUARDRAIL",
        "historical_source": "STEP9K",
    },
]
CONTRACT_BY_ID = {row["contract_id"]: row for row in CONTRACTS}
COMPARISONS: list[tuple[str, str, str, str]] = []


@contextmanager
def _patched_step9l_globals():
    """Temporarily install Step 9L contracts without mutating Step 9I V2."""

    step9i_names = [
        "EXPERIMENT_ID", "RESEARCH_STATUS", "CODE_VERSION", "SHADOW_UNIVERSE_VERSION",
        "SHADOW_INTRADAY_DB", "SHADOW_LEDGER_DB", "DECISION_BATCH_FILE", "DECISION_FILE",
        "OUTCOME_BATCH_FILE", "OUTCOME_FILE", "PERFORMANCE_FILE", "MULTIPLE_TESTING_FILE",
        "AUDIT_FILE", "SUMMARY_FILE", "CONTRACT_REGISTRY_FILE", "SEGMENTED_DECISION_FILE",
        "SEGMENTED_OUTCOME_FILE", "SEGMENT_PERFORMANCE_FILE", "UNIVERSE_SUMMARY_FILE",
        "SELF_INFLUENCE_FILE",
    ]
    old_step9i = {name: getattr(step9i, name) for name in step9i_names}

    step9h_names = ["EXPERIMENT_ID", "RESEARCH_STATUS", "CONTRACTS", "CONTRACT_BY_ID", "COMPARISONS"]
    old_step9h = {name: getattr(step9h, name) for name in step9h_names}

    step9g_names = ["CHALLENGER_BY_ID", "_single_candidates_for_challenger", "_intended_side"]
    old_step9g = {name: getattr(step9g, name) for name in step9g_names}

    challenger_map = dict(step9g.CHALLENGER_BY_ID)
    challenger_map[step9k.LAGGARD_CATCHUP_ID] = dict(step9k.LAGGARD_CATCHUP)
    original_dispatch = step9g._single_candidates_for_challenger
    original_intended_side = step9g._intended_side

    def dispatch(session, challenger, states, bars_lookup, trades, legs):
        if challenger["challenger_id"] == step9k.LAGGARD_CATCHUP_ID:
            return step9k._laggard_catchup_candidates(
                session, challenger, states, bars_lookup, trades, legs
            )
        return original_dispatch(session, challenger, states, bars_lookup, trades, legs)

    def intended_side(base_challenger_id: str, row: pd.Series | dict) -> str:
        if base_challenger_id in {
            "DELAYED_EARLY_MOVE_REVERSAL_1R_V1",
            step9k.LAGGARD_CATCHUP_ID,
        }:
            # The alignment filter describes the stock's early move relative to
            # its sector. The later trade itself is a reversal/catch-up trade.
            return step9k._early_move_side(row)
        return original_intended_side(base_challenger_id, row)

    try:
        replacements = {
            "EXPERIMENT_ID": EXPERIMENT_ID,
            "RESEARCH_STATUS": RESEARCH_STATUS,
            "CODE_VERSION": CODE_VERSION,
            "SHADOW_UNIVERSE_VERSION": SHADOW_UNIVERSE_VERSION,
            "SHADOW_INTRADAY_DB": SHADOW_INTRADAY_DB,
            "SHADOW_LEDGER_DB": SHADOW_LEDGER_DB,
            "DECISION_BATCH_FILE": DECISION_BATCH_FILE,
            "DECISION_FILE": DECISION_FILE,
            "OUTCOME_BATCH_FILE": OUTCOME_BATCH_FILE,
            "OUTCOME_FILE": OUTCOME_FILE,
            "PERFORMANCE_FILE": PERFORMANCE_FILE,
            "MULTIPLE_TESTING_FILE": MULTIPLE_TESTING_FILE,
            "AUDIT_FILE": AUDIT_FILE,
            "SUMMARY_FILE": SUMMARY_FILE,
            "CONTRACT_REGISTRY_FILE": CONTRACT_REGISTRY_FILE,
            "SEGMENTED_DECISION_FILE": SEGMENTED_DECISION_FILE,
            "SEGMENTED_OUTCOME_FILE": SEGMENTED_OUTCOME_FILE,
            "SEGMENT_PERFORMANCE_FILE": SEGMENT_PERFORMANCE_FILE,
            "UNIVERSE_SUMMARY_FILE": UNIVERSE_SUMMARY_FILE,
            "SELF_INFLUENCE_FILE": SELF_INFLUENCE_FILE,
        }
        for name, value in replacements.items():
            setattr(step9i, name, value)

        step9h.EXPERIMENT_ID = EXPERIMENT_ID
        step9h.RESEARCH_STATUS = RESEARCH_STATUS
        step9h.CONTRACTS = CONTRACTS
        step9h.CONTRACT_BY_ID = CONTRACT_BY_ID
        step9h.COMPARISONS = COMPARISONS

        step9g.CHALLENGER_BY_ID = challenger_map
        step9g._single_candidates_for_challenger = dispatch
        step9g._intended_side = intended_side
        yield
    finally:
        for name, value in old_step9g.items():
            setattr(step9g, name, value)
        for name, value in old_step9h.items():
            setattr(step9h, name, value)
        for name, value in old_step9i.items():
            setattr(step9i, name, value)


def _parse_stockholm_datetime(value: str | None):
    return step9i._parse_stockholm_datetime(value)


def _target_date(value: str | None, now):
    return step9i._target_date(value, now)


def load_shadow_prices(db_path: Path = SHADOW_INTRADAY_DB) -> pd.DataFrame:
    return step9i.load_shadow_prices(db_path)


def build_morning_decisions(prices: pd.DataFrame, target_date: str):
    with _patched_step9l_globals():
        return step9i.build_morning_decisions(prices, target_date)


def seal_morning_decisions(
    target_date: str,
    now,
    prices: pd.DataFrame,
    ledger_db: Path = SHADOW_LEDGER_DB,
    source_db: Path = SHADOW_INTRADAY_DB,
    allow_late: bool = False,
    export_outputs_after: bool = True,
    simulated_clock: bool = False,
):
    with _patched_step9l_globals():
        return step9i.seal_morning_decisions(
            target_date=target_date,
            now=now,
            prices=prices,
            ledger_db=ledger_db,
            source_db=source_db,
            allow_late=allow_late,
            export_outputs_after=export_outputs_after,
            simulated_clock=simulated_clock,
        )


def evaluate_eod(
    target_date: str,
    now,
    prices: pd.DataFrame,
    ledger_db: Path = SHADOW_LEDGER_DB,
    source_db: Path = SHADOW_INTRADAY_DB,
    allow_early: bool = False,
    export_outputs_after: bool = True,
):
    with _patched_step9l_globals():
        return step9i.evaluate_eod(
            target_date=target_date,
            now=now,
            prices=prices,
            ledger_db=ledger_db,
            source_db=source_db,
            allow_early=allow_early,
            export_outputs_after=export_outputs_after,
        )


def export_shadow_outputs(ledger_db: Path = SHADOW_LEDGER_DB) -> None:
    with _patched_step9l_globals():
        step9i.export_shadow_outputs(ledger_db)


def contract_registry() -> pd.DataFrame:
    with _patched_step9l_globals():
        registry = step9i.contract_registry()
    registry["selection_status"] = registry["contract_id"].map(
        {row["contract_id"]: row["selection_status"] for row in CONTRACTS}
    )
    registry["historical_source"] = registry["contract_id"].map(
        {row["contract_id"]: row["historical_source"] for row in CONTRACTS}
    )
    return registry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 9L separate prospective selected-strategy shadow engine."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    morning = subparsers.add_parser("morning")
    morning.add_argument("--date")
    morning.add_argument("--as-of")
    morning.add_argument("--source-db", type=Path, default=SHADOW_INTRADAY_DB)
    morning.add_argument("--ledger-db", type=Path, default=SHADOW_LEDGER_DB)
    morning.add_argument("--allow-late-reconstruction", action="store_true")

    eod = subparsers.add_parser("eod")
    eod.add_argument("--date")
    eod.add_argument("--as-of")
    eod.add_argument("--source-db", type=Path, default=SHADOW_INTRADAY_DB)
    eod.add_argument("--ledger-db", type=Path, default=SHADOW_LEDGER_DB)
    eod.add_argument("--allow-early-evaluation", action="store_true")

    export = subparsers.add_parser("export")
    export.add_argument("--ledger-db", type=Path, default=SHADOW_LEDGER_DB)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "export":
        export_shadow_outputs(args.ledger_db)
        print("Step 9L immutable ledger exports refreshed.")
        return

    now = _parse_stockholm_datetime(args.as_of)
    target = _target_date(args.date, now)
    prices = load_shadow_prices(args.source_db)
    if prices.empty:
        raise step9i.ShadowDataNotReady(
            f"No shadow data found at {args.source_db}. Run .\\collect_step9i_v2_shadow_data.ps1 first."
        )

    if args.command == "morning":
        print("\n=== STEP 9L SELECTED-STRATEGY MORNING SHADOW SEAL ===")
        print(f"Experiment         : {EXPERIMENT_ID}")
        print(f"Session date       : {target}")
        print(f"As-of Stockholm    : {now:%Y-%m-%d %H:%M:%S %Z}")
        print(f"Tradable universe  : {len(step9i.TRADING_TICKERS)} (5 core + 18 holdout)")
        print("Positive contracts : 3")
        print("HD guardrails      : 2")
        batches, decisions, inserted = seal_morning_decisions(
            target_date=target,
            now=now,
            prices=prices,
            ledger_db=args.ledger_db,
            source_db=args.source_db,
            allow_late=args.allow_late_reconstruction,
            export_outputs_after=True,
            simulated_clock=bool(args.as_of),
        )
        row = batches.iloc[0]
        eligible = int(decisions["contract_eligible"].astype(bool).sum())
        guards = int(decisions["decision_action"].eq("GUARDRAIL_ACTIVE_AVOID_STRATEGY").sum())
        print(f"Ledger action      : {'SEALED_NEW_BATCH' if inserted else 'EXISTING_IDENTICAL_BATCH_RETURNED'}")
        print(f"Prospective status : {row['prospective_status']}")
        print(f"Primary regime     : {row['primary_regime']} ({float(row['regime_confidence']):.1%})")
        print(f"Decisions / eligible: {len(decisions)}/{eligible}")
        print(f"Active guardrails  : {guards}")
        print("No orders were sent. Step 9L is separate from the frozen Step 9I V2 ledger.")
    else:
        print("\n=== STEP 9L SELECTED-STRATEGY END-OF-DAY EVALUATION ===")
        print(f"Session date       : {target}")
        print(f"As-of Stockholm    : {now:%Y-%m-%d %H:%M:%S %Z}")
        batches, outcomes, inserted = evaluate_eod(
            target_date=target,
            now=now,
            prices=prices,
            ledger_db=args.ledger_db,
            source_db=args.source_db,
            allow_early=args.allow_early_evaluation,
            export_outputs_after=True,
        )
        completed = outcomes[
            outcomes["outcome_status"].astype(str).str.endswith("TRADE_COMPLETED")
        ] if not outcomes.empty else outcomes
        positive = completed[completed["test_role"].eq("PRIMARY_HYPOTHESIS")] if not completed.empty else completed
        counterfactual = completed[completed["test_role"].eq("NEGATIVE_GUARDRAIL")] if not completed.empty else completed
        print(f"Ledger action      : {'SEALED_NEW_OUTCOME_BATCH' if inserted else 'EXISTING_IDENTICAL_BATCH_RETURNED'}")
        print(f"Outcome rows       : {len(outcomes)}")
        print(f"Positive-strategy completed trades: {len(positive)}")
        print(f"Guardrail counterfactual trades    : {len(counterfactual)}")
        print("Morning decisions were read-only and were not rewritten.")


if __name__ == "__main__":
    main()
