from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import atr, rsi, sma, bollinger_bands, support_resistance, macd, stoch_rsi, volume_ratio, swing_points, atr_average, ema
from packages.strategy_core.ml_model import extract_features, train_signal_quality_model
from packages.strategy_core.advanced_filters import detect_divergence, candlestick_boost


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

    confluence_count, confluence_reasons = calculate_confluence(candles, signal.side)
    min_conf = min_confluence_required()
    if confluence_count < min_conf:
        return Signal(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            side='NO_TRADE',
            confidence=0.0,
            entry=None,
            stop_loss=None,
            take_profit=[],
            reason=signal_reasons(
                signal.reason + [f'confluencia insuficiente ({confluence_count}/{min_conf})'],
                model.trained,
                side_score,
            ),
            ml_score=side_score,
            ml_trained=model.trained,
            strategy_style=None,
        )

    swing_stop = swing_based_stop(candles, signal.side, atr(candles, 14) or 0.001)
    if swing_stop is not None and signal.stop_loss is not None:
        if signal.side == 'BUY' and swing_stop > signal.stop_loss:
            signal = Signal(
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                side=signal.side,
                confidence=signal.confidence,
                entry=signal.entry,
                stop_loss=swing_stop,
                take_profit=signal.take_profit,
                reason=signal.reason + ['stop ajustado para swing point'],
                ml_score=signal.ml_score,
                ml_trained=signal.ml_trained,
                strategy_style=signal.strategy_style,
            )
        elif signal.side == 'SELL' and swing_stop < signal.stop_loss:
            signal = Signal(
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                side=signal.side,
                confidence=signal.confidence,
                entry=signal.entry,
                stop_loss=swing_stop,
                take_profit=signal.take_profit,
                reason=signal.reason + ['stop ajustado para swing point'],
                ml_score=signal.ml_score,
                ml_trained=signal.ml_trained,
                strategy_style=signal.strategy_style,
            )

    confidence = calibrated_confidence(signal.confidence, side_score, model.trained)

    has_divergence, divergence_reason = detect_divergence(candles, signal.side)
    if has_divergence:
        confidence = min(confidence + 0.05, 0.92)
        confluence_reasons.append(divergence_reason)

    candle_boost, candle_descriptions = candlestick_boost(candles, signal.side)
    if candle_boost > 0:
        confidence = min(confidence + candle_boost, 0.92)
        confluence_reasons.extend(candle_descriptions)

    return Signal(
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        side=signal.side,
        confidence=confidence,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        reason=signal_reasons(signal.reason + confluence_reasons, model.trained, side_score),
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
        session_score = session_alignment_score()
        mtf_score = mtf_alignment_score('BUY', [])
        confidence = quality_confidence(
            trend_strength, body_strength, direction_strength, momentum_score, pullback_score, chase_penalty, session_score, mtf_score
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
        session_score = session_alignment_score()
        mtf_score = mtf_alignment_score('SELL', [])
        confidence = quality_confidence(
            trend_strength, body_strength, direction_strength, momentum_score, pullback_score, chase_penalty, session_score, mtf_score
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
    session_score: float = 0.0,
    mtf_score: float = 0.0,
) -> float:
    score = (
        0.48
        + trend_strength * 0.2
        + body_strength * 0.08
        + direction_strength * 0.08
        + momentum_score * 0.1
        + pullback_score * 0.12
        - chase_penalty
        + session_score
        + mtf_score
    )
    return round(min(max(score, 0.0), 0.88), 2)


def signal_reasons(reasons: list[str], trained: bool, score: float) -> list[str]:
    if not trained:
        return reasons + ['IA aguardando mais dados para treino']
    return reasons + ['score ML ' + str(round(score * 100)) + '%']


def calculate_confluence(candles: list[Candle], side: str) -> tuple[int, list[str]]:
    confluence_count = 0
    reasons = []
    closes = [c.close for c in candles]
    macd_val = macd(closes)
    if macd_val is not None:
        macd_line, signal_line, histogram = macd_val
        if side == 'BUY' and macd_line > signal_line and histogram > 0:
            confluence_count += 1
            reasons.append('MACD bullish')
        elif side == 'SELL' and macd_line < signal_line and histogram < 0:
            confluence_count += 1
            reasons.append('MACD bearish')
    stoch_rsi_val = stoch_rsi(closes)
    if stoch_rsi_val is not None:
        k, d = stoch_rsi_val
        if side == 'BUY' and k > d and k < 80:
            confluence_count += 1
            reasons.append('StochRSI bullish')
        elif side == 'SELL' and k < d and k > 20:
            confluence_count += 1
            reasons.append('StochRSI bearish')
    vol_ratio = volume_ratio(candles)
    if vol_ratio is not None and vol_ratio > 1.2:
        confluence_count += 1
        reasons.append('volume acima da media')
    fast_sma = sma(closes, 5)
    slow_sma = sma(closes, 20)
    if fast_sma is not None and slow_sma is not None:
        if side == 'BUY' and fast_sma > slow_sma:
            confluence_count += 1
            reasons.append('SMA 5 > SMA 20')
        elif side == 'SELL' and fast_sma < slow_sma:
            confluence_count += 1
            reasons.append('SMA 5 < SMA 20')
    return confluence_count, reasons


def min_confluence_required() -> int:
    raw = os.getenv('SIGNAL_MIN_CONFLUENCE', '2')
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def swing_based_stop(candles: list[Candle], side: str, volatility: float) -> float | None:
    swing_high, swing_low, prev_high, prev_low = swing_points(candles, 5)
    if swing_high == 0 and swing_low == 0:
        return None
    if side == 'BUY':
        base_stop = swing_low if swing_low > 0 else prev_low
        if base_stop == 0:
            return None
        return round(min(base_stop - volatility * 0.15, candles[-1].close - volatility * 1.0), 5)
    elif side == 'SELL':
        base_stop = swing_high if swing_high > 0 else prev_high
        if base_stop == 0:
            return None
        return round(max(base_stop + volatility * 0.15, candles[-1].close + volatility * 1.0), 5)
    return None


def adaptive_atr_multiple(candles: list[Candle], period: int = 14, lookback: int = 50) -> float:
    current_atr = atr(candles, period)
    avg_atr = atr_average(candles, period, lookback)
    if current_atr is None or avg_atr is None or avg_atr == 0:
        return max_stop_atr_multiple()
    ratio = current_atr / avg_atr
    if ratio > 1.5:
        return 2.0
    elif ratio < 0.7:
        return 3.2
    return 2.6


def session_alignment_score() -> float:
    from datetime import datetime, timezone
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour < 16:
        return 0.05
    elif 13 <= hour < 21:
        return 0.05
    elif 0 <= hour < 3:
        return 0.03
    return 0.0


def mtf_alignment_score(signal_side: str, reasons: list[str]) -> float:
    confirm_count = sum(1 for r in reasons if f'confirma {signal_side.upper()}' in r.upper())
    if confirm_count >= 2:
        return 0.06
    elif confirm_count == 1:
        return 0.03
    return 0.0


def momentum_confirmation(candles: list[Candle], side: str) -> bool:
    if len(candles) < 5:
        return False
    closes = [c.close for c in candles[-5:]]
    if side == 'BUY':
        return all(closes[i] <= closes[i + 1] for i in range(len(closes) - 1))
    elif side == 'SELL':
        return all(closes[i] >= closes[i + 1] for i in range(len(closes) - 1))
    return False


def time_based_filter() -> tuple[bool, str]:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()
    if weekday == 4 and hour >= 20:
        return False, "sexta fechamento - evitar novas entradas"
    if weekday == 6 and hour < 18:
        return False, "domingo mercado fechado"
    if 7 <= hour < 13:
        return True, "sessao Londres ativa"
    elif 13 <= hour < 21:
        return True, "sessao Nova York ativa"
    elif 0 <= hour < 3:
        return True, "sessao Asia ativa"
    return True, "sessao disponivel"


def trailing_stop_suggestion(entry: float, current_price: float, stop_loss: float, side: str) -> float | None:
    if side == 'BUY':
        if current_price > entry + (entry - stop_loss) * 0.5:
            new_stop = entry + (current_price - entry) * 0.3
            if new_stop > stop_loss:
                return round(new_stop, 5)
    elif side == 'SELL':
        if current_price < entry - (stop_loss - entry) * 0.5:
            new_stop = entry - (entry - current_price) * 0.3
            if new_stop < stop_loss:
                return round(new_stop, 5)
    return None


def volume_confirmation(candles: list[Candle], side: str) -> bool:
    if len(candles) < 5:
        return False
    volumes = [c.volume for c in candles[-5:] if hasattr(c, 'volume') and c.volume > 0]
    if len(volumes) < 3:
        return False
    avg_vol = sum(volumes) / len(volumes)
    last_vol = volumes[-1]
    return last_vol > avg_vol * 1.3


def price_action_quality(candles: list[Candle]) -> float:
    if len(candles) < 3:
        return 0.0
    score = 0.0
    last = candles[-1]
    body = abs(last.close - last.open)
    total_range = max(last.high - last.low, 0.00001)
    body_ratio = body / total_range
    if body_ratio > 0.6:
        score += 0.3
    elif body_ratio > 0.4:
        score += 0.2
    if last.close > last.open:
        upper_wick = last.high - last.close
        lower_wick = last.open - last.low
        if upper_wick < body * 0.3 and lower_wick < body * 0.3:
            score += 0.2
    prev = candles[-2]
    if last.close > last.open and prev.close < prev.open:
        score += 0.1
    elif last.close < last.open and prev.close > prev.open:
        score += 0.1
    return min(score, 1.0)


def market_regime_adjustment(candles: list[Candle]) -> dict[str, float]:
    if len(candles) < 20:
        return {'trend_adjustment': 0.0, 'range_adjustment': 0.0, 'volatility_adjustment': 0.0}
    closes = [c.close for c in candles[-20:]]
    fast = sma(closes, 5)
    slow = sma(closes, 20)
    volatility = atr(candles, 14)
    if fast is None or slow is None or volatility is None:
        return {'trend_adjustment': 0.0, 'range_adjustment': 0.0, 'volatility_adjustment': 0.0}
    trend_strength = min(abs(fast - slow) / max(volatility, 0.00001), 1.0)
    trend_adjustment = 0.0
    range_adjustment = 0.0
    volatility_adjustment = 0.0
    if trend_strength > 0.3:
        trend_adjustment = 0.05
    elif trend_strength < 0.1:
        range_adjustment = 0.03
    current_atr = atr(candles, 14)
    avg_atr = atr_average(candles, 14, 50)
    if current_atr is not None and avg_atr is not None and avg_atr > 0:
        vol_ratio = current_atr / avg_atr
        if vol_ratio > 1.5:
            volatility_adjustment = -0.03
        elif vol_ratio < 0.7:
            volatility_adjustment = 0.02
    return {
        'trend_adjustment': trend_adjustment,
        'range_adjustment': range_adjustment,
        'volatility_adjustment': volatility_adjustment,
    }
