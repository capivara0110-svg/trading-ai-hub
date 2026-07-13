from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from packages.strategy_core.backtest import BacktestCosts
from packages.strategy_core.data import Candle
from packages.strategy_core.datasets import normalize_candle_time, parse_uploaded_candles
from packages.strategy_core.decision_log import evaluate_decisions, record_decision
from packages.strategy_core.execution import execution_cooldown_ok, safe_daily_order_limit
from packages.strategy_core.validation import simulate_trade
from packages.strategy_core.walk_forward import run_walk_forward_validation
from packages.strategy_core.ml_model import frozen_training_candles
from packages.strategy_core.validation import SimulationPolicy, higher_timeframe_directions, policy_block_reason


class TimeNormalizationTests(unittest.TestCase):
    def test_mt5_broker_time_is_converted_to_utc(self) -> None:
        self.assertEqual(
            normalize_candle_time("2026.07.13 09:00:00", "-03:00"),
            "2026-07-13 12:00:00Z",
        )

    def test_naive_legacy_time_is_not_silently_shifted(self) -> None:
        self.assertEqual(normalize_candle_time("2026-07-13 09:00:00"), "2026-07-13 09:00:00")

    def test_mt5_export_columns_are_supported(self) -> None:
        header = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>"
        rows = [header]
        for minute in range(25):
            rows.append(f"2026.07.13\t09:{minute:02d}:00\t1.10\t1.11\t1.09\t1.10\t100")
        candles = parse_uploaded_candles("\n".join(rows), "-03:00")
        self.assertEqual(candles[0].time, "2026-07-13 12:00:00Z")


class BacktestCostTests(unittest.TestCase):
    def test_costs_are_deducted_from_gross_result(self) -> None:
        candles = make_candles(30)
        trade = simulate_trade(
            candles,
            20,
            3,
            "BUY",
            candles[20].close,
            candles[20].close - 0.0100,
            candles[20].close + 0.0001,
            BacktestCosts(spread_pips=1.0, slippage_pips=0.2, commission_pips=0.1),
        )
        self.assertAlmostEqual(trade.gross_result_pips, 1.0)
        self.assertAlmostEqual(trade.cost_pips, 1.3)
        self.assertAlmostEqual(trade.result_pips, -0.3)


class WalkForwardTests(unittest.TestCase):
    def test_walk_forward_keeps_test_period_after_training_period(self) -> None:
        result = run_walk_forward_validation(make_candles(120), train_candles=80, test_candles=40)
        self.assertEqual(result["summary"]["folds"], 1)
        fold = result["folds"][0]
        self.assertLess(fold["trainPeriod"]["end"], fold["testPeriod"]["start"])

    def test_higher_timeframe_uses_only_completed_candles(self) -> None:
        candles = make_candles(70)
        directions = higher_timeframe_directions(candles, 15)
        self.assertIsNone(directions[59])
        self.assertIn(directions[60], {"BUY", "SELL"})

    def test_session_gate_blocks_outside_london_and_new_york(self) -> None:
        candles = make_candles(30)
        signal = SimpleNamespace(
            side="BUY", strategy_style="TREND_HUNTER", entry=1.10, take_profit=[1.102]
        )
        reason = policy_block_reason(
            candles, 25, signal, {"m15": "BUY", "h1": "BUY", "atrRatio": 1.0},
            BacktestCosts(1.0, 0.2, 0.1), SimulationPolicy()
        )
        self.assertEqual(reason, "outside_sessions")


class FrozenModelTests(unittest.TestCase):
    def test_future_candles_do_not_enter_frozen_training_set(self) -> None:
        candles = make_candles(40)
        cutoff = candles[29].time
        with patch.dict("os.environ", {"ML_FREEZE_AT_TIME": cutoff}):
            frozen = frozen_training_candles(candles)
        self.assertEqual(len(frozen), 30)


class DecisionLogTests(unittest.TestCase):
    def test_blocked_paper_signal_receives_hypothetical_result(self) -> None:
        candles = make_candles(30)
        signal = SimpleNamespace(
            to_dict=lambda: {
                "symbol": "EURUSD", "timeframe": "M5", "side": "BUY", "confidence": 0.8,
                "mlScore": 0.6, "mlTrained": True, "strategyStyle": "TREND_HUNTER",
                "entry": candles[20].close, "stopLoss": candles[20].close - 0.01,
                "takeProfit": [candles[20].close + 0.0001], "reason": ["teste"],
            }
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "decisions.json"
            record_decision(path, candles[20].time, signal, False, "cooldown", {"created": False})
            result = evaluate_decisions(path, candles)
        self.assertEqual(result["closed"], 1)

    def test_execution_cooldown_blocks_recent_closed_order(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        allowed, reason = execution_cooldown_ok(
            {"orders": {"1": {"status": "LOSS", "closedAt": now}}}
        )
        self.assertFalse(allowed)
        self.assertIn("cooldown", reason)

    def test_zero_daily_limit_falls_back_to_safe_limit(self) -> None:
        with patch.dict("os.environ", {"AUTO_TRADE_MAX_ORDERS_PER_DAY": "0"}):
            self.assertEqual(safe_daily_order_limit(), 2)


def make_candles(count: int) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles: list[Candle] = []
    price = 1.10
    for index in range(count):
        drift = 0.0001 if (index // 12) % 2 == 0 else -0.00008
        open_price = price
        price += drift
        candles.append(
            Candle(
                time=(start + timedelta(minutes=5 * index)).isoformat().replace("+00:00", "Z"),
                open=open_price,
                high=max(open_price, price) + 0.00015,
                low=min(open_price, price) - 0.00015,
                close=price,
                volume=100 + index,
            )
        )
    return candles


if __name__ == "__main__":
    unittest.main()
