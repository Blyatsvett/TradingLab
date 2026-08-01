from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing, contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from RegimeTrading.scripts import step9d_regime_strategy_challenger_matrix as step9d
from RegimeTrading.scripts import step9r_v1_candidate_ranking_research as step9r
from RegimeTrading.core.stage_registry import resolve_stage_path
from RegimeTrading.core.paths import legacy_output_path


ROOT = Path(__file__).resolve().parents[1]
PRICE_DB = resolve_stage_path("prices")
V3_LEDGER = resolve_stage_path("step9l")
TAXONOMY_LEDGER = legacy_output_path("step9ir_v2_historical_replay_ledger.db")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Step9RHelperTests(unittest.TestCase):
    def test_rank_bucket_boundaries(self) -> None:
        expected = {
            1: "1",
            2: "2",
            3: "3_TO_5",
            5: "3_TO_5",
            6: "6_TO_10",
            10: "6_TO_10",
            11: "11_PLUS",
            999: "11_PLUS",
        }
        for rank, bucket in expected.items():
            self.assertEqual(step9r.rank_bucket(rank), bucket)

    def test_select_all_context_preserves_rank_and_restores_function(self) -> None:
        original = step9d._select_candidates
        rows = [
            {"ticker": "B", "paired_ticker": "", "setup_status": "VALID_SETUP", "ranking_metric": 1.0, "selected_for_simulation": False, "trigger_status": ""},
            {"ticker": "A", "paired_ticker": "", "setup_status": "VALID_SETUP", "ranking_metric": 2.0, "selected_for_simulation": False, "trigger_status": ""},
            {"ticker": "C", "paired_ticker": "", "setup_status": "INVALID_SETUP", "ranking_metric": 3.0, "selected_for_simulation": False, "trigger_status": ""},
        ]
        with step9r._select_all_valid_candidates():
            step9d._select_candidates(rows, max_ideas=1)
            self.assertTrue(rows[0]["selected_for_simulation"])
            self.assertTrue(rows[1]["selected_for_simulation"])
            self.assertFalse(rows[2]["selected_for_simulation"])
            self.assertEqual(rows[1]["selection_rank"], 1)
            self.assertEqual(rows[0]["selection_rank"], 2)
        self.assertIs(step9d._select_candidates, original)

    def test_oracle_uses_at_most_two_unique_positive_tickers(self) -> None:
        frame = pd.DataFrame(
            [
                {"ticker": "A", "risk_capped_net_pnl_sek": 3.0, "ranking_metric": 0.1},
                {"ticker": "A", "risk_capped_net_pnl_sek": 2.0, "ranking_metric": 0.2},
                {"ticker": "B", "risk_capped_net_pnl_sek": 1.0, "ranking_metric": 0.3},
                {"ticker": "C", "risk_capped_net_pnl_sek": -1.0, "ranking_metric": 0.4},
            ]
        )
        selected = step9r._oracle_selection(frame)
        self.assertEqual(len(selected), 2)
        self.assertEqual(set(selected["ticker"]), {"A", "B"})
        self.assertTrue(selected["risk_capped_net_pnl_sek"].gt(0).all())

    def test_guardrails_are_not_model_eligible_and_valid_nontrigger_zero(self) -> None:
        candidates = pd.DataFrame(
            [
                {
                    "date": "2026-07-28",
                    "contract_id": "P",
                    "test_role": step9r.PRIMARY_ROLE,
                    "ticker": "A.ST",
                    "company_id": "A",
                    "broad_sector": "X",
                    "primary_regime": "TEST",
                    "base_challenger_id": "B",
                    "direction": "LONG",
                    "ticker_relative_state": "EARLY_LEADER",
                    "volatility_bucket": "MEDIUM_RELATIVE_VOL",
                    "range_state": "RANGE_NORMAL",
                    "sector_direction_state": "UP",
                    "sector_direction_alignment": "ALIGNED_WITH_GROUP",
                    "ranking_metric": 1.0,
                    "selection_rank": 1,
                    "setup_status": "VALID_SETUP",
                    "trigger_status": "NOT_TRIGGERED",
                    "invalid_reason": "",
                    "max_router_source_label": "09:40",
                    "point_in_time_pass": True,
                },
                {
                    "date": "2026-07-28",
                    "contract_id": "G",
                    "test_role": step9r.GUARDRAIL_ROLE,
                    "ticker": "B.ST",
                    "company_id": "B",
                    "broad_sector": "X",
                    "primary_regime": "TEST",
                    "base_challenger_id": "B",
                    "direction": "SHORT",
                    "ticker_relative_state": "EARLY_LAGGARD",
                    "volatility_bucket": "MEDIUM_RELATIVE_VOL",
                    "range_state": "RANGE_NORMAL",
                    "sector_direction_state": "DOWN",
                    "sector_direction_alignment": "ALIGNED_WITH_GROUP",
                    "ranking_metric": 0.5,
                    "selection_rank": 1,
                    "setup_status": "VALID_SETUP",
                    "trigger_status": "NOT_TRIGGERED",
                    "invalid_reason": "",
                    "max_router_source_label": "09:40",
                    "point_in_time_pass": True,
                },
            ]
        )
        taxonomy = pd.DataFrame(
            [{"date": "2026-07-28", "primary_regime": "TEST", "regime_confidence": 0.8, "confidence_band": "HIGH", "direction_bias": "NEUTRAL", "research_risk_multiplier": 0.5, "research_max_concurrent_ideas": 2}]
        )
        characteristics = pd.DataFrame(
            [
                {"date": "2026-07-28", "ticker": "A.ST", "max_same_day_source_label": "09:40", "point_in_time_pass": True},
                {"date": "2026-07-28", "ticker": "B.ST", "max_same_day_source_label": "09:40", "point_in_time_pass": True},
            ]
        )
        replay = step9r.ReplayFrames(
            taxonomy=taxonomy,
            taxonomy_skips=pd.DataFrame(),
            baseline_candidates=pd.DataFrame(),
            baseline_trades=pd.DataFrame(),
            all_candidates=candidates,
            all_trades=pd.DataFrame(),
            characteristics=characteristics,
            prices=pd.DataFrame(columns=["datetime", "ticker", "high", "low"]),
        )
        outcomes = step9r.build_candidate_outcomes(replay)
        primary = outcomes[outcomes["test_role"].eq(step9r.PRIMARY_ROLE)].iloc[0]
        guardrail = outcomes[outcomes["test_role"].eq(step9r.GUARDRAIL_ROLE)].iloc[0]
        self.assertTrue(bool(primary["model_eligible"]))
        self.assertEqual(float(primary["risk_capped_net_pnl_sek"]), 0.0)
        self.assertEqual(float(primary["net_r_after_costs"]), 0.0)
        self.assertFalse(bool(guardrail["model_eligible"]))

    def test_daily_failure_classification(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "date": "2026-07-28",
                    "primary_regime": "TEST",
                    "model_eligible": True,
                    "counterfactual_trade_generated": True,
                    "winning_trade": True,
                    "risk_capped_net_pnl_sek": 2.0,
                    "selected_by_v3": False,
                    "ticker": "A.ST",
                    "v3_rank": 3,
                },
                {
                    "date": "2026-07-28",
                    "primary_regime": "TEST",
                    "model_eligible": True,
                    "counterfactual_trade_generated": True,
                    "winning_trade": False,
                    "risk_capped_net_pnl_sek": -1.0,
                    "selected_by_v3": True,
                    "ticker": "B.ST",
                    "v3_rank": 1,
                },
            ]
        )
        daily, _ = step9r.build_daily_selection_diagnostics(frame)
        row = daily.iloc[0]
        self.assertTrue(bool(row["selection_failure"]))
        self.assertTrue(bool(row["economic_failure"]))
        self.assertEqual(row["daily_system_result"], "FAILURE_PROFITABLE_OPPORTUNITY_MISSED")

    def test_selector_can_abstain_or_select_up_to_two(self) -> None:
        frame = pd.DataFrame(
            [
                {"ticker": "A", "score": -0.1, "ranking_metric": 3.0},
                {"ticker": "B", "score": 0.2, "ranking_metric": 2.0},
                {"ticker": "C", "score": 0.1, "ranking_metric": 1.0},
            ]
        )
        self.assertEqual(len(step9r._select_up_to_two(frame[frame["score"].lt(0)], "score")), 0)
        one = step9r._select_up_to_two(frame[frame["ticker"].eq("B")], "score")
        self.assertEqual(list(one["ticker"]), ["B"])
        two = step9r._select_up_to_two(frame, "score")
        self.assertEqual(list(two["ticker"]), ["B", "C"])

    def test_zero_eligible_prospective_day_records_abstention_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            price_db = temp / "prices.db"
            v3_ledger = temp / "v3.db"
            research_db = temp / "research.db"
            prospective_db = temp / "prospective.db"
            price_db.write_bytes(b"price-db-placeholder")
            v3_ledger.write_bytes(b"v3-ledger-placeholder")
            research_db.write_bytes(b"research-db-placeholder")

            historical = pd.DataFrame(columns=["model_eligible", "date"])
            empty_candidates = pd.DataFrame()
            batch = pd.DataFrame(
                [{"prospective_status": step9r.CONFIRMATORY_STATUS}]
            )
            decisions = pd.DataFrame()

            with (
                patch.object(step9r, "_read_research_candidates", return_value=historical),
                patch.object(
                    step9r,
                    "_build_prospective_candidates",
                    return_value=(empty_candidates, batch, decisions),
                ),
                patch.object(step9r, "export_csv_for_power_bi"),
            ):
                outputs = step9r.run_prospective_morning(
                    session_date="2026-07-28",
                    price_db=price_db,
                    v3_ledger=v3_ledger,
                    research_db=research_db,
                    prospective_db=prospective_db,
                )

            current_batch = outputs["batches"].loc[
                outputs["batches"]["session_date"].eq("2026-07-28")
            ].iloc[0]
            self.assertEqual(int(current_batch["candidate_rows"]), 0)
            self.assertEqual(int(current_batch["selected_rows"]), 0)
            self.assertEqual(
                current_batch["prospective_status"],
                step9r.CONFIRMATORY_STATUS,
            )
            self.assertTrue(outputs["candidates"].empty)
            self.assertTrue(outputs["selections"].empty)
            self.assertIn("selected", outputs["selections"].columns)


    def test_design_matrix_uses_training_categories_only(self) -> None:
        train_row = {column: 0.0 for column in step9r.NUMERIC_FEATURES}
        test_row = {column: 0.0 for column in step9r.NUMERIC_FEATURES}
        for column in step9r.CATEGORICAL_FEATURES:
            train_row[column] = "TRAIN_LEVEL"
            test_row[column] = "UNSEEN_TEST_LEVEL"
        train = pd.DataFrame([train_row])
        test = pd.DataFrame([test_row])
        x_train, x_test = step9r._design_matrices(train, test, nonlinear=False)
        expected_width = 1 + len(step9r.NUMERIC_FEATURES) + len(step9r.CATEGORICAL_FEATURES)
        self.assertEqual(x_train.shape, (1, expected_width))
        self.assertEqual(x_test.shape, (1, expected_width))
        # All test dummy columns are zero because the test categories were not
        # observed in the training window.
        categorical_start = 1 + len(step9r.NUMERIC_FEATURES)
        self.assertTrue(np.allclose(x_test[0, categorical_start:], 0.0))

    def test_prospective_eod_preserves_all_candidate_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            prospective_db = temp / "prospective.db"
            price_db = temp / "prices.db"
            v3_ledger = temp / "v3.db"
            price_db.write_bytes(b"prices")
            v3_ledger.write_bytes(b"ledger")
            with closing(sqlite3.connect(prospective_db)) as connection:
                step9r._ensure_prospective_schema(connection)
                connection.execute(
                    "INSERT INTO selector_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "B1", "2026-07-29", "2026-07-29T09:47:00+02:00",
                        step9r.EXPERIMENT_ID, step9r.SELECTOR_MODEL, "2026-07-28",
                        20, 100, step9r.CONFIRMATORY_STATUS, 1, 3, 2,
                        "p", "v", "batchhash",
                    ),
                )
                rows = [
                    ("C1", "A.ST", 1),
                    ("C2", "B.ST", 1),
                    ("C3", "C.ST", 0),
                ]
                for rank, (candidate_id, ticker, selected) in enumerate(rows, start=1):
                    connection.execute(
                        "INSERT INTO selector_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            candidate_id, "B1", "2026-07-29", "CONTRACT", ticker,
                            step9r.PRIMARY_ROLE, rank, float(4-rank), 0.3-rank*0.05,
                            rank, selected, "TEST", 1, "{}", f"hash-{rank}",
                        ),
                    )
                connection.commit()

            exact_outcomes = pd.DataFrame(
                [
                    {
                        "contract_id": "CONTRACT", "ticker": "A.ST",
                        "valid_setup": True, "counterfactual_trade_generated": True,
                        "risk_capped_net_pnl_sek": 2.0, "net_r_after_costs": 1.0,
                        "winning_trade": True, "entry_time": "2026-07-29 10:00:00",
                        "exit_time": "2026-07-29 11:00:00", "exit_reason": "TARGET_HIT",
                    },
                    {
                        "contract_id": "CONTRACT", "ticker": "B.ST",
                        "valid_setup": True, "counterfactual_trade_generated": True,
                        "risk_capped_net_pnl_sek": -1.0, "net_r_after_costs": -0.5,
                        "winning_trade": False, "entry_time": "2026-07-29 10:05:00",
                        "exit_time": "2026-07-29 10:30:00", "exit_reason": "STOP_HIT",
                    },
                    {
                        "contract_id": "CONTRACT", "ticker": "C.ST",
                        "valid_setup": True, "counterfactual_trade_generated": False,
                        "risk_capped_net_pnl_sek": 0.0, "net_r_after_costs": 0.0,
                        "winning_trade": False, "entry_time": "",
                        "exit_time": "", "exit_reason": "",
                    },
                ]
            )
            replay = step9r.ReplayFrames(
                taxonomy=pd.DataFrame(), taxonomy_skips=pd.DataFrame(),
                baseline_candidates=pd.DataFrame(), baseline_trades=pd.DataFrame(),
                all_candidates=pd.DataFrame(), all_trades=pd.DataFrame(),
                characteristics=pd.DataFrame(), prices=pd.DataFrame(),
            )
            with (
                patch.object(step9r, "replay_exact_v3", return_value=replay),
                patch.object(step9r, "build_candidate_outcomes", return_value=exact_outcomes),
                patch.object(step9r, "export_csv_for_power_bi"),
            ):
                selected = step9r.run_prospective_eod(
                    session_date="2026-07-29",
                    price_db=price_db,
                    v3_ledger=v3_ledger,
                    prospective_db=prospective_db,
                )
                # Identical rerun must not duplicate or conflict.
                selected_again = step9r.run_prospective_eod(
                    session_date="2026-07-29",
                    price_db=price_db,
                    v3_ledger=v3_ledger,
                    prospective_db=prospective_db,
                )

            with closing(sqlite3.connect(prospective_db)) as connection:
                all_rows = pd.read_sql_query(
                    "SELECT * FROM selector_candidate_outcomes ORDER BY ticker", connection
                )
                selected_rows = pd.read_sql_query(
                    "SELECT * FROM selector_outcomes ORDER BY ticker", connection
                )
            self.assertEqual(len(all_rows), 3)
            self.assertEqual(len(selected_rows), 2)
            self.assertEqual(len(selected), 2)
            self.assertEqual(len(selected_again), 2)
            unselected = all_rows.loc[all_rows["ticker"].eq("C.ST")].iloc[0]
            self.assertEqual(int(unselected["selected"]), 0)
            self.assertEqual(int(unselected["counterfactual_trade_generated"]), 0)
            self.assertEqual(float(unselected["risk_capped_net_pnl_sek"]), 0.0)

    def test_prospective_eod_fails_when_a_morning_candidate_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            prospective_db = temp / "prospective.db"
            price_db = temp / "prices.db"
            v3_ledger = temp / "v3.db"
            price_db.write_bytes(b"prices")
            v3_ledger.write_bytes(b"ledger")
            with closing(sqlite3.connect(prospective_db)) as connection:
                step9r._ensure_prospective_schema(connection)
                connection.execute(
                    "INSERT INTO selector_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "B1", "2026-07-29", "2026-07-29T09:47:00+02:00",
                        step9r.EXPERIMENT_ID, step9r.SELECTOR_MODEL, "2026-07-28",
                        20, 100, step9r.CONFIRMATORY_STATUS, 1, 1, 1,
                        "p", "v", "batchhash",
                    ),
                )
                connection.execute(
                    "INSERT INTO selector_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "C1", "B1", "2026-07-29", "CONTRACT", "A.ST",
                        step9r.PRIMARY_ROLE, 1, 1.0, 0.2, 1, 1, "TEST", 1, "{}", "h",
                    ),
                )
                connection.commit()
            replay = step9r.ReplayFrames(
                taxonomy=pd.DataFrame(), taxonomy_skips=pd.DataFrame(),
                baseline_candidates=pd.DataFrame(), baseline_trades=pd.DataFrame(),
                all_candidates=pd.DataFrame(), all_trades=pd.DataFrame(),
                characteristics=pd.DataFrame(), prices=pd.DataFrame(),
            )
            with (
                patch.object(step9r, "replay_exact_v3", return_value=replay),
                patch.object(step9r, "build_candidate_outcomes", return_value=pd.DataFrame()),
            ):
                with self.assertRaises(step9r.Step9RError):
                    step9r.run_prospective_eod(
                        session_date="2026-07-29",
                        price_db=price_db,
                        v3_ledger=v3_ledger,
                        prospective_db=prospective_db,
                    )

    def test_simple_score_uses_only_training_rows(self) -> None:
        train = pd.DataFrame(
            [
                {"contract_id": "C", "primary_regime": "R", "direction": "LONG", "volatility_bucket": "V", "sector_direction_alignment": "A", "ticker": "X", "rank_bucket": "1", "net_r_after_costs": 1.0},
                {"contract_id": "C", "primary_regime": "R", "direction": "LONG", "volatility_bucket": "V", "sector_direction_alignment": "A", "ticker": "Y", "rank_bucket": "2", "net_r_after_costs": 0.5},
            ]
        )
        test = pd.DataFrame(
            [{"contract_id": "C", "primary_regime": "R", "direction": "LONG", "volatility_bucket": "V", "sector_direction_alignment": "A", "ticker": "X", "rank_bucket": "1"}]
        )
        score = float(step9r.simple_expected_r_scores(train, test).iloc[0])
        self.assertGreater(score, 0)


@unittest.skipUnless(PRICE_DB.exists() and V3_LEDGER.exists() and TAXONOMY_LEDGER.exists(), "Real Step 9R integration databases are not present")
class Step9RIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.price_hash_before = file_hash(PRICE_DB)
        cls.ledger_hash_before = file_hash(V3_LEDGER)
        cls.replay = step9r.replay_exact_v3(
            price_db=PRICE_DB,
            v3_ledger=V3_LEDGER,
            taxonomy_ledger=TAXONOMY_LEDGER,
            start_date="2026-07-27",
            end_date="2026-07-27",
            rebuild_missing_taxonomy=False,
        )
        cls.outcomes = step9r.build_candidate_outcomes(cls.replay)

    def test_july_27_candidate_pool_and_primary_results(self) -> None:
        self.assertEqual(len(self.outcomes), 32)
        primary = self.outcomes[self.outcomes["model_eligible"].map(bool)]
        self.assertEqual(len(primary), 23)
        self.assertEqual(int(primary["winning_trade"].sum()), 3)
        self.assertAlmostEqual(float(primary["risk_capped_net_pnl_sek"].sum()), -21.5842618067, places=7)
        selected = primary[primary["selected_by_v3"].map(bool)]
        self.assertEqual(set(selected["ticker"]), {"SOBI.ST", "HEXA-B.ST"})
        self.assertAlmostEqual(float(selected["risk_capped_net_pnl_sek"].sum()), -4.6634014313, places=6)

    def test_model_eligible_rows_are_point_in_time_and_guardrails_are_excluded(self) -> None:
        eligible = self.outcomes[self.outcomes["model_eligible"].map(bool)]
        self.assertFalse(eligible.empty)
        self.assertTrue(eligible["point_in_time_pass"].map(bool).all())
        self.assertTrue(eligible["max_router_source_label"].astype(str).le(step9r.LATEST_FEATURE_LABEL).all())
        self.assertTrue(eligible["test_role"].eq(step9r.PRIMARY_ROLE).all())

    def test_authoritative_v3_reconciliation(self) -> None:
        reconciliation, checked, failures = step9r.reconcile_authoritative_v3(
            self.replay.baseline_trades,
            V3_LEDGER,
            "2026-07-27",
            "2026-07-27",
        )
        self.assertEqual(checked, 4)
        self.assertEqual(failures, 0)
        self.assertTrue(reconciliation["audit_pass"].map(bool).all())

    def test_source_files_remain_unchanged(self) -> None:
        self.assertEqual(file_hash(PRICE_DB), self.price_hash_before)
        self.assertEqual(file_hash(V3_LEDGER), self.ledger_hash_before)

    def test_strategy_promotion_is_not_available(self) -> None:
        self.assertEqual(step9r.RESEARCH_STATUS, "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION")
        self.assertEqual(step9r.SELECTOR_MODEL, "SIMPLE_EXPECTED_R_SCORE_V1")
        self.assertEqual(step9r.MAX_POSITIONS_PER_TICKER, 1)
        self.assertFalse(hasattr(step9r, "promote_strategy"))

    def test_router_and_orders_are_permanently_disabled(self) -> None:
        self.assertEqual(step9r.RESEARCH_STATUS, "RESEARCH_ONLY_SHADOW_NOT_PRODUCTION")
        self.assertEqual(step9r.MAX_SHADOW_POSITIONS, 2)
        self.assertFalse(hasattr(step9r, "send_order"))


if __name__ == "__main__":
    unittest.main()
