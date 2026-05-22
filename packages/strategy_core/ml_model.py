from __future__ import annotations

import math
from dataclasses import dataclass

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import atr, rsi, sma


FEATURE_NAMES = [
    "trend",
    "momentum",
    "volatility",
    "body_strength",
    "last_return",
    "range_expansion",
]


@dataclass(frozen=True)
class TrainingSample:
    features: list[float]
    label: int


@dataclass(frozen=True)
class MlModel:
    trained: bool
    samples: int
    positive_samples: int
    negative_samples: int
    train_accuracy: float
    positive_centroid: list[float]
    negative_centroid: list[float]

    def score(self, features: list[float]) -> float:
        if not self.trained:
            return 0.5
        positive_distance = euclidean(features, self.positive_centroid)
        negative_distance = euclidean(features, self.negative_centroid)
        total = positive_distance + negative_distance
        if total == 0:
            return 0.5
        return round(max(0.05, min(0.95, negative_distance / total)), 2)

    def to_dict(self) -> dict[str, object]:
        return {
            "trained": self.trained,
            "samples": self.samples,
            "positiveSamples": self.positive_samples,
            "negativeSamples": self.negative_samples,
            "trainAccuracy": round(self.train_accuracy, 2),
            "features": FEATURE_NAMES,
        }


def train_signal_quality_model(candles: list[Candle]) -> MlModel:
    samples = build_training_samples(candles)
    positive = [sample.features for sample in samples if sample.label == 1]
    negative = [sample.features for sample in samples if sample.label == 0]

    if len(positive) < 3 or len(negative) < 3:
        return MlModel(False, len(samples), len(positive), len(negative), 0.0, [], [])

    model = MlModel(
        trained=True,
        samples=len(samples),
        positive_samples=len(positive),
        negative_samples=len(negative),
        train_accuracy=0.0,
        positive_centroid=centroid(positive),
        negative_centroid=centroid(negative),
    )
    correct = sum(1 for sample in samples if int(model.score(sample.features) >= 0.5) == sample.label)
    return MlModel(
        trained=True,
        samples=model.samples,
        positive_samples=model.positive_samples,
        negative_samples=model.negative_samples,
        train_accuracy=correct / len(samples) if samples else 0,
        positive_centroid=model.positive_centroid,
        negative_centroid=model.negative_centroid,
    )


def build_training_samples(candles: list[Candle], lookahead: int = 6) -> list[TrainingSample]:
    samples: list[TrainingSample] = []
    for index in range(20, len(candles) - lookahead):
        features = extract_features(candles[: index + 1])
        if features is None:
            continue
        label = label_future_move(candles, index, lookahead)
        samples.append(TrainingSample(features=features, label=label))
    return samples


def extract_features(candles: list[Candle]) -> list[float] | None:
    closes = [candle.close for candle in candles]
    fast = sma(closes, 5)
    slow = sma(closes, 20)
    volatility = atr(candles, 14)
    momentum = rsi(closes, 14)
    average_range = average_recent_range(candles, 10)

    if fast is None or slow is None or volatility is None or momentum is None or average_range is None:
        return None

    last = candles[-1]
    previous = candles[-2]
    candle_range = max(last.high - last.low, 0.00001)
    trend = clamp((fast - slow) / max(volatility, 0.00001), -2, 2) / 2
    normalized_momentum = (momentum - 50) / 50
    normalized_volatility = clamp(volatility / max(last.close, 0.00001) * 1000, 0, 2) / 2
    body_strength = clamp((last.close - last.open) / candle_range, -1, 1)
    last_return = clamp((last.close - previous.close) / max(volatility, 0.00001), -2, 2) / 2
    range_expansion = clamp(candle_range / max(average_range, 0.00001), 0, 3) / 3
    return [
        round(trend, 4),
        round(normalized_momentum, 4),
        round(normalized_volatility, 4),
        round(body_strength, 4),
        round(last_return, 4),
        round(range_expansion, 4),
    ]


def label_future_move(candles: list[Candle], index: int, lookahead: int) -> int:
    current = candles[index]
    future = candles[index + 1 : index + 1 + lookahead]
    volatility = atr(candles[: index + 1], 14) or max(current.high - current.low, 0.00001)
    target = current.close + volatility * 1.2
    stop = current.close - volatility * 0.9

    for candle in future:
        if candle.low <= stop:
            return 0
        if candle.high >= target:
            return 1
    return int(future[-1].close > current.close)


def average_recent_range(candles: list[Candle], period: int) -> float | None:
    if len(candles) < period:
        return None
    ranges = [candle.high - candle.low for candle in candles[-period:]]
    return sum(ranges) / len(ranges)


def centroid(rows: list[list[float]]) -> list[float]:
    return [sum(row[index] for row in rows) / len(rows) for index in range(len(rows[0]))]


def euclidean(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
