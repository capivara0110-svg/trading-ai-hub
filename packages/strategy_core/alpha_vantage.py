from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from packages.strategy_core.data import Candle


ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
INTERVAL_MAP = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "60min",
}


def alpha_vantage_status() -> dict[str, object]:
    return {"configured": bool(os.getenv("ALPHA_VANTAGE_API_KEY"))}


def fetch_fx_intraday(symbol: str, timeframe: str, outputsize: str = "compact") -> list[Candle]:
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise ValueError("ALPHA_VANTAGE_API_KEY nao configurada")

    from_symbol, to_symbol = split_forex_symbol(symbol)
    interval = INTERVAL_MAP.get(timeframe.upper())
    if not interval:
        raise ValueError("Timeframe Alpha Vantage invalido. Use M1, M5, M15, M30 ou H1.")

    query = urlencode(
        {
            "function": "FX_INTRADAY",
            "from_symbol": from_symbol,
            "to_symbol": to_symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": api_key,
        }
    )
    request = Request(f"{ALPHA_VANTAGE_URL}?{query}", headers={"User-Agent": "TradingAIHub/0.1"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if "Note" in payload:
        raise ValueError("Alpha Vantage limitou as chamadas. Tente novamente mais tarde.")
    if "Information" in payload:
        raise ValueError(str(payload["Information"]))
    if "Error Message" in payload:
        raise ValueError(str(payload["Error Message"]))

    series_key = f"Time Series FX ({interval})"
    series = payload.get(series_key)
    if not isinstance(series, dict):
        raise ValueError("Alpha Vantage nao retornou serie FX valida")

    candles = [
        Candle(
            time=timestamp,
            open=float(values["1. open"]),
            high=float(values["2. high"]),
            low=float(values["3. low"]),
            close=float(values["4. close"]),
            volume=0,
        )
        for timestamp, values in sorted(series.items())
    ]
    if len(candles) < 25:
        raise ValueError("Alpha Vantage retornou poucos candles")
    return candles


def split_forex_symbol(symbol: str) -> tuple[str, str]:
    clean = symbol.replace("/", "").replace("_", "").replace("-", "").upper()
    if len(clean) != 6:
        raise ValueError("Ativo Forex deve ter 6 letras, exemplo EURUSD")
    return clean[:3], clean[3:]
