from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from RegimeTrading.core.research_config import ORB_INITIAL_CAPITAL
from RegimeTrading.scripts import step9e_instrument_sector_taxonomy as step9e
from RegimeTrading.scripts import step9g_state_filtered_contract_experiments as step9g
from RegimeTrading.scripts import step9h_cross_sectional_holdout_transport as step9h
from RegimeTrading.scripts import step9i_v2_core5_plus_holdout18_shadow_router as step9i
from RegimeTrading.scripts import step9k_high_dispersion_strategy_research as step9k
from RegimeTrading.scripts import step9l_v3_selected_strategy_shadow_engine as step9l_v3


STEP9QB_STATUS = "READ_ONLY_INTRADAY_TRADE_MONITOR_NOT_ROUTER_ACTIVE"
STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")
BAR_INTERVAL_MINUTES = 5
INITIAL_CAPITAL_SEK = float(ORB_INITIAL_CAPITAL)
CONFIRMATORY_STATUS = "PROSPECTIVE_CONFIRMATORY_ELIGIBLE"
PRIMARY_ROLE = "PRIMARY_HYPOTHESIS"
GUARDRAIL_ROLE = "NEGATIVE_GUARDRAIL"

DECISION_BATCH_COLUMNS = {
    "batch_id",
    "session_date",
    "prospective_status",
    "taxonomy_payload_json",
    "research_max_concurrent_ideas",
}
DECISION_COLUMNS = {
    "decision_id",
    "batch_id",
    "session_date",
    "contract_id",
    "test_role",
    "ticker",
    "company_id",
    "broad_sector",
    "contract_eligible",
    "intended_side",
    "point_in_time_pass",
}
OUTCOME_COLUMNS = {
    "decision_id",
    "session_date",
    "contract_id",
    "test_role",
    "ticker",
    "direction",
    "entry_time",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_time",
    "exit_price",
    "exit_reason",
    "risk_capped_net_pnl_sek",
    "outcome_status",
    "point_in_time_pass",
}
PRICE_COLUMNS = {"datetime", "open", "high", "low", "close", "ticker"}


class Step9QBLiteError(RuntimeError):
    """Raised when the read-only live monitor cannot build a safe snapshot."""


@dataclass
class ReplayFrames:
    candidates: pd.DataFrame
    trades: pd.DataFrame
    last_completed_bar: datetime | None
    replay_status: str


def _sqlite_uri(path: Path) -> str:
    absolute = Path(path).resolve().as_posix()
    return f"file:{quote(absolute, safe='/:')}?mode=ro"


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_sqlite_uri(path), uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _require_columns(
    connection: sqlite3.Connection,
    path: Path,
    table: str,
    required: set[str],
) -> None:
    if table not in _table_names(connection):
        raise Step9QBLiteError(f"Required source table is missing: {path}:{table}")
    missing = sorted(required - _table_columns(connection, table))
    if missing:
        raise Step9QBLiteError(
            f"Source table {path}:{table} is missing columns: {', '.join(missing)}"
        )


def _boolish(value: Any, default: bool = False) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return default


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or pd.isna(value):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(STOCKHOLM_TZ).tz_localize(None)
    return stamp.to_pydatetime()


def _clock(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.strftime("%H:%M") if parsed is not None else ""


def _latest_completed_label(now: datetime, session_date: str) -> str:
    if session_date < now.date().isoformat():
        return "23:59"
    if session_date > now.date().isoformat():
        return ""
    local = now.astimezone(STOCKHOLM_TZ) if now.tzinfo else now.replace(tzinfo=STOCKHOLM_TZ)
    floored_minute = local.minute - (local.minute % BAR_INTERVAL_MINUTES)
    floor = local.replace(minute=floored_minute, second=0, microsecond=0)
    completed = floor - timedelta(minutes=BAR_INTERVAL_MINUTES)
    return completed.strftime("%H:%M")


def _read_decision_sources(
    ledger_path: Path,
    session_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ledger_path = Path(ledger_path)
    if not ledger_path.exists():
        return pd.DataFrame(), pd.DataFrame()
    with closing(_connect_read_only(ledger_path)) as connection:
        _require_columns(
            connection,
            ledger_path,
            "shadow_decision_batches",
            DECISION_BATCH_COLUMNS,
        )
        _require_columns(
            connection,
            ledger_path,
            "shadow_decisions",
            DECISION_COLUMNS,
        )
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
    return batch, decisions


def _read_all_authoritative_outcomes(ledger_path: Path) -> pd.DataFrame:
    ledger_path = Path(ledger_path)
    if not ledger_path.exists():
        return pd.DataFrame()
    with closing(_connect_read_only(ledger_path)) as connection:
        tables = _table_names(connection)
        if "shadow_outcomes" not in tables or "shadow_decision_batches" not in tables:
            return pd.DataFrame()
        missing = OUTCOME_COLUMNS - _table_columns(connection, "shadow_outcomes")
        if missing:
            raise Step9QBLiteError(
                f"Source table {ledger_path}:shadow_outcomes is missing columns: "
                + ", ".join(sorted(missing))
            )
        query = """
            SELECT
                o.*,
                b.prospective_status,
                b.created_at_stockholm AS morning_seal_time_stockholm
            FROM shadow_outcomes AS o
            INNER JOIN shadow_decisions AS d
                ON d.decision_id = o.decision_id
            INNER JOIN shadow_decision_batches AS b
                ON b.batch_id = d.batch_id
            ORDER BY o.session_date, o.contract_id, o.ticker
        """
        return pd.read_sql_query(query, connection)


def _read_prices_through_completed_bar(
    price_db: Path,
    session_date: str,
    now: datetime,
) -> tuple[pd.DataFrame, datetime | None]:
    price_db = Path(price_db)
    if not price_db.exists():
        return pd.DataFrame(), None
    with closing(_connect_read_only(price_db)) as connection:
        _require_columns(connection, price_db, "intraday_prices", PRICE_COLUMNS)
        prices = pd.read_sql_query(
            """
            SELECT datetime, open, high, low, close, ticker
            FROM intraday_prices
            WHERE substr(datetime, 1, 10) <= ?
            ORDER BY ticker, datetime
            """,
            connection,
            params=(session_date,),
        )
    if prices.empty:
        return prices, None
    prices["datetime"] = pd.to_datetime(prices["datetime"], errors="coerce")
    prices["ticker"] = prices["ticker"].astype(str).str.strip()
    for column in ["open", "high", "low", "close"]:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
    prices["open"] = prices["open"].where(prices["open"].notna(), prices["close"])
    prices = prices.dropna(
        subset=["datetime", "ticker", "high", "low", "close"]
    ).copy()
    prices["date"] = prices["datetime"].dt.date
    label = _latest_completed_label(now, session_date)
    current_mask = prices["date"].astype(str).eq(session_date)
    if label:
        clocks = prices["datetime"].dt.strftime("%H:%M")
        prices = prices[~current_mask | clocks.le(label)].copy()
    else:
        prices = prices[~current_mask].copy()
    prices = prices.sort_values(["ticker", "datetime"]).reset_index(drop=True)
    day = prices[prices["date"].astype(str).eq(session_date)]
    last = day["datetime"].max() if not day.empty else pd.NaT
    return prices, None if pd.isna(last) else pd.Timestamp(last).to_pydatetime()


@contextmanager
def _safe_group_state_labels():
    """Keep Step 9Q-B compatible with stricter pandas mixed-string reductions."""

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


def _replay_exact_selected_engine(
    *,
    batch: pd.DataFrame,
    decisions: pd.DataFrame,
    prices: pd.DataFrame,
    session_date: str,
    last_completed_bar: datetime | None,
) -> ReplayFrames:
    if batch.empty or decisions.empty:
        return ReplayFrames(pd.DataFrame(), pd.DataFrame(), last_completed_bar, "NO_MORNING_BATCH")
    eligible = decisions[decisions["contract_eligible"].map(_boolish)].copy()
    known_ids = {row["contract_id"] for row in step9l_v3.CONTRACTS}
    recognized = eligible[eligible["contract_id"].isin(known_ids)]
    if recognized.empty:
        return ReplayFrames(pd.DataFrame(), pd.DataFrame(), last_completed_bar, "NO_SUPPORTED_ELIGIBLE_CONTRACTS")
    if prices.empty or last_completed_bar is None:
        return ReplayFrames(pd.DataFrame(), pd.DataFrame(), last_completed_bar, "NO_COMPLETED_SESSION_BARS")

    taxonomy_payload = json.loads(str(batch.iloc[0]["taxonomy_payload_json"]))
    taxonomy_payload["date"] = session_date
    taxonomy = pd.DataFrame([taxonomy_payload])

    try:
        with _safe_group_state_labels(), step9l_v3._patched_step9l_v3_globals():
            static, holdout, characteristics, group_states = step9i._full_holdout_context(
                prices,
                session_date,
            )
            with step9h._patched_step9g_globals():
                result = step9g.build_state_filtered_experiment(
                    taxonomy,
                    holdout,
                    static,
                    characteristics,
                    group_states,
                )
    except Exception as exc:
        raise Step9QBLiteError(
            f"Exact read-only V3 intraday replay failed: {type(exc).__name__}: {exc}"
        ) from exc

    candidates = result[3]
    trades = result[4]
    if not candidates.empty:
        candidates = candidates[candidates["date"].astype(str).eq(session_date)].copy()
    if not trades.empty:
        trades = trades[trades["date"].astype(str).eq(session_date)].copy()

    eligible_keys = {
        (str(row["contract_id"]), str(row["ticker"]))
        for row in recognized.to_dict("records")
    }
    candidate_keys = {
        (str(row["contract_id"]), str(row["ticker"]))
        for row in candidates.to_dict("records")
    } if not candidates.empty else set()
    trade_keys = {
        (str(row["contract_id"]), str(row["ticker"]))
        for row in trades.to_dict("records")
    } if not trades.empty else set()
    unexpected = (candidate_keys | trade_keys) - eligible_keys
    if unexpected:
        raise Step9QBLiteError(
            "Intraday replay produced keys outside the immutable morning ledger: "
            + repr(sorted(unexpected))
        )
    return ReplayFrames(candidates, trades, last_completed_bar, "EXACT_V3_REPLAY_OK")


def _contract_metadata(contract_id: str) -> tuple[str, str, str]:
    contract = next(
        (row for row in step9l_v3.CONTRACTS if row["contract_id"] == contract_id),
        None,
    )
    if contract is None:
        return "", "", ""
    base_id = str(contract["base_challenger_id"])
    if base_id == step9k.LAGGARD_CATCHUP_ID:
        challenger = step9k.LAGGARD_CATCHUP
    else:
        challenger = step9g.CHALLENGER_BY_ID.get(base_id, {})
    return base_id, str(challenger.get("exit_cutoff", "16:30")), str(contract.get("selection_status", ""))


def _entry_window_end(base_challenger_id: str) -> str:
    if base_challenger_id == "DIRECTIONAL_VOLATILITY_BREAKOUT_2R_V1":
        return "12:00"
    return "13:00"


def _latest_ticker_close(
    prices: pd.DataFrame,
    session_date: str,
    ticker: str,
) -> tuple[float | None, datetime | None]:
    if prices.empty:
        return None, None
    day = prices[
        prices["date"].astype(str).eq(session_date)
        & prices["ticker"].eq(ticker)
    ].sort_values("datetime")
    if day.empty:
        return None, None
    row = day.iloc[-1]
    return _number(row.get("close")), pd.Timestamp(row["datetime"]).to_pydatetime()


def _trade_state(
    *,
    decision: dict[str, Any],
    candidate: dict[str, Any],
    trade: dict[str, Any],
    latest_label: str,
    base_id: str,
    exit_cutoff: str,
) -> str:
    if not candidate:
        return "ELIGIBLE_NO_CANDIDATE"
    if str(candidate.get("setup_status", "")) != "VALID_SETUP":
        return "INVALID_SETUP"
    if not _boolish(candidate.get("selected_for_simulation")):
        return "ELIGIBLE_NOT_SELECTED"
    if not trade:
        trigger_status = str(candidate.get("trigger_status", ""))
        if any(token in trigger_status for token in ("AMBIGUOUS", "INVALID", "NO_EXECUTABLE")):
            return trigger_status or "INVALID_TRIGGER"
        return "WAITING_FOR_ENTRY" if latest_label <= _entry_window_end(base_id) else "NO_TRIGGER"
    exit_reason = str(trade.get("exit_reason", ""))
    if exit_reason == "TIME_EXIT" and latest_label < exit_cutoff:
        return "OPEN"
    return "CLOSED_PROVISIONAL"


def _build_live_rows_from_replay(
    *,
    batch: pd.DataFrame,
    decisions: pd.DataFrame,
    replay: ReplayFrames,
    prices: pd.DataFrame,
    session_date: str,
    snapshot_time: datetime,
) -> list[dict[str, Any]]:
    if batch.empty or decisions.empty:
        return []
    prospective_status = str(batch.iloc[0].get("prospective_status", ""))
    evidence_eligible = prospective_status == CONFIRMATORY_STATUS
    candidates = replay.candidates
    trades = replay.trades
    candidate_lookup = {
        (str(row["contract_id"]), str(row["ticker"])): row
        for row in candidates.to_dict("records")
    } if not candidates.empty else {}
    trade_lookup = {
        (str(row["contract_id"]), str(row["ticker"])): row
        for row in trades.to_dict("records")
    } if not trades.empty else {}
    latest_label = replay.last_completed_bar.strftime("%H:%M") if replay.last_completed_bar else ""
    rows: list[dict[str, Any]] = []
    eligible = decisions[decisions["contract_eligible"].map(_boolish)].copy()
    for decision in eligible.to_dict("records"):
        contract_id = str(decision["contract_id"])
        ticker = str(decision["ticker"])
        key = (contract_id, ticker)
        candidate = candidate_lookup.get(key, {})
        trade = trade_lookup.get(key, {})
        base_id, exit_cutoff, selection_status = _contract_metadata(contract_id)
        status = _trade_state(
            decision=decision,
            candidate=candidate,
            trade=trade,
            latest_label=latest_label,
            base_id=base_id,
            exit_cutoff=exit_cutoff,
        )
        current_price, current_time = _latest_ticker_close(prices, session_date, ticker)
        is_primary = str(decision["test_role"]) == PRIMARY_ROLE
        is_guardrail = str(decision["test_role"]) == GUARDRAIL_ROLE
        selected = _boolish(candidate.get("selected_for_simulation"))
        entry_price = _number(trade.get("entry_price", candidate.get("entry_price")))
        stop_price = _number(trade.get("stop_price", candidate.get("stop_price")))
        target_price = _number(trade.get("target_price", candidate.get("target_price")))
        provisional_pnl = _number(trade.get("risk_capped_net_pnl_sek"), 0.0) or 0.0
        unrealized = provisional_pnl if status == "OPEN" and is_primary else 0.0
        provisional_realized = provisional_pnl if status == "CLOSED_PROVISIONAL" and is_primary else 0.0
        rows.append(
            {
                "SessionDate": session_date,
                "SnapshotTimeStockholm": snapshot_time.replace(tzinfo=None),
                "ProspectiveStatus": prospective_status,
                "EvidenceEligible": evidence_eligible,
                "DecisionID": str(decision.get("decision_id", "")),
                "ContractID": contract_id,
                "BaseChallengerID": base_id,
                "SelectionStatus": selection_status,
                "TestRole": str(decision.get("test_role", "")),
                "IsPrimary": is_primary,
                "IsGuardrail": is_guardrail,
                "Ticker": ticker,
                "CompanyID": str(decision.get("company_id", "")),
                "BroadSector": str(decision.get("broad_sector", "")),
                "Direction": str(trade.get("direction", candidate.get("direction", decision.get("intended_side", "")))),
                "SelectionRank": int(_number(candidate.get("selection_rank"), 0) or 0),
                "SelectedForSimulation": selected,
                "TradeStatus": status,
                "IsOpenForTrade": bool(is_primary and selected and status == "WAITING_FOR_ENTRY"),
                "IsCurrentlyTraded": bool(is_primary and status == "OPEN"),
                "SetupStatus": str(candidate.get("setup_status", "")),
                "TriggerStatus": str(candidate.get("trigger_status", "")),
                "SignalTime": _parse_datetime(candidate.get("signal_time")),
                "EntryTime": _parse_datetime(trade.get("entry_time", candidate.get("entry_time"))),
                "EntryPrice": entry_price,
                "CurrentPrice": current_price,
                "CurrentPriceTime": current_time,
                "StopPrice": stop_price,
                "TargetPrice": target_price,
                "ExitTime": _parse_datetime(trade.get("exit_time")) if status == "CLOSED_PROVISIONAL" else None,
                "ExitPrice": _number(trade.get("exit_price")) if status == "CLOSED_PROVISIONAL" else None,
                "ExitReason": str(trade.get("exit_reason", "")) if status == "CLOSED_PROVISIONAL" else "",
                "RiskCappedNotionalSEK": _number(trade.get("risk_capped_notional_sek")),
                "UnrealizedPnLSEK": unrealized,
                "ProvisionalRealizedPnLSEK": provisional_realized,
                "DisplayPnLSEK": unrealized + provisional_realized,
                "PnLIncludedInEquity": bool(is_primary and evidence_eligible and status in {"OPEN", "CLOSED_PROVISIONAL"}),
                "LastCompletedBar": replay.last_completed_bar,
                "ReplayStatus": replay.replay_status,
                "PointInTimePass": _boolish(decision.get("point_in_time_pass")) and _boolish(candidate.get("point_in_time_pass"), True),
            }
        )
    return rows


def _authoritative_history_rows(outcomes: pd.DataFrame) -> list[dict[str, Any]]:
    if outcomes.empty:
        return []
    rows: list[dict[str, Any]] = []
    primary = outcomes[
        outcomes["test_role"].eq(PRIMARY_ROLE)
        & outcomes["outcome_status"].eq("HYPOTHETICAL_TRADE_COMPLETED")
    ].copy()
    for row in primary.to_dict("records"):
        pnl = _number(row.get("risk_capped_net_pnl_sek"), 0.0) or 0.0
        evidence = str(row.get("prospective_status", "")) == CONFIRMATORY_STATUS
        rows.append(
            {
                "TradeRecordID": str(row.get("decision_id", "")),
                "SessionDate": str(row.get("session_date", "")),
                "RecordStatus": "AUTHORITATIVE_EOD",
                "IsAuthoritative": True,
                "ProspectiveStatus": str(row.get("prospective_status", "")),
                "EvidenceEligible": evidence,
                "ContractID": str(row.get("contract_id", "")),
                "TestRole": str(row.get("test_role", "")),
                "Ticker": str(row.get("ticker", "")),
                "Direction": str(row.get("direction", "")),
                "EntryTime": _parse_datetime(row.get("entry_time")),
                "EntryPrice": _number(row.get("entry_price")),
                "StopPrice": _number(row.get("stop_price")),
                "TargetPrice": _number(row.get("target_price")),
                "ExitTime": _parse_datetime(row.get("exit_time")),
                "ExitPrice": _number(row.get("exit_price")),
                "ExitReason": str(row.get("exit_reason", "")),
                "NetPnLSEK": pnl,
                "WinningTrade": pnl > 0,
                "PnLIncludedInEquity": evidence,
                "PointInTimePass": _boolish(row.get("point_in_time_pass")),
            }
        )
    return rows


def _provisional_history_rows(
    live_rows: list[dict[str, Any]],
    authoritative_sessions: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in live_rows:
        if not row["IsPrimary"] or row["TradeStatus"] != "CLOSED_PROVISIONAL":
            continue
        if str(row["SessionDate"]) in authoritative_sessions:
            continue
        pnl = float(row["ProvisionalRealizedPnLSEK"] or 0.0)
        rows.append(
            {
                "TradeRecordID": str(row["DecisionID"]),
                "SessionDate": str(row["SessionDate"]),
                "RecordStatus": "CLOSED_PROVISIONAL",
                "IsAuthoritative": False,
                "ProspectiveStatus": str(row["ProspectiveStatus"]),
                "EvidenceEligible": bool(row["EvidenceEligible"]),
                "ContractID": str(row["ContractID"]),
                "TestRole": str(row["TestRole"]),
                "Ticker": str(row["Ticker"]),
                "Direction": str(row["Direction"]),
                "EntryTime": row["EntryTime"],
                "EntryPrice": row["EntryPrice"],
                "StopPrice": row["StopPrice"],
                "TargetPrice": row["TargetPrice"],
                "ExitTime": row["ExitTime"],
                "ExitPrice": row["ExitPrice"],
                "ExitReason": str(row["ExitReason"]),
                "NetPnLSEK": pnl,
                "WinningTrade": pnl > 0,
                "PnLIncludedInEquity": bool(row["PnLIncludedInEquity"]),
                "PointInTimePass": bool(row["PointInTimePass"]),
            }
        )
    return rows


def _account_snapshot_row(
    *,
    session_date: str,
    snapshot_time: datetime,
    live_rows: list[dict[str, Any]],
    history_rows: list[dict[str, Any]],
    last_completed_bar: datetime | None,
    replay_status: str,
) -> dict[str, Any]:
    all_history_pnl = float(
        sum(float(row["NetPnLSEK"] or 0.0) for row in history_rows)
    )
    confirmatory_history = [
        row for row in history_rows if row["PnLIncludedInEquity"]
    ]
    confirmatory_history_pnl = float(
        sum(float(row["NetPnLSEK"] or 0.0) for row in confirmatory_history)
    )
    open_rows = [
        row for row in live_rows
        if row["IsPrimary"] and row["TradeStatus"] == "OPEN"
    ]
    all_unrealized = float(
        sum(float(row["UnrealizedPnLSEK"] or 0.0) for row in open_rows)
    )
    confirmatory_unrealized = float(
        sum(
            float(row["UnrealizedPnLSEK"] or 0.0)
            for row in open_rows
            if row["PnLIncludedInEquity"]
        )
    )
    all_winners = int(sum(bool(row["WinningTrade"]) for row in history_rows))
    all_closed = len(history_rows)
    confirmatory_winners = int(
        sum(bool(row["WinningTrade"]) for row in confirmatory_history)
    )
    confirmatory_closed = len(confirmatory_history)
    total_pnl = all_history_pnl + all_unrealized
    confirmatory_total = confirmatory_history_pnl + confirmatory_unrealized
    return {
        "SessionDate": session_date,
        "SnapshotTimeStockholm": snapshot_time.replace(tzinfo=None),
        "InitialCapitalSEK": INITIAL_CAPITAL_SEK,
        "RealizedPnLSEK": all_history_pnl,
        "UnrealizedPnLSEK": all_unrealized,
        "TotalPnLSEK": total_pnl,
        "CurrentEquitySEK": INITIAL_CAPITAL_SEK + total_pnl,
        "ConfirmatoryTotalPnLSEK": confirmatory_total,
        "ConfirmatoryEquitySEK": INITIAL_CAPITAL_SEK + confirmatory_total,
        "OpenForTradeCount": int(sum(bool(row["IsOpenForTrade"]) for row in live_rows)),
        "OpenTradeCount": len(open_rows),
        "ClosedTradeCount": all_closed,
        "WinningTradeCount": all_winners,
        "WinRatePct": all_winners / all_closed if all_closed else None,
        "ConfirmatoryClosedTradeCount": confirmatory_closed,
        "ConfirmatoryWinningTradeCount": confirmatory_winners,
        "ConfirmatoryWinRatePct": (
            confirmatory_winners / confirmatory_closed
            if confirmatory_closed
            else None
        ),
        "LastCompletedBar": last_completed_bar,
        "ReplayStatus": replay_status,
        "EquityBasis": "ALL_PRIMARY_SHADOW_TRADES; CONFIRMATORY_FIELDS_EXCLUDE_LATE_RECONSTRUCTIONS",
        "Notes": (
            "CurrentEquitySEK is the operational all-primary shadow view. "
            "ConfirmatoryEquitySEK excludes guardrails and late reconstructions. "
            "Intraday states remain provisional until Step 9L EOD sealing."
        ),
    }


def build_step9qb_rows(
    *,
    session_date: str,
    step9l_ledger: Path,
    price_db: Path,
    now: datetime,
    replay_builder: Callable[..., ReplayFrames] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    batch, decisions = _read_decision_sources(step9l_ledger, session_date)
    prices, last_completed = _read_prices_through_completed_bar(
        price_db,
        session_date,
        now,
    )
    builder = replay_builder or _replay_exact_selected_engine
    replay = builder(
        batch=batch,
        decisions=decisions,
        prices=prices,
        session_date=session_date,
        last_completed_bar=last_completed,
    )
    live_rows = _build_live_rows_from_replay(
        batch=batch,
        decisions=decisions,
        replay=replay,
        prices=prices,
        session_date=session_date,
        snapshot_time=now,
    )
    outcomes = _read_all_authoritative_outcomes(step9l_ledger)
    authoritative_rows = _authoritative_history_rows(outcomes)
    authoritative_sessions = {
        str(row["SessionDate"]) for row in authoritative_rows
    }
    provisional_rows = _provisional_history_rows(live_rows, authoritative_sessions)
    history_rows = authoritative_rows + provisional_rows
    account_row = _account_snapshot_row(
        session_date=session_date,
        snapshot_time=now,
        live_rows=live_rows,
        history_rows=history_rows,
        last_completed_bar=replay.last_completed_bar,
        replay_status=replay.replay_status,
    )
    return {
        "Live_Trade_Status": live_rows,
        "Trade_History": history_rows,
        "Account_Snapshot": [account_row],
    }
