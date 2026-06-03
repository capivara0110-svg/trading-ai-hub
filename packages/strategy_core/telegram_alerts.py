from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from packages.strategy_core.market_hours import get_market_timezone
from packages.strategy_core.signals import Signal


TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"


def telegram_config_status() -> dict[str, object]:
    return {
        "configured": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "hasBotToken": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "hasChatId": bool(os.getenv("TELEGRAM_CHAT_ID")),
    }


def format_signal_message(signal: Signal, ai_note: str | None = None, execution_note: str | None = None) -> str:
    targets = " / ".join(str(target) for target in signal.take_profit) if signal.take_profit else "--"
    reasons = "\n".join(f"- {reason}" for reason in signal.reason)
    lines = [
        "Trading AI Hub",
        "",
        f"{signal.symbol} {signal.timeframe}",
        f"SINAL: {signal.side}",
        f"Confianca: {round(signal.confidence * 100)}%",
        f"IA score: {round((signal.ml_score or 0) * 100)}%" if signal.ml_score is not None else "IA score: --",
        "",
        f"Entrada: {signal.entry if signal.entry is not None else '--'}",
        f"Stop: {signal.stop_loss if signal.stop_loss is not None else '--'}",
        f"Alvos: {targets}",
        "",
        "Motivos:",
        reasons or "- sem motivo informado",
    ]
    if execution_note:
        lines.extend(["", execution_note.strip()])
    if ai_note:
        lines.extend(["", "Leitura da IA:", ai_note.strip()])
    lines.extend(["", "Aviso: sinal experimental, nao e recomendacao financeira nem garantia de lucro."])
    return "\n".join(lines)


def send_telegram_message(text: str) -> dict[str, object]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise ValueError("Telegram nao configurado. Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.")

    payload = urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = Request(
        TELEGRAM_API_URL.format(token=token, method="sendMessage"),
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def should_send_signal(signal: Signal, state_path: Path) -> tuple[bool, str]:
    min_confidence = float(os.getenv("TELEGRAM_MIN_CONFIDENCE", "0.60"))
    if signal.side == "NO_TRADE":
        return False, "Sem sinal operacional."
    if signal.confidence < min_confidence:
        return False, f"Confianca abaixo do minimo ({round(min_confidence * 100)}%)."

    key = signal_key(signal)
    state = read_signal_state(state_path)
    if key == state.get("lastSignalKey"):
        return False, "Sinal ja enviado anteriormente."
    if daily_signal_limit_reached(state):
        return False, "Limite diario de sinais do Telegram atingido."
    cooldown_ok, cooldown_reason = signal_cooldown_ok(state)
    if not cooldown_ok:
        return False, cooldown_reason
    return True, key


def mark_signal_sent(signal: Signal, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    state = read_signal_state(state_path)
    today = local_signal_day()
    sent_today = int(state.get("sentToday") or 0)
    if state.get("sentDay") != today:
        sent_today = 0
    payload = {
        "lastSignalKey": signal_key(signal),
        "lastSignalAt": now.isoformat(timespec="seconds"),
        "lastSide": signal.side,
        "lastSymbol": signal.symbol,
        "sentDay": today,
        "sentToday": sent_today + 1,
    }
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


def read_signal_state(state_path: Path) -> dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def signal_cooldown_ok(state: dict[str, object]) -> tuple[bool, str]:
    minutes = int(os.getenv("TELEGRAM_SIGNAL_COOLDOWN_MINUTES", "60"))
    if minutes <= 0:
        return True, "cooldown desativado"
    raw = state.get("lastSignalAt")
    if not raw:
        return True, "sem envio anterior"
    try:
        last_sent = datetime.fromisoformat(str(raw))
    except ValueError:
        return True, "estado anterior invalido"
    if last_sent.tzinfo is None:
        last_sent = last_sent.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - last_sent
    remaining = int((minutes * 60 - elapsed.total_seconds()) // 60) + 1
    if remaining > 0:
        return False, f"Aguardando cooldown do Telegram ({remaining} min)."
    return True, "cooldown liberado"


def daily_signal_limit_reached(state: dict[str, object]) -> bool:
    limit = int(os.getenv("TELEGRAM_MAX_SIGNALS_PER_DAY", "4"))
    if limit <= 0:
        return False
    today = local_signal_day()
    if state.get("sentDay") != today:
        return False
    return int(state.get("sentToday") or 0) >= limit


def local_signal_day() -> str:
    return datetime.now(get_market_timezone()).date().isoformat()
