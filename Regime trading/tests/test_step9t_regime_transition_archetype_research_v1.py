from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.scripts import step9t_regime_transition_archetype_research_v1 as step9t


class Step9TUnitTests(unittest.TestCase):
    def _ticker_row(self, ticker: str = "TEST.ST") -> pd.Series:
        return pd.Series(
            {
                "ticker": ticker,
                "company_id": ticker.split(".")[0],
                "broad_sector": "TEST",
                "universe_role": "REGIME_SOURCE",
            }
        )

    def _prices(
        self,
        *,
        open_0930: float = 100.0,
        close_0940: float = 100.0,
        close_0945: float = 100.0,
        entry_0950: float = 100.0,
        future_close: float = 101.0,
    ) -> pd.DataFrame:
        values = [
            ("09:30", open_0930, max(open_0930, 100.5), min(open_0930, 99.5), open_0930),
            ("09:35", open_0930, 100.5, 99.5, open_0930),
            ("09:40", close_0940, 100.5, 99.5, close_0940),
            ("09:45", close_0945, max(close_0945, 100.5), min(close_0945, 99.5), close_0945),
            ("09:50", entry_0950, max(entry_0950, future_close), min(entry_0950, future_close), future_close),
            ("17:25", future_close, future_close, future_close, future_close),
        ]
        rows = []
        for clock, open_, high, low, close in values:
            rows.append(
                {
                    "datetime": pd.Timestamp(f"2026-07-28 {clock}:00"),
                    "session_date": "2026-07-28",
                    "clock": clock,
                    "ticker": "TEST.ST",
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                }
            )
        return pd.DataFrame(rows)

    def test_config_is_router_inactive(self) -> None:
        self.assertFalse(step9t.CONFIG["router_active"])
        self.assertFalse(step9t.CONFIG["orders_enabled"])
        self.assertEqual(step9t.LATEST_MORNING_LABEL, "09:45")
        self.assertEqual(step9t.ENTRY_LABEL, "09:50")

    def test_bullish_continuation(self) -> None:
        row = step9t.classify_ticker_morning(
            "2026-07-28", self._ticker_row(), self._prices(close_0940=100.1, close_0945=100.3)
        )
        self.assertEqual(row["primary_archetype"], "BULLISH_CONTINUATION_LONG")
        self.assertEqual(row["direction"], "LONG")

    def test_bearish_continuation(self) -> None:
        row = step9t.classify_ticker_morning(
            "2026-07-28", self._ticker_row(), self._prices(close_0940=99.8, close_0945=99.6)
        )
        self.assertEqual(row["primary_archetype"], "BEARISH_CONTINUATION_SHORT")
        self.assertEqual(row["direction"], "SHORT")

    def test_laggard_recovery_has_priority(self) -> None:
        row = step9t.classify_ticker_morning(
            "2026-07-28", self._ticker_row(), self._prices(close_0940=99.0, close_0945=99.2)
        )
        self.assertEqual(row["primary_archetype"], "LAGGARD_RECOVERY_LONG")

    def test_leader_reversal(self) -> None:
        row = step9t.classify_ticker_morning(
            "2026-07-28", self._ticker_row(), self._prices(close_0940=100.5, close_0945=100.3)
        )
        self.assertEqual(row["primary_archetype"], "LEADER_REVERSAL_SHORT")

    def test_future_bars_do_not_change_morning_classification(self) -> None:
        first = step9t.classify_ticker_morning(
            "2026-07-28", self._ticker_row(), self._prices(close_0940=99.8, close_0945=99.6, future_close=90.0)
        )
        second = step9t.classify_ticker_morning(
            "2026-07-28", self._ticker_row(), self._prices(close_0940=99.8, close_0945=99.6, future_close=110.0)
        )
        comparable = [
            "early_return",
            "last5_return",
            "primary_archetype",
            "direction",
            "entry_price",
            "ticker_row_id",
        ]
        self.assertEqual({key: first[key] for key in comparable}, {key: second[key] for key in comparable})

    def test_outcomes_use_standardized_direction(self) -> None:
        prices = self._prices(close_0940=99.8, close_0945=99.6, entry_0950=100.0, future_close=101.0)
        morning = step9t.classify_ticker_morning("2026-07-28", self._ticker_row(), prices)
        outcome = step9t.evaluate_ticker_outcome(pd.Series(morning), prices)
        self.assertEqual(outcome["direction"], "SHORT")
        self.assertAlmostEqual(outcome["session_close_return"], -0.01, places=12)
        self.assertAlmostEqual(outcome["net_pnl_sek"], -10.5, places=12)

    def test_readonly_sqlite_handle_closes_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "prices.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "CREATE TABLE intraday_prices(datetime TEXT, open REAL, high REAL, low REAL, close REAL, ticker TEXT)"
                )
                connection.execute(
                    "INSERT INTO intraday_prices VALUES ('2026-07-28 09:30:00', 1, 1, 1, 1, 'TEST.ST')"
                )
                connection.commit()
            with closing(step9t._readonly_connection(path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0], 1)
            path.unlink()
            self.assertFalse(path.exists())


class Step9TProjectIntegrationTests(unittest.TestCase):
    def test_july28_morning_reproduces_frozen_transition_snapshot(self) -> None:
        universe = step9t._load_universe(step9t.DEFAULT_CORE_REGISTRY, step9t.DEFAULT_HOLDOUT_REGISTRY)
        prices = step9t._load_prices(step9t.DEFAULT_PRICE_DB, "2026-07-28", "2026-07-28", duplicate_policy="latest_rowid")
        rows = []
        for ticker in universe.to_dict("records"):
            rows.append(
                step9t.classify_ticker_morning(
                    "2026-07-28",
                    pd.Series(ticker),
                    prices[prices["ticker"].eq(ticker["ticker"])],
                )
            )
        frame = pd.DataFrame(rows)
        transition, features = step9t.classify_transition(frame)
        self.assertEqual(len(frame), 29)
        self.assertEqual(transition, "WEAKNESS_PERSISTING")
        self.assertEqual(features["valid_ticker_count"], 28)
        sand = frame[frame["ticker"].eq("SAND.ST")].iloc[0]
        self.assertEqual(sand["primary_archetype"], "BEARISH_CONTINUATION_SHORT")


if __name__ == "__main__":
    unittest.main()
