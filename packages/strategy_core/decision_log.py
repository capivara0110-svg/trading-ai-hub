from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def record_decision(
    path: Path,
    candle_time: str | None,
    signal: object,
    alert_allowed: bool,
    alert_reason: str,
    execution: dict[str, object],
    spread_pips: float | None = None,
) -> dict[str, object]:
    rows = load_decisions(path)
    signal_payload = signal.to_dict() if hasattr(signal, "to_dict") else {}
    item = {
        "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candleTime": candle_time,
        "symbol": signal_payload.get("symbol"),
        "timeframe": signal_payload.get("timeframe"),
        "side": signal_payload.get("side"),
        "confidence": signal_payload.get("confidence"),
        "mlScore": signal_payload.get("mlScore"),
        "mlTrained": signal_payload.get("mlTrained"),
        "strategyStyle": signal_payload.get("strategyStyle"),
        "entry": signal_payload.get("entry"),
        "stopLoss": signal_payload.get("stopLoss"),
        "takeProfit": signal_payload.get("takeProfit"),
        "spreadPips": spread_pips,
        "reasons": signal_payload.get("reason") or [],
        "alertAllowed": alert_allowed,
        "alertReason": alert_reason,
        "executionCreated": bool(execution.get("created")),
        "executionReason": execution.get("reason"),
        "executionOrderId": (
            execution.get("order", {}).get("id") if isinstance(execution.get("order"), dict) else None
        ),
        "status": "OBSERVED",
    }
    if rows:
        previous = rows[-1]
        if (
            previous.get("candleTime") == item["candleTime"]
            and previous.get("side") == item["side"]
            and previous.get("entry") == item["entry"]
        ):
            previous.update(item)
            save_decisions(path, rows[-5000:])
            return previous
    rows.append(item)
    save_decisions(path, rows[-5000:])
    return item


def evaluate_decisions(path: Path, candles: list[object]) -> dict[str, int]:
    rows = load_decisions(path)
    closed = 0
    for item in rows:
        if item.get("status") != "OBSERVED" or item.get("side") not in {"BUY", "SELL"}:
            continue
        entry = item.get("entry")
        stop = item.get("stopLoss")
        targets = item.get("takeProfit")
        candle_time = str(item.get("candleTime") or "")
        if entry is None or stop is None or not isinstance(targets, list) or not targets:
            continue
        target = float(targets[0])
        outcome = None
        exit_price = None
        exit_time = None
        for candle in candles:
            if str(getattr(candle, "time", "")) <= candle_time:
                continue
            if item["side"] == "BUY":
                if float(getattr(candle, "low")) <= float(stop):
                    outcome, exit_price = "LOSS", float(stop)
                elif float(getattr(candle, "high")) >= target:
                    outcome, exit_price = "WIN", target
            else:
                if float(getattr(candle, "high")) >= float(stop):
                    outcome, exit_price = "LOSS", float(stop)
                elif float(getattr(candle, "low")) <= target:
                    outcome, exit_price = "WIN", target
            if outcome:
                exit_time = str(getattr(candle, "time"))
                break
        if not outcome or exit_price is None:
            continue
        raw = exit_price - float(entry)
        if item["side"] == "SELL":
            raw *= -1
        cost = float(os.getenv("PAPER_COST_PIPS", "1.3"))
        item.update(
            {
                "status": outcome,
                "exitPrice": exit_price,
                "closedAt": exit_time,
                "grossResultPips": round(raw * 10000, 1),
                "resultPips": round(raw * 10000 - cost, 1),
                "costPips": cost,
            }
        )
        closed += 1
    if closed:
        save_decisions(path, rows)
    return {"closed": closed, "total": len(rows)}


def update_decision_execution(path: Path, order_id: str, payload: dict[str, object]) -> None:
    rows = load_decisions(path)
    changed = False
    for item in reversed(rows):
        if str(item.get("executionOrderId") or "") != order_id:
            continue
        fill = payload.get("fillPrice")
        entry = item.get("entry")
        item["executionStatus"] = payload.get("status")
        item["fillPrice"] = fill
        item["brokerProfit"] = payload.get("profit")
        item["brokerClosePrice"] = payload.get("closePrice")
        if fill is not None and entry is not None:
            item["entryDeviationPips"] = round(abs(float(fill) - float(entry)) * 10000, 1)
        changed = True
        break
    if changed:
        save_decisions(path, rows)


def load_decisions(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return payload if isinstance(payload, list) else []


def save_decisions(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
