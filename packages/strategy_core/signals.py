from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import atr, rsi, sma, bollinger_bands, support_resistance
from packages.strategy_core.ml_model import extract_features, train_signal_quality_model


class StrategyStyle(str, Enum):
    TREND_HUNTER = 'TREND_HUNTER'
    SCALPER = 'SCALPER'
    REVERSAL_PRO = 'REVERSAL_PRO'
    BREAKOUT = 'BREAKOUT'

    def display_name(self) -> str:
        names = {
            'TREND_HUNTER': 'Cacador de Tendencia',
            'SCALPER': 'Scalper Range',
            'REVERSAL_PRO': 'Reversao Extrema',
            'BREAKOUT': 'Rompimento',
        }
        return names.get(self.value, self.value)

    def emoji(self) -> str:
        emojis = {
            'TREND_HUNTER': '~$',
            'SCALPER': '~%',
            'REVERSAL_PRO': '~&',
            'BREAKOUT': '~(',
        }
        return emojis.get(self.value, '~)')


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
    strategy_style: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'side': self.side,
            'confidence': self.confidence,
            'entry': self.entry,
            'stopLoss': self.stop_loss,
            'takeProfit': self.take_profit,
            'reason': self.reason,
            'mlScore': self.ml_score,
            'mlTrained': self.ml_trained,
            'strategyStyle': self.strategy_style,
        }

    def with_adjustment(self, confidence_delta: float, reasons: list[str]) -> 'Signal':
        return Signal(
            symbol=self.symbol,
            timeframe=self.timeframe,
            side=self.side,
            confidence=round(min(max(self.confidence + confidence_delta, 0.0), 0.95), 2),
            entry=self.entry,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            reason=self.reason + reasons,
            ml_score=self.ml_score,
            ml_trained=self.ml_trained,
            strategy_style=self.strategy_style,
        )


def detect_forex_signal(
    candles: list[Candle],
    symbol: str = 'EURUSD',
    timeframe: str = 'M5',
    lookback: int | None = None,
) -> Signal:
    max_lookback = max(1, min(int(lookback or os.getenv('SIGNAL_LOOKBACK_CANDLES', '4')), len(candles)))
    signal = detect_best_strategy(candles, symbol, timeframe)
    if signal.side == 'NO_TRADE' and 'dados insuficientes' in signal.reason:
        return signal

    for offset in range(max_lookback):
        window = candles[: len(candles) - offset]
        candidate = detect_best_strategy(window, symbol, timeframe)
        if candidate.side == 'NO_TRADE':
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
                reason=candidate.reason + ['setup detectado ha ' + str(offset) + ' candle(s)'],
                strategy_style=candidate.strategy_style,
            )
        return apply_ml_score(candidate, window, symbol, timeframe)

    return apply_ml_score(signal, candles, symbol, timeframe)


def apply_ml_score(signal: Signal, candles: list[Candle], symbol: str, timeframe: str) -> Signal:
    model = train_signal_quality_model(candles)
    features = extract_features(candles)
    ml_score = model.score(features) if features else 0.5

    if signal.side == 'NO_TRADE':
        return Signal(
            symbol,
            timeframe,
            'NO_TRADE',
            0.0,
            None,
            None,
            [],
            signal_reasons(signal.reason, model.trained, ml_score),
            ml_score=ml_score,
            ml_trained=model.trained,
            strategy_style=None,
        )

    side_score = ml_score if signal.side == 'BUY' else 1 - ml_score
    if model.trained and side_score < min_signal_ml_score():
        return Signal(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            side='NO_TRADE',
            confidence=0.0,
            entry=None,
            stop_loss=None,
            take_profit=[],
            reason=signal_reasons(
                signal.reason + ['score ML abaixo do minimo operacional'],
                model.trained,
                side_score,
            ),
            ml_score=side_score,
            ml_trained=model.trained,
            strategy_style=None,
        )

    confidence = calibrated_confidence(signal.confidence, side_score, model.trained)
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
        strategy_style=signal.strategy_style,
    )


def detect_best_strategy(
    candles: list[Candle],
    symbol: str = 'EURUSD',
    timeframe: str = 'M5',
) -> Signal:
    '''''Detecta qual estrategia usar baseado nas condicoes atuais do mercado.'''''
    # The longest technical lookback below is 20 candles. A bounded buffer
    # preserves the signal while avoiding quadratic work in long backtests.
    candles = candles[-64:]
    closes = [candle.close for candle in candles]
    fast = sma(closes, 5)
    slow = sma(closes, 20)
    volatility = atr(candles, 14)
    momentum = rsi(closes, 14)
    upper_bb, lower_bb = bollinger_bands(closes, 20, 2.0)
    sup, res = support_resistance(candles, 12)

    if fast is None or slow is None or volatility is None or momentum is None:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['dados insuficientes'])

    trend_strength = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)
    last = candles[-1]
    body = abs(last.close - last.open)
    candle_range = max(last.high - last.low, 0.00001)
    body_strength = body / candle_range
    recent_move = closes[-1] - closes[-4] if len(closes) >= 4 else 0.0
    direction_strength = min(abs(recent_move) / max(volatility, 0.00001), 1.0)

    # Detect market environment
    is_strong_trend = trend_strength > 0.20
    is_range_market = trend_strength < 0.10
    is_oversold = momentum is not None and momentum < 30
    is_overbought = momentum is not None and momentum > 70
    is_breakout = detect_breakout_condition(candles, volatility)
    momentum_extreme = momentum is not None and (momentum < 28 or momentum > 72)

    # 1. Try BREAKOUT first (most profitable when happens)
    if is_breakout and is_strong_trend:
        signal = detect_breakout_signal(candles, symbol, timeframe, volatility, sup, res)
        if signal.side != 'NO_TRADE':
            return signal

    # 2. Try REVERSAL when momentum extreme
    if momentum_extreme and not is_strong_trend:
        signal = detect_reversal_signal(candles, symbol, timeframe, volatility, momentum, sup, res)
        if signal.side != 'NO_TRADE':
            return signal

    # 3. Try TREND HUNTER (original strategy)
    signal = detect_trend_hunter(candles, symbol, timeframe, fast, slow, volatility, momentum, body_strength, direction_strength, recent_move)
    if signal.side != 'NO_TRADE':
        return signal

    # 4. Try SCALPER if range market
    if is_range_market:
        signal = detect_scalper_signal(candles, symbol, timeframe, volatility, momentum, sup, res, upper_bb, lower_bb)
        if signal.side != 'NO_TRADE':
            return signal

    return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['sem vantagem estatistica clara'])


def detect_breakout_condition(candles: list[Candle], volatility: float | None = None) -> bool:
    '''''Detecta se houve um rompimento recente.'''''
    if len(candles) < 10:
        return False
    recent_highs = [c.high for c in candles[-10:-2]]
    recent_lows = [c.low for c in candles[-10:-2]]
    current = candles[-1]
    prev = candles[-2]

    avg_range = sum(max(c.high - c.low, 0.00001) for c in candles[-10:]) / 10
    current_range = max(current.high - current.low, 0.00001)
    range_ratio = current_range / avg_range if avg_range > 0 else 0

    bullish_breakout = current.close > max(recent_highs) and current.high > max(recent_highs) and range_ratio > 1.3
    bearish_breakout = current.close < min(recent_lows) and current.low < min(recent_lows) and range_ratio > 1.3

    return bullish_breakout or bearish_breakout


def detect_trend_hunter(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    fast: float,
    slow: float,
    volatility: float,
    momentum: float,
    body_strength: float,
    direction_strength: float,
    recent_move: float,
) -> Signal:
    '''''ESTILO 1: Cacador de Tendencia - Estrategia original melhorada.'''''
    last = candles[-1]
    closes = [c.close for c in candles]
    trend_strength = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)

    if trend_strength < 0.12:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['tendencia fraca para trend hunter'])

    distance_from_fast = abs(last.close - fast) / max(volatility, 0.00001)
    pullback_score = max(0.0, 1 - min(distance_from_fast, 1.4) / 1.4)
    chase_penalty = min(max(distance_from_fast - 1.2, 0.0) * 0.08, 0.12)
    recent_low = min(candle.low for candle in candles[-8:])
    recent_high = max(candle.high for candle in candles[-8:])

    if fast > slow and last.close >= fast and recent_move >= -volatility * 0.25 and 40 <= momentum <= 78:
        momentum_score = max(0.0, 1 - abs(momentum - 58) / 24)
        confidence = quality_confidence(
            trend_strength, body_strength, direction_strength, momentum_score, pullback_score, chase_penalty
        )
        confidence = min(confidence + 0.05, 0.90)
        stop = round(min(last.close - volatility * 1.3, recent_low - volatility * 0.15), 5)
        risk = last.close - stop
        if risk / max(volatility, 0.00001) > max_stop_atr_multiple():
            return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['stop ATR acima do limite operacional'])
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side='BUY',
            confidence=confidence,
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close + risk * 1.8, 5), round(last.close + risk * 2.8, 5)],
            reason=['tendencia curta compradora', 'momentum saudavel', 'stop ATR x' + str(round(risk/volatility, 1))],
            strategy_style=StrategyStyle.TREND_HUNTER.value,
        )

    if fast < slow and last.close <= fast and recent_move <= volatility * 0.25 and 22 <= momentum <= 60:
        momentum_score = max(0.0, 1 - abs(momentum - 42) / 24)
        confidence = quality_confidence(
            trend_strength, body_strength, direction_strength, momentum_score, pullback_score, chase_penalty
        )
        confidence = min(confidence + 0.05, 0.90)
        stop = round(max(last.close + volatility * 1.3, recent_high + volatility * 0.15), 5)
        risk = stop - last.close
        if risk / max(volatility, 0.00001) > max_stop_atr_multiple():
            return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['stop ATR acima do limite operacional'])
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side='SELL',
            confidence=confidence,
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close - risk * 1.8, 5), round(last.close - risk * 2.8, 5)],
            reason=['tendencia curta vendedora', 'momentum saudavel', 'stop ATR x' + str(round(risk/volatility, 1))],
            strategy_style=StrategyStyle.TREND_HUNTER.value,
        )

    return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['sem entrada trend hunter'])


def detect_reversal_signal(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    volatility: float,
    momentum: float,
    support: float | None,
    resistance: float | None,
) -> Signal:
    '''''ESTILO 2: Reversao Extrema - Opera quando mercado esta exagerado.'''''
    last = candles[-1]
    closes = [c.close for c in candles]
    fast = sma(closes, 5)
    slow = sma(closes, 20)

    if fast is None or slow is None:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['dados insuficientes para reversao'])

    trend_strength = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)

    if trend_strength > 0.30:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['tendencia forte demais para reversao'])

    body = abs(last.close - last.open)
    total_range = max(last.high - last.low, 0.00001)
    upper_shadow = last.high - max(last.close, last.open)
    lower_shadow = min(last.close, last.open) - last.low
    exhaustion = (upper_shadow / total_range > 0.6) or (lower_shadow / total_range > 0.6)

    recent_low = min(c.low for c in candles[-8:])
    recent_high = max(c.high for c in candles[-8:])

    # REVERSAL BAIXA (overbought)
    if momentum > 72 and last.close >= fast and (exhaustion or (resistance and last.close > resistance)):
        confidence = min(0.60 + ((momentum - 70) / 60) * 0.20, 0.78)
        if exhaustion:
            confidence = min(confidence + 0.08, 0.80)
        stop = round(max(last.close + volatility * 0.8, recent_high + volatility * 0.1), 5)
        risk = stop - last.close
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side='SELL',
            confidence=round(confidence, 2),
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close - risk * 1.5, 5), round(last.close - risk * 2.2, 5)],
            reason=['sobrecompra extrema', 'exaustao de compradores', 'reversao probabilistica'],
            strategy_style=StrategyStyle.REVERSAL_PRO.value,
        )

    # REVERSAL ALTA (oversold)
    if momentum < 28 and last.close <= fast and (exhaustion or (support and last.close < support)):
        confidence = min(0.60 + ((28 - momentum) / 28) * 0.20, 0.78)
        if exhaustion:
            confidence = min(confidence + 0.08, 0.80)
        stop = round(min(last.close - volatility * 0.8, recent_low - volatility * 0.1), 5)
        risk = last.close - stop
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side='BUY',
            confidence=round(confidence, 2),
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close + risk * 1.5, 5), round(last.close + risk * 2.2, 5)],
            reason=['sobrevenda extrema', 'exaustao de vendedores', 'reversao probabilistica'],
            strategy_style=StrategyStyle.REVERSAL_PRO.value,
        )

    return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['sem reversao viavel'])


def detect_scalper_signal(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    volatility: float,
    momentum: float,
    support: float | None,
    resistance: float | None,
    upper_bb: float | None,
    lower_bb: float | None,
) -> Signal:
    '''''ESTILO 3: Scalper Range - Opera dentro do range em mercado lateral.'''''
    if len(candles) < 10:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['dados insuficientes para scalper'])

    last = candles[-1]
    closes = [c.close for c in candles]
    fast = sma(closes, 5)
    slow = sma(closes, 20)

    if fast is None or slow is None:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['dados insuficientes'])
    trend_strength = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)

    if trend_strength > 0.15:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['tendencia forte demais para scalper'])

    # Bollinger position
    if upper_bb is not None and lower_bb is not None:
        bb_width = upper_bb - lower_bb
        bb_position = (last.close - lower_bb) / bb_width if bb_width > 0 else 0.5
    else:
        bb_position = 0.5

    # Range position
    if support is not None and resistance is not None:
        range_height = max(resistance - support, 0.00001)
        range_position = (last.close - support) / range_height
    else:
        range_position = 0.5

    # ENTRADA COMPRA (na banda inferior / suporte)
    if (bb_position < 0.25 or range_position < 0.25) and 35 <= momentum <= 55:
        confidence = min(0.55 + (0.25 - min(bb_position, range_position)) * 0.5, 0.72)
        body = abs(last.close - last.open)
        total_range = max(last.high - last.low, 0.00001)
        lower_shadow = min(last.close, last.open) - last.low
        if lower_shadow / total_range > 0.5:
            confidence = min(confidence + 0.08, 0.75)

        stop = round(last.close - volatility * 0.6, 5)
        risk = last.close - stop
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side='BUY',
            confidence=round(confidence, 2),
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close + risk * 1.2, 5), round(last.close + risk * 2.0, 5)],
            reason=['suporte do range', 'banda inferior bollinger', 'scalp em mercado lateral'],
            strategy_style=StrategyStyle.SCALPER.value,
        )

    # ENTRADA VENDA (na banda superior / resistencia)
    if (bb_position > 0.75 or range_position > 0.75) and 45 <= momentum <= 65:
        confidence = min(0.55 + (min(bb_position, range_position) - 0.75) * 0.5, 0.72)
        body = abs(last.close - last.open)
        total_range = max(last.high - last.low, 0.00001)
        upper_shadow = last.high - max(last.close, last.open)
        if upper_shadow / total_range > 0.5:
            confidence = min(confidence + 0.08, 0.75)
        stop = round(last.close + volatility * 0.6, 5)
        risk = stop - last.close
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side='SELL',
            confidence=round(confidence, 2),
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close - risk * 1.2, 5), round(last.close - risk * 2.0, 5)],
            reason=['resistencia do range', 'banda superior bollinger', 'scalp em mercado lateral'],
            strategy_style=StrategyStyle.SCALPER.value,
        )

    return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['sem entrada scalper viavel'])


def detect_breakout_signal(
    candles: list[Candle],
    symbol: str,
    timeframe: str,
    volatility: float,
    support: float | None,
    resistance: float | None,
) -> Signal:
    '''''ESTILO 4: Breakout - Opera rompimentos de suporte/resistencia.'''''
    if len(candles) < 12:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['dados insuficientes para breakout'])

    last = candles[-1]
    closes = [c.close for c in candles]
    fast = sma(closes, 5)
    slow = sma(closes, 20)

    if fast is None or slow is None:
        return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['dados insuficientes'])

    lookback = candles[-12:-1]
    recent_high = max(c.high for c in lookback)
    recent_low = min(c.low for c in lookback)

    avg_range = sum(max(c.high - c.low, 0.00001) for c in lookback) / len(lookback)
    current_range = max(last.high - last.low, 0.00001)
    range_ratio = current_range / avg_range if avg_range > 0 else 0

    # Breakout de alta
    if last.close > recent_high and last.high > recent_high and range_ratio > 1.2 and fast > slow:
        trend_str = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)
        confidence = min(0.55 + (range_ratio - 1.0) * 0.15 + trend_str * 0.10, 0.82)
        stop = round(min(last.close - volatility * 0.9, recent_high - volatility * 0.2), 5)
        risk = last.close - stop
        target_distance = risk * 2.0
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side='BUY',
            confidence=round(confidence, 2),
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close + target_distance, 5), round(last.close + target_distance * 1.5, 5)],
            reason=['rompimento de resistencia', 'expansao de range x' + str(round(range_ratio, 1)), 'breakout com volume'],
            strategy_style=StrategyStyle.BREAKOUT.value,
        )

    # Breakout de baixa
    if last.close < recent_low and last.low < recent_low and range_ratio > 1.2 and fast < slow:
        trend_str = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)
        confidence = min(0.55 + (range_ratio - 1.0) * 0.15 + trend_str * 0.10, 0.82)
        stop = round(max(last.close + volatility * 0.9, recent_low + volatility * 0.2), 5)
        risk = stop - last.close
        target_distance = risk * 2.0
        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            side='SELL',
            confidence=round(confidence, 2),
            entry=round(last.close, 5),
            stop_loss=stop,
            take_profit=[round(last.close - target_distance, 5), round(last.close - target_distance * 1.5, 5)],
            reason=['rompimento de suporte', 'expansao de range x' + str(round(range_ratio, 1)), 'breakout com volume'],
            strategy_style=StrategyStyle.BREAKOUT.value,
        )

    return Signal(symbol, timeframe, 'NO_TRADE', 0.0, None, None, [], ['sem breakout viavel'])


def risk_reward_ratio(entry: float, stop: float, target: float, side: str) -> float:
    if side == "BUY":
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target
    if risk <= 0 or reward <= 0:
        return 0.0
    return reward / risk


def min_signal_risk_reward() -> float:
    raw = os.getenv("SIGNAL_MIN_RISK_REWARD", "1.35")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 1.35


def min_signal_ml_score() -> float:
    raw = os.getenv("SIGNAL_MIN_ML_SCORE", "0.55")
    try:
        return min(max(float(raw), 0.0), 0.95)
    except ValueError:
        return 0.55


def max_stop_atr_multiple() -> float:
    raw = os.getenv("SIGNAL_MAX_STOP_ATR_MULTIPLE", "2.6")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 2.6


def calibrated_confidence(rule_confidence: float, ml_score: float, trained: bool) -> float:
    if not trained:
        return min(rule_confidence, 0.72)

    blended = (rule_confidence * 0.55) + (ml_score * 0.45)
    if ml_score < 0.60:
        blended = min(blended, 0.78)
    elif ml_score < 0.65:
        blended = min(blended, 0.84)
    else:
        blended = min(blended, 0.92)
    return round(max(blended, 0.0), 2)


def quality_confidence(
    trend_strength: float,
    body_strength: float,
    direction_strength: float,
    momentum_score: float,
    pullback_score: float,
    chase_penalty: float,
) -> float:
    score = (
        0.48
        + trend_strength * 0.2
        + body_strength * 0.08
        + direction_strength * 0.08
        + momentum_score * 0.1
        + pullback_score * 0.12
        - chase_penalty
    )
    return round(min(max(score, 0.0), 0.88), 2)


def signal_reasons(reasons: list[str], trained: bool, score: float) -> list[str]:
    if not trained:
        return reasons + ['IA aguardando mais dados para treino']
    return reasons + ['score ML ' + str(round(score * 100)) + '%']
