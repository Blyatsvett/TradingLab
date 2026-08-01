from __future__ import annotations

import unittest

import pandas as pd

from RegimeTrading.scripts.v1_validation_exposure_reconciliation import (
    build_reconciliation,
)


def make_inputs():
    portfolio_summary = pd.DataFrame(
        [
            {
                "total_realized_pnl_sek": 3.0,
                "selected_closed_trades": 2,
                "selected_open_trades": 1,
            }
        ]
    )
    portfolio_ledger = pd.DataFrame(
        [
            {
                "source_trade_row": 10,
                "selected_for_portfolio": True,
                "selection_status": "SELECTED_CLOSED",
                "portfolio_pnl_sek": 5.0,
            },
            {
                "source_trade_row": 11,
                "selected_for_portfolio": True,
                "selection_status": "SELECTED_CLOSED",
                "portfolio_pnl_sek": -2.0,
            },
            {
                "source_trade_row": 12,
                "selected_for_portfolio": True,
                "selection_status": "SELECTED_OPEN",
                "portfolio_pnl_sek": 0.0,
            },
            {
                "source_trade_row": 13,
                "selected_for_portfolio": False,
                "selection_status": "REJECTED_CAPACITY",
                "portfolio_pnl_sek": 0.0,
            },
        ]
    )
    portfolio_equity = pd.DataFrame(
        [
            {"event_number": 0, "cumulative_pnl_sek": 0.0},
            {"event_number": 1, "cumulative_pnl_sek": 5.0},
            {"event_number": 2, "cumulative_pnl_sek": 3.0},
        ]
    )
    exposure_summary = pd.DataFrame(
        [
            {
                "realized_pnl_sek": 3.0,
                "selected_closed_positions": 2,
                "selected_open_positions": 1,
            }
        ]
    )
    exposure_positions = pd.DataFrame(
        [
            {
                "source_trade_row": 10,
                "is_realized_closed_position": True,
                "is_open_position": False,
                "realized_pnl_sek": 5.0,
            },
            {
                "source_trade_row": 11,
                "is_realized_closed_position": True,
                "is_open_position": False,
                "realized_pnl_sek": -2.0,
            },
            {
                "source_trade_row": 12,
                "is_realized_closed_position": False,
                "is_open_position": True,
                "realized_pnl_sek": 0.0,
            },
        ]
    )
    exposure_daily = pd.DataFrame(
        [
            {"date": "2026-01-01", "realized_pnl_sek": 5.0},
            {"date": "2026-01-02", "realized_pnl_sek": -2.0},
        ]
    )
    sizing = pd.DataFrame(
        [{"scenario_id": "CURRENT_V1", "scaled_realized_pnl_sek": 3.0}]
    )
    return (
        portfolio_summary,
        portfolio_ledger,
        portfolio_equity,
        exposure_summary,
        exposure_positions,
        exposure_daily,
        sizing,
    )


class ExposureReconciliationTests(unittest.TestCase):
    def test_exact_inputs_pass(self):
        result = build_reconciliation(*make_inputs())
        row = result.report.iloc[0]
        self.assertTrue(result.passed)
        self.assertEqual(row["reconciliation_status"], "PASS_EXACT_SAME_RUN_RECONCILIATION")
        self.assertAlmostEqual(float(row["max_absolute_pnl_difference_sek"]), 0.0)

    def test_pnl_difference_fails(self):
        inputs = list(make_inputs())
        inputs[3] = inputs[3].copy()
        inputs[3].loc[0, "realized_pnl_sek"] = 2.5
        result = build_reconciliation(*inputs)
        row = result.report.iloc[0]
        self.assertFalse(result.passed)
        self.assertEqual(row["reconciliation_status"], "FAIL_PNL_MISMATCH")
        self.assertAlmostEqual(float(row["max_absolute_pnl_difference_sek"]), 0.5)

    def test_missing_exposure_trade_fails(self):
        inputs = list(make_inputs())
        inputs[4] = inputs[4][inputs[4]["source_trade_row"] != 12].copy()
        inputs[3] = inputs[3].copy()
        inputs[3].loc[0, "selected_open_positions"] = 0
        result = build_reconciliation(*inputs)
        row = result.report.iloc[0]
        self.assertFalse(result.passed)
        self.assertEqual(row["reconciliation_status"], "FAIL_TRADE_IDENTITY_MISMATCH")
        self.assertEqual(int(row["missing_exposure_trade_count"]), 1)
        self.assertEqual(str(row["missing_exposure_trade_ids"]), "12")

    def test_duplicate_exposure_trade_fails(self):
        inputs = list(make_inputs())
        duplicate = inputs[4].iloc[[0]].copy()
        inputs[4] = pd.concat([inputs[4], duplicate], ignore_index=True)
        inputs[3] = inputs[3].copy()
        inputs[3].loc[0, "selected_closed_positions"] = 3
        inputs[3].loc[0, "realized_pnl_sek"] = 8.0
        inputs[5] = pd.DataFrame([{"date": "2026-01-01", "realized_pnl_sek": 8.0}])
        inputs[6] = pd.DataFrame([{"scenario_id": "CURRENT_V1", "scaled_realized_pnl_sek": 8.0}])
        result = build_reconciliation(*inputs)
        row = result.report.iloc[0]
        self.assertFalse(result.passed)
        self.assertEqual(row["reconciliation_status"], "FAIL_TRADE_IDENTITY_MISMATCH")
        self.assertEqual(int(row["duplicate_exposure_trade_count"]), 1)
        self.assertEqual(str(row["duplicate_exposure_trade_ids"]), "10")


if __name__ == "__main__":
    unittest.main()
