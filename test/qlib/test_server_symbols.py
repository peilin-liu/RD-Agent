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


if __name__ == "__main__":
    unittest.main()
