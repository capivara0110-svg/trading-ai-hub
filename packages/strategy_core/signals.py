from __future__ import annotations

from dataclasses import dataclass

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import atr, rsi, sma


@dataclass(frozen=True)
class Signal:
    symbol: str
    timeframe: str
    side: str
    confidence: float
    entry: float | None
    stop_loss: float | None
    take_profit: list[float]
    reason: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "side": self.side,
            "confidence": self.confidence,
            "entry": self.entry,
            "stopLoss": self.stop_loss,
            "takeProfit": self.take_profit,
            "reason": self.reason,
        }


def detect_forex_signal(
    candles: list[Candle],
    symbol: str = "EURUSD",
    timeframe: str = "M5",
) -> Signal:
    closes = [candle.close for candle in candles]
    fast = sma(closes, 5)
    slow = sma(closes, 20)
    volatility = atr(candles, 14)
    momentum = rsi(closes, 14)

    if fast is None or slow is None or volatility is None or momentum is None:
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["dados insuficientes"])

    last = candles[-1]
    body = abs(last.close - last.open)
    candle_range = max(last.high - last.low, 0.00001)
    body_strength = body / candle_range
    trend_strength = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)

    if fast > slow and last.close > last.open and 48 <= momentum <= 72:
        confidence = round(min(0.52 + trend_strength * 0.2 + body_strength * 0.18, 0.86), 2)
        stop = round(last.close - volatility * 1.2, 5)
        risk = last.close - stop
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side="BUY",
            confidence=confidence,
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close + risk * 1.5, 5), round(last.close + risk * 2.2, 5)],
            reason=["tendência curta compradora", "momentum saudável", "stop baseado em ATR"],
        )

    if fast < slow and last.close < last.open and 28 <= momentum <= 52:
        confidence = round(min(0.52 + trend_strength * 0.2 + body_strength * 0.18, 0.86), 2)
        stop = round(last.close + volatility * 1.2, 5)
        risk = stop - last.close
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side="SELL",
            confidence=confidence,
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close - risk * 1.5, 5), round(last.close - risk * 2.2, 5)],
            reason=["tendência curta vendedora", "momentum saudável", "stop baseado em ATR"],
        )

    return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["sem vantagem estatística clara"])

