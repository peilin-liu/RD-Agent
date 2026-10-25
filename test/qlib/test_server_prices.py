import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from rdagent.log.server import app as server


class PriceAdjustmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "calendars").mkdir()
        (root / "calendars/day.txt").write_text("2026-01-02\n2026-01-05\n2026-01-06\n")
        self.provider = server.QlibDataProvider.__new__(server.QlibDataProvider)
        self.provider.provider_uri = str(root)
        self.provider.price_adjustment = "qfq"
        self.provider._price_anchor_cache = {}
        self.provider.ohlcv_fields = {key: f"${key}/$factor" for key in ("open", "high", "low", "close")}
        self.provider.tech_fields = {"volume": "$volume*$factor", "pe": "$pe_ttm"}
        self.provider.pit_factors = {}
        self.provider.pit_overlay_fields = []
        index = pd.MultiIndex.from_product(
            [pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]), ["000001.SZ"]],
            names=["date", "instrument"],
        )
        # A 2-for-1 action halves nominal prices while the adjusted series stays flat.
        self.frame = pd.DataFrame({
            "$open/$factor": [96.0, 48.0, float("nan")],
            "$high/$factor": [104.0, 52.0, float("nan")],
            "$low/$factor": [94.0, 47.0, float("nan")],
            "$close/$factor": [100.0, 50.0, float("nan")],
            "$volume*$factor": [1000.0, 2000.0, 0.0],
            "$pe_ttm": [10.0, 11.0, float("nan")],
            "$factor": [0.1, 0.2, float("nan")],
            "$factor*$adjclose/$close": [2.0, 4.0, float("nan")],
            "$close": [10.0, 10.0, float("nan")],
        }, index=index)
        self.provider.query = Mock(side_effect=self.query)

    def query(self, instruments, fields, start, end):
        dates = self.frame.index.get_level_values("date")
        symbols = self.frame.index.get_level_values("instrument")
        return self.frame.loc[(dates >= start) & (dates <= end) & symbols.isin(instruments), fields].copy()

    def response(self, **overrides):
        payload = {"instruments": ["000001.SZ"], "start": "2026-01-02", "end": "2026-01-05", **overrides}
        with patch.object(server, "_get_provider", return_value=self.provider):
            return server.app.test_client().post("/api/ohlcv/cn", json=payload)

    def records(self, **overrides):
        response = self.response(**overrides)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        return payload, [dict(zip(payload["columns"], row)) for row in payload["data"]]

    def test_price_modes_convert_all_ohlc_without_changing_volume_or_ratios(self):
        for mode, closes, opens in [
            ("none", [100.0, 50.0], [96.0, 48.0]),
            ("qfq", [50.0, 50.0], [48.0, 48.0]),
            ("hfq", [200.0, 200.0], [192.0, 192.0]),
        ]:
            with self.subTest(mode=mode):
                payload, rows = self.records(adjustment=mode)
                self.assertEqual(payload["adjustment"], mode)
                self.assertEqual([r["close"] for r in rows], closes)
                self.assertEqual([r["open"] for r in rows], opens)
                self.assertEqual([r["high"] for r in rows], [p * 1.04 for p in closes])
                self.assertEqual([r["low"] for r in rows], [p * 0.94 for p in closes])
                self.assertEqual([r["volume"] for r in rows], [1000.0, 2000.0])
                self.assertEqual([r["pe"] for r in rows], [10.0, 11.0])
                self.assertNotIn("$factor", payload["columns"])

    def test_front_adjustment_uses_latest_valid_factor_outside_chart_window(self):
        short, short_rows = self.records(adjustment="qfq", end="2026-01-02")
        long, long_rows = self.records(adjustment="qfq")
        self.assertEqual(short_rows[0]["close"], 50.0)
        self.assertEqual(short_rows[0]["close"], long_rows[0]["close"])
        self.assertEqual(short["adjustment_anchors"]["000001.SZ"], {"date": "2026-01-05", "factor": 0.2})
        self.assertEqual(short["adjustment_anchors"], long["adjustment_anchors"])

    def test_front_adjustment_anchors_each_instrument_separately(self):
        other = self.frame.copy()
        other.index = pd.MultiIndex.from_product(
            [other.index.get_level_values("date"), ["000002.SZ"]], names=["date", "instrument"],
        )
        for field in self.provider.ohlcv_fields.values():
            other[field] *= 0.4
        other["$factor"] *= 5
        self.frame = pd.concat([self.frame, other]).sort_index()
        payload, rows = self.records(adjustment="qfq", instruments=["000001.SZ", "000002.SZ"])
        self.assertEqual([r["close"] for r in rows if r["instrument"] == "000002.SZ"], [20.0, 20.0])
        self.assertEqual(payload["adjustment_anchors"]["000002.SZ"]["factor"], 1.0)

    def test_default_mode_comes_from_region_config(self):
        self.provider.price_adjustment = "none"
        payload, rows = self.records()
        self.assertEqual(payload["adjustment"], "none")
        self.assertEqual(rows[0]["close"], 100.0)

    def test_old_checkbox_clients_have_explicit_compatibility(self):
        for adjust, expected in [(False, 100.0), (True, 200.0)]:
            with self.subTest(adjust=adjust):
                _, rows = self.records(adjust=adjust)
                self.assertEqual(rows[0]["close"], expected)

    def test_invalid_modes_are_rejected(self):
        self.assertEqual(self.response(adjustment="unknown").status_code, 400)
        self.assertEqual(self.response(adjust="false").status_code, 400)

    def test_missing_factor_is_reported_instead_of_silently_using_wrong_prices(self):
        self.frame.loc[(pd.Timestamp("2026-01-02"), "000001.SZ"), "$factor"] = float("nan")
        response = self.response(adjustment="qfq")
        self.assertEqual(response.status_code, 500)
        self.assertIn("adjustment factor", response.get_json()["error"])

    def test_explicit_stored_fields_are_not_adjusted_or_relabelled(self):
        payload, rows = self.records(fields=["$close"], adjustment="qfq")
        self.assertEqual(payload["adjustment"], "stored")
        self.assertEqual([r["$close"] for r in rows], [10.0, 10.0])


if __name__ == "__main__":
    unittest.main()
