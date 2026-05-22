from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


STOOQ_DOWNLOAD_URL = "https://stooq.com/q/d/l/"


def main() -> None:
    parser = argparse.ArgumentParser(description="Download daily Forex history from Stooq.")
    parser.add_argument("--symbol", default="eurusd", help="Stooq symbol, for example eurusd.")
    parser.add_argument("--from-date", default="20200101", help="Start date in YYYYMMDD.")
    parser.add_argument("--to-date", default=date.today().strftime("%Y%m%d"), help="End date in YYYYMMDD.")
    parser.add_argument("--output", default="data/forex/eurusd_d1_stooq.csv", help="Output CSV path.")
    parser.add_argument("--apikey", default="", help="Stooq API key. Stooq may require this for CSV downloads.")
    args = parser.parse_args()

    params = {"s": args.symbol, "d1": args.from_date, "d2": args.to_date, "i": "d"}
    if args.apikey:
        params["apikey"] = args.apikey
    url = f"{STOOQ_DOWNLOAD_URL}?{urlencode(params)}"
    with urlopen(url, timeout=30) as response:
        raw_csv = response.read().decode("utf-8-sig")

    rows = list(csv.DictReader(raw_csv.splitlines()))
    if not rows or "Date" not in rows[0]:
        raise RuntimeError("Stooq did not return a valid CSV. It may require --apikey for CSV downloads.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "time": row["Date"],
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": row.get("Volume") or 0,
                }
            )

    print(f"Saved {len(rows)} candles to {output}")


if __name__ == "__main__":
    main()
