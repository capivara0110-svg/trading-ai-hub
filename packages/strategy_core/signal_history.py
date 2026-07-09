from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from packages.strategy_core.data import Candle
from packages.strategy_core.signals import Signal


def record_signal(signal: Signal, history_path: Path, candle_time: str | None = None) -> dict[str, object]:
    history = load_history(history_path)
    key = signal_key(signal)
    for item in history:
        if item.get("key") == key:
            return item

    item = {
        "key": key,
        "sentAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "signalCandleTime": candle_time,
        "symbol": signal.symbol,
        "timeframe": signal.timeframe,
        "side": signal.side,
        "confidence": signal.confidence,
        "entry": signal.entry,
        "stopLoss": signal.stop_loss,
        "takeProfit": signal.take_profit,
        "status": "OPEN",
        "resultPips": None,
        "closedAt": None,
        "exitPrice": None,
        "closeNotificationSent": False,
        "reason": signal.reason,
    }
    history.append(item)
    save_history(history_path, history)
    return item


def evaluate_history(history_path: Path, candles: list[Candle]) -> dict[str, object]:
    history = load_history(history_path)
    changed = False
    closed_now: list[dict[str, object]] = []
    for item in history:
        if item.get("status") != "OPEN":
            continue
        result = evaluate_item(item, candles)
        if result:
            item.update(result)
            item["closeNotificationSent"] = False
            closed_now.append(dict(item))
            changed = True
    if changed:
        save_history(history_path, history)
    summary = history_summary(history)
    summary["closedNow"] = closed_now
    return summary


def mark_signal_close_notification_sent(history_path: Path, key: str) -> None:
    history = load_history(history_path)
    changed = False
    for item in history:
        if item.get("key") == key:
            item["closeNotificationSent"] = True
            changed = True
            break
    if changed:
        save_history(history_path, history)


def history_summary(history: list[dict[str, object]]) -> dict[str, object]:
    closed = [item for item in history if item.get("status") in {"WIN", "LOSS"}]
    wins = [item for item in closed if item.get("status") == "WIN"]
    total_pips = sum(float(item.get("resultPips") or 0) for item in closed)
    return {
        "signals": history[-50:],
        "totalSignals": len(history),
        "openSignals": len([item for item in history if item.get("status") == "OPEN"]),
        "closedSignals": len(closed),
        "winRate": round(len(wins) / len(closed), 2) if closed else 0,
        "totalPips": round(total_pips, 1),
        "closedNow": [],
    }


def evaluate_item(item: dict[str, object], candles: list[Candle]) -> dict[str, object] | None:
    side = str(item.get("side") or "")
    entry = item.get("entry")
    stop = item.get("stopLoss")
    targets = item.get("takeProfit")
    if side not in {"BUY", "SELL"} or entry is None or stop is None or not isinstance(targets, list) or not targets:
        return None

    entry_price = float(entry)
    stop_price = float(stop)
    target_price = float(targets[0])
    signal_candle_time = str(item.get("signalCandleTime") or "")
    for candle in candles:
        if signal_candle_time and candle.time <= signal_candle_time:
            continue
        if side == "BUY":
            if candle.low <= stop_price:
                return close_item("LOSS", candle.time, stop_price, stop_price - entry_price, side)
            if candle.high >= target_price:
                return close_item("WIN", candle.time, target_price, target_price - entry_price, side)
        if side == "SELL":
            if candle.high >= stop_price:
                return close_item("LOSS", candle.time, stop_price, entry_price - stop_price, side)
            if candle.low <= target_price:
                return close_item("WIN", candle.time, target_price, entry_price - target_price, side)
    return None


def close_item(status: str, closed_at: str, exit_price: float, raw_result: float, side: str) -> dict[str, object]:
    return {
        "status": status,
        "closedAt": closed_at,
        "exitPrice": round(exit_price, 5),
        "resultPips": round(price_to_pips(raw_result, side), 1),
    }


def price_to_pips(value: float, side: str) -> float:
    multiplier = 100 if "JPY" in side else 10000
    return value * multiplier


def signal_key(signal: Signal) -> str:
    return "|".join(
        [
            signal.symbol,
            signal.timeframe,
            signal.side,
            str(signal.entry),
            str(signal.stop_loss),
            ",".join(str(target) for target in signal.take_profit),
        ]
    )


def load_history(history_path: Path) -> list[dict[str, object]]:
    if not history_path.exists():
        return []
    try:
        payload = json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def save_history(history_path: Path, history: list[dict[str, object]]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
