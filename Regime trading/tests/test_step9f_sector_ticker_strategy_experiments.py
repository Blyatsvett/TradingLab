import unittest

import pandas as pd

from RegimeTrading.scripts.step9e_instrument_sector_taxonomy import build_static_taxonomy
from RegimeTrading.scripts.step9f_sector_ticker_strategy_experiments import (
    DIMENSION_AUDIT_COLUMNS,
    LEG_CONTEXT_COLUMNS,
    RANKING_COLUMNS,
    SEGMENT_PERFORMANCE_COLUMNS,
    STATE_AUDIT_COLUMNS,
    SUMMARY_COLUMNS,
    TRADE_CONTEXT_COLUMNS,
    build_dimension_audit,
    build_exclusion_robustness,
    build_outputs,
    build_segment_performance,
    build_state_audit,
    enrich_leg_context,
    enrich_trade_context,
)


class Step9FSectorTickerStrategyExperimentTests(unittest.TestCase):
    def setUp(self):
        self.static = build_static_taxonomy()

    def _characteristics(self, days=("2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08")):
        rows = []
        for day in days:
            for ticker in ["SEB-A.ST", "SHB-A.ST", "AZN.ST", "ALFA.ST", "ATCO-A.ST"]:
                sector_count = 3 if ticker in {"SEB-A.ST", "SHB-A.ST"} else 1 if ticker == "AZN.ST" else 3
                rows.append(
                    {
                        "date": day,
                        "ticker": ticker,
                        "ticker_relative_state": "EARLY_LEADER" if ticker in {"SEB-A.ST", "ALFA.ST"} else "EARLY_LAGGARD",
                        "gap_state": "POSITIVE_GAP",
                        "historical_tendency": "CONTINUATION_PRONE",
                        "volatility_bucket": "MEDIUM_RELATIVE_VOL",
                        "range_state": "RANGE_NORMAL",
                        "prior_history_sessions": 10,
                        "minimum_history_ready": True,
                        "full_history_ready": False,
                        "sector_independent_company_count": sector_count,
                        "relative_reference_used": "BROAD_SECTOR" if sector_count >= 2 else "COMPANY_WEIGHTED_MARKET_FALLBACK",
                        "point_in_time_pass": True,
                    }
                )
        return pd.DataFrame(rows)

    def _group_states(self, days=("2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08")):
        rows = []
        for day in days:
            for sector, direction, companies in [
                ("FINANCIALS", "UP", 3),
                ("HEALTH_CARE", "MIXED", 1),
                ("INDUSTRIALS", "DOWN", 3),
            ]:
                rows.append(
                    {
                        "date": day,
                        "aggregation_level": "BROAD_SECTOR",
                        "group_name": sector,
                        "group_direction_state": direction,
                        "group_peer_status": "PEER_GROUP_READY" if companies >= 2 else "SINGLE_COMPANY_PROXY",
                        "point_in_time_pass": True,
                    }
                )
        return pd.DataFrame(rows)

    def _single_trade(self, trade_id, day, ticker, direction="LONG", pnl=1.0, challenger="C1"):
        return {
            "trade_id": trade_id,
            "date": day,
            "primary_regime": "TREND_UP",
            "challenger_id": challenger,
            "strategy_family": "TEST_FAMILY",
            "control_status": "CHALLENGER",
            "idea_type": "SINGLE",
            "direction": direction,
            "ticker": ticker,
            "paired_ticker": "",
            "long_ticker": ticker if direction == "LONG" else "",
            "short_ticker": ticker if direction == "SHORT" else "",
            "entry_time": f"{day} 10:00:00",
            "exit_time": f"{day} 11:00:00",
            "exit_reason": "TARGET",
            "equal_gross_pnl_sek": pnl + 0.5,
            "equal_cost_sek": 0.5,
            "equal_net_pnl_sek": pnl,
            "risk_capped_gross_pnl_sek": pnl + 0.25,
            "risk_capped_cost_sek": 0.25,
            "risk_capped_net_pnl_sek": pnl,
        }

    def _pair_trade(self, trade_id, day, long_ticker, short_ticker, pnl=1.0):
        row = self._single_trade(trade_id, day, long_ticker, direction="LONG", pnl=pnl, challenger="PAIR_C")
        row.update(
            {
                "idea_type": "PAIR",
                "direction": "LONG_SHORT",
                "ticker": long_ticker,
                "paired_ticker": short_ticker,
                "long_ticker": long_ticker,
                "short_ticker": short_ticker,
            }
        )
        return row

    def _legs(self, trades):
        rows = []
        for trade in trades:
            tickers = [trade["ticker"]] if trade["idea_type"] == "SINGLE" else [trade["long_ticker"], trade["short_ticker"]]
            sides = [trade["direction"]] if trade["idea_type"] == "SINGLE" else ["LONG", "SHORT"]
            for idx, (ticker, side) in enumerate(zip(tickers, sides), start=1):
                divisor = len(tickers)
                rows.append(
                    {
                        "trade_id": trade["trade_id"],
                        "leg_id": f"{trade['trade_id']}|L{idx}",
                        "date": trade["date"],
                        "primary_regime": trade["primary_regime"],
                        "challenger_id": trade["challenger_id"],
                        "ticker": ticker,
                        "side": side,
                        "entry_time": trade["entry_time"],
                        "exit_time": trade["exit_time"],
                        "exit_reason": trade["exit_reason"],
                        "equal_net_pnl_sek": trade["equal_net_pnl_sek"] / divisor,
                        "risk_capped_net_pnl_sek": trade["risk_capped_net_pnl_sek"] / divisor,
                    }
                )
        return pd.DataFrame(rows)

    def test_trade_and_leg_context_are_fully_enriched_and_point_in_time_safe(self):
        trades = pd.DataFrame([self._single_trade("T1", "2026-01-05", "SEB-A.ST")])
        legs = self._legs(trades.to_dict("records"))
        trade_context = enrich_trade_context(trades, self.static, self._characteristics(), self._group_states())
        leg_context = enrich_leg_context(legs, self.static, self._characteristics(), self._group_states())
        self.assertEqual(list(trade_context.columns), TRADE_CONTEXT_COLUMNS)
        self.assertEqual(list(leg_context.columns), LEG_CONTEXT_COLUMNS)
        self.assertTrue(trade_context["taxonomy_context_complete"].all())
        self.assertTrue(leg_context["taxonomy_point_in_time_pass"].all())
        self.assertEqual(trade_context.iloc[0]["primary_sector_direction_alignment"], "ALIGNED_WITH_GROUP")

    def test_same_company_atlas_pair_is_flagged(self):
        trades = pd.DataFrame([self._pair_trade("P1", "2026-01-05", "ATCO-A.ST", "ATCO-B.ST")])
        context = enrich_trade_context(trades, self.static, self._characteristics(), self._group_states())
        self.assertTrue(bool(context.iloc[0]["same_company_pair_conflict"]))
        self.assertEqual(context.iloc[0]["pair_relationship"], "SAME_COMPANY_INVALID")

    def test_economic_cluster_is_marked_redundant_in_current_universe(self):
        audit = build_dimension_audit(self.static)
        self.assertEqual(list(audit.columns), DIMENSION_AUDIT_COLUMNS)
        row = audit[audit["dimension_name"].eq("ECONOMIC_CLUSTER")].iloc[0]
        self.assertEqual(row["duplicate_of_dimension"], "BROAD_SECTOR")
        self.assertFalse(bool(row["primary_screening_eligible"]))

    def test_concentrated_historical_tendency_is_flagged(self):
        characteristics = self._characteristics()
        audit = build_state_audit(characteristics)
        self.assertEqual(list(audit.columns), STATE_AUDIT_COLUMNS)
        row = audit[audit["parameter_name"].eq("HISTORICAL_TENDENCY")].iloc[0]
        self.assertEqual(row["discrimination_status"], "LOW_DISCRIMINATION_REVIEW_REQUIRED")

    def test_single_company_sector_is_not_screenable_as_sector_evidence(self):
        trades = pd.DataFrame(
            [self._single_trade(f"A{i}", day, "AZN.ST", pnl=1.0) for i, day in enumerate(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"] * 2)]
        )
        context = enrich_trade_context(trades, self.static, self._characteristics(), self._group_states())
        perf = build_segment_performance(context, self.static)
        sector = perf[(perf["analysis_dimension"].eq("BROAD_SECTOR")) & (perf["segment_value"].eq("HEALTH_CARE"))].iloc[0]
        self.assertEqual(sector["sample_status"], "SINGLE_COMPANY_PROXY_NOT_SCREENABLE_AS_GROUP")
        self.assertEqual(sector["generalization_status"], "TICKER_OR_COMPANY_EVIDENCE_ONLY")

    def test_multi_company_sector_can_be_screenable(self):
        days = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
        rows = []
        for i, day in enumerate(days):
            rows.append(self._single_trade(f"S{i}A", day, "SEB-A.ST", pnl=1.0))
            rows.append(self._single_trade(f"S{i}B", day, "SHB-A.ST", pnl=0.5))
        context = enrich_trade_context(pd.DataFrame(rows), self.static, self._characteristics(), self._group_states())
        perf = build_segment_performance(context, self.static)
        sector = perf[(perf["analysis_dimension"].eq("BROAD_SECTOR")) & (perf["segment_value"].eq("FINANCIALS"))].iloc[0]
        self.assertEqual(sector["sample_status"], "SCREENABLE_HIERARCHICAL_DISCOVERY")
        self.assertEqual(int(sector["observed_independent_companies"]), 2)

    def test_company_exclusion_removes_entire_pair_trade(self):
        trades = pd.DataFrame([self._pair_trade("P1", "2026-01-05", "SEB-A.ST", "SHB-A.ST", pnl=2.0)])
        context = enrich_trade_context(trades, self.static, self._characteristics(), self._group_states())
        robustness = build_exclusion_robustness(context)
        seb = robustness[(robustness["exclusion_type"].eq("COMPANY")) & (robustness["excluded_value"].eq("SEB"))].iloc[0]
        self.assertEqual(int(seb["excluded_trades"]), 1)
        self.assertEqual(int(seb["remaining_trades"]), 0)

    def test_outputs_have_stable_schemas_and_no_promotion(self):
        trades = pd.DataFrame([self._single_trade("T1", "2026-01-05", "SEB-A.ST")])
        legs = self._legs(trades.to_dict("records"))
        outputs = build_outputs(trades, legs, self.static, self._characteristics(), self._group_states())
        summary, _, _, segment, _, _, _, _, rankings = outputs
        self.assertEqual(list(summary.columns), SUMMARY_COLUMNS)
        self.assertEqual(list(segment.columns), SEGMENT_PERFORMANCE_COLUMNS)
        self.assertEqual(list(rankings.columns), RANKING_COLUMNS)
        self.assertEqual(int(summary.iloc[0]["strategies_promoted"]), 0)
        self.assertFalse(bool(summary.iloc[0]["router_active"]))
        self.assertEqual(summary.iloc[0]["classification"], "SECTOR_TICKER_EXPERIMENT_FOUNDATION_READY_FOR_HIERARCHICAL_REVIEW")


if __name__ == "__main__":
    unittest.main()
