from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import atr, rsi, sma, macd, ema


# =============================================================================
# 1. PROTECAO MAXIMA DE DRAWDOWN
# =============================================================================

@dataclass
class DrawdownState:
    daily_pnl: float = 0.0
    daily_pnl_limit: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    last_reset_date: str = ""
    is_blocked: bool = False
    block_reason: str = ""
    total_trades_today: int = 0
    winning_trades_today: int = 0


def load_drawdown_state(state_path: Path) -> DrawdownState:
    if not state_path.exists():
        return DrawdownState()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return DrawdownState(
            daily_pnl=float(data.get("daily_pnl", 0)),
            daily_pnl_limit=float(data.get("daily_pnl_limit", 0)),
            consecutive_losses=int(data.get("consecutive_losses", 0)),
            max_consecutive_losses=int(data.get("max_consecutive_losses", 0)),
            last_reset_date=str(data.get("last_reset_date", "")),
            is_blocked=bool(data.get("is_blocked", False)),
            block_reason=str(data.get("block_reason", "")),
            total_trades_today=int(data.get("total_trades_today", 0)),
            winning_trades_today=int(data.get("winning_trades_today", 0)),
        )
    except (json.JSONDecodeError, ValueError):
        return DrawdownState()


def save_drawdown_state(state_path: Path, state: DrawdownState) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "daily_pnl": state.daily_pnl,
        "daily_pnl_limit": state.daily_pnl_limit,
        "consecutive_losses": state.consecutive_losses,
        "max_consecutive_losses": state.max_consecutive_losses,
        "last_reset_date": state.last_reset_date,
        "is_blocked": state.is_blocked,
        "block_reason": state.block_reason,
        "total_trades_today": state.total_trades_today,
        "winning_trades_today": state.winning_trades_today,
    }, indent=2), encoding="utf-8")


def max_drawdown_protection(state_path: Path, current_pnl: float = 0.0) -> tuple[bool, str]:
    state = load_drawdown_state(state_path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if state.last_reset_date != today:
        state.daily_pnl = 0.0
        state.consecutive_losses = 0
        state.is_blocked = False
        state.block_reason = ""
        state.total_trades_today = 0
        state.winning_trades_today = 0
        state.last_reset_date = today

    state.daily_pnl += current_pnl

    max_daily_loss_pips = _env_float("DRAWDOWN_MAX_DAILY_LOSS_PIPS", 30.0)
    if state.daily_pnl <= -max_daily_loss_pips:
        state.is_blocked = True
        state.block_reason = f"perda diaria maxima atingida ({state.daily_pnl:.1f} pips)"
        save_drawdown_state(state_path, state)
        return True, state.block_reason

    max_consecutive = _env_int("DRAWDOWN_MAX_CONSECUTIVE_LOSSES", 3)
    if state.consecutive_losses >= max_consecutive:
        state.is_blocked = True
        state.block_reason = f"{state.consecutive_losses} losses consecutivos"
        save_drawdown_state(state_path, state)
        return True, state.block_reason

    cooldown_minutes = _env_int("DRAWDOWN_COOLDOWN_MINUTES", 30)
    if state.consecutive_losses > 0 and cooldown_minutes > 0:
        state.is_blocked = True
        state.block_reason = f"cooldown apos {state.consecutive_losses} loss(es): {cooldown_minutes} min"
        save_drawdown_state(state_path, state)
        return True, state.block_reason

    if state.is_blocked and not state.block_reason:
        state.is_blocked = False
        save_drawdown_state(state_path, state)

    save_drawdown_state(state_path, state)
    return False, "sem restricao de drawdown"


def record_trade_result(state_path: Path, pnl_pips: float) -> None:
    state = load_drawdown_state(state_path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.last_reset_date != today:
        state.daily_pnl = 0.0
        state.consecutive_losses = 0
        state.total_trades_today = 0
        state.winning_trades_today = 0
        state.last_reset_date = today
    state.daily_pnl += pnl_pips
    state.total_trades_today += 1
    if pnl_pips >= 0:
        state.winning_trades_today += 1
        state.consecutive_losses = 0
    else:
        state.consecutive_losses += 1
        state.max_consecutive_losses = max(state.max_consecutive_losses, state.consecutive_losses)
    save_drawdown_state(state_path, state)


def reset_drawdown_block(state_path: Path) -> None:
    state = load_drawdown_state(state_path)
    state.is_blocked = False
    state.block_reason = ""
    state.consecutive_losses = 0
    save_drawdown_state(state_path, state)


# =============================================================================
# 2. POSITION SIZING DINAMICO
# =============================================================================

def calculate_dynamic_lot(
    balance: float,
    risk_percent: float,
    entry: float,
    stop_loss: float,
    symbol: str = "EURUSD",
    min_lot: float = 0.01,
    max_lot: float = 1.0,
) -> float:
    if balance <= 0 or risk_percent <= 0 or entry <= 0 or stop_loss <= 0:
        return min_lot

    risk_amount = balance * (risk_percent / 100)
    stop_distance_pips = abs(entry - stop_loss) * _pip_multiplier(symbol)
    if stop_distance_pips <= 0:
        return min_lot

    pip_value = _pip_value(symbol)
    if pip_value <= 0:
        return min_lot

    lot = risk_amount / (stop_distance_pips * pip_value * 10)
    lot = max(min_lot, min(round(lot, 2), max_lot))
    return lot


def _pip_multiplier(symbol: str) -> float:
    return 10000.0 if "JPY" not in symbol.upper() else 100.0


def _pip_value(symbol: str) -> float:
    return 10.0 if "JPY" not in symbol.upper() else 0.09


def get_optimal_lot(
    balance: float,
    entry: float,
    stop_loss: float,
    symbol: str = "EURUSD",
) -> float:
    risk_percent = _env_float("POSITION_RISK_PERCENT", 1.0)
    max_daily_risk = _env_float("POSITION_MAX_DAILY_RISK_PERCENT", 3.0)
    return calculate_dynamic_lot(balance, risk_percent, entry, stop_loss, symbol)


# =============================================================================
# 3. DIVERGENCIA RSI/MACD
# =============================================================================

def detect_divergence(
    candles: list[Candle],
    side: str,
    lookback: int = 20,
) -> tuple[bool, str]:
    if len(candles) < lookback:
        return False, "dados insuficientes para divergencia"

    recent = candles[-lookback:]
    closes = [c.close for c in recent]
    rsi_values = _calculate_rsi_series(closes, 14)

    if len(rsi_values) < 10 or len(closes) < 10:
        return False, "dados insuficientes"

    if side == "BUY":
        price_lows = [min(closes[i], closes[i+1], closes[i+2]) for i in range(len(closes)-3)]
        rsi_lows = [min(rsi_values[i], rsi_values[i+1], rsi_values[i+2]) for i in range(len(rsi_values)-3)]

        if len(price_lows) >= 3 and len(rsi_lows) >= 3:
            if price_lows[-1] < price_lows[-3] and rsi_lows[-1] > rsi_lows[-3]:
                return True, "divergencia bullish RSI"
    elif side == "SELL":
        price_highs = [max(closes[i], closes[i+1], closes[i+2]) for i in range(len(closes)-3)]
        rsi_highs = [max(rsi_values[i], rsi_values[i+1], rsi_values[i+2]) for i in range(len(rsi_values)-3)]

        if len(price_highs) >= 3 and len(rsi_highs) >= 3:
            if price_highs[-1] > price_highs[-3] and rsi_highs[-1] < rsi_highs[-3]:
                return True, "divergencia bearish RSI"

    macd_values = _calculate_macd_series(closes)
    if len(macd_values) >= 6:
        if side == "BUY":
            price_low_idx = _find_local_min(closes[-10:])
            macd_low_idx = _find_local_min(macd_values[-10:])
            if price_low_idx is not None and macd_low_idx is not None:
                if price_low_idx > macd_low_idx:
                    return True, "divergencia bullish MACD"
        elif side == "SELL":
            price_high_idx = _find_local_max(closes[-10:])
            macd_high_idx = _find_local_max(macd_values[-10:])
            if price_high_idx is not None and macd_high_idx is not None:
                if price_high_idx > macd_high_idx:
                    return True, "divergencia bearish MACD"

    return False, "sem divergencia"


def _calculate_rsi_series(values: list[float], period: int = 14) -> list[float]:
    if len(values) < period + 1:
        return []
    rsi_values = []
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        if change >= 0:
            gains += change
        else:
            losses += abs(change)
    if losses == 0:
        rsi_values.append(100.0)
    else:
        rs = gains / losses
        rsi_values.append(100 - (100 / (1 + rs)))

    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        if change >= 0:
            gains = (gains * (period - 1) + change) / period
            losses = (losses * (period - 1)) / period
        else:
            gains = (gains * (period - 1)) / period
            losses = (losses * (period - 1) + abs(change)) / period
        if losses == 0:
            rsi_values.append(100.0)
        else:
            rs = gains / losses
            rsi_values.append(100 - (100 / (1 + rs)))
    return rsi_values


def _calculate_macd_series(values: list[float]) -> list[float]:
    if len(values) < 26:
        return []
    fast_ema = values[0]
    slow_ema = sum(values[:26]) / 26
    macd_values = []
    fast_mult = 2 / 13
    slow_mult = 2 / 27
    for i in range(1, len(values)):
        fast_ema = (values[i] - fast_ema) * fast_mult + fast_ema
        if i >= 25:
            slow_ema = (values[i] - slow_ema) * slow_mult + slow_ema
            macd_values.append(fast_ema - slow_ema)
    return macd_values


def _find_local_min(values: list[float]) -> int | None:
    if len(values) < 3:
        return None
    min_idx = 0
    for i in range(1, len(values) - 1):
        if values[i] < values[i-1] and values[i] < values[i+1]:
            if values[i] < values[min_idx]:
                min_idx = i
    return min_idx


def _find_local_max(values: list[float]) -> int | None:
    if len(values) < 3:
        return None
    max_idx = 0
    for i in range(1, len(values) - 1):
        if values[i] > values[i-1] and values[i] > values[i+1]:
            if values[i] > values[max_idx]:
                max_idx = i
    return max_idx


# =============================================================================
# 4. FILTRO DE SPREAD DINAMICO
# =============================================================================

def dynamic_spread_filter(current_spread_pips: float, symbol: str = "EURUSD") -> tuple[bool, str]:
    session = _current_session()
    base_spread = _env_float("SPREAD_BASE_PIPS", 1.2)

    session_multipliers = {
        "londres": 1.0,
        "nova_york": 1.0,
        "asia": 1.5,
        "fechado": 2.0,
    }
    multiplier = session_multipliers.get(session, 1.2)
    max_spread = base_spread * multiplier

    if current_spread_pips > max_spread:
        return False, f"spread {current_spread_pips:.2f} acima do maximo {max_spread:.2f} para sessao {session}"

    return True, f"spread ok para sessao {session}"


def _current_session() -> str:
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour < 16:
        return "londres"
    elif 13 <= hour < 21:
        return "nova_york"
    elif 0 <= hour < 3:
        return "asia"
    return "fechado"


# =============================================================================
# 5. RECONHECIMENTO DE PADROES DE CANDLESTICK
# =============================================================================

@dataclass
class CandlestickPattern:
    name: str
    signal: str  # "BUY", "SELL", "NEUTRAL"
    confidence_boost: float
    description: str


def detect_candlestick_patterns(candles: list[Candle]) -> list[CandlestickPattern]:
    if len(candles) < 5:
        return []

    patterns = []
    last = candles[-1]
    prev = candles[-2]
    prev2 = candles[-3]

    body = abs(last.close - last.open)
    total_range = max(last.high - last.low, 0.00001)
    body_ratio = body / total_range

    prev_body = abs(prev.close - prev.open)
    prev_range = max(prev.high - prev.low, 0.00001)
    prev_body_ratio = prev_body / prev_range

    if (last.close > last.open and prev.close < prev.open and
        last.open <= prev.close and last.close >= prev.open and
        body > prev_body * 1.2):
        patterns.append(CandlestickPattern(
            name="engolfo_comprador",
            signal="BUY",
            confidence_boost=0.06,
            description="engolfo de alta"
        ))

    if (last.close < last.open and prev.close > prev.open and
        last.open >= prev.close and last.close <= prev.open and
        body > prev_body * 1.2):
        patterns.append(CandlestickPattern(
            name="engolfo_vendedor",
            signal="SELL",
            confidence_boost=0.06,
            description="engolfo de baixa"
        ))

    lower_shadow = min(last.close, last.open) - last.low
    upper_shadow = last.high - max(last.close, last.open)

    if lower_shadow > body * 2 and upper_shadow < body * 0.3 and body_ratio < 0.3:
        patterns.append(CandlestickPattern(
            name="martelo",
            signal="BUY",
            confidence_boost=0.04,
            description="martelo"
        ))

    if upper_shadow > body * 2 and lower_shadow < body * 0.3 and body_ratio < 0.3:
        patterns.append(CandlestickPattern(
            name="estrela_cadente",
            signal="SELL",
            confidence_boost=0.04,
            description="estrela cadente"
        ))

    if body < total_range * 0.1:
        if upper_shadow > lower_shadow * 2:
            patterns.append(CandlestickPattern(
                name="doji_grave",
                signal="SELL",
                confidence_boost=0.03,
                description="doji com sombra superior"
            ))
        elif lower_shadow > upper_shadow * 2:
            patterns.append(CandlestickPattern(
                name="doji_dragao",
                signal="BUY",
                confidence_boost=0.03,
                description="doji com sombra inferior"
            ))

    if (prev2.close > prev2.open and prev.close > prev.open and last.close > last.open and
        all(c.close > c.open for c in candles[-3:])):
        patterns.append(CandlestickPattern(
            name="tres_soldados",
            signal="BUY",
            confidence_boost=0.05,
            description="tres soldados brancos"
        ))

    if (prev2.close < prev2.open and prev.close < prev.open and last.close < last.open and
        all(c.close < c.open for c in candles[-3:])):
        patterns.append(CandlestickPattern(
            name="tres_corvos",
            signal="SELL",
            confidence_boost=0.05,
            description="tres corvos negros"
        ))

    return patterns


def candlestick_boost(candles: list[Candle], signal_side: str) -> tuple[float, list[str]]:
    patterns = detect_candlestick_patterns(candles)
    matching = [p for p in patterns if p.signal == signal_side]
    if not matching:
        return 0.0, []
    total_boost = sum(p.confidence_boost for p in matching)
    total_boost = min(total_boost, 0.10)
    descriptions = [p.description for p in matching]
    return total_boost, descriptions


# =============================================================================
# 6. SAIDA INTELIGENTE
# =============================================================================

@dataclass
class ExitDecision:
    should_exit: bool
    exit_type: str  # "FULL", "PARTIAL", "TRAILING", "TIME", "NONE"
    exit_pct: float  # 0-100 percent to close
    reason: str
    new_stop_loss: float | None = None


def smart_exit_check(
    entry_price: float,
    current_price: float,
    stop_loss: float,
    take_profit: float,
    side: str,
    candles: list[Candle],
    entry_time: datetime | None = None,
    pnl_pips: float = 0.0,
) -> ExitDecision:
    if entry_price <= 0 or current_price <= 0:
        return ExitDecision(False, "NONE", 0, "precos invalidos")

    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return ExitDecision(False, "NONE", 0, "risco zero")

    if side == "BUY":
        profit_distance = current_price - entry_price
    else:
        profit_distance = entry_price - current_price

    profit_ratio = profit_distance / risk if risk > 0 else 0

    be_trigger = _env_float("EXIT_BE_TRIGGER_RATIO", 0.5)
    if profit_ratio >= be_trigger:
        new_stop = entry_price + (entry_price - stop_loss) * 0.1 if side == "BUY" else entry_price - (stop_loss - entry_price) * 0.1
        if side == "BUY" and new_stop > stop_loss:
            return ExitDecision(False, "TRAILING", 0, "mover para breakeven", new_stop)
        elif side == "SELL" and new_stop < stop_loss:
            return ExitDecision(False, "TRAILING", 0, "mover para breakeven", new_stop)

    trailing_trigger = _env_float("EXIT_TRAILING_TRIGGER_RATIO", 1.0)
    trailing_step = _env_float("EXIT_TRAILING_STEP_RATIO", 0.3)
    if profit_ratio >= trailing_trigger:
        if side == "BUY":
            new_stop = current_price - risk * trailing_step
            if new_stop > stop_loss:
                return ExitDecision(False, "TRAILING", 0, f"trailing stop {profit_ratio:.1f}R", new_stop)
        else:
            new_stop = current_price + risk * trailing_step
            if new_stop < stop_loss:
                return ExitDecision(False, "TRAILING", 0, f"trailing stop {profit_ratio:.1f}R", new_stop)

    partial_trigger = _env_float("EXIT_PARTIAL_TRIGGER_RATIO", 0.8)
    partial_pct = _env_float("EXIT_PARTIAL_PERCENT", 50.0)
    if profit_ratio >= partial_trigger and pnl_pips > 0:
        return ExitDecision(True, "PARTIAL", partial_pct, f"lucro parcial {profit_ratio:.1f}R")

    tp_ratio = _env_float("EXIT_TP_RATIO", 1.8)
    if profit_ratio >= tp_ratio:
        return ExitDecision(True, "FULL", 100, f"take profit atingido {profit_ratio:.1f}R")

    if entry_time:
        max_candles = _env_int("EXIT_MAX_CANDLES", 50)
        if len(candles) > max_candles:
            if profit_ratio < 0.3:
                return ExitDecision(True, "FULL", 100, f"timeout {max_candles} candles sem progresso")

    return ExitDecision(False, "NONE", 0, "manter posicao")


# =============================================================================
# 7. CORRELACAO ENTRE PARES
# =============================================================================

@dataclass
class CorrelationCache:
    correlations: dict[str, float] = field(default_factory=dict)
    last_update: str = ""


def check_correlation_risk(
    symbol1: str,
    symbol2: str,
    candles1: list[Candle],
    candles2: list[Candle],
    max_correlation: float = 0.85,
) -> tuple[bool, str]:
    if len(candles1) < 20 or len(candles2) < 20:
        return True, "dados insuficientes para correlacao"

    closes1 = [c.close for c in candles1[-20:]]
    closes2 = [c.close for c in candles2[-20:]]

    returns1 = [(closes1[i] - closes1[i-1]) / closes1[i-1] for i in range(1, len(closes1))]
    returns2 = [(closes2[i] - closes2[i-1]) / closes2[i-1] for i in range(1, len(closes2))]

    if len(returns1) < 5 or len(returns2) < 5:
        return True, "dados insuficientes"

    mean1 = sum(returns1) / len(returns1)
    mean2 = sum(returns2) / len(returns2)

    var1 = sum((r - mean1) ** 2 for r in returns1) / len(returns1)
    var2 = sum((r - mean2) ** 2 for r in returns2) / len(returns2)

    if var1 == 0 or var2 == 0:
        return True, "variancia zero"

    cov = sum((returns1[i] - mean1) * (returns2[i] - mean2) for i in range(len(returns1))) / len(returns1)
    correlation = cov / (var1 ** 0.5 * var2 ** 0.5)

    if abs(correlation) > max_correlation:
        return False, f"correlacao alta {correlation:.2f} entre {symbol1} e {symbol2}"

    return True, f"correlacao {correlation:.2f} aceitavel"


# =============================================================================
# 8. METRICAS DE PERFORMANCE EM TEMPO REAL
# =============================================================================

@dataclass
class PerformanceMetrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_consecutive_losses: int = 0
    current_consecutive_losses: int = 0
    total_pnl_pips: float = 0.0
    max_drawdown_pips: float = 0.0
    sharpe_ratio: float = 0.0
    strategy_breakdown: dict[str, dict] = field(default_factory=dict)
    last_updated: str = ""


def load_performance_metrics(state_path: Path) -> PerformanceMetrics:
    if not state_path.exists():
        return PerformanceMetrics()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return PerformanceMetrics(
            total_trades=int(data.get("total_trades", 0)),
            winning_trades=int(data.get("winning_trades", 0)),
            losing_trades=int(data.get("losing_trades", 0)),
            win_rate=float(data.get("win_rate", 0)),
            avg_win=float(data.get("avg_win", 0)),
            avg_loss=float(data.get("avg_loss", 0)),
            profit_factor=float(data.get("profit_factor", 0)),
            max_consecutive_losses=int(data.get("max_consecutive_losses", 0)),
            current_consecutive_losses=int(data.get("current_consecutive_losses", 0)),
            total_pnl_pips=float(data.get("total_pnl_pips", 0)),
            max_drawdown_pips=float(data.get("max_drawdown_pips", 0)),
            sharpe_ratio=float(data.get("sharpe_ratio", 0)),
            strategy_breakdown=data.get("strategy_breakdown", {}),
            last_updated=str(data.get("last_updated", "")),
        )
    except (json.JSONDecodeError, ValueError):
        return PerformanceMetrics()


def save_performance_metrics(state_path: Path, metrics: PerformanceMetrics) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "total_trades": metrics.total_trades,
        "winning_trades": metrics.winning_trades,
        "losing_trades": metrics.losing_trades,
        "win_rate": round(metrics.win_rate, 2),
        "avg_win": round(metrics.avg_win, 2),
        "avg_loss": round(metrics.avg_loss, 2),
        "profit_factor": round(metrics.profit_factor, 2),
        "max_consecutive_losses": metrics.max_consecutive_losses,
        "current_consecutive_losses": metrics.current_consecutive_losses,
        "total_pnl_pips": round(metrics.total_pnl_pips, 2),
        "max_drawdown_pips": round(metrics.max_drawdown_pips, 2),
        "sharpe_ratio": round(metrics.sharpe_ratio, 2),
        "strategy_breakdown": metrics.strategy_breakdown,
        "last_updated": metrics.last_updated,
    }, indent=2), encoding="utf-8")


def record_trade_performance(
    state_path: Path,
    pnl_pips: float,
    strategy_style: str = "",
    symbol: str = "EURUSD",
) -> PerformanceMetrics:
    metrics = load_performance_metrics(state_path)
    metrics.total_trades += 1
    metrics.total_pnl_pips += pnl_pips
    metrics.last_updated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if pnl_pips >= 0:
        metrics.winning_trades += 1
        metrics.current_consecutive_losses = 0
        total_wins = metrics.avg_win * (metrics.winning_trades - 1)
        metrics.avg_win = (total_wins + pnl_pips) / metrics.winning_trades
    else:
        metrics.losing_trades += 1
        metrics.current_consecutive_losses += 1
        metrics.max_consecutive_losses = max(
            metrics.max_consecutive_losses,
            metrics.current_consecutive_losses
        )
        total_losses = abs(metrics.avg_loss) * (metrics.losing_trades - 1)
        metrics.avg_loss = -((total_losses + abs(pnl_pips)) / metrics.losing_trades)

    metrics.win_rate = (metrics.winning_trades / metrics.total_trades * 100) if metrics.total_trades > 0 else 0

    total_wins_pips = metrics.avg_win * metrics.winning_trades
    total_losses_pips = abs(metrics.avg_loss) * metrics.losing_trades
    metrics.profit_factor = (total_wins_pips / total_losses_pips) if total_losses_pips > 0 else 999.0

    if metrics.total_pnl_pips < -metrics.max_drawdown_pips:
        metrics.max_drawdown_pips = abs(metrics.total_pnl_pips)

    if strategy_style:
        if strategy_style not in metrics.strategy_breakdown:
            metrics.strategy_breakdown[strategy_style] = {
                "trades": 0, "wins": 0, "total_pnl": 0
            }
        strat = metrics.strategy_breakdown[strategy_style]
        strat["trades"] = int(strat.get("trades", 0)) + 1
        strat["total_pnl"] = float(strat.get("total_pnl", 0)) + pnl_pips
        if pnl_pips >= 0:
            strat["wins"] = int(strat.get("wins", 0)) + 1

    save_performance_metrics(state_path, metrics)
    return metrics


def get_performance_summary(state_path: Path) -> dict[str, object]:
    metrics = load_performance_metrics(state_path)
    return {
        "totalTrades": metrics.total_trades,
        "winRate": round(metrics.win_rate, 1),
        "profitFactor": round(metrics.profit_factor, 2),
        "avgWin": round(metrics.avg_win, 1),
        "avgLoss": round(metrics.avg_loss, 1),
        "totalPnlPips": round(metrics.total_pnl_pips, 1),
        "maxDrawdownPips": round(metrics.max_drawdown_pips, 1),
        "maxConsecutiveLosses": metrics.max_consecutive_losses,
        "currentConsecutiveLosses": metrics.current_consecutive_losses,
        "strategyBreakdown": metrics.strategy_breakdown,
        "lastUpdated": metrics.last_updated,
    }


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
