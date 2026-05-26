from __future__ import annotations

import os
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
    lookback: int | None = None,
) -> Signal:
    max_lookback = max(1, min(int(lookback or os.getenv("SIGNAL_LOOKBACK_CANDLES", "4")), len(candles)))
    signal = detect_rule_signal(candles, symbol, timeframe)
    if signal.side == "NO_TRADE" and "dados insuficientes" in signal.reason:
        return signal

    for offset in range(max_lookback):
        window = candles[: len(candles) - offset]
        candidate = detect_rule_signal(window, symbol, timeframe)
        if candidate.side == "NO_TRADE":
            continue
        if offset > 0:
            candidate = Signal(
                symbol=candidate.symbol,
                timeframe=candidate.timeframe,
                side=candidate.side,
                confidence=max(candidate.confidence - (offset * 0.03), 0.0),
                entry=candidate.entry,
                stop_loss=candidate.stop_loss,
                take_profit=candidate.take_profit,
                reason=candidate.reason + [f"setup detectado ha {offset} candle(s)"],
            )
        return apply_ml_score(candidate, window, symbol, timeframe)

    return apply_ml_score(signal, candles, symbol, timeframe)


def apply_ml_score(signal: Signal, candles: list[Candle], symbol: str, timeframe: str) -> Signal:
    model = train_signal_quality_model(candles)
    features = extract_features(candles)
    ml_score = model.score(features) if features else 0.5

    if signal.side == "NO_TRADE":
        return Signal(
            symbol,
            timeframe,
            "NO_TRADE",
            0.0,
            None,
            None,
            [],
            signal_reasons(signal.reason, model.trained, ml_score),
            ml_score=ml_score,
            ml_trained=model.trained,
        )

    side_score = ml_score if signal.side == "BUY" else 1 - ml_score
    confidence = round((signal.confidence * 0.85) + (side_score * 0.15), 2) if model.trained else signal.confidence
    return Signal(
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        side=signal.side,
        confidence=confidence,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        reason=signal_reasons(signal.reason, model.trained, side_score),
        ml_score=side_score,
        ml_trained=model.trained,
    )


def detect_rule_signal(
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
    recent_move = closes[-1] - closes[-4] if len(closes) >= 4 else 0.0
    direction_strength = min(abs(recent_move) / max(volatility, 0.00001), 1.0)

    if trend_strength < 0.08:
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["tendencia fraca ou lateral"])

    if fast > slow and last.close >= fast and recent_move >= -volatility * 0.25 and 43 <= momentum <= 76:
        momentum_score = max(0.0, 1 - abs(momentum - 58) / 24)
        confidence = round(
            min(0.50 + trend_strength * 0.22 + body_strength * 0.12 + direction_strength * 0.08 + momentum_score * 0.1, 0.86),
            2,
        )
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

    if fast < slow and last.close <= fast and recent_move <= volatility * 0.25 and 24 <= momentum <= 57:
        momentum_score = max(0.0, 1 - abs(momentum - 42) / 24)
        confidence = round(
            min(0.50 + trend_strength * 0.22 + body_strength * 0.12 + direction_strength * 0.08 + momentum_score * 0.1, 0.86),
            2,
        )
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


def signal_reasons(reasons: list[str], trained: bool, score: float) -> list[str]:
    if not trained:
        return reasons + ["IA aguardando mais dados para treino"]
    return reasons + [f"score ML {round(score * 100)}%"]
