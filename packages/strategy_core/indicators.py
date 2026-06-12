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

