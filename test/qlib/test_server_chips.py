import unittest

import pandas as pd
import test_server_prices as price_tests
from rdagent.log.server.screening import chip_cost_metrics, chip_screening_fields, historical_screening_metrics


class ChipOverlayTests(unittest.TestCase):
    def setUp(self):
        # Reuse the synthetic split/factor fixture without initializing Qlib.
        self.prices = price_tests.PriceAdjustmentTests("test_default_mode_comes_from_region_config")
        self.prices.setUp()
        self.addCleanup(self.prices.doCleanups)
        self.provider = self.prices.provider
        self.provider.chips = {
            "price_adjustment": "qfq",
            "price_fields": {
                "weight_avg": "$weight_avg",
                "cost_15pct": "$cost_15pct",
                "cost_85pct": "$cost_85pct",
            },
            "rate_fields": {"winner_rate": "$winner_rate"},
            "default_layers": ["weight_avg", "band_70", "winner_rate"],
        }
        for name, values in {
            "$weight_avg": [60.0, 55.0, float("nan")],
            "$cost_15pct": [40.0, 42.0, float("nan")],
            "$cost_85pct": [70.0, 66.0, float("nan")],
            "$winner_rate": [0.0, 57.0, float("nan")],
        }.items():
            self.prices.frame[name] = values

    def test_costs_follow_chart_price_mode_while_rates_keep_percent_units(self):
        for mode, expected in [
            ("qfq", [60.0, 55.0]),
            ("none", [120.0, 55.0]),
            ("hfq", [240.0, 220.0]),
        ]:
            with self.subTest(mode=mode):
                payload, rows = self.prices.records(adjustment=mode)
                self.assertEqual([row["weight_avg"] for row in rows], expected)
                self.assertEqual([row["winner_rate"] for row in rows], [0.0, 57.0])
                self.assertEqual(payload["chips"]["adjustment"], mode)
                self.assertEqual(payload["chips"]["source_adjustment"], "qfq")
                self.assertEqual(payload["chips"]["default_layers"], ["weight_avg", "band_70", "winner_rate"])
                self.assertNotIn("$factor", payload["columns"])
                self.assertNotIn("$factor*$adjclose/$close", payload["columns"])

    def test_cost_band_bounds_get_the_same_price_scale(self):
        _, rows = self.prices.records(adjustment="hfq")
        self.assertEqual(rows[0]["cost_15pct"], 160.0)
        self.assertEqual(rows[0]["cost_85pct"], 280.0)
        self.assertEqual(rows[1]["cost_15pct"], 168.0)
        self.assertEqual(rows[1]["cost_85pct"], 264.0)

    def test_conversion_anchor_does_not_depend_on_chart_window(self):
        short, short_rows = self.prices.records(adjustment="none", end="2026-01-02")
        long, long_rows = self.prices.records(adjustment="none")
        self.assertEqual(short_rows[0]["weight_avg"], 120.0)
        self.assertEqual(short_rows[0]["weight_avg"], long_rows[0]["weight_avg"])
        self.assertEqual(short["chips"]["anchors"], long["chips"]["anchors"])

    def test_missing_chip_values_stay_null_without_hiding_candlesticks(self):
        for name in self.provider.chips["price_fields"].values():
            self.prices.frame[name] = float("nan")
        _, rows = self.prices.records(adjustment="none")
        self.assertEqual([row["close"] for row in rows], [100.0, 50.0])
        self.assertTrue(all(row["weight_avg"] is None for row in rows))
        self.assertEqual(rows[0]["winner_rate"], 0.0)

    def test_explicit_low_level_queries_bypass_chip_display_conversion(self):
        payload, rows = self.prices.records(fields=["$weight_avg"], adjustment="none")
        self.assertEqual([row["$weight_avg"] for row in rows], [60.0, 55.0])
        self.assertEqual(payload["chips"]["price_fields"], [])

    def test_screening_ratios_are_equal_in_all_price_modes(self):
        results = []
        for mode in ("none", "qfq", "hfq"):
            self.provider.query.reset_mock()
            row = self.provider.chip_snapshot_metrics(["000001.SZ"], "2026-01-02", mode)["000001.SZ"]
            results.append(row)
            self.assertEqual(self.provider.query.call_args_list[0].args[2:], ("2026-01-02", "2026-01-02"))
            self.assertAlmostEqual(row["chip_avg_cost_bias"], (50 / 60 - 1) * 100)
            self.assertAlmostEqual(row["chip_concentration_70"], 30 / 40 * 100)
            self.assertAlmostEqual(row["chip_band_70_position"], 100 / 3)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])


class ChipScreeningTests(unittest.TestCase):
    def test_band_positions_and_bias_allow_negative_and_above_100_values(self):
        costs = {"weight_avg": 10, "cost_50pct": 8, "cost_15pct": 8, "cost_85pct": 12,
                 "cost_5pct": 5, "cost_95pct": 15}
        row = chip_cost_metrics(14, costs)
        self.assertAlmostEqual(row["chip_avg_cost_bias"], 40)
        self.assertEqual(row["chip_median_cost_bias"], 75)
        self.assertEqual(row["chip_concentration_70"], 50)
        self.assertEqual(row["chip_concentration_90"], 200)
        self.assertEqual(row["chip_band_70_position"], 150)
        self.assertEqual(row["chip_band_90_position"], 90)
        row = chip_cost_metrics(4, costs)
        self.assertEqual(row["chip_avg_cost_bias"], -60)
        self.assertEqual(row["chip_band_70_position"], -100)

    def test_invalid_and_flat_bands_do_not_produce_false_positions(self):
        for value in (None, float("nan"), float("inf"), 0, -1):
            row = chip_cost_metrics(10, {"weight_avg": value, "cost_15pct": value, "cost_85pct": 12})
            self.assertIsNone(row["chip_avg_cost_bias"])
            self.assertIsNone(row["chip_concentration_70"])
            self.assertIsNone(row["chip_band_70_position"])
        row = chip_cost_metrics(10, {"cost_15pct": 12, "cost_85pct": 8})
        self.assertIsNone(row["chip_concentration_70"])
        row = chip_cost_metrics(10, {"cost_15pct": 10, "cost_85pct": 10})
        self.assertEqual(row["chip_concentration_70"], 0)
        self.assertIsNone(row["chip_band_70_position"])

    def test_available_fields_follow_configured_sources(self):
        self.assertEqual(chip_screening_fields({}), [])
        self.assertEqual(chip_screening_fields({"price_fields": {"weight_avg": "$avg"}}), ["chip_avg_cost_bias"])
        fields = chip_screening_fields({"price_fields": {"cost_15pct": "$low"}, "rate_fields": {"winner_rate": "$rate"}})
        self.assertIn("winner_rate_change_20d", fields)
        self.assertNotIn("chip_concentration_70", fields)

    def test_winner_changes_use_market_trading_days_and_percentage_points(self):
        dates = pd.bdate_range("2026-01-02", periods=26)
        frame = pd.DataFrame({"winner_rate": list(range(20, 45)) + [100]},
                             index=pd.MultiIndex.from_product([dates, ["TEST"]], names=["date", "instrument"]))
        end = str(dates[-2].date())
        row = historical_screening_metrics(frame, end, calendar=dates)["TEST"]
        self.assertEqual(row["winner_rate"], 44)
        self.assertEqual(row["winner_rate_change_5d"], 5)
        self.assertEqual(row["winner_rate_change_20d"], 20)
        # Missing the exact five-day baseline must not borrow another day's value.
        frame = frame.drop((dates[19], "TEST"))
        row = historical_screening_metrics(frame, end, calendar=dates)["TEST"]
        self.assertIsNone(row["winner_rate_change_5d"])
        self.assertEqual(row["winner_rate_change_20d"], 20)


if __name__ == "__main__":
    unittest.main()
