import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from rdagent.log.server import app as server
from rdagent.log.server.screening import historical_screening_metrics


class ScreeningMetricsTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.bdate_range("2025-01-02", periods=252)
        self.end = self.dates[-2].strftime("%Y-%m-%d")
        self.index = pd.MultiIndex.from_product([self.dates, ["TEST.SZ"]], names=["date", "instrument"])
        self.frame = pd.DataFrame({"close": range(252), "volume": 100, "winner_rate": 40.0}, index=self.index)

    def metrics(self):
        return historical_screening_metrics(self.frame, self.end)["TEST.SZ"]

    def test_ma_differences_for_all_three_periods_and_directions(self):
        for multiplier in (1, 0, -1):
            self.frame["close"] = [1000 + multiplier * i for i in range(252)]
            row = self.metrics()
            for period in (5, 20, 60):
                self.assertAlmostEqual(row[f"ma{period}_slope"], multiplier)

    def test_250_trading_days_exclude_older_and_future_extremes(self):
        self.frame["winner_rate"] = [0, 20] + [40] * 248 + [50, 100]
        row = self.metrics()
        self.assertEqual(row["winner_rate"], 50)
        # Old 0 and future 100 must both be excluded: current 50 is the max.
        self.assertEqual(row["winner_rate_position_250d"], 100)
        self.frame.loc[(self.dates[100], "TEST.SZ"), "winner_rate"] = 80
        self.assertEqual(self.metrics()["winner_rate_position_250d"], 50)

    def test_flat_missing_and_invalid_chip_ranges_remain_null(self):
        self.assertIsNone(self.metrics()["winner_rate_position_250d"])
        for value in (float("nan"), float("inf"), -1, 101):
            self.frame.loc[(self.dates[-2], "TEST.SZ"), "winner_rate"] = value
            row = self.metrics()
            self.assertIsNone(row["winner_rate"])
            self.assertIsNone(row["winner_rate_position_250d"])

    def test_short_history_can_form_ma5_but_not_ma20_or_ma60(self):
        self.frame = self.frame.iloc[-7:]
        row = self.metrics()
        self.assertEqual(row["ma5_slope"], 1)
        self.assertIsNone(row["ma20_slope"])
        self.assertIsNone(row["ma60_slope"])

    def test_suspended_current_day_does_not_reuse_a_previous_ma_signal(self):
        self.frame.loc[(self.dates[-2], "TEST.SZ"), "volume"] = 0
        row = self.metrics()
        self.assertTrue(all(row[f"ma{p}_slope"] is None for p in (5, 20, 60)))

    def test_missing_current_day_does_not_reuse_previous_chip_value(self):
        self.frame = self.frame.drop((self.dates[-2], "TEST.SZ"))
        self.assertTrue(all(value is None for value in self.metrics().values()))

    def test_symbols_are_calculated_independently(self):
        other = self.frame.copy()
        other.index = pd.MultiIndex.from_product([self.dates, ["OTHER.SZ"]], names=["date", "instrument"])
        other["close"] = -other["close"]
        rows = historical_screening_metrics(pd.concat([self.frame, other]), self.end)
        self.assertEqual(rows["TEST.SZ"]["ma60_slope"], 1)
        self.assertEqual(rows["OTHER.SZ"]["ma60_slope"], -1)

    def test_provider_queries_calendar_window_and_uses_adjusted_prices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "calendars").mkdir()
            (root / "calendars/day.txt").write_text("\n".join(d.strftime("%Y-%m-%d") for d in self.dates))
            provider = server.QlibDataProvider.__new__(server.QlibDataProvider)
            provider.provider_uri = str(root)
            provider.ohlcv_fields = {"close": "$nominal"}
            provider.tech_fields = {"volume": "$volume"}
            provider.chips = {"rate_fields": {"winner_rate": "$winner"}}
            provider._price_anchor_cache = {}
            data = self.frame.rename(columns={"close": "$nominal", "volume": "$volume", "winner_rate": "$winner"})
            data["$factor"] = [1] * 249 + [2] * 3
            data["$nominal"] = 100 / data["$factor"]
            provider.query = Mock(return_value=data)
            provider.latest_price_anchors = Mock(return_value={"TEST.SZ": {"factor": 2, "date": self.end}})
            row = provider.screening_metrics(["TEST.SZ"], self.end, "qfq")["TEST.SZ"]
            self.assertEqual(row["ma5_slope"], 0)
            self.assertEqual(provider.query.call_args.args[2:], (self.dates[1].strftime("%Y-%m-%d"), self.end))
            row = provider.screening_metrics(["TEST.SZ"], self.end, "none")["TEST.SZ"]
            self.assertEqual(row["ma5_slope"], -10)

    def test_endpoint_only_computes_history_when_requested(self):
        provider = Mock(price_adjustment="qfq", prediction_dirs={})
        provider._parse_date.return_value = self.end
        provider.market_snapshot.side_effect = lambda *_: [{"symbol": "TEST.SZ"}]
        provider.screening_metrics.return_value = {"TEST.SZ": {"ma5_slope": 1, "winner_rate_position_250d": 50}}
        with patch.object(server, "_get_provider", return_value=provider):
            client = server.app.test_client()
            basic = client.get(f"/api/market_snapshot/cn?market=all&date={self.end}")
            self.assertEqual(basic.status_code, 200)
            provider.screening_metrics.assert_not_called()
            enhanced = client.get(f"/api/market_snapshot/cn?market=all&date={self.end}&screening=1&adjustment=none")
            self.assertEqual(enhanced.status_code, 200)
            self.assertTrue(enhanced.get_json()["screening"])
            self.assertEqual(enhanced.get_json()["data"][0]["winner_rate_position_250d"], 50)
            provider.screening_metrics.assert_called_once_with(["TEST.SZ"], self.end, "none")
            self.assertEqual(client.get(f"/api/market_snapshot/cn?screening=1&adjustment=invalid&date={self.end}").status_code, 400)


if __name__ == "__main__":
    unittest.main()
