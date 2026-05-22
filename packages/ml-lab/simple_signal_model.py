from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Candle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def load_candles(path: Path) -> list[Candle]:
    with path.open(newline="", encoding="utf-8") as file:
        rows = csv.DictReader(file)
        return [
            Candle(
                time=row["time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in rows
        ]


def simple_moving_average(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def detect_signal(candles: list[Candle]) -> dict[str, object]:
    closes = [candle.close for candle in candles]
    fast = simple_moving_average(closes, 3)
    slow = simple_moving_average(closes, 5)

    if fast is None or slow is None:
        return {"side": "NO_TRADE", "confidence": 0.0, "reason": ["dados insuficientes"]}

    last = candles[-1]
    candle_range = max(last.high - last.low, 1)
    body_strength = abs(last.close - last.open) / candle_range

    if fast > slow and last.close > last.open:
        return {
            "side": "BUY",
            "confidence": round(min(0.55 + body_strength * 0.25, 0.85), 2),
            "entry": last.close,
            "stopLoss": last.low,
            "takeProfit": [last.close + candle_range, last.close + candle_range * 2],
            "reason": ["média curta acima da longa", "candle comprador"],
        }

    if fast < slow and last.close < last.open:
        return {
            "side": "SELL",
            "confidence": round(min(0.55 + body_strength * 0.25, 0.85), 2),
            "entry": last.close,
            "stopLoss": last.high,
            "takeProfit": [last.close - candle_range, last.close - candle_range * 2],
            "reason": ["média curta abaixo da longa", "candle vendedor"],
        }

    return {"side": "NO_TRADE", "confidence": 0.0, "reason": ["sem alinhamento claro"]}


if __name__ == "__main__":
    candles_path = Path(__file__).with_name("sample_candles.csv")
    print(detect_signal(load_candles(candles_path)))

