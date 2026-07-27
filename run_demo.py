from __future__ import annotations

from pathlib import Path

from packages.strategy_core.strategy_v1_enhanced import detect_forex_signal_enhanced, run_backtest_enhanced
from packages.strategy_core.data import load_candles


ROOT = Path(__file__).resolve().parent


def main() -> None:
    candles = load_candles(ROOT / "data" / "forex" / "eurusd_m5_sample.csv")
    signal = detect_forex_signal_enhanced(candles)
    backtest = run_backtest_enhanced(candles, min_confidence=0.5)

    print("Sinal atual (V1 Enhanced):")
    print(signal.to_dict())
    print()
    print("Backtest (V1 Enhanced):")
    print(backtest.to_dict())


if __name__ == "__main__":
    main()
