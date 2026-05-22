from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from packages.strategy_core.signals import Signal


TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"


def telegram_config_status() -> dict[str, object]:
    return {
        "configured": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "hasBotToken": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "hasChatId": bool(os.getenv("TELEGRAM_CHAT_ID")),
    }


def format_signal_message(signal: Signal) -> str:
    targets = " / ".join(str(target) for target in signal.take_profit) if signal.take_profit else "--"
    reasons = "\n".join(f"- {reason}" for reason in signal.reason)
    return "\n".join(
        [
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
            "",
            "Aviso: sinal experimental, nao e recomendacao financeira nem garantia de lucro.",
        ]
    )


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
