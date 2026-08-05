from __future__ import annotations

import unittest
from unittest.mock import patch

from apps.api.main import configured_watch_symbols, paper_stop_distance_pips
from packages.strategy_core.signals import Signal


class WatchlistTests(unittest.TestCase):
    def test_default_watchlist_is_parsed_and_deduplicated(self) -> None:
        with patch.dict("os.environ", {"WATCH_SYMBOLS": "EURUSD, GBPUSD, USDJPY, EURUSD"}):
            self.assertEqual(configured_watch_symbols(), ["EURUSD", "GBPUSD", "USDJPY"])

    def test_explicit_symbol_limits_manual_scan(self) -> None:
        self.assertEqual(configured_watch_symbols({"symbol": "gbp/usd"}), ["GBPUSD"])

    def test_paper_stop_distance_uses_standard_pip_scale(self) -> None:
        signal = Signal("EURUSD", "M5", "BUY", 0.7, 1.1000, 1.0985, [1.1024], [])
        self.assertEqual(paper_stop_distance_pips(signal), 15.0)

    def test_paper_stop_distance_uses_jpy_pip_scale(self) -> None:
        signal = Signal("USDJPY", "M5", "SELL", 0.7, 157.50, 157.65, [157.26], [])
        self.assertEqual(paper_stop_distance_pips(signal), 15.0)


if __name__ == "__main__":
    unittest.main()
