from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.export_utils import export_csv_for_power_bi
from RegimeTrading.core.paths import shadow_output_path
from RegimeTrading.core.stage_registry import resolve_stage_path
from RegimeTrading.scripts import step9e_instrument_sector_taxonomy as step9e
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_prospective_shadow_router as base


_ORIGINAL_HOLDOUT_STATIC_BUILDER = step9h.build_holdout_static
_ORIGINAL_HOLDOUT_INSTRUMENTS = tuple(dict(row) for row in step9h.HOLDOUT_INSTRUMENTS)


EXPERIMENT_ID = "PROSPECTIVE_SHADOW_ROUTER_V2_CORE5_PLUS_HOLDOUT18"
RESEARCH_STATUS = "SIMULATION_ONLY_PROSPECTIVE_SHADOW_23_TICKERS_NOT_ROUTER_ACTIVE"
CODE_VERSION = "STEP9I_V2_CORE5_PLUS_HOLDOUT18_CORE_EOD_FIX_2026_07_26"
SHADOW_UNIVERSE_VERSION = "STEP9I_V2_REGIME_SOURCE11_TRADABLE23"

DECISION_TIME = base.DECISION_TIME
LATEST_ALLOWED_BAR_LABEL = base.LATEST_ALLOWED_BAR_LABEL
SEAL_DEADLINE = base.SEAL_DEADLINE
EOD_MINIMUM_LABEL = base.EOD_MINIMUM_LABEL
LOCAL_TZ = base.LOCAL_TZ

SHADOW_INTRADAY_DB = base.SHADOW_INTRADAY_DB
SHADOW_LEDGER_DB = resolve_stage_path("step9i")

DECISION_BATCH_FILE = shadow_output_path("step9i_v2_shadow_decision_batches.csv")
DECISION_FILE = shadow_output_path("step9i_v2_shadow_decisions.csv")
OUTCOME_BATCH_FILE = shadow_output_path("step9i_v2_shadow_outcome_batches.csv")
OUTCOME_FILE = shadow_output_path("step9i_v2_shadow_outcomes.csv")
PERFORMANCE_FILE = shadow_output_path("step9i_v2_shadow_performance.csv")
MULTIPLE_TESTING_FILE = shadow_output_path("step9i_v2_shadow_multiple_testing.csv")
AUDIT_FILE = shadow_output_path("step9i_v2_shadow_audit.csv")
SUMMARY_FILE = shadow_output_path("step9i_v2_shadow_summary.csv")
CONTRACT_REGISTRY_FILE = shadow_output_path("step9i_v2_shadow_contract_registry.csv")
SEGMENTED_DECISION_FILE = shadow_output_path("step9i_v2_shadow_decisions_segmented.csv")
SEGMENTED_OUTCOME_FILE = shadow_output_path("step9i_v2_shadow_outcomes_segmented.csv")
SEGMENT_PERFORMANCE_FILE = shadow_output_path("step9i_v2_shadow_segment_performance.csv")
UNIVERSE_SUMMARY_FILE = shadow_output_path("step9i_v2_shadow_universe_summary.csv")
SELF_INFLUENCE_FILE = shadow_output_path("step9i_v2_core5_regime_sensitivity.csv")

REGIME_SOURCE_TICKERS = tuple(base.REGIME_SOURCE_TICKERS)
CORE_TICKERS = (
    "SHB-A.ST",
    "ERIC-B.ST",
    "ALFA.ST",
    "SEB-A.ST",
    "ATCO-A.ST",
)
HOLDOUT_ONLY_TICKERS = tuple(row["ticker"] for row in step9h.HOLDOUT_INSTRUMENTS)
TRADING_TICKERS = tuple(dict.fromkeys(list(CORE_TICKERS) + list(HOLDOUT_ONLY_TICKERS)))
# Alias retained because the historical replay module expects this public name.
HOLDOUT_TICKERS = TRADING_TICKERS

CORE_COMPANY_REMOVALS = {
    "HANDELSBANKEN": ("SHB-A.ST",),
    "ERICSSON": ("ERIC-B.ST",),
    "ALFA_LAVAL": ("ALFA.ST",),
    "SEB": ("SEB-A.ST",),
    "ATLAS_COPCO": ("ATCO-A.ST", "ATCO-B.ST"),
}

ImmutableLedgerConflict = base.ImmutableLedgerConflict
ShadowDataNotReady = base.ShadowDataNotReady


def _bool(value: Any) -> bool:
    return base._bool(value)


def _num(value: Any, default: float = np.nan) -> float:
    return base._num(value, default)


def _parse_stockholm_datetime(value: str | None) -> datetime:
    return base._parse_stockholm_datetime(value)


def _target_date(value: str | None, now: datetime) -> str:
    return base._target_date(value, now)


def _prospective_status(target_date: str, now: datetime, allow_late: bool) -> str:
    return base._prospective_status(target_date, now, allow_late)


def _point_in_time_prices(prices: pd.DataFrame, target_date: str) -> pd.DataFrame:
    return base._point_in_time_prices(prices, target_date)


def _segment_for_ticker(ticker: str) -> str:
    return "CORE_5" if str(ticker) in CORE_TICKERS else "HOLDOUT_18"


def build_trading_static() -> pd.DataFrame:
    original = step9e.build_static_taxonomy()
    core = original[original["ticker"].isin(CORE_TICKERS)].copy()
    if set(core["ticker"].astype(str)) != set(CORE_TICKERS):
        missing = sorted(set(CORE_TICKERS) - set(core["ticker"].astype(str)))
        raise ValueError(f"Core static taxonomy is incomplete: {missing}")
    core["universe_role"] = "ORIGINAL_CORE_TRADABLE_IN_SAMPLE"
    core["holdout_lock_version"] = "NOT_APPLICABLE_CORE5"
    core["locked_before_results"] = False
    core["discovery_company_overlap"] = True
    core["universe_segment"] = "CORE_5"

    # The Step 9H builder resolves HOLDOUT_INSTRUMENTS at call time. During a
    # V2 execution context that registry is intentionally patched to Combined
    # 23, so temporarily restore the frozen original Holdout 18 definition.
    active_holdout_instruments = step9h.HOLDOUT_INSTRUMENTS
    try:
        step9h.HOLDOUT_INSTRUMENTS = [dict(row) for row in _ORIGINAL_HOLDOUT_INSTRUMENTS]
        holdout = _ORIGINAL_HOLDOUT_STATIC_BUILDER().copy()
    finally:
        step9h.HOLDOUT_INSTRUMENTS = active_holdout_instruments
    holdout["universe_segment"] = "HOLDOUT_18"

    combined = pd.concat([core, holdout], ignore_index=True, sort=False)
    combined = combined.drop_duplicates("ticker", keep="first")
    if set(combined["ticker"].astype(str)) != set(TRADING_TICKERS):
        missing = sorted(set(TRADING_TICKERS) - set(combined["ticker"].astype(str)))
        extra = sorted(set(combined["ticker"].astype(str)) - set(TRADING_TICKERS))
        raise ValueError(f"Combined trading taxonomy mismatch. Missing={missing}; extra={extra}")
    return combined.sort_values("ticker").reset_index(drop=True)


@contextmanager
def _patched_base(regime_source_tickers: Iterable[str] | None = None):
    global_names = [
        "EXPERIMENT_ID",
        "RESEARCH_STATUS",
        "CODE_VERSION",
        "SHADOW_UNIVERSE_VERSION",
        "SHADOW_INTRADAY_DB",
        "SHADOW_LEDGER_DB",
        "DECISION_BATCH_FILE",
        "DECISION_FILE",
        "OUTCOME_BATCH_FILE",
        "OUTCOME_FILE",
        "PERFORMANCE_FILE",
        "MULTIPLE_TESTING_FILE",
        "AUDIT_FILE",
        "SUMMARY_FILE",
        "CONTRACT_REGISTRY_FILE",
        "REGIME_SOURCE_TICKERS",
        "HOLDOUT_TICKERS",
    ]
    old_globals = {name: getattr(base, name) for name in global_names}
    old_static_builder = step9h.build_holdout_static
    old_holdout_instruments = step9h.HOLDOUT_INSTRUMENTS
    # Build the combined taxonomy before patching the Step 9H instrument registry;
    # build_trading_static deliberately reads the original locked Holdout 18 list.
    combined_instruments = build_trading_static().to_dict("records")
    try:
        base.EXPERIMENT_ID = EXPERIMENT_ID
        base.RESEARCH_STATUS = RESEARCH_STATUS
        base.CODE_VERSION = CODE_VERSION
        base.SHADOW_UNIVERSE_VERSION = SHADOW_UNIVERSE_VERSION
        base.SHADOW_INTRADAY_DB = SHADOW_INTRADAY_DB
        base.SHADOW_LEDGER_DB = SHADOW_LEDGER_DB
        base.DECISION_BATCH_FILE = DECISION_BATCH_FILE
        base.DECISION_FILE = DECISION_FILE
        base.OUTCOME_BATCH_FILE = OUTCOME_BATCH_FILE
        base.OUTCOME_FILE = OUTCOME_FILE
        base.PERFORMANCE_FILE = PERFORMANCE_FILE
        base.MULTIPLE_TESTING_FILE = MULTIPLE_TESTING_FILE
        base.AUDIT_FILE = AUDIT_FILE
        base.SUMMARY_FILE = SUMMARY_FILE
        base.CONTRACT_REGISTRY_FILE = CONTRACT_REGISTRY_FILE
        base.REGIME_SOURCE_TICKERS = tuple(regime_source_tickers or REGIME_SOURCE_TICKERS)
        base.HOLDOUT_TICKERS = tuple(TRADING_TICKERS)
        # Step 9H's execution context derives the Step 9B whitelist directly
        # from HOLDOUT_INSTRUMENTS. Patch both the static builder and registry,
        # otherwise Core 5 rows can be morning-eligible but never reach EOD
        # candidate/trade generation.
        step9h.HOLDOUT_INSTRUMENTS = combined_instruments
        step9h.build_holdout_static = build_trading_static
        yield
    finally:
        step9h.build_holdout_static = old_static_builder
        step9h.HOLDOUT_INSTRUMENTS = old_holdout_instruments
        for name, value in old_globals.items():
            setattr(base, name, value)


@contextmanager
def _patched_holdout_tickers():
    """Patch the shared Step 9B trade engine to the full 23-ticker universe.

    This compatibility helper mirrors the public context manager exposed by
    Step 9I V1.  Step 9J diagnostics call it directly while reconstructing
    market states and trade excursions.  The nested V2 base patch ensures the
    V1 helper reads the 23-ticker V2 universe, and both contexts restore their
    original globals on exit.
    """
    with _patched_base():
        with base._patched_holdout_tickers():
            yield


def _registry_hash() -> str:
    with _patched_base():
        return base._registry_hash()


def _universe_hash() -> str:
    with _patched_base():
        return base._universe_hash()


def _ensure_ledger_schema(connection: sqlite3.Connection) -> None:
    with _patched_base():
        base._ensure_ledger_schema(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS core_regime_sensitivity (
            sensitivity_id TEXT PRIMARY KEY,
            session_date TEXT NOT NULL,
            company_id TEXT NOT NULL,
            removed_tickers TEXT NOT NULL,
            baseline_regime TEXT NOT NULL,
            leave_out_regime TEXT NOT NULL,
            baseline_confidence REAL,
            leave_out_confidence REAL,
            sensitivity_status TEXT NOT NULL,
            regime_stable INTEGER NOT NULL,
            row_payload_hash TEXT NOT NULL,
            UNIQUE(session_date, company_id)
        )
        """
    )
    connection.commit()


def load_shadow_prices(db_path: Path = SHADOW_INTRADAY_DB) -> pd.DataFrame:
    with _patched_base():
        return base.load_shadow_prices(db_path)


def build_current_regime(prices: pd.DataFrame, target_date: str) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    with _patched_base():
        return base.build_current_regime(prices, target_date)


def build_morning_decisions(prices: pd.DataFrame, target_date: str) -> tuple[pd.Series, pd.DataFrame, dict[str, int]]:
    with _patched_base():
        taxonomy, decisions, coverage = base.build_morning_decisions(prices, target_date)
    decisions = decisions.copy()
    decisions["universe_segment"] = decisions["ticker"].map(_segment_for_ticker)
    coverage = dict(coverage)
    coverage["trading_tickers_observed"] = coverage.get("holdout_tickers_observed", 0)
    coverage["core_tickers_observed"] = int(
        prices[prices["date"].astype(str).eq(target_date) & prices["ticker"].isin(CORE_TICKERS)]["ticker"].nunique()
    )
    coverage["holdout_only_tickers_observed"] = int(
        prices[prices["date"].astype(str).eq(target_date) & prices["ticker"].isin(HOLDOUT_ONLY_TICKERS)]["ticker"].nunique()
    )
    return taxonomy, decisions, coverage


def _full_holdout_context(prices: pd.DataFrame, target_date: str):
    with _patched_base():
        return base._full_holdout_context(prices, target_date)


def _build_core_regime_sensitivity(
    prices: pd.DataFrame,
    target_date: str,
    baseline_regime: str,
    baseline_confidence: float | None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for company_id, removed in CORE_COMPANY_REMOVALS.items():
        reduced = tuple(t for t in REGIME_SOURCE_TICKERS if t not in set(removed))
        try:
            with _patched_base(reduced):
                row, _, _ = base.build_current_regime(prices, target_date)
            leave_out_regime = str(row.get("primary_regime", ""))
            leave_out_confidence = _num(row.get("regime_confidence"))
            status = "CLASSIFIED"
            stable = leave_out_regime == baseline_regime
        except Exception as exc:  # recorded, never silently ignored
            leave_out_regime = ""
            leave_out_confidence = np.nan
            status = f"NOT_CLASSIFIABLE:{type(exc).__name__}"
            stable = False
        payload = {
            "session_date": target_date,
            "company_id": company_id,
            "removed_tickers": "|".join(removed),
            "baseline_regime": baseline_regime,
            "leave_out_regime": leave_out_regime,
            "baseline_confidence": baseline_confidence,
            "leave_out_confidence": leave_out_confidence,
            "sensitivity_status": status,
            "regime_stable": stable,
        }
        rows.append(
            {
                "sensitivity_id": base._payload_hash({"session_date": target_date, "company_id": company_id})[:24],
                **payload,
                "row_payload_hash": base._payload_hash(payload),
            }
        )
    return pd.DataFrame(rows)


def _seal_sensitivity_rows(ledger_db: Path, frame: pd.DataFrame) -> None:
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        for row in frame.to_dict("records"):
            existing = con.execute(
                "SELECT row_payload_hash FROM core_regime_sensitivity WHERE session_date = ? AND company_id = ?",
                (row["session_date"], row["company_id"]),
            ).fetchone()
            if existing:
                if str(existing[0]) != str(row["row_payload_hash"]):
                    raise ImmutableLedgerConflict(
                        f"Core regime sensitivity conflict for {row['session_date']} {row['company_id']}."
                    )
                continue
            con.execute(
                """
                INSERT INTO core_regime_sensitivity (
                    sensitivity_id, session_date, company_id, removed_tickers,
                    baseline_regime, leave_out_regime, baseline_confidence,
                    leave_out_confidence, sensitivity_status, regime_stable, row_payload_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["sensitivity_id"], row["session_date"], row["company_id"], row["removed_tickers"],
                    row["baseline_regime"], row["leave_out_regime"], row["baseline_confidence"],
                    row["leave_out_confidence"], row["sensitivity_status"], int(bool(row["regime_stable"])),
                    row["row_payload_hash"],
                ),
            )
        con.commit()


def seal_morning_decisions(
    target_date: str,
    now: datetime,
    prices: pd.DataFrame,
    ledger_db: Path = SHADOW_LEDGER_DB,
    source_db: Path = SHADOW_INTRADAY_DB,
    allow_late: bool = False,
    export_outputs_after: bool = True,
    simulated_clock: bool = False,
    include_core_regime_sensitivity: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    with _patched_base():
        batches, decisions, inserted = base.seal_morning_decisions(
            target_date=target_date,
            now=now,
            prices=prices,
            ledger_db=ledger_db,
            source_db=source_db,
            allow_late=allow_late,
            export_outputs_after=False,
            simulated_clock=simulated_clock,
        )
    if include_core_regime_sensitivity and not batches.empty:
        batch = batches.iloc[0]
        sensitivity = _build_core_regime_sensitivity(
            prices,
            target_date,
            str(batch["primary_regime"]),
            _num(batch.get("regime_confidence")),
        )
        _seal_sensitivity_rows(Path(ledger_db), sensitivity)
    decisions = decisions.copy()
    if not decisions.empty:
        decisions["universe_segment"] = decisions["ticker"].map(_segment_for_ticker)
    if export_outputs_after:
        export_shadow_outputs(ledger_db)
    return batches, decisions, inserted


def complete_core_regime_sensitivity(
    target_date: str,
    prices: pd.DataFrame,
    ledger_db: Path = SHADOW_LEDGER_DB,
) -> pd.DataFrame:
    """Complete the immutable Core-5 leave-one-company sensitivity rows.

    The decision batch and decision rows must already be sealed. This helper is
    idempotent and exists so the diagnostic sensitivity calculation can be
    moved out of the deadline-critical decision path without changing its
    inputs, schema, hashes, or evidence semantics.
    """

    ledger_db = Path(ledger_db)
    if not ledger_db.is_file():
        raise ShadowDataNotReady(
            f"Step 9 morning ledger is missing before sensitivity completion: {ledger_db}"
        )
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        batches = pd.read_sql_query(
            "SELECT * FROM shadow_decision_batches WHERE session_date = ?",
            con,
            params=(target_date,),
        )
    if len(batches) != 1:
        raise ShadowDataNotReady(
            f"Expected one sealed morning batch for {target_date} before "
            f"sensitivity completion; found {len(batches)}."
        )
    batch = batches.iloc[0]
    sensitivity = _build_core_regime_sensitivity(
        prices,
        target_date,
        str(batch["primary_regime"]),
        _num(batch.get("regime_confidence")),
    )
    _seal_sensitivity_rows(ledger_db, sensitivity)
    return sensitivity


def evaluate_eod(
    target_date: str,
    now: datetime,
    prices: pd.DataFrame,
    ledger_db: Path = SHADOW_LEDGER_DB,
    source_db: Path = SHADOW_INTRADAY_DB,
    allow_early: bool = False,
    export_outputs_after: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    with _patched_base():
        batches, outcomes, inserted = base.evaluate_eod(
            target_date=target_date,
            now=now,
            prices=prices,
            ledger_db=ledger_db,
            source_db=source_db,
            allow_early=allow_early,
            export_outputs_after=False,
        )
    outcomes = outcomes.copy()
    if not outcomes.empty:
        outcomes["universe_segment"] = outcomes["ticker"].map(_segment_for_ticker)
    if export_outputs_after:
        export_shadow_outputs(ledger_db)
    return batches, outcomes, inserted


def build_performance(decisions: pd.DataFrame, outcomes: pd.DataFrame, batches: pd.DataFrame):
    with _patched_base():
        return base.build_performance(decisions, outcomes, batches)


def build_audit(
    decisions: pd.DataFrame,
    outcomes: pd.DataFrame,
    batches: pd.DataFrame,
    outcome_batches: pd.DataFrame,
    sensitivity: pd.DataFrame | None = None,
) -> pd.DataFrame:
    with _patched_base():
        audit = base.build_audit(decisions, outcomes, batches, outcome_batches)
    extra_rows = []
    if sensitivity is not None:
        expected = len(batches) * len(CORE_COMPANY_REMOVALS)
        observed = len(sensitivity)
        extra_rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "audit_item": "CORE5_REGIME_SELF_INFLUENCE_ROWS_RECORDED",
                "rows_checked": expected,
                "failures": max(0, expected - observed),
                "audit_pass": observed == expected,
                "interpretation": "Five leave-one-company-out regime sensitivity rows are sealed for each morning batch.",
            }
        )
    extra_rows.append(
        {
            "experiment_id": EXPERIMENT_ID,
            "audit_item": "TRADABLE_UNIVERSE_IS_23_TICKERS",
            "rows_checked": len(TRADING_TICKERS),
            "failures": 0 if len(TRADING_TICKERS) == 23 and len(set(TRADING_TICKERS)) == 23 else 1,
            "audit_pass": len(TRADING_TICKERS) == 23 and len(set(TRADING_TICKERS)) == 23,
            "interpretation": "The active research universe contains exactly Core 5 plus Holdout 18.",
        }
    )
    return pd.concat([audit, pd.DataFrame(extra_rows)], ignore_index=True)


def contract_registry() -> pd.DataFrame:
    with _patched_base():
        registry = base.contract_registry()
    registry["tradable_universe_version"] = SHADOW_UNIVERSE_VERSION
    registry["tradable_tickers"] = len(TRADING_TICKERS)
    return registry


def _read_tables(ledger_db: Path):
    if not Path(ledger_db).exists():
        return (pd.DataFrame(),) * 5
    with closing(sqlite3.connect(ledger_db)) as con:
        _ensure_ledger_schema(con)
        batches = pd.read_sql_query("SELECT * FROM shadow_decision_batches ORDER BY session_date", con)
        decisions = pd.read_sql_query("SELECT * FROM shadow_decisions ORDER BY session_date, contract_id, ticker", con)
        outcome_batches = pd.read_sql_query("SELECT * FROM shadow_outcome_batches ORDER BY session_date", con)
        outcomes = pd.read_sql_query("SELECT * FROM shadow_outcomes ORDER BY session_date, contract_id, ticker", con)
        sensitivity = pd.read_sql_query("SELECT * FROM core_regime_sensitivity ORDER BY session_date, company_id", con)
    return batches, decisions, outcome_batches, outcomes, sensitivity


def _build_segment_performance(decisions: pd.DataFrame, outcomes: pd.DataFrame, batches: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for segment, tickers in (
        ("CORE_5", CORE_TICKERS),
        ("HOLDOUT_18", HOLDOUT_ONLY_TICKERS),
        ("COMBINED_23", TRADING_TICKERS),
    ):
        d = decisions[decisions["ticker"].isin(tickers)].copy() if not decisions.empty else decisions.copy()
        o = outcomes[outcomes["ticker"].isin(tickers)].copy() if not outcomes.empty else outcomes.copy()
        with _patched_base():
            perf, _ = base.build_performance(d, o, batches)
        perf.insert(1, "universe_segment", segment)
        frames.append(perf)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def export_shadow_outputs(ledger_db: Path = SHADOW_LEDGER_DB) -> None:
    ledger_db = Path(ledger_db)
    with _patched_base():
        base.export_shadow_outputs(ledger_db)
    batches, decisions, outcome_batches, outcomes, sensitivity = _read_tables(ledger_db)

    segmented_decisions = decisions.copy()
    if not segmented_decisions.empty:
        segmented_decisions.insert(
            segmented_decisions.columns.get_loc("ticker") + 1,
            "universe_segment",
            segmented_decisions["ticker"].map(_segment_for_ticker),
        )
    segmented_outcomes = outcomes.copy()
    if not segmented_outcomes.empty:
        segmented_outcomes.insert(
            segmented_outcomes.columns.get_loc("ticker") + 1,
            "universe_segment",
            segmented_outcomes["ticker"].map(_segment_for_ticker),
        )
    segment_performance = _build_segment_performance(decisions, outcomes, batches)
    audit = build_audit(decisions, outcomes, batches, outcome_batches, sensitivity)

    universe_summary = pd.DataFrame(
        [
            {
                "experiment_id": EXPERIMENT_ID,
                "universe_version": SHADOW_UNIVERSE_VERSION,
                "regime_source_tickers": len(REGIME_SOURCE_TICKERS),
                "tradable_tickers": len(TRADING_TICKERS),
                "core_tickers": len(CORE_TICKERS),
                "holdout_tickers": len(HOLDOUT_ONLY_TICKERS),
                "contracts": len(step9h.CONTRACTS),
                "decisions_per_full_morning_batch": len(TRADING_TICKERS) * len(step9h.CONTRACTS),
                "decision_batches": len(batches),
                "outcome_batches": len(outcome_batches),
                "router_active": False,
            }
        ]
    )

    for frame, path in (
        (segmented_decisions, SEGMENTED_DECISION_FILE),
        (segmented_outcomes, SEGMENTED_OUTCOME_FILE),
        (segment_performance, SEGMENT_PERFORMANCE_FILE),
        (universe_summary, UNIVERSE_SUMMARY_FILE),
        (sensitivity, SELF_INFLUENCE_FILE),
        (audit, AUDIT_FILE),
    ):
        export_csv_for_power_bi(frame, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 9I V2 prospective shadow router for Core 5 plus Holdout 18.")
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
        print("Step 9I V2 immutable ledger exports refreshed.")
        return

    now = _parse_stockholm_datetime(args.as_of)
    target = _target_date(args.date, now)
    prices = load_shadow_prices(args.source_db)
    if prices.empty:
        raise ShadowDataNotReady(
            f"No shadow data found at {args.source_db}. Run .\\collect_step9i_shadow_data.ps1 first."
        )

    if args.command == "morning":
        print("\n=== STEP 9I V2 PROSPECTIVE MORNING SHADOW SEAL ===")
        print(f"Experiment         : {EXPERIMENT_ID}")
        print(f"Session date       : {target}")
        print(f"As-of Stockholm    : {now:%Y-%m-%d %H:%M:%S %Z}")
        print(f"Regime source      : {len(REGIME_SOURCE_TICKERS)} tickers")
        print(f"Tradable universe  : {len(TRADING_TICKERS)} (5 core + 18 holdout)")
        print(f"Decision cutoff    : completed start-labelled bars through {LATEST_ALLOWED_BAR_LABEL}")
        batches, decisions, inserted = seal_morning_decisions(
            target, now, prices, args.ledger_db, args.source_db,
            args.allow_late_reconstruction, True, bool(args.as_of)
        )
        row = batches.iloc[0]
        print(f"Ledger action      : {'SEALED_NEW_BATCH' if inserted else 'EXISTING_IDENTICAL_BATCH_RETURNED'}")
        print(f"Prospective status : {row['prospective_status']}")
        print(f"Primary regime     : {row['primary_regime']} ({float(row['regime_confidence']):.1%})")
        print(f"Decisions / eligible: {len(decisions)}/{int(decisions['contract_eligible'].astype(bool).sum())}")
        print(f"Core / holdout decisions: {int(decisions['universe_segment'].eq('CORE_5').sum())}/{int(decisions['universe_segment'].eq('HOLDOUT_18').sum())}")
        print(f"Active guardrails  : {int(decisions['decision_action'].eq('GUARDRAIL_ACTIVE_AVOID_STRATEGY').sum())}")
        print("No orders were sent. The V2 morning ledger is immutable and separate from V1.")
    else:
        print("\n=== STEP 9I V2 END-OF-DAY SHADOW EVALUATION ===")
        print(f"Session date       : {target}")
        print(f"As-of Stockholm    : {now:%Y-%m-%d %H:%M:%S %Z}")
        batches, outcomes, inserted = evaluate_eod(
            target, now, prices, args.ledger_db, args.source_db,
            args.allow_early_evaluation, True
        )
        print(f"Ledger action      : {'SEALED_NEW_OUTCOME_BATCH' if inserted else 'EXISTING_IDENTICAL_BATCH_RETURNED'}")
        print(f"Outcome rows       : {len(outcomes)}")
        print(f"Completed trades   : {int(outcomes['outcome_status'].astype(str).str.endswith('TRADE_COMPLETED').sum())}")
        if not outcomes.empty:
            completed = outcomes[outcomes['outcome_status'].astype(str).str.endswith('TRADE_COMPLETED')]
            print(f"Core / holdout completed: {int(completed['universe_segment'].eq('CORE_5').sum())}/{int(completed['universe_segment'].eq('HOLDOUT_18').sum())}")
        print("Morning decisions were read-only and were not rewritten.")


if __name__ == "__main__":
    main()
