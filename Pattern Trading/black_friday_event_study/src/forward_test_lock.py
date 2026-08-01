from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .settings import OUTPUT_DIR


LOCK_VERSION = "1.0.0"
LOCK_CREATED_DATE = "2026-07-22"
EVENT_YEAR = 2026
EVENT_RELATIVE_DAY = 0
ENTRY_RELATIVE_DAY = -4
EXIT_RELATIVE_DAY = 1
ROUND_TRIP_COSTS_BPS = [25, 50]

IMPLEMENTATIONS: dict[str, dict[str, Any]] = {
    "AMZN": {
        "components": {"AMZN": 1.0},
        "role": "single_stock_return_benchmark",
        "historical_sample": "Full_available_history",
    },
    "WMT": {
        "components": {"WMT": 1.0},
        "role": "defensive_recent_regime_benchmark",
        "historical_sample": "Validation_2019_2025",
    },
    "ETSY": {
        "components": {"ETSY": 1.0},
        "role": "exploratory_high_return_benchmark",
        "historical_sample": "Validation_2019_2025",
    },
    "Portfolio_AMZN50_WMT50": {
        "components": {"AMZN": 0.5, "WMT": 0.5},
        "role": "primary_forward_strategy",
        "historical_sample": "Full_available_history",
    },
    "Portfolio_AMZN40_WMT40_ETSY20": {
        "components": {"AMZN": 0.4, "WMT": 0.4, "ETSY": 0.2},
        "role": "secondary_aggressive_satellite",
        "historical_sample": "Validation_2019_2025",
    },
}

FORWARD_DIR = OUTPUT_DIR / "forward_test_2026"
LOCK_FILE = FORWARD_DIR / "frozen_rules.json"
LOCK_HASH_FILE = FORWARD_DIR / "frozen_rules.sha256"
SCHEDULE_FILE = FORWARD_DIR / "forward_test_schedule.csv"
AUDIT_FILE = FORWARD_DIR / "audit_log.jsonl"
ENTRY_FILE = FORWARD_DIR / "entry_record.json"
EXIT_FILE = FORWARD_DIR / "exit_record.json"
RESULT_FILE = FORWARD_DIR / "forward_test_result.json"
RESULT_CSV_FILE = FORWARD_DIR / "forward_test_result.csv"

FINGERPRINT_CANDIDATES = [
    "src/forward_test_lock.py",
    "src/trading_backtest.py",
    "src/executable_validation.py",
    "src/implementation_risk_analysis.py",
    "output/backtest_trade_results.csv",
    "output/execution_validation_trades.csv",
    "output/execution_validation_summary.csv",
    "output/implementation_risk_annual.csv",
    "output/implementation_risk_summary.csv",
]


class ForwardTestError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError as exc:
        raise ForwardTestError(
            f"Refusing to overwrite existing locked record: {path}"
        ) from exc


def _write_text_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise ForwardTestError(
            f"Refusing to overwrite existing locked record: {path}"
        ) from exc


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ForwardTestError(f"Required file does not exist: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ForwardTestError(f"Expected a JSON object in {path}")
    return payload


def _fourth_thursday_of_november(year: int) -> date:
    november_first = date(year, 11, 1)
    days_until_thursday = (3 - november_first.weekday()) % 7
    first_thursday = november_first.replace(
        day=1 + days_until_thursday
    )
    return first_thursday.replace(day=first_thursday.day + 21)


def _black_friday(year: int) -> date:
    thanksgiving = _fourth_thursday_of_november(year)
    return date.fromordinal(thanksgiving.toordinal() + 1)


def _is_market_session(candidate: date, thanksgiving: date) -> bool:
    return candidate.weekday() < 5 and candidate != thanksgiving


def _session_offset(event_date: date, offset: int) -> date:
    if offset == 0:
        return event_date

    thanksgiving = _fourth_thursday_of_november(event_date.year)
    direction = 1 if offset > 0 else -1
    current = event_date
    sessions_moved = 0

    while sessions_moved < abs(offset):
        current = date.fromordinal(current.toordinal() + direction)
        if _is_market_session(current, thanksgiving):
            sessions_moved += 1
    return current


def _event_schedule() -> list[dict[str, Any]]:
    event_date = _black_friday(EVENT_YEAR)
    rows: list[dict[str, Any]] = []
    for relative_day in range(ENTRY_RELATIVE_DAY, EXIT_RELATIVE_DAY + 1):
        session_date = _session_offset(event_date, relative_day)
        rows.append(
            {
                "event_year": EVENT_YEAR,
                "relative_day": relative_day,
                "date": session_date.isoformat(),
                "role": (
                    "entry_close"
                    if relative_day == ENTRY_RELATIVE_DAY
                    else "black_friday_event"
                    if relative_day == EVENT_RELATIVE_DAY
                    else "exit_close"
                    if relative_day == EXIT_RELATIVE_DAY
                    else "holding_return_day"
                ),
                "notes": (
                    "NYSE early-close session expected"
                    if relative_day == EVENT_RELATIVE_DAY
                    else ""
                ),
            }
        )
    return rows


def _project_root() -> Path:
    return OUTPUT_DIR.parent


def _fingerprint_historical_artifacts() -> list[dict[str, Any]]:
    root = _project_root()
    rows: list[dict[str, Any]] = []
    for relative_path in FINGERPRINT_CANDIDATES:
        path = root / relative_path
        if path.exists() and path.is_file():
            rows.append(
                {
                    "relative_path": relative_path,
                    "exists_at_lock": True,
                    "size_bytes": int(path.stat().st_size),
                    "sha256": _sha256_file(path),
                }
            )
        else:
            rows.append(
                {
                    "relative_path": relative_path,
                    "exists_at_lock": False,
                    "size_bytes": None,
                    "sha256": None,
                }
            )
    return rows


def _build_lock_payload() -> dict[str, Any]:
    schedule = _event_schedule()
    schedule_by_day = {int(row["relative_day"]): row["date"] for row in schedule}

    rules: dict[str, Any] = {
        "lock_version": LOCK_VERSION,
        "lock_created_date": LOCK_CREATED_DATE,
        "lock_created_at_utc": _utc_now().isoformat(),
        "research_status": "historical_research_locked_before_2026_event",
        "event": {
            "name": "Black Friday",
            "event_year": EVENT_YEAR,
            "event_date": schedule_by_day[EVENT_RELATIVE_DAY],
            "entry_relative_day": ENTRY_RELATIVE_DAY,
            "entry_date": schedule_by_day[ENTRY_RELATIVE_DAY],
            "exit_relative_day": EXIT_RELATIVE_DAY,
            "exit_date": schedule_by_day[EXIT_RELATIVE_DAY],
            "return_relative_days": list(
                range(ENTRY_RELATIVE_DAY + 1, EXIT_RELATIVE_DAY + 1)
            ),
            "calendar_method": (
                "Black Friday is the day after the fourth Thursday of November; "
                "relative trading sessions skip Thanksgiving and weekends."
            ),
        },
        "strategy_rules": {
            "direction": "long_only",
            "entry_execution": "close_on_relative_day_minus_4",
            "exit_execution": "close_on_relative_day_plus_1",
            "weighting": "fixed_initial_capital_weights",
            "rebalancing_during_trade": False,
            "stop_loss": None,
            "profit_target": None,
            "hedging": None,
            "round_trip_cost_scenarios_bps": ROUND_TRIP_COSTS_BPS,
            "official_primary_strategy": "Portfolio_AMZN50_WMT50",
            "official_secondary_strategy": "Portfolio_AMZN40_WMT40_ETSY20",
            "entry_timing_shadow_study_changes_official_rule": False,
        },
        "implementations": IMPLEMENTATIONS,
        "schedule": schedule,
        "historical_artifact_fingerprints": _fingerprint_historical_artifacts(),
        "governance": {
            "no_rule_changes_after_lock": True,
            "no_overwrite_of_entry_record": True,
            "no_overwrite_of_exit_record": True,
            "no_overwrite_of_result_record": True,
            "record_all_results_whether_positive_or_negative": True,
            "forward_result_must_not_trigger_retroactive_rule_change": True,
        },
    }

    digest = _sha256_bytes(_canonical_json(rules))
    rules["rules_sha256"] = digest
    rules["lock_id"] = f"BF2026-{digest[:16]}"
    return rules


def _verify_self_hashed_payload(payload: dict[str, Any], hash_field: str) -> bool:
    expected = payload.get(hash_field)
    if not isinstance(expected, str):
        return False
    candidate = dict(payload)
    candidate.pop(hash_field, None)
    return _sha256_bytes(_canonical_json(candidate)) == expected


def _self_hash_payload(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    candidate = dict(payload)
    candidate.pop(hash_field, None)
    candidate[hash_field] = _sha256_bytes(_canonical_json(candidate))
    return candidate


def _verify_lock() -> dict[str, Any]:
    rules = _read_json(LOCK_FILE)
    expected_hash = rules.get("rules_sha256")
    candidate = dict(rules)
    candidate.pop("rules_sha256", None)
    candidate.pop("lock_id", None)
    calculated_hash = _sha256_bytes(_canonical_json(candidate))
    if not isinstance(expected_hash, str) or calculated_hash != expected_hash:
        raise ForwardTestError("Frozen-rules JSON hash verification failed.")

    if not LOCK_HASH_FILE.exists():
        raise ForwardTestError("Frozen-rules hash sidecar is missing.")
    sidecar_hash = LOCK_HASH_FILE.read_text(encoding="utf-8").strip()
    if sidecar_hash != rules["rules_sha256"]:
        raise ForwardTestError("Frozen-rules sidecar hash does not match JSON.")
    return rules


def _read_audit_events() -> list[dict[str, Any]]:
    if not AUDIT_FILE.exists():
        return []
    events: list[dict[str, Any]] = []
    with AUDIT_FILE.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ForwardTestError(
                    f"Invalid audit JSON on line {line_number}."
                ) from exc
            if not isinstance(event, dict):
                raise ForwardTestError(
                    f"Audit event on line {line_number} is not an object."
                )
            events.append(event)
    return events


def _verify_audit_chain() -> int:
    events = _read_audit_events()
    previous_hash = "GENESIS"
    expected_sequence = 1

    for event in events:
        if event.get("sequence") != expected_sequence:
            raise ForwardTestError("Audit sequence is broken.")
        if event.get("previous_event_hash") != previous_hash:
            raise ForwardTestError("Audit previous-hash chain is broken.")
        stored_hash = event.get("event_hash")
        candidate = dict(event)
        candidate.pop("event_hash", None)
        calculated_hash = _sha256_bytes(_canonical_json(candidate))
        if stored_hash != calculated_hash:
            raise ForwardTestError("Audit event hash verification failed.")
        previous_hash = str(stored_hash)
        expected_sequence += 1

    return len(events)


def _append_audit(event_type: str, details: dict[str, Any]) -> None:
    events = _read_audit_events()
    if events:
        _verify_audit_chain()
        previous_hash = str(events[-1]["event_hash"])
        sequence = int(events[-1]["sequence"]) + 1
    else:
        previous_hash = "GENESIS"
        sequence = 1

    event: dict[str, Any] = {
        "sequence": sequence,
        "timestamp_utc": _utc_now().isoformat(),
        "event_type": event_type,
        "previous_event_hash": previous_hash,
        "details": details,
    }
    event["event_hash"] = _sha256_bytes(_canonical_json(event))

    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_FILE.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False))
        handle.write("\n")


def initialize_lock() -> None:
    if LOCK_FILE.exists() or LOCK_HASH_FILE.exists():
        raise ForwardTestError(
            "The 2026 research lock already exists. Use the status or verify command."
        )

    FORWARD_DIR.mkdir(parents=True, exist_ok=True)
    rules = _build_lock_payload()
    _write_json_exclusive(LOCK_FILE, rules)
    _write_text_exclusive(LOCK_HASH_FILE, rules["rules_sha256"] + "\n")

    schedule = pd.DataFrame(rules["schedule"])
    try:
        schedule.to_csv(SCHEDULE_FILE, index=False, mode="x")
    except FileExistsError as exc:
        raise ForwardTestError(
            f"Refusing to overwrite existing schedule: {SCHEDULE_FILE}"
        ) from exc

    _append_audit(
        "research_lock_initialized",
        {
            "lock_id": rules["lock_id"],
            "rules_sha256": rules["rules_sha256"],
            "entry_date": rules["event"]["entry_date"],
            "exit_date": rules["event"]["exit_date"],
        },
    )

    print("2026 forward-test research lock created.")
    print(f"Lock ID: {rules['lock_id']}")
    print(f"Entry close: {rules['event']['entry_date']}")
    print(f"Black Friday: {rules['event']['event_date']}")
    print(f"Exit close: {rules['event']['exit_date']}")
    print(f"Locked files: {FORWARD_DIR}")


def _current_integrity_rows(rules: dict[str, Any]) -> list[dict[str, Any]]:
    root = _project_root()
    rows: list[dict[str, Any]] = []
    for locked in rules.get("historical_artifact_fingerprints", []):
        relative_path = str(locked["relative_path"])
        path = root / relative_path
        exists_now = path.exists() and path.is_file()
        current_hash = _sha256_file(path) if exists_now else None
        locked_hash = locked.get("sha256")
        rows.append(
            {
                "relative_path": relative_path,
                "exists_at_lock": bool(locked.get("exists_at_lock")),
                "exists_now": exists_now,
                "locked_sha256": locked_hash,
                "current_sha256": current_hash,
                "status": (
                    "unchanged"
                    if locked.get("exists_at_lock") and exists_now and locked_hash == current_hash
                    else "missing_both"
                    if not locked.get("exists_at_lock") and not exists_now
                    else "created_after_lock"
                    if not locked.get("exists_at_lock") and exists_now
                    else "missing_after_lock"
                    if locked.get("exists_at_lock") and not exists_now
                    else "changed_after_lock"
                ),
            }
        )
    return rows


def verify_all() -> dict[str, Any]:
    rules = _verify_lock()
    audit_count = _verify_audit_chain()

    record_status: dict[str, str] = {}
    for name, path in [
        ("entry", ENTRY_FILE),
        ("exit", EXIT_FILE),
        ("result", RESULT_FILE),
    ]:
        if not path.exists():
            record_status[name] = "not_created"
            continue
        payload = _read_json(path)
        field = f"{name}_record_sha256" if name != "result" else "result_record_sha256"
        if not _verify_self_hashed_payload(payload, field):
            raise ForwardTestError(f"{name.title()} record hash verification failed.")
        if payload.get("lock_id") != rules.get("lock_id"):
            raise ForwardTestError(f"{name.title()} record belongs to another lock.")
        record_status[name] = "verified"

    integrity_rows = _current_integrity_rows(rules)
    changed = [
        row
        for row in integrity_rows
        if row["status"] in {"changed_after_lock", "missing_after_lock"}
    ]

    return {
        "lock_id": rules["lock_id"],
        "audit_events_verified": audit_count,
        "record_status": record_status,
        "historical_artifact_integrity": integrity_rows,
        "historical_artifacts_changed_or_missing": len(changed),
    }


def print_verify() -> None:
    result = verify_all()
    print("Forward-test integrity verification passed.")
    print(f"Lock ID: {result['lock_id']}")
    print(f"Audit events verified: {result['audit_events_verified']}")
    for name, status in result["record_status"].items():
        print(f"{name.title()} record: {status}")

    changed_rows = [
        row
        for row in result["historical_artifact_integrity"]
        if row["status"] not in {"unchanged", "missing_both"}
    ]
    if changed_rows:
        print("Historical artifact notices:")
        for row in changed_rows:
            print(f"  {row['status']}: {row['relative_path']}")
    else:
        print("Historical artifact fingerprints: unchanged.")


def print_status() -> None:
    rules = _verify_lock()
    _verify_audit_chain()
    now = _utc_now().date()
    entry_date = date.fromisoformat(rules["event"]["entry_date"])
    exit_date = date.fromisoformat(rules["event"]["exit_date"])

    print(f"Lock ID: {rules['lock_id']}")
    print(f"Current UTC date: {now.isoformat()}")
    print(f"Entry close: {entry_date.isoformat()}")
    print(f"Exit close: {exit_date.isoformat()}")
    print(f"Days until entry: {(entry_date - now).days}")
    print(f"Entry record: {'created' if ENTRY_FILE.exists() else 'pending'}")
    print(f"Exit record: {'created' if EXIT_FILE.exists() else 'pending'}")
    print(f"Result record: {'created' if RESULT_FILE.exists() else 'pending'}")


def _load_database_prices(expected_date: date) -> dict[str, float]:
    try:
        from .database import read_table
    except ImportError as exc:
        raise ForwardTestError("Could not import the project database helper.") from exc

    prices = read_table("daily_prices")
    required_columns = {"ticker", "date", "adjusted_close"}
    missing = required_columns - set(prices.columns)
    if missing:
        raise ForwardTestError(
            "daily_prices is missing columns: " + ", ".join(sorted(missing))
        )

    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    prices["adjusted_close"] = pd.to_numeric(
        prices["adjusted_close"], errors="coerce"
    )

    result: dict[str, float] = {}
    for ticker in ["AMZN", "WMT", "ETSY"]:
        rows = prices[
            prices["ticker"].eq(ticker) & prices["date"].eq(expected_date)
        ]["adjusted_close"].dropna()
        if len(rows) != 1:
            raise ForwardTestError(
                f"Expected exactly one adjusted close for {ticker} on "
                f"{expected_date.isoformat()}, found {len(rows)}."
            )
        result[ticker] = float(rows.iloc[0])
    return result


def _prices_from_args(args: argparse.Namespace, expected_date: date) -> dict[str, float]:
    if args.from_database:
        manual_values = [args.amzn_price, args.wmt_price, args.etsy_price]
        if any(value is not None for value in manual_values):
            raise ForwardTestError(
                "Use either --from-database or manual prices, not both."
            )
        return _load_database_prices(expected_date)

    values = {
        "AMZN": args.amzn_price,
        "WMT": args.wmt_price,
        "ETSY": args.etsy_price,
    }
    missing = [ticker for ticker, value in values.items() if value is None]
    if missing:
        raise ForwardTestError(
            "Manual recording requires all prices. Missing: " + ", ".join(missing)
        )

    result: dict[str, float] = {}
    for ticker, value in values.items():
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0:
            raise ForwardTestError(f"Invalid price for {ticker}: {value}")
        result[ticker] = numeric
    return result


def _record_market_prices(
    record_type: str,
    target_file: Path,
    expected_date: date,
    prices: dict[str, float],
    source: str,
    note: str,
) -> None:
    rules = _verify_lock()
    _verify_audit_chain()

    if target_file.exists():
        raise ForwardTestError(
            f"The {record_type} record already exists and cannot be overwritten."
        )

    now = _utc_now()
    if now.date() < expected_date:
        raise ForwardTestError(
            f"Cannot record {record_type} prices before {expected_date.isoformat()}."
        )

    if record_type == "exit" and not ENTRY_FILE.exists():
        raise ForwardTestError("Entry prices must be recorded before exit prices.")

    record: dict[str, Any] = {
        "record_type": record_type,
        "lock_id": rules["lock_id"],
        "rules_sha256": rules["rules_sha256"],
        "expected_market_date": expected_date.isoformat(),
        "recorded_at_utc": now.isoformat(),
        "calendar_days_after_expected_date": (now.date() - expected_date).days,
        "price_source": source,
        "prices": {ticker: float(price) for ticker, price in sorted(prices.items())},
        "note": note,
    }
    hash_field = f"{record_type}_record_sha256"
    record = _self_hash_payload(record, hash_field)
    _write_json_exclusive(target_file, record)

    _append_audit(
        f"{record_type}_prices_recorded",
        {
            "lock_id": rules["lock_id"],
            "expected_market_date": expected_date.isoformat(),
            "price_source": source,
            "record_sha256": record[hash_field],
            "record_file": target_file.name,
        },
    )

    print(f"{record_type.title()} prices recorded and locked.")
    print(f"Market date: {expected_date.isoformat()}")
    for ticker, price in sorted(prices.items()):
        print(f"{ticker}: {price:.6f}")


def record_entry(args: argparse.Namespace) -> None:
    rules = _verify_lock()
    expected_date = date.fromisoformat(rules["event"]["entry_date"])
    prices = _prices_from_args(args, expected_date)
    source = args.price_source or (
        "project_daily_prices_adjusted_close"
        if args.from_database
        else "manual_recording"
    )
    _record_market_prices(
        "entry",
        ENTRY_FILE,
        expected_date,
        prices,
        source,
        args.note or "",
    )


def record_exit(args: argparse.Namespace) -> None:
    rules = _verify_lock()
    expected_date = date.fromisoformat(rules["event"]["exit_date"])
    prices = _prices_from_args(args, expected_date)
    source = args.price_source or (
        "project_daily_prices_adjusted_close"
        if args.from_database
        else "manual_recording"
    )
    _record_market_prices(
        "exit",
        EXIT_FILE,
        expected_date,
        prices,
        source,
        args.note or "",
    )


def _historical_comparison(
    implementation: str,
    cost_bps: int,
    forward_return: float,
) -> dict[str, Any]:
    source_path = OUTPUT_DIR / "execution_validation_trades.csv"
    if not source_path.exists():
        return {
            "status": "historical_source_unavailable",
            "source_file": str(source_path),
        }

    historical = pd.read_csv(source_path)
    required = {"implementation", "trade_type", "cost_bps", "event_year", "net_return"}
    missing = required - set(historical.columns)
    if missing:
        return {
            "status": "historical_source_missing_columns",
            "missing_columns": sorted(missing),
        }

    definition = IMPLEMENTATIONS[implementation]
    sample = definition["historical_sample"]
    filtered = historical[
        historical["implementation"].eq(implementation)
        & historical["trade_type"].eq("LongOnly")
        & pd.to_numeric(historical["cost_bps"], errors="coerce").eq(cost_bps)
    ].copy()
    filtered["event_year"] = pd.to_numeric(
        filtered["event_year"], errors="coerce"
    )
    filtered["net_return"] = pd.to_numeric(
        filtered["net_return"], errors="coerce"
    )
    filtered = filtered.dropna(subset=["event_year", "net_return"])

    if sample == "Validation_2019_2025":
        filtered = filtered[filtered["event_year"] >= 2019]

    values = filtered["net_return"].to_numpy(dtype=float)
    if len(values) == 0:
        return {
            "status": "no_matching_historical_rows",
            "historical_sample": sample,
        }

    percentile = float(100.0 * np.mean(values <= forward_return))
    std = float(np.std(values, ddof=1)) if len(values) > 1 else np.nan
    z_score = (
        float((forward_return - np.mean(values)) / std)
        if np.isfinite(std) and not np.isclose(std, 0.0)
        else None
    )

    return {
        "status": "ok",
        "historical_sample": sample,
        "n_historical_trades": int(len(values)),
        "historical_mean": float(np.mean(values)),
        "historical_median": float(np.median(values)),
        "historical_positive_rate": float(np.mean(values > 0)),
        "historical_minimum": float(np.min(values)),
        "historical_maximum": float(np.max(values)),
        "forward_percentile_vs_history": percentile,
        "forward_z_score_vs_history": z_score,
    }


def finalize_result() -> None:
    rules = _verify_lock()
    _verify_audit_chain()

    if RESULT_FILE.exists() or RESULT_CSV_FILE.exists():
        raise ForwardTestError(
            "The forward-test result already exists and cannot be overwritten."
        )
    if not ENTRY_FILE.exists() or not EXIT_FILE.exists():
        raise ForwardTestError(
            "Both locked entry and exit records are required before finalization."
        )

    entry = _read_json(ENTRY_FILE)
    exit_record = _read_json(EXIT_FILE)
    if not _verify_self_hashed_payload(entry, "entry_record_sha256"):
        raise ForwardTestError("Entry record hash verification failed.")
    if not _verify_self_hashed_payload(exit_record, "exit_record_sha256"):
        raise ForwardTestError("Exit record hash verification failed.")

    entry_prices = {ticker: float(value) for ticker, value in entry["prices"].items()}
    exit_prices = {
        ticker: float(value) for ticker, value in exit_record["prices"].items()
    }
    component_returns = {
        ticker: float(exit_prices[ticker] / entry_prices[ticker] - 1.0)
        for ticker in ["AMZN", "WMT", "ETSY"]
    }

    result_rows: list[dict[str, Any]] = []
    for implementation, definition in IMPLEMENTATIONS.items():
        components: dict[str, float] = definition["components"]
        gross_return = float(
            sum(components[ticker] * component_returns[ticker] for ticker in components)
        )
        for cost_bps in ROUND_TRIP_COSTS_BPS:
            net_return = gross_return - cost_bps / 10_000.0
            historical = _historical_comparison(
                implementation,
                cost_bps,
                net_return,
            )
            result_rows.append(
                {
                    "lock_id": rules["lock_id"],
                    "event_year": EVENT_YEAR,
                    "implementation": implementation,
                    "role": definition["role"],
                    "component_weights": ";".join(
                        f"{ticker}:{weight:.2f}"
                        for ticker, weight in components.items()
                    ),
                    "entry_date": entry["expected_market_date"],
                    "exit_date": exit_record["expected_market_date"],
                    "cost_bps": cost_bps,
                    "gross_return": gross_return,
                    "transaction_cost": cost_bps / 10_000.0,
                    "net_return": net_return,
                    "positive_result": bool(net_return > 0),
                    "historical_comparison": historical,
                }
            )

    result_payload: dict[str, Any] = {
        "lock_id": rules["lock_id"],
        "rules_sha256": rules["rules_sha256"],
        "finalized_at_utc": _utc_now().isoformat(),
        "entry_record_sha256": entry["entry_record_sha256"],
        "exit_record_sha256": exit_record["exit_record_sha256"],
        "entry_prices": entry_prices,
        "exit_prices": exit_prices,
        "component_gross_returns": component_returns,
        "implementation_results": result_rows,
        "interpretation_rule": (
            "Preserve and report the 2026 result whether positive or negative. "
            "Do not alter historical rules after observing it."
        ),
    }
    result_payload = _self_hash_payload(
        result_payload,
        "result_record_sha256",
    )
    _write_json_exclusive(RESULT_FILE, result_payload)

    flat_rows: list[dict[str, Any]] = []
    for row in result_rows:
        historical = row["historical_comparison"]
        history_columns = {
            ("history_status" if key == "status" else key): value
            for key, value in historical.items()
        }
        flat_rows.append(
            {
                key: value
                for key, value in row.items()
                if key != "historical_comparison"
            }
            | history_columns
        )
    pd.DataFrame(flat_rows).to_csv(RESULT_CSV_FILE, index=False, mode="x")

    _append_audit(
        "forward_result_finalized",
        {
            "lock_id": rules["lock_id"],
            "result_record_sha256": result_payload["result_record_sha256"],
            "result_file": RESULT_FILE.name,
            "result_csv_file": RESULT_CSV_FILE.name,
        },
    )

    print("2026 forward-test result finalized and locked.")
    for row in result_rows:
        if row["cost_bps"] == 25 and row["implementation"] in {
            "Portfolio_AMZN50_WMT50",
            "Portfolio_AMZN40_WMT40_ETSY20",
        }:
            print(
                f"{row['implementation']}: "
                f"{100 * row['net_return']:.2f}% net at 25 bps"
            )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze and operate the prospective 2026 Black Friday forward test."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("initialize", help="Create the immutable research lock.")
    subparsers.add_parser("status", help="Show the forward-test state.")
    subparsers.add_parser("verify", help="Verify hashes and the audit chain.")

    for command in ["record-entry", "record-exit"]:
        child = subparsers.add_parser(
            command,
            help=f"Create the non-overwritable {command.split('-')[1]} price record.",
        )
        child.add_argument("--from-database", action="store_true")
        child.add_argument("--amzn-price", type=float)
        child.add_argument("--wmt-price", type=float)
        child.add_argument("--etsy-price", type=float)
        child.add_argument("--price-source", type=str)
        child.add_argument("--note", type=str)

    subparsers.add_parser(
        "finalize",
        help="Calculate and permanently record the 2026 result.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "initialize":
        initialize_lock()
    elif args.command == "status":
        print_status()
    elif args.command == "verify":
        print_verify()
    elif args.command == "record-entry":
        record_entry(args)
    elif args.command == "record-exit":
        record_exit(args)
    elif args.command == "finalize":
        finalize_result()
    else:
        raise ForwardTestError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except ForwardTestError as exc:
        raise SystemExit(f"Forward-test error: {exc}") from exc
