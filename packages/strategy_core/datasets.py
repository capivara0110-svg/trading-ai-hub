from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.strategy_core.data import Candle, load_candles


@dataclass(frozen=True)
class Dataset:
    id: str
    symbol: str
    timeframe: str
    path: Path
    candles: int

    def to_dict(self, active_id: str | None = None) -> dict[str, object]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "fileName": self.path.name,
            "candles": self.candles,
            "active": self.id == active_id,
        }


class DatasetStore:
    def __init__(self, root: Path, default_dataset: Path, bundled_datasets: list[Dataset] | None = None) -> None:
        self.root = root
        self.uploads = root / "data" / "uploads"
        self.state_path = self.uploads / "state.json"
        self.default_dataset = default_dataset
        self.bundled_datasets = bundled_datasets or []
        self.uploads.mkdir(parents=True, exist_ok=True)

    def active_path(self) -> Path:
        dataset = self.active_dataset()
        if dataset is not None and dataset.path.exists():
            return dataset.path
        return self.default_dataset

    def active_dataset(self) -> Dataset | None:
        active_id = self.active_id()
        if not active_id:
            return self.get("sample-eurusd-m5")
        bundled = self.get(active_id)
        if bundled is not None:
            return bundled
        dataset_path = self.uploads / f"{active_id}.csv"
        return self.dataset_from_path(dataset_path) if dataset_path.exists() else self.get("sample-eurusd-m5")

    def active_id(self) -> str | None:
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        active = payload.get("activeDataset")
        return str(active) if active else None

    def list(self) -> list[Dataset]:
        datasets = [
            Dataset(
                id="sample-eurusd-m5",
                symbol="EURUSD",
                timeframe="M5",
                path=self.default_dataset,
                candles=len(load_candles(self.default_dataset)),
            )
        ]
        datasets.extend(
            Dataset(
                id=dataset.id,
                symbol=dataset.symbol,
                timeframe=dataset.timeframe,
                path=dataset.path,
                candles=len(load_candles(dataset.path)),
            )
            for dataset in self.bundled_datasets
            if dataset.path.exists()
        )
        for path in sorted(self.uploads.glob("*.csv")):
            if path.name == self.state_path.name:
                continue
            datasets.append(self.dataset_from_path(path))
        return datasets

    def get(self, dataset_id: str) -> Dataset | None:
        for dataset in self.list():
            if dataset.id == dataset_id:
                return dataset
        return None

    def set_active(self, dataset_id: str) -> Dataset:
        dataset = self.get(dataset_id)
        if dataset is None:
            raise ValueError("Dataset nao encontrado")
        self.state_path.write_text(json.dumps({"activeDataset": dataset.id}, indent=2), encoding="utf-8")
        return dataset

    def save_csv(self, symbol: str, timeframe: str, content: str, source_timezone: str | None = None) -> Dataset:
        clean_symbol = normalize_id(symbol)
        clean_timeframe = normalize_id(timeframe)
        if not clean_symbol or not clean_timeframe:
            raise ValueError("Informe ativo e timeframe validos")

        candles = parse_uploaded_candles(content, source_timezone=source_timezone)
        dataset_id = f"{clean_symbol.lower()}-{clean_timeframe.lower()}"
        path = self.uploads / f"{dataset_id}.csv"
        path.write_text(normalize_csv(candles), encoding="utf-8")
        self.set_active(dataset_id)
        return self.dataset_from_path(path)

    def save_candles(self, symbol: str, timeframe: str, candles: list[Candle]) -> Dataset:
        clean_symbol = normalize_id(symbol)
        clean_timeframe = normalize_id(timeframe)
        if not clean_symbol or not clean_timeframe:
            raise ValueError("Informe ativo e timeframe validos")
        if len(candles) < 25:
            raise ValueError("Envie pelo menos 25 candles")

        dataset_id = f"{clean_symbol.lower()}-{clean_timeframe.lower()}"
        path = self.uploads / f"{dataset_id}.csv"
        path.write_text(normalize_csv(candles), encoding="utf-8")
        self.set_active(dataset_id)
        return self.dataset_from_path(path)

    def dataset_from_path(self, path: Path) -> Dataset:
        candles = load_candles(path)
        parts = path.stem.split("-", maxsplit=1)
        symbol = parts[0].upper() if parts else path.stem.upper()
        timeframe = parts[1].upper() if len(parts) > 1 else "M5"
        return Dataset(id=path.stem, symbol=symbol, timeframe=timeframe, path=path, candles=len(candles))


def normalize_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def parse_uploaded_candles(content: str, source_timezone: str | None = None) -> list[Candle]:
    rows = content.replace("\ufeff", "").strip()
    if not rows:
        raise ValueError("CSV vazio")

    import csv
    from io import StringIO

    sample = rows[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    reader = csv.DictReader(StringIO(rows), dialect=dialect)
    required = {"time", "open", "high", "low", "close"}
    field_map = {canonical_header(field): field for field in reader.fieldnames or []}
    columns = set(field_map)
    missing = (required - {"time"}) - columns
    has_time = "time" in columns or {"date", "clock"} <= columns
    if not has_time:
        missing.add("time")
    if missing:
        raise ValueError(f"CSV sem colunas obrigatorias: {', '.join(sorted(missing))}")

    candles = [
        Candle(
            time=normalize_candle_time(row_time(row, field_map), source_timezone),
            open=float(row[field_map["open"]]),
            high=float(row[field_map["high"]]),
            low=float(row[field_map["low"]]),
            close=float(row[field_map["close"]]),
            volume=float(row.get(field_map.get("volume", ""), 0) or 0),
        )
        for row in reader
    ]
    if len(candles) < 25:
        raise ValueError("CSV precisa ter pelo menos 25 candles")
    return candles


def normalize_candle_time(value: str, source_timezone: str | None = None) -> str:
    """Return an ISO-like UTC timestamp when the source timezone is known.

    Naive legacy timestamps are preserved unless callers explicitly identify the
    broker/source timezone. This avoids silently shifting existing datasets.
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Candle sem horario")

    parsed = parse_candle_datetime(raw)
    if parsed.tzinfo is None:
        if not source_timezone:
            return parsed.isoformat(sep=" ", timespec="seconds")
        parsed = parsed.replace(tzinfo=source_timezone_info(source_timezone))

    return parsed.astimezone(timezone.utc).isoformat(sep=" ", timespec="seconds").replace("+00:00", "Z")


def source_timezone_info(value: str):
    raw = value.strip()
    offset_match = re.fullmatch(r"(?:UTC)?([+-])(\d{1,2})(?::?(\d{2}))?", raw, re.IGNORECASE)
    if offset_match:
        direction = 1 if offset_match.group(1) == "+" else -1
        hours = int(offset_match.group(2))
        minutes = int(offset_match.group(3) or 0)
        if hours > 14 or minutes > 59:
            raise ValueError(f"Timezone de origem invalido: {value}")
        return timezone(direction * timedelta(hours=hours, minutes=minutes))
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError as error:
        raise ValueError(
            f"Timezone de origem indisponivel: {value}. Use um offset como -03:00 ou +02:00."
        ) from error


def parse_candle_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    formats = (
        None,
        "%Y.%m.%d %H:%M:%S",
        "%Y.%m.%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.fromisoformat(normalized) if fmt is None else datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f"Horario de candle invalido: {value}")


def normalize_csv(candles: list[Candle]) -> str:
    lines = ["time,open,high,low,close,volume"]
    for candle in candles:
        lines.append(
            f"{candle.time},{candle.open},{candle.high},{candle.low},{candle.close},{candle.volume}"
        )
    return "\n".join(lines) + "\n"


def canonical_header(value: str | None) -> str:
    raw = str(value or "").replace("\ufeff", "").strip().lower()
    header = raw.replace("<", "").replace(">", "").replace(" ", "")
    aliases = {
        "datetime": "time",
        "timestamp": "time",
        "date": "date",
        "time": "clock" if raw.startswith("<") else "time",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "tickvol": "volume",
        "tick_volume": "volume",
        "volume": "volume",
        "vol": "volume",
    }
    return aliases.get(header, header)


def row_time(row: dict[str, str], field_map: dict[str, str]) -> str:
    if "time" in field_map:
        return str(row[field_map["time"]])
    return f"{row[field_map['date']]} {row[field_map['clock']]}"


def candles_from_payload(rows: object) -> list[Candle]:
    if not isinstance(rows, list):
        raise ValueError("candles precisa ser uma lista")

    candles: list[Candle] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Cada candle precisa ser um objeto")
        candles.append(
            Candle(
                time=str(row.get("time") or ""),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume") or 0),
            )
        )
    return candles
