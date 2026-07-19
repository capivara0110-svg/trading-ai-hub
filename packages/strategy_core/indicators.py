from __future__ import annotations

from packages.strategy_core.data import Candle


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def atr(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None

    true_ranges: list[float] = []
    for index in range(1, len(candles)):
        candle = candles[index]
        previous = candles[index - 1]
        true_ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous.close),
                abs(candle.low - previous.close),
            )
        )

    return sum(true_ranges[-period:]) / period




def bollinger_bands(values: list[float], period: int = 20, std_mult: float = 2.0) -> tuple[float | None, float | None]:
    """Retorna (upper_band, lower_band) para as Bandas de Bollinger."""
    if len(values) < period:
        return None, None
    avg = sum(values[-period:]) / period
    variance = sum((v - avg)**2 for v in values[-period:]) / period
    std = variance**0.5
    upper = avg + std * std_mult
    lower = avg - std * std_mult
    return upper, lower


def support_resistance(candles: list[Candle], period: int = 12) -> tuple[float | None, float | None]:
    """Retorna (support, resistance) baseado em minimos e maximos recentes."""
    if len(candles) < period:
        return None, None
    window = candles[-period:]
    resistance = max(c.high for c in window)
    support = min(c.low for c in window)
    return support, resistance

def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None

    gains = 0.0
    losses = 0.0
    for index in range(len(values) - period, len(values)):
        change = values[index] - values[index - 1]
        if change >= 0:
            gains += change
        else:
            losses += abs(change)

    if losses == 0:
        return 100.0

    relative_strength = gains / losses
    return 100 - (100 / (1 + relative_strength))


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def macd(values: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> tuple[float, float, float] | None:
    if len(values) < slow + signal_period:
        return None
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    if fast_ema is None or slow_ema is None:
        return None
    macd_line = fast_ema - slow_ema
    macd_values = []
    temp = values[:slow]
    temp_fast_ema = sum(temp[:fast]) / fast
    temp_slow_ema = sum(temp) / slow
    temp_macd = temp_fast_ema - temp_slow_ema
    macd_values.append(temp_macd)
    multiplier = 2 / (fast + 1)
    slow_multiplier = 2 / (slow + 1)
    for i in range(slow, len(values)):
        temp_fast_ema = (values[i] - temp_fast_ema) * multiplier + temp_fast_ema
        temp_slow_ema = (values[i] - temp_slow_ema) * slow_multiplier + temp_slow_ema
        macd_values.append(temp_fast_ema - temp_slow_ema)
    if len(macd_values) < signal_period:
        return None
    signal_ema = ema(macd_values, signal_period)
    if signal_ema is None:
        return None
    histogram = macd_values[-1] - signal_ema
    return macd_values[-1], signal_ema, histogram


def stoch_rsi(values: list[float], rsi_period: int = 14, stoch_period: int = 14, k_smooth: int = 3, d_smooth: int = 3) -> tuple[float, float] | None:
    if len(values) < rsi_period + stoch_period:
        return None
    rsi_values = []
    for i in range(len(values) - stoch_period - 1, len(values)):
        rsi_val = rsi(values[:i + 1], rsi_period)
        if rsi_val is not None:
            rsi_values.append(rsi_val)
    if len(rsi_values) < stoch_period:
        return None
    stoch_k_values = []
    for i in range(len(rsi_values) - stoch_period + 1):
        window = rsi_values[i:i + stoch_period]
        min_rsi = min(window)
        max_rsi = max(window)
        if max_rsi - min_rsi == 0:
            stoch_k_values.append(50.0)
        else:
            stoch_k_values.append(((rsi_values[i + stoch_period - 1] - min_rsi) / (max_rsi - min_rsi)) * 100)
    if len(stoch_k_values) < k_smooth:
        k = sum(stoch_k_values) / len(stoch_k_values)
        d = k
    else:
        k = sum(stoch_k_values[-k_smooth:]) / k_smooth
        d = sum(stoch_k_values[-d_smooth:]) / d_smooth
    return k, d


def volume_ratio(candles: list[Candle], period: int = 20) -> float | None:
    if len(candles) < period + 1:
        return None
    volumes = [c.volume for c in candles if hasattr(c, 'volume') and c.volume > 0]
    if len(volumes) < period:
        return None
    avg_volume = sum(volumes[-period:]) / period
    if avg_volume == 0:
        return None
    return volumes[-1] / avg_volume


def swing_points(candles: list[Candle], lookback: int = 5) -> tuple[float, float, float, float]:
    if len(candles) < lookback * 2 + 1:
        return 0, 0, 0, 0
    recent_highs = [c.high for c in candles[-(lookback * 2 + 1):]]
    recent_lows = [c.low for c in candles[-(lookback * 2 + 1):]]
    current = candles[-1]
    swing_high = max(recent_highs[:-1]) if len(recent_highs) > 1 else recent_highs[0]
    swing_low = min(recent_lows[:-1]) if len(recent_lows) > 1 else recent_lows[0]
    prev_high = max(recent_highs[-(lookback + 1):-1]) if len(recent_highs) > lookback + 1 else swing_high
    prev_low = min(recent_lows[-(lookback + 1):-1]) if len(recent_lows) > lookback + 1 else swing_low
    return swing_high, swing_low, prev_high, prev_low


def atr_average(candles: list[Candle], period: int = 14, lookback: int = 50) -> float | None:
    if len(candles) < period + lookback:
        return None
    atr_values = []
    for i in range(len(candles) - lookback, len(candles)):
        atr_val = atr(candles[:i + 1], period)
        if atr_val is not None:
            atr_values.append(atr_val)
    if not atr_values:
        return None
    return sum(atr_values) / len(atr_values)


def price_distance_from_sma(values: list[float], period: int) -> float | None:
    sma_val = sma(values, period)
    if sma_val is None or len(values) == 0:
        return None
    return abs(values[-1] - sma_val) / max(sma_val, 0.00001)

