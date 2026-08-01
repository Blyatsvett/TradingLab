from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "RegimeTrading"
    / "scripts"
    / "step9q_b_lite_live_trade_feed.py"
)
SPEC = importlib.util.spec_from_file_location("step9qb_lite", MODULE_PATH)
step9qb = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = step9qb
assert SPEC.loader is not None
SPEC.loader.exec_module(step9qb)

SESSION = "2026-07-28"
TZ = ZoneInfo("Europe/Stockholm")
PRIMARY_CONTRACT = "L2_HVR_DIRECTIONAL_BREAKOUT_2R_V1"
GUARDRAIL_CONTRACT = "L2_HVR_ALIGNED_DELAYED_REVERSAL_AVOID_V1"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def batch_frame(status: str = step9qb.CONFIRMATORY_STATUS) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "batch_id": "B1",
                "session_date": SESSION,
                "prospective_status": status,
                "taxonomy_payload_json": '{"date":"2026-07-28","primary_regime":"HIGH_VOL_REVERSAL","direction_bias":"NEUTRAL","research_risk_multiplier":0.5,"research_max_concurrent_ideas":2}',
                "research_max_concurrent_ideas": 2,
            }
        ]
    )


def decision_frame(
    *,
    contract_id: str = PRIMARY_CONTRACT,
    test_role: str = step9qb.PRIMARY_ROLE,
    ticker: str = "ABB.ST",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_id": f"B1|{contract_id}|{ticker}",
                "batch_id": "B1",
                "session_date": SESSION,
                "contract_id": contract_id,
                "test_role": test_role,
                "ticker": ticker,
                "company_id": "ABB",
                "broad_sector": "INDUSTRIALS",
                "contract_eligible": 1,
                "intended_side": "LONG",
                "point_in_time_pass": 1,
            }
        ]
    )


def price_frame(ticker: str = "ABB.ST") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp(f"{SESSION} 11:00:00"),
                "open": 101.0,
                "high": 102.0,
                "low": 100.5,
                "close": 101.5,
                "ticker": ticker,
                "date": pd.Timestamp(SESSION).date(),
            }
        ]
    )


def candidate_frame(
    *,
    contract_id: str = PRIMARY_CONTRACT,
    test_role: str = step9qb.PRIMARY_ROLE,
    ticker: str = "ABB.ST",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_id": contract_id,
                "test_role": test_role,
                "ticker": ticker,
                "selected_for_simulation": True,
                "setup_status": "VALID_SETUP",
                "trigger_status": "TRIGGERED_CLOSED",
                "direction": "LONG",
                "selection_rank": 1,
                "point_in_time_pass": True,
                "signal_time": f"{SESSION} 10:00:00",
                "entry_time": f"{SESSION} 10:05:00",
                "entry_price": 100.0,
                "stop_price": 99.0,
                "target_price": 102.0,
            }
        ]
    )


def trade_frame(
    *,
    exit_reason: str = "TIME_EXIT",
    pnl: float = 2.0,
    contract_id: str = PRIMARY_CONTRACT,
    test_role: str = step9qb.PRIMARY_ROLE,
    ticker: str = "ABB.ST",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_id": contract_id,
                "test_role": test_role,
                "ticker": ticker,
                "direction": "LONG",
                "entry_time": f"{SESSION} 10:05:00",
                "entry_price": 100.0,
                "stop_price": 99.0,
                "target_price": 102.0,
                "exit_time": f"{SESSION} 11:00:00",
                "exit_price": 101.5 if exit_reason == "TIME_EXIT" else 99.0,
                "exit_reason": exit_reason,
                "risk_capped_notional_sek": 500.0,
                "risk_capped_net_pnl_sek": pnl,
            }
        ]
    )


def create_price_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as con:
        con.execute(
            """
            CREATE TABLE intraday_prices (
                datetime TEXT, open REAL, high REAL, low REAL, close REAL,
                ticker TEXT, source TEXT, collected_at_utc TEXT
            )
            """
        )
        con.executemany(
            "INSERT INTO intraday_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (f"{SESSION} 10:00:00", 100, 101, 99, 100.5, "ABB.ST", "TEST", f"{SESSION} 08:06:00"),
                (f"{SESSION} 10:05:00", 100.5, 102, 100, 101.5, "ABB.ST", "TEST", f"{SESSION} 08:11:00"),
            ],
        )
        con.commit()


def create_full_ledger(path: Path) -> None:
    with closing(sqlite3.connect(path)) as con:
        con.executescript(
            """
            CREATE TABLE shadow_decision_batches (
                batch_id TEXT, session_date TEXT, prospective_status TEXT,
                taxonomy_payload_json TEXT, research_max_concurrent_ideas INTEGER,
                created_at_stockholm TEXT
            );
            CREATE TABLE shadow_decisions (
                decision_id TEXT, batch_id TEXT, session_date TEXT,
                contract_id TEXT, test_role TEXT, ticker TEXT, company_id TEXT,
                broad_sector TEXT, contract_eligible INTEGER, intended_side TEXT,
                point_in_time_pass INTEGER
            );
            CREATE TABLE shadow_outcomes (
                decision_id TEXT, session_date TEXT, contract_id TEXT,
                test_role TEXT, ticker TEXT, direction TEXT, entry_time TEXT,
                entry_price REAL, stop_price REAL, target_price REAL,
                exit_time TEXT, exit_price REAL, exit_reason TEXT,
                risk_capped_net_pnl_sek REAL, outcome_status TEXT,
                point_in_time_pass INTEGER
            );
            """
        )
        con.execute(
            "INSERT INTO shadow_decision_batches VALUES (?, ?, ?, ?, ?, ?)",
            (
                "B1",
                SESSION,
                step9qb.CONFIRMATORY_STATUS,
                '{"date":"2026-07-28","primary_regime":"HIGH_VOL_REVERSAL","direction_bias":"NEUTRAL","research_risk_multiplier":0.5,"research_max_concurrent_ideas":2}',
                2,
                f"{SESSION} 09:46:00+0200",
            ),
        )
        con.execute(
            "INSERT INTO shadow_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"B1|{PRIMARY_CONTRACT}|ABB.ST",
                "B1",
                SESSION,
                PRIMARY_CONTRACT,
                step9qb.PRIMARY_ROLE,
                "ABB.ST",
                "ABB",
                "INDUSTRIALS",
                1,
                "LONG",
                1,
            ),
        )
        con.execute(
            "INSERT INTO shadow_outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"B1|{PRIMARY_CONTRACT}|ABB.ST",
                SESSION,
                PRIMARY_CONTRACT,
                step9qb.PRIMARY_ROLE,
                "ABB.ST",
                "LONG",
                f"{SESSION} 10:05:00",
                100.0,
                99.0,
                102.0,
                f"{SESSION} 10:30:00",
                102.0,
                "TARGET_HIT",
                4.0,
                "HYPOTHETICAL_TRADE_COMPLETED",
                1,
            ),
        )
        con.commit()


class Step9QBLiteTests(unittest.TestCase):
    def test_completed_bar_filter_excludes_in_progress_bar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.db"
            create_price_db(path)
            now = datetime(2026, 7, 28, 10, 7, tzinfo=TZ)
            prices, last = step9qb._read_prices_through_completed_bar(path, SESSION, now)
            self.assertEqual(last, datetime(2026, 7, 28, 10, 0))
            self.assertEqual(prices[prices["date"].astype(str).eq(SESSION)]["datetime"].max(), pd.Timestamp(f"{SESSION} 10:00:00"))

    def test_time_exit_before_contract_cutoff_is_open(self) -> None:
        replay = step9qb.ReplayFrames(
            candidate_frame(),
            trade_frame(exit_reason="TIME_EXIT", pnl=2.0),
            datetime(2026, 7, 28, 11, 0),
            "TEST_REPLAY",
        )
        rows = step9qb._build_live_rows_from_replay(
            batch=batch_frame(),
            decisions=decision_frame(),
            replay=replay,
            prices=price_frame(),
            session_date=SESSION,
            snapshot_time=datetime(2026, 7, 28, 11, 7, tzinfo=TZ),
        )
        self.assertEqual(rows[0]["TradeStatus"], "OPEN")
        self.assertTrue(rows[0]["IsCurrentlyTraded"])
        self.assertEqual(rows[0]["UnrealizedPnLSEK"], 2.0)
        self.assertIsNone(rows[0]["ExitTime"])

    def test_late_reconstruction_closed_trade_is_visible_but_excluded_from_equity(self) -> None:
        replay = step9qb.ReplayFrames(
            candidate_frame(),
            trade_frame(exit_reason="STOP_HIT", pnl=-2.0),
            datetime(2026, 7, 28, 11, 0),
            "TEST_REPLAY",
        )
        live = step9qb._build_live_rows_from_replay(
            batch=batch_frame("LATE_RECONSTRUCTION_NOT_CONFIRMATORY"),
            decisions=decision_frame(),
            replay=replay,
            prices=price_frame(),
            session_date=SESSION,
            snapshot_time=datetime(2026, 7, 28, 11, 7, tzinfo=TZ),
        )
        history = step9qb._provisional_history_rows(live, set())
        account = step9qb._account_snapshot_row(
            session_date=SESSION,
            snapshot_time=datetime(2026, 7, 28, 11, 7, tzinfo=TZ),
            live_rows=live,
            history_rows=history,
            last_completed_bar=datetime(2026, 7, 28, 11, 0),
            replay_status="TEST_REPLAY",
        )
        self.assertEqual(live[0]["TradeStatus"], "CLOSED_PROVISIONAL")
        self.assertFalse(live[0]["PnLIncludedInEquity"])
        self.assertEqual(history[0]["NetPnLSEK"], -2.0)
        self.assertEqual(account["CurrentEquitySEK"], 9998.0)
        self.assertEqual(account["ConfirmatoryEquitySEK"], 10000.0)

    def test_guardrail_never_enters_primary_equity(self) -> None:
        replay = step9qb.ReplayFrames(
            candidate_frame(contract_id=GUARDRAIL_CONTRACT, test_role=step9qb.GUARDRAIL_ROLE),
            trade_frame(contract_id=GUARDRAIL_CONTRACT, test_role=step9qb.GUARDRAIL_ROLE, pnl=5.0),
            datetime(2026, 7, 28, 11, 0),
            "TEST_REPLAY",
        )
        live = step9qb._build_live_rows_from_replay(
            batch=batch_frame(),
            decisions=decision_frame(contract_id=GUARDRAIL_CONTRACT, test_role=step9qb.GUARDRAIL_ROLE),
            replay=replay,
            prices=price_frame(),
            session_date=SESSION,
            snapshot_time=datetime(2026, 7, 28, 11, 7, tzinfo=TZ),
        )
        self.assertTrue(live[0]["IsGuardrail"])
        self.assertFalse(live[0]["IsCurrentlyTraded"])
        self.assertEqual(live[0]["DisplayPnLSEK"], 0.0)
        self.assertFalse(live[0]["PnLIncludedInEquity"])

    def test_authoritative_history_builds_equity_and_sources_remain_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.db"
            prices = root / "prices.db"
            create_full_ledger(ledger)
            create_price_db(prices)
            before = {"ledger": file_hash(ledger), "prices": file_hash(prices)}

            def empty_replay(**kwargs):
                return step9qb.ReplayFrames(
                    pd.DataFrame(),
                    pd.DataFrame(),
                    kwargs["last_completed_bar"],
                    "TEST_NO_LIVE_REPLAY",
                )

            tables = step9qb.build_step9qb_rows(
                session_date=SESSION,
                step9l_ledger=ledger,
                price_db=prices,
                now=datetime(2026, 7, 28, 17, 0, tzinfo=TZ),
                replay_builder=empty_replay,
            )
            after = {"ledger": file_hash(ledger), "prices": file_hash(prices)}
            self.assertEqual(before, after)
            self.assertEqual(len(tables["Trade_History"]), 1)
            self.assertEqual(tables["Trade_History"][0]["RecordStatus"], "AUTHORITATIVE_EOD")
            self.assertEqual(tables["Account_Snapshot"][0]["CurrentEquitySEK"], 10004.0)
            self.assertEqual(tables["Account_Snapshot"][0]["ConfirmatoryEquitySEK"], 10004.0)
            self.assertEqual(tables["Account_Snapshot"][0]["WinRatePct"], 1.0)

    def test_authoritative_session_suppresses_duplicate_provisional_history(self) -> None:
        live = [
            {
                "IsPrimary": True,
                "TradeStatus": "CLOSED_PROVISIONAL",
                "SessionDate": SESSION,
                "ProvisionalRealizedPnLSEK": 3.0,
                "DecisionID": "D1",
                "ProspectiveStatus": step9qb.CONFIRMATORY_STATUS,
                "EvidenceEligible": True,
                "ContractID": PRIMARY_CONTRACT,
                "TestRole": step9qb.PRIMARY_ROLE,
                "Ticker": "ABB.ST",
                "Direction": "LONG",
                "EntryTime": None,
                "EntryPrice": 100.0,
                "StopPrice": 99.0,
                "TargetPrice": 102.0,
                "ExitTime": None,
                "ExitPrice": 102.0,
                "ExitReason": "TARGET_HIT",
                "PnLIncludedInEquity": True,
                "PointInTimePass": True,
            }
        ]
        self.assertEqual(step9qb._provisional_history_rows(live, {SESSION}), [])


if __name__ == "__main__":
    unittest.main()
