from __future__ import annotations

import unittest
from unittest.mock import patch

from apps.api.main import configured_watch_symbols


class WatchlistTests(unittest.TestCase):
    def test_default_watchlist_is_parsed_and_deduplicated(self) -> None:
        with patch.dict("os.environ", {"WATCH_SYMBOLS": "EURUSD, GBPUSD, USDJPY, EURUSD"}):
            self.assertEqual(configured_watch_symbols(), ["EURUSD", "GBPUSD", "USDJPY"])

    def test_explicit_symbol_limits_manual_scan(self) -> None:
        self.assertEqual(configured_watch_symbols({"symbol": "gbp/usd"}), ["GBPUSD"])


if __name__ == "__main__":
    unittest.main()
