from __future__ import annotations

from dataclasses import dataclass

from packages.strategy_core.backtest import BacktestCosts, Trade
from packages.strategy_core.data import Candle
from packages.strategy_core.validation import run_out_of_sample_validation, summarize_trades


@dataclass(frozen=True)
class WalkForwardFold:
    number: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    base_trades: list[Trade]
    ai_trades: list[Trade]
    model_samples: int
    model_accuracy: float

    def to_dict(self) -> dict[str, object]:
        base = summarize_trades(self.base_trades)
        ai = summarize_trades(self.ai_trades)
        return {
            "fold": self.number,
            "trainPeriod": {"start": self.train_start, "end": self.train_end},
            "testPeriod": {"start": self.test_start, "end": self.test_end},
            "modelSamples": self.model_samples,
            "modelAccuracy": round(self.model_accuracy, 2),
            "base": base.to_dict(),
            "aiFiltered": ai.to_dict(),
            "deltaPips": round(ai.total_pips - base.total_pips, 1),
        }


def run_walk_forward_validation(
    candles: list[Candle],
    train_candles: int = 500,
    test_candles: int = 100,
    step_candles: int | None = None,
    min_confidence: float = 0.58,
    ml_threshold: float = 0.55,
    costs: BacktestCosts | None = None,
    symbol: str = "EURUSD",
) -> dict[str, object]:
    if train_candles < 60:
        raise ValueError("Walk-forward precisa de pelo menos 60 candles de treino")
    if test_candles < 20:
        raise ValueError("Walk-forward precisa de pelo menos 20 candles de teste")
    step = step_candles or test_candles
    if step < 1:
        raise ValueError("step_candles precisa ser positivo")
    if len(candles) < train_candles + test_candles:
        raise ValueError(
            f"Dataset insuficiente: {len(candles)} candles; necessario ao menos {train_candles + test_candles}"
        )

    costs = costs or BacktestCosts()
    folds: list[WalkForwardFold] = []
    cursor = train_candles
    while cursor + test_candles <= len(candles):
        train_start = cursor - train_candles
        window = candles[train_start : cursor + test_candles]
        result = run_out_of_sample_validation(
            window,
            train_ratio=train_candles / len(window),
            min_confidence=min_confidence,
            ml_threshold=ml_threshold,
            costs=costs,
            symbol=symbol,
        )
        folds.append(
            WalkForwardFold(
                number=len(folds) + 1,
                train_start=candles[train_start].time,
                train_end=candles[cursor - 1].time,
                test_start=candles[cursor].time,
                test_end=candles[cursor + test_candles - 1].time,
                base_trades=result.base.trades,
                ai_trades=result.ai_filtered.trades,
                model_samples=result.model.samples,
                model_accuracy=result.model.train_accuracy,
            )
        )
        cursor += step

    base = summarize_trades([trade for fold in folds for trade in fold.base_trades])
    ai = summarize_trades([trade for fold in folds for trade in fold.ai_trades])
    profitable_folds = sum(1 for fold in folds if summarize_trades(fold.ai_trades).total_pips > 0)
    return {
        "configuration": {
            "trainCandles": train_candles,
            "testCandles": test_candles,
            "stepCandles": step,
            "minConfidence": min_confidence,
            "mlThreshold": ml_threshold,
            "costs": costs.to_dict(),
        },
        "folds": [fold.to_dict() for fold in folds],
        "summary": {
            "folds": len(folds),
            "profitableAiFolds": profitable_folds,
            "profitableAiFoldRate": round(profitable_folds / len(folds), 2) if folds else 0.0,
            "base": base.to_dict(),
            "aiFiltered": ai.to_dict(),
            "deltaPips": round(ai.total_pips - base.total_pips, 1),
        },
    }
