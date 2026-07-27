"""
V1 Enhanced - mesmas entradas, saidas inteligentes, mais sinais.

Melhorias:
1. Trailing stop apos TP1 parcial
2. Take Profit parcial (50% no TP1, resto corre com trailing)
3. Stop baseado em swing points
4. Novo estilo: Momentum Continuation (entradas extras)
5. Time-based exit para trades estagnados
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from packages.strategy_core.data import Candle
from packages.strategy_core.signals import Signal, StrategyStyle, detect_forex_signal
from packages.strategy_core.indicators import atr, sma, rsi, ema, swing_points, bollinger_bands
from packages.strategy_core.backtest import BacktestCosts, BacktestResult, Trade, price_to_pips, calculate_drawdown


def detect_forex_signal_enhanced(
    candles: list[Candle],
    symbol: str = "EURUSD",
    timeframe: str = "M5",
    lookback: int | None = None,
) -> Signal:
    """Same as original but adds Momentum Continuation entries."""
    signal = detect_forex_signal(candles, symbol, timeframe, lookback)
    if signal.side != "NO_TRADE":
        return signal

    if len(candles) < 30:
        return signal

    return _detect_momentum_continuation(candles, symbol, timeframe)


def _detect_momentum_continuation(candles: list[Candle], symbol: str, timeframe: str) -> Signal:
    """Enter on pullback to SMA in a strong trending market."""
    closes = [c.close for c in candles]
    fast = sma(closes, 10)
    slow = sma(closes, 30)
    vol = atr(candles, 14)
    mom = rsi(closes, 14)

    if fast is None or slow is None or vol is None or mom is None:
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["dados insuficientes"])

    trend_strength = abs(fast - slow) / max(vol, 0.00001)
    if trend_strength < 0.15:
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["tendencia fraca"])

    last = candles[-1]
    dist_from_fast = abs(last.close - fast) / max(vol, 0.00001)

    # Pullback to SMA in uptrend - requires volume confirmation
    vol_ok = _volume_above_average(candles)
    if fast > slow and 45 <= mom <= 60 and last.close <= fast + vol * 0.2 and last.close >= fast - vol * 0.4 and vol_ok:
        swing_low, _ = _recent_swing_levels(candles)
        stop = min(last.close - vol * 1.0, swing_low - vol * 0.1) if swing_low else last.close - vol * 1.2
        risk = last.close - stop
        if risk <= 0:
            return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["risco invalido"])
        confidence = round(min(0.62 + trend_strength * 0.10, 0.78), 2)
        return Signal(
            symbol, timeframe, "BUY", confidence,
            round(last.close, 5), stop,
            [round(last.close + risk * 1.6, 5), round(last.close + risk * 2.6, 5)],
            ["pullback para SMA10 em tendencia de alta", "momentum continuation"],
            strategy_style=StrategyStyle.TREND_HUNTER.value,
        )

    # Pullback to SMA in downtrend - requires volume confirmation
    if fast < slow and 40 <= mom <= 55 and last.close >= fast - vol * 0.2 and last.close <= fast + vol * 0.4 and vol_ok:
        _, swing_high = _recent_swing_levels(candles)
        stop = max(last.close + vol * 1.0, swing_high + vol * 0.1) if swing_high else last.close + vol * 1.2
        risk = stop - last.close
        if risk <= 0:
            return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["risco invalido"])
        confidence = round(min(0.62 + trend_strength * 0.10, 0.78), 2)
        return Signal(
            symbol, timeframe, "SELL", confidence,
            round(last.close, 5), stop,
            [round(last.close - risk * 1.6, 5), round(last.close - risk * 2.6, 5)],
            ["pullback para SMA10 em tendencia de baixa", "momentum continuation"],
            strategy_style=StrategyStyle.TREND_HUNTER.value,
        )

    return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["sem pullback viavel"])


def _recent_swing_levels(candles: list[Candle]) -> tuple[float, float]:
    if len(candles) < 10:
        return 0.0, 0.0
    recent = candles[-10:]
    return min(c.low for c in recent), max(c.high for c in recent)


def _volume_above_average(candles: list[Candle]) -> bool:
    if len(candles) < 5:
        return True  # Don't block on insufficient data
    volumes = [c.volume for c in candles[-5:] if c.volume > 0]
    if len(volumes) < 3:
        return True
    return volumes[-1] > sum(volumes[:-1]) / max(len(volumes[:-1]), 1)


def run_backtest_enhanced(
    candles: list[Candle],
    lookahead: int = 24,
    min_confidence: float = 0.50,
    costs: BacktestCosts | None = None,
    symbol: str = "EURUSD",
    timeframe: str = "M5",
) -> BacktestResult:
    """Enhanced backtest with trailing stop, partial TP, smart exits, and drawdown protection."""
    trades: list[Trade] = []
    costs = costs or BacktestCosts()
    consecutive_losses = 0
    max_consecutive_skip = 3  # Skip 1 trade after 3 consecutive losses

    for index in range(20, len(candles) - lookahead):
        window = candles[: index + 1]

        # Drawdown protection: skip after consecutive losses
        if consecutive_losses >= max_consecutive_skip:
            consecutive_losses = 0
            continue

        # Volatility spike filter: skip if ATR is 2x normal
        if _is_volatility_spike(window):
            continue

        signal = detect_forex_signal_enhanced(window, symbol=symbol, timeframe=timeframe)

        if signal.side == "NO_TRADE" or signal.confidence < min_confidence:
            continue
        if signal.entry is None or signal.stop_loss is None or not signal.take_profit:
            continue

        entry = float(signal.entry)
        stop = float(signal.stop_loss)
        tp1 = float(signal.take_profit[0])
        tp2 = float(signal.take_profit[1]) if len(signal.take_profit) > 1 else tp1 * 1.4
        risk = abs(entry - stop)

        # Refine stop using swing points if better
        refined_stop = _refine_stop_with_swings(window, signal.side, stop)
        if refined_stop is not None:
            if signal.side == "BUY" and refined_stop > stop:
                stop = refined_stop
                risk = abs(entry - stop)
            elif signal.side == "SELL" and refined_stop < stop:
                stop = refined_stop
                risk = abs(entry - stop)

        future = candles[index + 1 : index + 1 + lookahead]

        # Enhanced exit logic with more aggressive trailing
        result_pips, exit_price, exit_time = _simulate_enhanced_exit(
            future, signal.side, entry, stop, tp1, tp2, risk, costs
        )
        result_pips = round(result_pips - costs.round_trip_pips, 1)

        # Track consecutive losses
        if result_pips < 0:
            consecutive_losses += 1
        else:
            consecutive_losses = 0

        trades.append(Trade(
            entry_time=candles[index].time,
            side=signal.side,
            entry=round(entry, 5),
            exit=round(exit_price, 5),
            result_pips=result_pips,
            gross_result_pips=round(result_pips + costs.round_trip_pips, 1),
            cost_pips=costs.round_trip_pips,
            exit_time=exit_time,
        ))

    total = sum(trade.result_pips for trade in trades)
    wins = [t for t in trades if t.result_pips > 0]
    losses = [t for t in trades if t.result_pips < 0]
    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = sum(t.result_pips for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t.result_pips for t in losses) / len(losses)) if losses else 0
    gross_profit = sum(t.result_pips for t in wins)
    gross_loss = abs(sum(t.result_pips for t in losses))

    return BacktestResult(
        trades=trades,
        total_pips=total,
        win_rate=win_rate,
        max_drawdown_pips=calculate_drawdown(trades),
        average_win_pips=avg_win,
        average_loss_pips=avg_loss,
        payoff=avg_win / avg_loss if avg_loss else 0,
        profit_factor=gross_profit / gross_loss if gross_loss else 0,
        total_cost_pips=sum(t.cost_pips for t in trades),
    )


def _simulate_enhanced_exit(
    future: list[Candle],
    side: str,
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    risk: float,
    costs: BacktestCosts,
) -> tuple[float, float, str | None]:
    """
    Enhanced exit simulation:
    1. 50% at TP1, move remaining SL to breakeven
    2. Trail remaining at 0.5R behind best price
    3. Close remaining at TP2 or trailing stop
    """
    partial_closed = False
    be_activated = False
    trailing_stop = stop
    best_price = entry
    exit_price = entry
    exit_time = None

    for candle in future:
        if side == "BUY":
            best_price = max(best_price, candle.high)

            # Check TP1 hit
            if not partial_closed and candle.high >= tp1:
                partial_closed = True
                be_activated = True
                trailing_stop = entry  # Move to breakeven
                continue  # Continue with remaining position

            # After TP1, trail stop (more aggressive: 0.4R instead of 0.6R)
            if be_activated:
                trail_distance = risk * 0.4
                new_trail = best_price - trail_distance
                trailing_stop = max(trailing_stop, new_trail) if new_trail > trailing_stop else trailing_stop

            # Check trailing stop hit
            if candle.low <= trailing_stop:
                exit_price = trailing_stop
                exit_time = candle.time
                break

            # Check TP2 hit (remaining)
            if partial_closed and candle.high >= tp2:
                exit_price = tp2
                exit_time = candle.time
                break

            # Check original stop (before TP1)
            if not be_activated and candle.low <= stop:
                exit_price = stop
                exit_time = candle.time
                break

        else:  # SELL
            best_price = min(best_price, candle.low)

            if not partial_closed and candle.low <= tp1:
                partial_closed = True
                be_activated = True
                trailing_stop = entry
                continue

            if be_activated:
                trail_distance = risk * 0.4
                new_trail = best_price + trail_distance
                trailing_stop = min(trailing_stop, new_trail) if new_trail < trailing_stop else trailing_stop

            if candle.high >= trailing_stop:
                exit_price = trailing_stop
                exit_time = candle.time
                break

            if partial_closed and candle.low <= tp2:
                exit_price = tp2
                exit_time = candle.time
                break

            if not be_activated and candle.high >= stop:
                exit_price = stop
                exit_time = candle.time
                break

    # No exit triggered - close at last price
    if exit_time is None and future:
        exit_price = future[-1].close
        exit_time = future[-1].time

    if partial_closed:
        # Weighted result: 50% at TP1, 50% at exit_price
        raw = (tp1 - entry) * 0.5 + (exit_price - entry) * 0.5
    else:
        raw = exit_price - entry

    result_pips = raw * (100 if "JPY" in "EURUSD" else 10000)
    if side == "SELL":
        result_pips *= -1

    return result_pips, exit_price, exit_time


def _is_volatility_spike(candles: list[Candle]) -> bool:
    """Skip entries when ATR spikes 2x above normal (news events)."""
    if len(candles) < 30:
        return False
    current_atr = atr(candles, 14)
    if current_atr is None:
        return False
    avg_range = sum(max(c.high - c.low, 0.00001) for c in candles[-20:-1]) / 19
    if avg_range <= 0:
        return False
    return current_atr > avg_range * 2.0


def _refine_stop_with_swings(candles: list[Candle], side: str, current_stop: float) -> float | None:
    """Use swing points to tighten stop if they provide a better level."""
    if len(candles) < 15:
        return None
    recent = candles[-15:-1]
    if side == "BUY":
        swing_low = min(c.low for c in recent[-5:])
        # Only tighten if swing low is above current stop (tighter)
        if swing_low > current_stop:
            return swing_low
    else:  # SELL
        swing_high = max(c.high for c in recent[-5:])
        if swing_high < current_stop:
            return swing_high
    return None
