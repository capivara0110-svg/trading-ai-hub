from __future__ import annotations

from dataclasses import dataclass

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import atr, rsi, sma
from packages.strategy_core.ml_model import extract_features, train_signal_quality_model


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
    ml_score: float | None = None
    ml_trained: bool = False

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
            "mlScore": self.ml_score,
            "mlTrained": self.ml_trained,
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
    model = train_signal_quality_model(candles)
    features = extract_features(candles)
    ml_score = model.score(features) if features else 0.5
    body = abs(last.close - last.open)
    candle_range = max(last.high - last.low, 0.00001)
    body_strength = body / candle_range
    trend_strength = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)

    if fast > slow and last.close > last.open and 48 <= momentum <= 72:
        base_confidence = min(0.52 + trend_strength * 0.2 + body_strength * 0.18, 0.86)
        confidence = round((base_confidence * 0.72) + (ml_score * 0.28), 2) if model.trained else round(base_confidence, 2)
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
            reason=signal_reasons(["tendência curta compradora", "momentum saudável", "stop baseado em ATR"], model.trained, ml_score),
            ml_score=ml_score,
            ml_trained=model.trained,
        )

    if fast < slow and last.close < last.open and 28 <= momentum <= 52:
        base_confidence = min(0.52 + trend_strength * 0.2 + body_strength * 0.18, 0.86)
        sell_ml_score = 1 - ml_score if model.trained else ml_score
        confidence = round((base_confidence * 0.72) + (sell_ml_score * 0.28), 2) if model.trained else round(base_confidence, 2)
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
            reason=signal_reasons(["tendência curta vendedora", "momentum saudável", "stop baseado em ATR"], model.trained, sell_ml_score),
            ml_score=sell_ml_score,
            ml_trained=model.trained,
        )

    return Signal(
        symbol,
        timeframe,
        "NO_TRADE",
        0.0,
        None,
        None,
        [],
        signal_reasons(["sem vantagem estatística clara"], model.trained, ml_score),
        ml_score=ml_score,
        ml_trained=model.trained,
    )


def signal_reasons(reasons: list[str], trained: bool, score: float) -> list[str]:
    if not trained:
        return reasons + ["IA aguardando mais dados para treino"]
    return reasons + [f"score ML {round(score * 100)}%"]
