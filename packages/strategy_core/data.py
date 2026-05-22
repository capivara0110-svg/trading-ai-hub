from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Candle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def load_candles(path: Path) -> list[Candle]:
    with path.open(newline="", encoding="utf-8") as file:
        rows = csv.DictReader(file)
        return [
            Candle(
                time=row["time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume") or 0),
            )
            for row in rows
        ]

