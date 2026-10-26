import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rdagent.log.server import app as server


class SymbolsResponseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.symbols_dir = Path(directory.name)

    def load_response(self):
        # Exercise CSV loading and the HTTP response without initializing Qlib.
        provider = server.QlibDataProvider.__new__(server.QlibDataProvider)
        provider.region = "cn"
        provider.symbols_path = str(self.symbols_dir)
        with patch(
            "rdagent.core.region_config.get_region_config",
            return_value=SimpleNamespace(industry_csv_path=""),
        ):
            provider._load_symbols()
        with patch.object(server, "_get_provider", return_value=provider):
            response = server.app.test_client().get("/api/symbols/cn")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        return json.loads(response.get_data(as_text=True), parse_constant=self.reject_nonfinite)

    @staticmethod
    def reject_nonfinite(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    def test_missing_csv_values_serialize_as_null(self):
        (self.symbols_dir / "cn_symbols.csv").write_text(
            "symbol,name,listing_date,delist_date,score\n"
            "000001.SZ,平安银行,1991-04-03,,1.5\n"
            "000002.SZ,万科A,,,\n",
            encoding="utf-8",
        )

        symbols = self.load_response()

        self.assertEqual(len(symbols), 2)
        self.assertEqual(symbols[0]["symbol"], "000001.SZ")
        self.assertEqual(symbols[0]["name"], "平安银行")
        self.assertEqual(symbols[0]["listing_date"], "1991-04-03")
        self.assertEqual(symbols[0]["score"], 1.5)
        self.assertIsNone(symbols[0]["delist_date"])
        self.assertIsNone(symbols[1]["listing_date"])
        self.assertIsNone(symbols[1]["delist_date"])
        self.assertIsNone(symbols[1]["score"])

    def test_missing_symbols_csv_returns_empty_list(self):
        self.assertEqual(self.load_response(), [])


class InstrumentSnapshotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "calendars").mkdir()
        (self.root / "calendars/day.txt").write_text("2026-10-22\n2026-10-23\n2026-10-26\n")
        (self.root / "instruments").mkdir()
        self.provider = server.QlibDataProvider.__new__(server.QlibDataProvider)
        self.provider.provider_uri = str(self.root)
        self.provider._symbols_meta = {"000001.SZ": {"name": "测试股票", "industry_name": "银行"}}

    def write_pool(self, rows, market="csi500"):
        (self.root / "instruments" / f"{market}.txt").write_text("\n".join(rows))

    def test_lagging_index_keeps_latest_members_but_excludes_older_removals(self):
        self.write_pool([
            "000001.SZ\t2020-01-01\t2026-10-23",
            "000002.SZ\t2020-01-01\t2026-10-22",
            "000003.SZ\t2020-01-01\t2026-10-23",
        ])
        rows, date = self.provider.instrument_snapshot("csi500")
        self.assertEqual(date, "2026-10-23")
        self.assertEqual([row["symbol"] for row in rows], ["000001.SZ", "000003.SZ"])
        self.assertEqual(rows[0]["name"], "测试股票")
        self.assertEqual(self.provider._read_instruments("csi500"), rows)

    def test_current_all_pool_still_excludes_delisted_symbols(self):
        self.write_pool(["000001.SZ\t2020-01-01\t2026-10-26", "000002.SZ\t2020-01-01\t2024-01-01"], "all")
        rows, date = self.provider.instrument_snapshot("all")
        self.assertEqual(date, "2026-10-26")
        self.assertEqual([row["symbol"] for row in rows], ["000001.SZ"])

    def test_future_membership_does_not_advance_snapshot_or_add_duplicates(self):
        self.write_pool([
            "000001.SZ\t2020-01-01\t2026-10-23",
            "000001.SZ\t2021-01-01\t2026-10-23",
            "000002.SZ\t2026-11-01\t2026-12-31",
        ])
        rows, date = self.provider.instrument_snapshot("csi500")
        self.assertEqual(date, "2026-10-23")
        self.assertEqual([row["symbol"] for row in rows], ["000001.SZ"])

    def test_open_or_future_end_is_clamped_to_latest_price_date(self):
        for record in ["000001.SZ", "000001.SZ\t2020-01-01\t2099-12-31"]:
            self.write_pool([record])
            rows, date = self.provider.instrument_snapshot("csi500")
            self.assertEqual(date, "2026-10-26")
            self.assertEqual(len(rows), 1)

    def test_empty_missing_or_future_only_pool_is_empty(self):
        self.assertEqual(self.provider.instrument_snapshot("missing"), ([], ""))
        for rows in [[], ["000001.SZ\t2026-11-01\t2026-12-31"]]:
            self.write_pool(rows)
            self.assertEqual(self.provider.instrument_snapshot("csi500"), ([], ""))

    def test_api_exposes_membership_date(self):
        self.write_pool(["000001.SZ\t2020-01-01\t2026-10-23"])
        with patch.object(server, "_get_provider", return_value=self.provider):
            response = server.app.test_client().get("/api/instruments/cn?market=csi500")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["constituents_date"], "2026-10-23")
        self.assertEqual(len(response.get_json()["instruments"]), 1)


if __name__ == "__main__":
    unittest.main()
