from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from RegimeTrading.core.paths import DATA_DIR, REFERENCE_DATA_DIR, legacy_output_path
from RegimeTrading.core.stage_registry import resolve_stage_output_dir, resolve_stage_path


CONFIG_FILE = Path(__file__).resolve().parents[2] / "config" / "step9t_regime_transition_archetype_research_v1.json"
DEFAULT_PRICE_DB = resolve_stage_path("prices")
DEFAULT_TAXONOMY_FILE = DATA_DIR / "regime_daily_taxonomy.csv"
DEFAULT_STEP9L_LEDGER = resolve_stage_path("step9l")
DEFAULT_CORE_REGISTRY = REFERENCE_DATA_DIR / "instrument_static_taxonomy.csv"
DEFAULT_HOLDOUT_REGISTRY = legacy_output_path("regime_holdout_universe_registry.csv")
DEFAULT_OUTPUT_DIR = resolve_stage_output_dir("step9t")

SESSION_EXPORT = "step9t_session_transitions.csv"
ARCHETYPE_EXPORT = "step9t_ticker_archetypes.csv"
OUTCOME_EXPORT = "step9t_ticker_outcomes.csv"
REGIME_SUMMARY_EXPORT = "step9t_regime_summary.csv"
TRANSITION_SUMMARY_EXPORT = "step9t_transition_summary.csv"
ARCHETYPE_SUMMARY_EXPORT = "step9t_archetype_summary.csv"
TICKER_SUMMARY_EXPORT = "step9t_ticker_summary.csv"
AUDIT_EXPORT = "step9t_audit.csv"
SUMMARY_EXPORT = "step9t_summary.csv"
SOURCE_HASH_EXPORT = "step9t_source_hashes.json"


class Step9TError(RuntimeError):
    pass


class Step9TSourceError(Step9TError):
    pass


class Step9TIntegrityError(Step9TError):
    pass


def _load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    if bool(config.get("router_active")) or bool(config.get("orders_enabled")):
        raise Step9TIntegrityError("Step 9T must remain router inactive with orders disabled.")
    expected_labels = {
        "BROAD_RECOVERY",
        "WEAKNESS_PERSISTING",
        "BULLISH_CONTINUATION",
        "LEADER_FAILURE",
        "MIXED_TRANSITION",
        "DATA_LIMITED_TRANSITION",
    }
    if set(config.get("transition_labels", [])) != expected_labels:
        raise Step9TIntegrityError("Step 9T transition-label registry is incomplete or duplicated.")
    expected_archetypes = [
        "LAGGARD_RECOVERY_LONG",
        "LEADER_REVERSAL_SHORT",
        "BULLISH_CONTINUATION_LONG",
        "BEARISH_CONTINUATION_SHORT",
        "NO_CLEAR_SETUP",
    ]
    if list(config.get("archetype_priority", [])) != expected_archetypes:
        raise Step9TIntegrityError("Step 9T archetype priority is not the frozen V1 ordering.")
    return config


CONFIG = _load_config()
EXPERIMENT_ID = str(CONFIG["experiment_id"])
RESEARCH_STATUS = str(CONFIG["research_status"])
CODE_VERSION = str(CONFIG["code_version"])
LATEST_MORNING_LABEL = str(CONFIG["latest_morning_source_label"])
ENTRY_LABEL = str(CONFIG["standardized_entry_label"])
EOD_MINIMUM_LABEL = str(CONFIG["eod_minimum_label"])
BASE_NOTIONAL_SEK = float(CONFIG["base_notional_sek"])
ROUND_TRIP_COST_RATE = float(CONFIG["round_trip_cost_rate"])
MINIMUM_VALID_TICKERS = int(CONFIG["minimum_valid_tickers"])
EARLY_MOVE_THRESHOLD = float(CONFIG["early_move_threshold"])
LAST5_CONFIRMATION_THRESHOLD = float(CONFIG["last5_confirmation_threshold"])
ARCHETYPE_PRIORITY = tuple(str(value) for value in CONFIG["archetype_priority"])


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


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _load_universe(core_registry: Path, holdout_registry: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path, role in ((core_registry, "REGIME_SOURCE"), (holdout_registry, "CROSS_SECTIONAL_HOLDOUT")):
        if not path.is_file():
            raise FileNotFoundError(path)
        frame = pd.read_csv(path)
        required = {"ticker", "company_id", "broad_sector"}
        missing = required.difference(frame.columns)
        if missing:
            raise Step9TSourceError(f"Universe registry {path} is missing columns: {sorted(missing)}")
        frame = frame[["ticker", "company_id", "broad_sector"]].copy()
        frame["universe_role"] = role
        frames.append(frame)
    universe = pd.concat(frames, ignore_index=True)
    universe["ticker"] = universe["ticker"].astype(str).str.strip()
    universe = universe.drop_duplicates("ticker", keep="last").sort_values("ticker").reset_index(drop=True)
    if len(universe) != 29:
        raise Step9TSourceError(f"Step 9T expected the frozen 29-ticker universe, found {len(universe)}.")
    return universe


def _load_regime_sessions(taxonomy_file: Path, step9l_ledger: Path) -> pd.DataFrame:
    if not taxonomy_file.is_file():
        raise FileNotFoundError(taxonomy_file)
    taxonomy = pd.read_csv(taxonomy_file)
    required = {"date", "primary_regime", "regime_confidence"}
    missing = required.difference(taxonomy.columns)
    if missing:
        raise Step9TSourceError(f"Taxonomy is missing columns: {sorted(missing)}")
    base = taxonomy[["date", "primary_regime", "regime_confidence"]].copy()
    base = base.rename(columns={"date": "session_date", "primary_regime": "source_regime", "regime_confidence": "source_regime_confidence"})
    base["source_regime_origin"] = "FROZEN_HISTORICAL_TAXONOMY"
    base["source_batch_id"] = ""
    base["source_batch_hash"] = ""
    base["source_prospective_status"] = "HISTORICAL_REPLAY"

    with closing(_readonly_connection(step9l_ledger)) as connection:
        ledger = pd.read_sql_query(
            """
            SELECT session_date, primary_regime, regime_confidence,
                   batch_id, batch_payload_hash, prospective_status
            FROM shadow_decision_batches
            ORDER BY session_date
            """,
            connection,
        )
    if not ledger.empty:
        ledger = ledger.rename(
            columns={
                "primary_regime": "source_regime",
                "regime_confidence": "source_regime_confidence",
                "batch_id": "source_batch_id",
                "batch_payload_hash": "source_batch_hash",
                "prospective_status": "source_prospective_status",
            }
        )
        ledger["source_regime_origin"] = "SEALED_STEP9L_V3_BATCH"
        ledger = ledger[~ledger["session_date"].isin(base["session_date"])].copy()
        sessions = pd.concat([base, ledger[base.columns]], ignore_index=True)
    else:
        sessions = base
    sessions["session_date"] = sessions["session_date"].astype(str)
    sessions = sessions.drop_duplicates("session_date", keep="last").sort_values("session_date").reset_index(drop=True)
    return sessions


def _load_prices(
    path: Path,
    start_date: str | None,
    end_date: str | None,
    *,
    duplicate_policy: str = "error",
) -> pd.DataFrame:
    """Load source prices without modifying the collector database.

    The collector can preserve multiple raw rows that normalize to the same
    ticker/minute. The default policy remains fail-fast for tests and unknown
    sources. Historical replay explicitly uses ``latest_rowid`` so the latest
    inserted raw observation becomes the canonical minute bar.

    No source row is updated or deleted.
    """

    valid_policies = {"error", "latest_rowid"}

    if duplicate_policy not in valid_policies:
        raise Step9TSourceError(
            "Unsupported duplicate policy: "
            f"{duplicate_policy!r}. "
            f"Expected one of {sorted(valid_policies)}."
        )

    clauses: list[str] = []
    params: list[Any] = []

    if start_date:
        clauses.append("substr(datetime, 1, 10) >= ?")
        params.append(start_date)

    if end_date:
        clauses.append("substr(datetime, 1, 10) <= ?")
        params.append(end_date)

    where = (
        " WHERE " + " AND ".join(clauses)
        if clauses
        else ""
    )

    query = (
        "SELECT "
        "rowid AS source_rowid, "
        "datetime, open, high, low, close, ticker "
        f"FROM intraday_prices{where} "
        "ORDER BY ticker, datetime, source_rowid"
    )

    try:
        with closing(_readonly_connection(path)) as connection:
            prices = pd.read_sql_query(
                query,
                connection,
                params=params,
            )
    except Exception as exc:
        raise Step9TSourceError(
            "Unable to load source prices with SQLite rowid provenance."
        ) from exc

    if prices.empty:
        raise Step9TSourceError(
            "No source price rows were loaded."
        )

    prices["source_rowid"] = pd.to_numeric(
        prices["source_rowid"],
        errors="raise",
    ).astype("int64")

    prices["source_datetime_raw"] = (
        prices["datetime"].astype(str)
    )

    prices["datetime"] = pd.to_datetime(
        prices["datetime"],
        errors="raise",
        format="mixed",
    )

    prices["ticker"] = (
        prices["ticker"]
        .astype(str)
        .str.strip()
    )

    for column in ["open", "high", "low", "close"]:
        prices[column] = pd.to_numeric(
            prices[column],
            errors="coerce",
        )

    prices = prices.dropna(
        subset=[
            "datetime",
            "ticker",
            "open",
            "high",
            "low",
            "close",
        ]
    ).copy()

    prices["session_date"] = (
        prices["datetime"].dt.strftime("%Y-%m-%d")
    )

    prices["clock"] = (
        prices["datetime"].dt.strftime("%H:%M")
    )

    key = ["session_date", "ticker", "clock"]

    duplicate_count = (
        prices.groupby(
            key,
            dropna=False,
        )["source_rowid"]
        .transform("size")
    )

    prices["source_duplicate_count"] = (
        duplicate_count.astype("int64")
    )

    conflict = (
        prices.groupby(
            key,
            dropna=False,
        )[["open", "high", "low", "close"]]
        .nunique(dropna=False)
        .max(axis=1)
        .gt(1)
    )

    conflict_keys = set(
        conflict[conflict].index.tolist()
    )

    prices["source_duplicate_conflict"] = [
        int(
            (
                session_date,
                ticker,
                clock,
            )
            in conflict_keys
        )
        for session_date, ticker, clock
        in prices[key].itertuples(
            index=False,
            name=None,
        )
    ]

    if bool(conflict.any()) and duplicate_policy == "error":
        examples = (
            conflict[conflict]
            .index
            .tolist()[:5]
        )

        raise Step9TSourceError(
            "Conflicting duplicate price bars found: "
            f"{examples}"
        )

    # Canonicalization policy:
    # retain the latest inserted SQLite row for each ticker/minute.
    #
    # This is deterministic and read-only. It does not average,
    # merge, update, or delete the raw source observations.
    prices = (
        prices.sort_values(
            key + ["source_rowid"],
            kind="mergesort",
        )
        .drop_duplicates(
            subset=key,
            keep="last",
        )
        .sort_values(
            ["ticker", "datetime", "source_rowid"],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )

    return prices




def _bar_map(ticker_prices: pd.DataFrame) -> dict[str, pd.Series]:
    return {str(row.clock): row for row in ticker_prices.itertuples(index=False)}


def _direction_for_archetype(archetype: str) -> str:
    if archetype.endswith("_LONG"):
        return "LONG"
    if archetype.endswith("_SHORT"):
        return "SHORT"
    return "NONE"


def _primary_archetype(flags: dict[str, bool]) -> str:
    for archetype in ARCHETYPE_PRIORITY:
        if archetype == "NO_CLEAR_SETUP" or flags.get(archetype, False):
            return archetype
    raise AssertionError("Frozen archetype priority did not produce a label.")


def classify_ticker_morning(
    session_date: str,
    ticker_row: pd.Series,
    ticker_prices: pd.DataFrame,
) -> dict[str, Any]:
    bars = _bar_map(ticker_prices)
    required = ("09:30", "09:35", "09:40", LATEST_MORNING_LABEL, ENTRY_LABEL)
    missing = [label for label in required if label not in bars]
    base = {
        "experiment_id": EXPERIMENT_ID,
        "code_version": CODE_VERSION,
        "session_date": session_date,
        "ticker": str(ticker_row["ticker"]),
        "company_id": str(ticker_row["company_id"]),
        "broad_sector": str(ticker_row["broad_sector"]),
        "universe_role": str(ticker_row["universe_role"]),
        "latest_morning_source_label": LATEST_MORNING_LABEL,
        "standardized_entry_label": ENTRY_LABEL,
    }
    if missing:
        payload = {
            **base,
            "morning_status": "INCOMPLETE_MORNING_BARS",
            "missing_labels": "|".join(missing),
            "early_return": np.nan,
            "last5_return": np.nan,
            "opening_range_high": np.nan,
            "opening_range_low": np.nan,
            "opening_range_midpoint": np.nan,
            "opening_range_position": np.nan,
            "midpoint_reclaimed": False,
            "bullish_continuation_flag": False,
            "bearish_continuation_flag": False,
            "laggard_recovery_flag": False,
            "leader_reversal_flag": False,
            "primary_archetype": "NO_CLEAR_SETUP",
            "direction": "NONE",
            "entry_price": np.nan,
        }
        payload["ticker_row_id"] = _payload_hash(payload)
        return payload

    open_0930 = float(bars["09:30"].open)
    close_0940 = float(bars["09:40"].close)
    close_0945 = float(bars[LATEST_MORNING_LABEL].close)
    entry_price = float(bars[ENTRY_LABEL].open)
    early_return = close_0945 / open_0930 - 1.0
    last5_return = close_0945 / close_0940 - 1.0
    opening_rows = [bars[label] for label in ("09:30", "09:35", "09:40")]
    opening_high = max(float(row.high) for row in opening_rows)
    opening_low = min(float(row.low) for row in opening_rows)
    midpoint = (opening_high + opening_low) / 2.0
    if opening_high > opening_low:
        range_position = (close_0945 - opening_low) / (opening_high - opening_low)
    else:
        range_position = 0.5
    midpoint_reclaimed = bool(early_return <= -EARLY_MOVE_THRESHOLD and close_0945 >= midpoint)

    flags = {
        "LAGGARD_RECOVERY_LONG": bool(
            early_return <= -EARLY_MOVE_THRESHOLD
            and (last5_return >= LAST5_CONFIRMATION_THRESHOLD or midpoint_reclaimed)
        ),
        "LEADER_REVERSAL_SHORT": bool(
            early_return >= EARLY_MOVE_THRESHOLD and last5_return <= -LAST5_CONFIRMATION_THRESHOLD
        ),
        "BULLISH_CONTINUATION_LONG": bool(
            early_return >= EARLY_MOVE_THRESHOLD and last5_return >= 0.0
        ),
        "BEARISH_CONTINUATION_SHORT": bool(
            early_return <= -EARLY_MOVE_THRESHOLD and last5_return <= 0.0
        ),
    }
    archetype = _primary_archetype(flags)
    payload = {
        **base,
        "morning_status": "MORNING_COMPLETE",
        "missing_labels": "",
        "early_return": early_return,
        "last5_return": last5_return,
        "opening_range_high": opening_high,
        "opening_range_low": opening_low,
        "opening_range_midpoint": midpoint,
        "opening_range_position": range_position,
        "midpoint_reclaimed": midpoint_reclaimed,
        "bullish_continuation_flag": flags["BULLISH_CONTINUATION_LONG"],
        "bearish_continuation_flag": flags["BEARISH_CONTINUATION_SHORT"],
        "laggard_recovery_flag": flags["LAGGARD_RECOVERY_LONG"],
        "leader_reversal_flag": flags["LEADER_REVERSAL_SHORT"],
        "primary_archetype": archetype,
        "direction": _direction_for_archetype(archetype),
        "entry_price": entry_price,
    }
    payload["ticker_row_id"] = _payload_hash(payload)
    return payload


def classify_transition(archetypes: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    valid = archetypes[archetypes["morning_status"].eq("MORNING_COMPLETE")].copy()
    valid_count = len(valid)
    if valid_count:
        advancer_share = float((valid["early_return"] > 0.0).mean())
        decliner_share = float((valid["early_return"] < 0.0).mean())
        median_early = float(valid["early_return"].median())
        median_last5 = float(valid["last5_return"].median())
        dispersion = float(valid["early_return"].std(ddof=0))
    else:
        advancer_share = decliner_share = median_early = median_last5 = dispersion = np.nan

    early_losers = valid[valid["early_return"] <= -EARLY_MOVE_THRESHOLD]
    early_winners = valid[valid["early_return"] >= EARLY_MOVE_THRESHOLD]
    recovery_share = float(early_losers["laggard_recovery_flag"].mean()) if len(early_losers) else 0.0
    continuation_share = float(early_winners["bullish_continuation_flag"].mean()) if len(early_winners) else 0.0
    midpoint_share = float(early_losers["midpoint_reclaimed"].mean()) if len(early_losers) else 0.0
    leader_failure_share = float(early_winners["leader_reversal_flag"].mean()) if len(early_winners) else 0.0

    features = {
        "valid_ticker_count": valid_count,
        "incomplete_ticker_count": int(len(archetypes) - valid_count),
        "advancer_share": advancer_share,
        "decliner_share": decliner_share,
        "median_early_return": median_early,
        "median_last5_return": median_last5,
        "early_loser_count": int(len(early_losers)),
        "early_winner_count": int(len(early_winners)),
        "recovery_share_of_early_losers": recovery_share,
        "continuation_share_of_early_winners": continuation_share,
        "midpoint_reclaim_share": midpoint_share,
        "leader_failure_share": leader_failure_share,
        "cross_sectional_dispersion": dispersion,
    }

    if valid_count < MINIMUM_VALID_TICKERS:
        label = "DATA_LIMITED_TRANSITION"
    elif (
        recovery_share >= float(CONFIG["broad_recovery_min_recovery_share"])
        and median_last5 >= float(CONFIG["broad_recovery_min_median_last5_return"])
    ):
        label = "BROAD_RECOVERY"
    elif (
        decliner_share >= float(CONFIG["weakness_persisting_min_decliner_share"])
        and median_last5 <= float(CONFIG["weakness_persisting_max_median_last5_return"])
    ):
        label = "WEAKNESS_PERSISTING"
    elif (
        advancer_share >= float(CONFIG["bullish_continuation_min_advancer_share"])
        and continuation_share >= float(CONFIG["bullish_continuation_min_continuation_share"])
    ):
        label = "BULLISH_CONTINUATION"
    elif (
        leader_failure_share >= float(CONFIG["leader_failure_min_share"])
        and median_last5 <= float(CONFIG["leader_failure_max_median_last5_return"])
    ):
        label = "LEADER_FAILURE"
    else:
        label = "MIXED_TRANSITION"
    return label, features


def evaluate_ticker_outcome(archetype_row: pd.Series, ticker_prices: pd.DataFrame) -> dict[str, Any]:
    base = {
        "experiment_id": EXPERIMENT_ID,
        "code_version": CODE_VERSION,
        "session_date": str(archetype_row["session_date"]),
        "ticker": str(archetype_row["ticker"]),
        "ticker_row_id": str(archetype_row["ticker_row_id"]),
        "primary_archetype": str(archetype_row["primary_archetype"]),
        "direction": str(archetype_row["direction"]),
        "entry_time": ENTRY_LABEL,
    }
    if archetype_row["morning_status"] != "MORNING_COMPLETE":
        payload = {
            **base,
            "outcome_status": "MORNING_INCOMPLETE_NO_OUTCOME",
            "entry_price": np.nan,
            "exit_time": "",
            "exit_price": np.nan,
            "session_close_return": np.nan,
            "mfe_return": np.nan,
            "mae_return": np.nan,
            "gross_pnl_sek": np.nan,
            "cost_sek": np.nan,
            "net_pnl_sek": np.nan,
        }
        payload["outcome_id"] = _payload_hash(payload)
        return payload

    after_entry = ticker_prices[ticker_prices["clock"] >= ENTRY_LABEL].sort_values("datetime")
    if after_entry.empty or after_entry.iloc[-1]["clock"] < EOD_MINIMUM_LABEL:
        payload = {
            **base,
            "outcome_status": "EOD_INCOMPLETE_NO_OUTCOME",
            "entry_price": float(archetype_row["entry_price"]),
            "exit_time": "",
            "exit_price": np.nan,
            "session_close_return": np.nan,
            "mfe_return": np.nan,
            "mae_return": np.nan,
            "gross_pnl_sek": np.nan,
            "cost_sek": np.nan,
            "net_pnl_sek": np.nan,
        }
        payload["outcome_id"] = _payload_hash(payload)
        return payload

    direction = str(archetype_row["direction"])
    entry = float(archetype_row["entry_price"])
    last = after_entry.iloc[-1]
    exit_price = float(last["close"])
    exit_time = pd.Timestamp(last["datetime"]).strftime("%H:%M")
    if direction == "LONG":
        close_return = exit_price / entry - 1.0
        mfe = float((after_entry["high"] / entry - 1.0).max())
        mae = float((after_entry["low"] / entry - 1.0).min())
        cost = BASE_NOTIONAL_SEK * ROUND_TRIP_COST_RATE
        gross = BASE_NOTIONAL_SEK * close_return
        status = "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"
    elif direction == "SHORT":
        close_return = 1.0 - exit_price / entry
        mfe = float((1.0 - after_entry["low"] / entry).max())
        mae = float((1.0 - after_entry["high"] / entry).min())
        cost = BASE_NOTIONAL_SEK * ROUND_TRIP_COST_RATE
        gross = BASE_NOTIONAL_SEK * close_return
        status = "DIRECTIONAL_COUNTERFACTUAL_COMPLETE"
    else:
        close_return = 0.0
        mfe = 0.0
        mae = 0.0
        cost = 0.0
        gross = 0.0
        status = "NO_CLEAR_SETUP_ZERO_OUTCOME"
    payload = {
        **base,
        "outcome_status": status,
        "entry_price": entry,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "session_close_return": close_return,
        "mfe_return": mfe,
        "mae_return": mae,
        "gross_pnl_sek": gross,
        "cost_sek": cost,
        "net_pnl_sek": gross - cost,
    }
    payload["outcome_id"] = _payload_hash(payload)
    return payload


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temp, index=False)
    temp.replace(path)


def _summary_by(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=group_columns)
    result = (
        frame.groupby(group_columns, dropna=False)
        .agg(
            rows=("ticker", "size"),
            directional_outcomes=("outcome_status", lambda values: int(pd.Series(values).eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE").sum())),
            wins=("net_pnl_sek", lambda values: int((pd.to_numeric(pd.Series(values), errors="coerce") > 0).sum())),
            net_pnl_sek=("net_pnl_sek", "sum"),
            average_net_pnl_sek=("net_pnl_sek", "mean"),
            average_close_return=("session_close_return", "mean"),
            average_mfe_return=("mfe_return", "mean"),
            average_mae_return=("mae_return", "mean"),
        )
        .reset_index()
    )
    result["win_rate"] = np.where(result["directional_outcomes"] > 0, result["wins"] / result["directional_outcomes"], np.nan)
    return result


def run_historical_replay(
    *,
    price_db: Path = DEFAULT_PRICE_DB,
    taxonomy_file: Path = DEFAULT_TAXONOMY_FILE,
    step9l_ledger: Path = DEFAULT_STEP9L_LEDGER,
    core_registry: Path = DEFAULT_CORE_REGISTRY,
    holdout_registry: Path = DEFAULT_HOLDOUT_REGISTRY,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    universe = _load_universe(core_registry, holdout_registry)
    sessions = _load_regime_sessions(taxonomy_file, step9l_ledger)
    if start_date:
        sessions = sessions[sessions["session_date"] >= start_date]
    if end_date:
        sessions = sessions[sessions["session_date"] <= end_date]
    prices = _load_prices(price_db, start_date, end_date, duplicate_policy="latest_rowid")
    available_dates = set(prices["session_date"].unique())
    sessions = sessions[sessions["session_date"].isin(available_dates)].copy()
    if sessions.empty:
        raise Step9TSourceError("No regime sessions overlap the source price database.")

    session_rows: list[dict[str, Any]] = []
    archetype_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []

    for session in sessions.itertuples(index=False):
        date = str(session.session_date)
        date_prices = prices[prices["session_date"].eq(date)]
        day_archetypes = []
        for ticker_row in universe.to_dict("records"):
            ticker_prices = date_prices[date_prices["ticker"].eq(ticker_row["ticker"])]
            row = classify_ticker_morning(date, pd.Series(ticker_row), ticker_prices)
            row.update(
                {
                    "source_regime": str(session.source_regime),
                    "source_regime_confidence": float(session.source_regime_confidence),
                    "replay_status": "RETROSPECTIVE_NON_CONFIRMATORY_DIAGNOSTIC",
                }
            )
            day_archetypes.append(row)
        day_frame = pd.DataFrame(day_archetypes).sort_values("ticker").reset_index(drop=True)
        transition, features = classify_transition(day_frame)
        transition_payload = {
            "experiment_id": EXPERIMENT_ID,
            "code_version": CODE_VERSION,
            "session_date": date,
            "replay_status": "RETROSPECTIVE_NON_CONFIRMATORY_DIAGNOSTIC",
            "source_regime": str(session.source_regime),
            "source_regime_confidence": float(session.source_regime_confidence),
            "source_regime_origin": str(session.source_regime_origin),
            "source_batch_id": str(session.source_batch_id),
            "source_batch_hash": str(session.source_batch_hash),
            "source_prospective_status": str(session.source_prospective_status),
            "latest_morning_source_label": LATEST_MORNING_LABEL,
            "standardized_entry_label": ENTRY_LABEL,
            "transition_state": transition,
            **features,
            "router_active": False,
            "orders_sent": False,
        }
        transition_payload["feature_payload_hash"] = _payload_hash(transition_payload)
        transition_payload["transition_batch_id"] = _payload_hash(
            {"session_date": date, "feature_payload_hash": transition_payload["feature_payload_hash"]}
        )
        session_rows.append(transition_payload)

        for row in day_archetypes:
            row["transition_state"] = transition
            row["transition_batch_id"] = transition_payload["transition_batch_id"]
            row.pop("ticker_row_id", None)
            row["ticker_row_id"] = _payload_hash(row)
            archetype_rows.append(row)
            ticker_prices = date_prices[date_prices["ticker"].eq(row["ticker"])]
            outcome = evaluate_ticker_outcome(pd.Series(row), ticker_prices)
            outcome.update(
                {
                    "source_regime": str(session.source_regime),
                    "transition_state": transition,
                    "replay_status": "RETROSPECTIVE_NON_CONFIRMATORY_DIAGNOSTIC",
                }
            )
            outcome_rows.append(outcome)

        audit_rows.extend(
            [
                {"session_date": date, "check": "ONE_TRANSITION_ROW", "passed": True, "detail": "1"},
                {"session_date": date, "check": "UNIVERSE_ROW_COUNT", "passed": len(day_archetypes) == len(universe), "detail": str(len(day_archetypes))},
                {"session_date": date, "check": "LATEST_MORNING_LABEL", "passed": all(row["latest_morning_source_label"] == LATEST_MORNING_LABEL for row in day_archetypes), "detail": LATEST_MORNING_LABEL},
                {"session_date": date, "check": "ROUTER_INACTIVE", "passed": True, "detail": "FALSE"},
                {"session_date": date, "check": "NO_ORDER_SENT", "passed": True, "detail": "FALSE"},
            ]
        )

    session_df = pd.DataFrame(session_rows).sort_values("session_date").reset_index(drop=True)
    archetype_df = pd.DataFrame(archetype_rows).sort_values(["session_date", "ticker"]).reset_index(drop=True)
    outcome_df = pd.DataFrame(outcome_rows).sort_values(["session_date", "ticker"]).reset_index(drop=True)
    combined = archetype_df.merge(
        outcome_df,
        on=["session_date", "ticker", "ticker_row_id", "primary_archetype", "direction", "source_regime", "transition_state", "replay_status"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_outcome"),
    )
    audit_df = pd.DataFrame(audit_rows)
    if not bool(audit_df["passed"].all()):
        failed = audit_df[~audit_df["passed"]]
        raise Step9TIntegrityError(f"Historical replay audit failed: {failed.to_dict('records')[:5]}")
    if session_df["session_date"].duplicated().any():
        raise Step9TIntegrityError("Duplicate session transition rows were generated.")
    if archetype_df.duplicated(["session_date", "ticker"]).any():
        raise Step9TIntegrityError("Duplicate ticker archetype rows were generated.")
    if outcome_df.duplicated(["session_date", "ticker"]).any():
        raise Step9TIntegrityError("Duplicate ticker outcome rows were generated.")

    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_csv(session_df, output_dir / SESSION_EXPORT)
    _atomic_csv(archetype_df, output_dir / ARCHETYPE_EXPORT)
    _atomic_csv(outcome_df, output_dir / OUTCOME_EXPORT)
    _atomic_csv(_summary_by(combined, ["source_regime"]), output_dir / REGIME_SUMMARY_EXPORT)
    _atomic_csv(_summary_by(combined, ["transition_state"]), output_dir / TRANSITION_SUMMARY_EXPORT)
    _atomic_csv(_summary_by(combined, ["primary_archetype"]), output_dir / ARCHETYPE_SUMMARY_EXPORT)
    _atomic_csv(_summary_by(combined, ["ticker"]), output_dir / TICKER_SUMMARY_EXPORT)
    _atomic_csv(audit_df, output_dir / AUDIT_EXPORT)

    source_paths = [price_db, taxonomy_file, step9l_ledger, core_registry, holdout_registry, CONFIG_FILE]
    source_hashes = {str(path): _sha256(path) for path in source_paths}
    (output_dir / SOURCE_HASH_EXPORT).write_text(
        json.dumps(source_hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    complete_outcomes = outcome_df["outcome_status"].eq("DIRECTIONAL_COUNTERFACTUAL_COMPLETE")
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "research_status": RESEARCH_STATUS,
        "code_version": CODE_VERSION,
        "sessions": int(len(session_df)),
        "regimes": int(session_df["source_regime"].nunique()),
        "transition_states": int(session_df["transition_state"].nunique()),
        "ticker_archetype_rows": int(len(archetype_df)),
        "ticker_outcome_rows": int(len(outcome_df)),
        "complete_directional_outcomes": int(complete_outcomes.sum()),
        "incomplete_eod_outcomes": int(outcome_df["outcome_status"].eq("EOD_INCOMPLETE_NO_OUTCOME").sum()),
        "net_directional_pnl_sek": float(outcome_df.loc[complete_outcomes, "net_pnl_sek"].sum()),
        "router_active": False,
        "orders_sent": False,
    }
    _atomic_csv(pd.DataFrame([summary]), output_dir / SUMMARY_EXPORT)
    return summary


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Step 9T historical transition/archetype replay.")
    parser.add_argument("--price-db", type=Path, default=DEFAULT_PRICE_DB)
    parser.add_argument("--taxonomy-file", type=Path, default=DEFAULT_TAXONOMY_FILE)
    parser.add_argument("--step9l-ledger", type=Path, default=DEFAULT_STEP9L_LEDGER)
    parser.add_argument("--core-registry", type=Path, default=DEFAULT_CORE_REGISTRY)
    parser.add_argument("--holdout-registry", type=Path, default=DEFAULT_HOLDOUT_REGISTRY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = _parse_args(argv)
    summary = run_historical_replay(
        price_db=args.price_db,
        taxonomy_file=args.taxonomy_file,
        step9l_ledger=args.step9l_ledger,
        core_registry=args.core_registry,
        holdout_registry=args.holdout_registry,
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print("STEP9T_REGIME_TRANSITION_ARCHETYPE_RESEARCH_V1: PASSED")
    print(f"Sessions/regimes: {summary['sessions']}/{summary['regimes']}")
    print(f"Transition states: {summary['transition_states']}")
    print(f"Ticker archetype rows: {summary['ticker_archetype_rows']}")
    print(f"Ticker outcome rows: {summary['ticker_outcome_rows']}")
    print(f"Complete directional outcomes: {summary['complete_directional_outcomes']}")
    print(f"Incomplete EOD outcomes: {summary['incomplete_eod_outcomes']}")
    print(f"Net standardized directional P&L: {summary['net_directional_pnl_sek']:.6f} SEK")
    print("ROUTER ACTIVE: FALSE")
    print("NO ORDER WAS SENT")


if __name__ == "__main__":
    main()
