from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from packages.strategy_core.data import Candle


TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
INTERVAL_MAP = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1day",
}


def twelve_data_status() -> dict[str, object]:
    return {"configured": bool(os.getenv("TWELVE_DATA_API_KEY"))}


def fetch_time_series(symbol: str, timeframe: str, outputsize: int = 100) -> list[Candle]:
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        raise ValueError("TWELVE_DATA_API_KEY nao configurada")

    interval = INTERVAL_MAP.get(timeframe.upper())
    if not interval:
        raise ValueError("Timeframe Twelve Data invalido. Use M1, M5, M15, M30, H1, H4 ou D1.")

    query = urlencode(
        {
            "symbol": normalize_symbol(symbol),
            "interval": interval,
            "outputsize": max(25, min(outputsize, 5000)),
            "timezone": "UTC",
            "apikey": api_key,
            "format": "JSON",
        }
    )
    request = Request(f"{TWELVE_DATA_URL}?{query}", headers={"User-Agent": "TradingAIHub/0.1"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if payload.get("status") == "error":
        raise ValueError(str(payload.get("message") or "Twelve Data retornou erro"))

    values = payload.get("values")
    if not isinstance(values, list):
        raise ValueError("Twelve Data nao retornou candles validos")

    candles = [
        Candle(
            time=f"{row['datetime']}Z",
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume") or 0),
        )
        for row in reversed(values)
    ]
    if len(candles) < 25:
        raise ValueError("Twelve Data retornou poucos candles")
    return candles


def normalize_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    if "/" in clean:
        return clean
    clean = clean.replace("_", "").replace("-", "")
    if len(clean) == 6:
        return f"{clean[:3]}/{clean[3:]}"
    return clean
