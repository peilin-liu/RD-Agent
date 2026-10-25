import unittest

import test_server_prices as price_tests


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


if __name__ == "__main__":
    unittest.main()
