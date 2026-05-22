from __future__ import annotations

from pathlib import Path

from packages.strategy_core.backtest import run_backtest
from packages.strategy_core.data import load_candles
from packages.strategy_core.signals import detect_forex_signal


ROOT = Path(__file__).resolve().parent


def main() -> None:
    candles = load_candles(ROOT / "data" / "forex" / "eurusd_m5_sample.csv")
    signal = detect_forex_signal(candles)
    backtest = run_backtest(candles, min_confidence=0.5)

    print("Sinal atual:")
    print(signal.to_dict())
    print()
    print("Backtest:")
    print(backtest.to_dict())


if __name__ == "__main__":
    main()
