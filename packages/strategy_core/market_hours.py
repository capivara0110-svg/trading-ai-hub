from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.strategy_core.data import Candle


MARKET_TZ = None


def forex_market_status(candles: list[Candle] | None = None, now: datetime | None = None) -> dict[str, object]:
    market_tz = get_market_timezone()
    current = (now or datetime.now(market_tz)).astimezone(market_tz)
    close_hour = int(os.getenv("FOREX_FRIDAY_CLOSE_HOUR", "18"))
    open_hour = int(os.getenv("FOREX_SUNDAY_OPEN_HOUR", "18"))
    is_open = is_forex_open(current, close_hour, open_hour)
    next_open = find_next_transition(current, target_open=True, close_hour=close_hour, open_hour=open_hour)
    next_close = find_next_transition(current, target_open=False, close_hour=close_hour, open_hour=open_hour)
    last_candle = candles[-1] if candles else None

    return {
        "market": "FOREX",
        "timezone": str(market_tz),
        "isOpen": is_open,
        "reason": "Mercado Forex aberto." if is_open else "Mercado Forex fechado no fim de semana.",
        "now": current.isoformat(timespec="seconds"),
        "nextOpen": next_open.isoformat(timespec="seconds") if next_open else None,
        "nextClose": next_close.isoformat(timespec="seconds") if next_close else None,
        "lastCandleTime": last_candle.time if last_candle else None,
    }


def should_skip_forex_scan(payload: dict[str, object]) -> tuple[bool, dict[str, object]]:
    if truthy(payload.get("force")):
        status = forex_market_status()
        return False, {**status, "forced": True}
    if os.getenv("FOREX_MARKET_GUARD", "true").lower() == "false":
        status = forex_market_status()
        return False, {**status, "guardDisabled": True}

    status = forex_market_status()
    return not bool(status["isOpen"]), status


def is_forex_open(current: datetime, close_hour: int, open_hour: int) -> bool:
    weekday = current.weekday()
    if weekday == 5:
        return False
    if weekday == 4 and current.hour >= close_hour:
        return False
    if weekday == 6 and current.hour < open_hour:
        return False
    return True


def find_next_transition(current: datetime, target_open: bool, close_hour: int, open_hour: int) -> datetime | None:
    cursor = current.replace(minute=0, second=0, microsecond=0)
    previous_state = is_forex_open(cursor, close_hour, open_hour)
    for hours in range(1, 24 * 8):
        candidate = cursor + timedelta(hours=hours)
        state = is_forex_open(candidate, close_hour, open_hour)
        if state != previous_state and state == target_open:
            return candidate
        previous_state = state
    return None


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "sim", "force"}


def get_market_timezone() -> timezone | ZoneInfo:
    name = os.getenv("MARKET_TIMEZONE", "America/Sao_Paulo")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-3), name)
