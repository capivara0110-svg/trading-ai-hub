from __future__ import annotations

from dataclasses import dataclass

from packages.strategy_core.backtest import BacktestResult, Trade, calculate_drawdown, price_to_pips
from packages.strategy_core.data import Candle
from packages.strategy_core.ml_model import MlModel, extract_features, train_signal_quality_model
from packages.strategy_core.signals import detect_rule_signal


@dataclass(frozen=True)
class ValidationResult:
    train_candles: int
    test_candles: int
    ml_threshold: float
    base: BacktestResult
    ai_filtered: BacktestResult
    model: MlModel

    def to_dict(self) -> dict[str, object]:
        return {
            "trainCandles": self.train_candles,
            "testCandles": self.test_candles,
            "mlThreshold": self.ml_threshold,
            "model": self.model.to_dict(),
            "base": self.base.to_dict(),
            "aiFiltered": self.ai_filtered.to_dict(),
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
    lookahead: int = 6,
    min_confidence: float = 0.58,
    ml_threshold: float = 0.55,
) -> ValidationResult:
    split = max(30, min(len(candles) - lookahead - 1, int(len(candles) * train_ratio)))
    train = candles[:split]
    test_start = max(20, split - 25)
    test = candles[test_start:]
    model = train_signal_quality_model(train)

    base_trades: list[Trade] = []
    ai_trades: list[Trade] = []

    for index in range(25, len(test) - lookahead):
        window = test[: index + 1]
        signal = detect_rule_signal(window)
        if signal.side == "NO_TRADE" or signal.confidence < min_confidence:
            continue

        trade = simulate_trade(test, index, lookahead, signal.side, float(signal.entry), float(signal.stop_loss), float(signal.take_profit[0]))
        base_trades.append(trade)

        features = extract_features(window)
        if not features or not model.trained:
            continue
        score = model.score(features)
        signal_score = score if signal.side == "BUY" else 1 - score
        if signal_score >= ml_threshold:
            ai_trades.append(trade)

    return ValidationResult(
        train_candles=len(train),
        test_candles=len(test),
        ml_threshold=ml_threshold,
        base=summarize_trades(base_trades),
        ai_filtered=summarize_trades(ai_trades),
        model=model,
    )


def simulate_trade(
    candles: list[Candle],
    index: int,
    lookahead: int,
    side: str,
    entry: float,
    stop: float,
    target: float,
) -> Trade:
    future = candles[index + 1 : index + 1 + lookahead]
    exit_price = future[-1].close
    for candle in future:
        if side == "BUY":
            if candle.low <= stop:
                exit_price = stop
                break
            if candle.high >= target:
                exit_price = target
                break
        if side == "SELL":
            if candle.high >= stop:
                exit_price = stop
                break
            if candle.low <= target:
                exit_price = target
                break

    result_pips = price_to_pips(exit_price - entry)
    if side == "SELL":
        result_pips *= -1
    return Trade(candles[index].time, side, round(entry, 5), round(exit_price, 5), result_pips)


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
    )
