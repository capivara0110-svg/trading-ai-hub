from __future__ import annotations

import argparse
import csv
import struct
import calendar
from datetime import datetime, timedelta, timezone
from pathlib import Path


HEADER_SIZE = 148
RECORD_401 = struct.Struct("<qddddqiq")


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta historico MT4 HST v401 para CSV UTC.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument(
        "--server-offset",
        default="EET",
        help="Timezone do broker: EET (GMT+2/+3) ou offset fixo como +02:00.",
    )
    args = parser.parse_args()
    export_hst(args.input, args.output, args.months, parse_offset(args.server_offset))


def export_hst(input_path: Path, output_path: Path, months: int, server_offset: timezone | str) -> None:
    if months < 1:
        raise ValueError("months precisa ser positivo")
    with input_path.open("rb") as source:
        header = source.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE or struct.unpack_from("<i", header, 0)[0] != 401:
            raise ValueError("Somente HST versao 401 e suportado")
        symbol = header[68:80].split(b"\0", 1)[0].decode("ascii", errors="replace")
        period, digits = struct.unpack_from("<ii", header, 80)
        if period != 5:
            raise ValueError(f"Arquivo precisa ser M5; periodo encontrado: {period}")

        source.seek(-RECORD_401.size, 2)
        last_record = RECORD_401.unpack(source.read(RECORD_401.size))
        last_server_time = broker_datetime(last_record[0], server_offset)
        cutoff = last_server_time - timedelta(days=round(months * 365.2425 / 12))
        source.seek(HEADER_SIZE)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows = 0
        first_utc: datetime | None = None
        last_utc: datetime | None = None
        with output_path.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.writer(destination)
            writer.writerow(["time", "open", "high", "low", "close", "volume", "spread"])
            while raw := source.read(RECORD_401.size):
                if len(raw) != RECORD_401.size:
                    break
                timestamp, open_price, high, low, close, tick_volume, spread, _ = RECORD_401.unpack(raw)
                server_time = broker_datetime(timestamp, server_offset)
                if server_time < cutoff:
                    continue
                utc_time = server_time.astimezone(timezone.utc)
                writer.writerow(
                    [
                        utc_time.isoformat(sep=" ", timespec="seconds").replace("+00:00", "Z"),
                        f"{open_price:.{digits}f}",
                        f"{high:.{digits}f}",
                        f"{low:.{digits}f}",
                        f"{close:.{digits}f}",
                        tick_volume,
                        spread,
                    ]
                )
                rows += 1
                first_utc = first_utc or utc_time
                last_utc = utc_time

    print(
        f"Exportado {symbol} M{period}: {rows} candles, "
        f"{first_utc.isoformat() if first_utc else '--'} ate {last_utc.isoformat() if last_utc else '--'}"
    )


def parse_offset(value: str) -> timezone | str:
    raw = value.strip()
    if raw.upper() == "EET":
        return "EET"
    if len(raw) not in {3, 6} or raw[0] not in "+-":
        raise ValueError("server-offset deve usar formato +HH:MM ou -HH:MM")
    sign = 1 if raw[0] == "+" else -1
    parts = raw[1:].split(":")
    hours = int(parts[0])
    minutes = int(parts[1]) if len(parts) > 1 else 0
    if hours > 14 or minutes > 59:
        raise ValueError("server-offset invalido")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def broker_datetime(timestamp: int, source: timezone | str) -> datetime:
    naive = datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)
    if source == "EET":
        offset_hours = 3 if is_eet_summer(naive) else 2
        return naive.replace(tzinfo=timezone(timedelta(hours=offset_hours)))
    return naive.replace(tzinfo=source)


def is_eet_summer(value: datetime) -> bool:
    march_transition = last_sunday(value.year, 3).replace(hour=4)
    october_transition = last_sunday(value.year, 10).replace(hour=4)
    return march_transition <= value < october_transition


def last_sunday(year: int, month: int) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    result = datetime(year, month, last_day)
    return result - timedelta(days=(result.weekday() + 1) % 7)


if __name__ == "__main__":
    main()
