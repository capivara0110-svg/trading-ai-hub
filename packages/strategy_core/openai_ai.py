from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packages.strategy_core.signals import Signal


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4.1-nano"


def openai_config_status() -> dict[str, object]:
    return {
        "configured": bool(os.getenv("OPENAI_API_KEY")),
        "model": os.getenv("AI_MODEL", DEFAULT_MODEL),
        "telegramExplanation": os.getenv("AI_TELEGRAM_EXPLANATION", "true").lower() != "false",
        "onlyForAutoTrade": os.getenv("AI_ONLY_FOR_AUTO_TRADE", "true").lower() != "false",
    }


def explain_signal(signal: Signal) -> dict[str, object]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OpenAI nao configurada. Defina OPENAI_API_KEY no Railway.")

    model = os.getenv("AI_MODEL", DEFAULT_MODEL)
    payload = {
        "model": model,
        "instructions": (
            "Voce e um analista de risco para um sistema experimental de sinais Forex. "
            "Explique o sinal de forma curta, objetiva e em portugues do Brasil. "
            "Nao prometa lucro, nao diga que e recomendacao financeira e nao invente dados. "
            "Use no maximo 5 linhas."
        ),
        "input": json.dumps(signal.to_dict(), ensure_ascii=False),
        "max_output_tokens": 220,
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        raise ValueError(f"Falha na OpenAI ({error.code}): {compact_error(detail)}") from error
    except URLError as error:
        raise ValueError(f"Falha ao conectar na OpenAI: {error.reason}") from error

    return {
        "configured": True,
        "model": model,
        "text": extract_response_text(data),
    }


def should_add_ai_to_telegram() -> bool:
    return openai_config_status()["configured"] and os.getenv("AI_TELEGRAM_EXPLANATION", "true").lower() != "false"


def extract_response_text(data: dict[str, object]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = data.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return "\n".join(parts)

    raise ValueError("OpenAI retornou uma resposta sem texto.")


def compact_error(detail: str) -> str:
    if not detail:
        return "sem detalhe"
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return detail[:240]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message[:240]
    return detail[:240]
