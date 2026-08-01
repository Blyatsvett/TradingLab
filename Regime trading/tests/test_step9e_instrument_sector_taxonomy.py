import unittest

import numpy as np
import pandas as pd

from RegimeTrading.scripts.step9e_instrument_sector_taxonomy import (
    AUDIT_COLUMNS,
    CHARACTERISTIC_COLUMNS,
    COMPLETENESS_COLUMNS,
    CONSTRAINT_COLUMNS,
    GROUP_STATE_COLUMNS,
    STATIC_COLUMNS,
    SUMMARY_COLUMNS,
    build_outputs,
    build_point_in_time_characteristics,
    build_static_taxonomy,
)


class Step9EInstrumentSectorTaxonomyTests(unittest.TestCase):
    def _bars(self, ticker, day, open_price, cutoff_close, close_price):
        high_1 = max(open_price, cutoff_close) * 1.002
        low_1 = min(open_price, cutoff_close) * 0.998
        return [
            {
                "datetime": pd.Timestamp(f"{day} 09:30"),
                "open": open_price,
                "high": high_1,
                "low": low_1,
                "close": (open_price + cutoff_close) / 2,
                "ticker": ticker,
                "date": pd.Timestamp(day).date(),
            },
            {
                "datetime": pd.Timestamp(f"{day} 09:35"),
                "open": (open_price + cutoff_close) / 2,
                "high": high_1,
                "low": low_1,
                "close": cutoff_close * 0.999,
                "ticker": ticker,
                "date": pd.Timestamp(day).date(),
            },
            {
                "datetime": pd.Timestamp(f"{day} 09:40"),
                "open": cutoff_close * 0.999,
                "high": max(high_1, cutoff_close),
                "low": min(low_1, cutoff_close),
                "close": cutoff_close,
                "ticker": ticker,
                "date": pd.Timestamp(day).date(),
            },
            {
                "datetime": pd.Timestamp(f"{day} 16:30"),
                "open": cutoff_close,
                "high": max(cutoff_close, close_price),
                "low": min(cutoff_close, close_price),
                "close": close_price,
                "ticker": ticker,
                "date": pd.Timestamp(day).date(),
            },
        ]

    def _prices(self):
        rows = []
        days = pd.bdate_range("2026-01-02", periods=7)
        for i, date in enumerate(days):
            day = date.strftime("%Y-%m-%d")
            rows += self._bars("ATCO-A.ST", day, 100 + i, 101 + i, 102 + i)
            rows += self._bars("ATCO-B.ST", day, 200 + i, 202 + i, 204 + i)
            rows += self._bars("ALFA.ST", day, 90 + i, 89.5 + i, 89 + i)
            rows += self._bars("SEB-A.ST", day, 120 + i, 120.2 + i, 120.4 + i)
        return pd.DataFrame(rows)

    def test_static_taxonomy_maps_eleven_symbols_to_ten_companies(self):
        static = build_static_taxonomy()
        self.assertEqual(list(static.columns), STATIC_COLUMNS)
        self.assertEqual(len(static), 11)
        self.assertEqual(static["company_id"].nunique(), 10)
        self.assertEqual(static["broad_sector"].nunique(), 6)

    def test_atlas_copco_share_classes_have_half_company_weight(self):
        static = build_static_taxonomy()
        atlas = static[static["company_id"].eq("ATLAS_COPCO")]
        self.assertEqual(set(atlas["ticker"]), {"ATCO-A.ST", "ATCO-B.ST"})
        self.assertTrue(np.allclose(atlas["company_observation_weight"], 0.5))
        self.assertAlmostEqual(float(atlas["company_observation_weight"].sum()), 1.0)

    def test_prior_characteristics_exclude_current_session(self):
        static = build_static_taxonomy()
        characteristics, _, _, audit = build_point_in_time_characteristics(
            self._prices(), static, history_window=5, minimum_history=2
        )
        last_date = characteristics["date"].max()
        last = characteristics[characteristics["date"].eq(last_date)]
        self.assertTrue(last["minimum_history_ready"].all())
        self.assertTrue(
            all(pd.Timestamp(value).date() < pd.Timestamp(last_date).date() for value in last["prior_history_max_date"])
        )
        self.assertTrue(audit["point_in_time_pass"].all())

    def test_same_day_sources_stop_at_0940(self):
        characteristics, groups, _, audit = build_point_in_time_characteristics(
            self._prices(), build_static_taxonomy(), history_window=5, minimum_history=2
        )
        self.assertTrue(characteristics["max_same_day_source_label"].le("09:40").all())
        self.assertTrue(groups["max_same_day_source_label"].le("09:40").all())
        self.assertTrue(audit["max_source_label"].le("09:40").all())

    def test_company_weighted_market_does_not_double_count_atlas_classes(self):
        static = build_static_taxonomy()
        characteristics, _, _, _ = build_point_in_time_characteristics(
            self._prices(), static, history_window=5, minimum_history=2
        )
        first_date = characteristics["date"].min()
        day = characteristics[characteristics["date"].eq(first_date)]
        atco_a = float(day.loc[day["ticker"].eq("ATCO-A.ST"), "cutoff_return_from_open"].iloc[0])
        atco_b = float(day.loc[day["ticker"].eq("ATCO-B.ST"), "cutoff_return_from_open"].iloc[0])
        alfa = float(day.loc[day["ticker"].eq("ALFA.ST"), "cutoff_return_from_open"].iloc[0])
        seb = float(day.loc[day["ticker"].eq("SEB-A.ST"), "cutoff_return_from_open"].iloc[0])
        expected = (0.5 * atco_a + 0.5 * atco_b + alfa + seb) / 3.0
        actual = float(day["market_return_from_open_company_weighted"].iloc[0])
        self.assertAlmostEqual(actual, expected, places=12)

    def test_single_company_sector_uses_fallback_reference(self):
        characteristics, _, _, _ = build_point_in_time_characteristics(
            self._prices(), build_static_taxonomy(), history_window=5, minimum_history=2
        )
        # The synthetic data only contains one observed bank company, so the sector
        # cannot be treated as a true peer comparison for that date.
        seb = characteristics[characteristics["ticker"].eq("SEB-A.ST")]
        self.assertTrue(seb["relative_reference_used"].isin(["ECONOMIC_CLUSTER", "COMPANY_WEIGHTED_MARKET_FALLBACK"]).all())
        self.assertTrue(seb["sector_relative_return"].isna().all())

    def test_missing_early_label_does_not_crash_mixed_group(self):
        prices = self._prices()
        target_date = prices["date"].min()
        missing_early = (
            prices["ticker"].eq("ATCO-B.ST")
            & prices["date"].eq(target_date)
            & prices["datetime"].dt.strftime("%H:%M").le("09:40")
        )
        prices = prices.loc[~missing_early].copy()

        characteristics, groups, _, _ = build_point_in_time_characteristics(
            prices, build_static_taxonomy(), history_window=5, minimum_history=2
        )

        missing_row = characteristics[
            characteristics["date"].eq(target_date)
            & characteristics["ticker"].eq("ATCO-B.ST")
        ].iloc[0]
        self.assertEqual(missing_row["max_same_day_source_label"], "")
        self.assertFalse(bool(missing_row["point_in_time_pass"]))
        self.assertEqual(missing_row["characteristic_status"], "INCOMPLETE_REVIEW_REQUIRED")

        industrials = groups[
            groups["date"].eq(target_date)
            & groups["aggregation_level"].eq("BROAD_SECTOR")
            & groups["group_name"].eq("INDUSTRIALS")
        ].iloc[0]
        self.assertEqual(industrials["max_same_day_source_label"], "09:40")
        self.assertTrue(bool(industrials["point_in_time_pass"]))

    def test_all_missing_group_labels_fail_point_in_time_safely(self):
        prices = self._prices()
        target_date = prices["date"].min()
        industrial_tickers = {"ATCO-A.ST", "ATCO-B.ST", "ALFA.ST"}
        missing_early = (
            prices["ticker"].isin(industrial_tickers)
            & prices["date"].eq(target_date)
            & prices["datetime"].dt.strftime("%H:%M").le("09:40")
        )
        prices = prices.loc[~missing_early].copy()

        _, groups, _, _ = build_point_in_time_characteristics(
            prices, build_static_taxonomy(), history_window=5, minimum_history=2
        )
        industrials = groups[
            groups["date"].eq(target_date)
            & groups["aggregation_level"].eq("BROAD_SECTOR")
            & groups["group_name"].eq("INDUSTRIALS")
        ].iloc[0]

        self.assertEqual(industrials["max_same_day_source_label"], "")
        self.assertFalse(bool(industrials["point_in_time_pass"]))
        self.assertEqual(int(industrials["observed_ticker_count"]), 0)

    def test_outputs_have_stable_schemas_and_no_router_activation(self):
        outputs = build_outputs(self._prices())
        summary, static, _, characteristics, groups, completeness, constraints, audit = outputs
        self.assertEqual(list(summary.columns), SUMMARY_COLUMNS)
        self.assertEqual(list(static.columns), STATIC_COLUMNS)
        self.assertEqual(list(characteristics.columns), CHARACTERISTIC_COLUMNS)
        self.assertEqual(list(groups.columns), GROUP_STATE_COLUMNS)
        self.assertEqual(list(completeness.columns), COMPLETENESS_COLUMNS)
        self.assertEqual(list(constraints.columns), CONSTRAINT_COLUMNS)
        self.assertEqual(list(audit.columns), AUDIT_COLUMNS)
        self.assertFalse(bool(summary.iloc[0]["router_active"]))

    def test_mechanical_classification_is_ready(self):
        summary = build_outputs(self._prices())[0].iloc[0]
        self.assertEqual(
            summary["classification"],
            "INSTRUMENT_TAXONOMY_READY_FOR_SECTOR_STRATEGY_EXPERIMENTS",
        )
        self.assertTrue(bool(summary["company_weight_audit_pass"]))
        self.assertEqual(int(summary["future_source_rows"]), 0)


if __name__ == "__main__":
    unittest.main()
