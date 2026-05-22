from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Download daily Forex history from Yahoo Finance chart data.")
    parser.add_argument("--symbol", default="EURUSD=X", help="Yahoo symbol, for example EURUSD=X.")
    parser.add_argument("--from-date", default="2020-01-01", help="Start date in YYYY-MM-DD.")
    parser.add_argument("--to-date", default=date.today().isoformat(), help="End date in YYYY-MM-DD.")
    parser.add_argument("--output", default="data/forex/eurusd_d1_yahoo.csv", help="Output CSV path.")
    args = parser.parse_args()

    period1 = to_unix(args.from_date)
    period2 = to_unix(args.to_date)
    query = urlencode({"period1": period1, "period2": period2, "interval": "1d", "events": "history"})
    url = f"{YAHOO_CHART_URL.format(symbol=args.symbol)}?{query}"
    request = Request(url, headers={"User-Agent": "TradingAIHub/0.1"})

    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    rows = []
    for index, timestamp in enumerate(timestamps):
        if quote["open"][index] is None or quote["close"][index] is None:
            continue
        rows.append(
            {
                "time": datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat(),
                "open": quote["open"][index],
                "high": quote["high"][index],
                "low": quote["low"][index],
                "close": quote["close"][index],
                "volume": quote.get("volume", [0] * len(timestamps))[index] or 0,
            }
        )

    if not rows:
        raise RuntimeError("Yahoo did not return candles for this request.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} candles to {output}")


def to_unix(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


if __name__ == "__main__":
    main()
