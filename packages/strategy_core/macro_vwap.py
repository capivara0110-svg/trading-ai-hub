from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from packages.strategy_core.data import Candle


VALID_BIASES = {"COMPRADOR", "VENDEDOR", "NEUTRO"}
SESSION_TIMEZONES = {"LONDON": "Europe/London", "NEW_YORK": "America/New_York"}


def detect_macro_vwap_signal(
    candles: list[Candle], symbol: str, timeframe: str, bias: str | None = None
) -> "Signal":
    # Import local evita dependencia circular: Signal pertence ao contrato publico de signals.
    from packages.strategy_core.signals import Signal, StrategyStyle

    if timeframe.upper() != "M5":
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["MACRO_VWAP exige timeframe M5"],
                      strategy_style=StrategyStyle.MACRO_VWAP.value)
    if len(candles) < 23:
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["dados insuficientes para MACRO_VWAP"],
                      strategy_style=StrategyStyle.MACRO_VWAP.value)

    closes = [candle.close for candle in candles[-80:]]
    ema = ema_series(closes, 9)
    if len(ema) < 2:
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["dados insuficientes para EMA 9"],
                      strategy_style=StrategyStyle.MACRO_VWAP.value)
    sma_current = sum(closes[-21:]) / 21
    sma_previous = sum(closes[-22:-1]) / 21
    current_ema, previous_ema = ema[-1], ema[-2]
    cross_up = previous_ema <= sma_previous and current_ema > sma_current
    cross_down = previous_ema >= sma_previous and current_ema < sma_current

    average_volume = sum(max(candle.volume, 0.0) for candle in candles[-22:-2]) / 20
    last_two_volumes = [max(candle.volume, 0.0) for candle in candles[-2:]]
    volume_confirmed = average_volume > 0 and all(volume > average_volume for volume in last_two_volumes)
    if not volume_confirmed:
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["volume dos dois candles abaixo da media de 20"],
                      strategy_style=StrategyStyle.MACRO_VWAP.value)

    vwap = anchored_session_vwap(candles)
    if vwap is None:
        return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [], ["VWAP de sessao indisponivel"],
                      strategy_style=StrategyStyle.MACRO_VWAP.value)

    normalized_bias = normalize_bias(bias)
    last = candles[-1]
    pip = pip_size(symbol)
    stop_pips = positive_env_float("MACRO_VWAP_STOP_PIPS", 12.0)
    target_pips = positive_env_float("MACRO_VWAP_TARGET_PIPS", 24.0)
    volume_ratio = min(min(last_two_volumes) / average_volume, 2.0)
    confidence = round(min(0.76 + (volume_ratio - 1.0) * 0.12, 0.88), 2)
    digits = 3 if "JPY" in symbol.upper() else 5

    if cross_up and last.close > vwap and normalized_bias != "VENDEDOR":
        entry = round(last.close, digits)
        return Signal(
            symbol, timeframe, "BUY", confidence, entry,
            round(entry - stop_pips * pip, digits),
            [round(entry + target_pips * pip, digits)],
            ["MACRO_VWAP: EMA 9 cruzou acima da SMA 21", "preco acima da VWAP da sessao",
             "volume confirmado em dois candles", f"vies diario {normalized_bias.lower()}"],
            strategy_style=StrategyStyle.MACRO_VWAP.value,
        )

    if cross_down and last.close < vwap and normalized_bias != "COMPRADOR":
        entry = round(last.close, digits)
        return Signal(
            symbol, timeframe, "SELL", confidence, entry,
            round(entry + stop_pips * pip, digits),
            [round(entry - target_pips * pip, digits)],
            ["MACRO_VWAP: EMA 9 cruzou abaixo da SMA 21", "preco abaixo da VWAP da sessao",
             "volume confirmado em dois candles", f"vies diario {normalized_bias.lower()}"],
            strategy_style=StrategyStyle.MACRO_VWAP.value,
        )

    return Signal(symbol, timeframe, "NO_TRADE", 0.0, None, None, [],
                  ["sem cruzamento MACRO_VWAP alinhado ao preco e ao vies"],
                  strategy_style=StrategyStyle.MACRO_VWAP.value)


def ema_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    multiplier = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for value in values[period:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


def anchored_session_vwap(candles: list[Candle]) -> float | None:
    latest_time = parse_candle_time(candles[-1].time)
    if latest_time is None:
        return None
    session = os.getenv("MACRO_VWAP_SESSION", "LONDON").strip().upper()
    timezone_name = os.getenv("MACRO_VWAP_SESSION_TIMEZONE", SESSION_TIMEZONES.get(session, "Europe/London"))
    try:
        session_timezone = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        session_timezone = ZoneInfo("Europe/London")
    hour = bounded_env_int("MACRO_VWAP_SESSION_HOUR", 8, 0, 23)
    minute = bounded_env_int("MACRO_VWAP_SESSION_MINUTE", 0, 0, 59)
    local_latest = latest_time.astimezone(session_timezone)
    anchor = local_latest.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_latest < anchor:
        anchor -= timedelta(days=1)

    price_volume = 0.0
    volume_total = 0.0
    for candle in reversed(candles):
        candle_time = parse_candle_time(candle.time)
        if candle_time is None:
            continue
        if candle_time.astimezone(session_timezone) < anchor:
            break
        volume = max(candle.volume, 0.0)
        if volume <= 0:
            continue
        price_volume += ((candle.high + candle.low + candle.close) / 3) * volume
        volume_total += volume
    return price_volume / volume_total if volume_total > 0 else None


def parse_candle_time(raw: str) -> datetime | None:
    value = str(raw).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=ZoneInfo("UTC"))


def normalize_bias(value: str | None) -> str:
    normalized = (value or os.getenv("MACRO_VWAP_DAILY_BIAS", "NEUTRO")).strip().upper()
    return normalized if normalized in VALID_BIASES else "NEUTRO"


def pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol.upper() else 0.0001


def positive_env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)
