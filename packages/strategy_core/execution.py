from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from packages.strategy_core.market_hours import get_market_timezone
from packages.strategy_core.signals import Signal
from packages.strategy_core.signals import risk_reward_ratio
from packages.strategy_core.profit_manager import get_profit_manager


def execution_status(state_path: Path) -> dict[str, object]:
    state = read_execution_state(state_path)
    order = state.get("order") if isinstance(state.get("order"), dict) else None
    return {
        "enabled": auto_trade_enabled(),
        "mode": os.getenv("AUTO_TRADE_MODE", "DEMO_ONLY"),
        "configured": bool(os.getenv("EXECUTION_SECRET")),
        "lot": env_float("AUTO_TRADE_LOT", 0.01),
        "maxOrdersPerDay": env_int("AUTO_TRADE_MAX_ORDERS_PER_DAY", 3),
        "ttlSeconds": env_int("AUTO_TRADE_ORDER_TTL_SECONDS", 180),
        "claimedTtlSeconds": env_int("AUTO_TRADE_CLAIMED_TTL_SECONDS", 300),
        "pendingOrder": active_order(order),
        "lastOrder": order,
        "ordersToday": int(state.get("ordersToday") or 0),
        "orderDay": state.get("orderDay"),
    }


def create_pending_order(signal: Signal, state_path: Path, candle_time: str | None = None) -> dict[str, object]:
    state = read_execution_state(state_path)
    if cleanup_stale_orders(state):
        write_execution_state(state_path, state)

    allowed, reason = pending_order_eligibility(signal, state_path)
    if not allowed:
        return {"created": False, "reason": reason}

    state = read_execution_state(state_path)
    now = datetime.now(timezone.utc)
    ttl_seconds = env_int("AUTO_TRADE_ORDER_TTL_SECONDS", 180)
    order = {
        "id": uuid.uuid4().hex,
        "status": "PENDING",
        "createdAt": now.isoformat(timespec="seconds"),
        "expiresAt": (now + timedelta(seconds=max(10, ttl_seconds))).isoformat(timespec="seconds"),
        "mode": os.getenv("AUTO_TRADE_MODE", "DEMO_ONLY"),
        "symbol": signal.symbol,
        "timeframe": signal.timeframe,
        "side": signal.side,
        "lot": env_float("AUTO_TRADE_LOT", 0.01),
        "entry": signal.entry,
        "stopLoss": signal.stop_loss,
        "takeProfit": signal.take_profit[0],
        "takeProfit2": signal.take_profit[1] if len(signal.take_profit) > 1 else None,
        "maxEntryDeviationPips": env_float("AUTO_TRADE_MAX_ENTRY_DEVIATION_PIPS", 1.5),
        "confidence": signal.confidence,
        "mlScore": signal.ml_score,
        "signalCandleTime": candle_time,
        "reason": signal.reason,
    }
    state["order"] = order
    increment_daily_count(state, now)
    write_execution_state(state_path, state)
    return {"created": True, "order": order}


def pending_order_eligibility(signal: Signal, state_path: Path) -> tuple[bool, str]:
    if not auto_trade_enabled():
        return False, "auto trade desativado"
    if signal.side == "NO_TRADE":
        return False, "sem sinal operacional"
    if signal.entry is None or signal.stop_loss is None or not signal.take_profit:
        return False, "sinal sem entrada, stop ou alvo"

    min_confidence = env_float("AUTO_TRADE_MIN_CONFIDENCE", 0.72)
    if signal.confidence < min_confidence:
        return False, f"score abaixo do minimo ({round(min_confidence * 100)}%)"
    news_blocked, news_reason = news_block_active()
    if news_blocked:
        return False, news_reason
    passed_quality, quality_reason = execution_quality_gate(signal)
    if not passed_quality:
        return False, quality_reason

    state = read_execution_state(state_path)
    if cleanup_stale_orders(state):
        write_execution_state(state_path, state)
        state = read_execution_state(state_path)

    current = state.get("order") if isinstance(state.get("order"), dict) else None
    active = active_order(current)
    if active:
        replace_ok, replace_reason = should_replace_active_order(active, signal)
        if not replace_ok:
            return False, replace_reason
    if daily_order_limit_reached(state):
        return False, "limite diario de ordens atingido"
    return True, "elegivel para auto trade"


def execution_quality_gate(signal: Signal) -> tuple[bool, str]:
    min_ml_score = max(
        env_float("AUTO_TRADE_MIN_ML_SCORE", 0.55),
        env_float("SIGNAL_MIN_ML_SCORE", 0.55),
    )
    if signal.ml_score is not None and signal.ml_score < min_ml_score:
        return False, f"score IA abaixo do minimo ({round(min_ml_score * 100)}%)"

    min_rr = env_float("AUTO_TRADE_MIN_RISK_REWARD", 1.35)
    rr = risk_reward_ratio(
        float(signal.entry or 0),
        float(signal.stop_loss or 0),
        float(signal.take_profit[0]),
        signal.side,
    )
    if rr < min_rr:
        return False, f"risco/retorno abaixo do minimo ({round(rr, 2)})"

    reasons = [str(reason).upper() for reason in signal.reason]
    if env_bool("AUTO_TRADE_BLOCK_MTF_CONFLICT", True):
        conflict = f"CONTRA {signal.side}".upper()
        if any(conflict in reason for reason in reasons):
            return False, "confirmacao MTF contra o sinal"

    require_mtf_confirmation = not env_bool("AUTO_TRADE_ALLOW_NO_MTF_CONFIRMATION", False)
    if require_mtf_confirmation or env_bool("AUTO_TRADE_REQUIRE_MTF_CONFIRMATION", True):
        confirmation = f"CONFIRMA {signal.side}".upper()
        if not any(confirmation in reason for reason in reasons):
            return False, "sem confirmacao M15/H1 a favor"

    return True, "qualidade aprovada"


def news_block_active() -> tuple[bool, str]:
    if env_bool("AUTO_TRADE_NEWS_BLOCK_ENABLED", False):
        return True, os.getenv("AUTO_TRADE_NEWS_BLOCK_REASON", "auto trade bloqueado por noticia")

    raw_until = normalized_env("AUTO_TRADE_NEWS_BLOCK_UNTIL")
    if raw_until == "":
        return False, "sem bloqueio de noticia"
    block_until = parse_datetime(raw_until)
    if block_until and datetime.now(timezone.utc) < block_until:
        reason = os.getenv("AUTO_TRADE_NEWS_BLOCK_REASON", "auto trade pausado por janela de noticia")
        return True, f"{reason} ate {block_until.isoformat(timespec='minutes')}"
    return False, "bloqueio de noticia expirado"


def pending_order(state_path: Path) -> dict[str, object]:
    state = read_execution_state(state_path)
    order = state.get("order") if isinstance(state.get("order"), dict) else None
    active = active_order(order)
    if active and active.get("status") == "PENDING":
        return {"enabled": auto_trade_enabled(), "order": active}
    return {"enabled": auto_trade_enabled(), "order": None}


def claim_order(state_path: Path, order_id: str) -> dict[str, object]:
    state = read_execution_state(state_path)
    order = state.get("order") if isinstance(state.get("order"), dict) else None
    active = active_order(order)
    if not active:
        return {"claimed": False, "reason": "nenhuma ordem pendente ativa"}
    if active.get("status") != "PENDING":
        return {"claimed": False, "reason": "ordem ja reservada"}
    if str(active.get("id")) != order_id:
        return {"claimed": False, "reason": "ordem nao encontrada"}
    active["status"] = "CLAIMED"
    active["claimedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["order"] = active
    write_execution_state(state_path, state)
    return {"claimed": True, "order": active}


def mark_order_result(state_path: Path, order_id: str, payload: dict[str, object]) -> dict[str, object]:
    state = read_execution_state(state_path)
    order = state.get("order") if isinstance(state.get("order"), dict) else None
    if not order or str(order.get("id")) != order_id:
        return {"updated": False, "reason": "ordem nao encontrada"}
    status = str(payload.get("status") or "EXECUTED").upper()
    if status not in {"EXECUTED", "REJECTED", "CANCELLED", "ERROR"}:
        status = "EXECUTED"
    order["status"] = status

    # Registra no Profit Manager para gerenciamento de lucro
    if status == "EXECUTED":
        order["fillPrice"] = payload.get("fillPrice", order.get("entry"))
        order["brokerTicket"] = payload.get("brokerTicket")
        pm = get_profit_manager()
        if order_id not in pm.trades:
            pm.register_trade(
                order_id=order_id,
                symbol=str(order.get("symbol", "EURUSD")),
                direction="buy" if str(order.get("side", "")).upper() == "BUY" else "sell",
                entry_price=float(payload.get("fillPrice", order.get("entry", 0))),
                sl=float(order.get("stopLoss", 0)),
                tp=float(order.get("takeProfit", 0)),
                volume=float(order.get("lot", 0.01)),
                broker_ticket=str(payload.get("brokerTicket", "")),
            )
    order["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    order["brokerTicket"] = payload.get("brokerTicket")
    order["brokerMessage"] = payload.get("message")
    order["fillPrice"] = payload.get("fillPrice")
    state["order"] = order
    write_execution_state(state_path, state)
    return {"updated": True, "order": order}


def authorize_execution(headers: object, payload: dict[str, object] | None = None) -> bool:
    expected = os.getenv("EXECUTION_SECRET")
    if not expected:
        return False
    provided = ""
    if hasattr(headers, "get"):
        provided = str(headers.get("X-Execution-Secret") or "")
    if not provided and payload:
        provided = str(payload.get("secret") or "")
    return provided == expected


def auto_trade_enabled() -> bool:
    return os.getenv("AUTO_TRADE_ENABLED", "false").lower() == "true"


def active_order(order: dict[str, object] | None) -> dict[str, object] | None:
    if not order:
        return None
    status = str(order.get("status") or "")
    if status not in {"PENDING", "CLAIMED"}:
        return None
    now = datetime.now(timezone.utc)
    expires_at = parse_datetime(order.get("expiresAt"))
    if status == "PENDING" and expires_at and now > expires_at:
        order["status"] = "EXPIRED"
        order["updatedAt"] = now.isoformat(timespec="seconds")
        return None
    if status == "CLAIMED":
        claimed_at = parse_datetime(order.get("claimedAt"))
        claimed_ttl = env_int("AUTO_TRADE_CLAIMED_TTL_SECONDS", 300)
        if claimed_at and (now - claimed_at).total_seconds() > claimed_ttl:
            order["status"] = "EXPIRED"
            order["updatedAt"] = now.isoformat(timespec="seconds")
            return None
    return order


def cleanup_stale_orders(state: dict[str, object]) -> bool:
    order = state.get("order") if isinstance(state.get("order"), dict) else None
    if not order:
        return False
    previous_status = str(order.get("status") or "")
    active = active_order(order)
    if active:
        return False
    if previous_status in {"PENDING", "CLAIMED"}:
        state["lastOrder"] = order
        state["order"] = None
        return True
    if previous_status in {"EXECUTED", "REJECTED", "CANCELLED", "ERROR", "EXPIRED"}:
        state["lastOrder"] = order
        state["order"] = None
        return True
    return False


def should_replace_active_order(active: dict[str, object], signal: Signal) -> tuple[bool, str]:
    if str(active.get("symbol") or "") != signal.symbol:
        return False, "ja existe ordem pendente ativa em outro ativo"
    if str(active.get("side") or "") == signal.side:
        return False, "ja existe ordem pendente ativa no mesmo lado"

    min_delta = env_float("AUTO_TRADE_REPLACE_MIN_CONFIDENCE_DELTA", 0.04)
    active_confidence = float(active.get("confidence") or 0)
    if signal.confidence < active_confidence + min_delta:
        return False, "nova ordem nao supera a confianca da ordem ativa"

    expires_at = parse_datetime(active.get("expiresAt"))
    if expires_at:
        remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
        grace = env_int("AUTO_TRADE_REPLACE_GRACE_SECONDS", 45)
        if remaining > grace:
            return False, "ordem ativa ainda com tempo util"

    return True, "substituicao por sinal mais forte"


def daily_order_limit_reached(state: dict[str, object]) -> bool:
    limit = env_int("AUTO_TRADE_MAX_ORDERS_PER_DAY", 3)
    if limit <= 0:
        return False
    today = local_execution_day()
    if state.get("orderDay") != today:
        return False
    return int(state.get("ordersToday") or 0) >= limit


def increment_daily_count(state: dict[str, object], now: datetime) -> None:
    today = local_execution_day()
    count = int(state.get("ordersToday") or 0)
    if state.get("orderDay") != today:
        count = 0
    state["orderDay"] = today
    state["ordersToday"] = count + 1


def read_execution_state(state_path: Path) -> dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_execution_state(state_path: Path, payload: dict[str, object]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def env_int(name: str, default: int) -> int:
    raw = normalized_env(name)
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = normalized_env(name).replace(",", ".")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = normalized_env(name).lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "sim", "on"}


def normalized_env(name: str) -> str:
    return str(os.getenv(name, "")).strip().strip('"').strip("'")


def local_execution_day() -> str:
    return datetime.now(get_market_timezone()).date().isoformat()
