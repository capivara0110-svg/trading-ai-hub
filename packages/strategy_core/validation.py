from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import Counter

from packages.strategy_core.backtest import BacktestCosts, BacktestResult, Trade, calculate_drawdown, price_to_pips
from packages.strategy_core.data import Candle
from packages.strategy_core.ml_model import MlModel, extract_features, train_signal_quality_model
from packages.strategy_core.signals import detect_best_strategy


@dataclass(frozen=True)
class ValidationResult:
    train_candles: int
    test_candles: int
    ml_threshold: float
    base: BacktestResult
    ai_filtered: BacktestResult
    model: MlModel
    base_blocked: dict[str, int] | None = None
    ai_blocked: dict[str, int] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "trainCandles": self.train_candles,
            "testCandles": self.test_candles,
            "mlThreshold": self.ml_threshold,
            "model": self.model.to_dict(),
            "base": self.base.to_dict(),
            "aiFiltered": self.ai_filtered.to_dict(),
            "blocked": {"base": self.base_blocked or {}, "aiFiltered": self.ai_blocked or {}},
            "delta": {
                "totalPips": round(self.ai_filtered.total_pips - self.base.total_pips, 1),
                "winRate": round(self.ai_filtered.win_rate - self.base.win_rate, 2),
                "drawdownPips": round(self.ai_filtered.max_drawdown_pips - self.base.max_drawdown_pips, 1),
                "trades": len(self.ai_filtered.trades) - len(self.base.trades),
            },
        }


def run_out_of_sample_validation(
    candles: list[Candle],
    train_ratio: float = 0.7,
    lookahead: int = 24,
    min_confidence: float = 0.58,
    ml_threshold: float = 0.55,
    costs: BacktestCosts | None = None,
    symbol: str = "EURUSD",
    policy: "SimulationPolicy | None" = None,
) -> ValidationResult:
    costs = costs or BacktestCosts()
    policy = policy or SimulationPolicy()
    split = max(30, min(len(candles) - lookahead - 1, int(len(candles) * train_ratio)))
    train = candles[:split]
    test_start = max(20, split - 250)
    test = candles[test_start:]
    evaluation_start = split - test_start
    model = train_signal_quality_model(train, respect_freeze=False)

    contexts = build_historical_contexts(test)
    base_trades, base_blocked = simulate_policy(
        test, model, contexts, False, lookahead, min_confidence, ml_threshold, costs, symbol, policy, evaluation_start
    )
    ai_trades, ai_blocked = simulate_policy(
        test, model, contexts, True, lookahead, min_confidence, ml_threshold, costs, symbol, policy, evaluation_start
    )

    return ValidationResult(
        train_candles=len(train),
        test_candles=len(test),
        ml_threshold=ml_threshold,
        base=summarize_trades(base_trades),
        ai_filtered=summarize_trades(ai_trades),
        model=model,
        base_blocked=base_blocked,
        ai_blocked=ai_blocked,
    )


@dataclass(frozen=True)
class SimulationPolicy:
    position_limit: int = 1
    cooldown_candles: int = 6
    max_trades_per_day: int = 4
    allowed_utc_start_hour: int = 7
    allowed_utc_end_hour: int = 20
    require_mtf_confirmation: bool = True
    block_scalper: bool = True
    min_net_reward_cost_multiple: float = 3.0
    max_atr_ratio: float = 2.2


def simulate_policy(
    candles: list[Candle],
    model: MlModel,
    contexts: list[dict[str, object]],
    use_ml: bool,
    lookahead: int,
    min_confidence: float,
    ml_threshold: float,
    costs: BacktestCosts,
    symbol: str,
    policy: SimulationPolicy,
    evaluation_start: int = 25,
) -> tuple[list[Trade], dict[str, int]]:
    trades: list[Trade] = []
    blocked: Counter[str] = Counter()
    next_available = max(25, evaluation_start)
    trades_by_day: Counter[str] = Counter()
    index = max(25, evaluation_start)
    while index < len(candles) - lookahead:
        if index < next_available:
            blocked["position_or_cooldown"] += 1
            index += 1
            continue
        window = candles[: index + 1]
        signal = detect_best_strategy(window, symbol=symbol)
        if signal.side == "NO_TRADE" or signal.confidence < min_confidence:
            blocked["no_signal_or_confidence"] += 1
            index += 1
            continue
        reason = policy_block_reason(candles, index, signal, contexts[index], costs, policy)
        if reason:
            blocked[reason] += 1
            index += 1
            continue
        day = candle_day(candles[index].time)
        if trades_by_day[day] >= policy.max_trades_per_day:
            blocked["daily_limit"] += 1
            index += 1
            continue
        if use_ml:
            features = extract_features(window)
            if not features or not model.trained:
                blocked["ml_unavailable"] += 1
                index += 1
                continue
            score = model.score(features)
            side_score = score if signal.side == "BUY" else 1 - score
            if side_score < ml_threshold:
                blocked["ml_threshold"] += 1
                index += 1
                continue
        trade = simulate_trade(
            candles, index, lookahead, signal.side, float(signal.entry), float(signal.stop_loss),
            float(signal.take_profit[0]), costs, symbol
        )
        trades.append(trade)
        trades_by_day[day] += 1
        exit_index = trade.exit_index if trade.exit_index is not None else index + lookahead
        next_available = exit_index + 1 + policy.cooldown_candles
        index += 1
    return trades, dict(blocked)


def policy_block_reason(
    candles: list[Candle], index: int, signal: object, context: dict[str, object],
    costs: BacktestCosts, policy: SimulationPolicy,
) -> str | None:
    hour = candle_hour(candles[index].time)
    if not policy.allowed_utc_start_hour <= hour < policy.allowed_utc_end_hour:
        return "outside_sessions"
    if policy.block_scalper and getattr(signal, "strategy_style", None) == "SCALPER":
        return "lateral_regime"
    mtf = [context.get("m15"), context.get("h1")]
    if policy.require_mtf_confirmation and any(direction != signal.side for direction in mtf):
        return "mtf_not_confirmed"
    entry = float(signal.entry)
    target = float(signal.take_profit[0])
    reward_pips = abs(target - entry) * 10000
    if reward_pips < costs.round_trip_pips * policy.min_net_reward_cost_multiple:
        return "reward_too_small_for_cost"
    atr_ratio = float(context.get("atrRatio") or 1.0)
    if atr_ratio > policy.max_atr_ratio:
        return "excess_volatility"
    return None


def build_historical_contexts(candles: list[Candle]) -> list[dict[str, object]]:
    m15 = higher_timeframe_directions(candles, 15)
    h1 = higher_timeframe_directions(candles, 60)
    ranges = [max(c.high - c.low, 0.00001) for c in candles]
    contexts: list[dict[str, object]] = []
    for index in range(len(candles)):
        recent = ranges[max(0, index - 19) : index + 1]
        baseline = sum(recent) / len(recent) if recent else ranges[index]
        contexts.append({"m15": m15[index], "h1": h1[index], "atrRatio": ranges[index] / max(baseline, 0.00001)})
    return contexts


def higher_timeframe_directions(candles: list[Candle], timeframe_minutes: int) -> list[str | None]:
    output: list[str | None] = []
    completed_closes: list[float] = []
    current_bucket: int | None = None
    current_close = 0.0
    direction: str | None = None
    for candle in candles:
        stamp = parse_candle_time(candle.time)
        bucket = int(stamp.timestamp()) // (timeframe_minutes * 60)
        if current_bucket is not None and bucket != current_bucket:
            completed_closes.append(current_close)
            if len(completed_closes) >= 20:
                fast = sum(completed_closes[-5:]) / 5
                slow = sum(completed_closes[-20:]) / 20
                direction = "BUY" if fast > slow else "SELL" if fast < slow else None
        current_bucket = bucket
        current_close = candle.close
        output.append(direction)
    return output


def parse_candle_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def candle_hour(value: str) -> int:
    return parse_candle_time(value).astimezone(timezone.utc).hour


def candle_day(value: str) -> str:
    return parse_candle_time(value).astimezone(timezone.utc).date().isoformat()


def simulate_trade(
    candles: list[Candle],
    index: int,
    lookahead: int,
    side: str,
    entry: float,
    stop: float,
    target: float,
    costs: BacktestCosts | None = None,
    symbol: str = "EURUSD",
) -> Trade:
    costs = costs or BacktestCosts()
    future = candles[index + 1 : index + 1 + lookahead]
    exit_price = future[-1].close
    exit_index = index + len(future)
    for offset, candle in enumerate(future, start=1):
        if side == "BUY":
            if candle.low <= stop:
                    exit_price = stop
                    exit_index = index + offset
                    break
            if candle.high >= target:
                    exit_price = target
                    exit_index = index + offset
                    break
        if side == "SELL":
            if candle.high >= stop:
                    exit_price = stop
                    exit_index = index + offset
                    break
            if candle.low <= target:
                    exit_price = target
                    exit_index = index + offset
                    break

    gross_result_pips = price_to_pips(exit_price - entry, symbol)
    if side == "SELL":
        gross_result_pips *= -1
    result_pips = gross_result_pips - costs.round_trip_pips
    return Trade(
        candles[index].time, side, round(entry, 5), round(exit_price, 5), result_pips,
        gross_result_pips, costs.round_trip_pips, candles[exit_index].time, exit_index
    )


def summarize_trades(trades: list[Trade]) -> BacktestResult:
    total = sum(trade.result_pips for trade in trades)
    wins = [trade for trade in trades if trade.result_pips > 0]
    losses = [trade for trade in trades if trade.result_pips < 0]
    win_rate = len(wins) / len(trades) if trades else 0
    average_win = sum(trade.result_pips for trade in wins) / len(wins) if wins else 0
    average_loss = abs(sum(trade.result_pips for trade in losses) / len(losses)) if losses else 0
    gross_profit = sum(trade.result_pips for trade in wins)
    gross_loss = abs(sum(trade.result_pips for trade in losses))
    return BacktestResult(
        trades=trades,
        total_pips=total,
        win_rate=win_rate,
        max_drawdown_pips=calculate_drawdown(trades),
        average_win_pips=average_win,
        average_loss_pips=average_loss,
        payoff=average_win / average_loss if average_loss else 0,
        profit_factor=gross_profit / gross_loss if gross_loss else 0,
        total_cost_pips=sum(trade.cost_pips for trade in trades),
    )
