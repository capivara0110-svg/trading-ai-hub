from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from packages.strategy_core.market_hours import get_market_timezone
from packages.strategy_core.signals import Signal
from packages.strategy_core.signals import risk_reward_ratio


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


def format_order_result_message(order: dict[str, object]) -> str:
    status = str(order.get("status") or "").upper()
    result = "WIN" if status == "WIN" else "LOSS"
    symbol = str(order.get("symbol") or "--")
    timeframe = str(order.get("timeframe") or "--")
    side = str(order.get("side") or "--")
    pips = order.get("resultPips")
    profit = order.get("profit")
    lines = [
        "Trading AI Hub",
        "",
        f"ORDEM FECHADA: {result}",
        f"{symbol} {timeframe} {side}",
        "",
        f"Entrada: {order.get('fillPrice') or order.get('entry') or '--'}",
        f"Saida: {order.get('closePrice') or '--'}",
        f"Resultado: {pips if pips is not None else '--'} pips",
    ]
    if profit is not None:
        lines.append(f"Lucro/prejuizo: {profit}")
    if order.get("brokerTicket"):
        lines.append(f"Ticket: {order.get('brokerTicket')}")
    if order.get("brokerMessage"):
        lines.extend(["", str(order.get("brokerMessage"))])
    lines.extend(["", "Aviso: resultado operacional registrado pelo robo/MT5."])
    return "\n".join(lines)


def format_signal_result_message(item: dict[str, object]) -> str:
    status = str(item.get("status") or "").upper()
    result = "WIN" if status == "WIN" else "LOSS"
    targets = item.get("takeProfit") if isinstance(item.get("takeProfit"), list) else []
    first_target = targets[0] if targets else "--"
    lines = [
        "Trading AI Hub",
        "",
        f"SINAL FECHADO: {result}",
        f"{item.get('symbol') or '--'} {item.get('timeframe') or '--'} {item.get('side') or '--'}",
        "",
        f"Entrada: {item.get('entry') if item.get('entry') is not None else '--'}",
        f"Stop: {item.get('stopLoss') if item.get('stopLoss') is not None else '--'}",
        f"Alvo 1: {first_target}",
        f"Saida simulada: {item.get('exitPrice') if item.get('exitPrice') is not None else '--'}",
        f"Resultado: {item.get('resultPips') if item.get('resultPips') is not None else '--'} pips",
        f"Fechou em: {item.get('closedAt') or '--'}",
        "",
        "Modo: acompanhamento pelo servidor, sem execucao no MT5.",
        "Aviso: resultado simulado por candle, nao e garantia de execucao real.",
    ]
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
    min_confidence = max(env_float("TELEGRAM_MIN_CONFIDENCE", 0.72), 0.72)
    min_ml_score = max(env_float("TELEGRAM_MIN_ML_SCORE", env_float("SIGNAL_MIN_ML_SCORE", 0.62)), 0.62)
    if signal.side == "NO_TRADE":
        return False, "Sem sinal operacional."
    if signal.confidence < min_confidence:
        return False, f"Confianca abaixo do minimo ({round(min_confidence * 100)}%)."
    if signal.ml_score is not None and signal.ml_score < min_ml_score:
        return False, f"Score IA abaixo do minimo ({round(min_ml_score * 100)}%)."
    passed_expectancy, expectancy_reason = telegram_expectancy_gate(signal)
    if not passed_expectancy:
        return False, expectancy_reason
    passed_context, context_reason = telegram_context_gate(signal)
    if not passed_context:
        return False, context_reason

    key = signal_key(signal)
    state = read_signal_state(state_path)
    if key == state.get("lastSignalKey"):
        return False, "Sinal ja enviado anteriormente."
    if daily_signal_limit_reached(state):
        return False, "Limite diario de sinais do Telegram atingido."
    cooldown_ok, cooldown_reason = signal_cooldown_ok(state)
    if not cooldown_ok:
        return False, cooldown_reason
    side_cooldown_ok, side_cooldown_reason = same_side_cooldown_ok(state, signal.side)
    if not side_cooldown_ok:
        return False, side_cooldown_reason
    return True, key


def telegram_expectancy_gate(signal: Signal) -> tuple[bool, str]:
    if signal.entry is None or signal.stop_loss is None or not signal.take_profit:
        return False, "Sinal sem entrada, stop ou alvo."
    min_rr = max(env_float("TELEGRAM_MIN_RISK_REWARD", 1.60), 1.60)
    rr = risk_reward_ratio(float(signal.entry), float(signal.stop_loss), float(signal.take_profit[0]), signal.side)
    if rr < min_rr:
        return False, f"Risco/retorno abaixo do minimo ({round(rr, 2)})."
    return True, "expectativa aprovada"


def telegram_context_gate(signal: Signal) -> tuple[bool, str]:
    reasons = [str(reason).upper() for reason in signal.reason]
    if env_bool("TELEGRAM_BLOCK_FRIDAY_CLOSE", True):
        if any("SEXTA PERTO DO FECHAMENTO" in reason for reason in reasons):
            return False, "Sexta perto do fechamento."

    if env_bool("TELEGRAM_BLOCK_MTF_CONFLICT", True):
        conflict = f"CONTRA {signal.side}".upper()
        if any(conflict in reason for reason in reasons):
            return False, "Confirmacao MTF contra o sinal."

    if env_bool("TELEGRAM_REQUIRE_MTF_CONFIRMATION", True):
        confirmation = f"CONFIRMA {signal.side}".upper()
        if not any(confirmation in reason for reason in reasons):
            return False, "Sem confirmacao M15/H1 a favor."

    return True, "contexto aprovado"


def env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "sim", "on"}


def env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip().replace(",", ".")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def mark_signal_sent(signal: Signal, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    state = read_signal_state(state_path)
    today = local_signal_day()
    sent_today = int(state.get("sentToday") or 0)
    if state.get("sentDay") != today:
        sent_today = 0
    last_by_side = state.get("lastSignalBySide") if isinstance(state.get("lastSignalBySide"), dict) else {}
    last_by_side[signal.side] = now.isoformat(timespec="seconds")
    payload = {
        "lastSignalKey": signal_key(signal),
        "lastSignalAt": now.isoformat(timespec="seconds"),
        "lastSide": signal.side,
        "lastSymbol": signal.symbol,
        "sentDay": today,
        "sentToday": sent_today + 1,
        "lastSignalBySide": last_by_side,
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


def same_side_cooldown_ok(state: dict[str, object], side: str) -> tuple[bool, str]:
    minutes = env_int("TELEGRAM_SAME_SIDE_COOLDOWN_MINUTES", 120)
    if minutes <= 0:
        return True, "cooldown mesmo lado desativado"

    last_by_side = state.get("lastSignalBySide") if isinstance(state.get("lastSignalBySide"), dict) else {}
    raw = last_by_side.get(side)
    if not raw and state.get("lastSide") == side:
        raw = state.get("lastSignalAt")
    if not raw:
        return True, "sem envio anterior do mesmo lado"
    try:
        last_sent = datetime.fromisoformat(str(raw))
    except ValueError:
        return True, "estado anterior invalido"
    if last_sent.tzinfo is None:
        last_sent = last_sent.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - last_sent
    remaining = int((minutes * 60 - elapsed.total_seconds()) // 60) + 1
    if remaining > 0:
        return False, f"Aguardando cooldown de {side} ({remaining} min)."
    return True, "cooldown mesmo lado liberado"


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
