from __future__ import annotations

from dataclasses import dataclass

from packages.strategy_core.data import Candle
from packages.strategy_core.signals import detect_forex_signal


@dataclass(frozen=True)
class Trade:
    entry_time: str
    side: str
    entry: float
    exit: float
    result_pips: float
    gross_result_pips: float = 0.0
    cost_pips: float = 0.0
    exit_time: str | None = None
    exit_index: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "entryTime": self.entry_time,
            "side": self.side,
            "entry": self.entry,
            "exit": self.exit,
            "resultPips": round(self.result_pips, 1),
            "grossResultPips": round(self.gross_result_pips, 1),
            "costPips": round(self.cost_pips, 1),
            "exitTime": self.exit_time,
        }


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    total_pips: float
    win_rate: float
    max_drawdown_pips: float
    average_win_pips: float
    average_loss_pips: float
    payoff: float
    profit_factor: float
    total_cost_pips: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "trades": [trade.to_dict() for trade in self.trades],
            "totalPips": round(self.total_pips, 1),
            "winRate": round(self.win_rate, 2),
            "maxDrawdownPips": round(self.max_drawdown_pips, 1),
            "averageWinPips": round(self.average_win_pips, 1),
            "averageLossPips": round(self.average_loss_pips, 1),
            "payoff": round(self.payoff, 2),
            "profitFactor": round(self.profit_factor, 2),
            "totalTrades": len(self.trades),
            "totalCostPips": round(self.total_cost_pips, 1),
        }


@dataclass(frozen=True)
class BacktestCosts:
    spread_pips: float = 0.0
    slippage_pips: float = 0.0
    commission_pips: float = 0.0

    @property
    def round_trip_pips(self) -> float:
        return max(0.0, self.spread_pips) + max(0.0, self.slippage_pips) + max(0.0, self.commission_pips)

    def to_dict(self) -> dict[str, float]:
        return {
            "spreadPips": self.spread_pips,
            "slippagePips": self.slippage_pips,
            "commissionPips": self.commission_pips,
            "roundTripPips": self.round_trip_pips,
        }


def run_backtest(
    candles: list[Candle],
    lookahead: int = 24,
    min_confidence: float = 0.58,
    costs: BacktestCosts | None = None,
    symbol: str = "EURUSD",
) -> BacktestResult:
    trades: list[Trade] = []
    costs = costs or BacktestCosts()

    for index in range(20, len(candles) - lookahead):
        window = candles[: index + 1]
        signal = detect_forex_signal(window, lookback=1)

        if signal.side == "NO_TRADE" or signal.confidence < min_confidence:
            continue

        future = candles[index + 1 : index + 1 + lookahead]
        entry = float(signal.entry or candles[index].close)
        stop = float(signal.stop_loss or entry)
        target = float(signal.take_profit[0])
        exit_price = future[-1].close

        for candle in future:
            if signal.side == "BUY":
                if candle.low <= stop:
                    exit_price = stop
                    break
                if candle.high >= target:
                    exit_price = target
                    break
            if signal.side == "SELL":
                if candle.high >= stop:
                    exit_price = stop
                    break
                if candle.low <= target:
                    exit_price = target
                    break

        gross_result_pips = price_to_pips(exit_price - entry, symbol)
        if signal.side == "SELL":
            gross_result_pips *= -1
        result_pips = gross_result_pips - costs.round_trip_pips

        trades.append(
            Trade(
                entry_time=candles[index].time,
                side=signal.side,
                entry=round(entry, 5),
                exit=round(exit_price, 5),
                result_pips=result_pips,
                gross_result_pips=gross_result_pips,
                cost_pips=costs.round_trip_pips,
            )
        )

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


def price_to_pips(value: float, symbol: str = "EURUSD") -> float:
    return value * (100 if "JPY" in symbol.upper() else 10000)


def calculate_drawdown(trades: list[Trade]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for trade in trades:
        equity += trade.result_pips
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return max_drawdown
