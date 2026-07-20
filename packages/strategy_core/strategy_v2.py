"""
ESTRATEGIA V2 - TRADING AI HUB
Estrategia completamente redesenhada para maximizar win rate.
Foco: QUALIDADE > QUANTIDADE
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import (
    atr, rsi, sma, ema, macd, stoch_rsi, bollinger_bands,
    support_resistance, volume_ratio, swing_points
)
from packages.strategy_core.signals import Signal, StrategyStyle


@dataclass(frozen=True)
class StrategyConfig:
    # Entrada
    min_confidence: float = 0.85
    min_confluence: int = 2
    min_risk_reward: float = 1.5
    min_ml_score: float = 0.65

    # Filtros de sessao
    block_sunday: bool = True
    block_low_liquidity: bool = True
    preferred_sessions: tuple[str, ...] = ("londres", "nova_york")

    # Stop Loss
    min_stop_distance_atr: float = 1.2
    max_stop_distance_atr: float = 2.5

    # Take Profit
    tp1_ratio: float = 1.5
    tp2_ratio: float = 2.5

    # Gestao de risco
    max_daily_trades: int = 3
    max_daily_loss_pips: float = 20.0
    cooldown_after_loss_minutes: int = 45


def get_strategy_config() -> StrategyConfig:
    return StrategyConfig(
        min_confidence=_env_float("STRAT_V2_MIN_CONFIDENCE", 0.85),
        min_confluence=_env_int("STRAT_V2_MIN_CONFLUENCE", 2),
        min_risk_reward=_env_float("STRAT_V2_MIN_RISK_REWARD", 1.8),
        min_ml_score=_env_float("STRAT_V2_MIN_ML_SCORE", 0.65),
        max_daily_trades=_env_int("STRAT_V2_MAX_DAILY_TRADES", 3),
        max_daily_loss_pips=_env_float("STRAT_V2_MAX_DAILY_LOSS", 20.0),
    )


# =============================================================================
# DETECAO DE SESSAO
# =============================================================================

def get_current_session() -> str:
    hour = datetime.now(timezone.utc).hour
    weekday = datetime.now(timezone.utc).weekday()

    if weekday == 6:
        return "domingo"
    if weekday == 5 and hour >= 20:
        return "sabado_noite"

    if 7 <= hour < 16:
        return "londres"
    elif 13 <= hour < 21:
        return "nova_york"
    elif 0 <= hour < 3:
        return "asia"
    else:
        return "entre_sessoes"


def is_trading_allowed() -> tuple[bool, str]:
    config = get_strategy_config()
    session = get_current_session()

    if config.block_sunday and session == "domingo":
        return False, "domingo - mercado fechado"

    if session in ("sabado_noite", "entre_sessoes"):
        return False, f"sessao {session} - evitar"

    if config.block_low_liquidity and session == "asia":
        return False, "asia madrugada - baixa liquidez"

    return True, f"sessao {session} ativa"


# =============================================================================
# FILTRO DE QUALIDADE DO SETUP
# =============================================================================

def evaluate_setup_quality(candles: list[Candle], side: str) -> dict:
    if len(candles) < 30:
        return {"quality": 0, "reasons": ["dados insuficientes"]}

    closes = [c.close for c in candles]
    last = candles[-1]

    # 1. Tendencia clara
    fast_sma = sma(closes, 10)
    slow_sma = sma(closes, 30)
    trend_ok = False
    trend_strength = 0

    if fast_sma and slow_sma:
        diff = abs(fast_sma - slow_sma)
        avg_price = sum(closes[-20:]) / 20
        trend_strength = diff / avg_price * 10000  # em pips

        if side == "BUY" and fast_sma > slow_sma and trend_strength > 5:
            trend_ok = True
        elif side == "SELL" and fast_sma < slow_sma and trend_strength > 5:
            trend_ok = True

    # 2. Momentum favoravel
    momentum = rsi(closes, 14)
    momentum_ok = False
    if momentum:
        if side == "BUY" and 30 < momentum < 80:
            momentum_ok = True
        elif side == "SELL" and 20 < momentum < 70:
            momentum_ok = True

    # 3. MACD confirmando
    macd_val = macd(closes)
    macd_ok = False
    if macd_val:
        macd_line, signal_line, histogram = macd_val
        if side == "BUY" and macd_line > signal_line:
            macd_ok = True
        elif side == "SELL" and macd_line < signal_line:
            macd_ok = True

    # 4. Volume acima da media
    vol = volume_ratio(candles)
    volume_ok = vol is not None and vol > 0.8

    # 5. Candle de confirmacao
    body = abs(last.close - last.open)
    total_range = max(last.high - last.low, 0.00001)
    body_ratio = body / total_range

    candle_ok = False
    if side == "BUY" and last.close > last.open and body_ratio > 0.4:
        candle_ok = True
    elif side == "SELL" and last.close < last.open and body_ratio > 0.4:
        candle_ok = True

    # 6. Nao esta em extremo de preco
    bb_upper, bb_lower = bollinger_bands(closes, 20, 2.0)
    bb_ok = True
    if bb_upper and bb_lower:
        bb_position = (last.close - bb_lower) / (bb_upper - bb_lower)
        if side == "BUY" and bb_position > 0.92:
            bb_ok = False  # muito alto para comprar
        elif side == "SELL" and bb_position < 0.08:
            bb_ok = False  # muito baixo para vender

    # Calcular score
    score = 0
    reasons = []

    if trend_ok:
        score += 25
        reasons.append(f"tendencia forte ({trend_strength:.0f} pips)")
    if momentum_ok:
        score += 20
        reasons.append(f"momentum saudavel ({momentum:.0f})")
    if macd_ok:
        score += 20
        reasons.append("MACD confirmando")
    if volume_ok:
        score += 15
        reasons.append(f"volume acima media ({vol:.1f}x)")
    if candle_ok:
        score += 10
        reasons.append("candle de confirmacao")
    if bb_ok:
        score += 10
        reasons.append("nao em extremo de preco")

    return {
        "quality": score,
        "reasons": reasons,
        "trend_ok": trend_ok,
        "momentum_ok": momentum_ok,
        "macd_ok": macd_ok,
        "volume_ok": volume_ok,
        "candle_ok": candle_ok,
        "bb_ok": bb_ok,
    }


# =============================================================================
# CALCULO DE ENTRADA OTIMIZADA
# =============================================================================

def calculate_optimal_entry(candles: list[Candle], side: str) -> dict | None:
    if len(candles) < 20:
        return None

    last = candles[-1]
    closes = [c.close for c in candles]
    volatility = atr(candles, 14)

    if volatility is None or volatility <= 0:
        return None

    swing_high, swing_low, prev_high, prev_low = swing_points(candles, 5)

    if side == "BUY":
        # Entry: breakout acima do swing high recente ou pullback para SMA
        fast_sma = sma(closes, 10)
        if fast_sma and last.close > fast_sma:
            entry = last.close
        elif swing_high > 0:
            entry = swing_high + volatility * 0.1
        else:
            entry = last.close

        # Stop: abaixo do swing low com margem
        if swing_low > 0:
            stop = swing_low - volatility * 0.2
        else:
            stop = entry - volatility * 1.5

        # Validar stop
        stop_distance = entry - stop
        if stop_distance < volatility * 1.0:
            stop = entry - volatility * 1.2
            stop_distance = entry - stop
        elif stop_distance > volatility * 2.5:
            stop = entry - volatility * 2.0
            stop_distance = entry - stop

    else:  # SELL
        fast_sma = sma(closes, 10)
        if fast_sma and last.close < fast_sma:
            entry = last.close
        elif swing_low > 0:
            entry = swing_low - volatility * 0.1
        else:
            entry = last.close

        # Stop: acima do swing high com margem
        if swing_high > 0:
            stop = swing_high + volatility * 0.2
        else:
            stop = entry + volatility * 1.5

        # Validar stop
        stop_distance = stop - entry
        if stop_distance < volatility * 1.0:
            stop = entry + volatility * 1.2
            stop_distance = stop - entry
        elif stop_distance > volatility * 2.5:
            stop = entry + volatility * 2.0
            stop_distance = stop - entry

    # Calcular Take Profits
    config = get_strategy_config()
    risk = abs(entry - stop)

    if side == "BUY":
        tp1 = entry + risk * config.tp1_ratio
        tp2 = entry + risk * config.tp2_ratio
    else:
        tp1 = entry - risk * config.tp1_ratio
        tp2 = entry - risk * config.tp2_ratio

    # Verificar Risk/Reward
    rr = (abs(tp1 - entry) / risk) if risk > 0 else 0
    if rr < config.min_risk_reward:
        return None

    return {
        "entry": round(entry, 5),
        "stop_loss": round(stop, 5),
        "take_profit_1": round(tp1, 5),
        "take_profit_2": round(tp2, 5),
        "risk_pips": round(risk * 10000, 1),
        "reward_pips_1": round(abs(tp1 - entry) * 10000, 1),
        "reward_pips_2": round(abs(tp2 - entry) * 10000, 1),
        "risk_reward": round(rr, 2),
    }


# =============================================================================
# FUNCAO PRINCIPAL - DETECTAR SINAL V2
# =============================================================================

def detect_signal_v2(candles: list[Candle], symbol: str = "EURUSD", timeframe: str = "M5") -> Signal:
    config = get_strategy_config()

    # 1. Verificar se pode operar
    allowed, session_reason = is_trading_allowed()
    if not allowed:
        return Signal(
            symbol=symbol, timeframe=timeframe, side="NO_TRADE",
            confidence=0.0, entry=None, stop_loss=None, take_profit=[],
            reason=[session_reason]
        )

    # 2. Determinar lado
    closes = [c.close for c in candles]
    fast_sma = sma(closes, 10)
    slow_sma = sma(closes, 30)

    if not fast_sma or not slow_sma:
        return Signal(
            symbol=symbol, timeframe=timeframe, side="NO_TRADE",
            confidence=0.0, entry=None, stop_loss=None, take_profit=[],
            reason=["medias moveis indisponiveis"]
        )

    # Determinar direcao baseada na tendencia
    if fast_sma > slow_sma:
        side = "BUY"
    elif fast_sma < slow_sma:
        side = "SELL"
    else:
        return Signal(
            symbol=symbol, timeframe=timeframe, side="NO_TRADE",
            confidence=0.0, entry=None, stop_loss=None, take_profit=[],
            reason=["tendencia indefinida"]
        )

    # 3. Avaliar qualidade do setup
    quality = evaluate_setup_quality(candles, side)
    if quality["quality"] < 60:
        return Signal(
            symbol=symbol, timeframe=timeframe, side="NO_TRADE",
            confidence=0.0, entry=None, stop_loss=None, take_profit=[],
            reason=quality["reasons"] + [f"qualidade insuficiente ({quality['quality']}/100)"]
        )

    # 4. Calcular entrada otimizada
    entry_data = calculate_optimal_entry(candles, side)
    if not entry_data:
        return Signal(
            symbol=symbol, timeframe=timeframe, side="NO_TRADE",
            confidence=0.0, entry=None, stop_loss=None, take_profit=[],
            reason=["entrada invalida ou R/R insuficiente"]
        )

    # 5. Calcular confianca final
    confidence = calculate_final_confidence(quality, entry_data, candles)
    if confidence < config.min_confidence:
        return Signal(
            symbol=symbol, timeframe=timeframe, side="NO_TRADE",
            confidence=0.0, entry=None, stop_loss=None, take_profit=[],
            reason=quality["reasons"] + [f"confianca baixa ({confidence:.2f})"]
        )

    # 6. Montar sinal
    strategy_style = StrategyStyle.TREND_HUNTER.value if trend_is_strong(candles) else StrategyStyle.SCALPER.value

    return Signal(
        symbol=symbol,
        timeframe=timeframe,
        side=side,
        confidence=confidence,
        entry=entry_data["entry"],
        stop_loss=entry_data["stop_loss"],
        take_profit=[entry_data["take_profit_1"], entry_data["take_profit_2"]],
        reason=quality["reasons"] + [
            f"R/R {entry_data['risk_reward']:.1f}",
            f"risco {entry_data['risk_pips']:.0f} pips",
            f"alvo {entry_data['reward_pips_1']:.0f} pips",
            f"sessao {get_current_session()}",
        ],
        strategy_style=strategy_style,
    )


def trend_is_strong(candles: list[Candle]) -> bool:
    if len(candles) < 30:
        return False
    closes = [c.close for c in candles]
    fast = sma(closes, 10)
    slow = sma(closes, 30)
    if not fast or not slow:
        return False
    diff = abs(fast - slow)
    avg = sum(closes[-20:]) / 20
    return (diff / avg * 10000) > 10


def calculate_final_confidence(quality: dict, entry_data: dict, candles: list[Candle]) -> float:
    base = quality["quality"] / 100

    rr_bonus = min((entry_data["risk_reward"] - 1.5) * 0.1, 0.1)

    momentum = rsi([c.close for c in candles], 14)
    momentum_bonus = 0
    if momentum:
        if 45 <= momentum <= 65:
            momentum_bonus = 0.05

    session_bonus = 0.05 if get_current_session() in ("londres", "nova_york") else 0

    final = base + rr_bonus + momentum_bonus + session_bonus
    return round(min(max(final, 0.0), 0.95), 2)


# =============================================================================
# HELPERS
# =============================================================================

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip().replace(",", ".")
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default
