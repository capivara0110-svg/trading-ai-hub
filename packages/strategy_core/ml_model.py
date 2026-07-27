from __future__ import annotations

import json
import math
import heapq
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import atr, rsi, sma


FEATURE_NAMES = [
    "trend",
    "momentum",
    "volatility",
    "body_strength",
    "last_return",
    "range_expansion",
    "distance_fast",
    "distance_slow",
    "momentum_slope",
    "upper_wick",
    "lower_wick",
]
MODEL_VERSION = "knn-centroid-v2-bounded"
DEFAULT_FREEZE_AT = "2026-07-13T23:59:59Z"
CACHE_TTL_SECONDS = 60
MODEL_CACHE_DIR = Path(os.getenv("ML_MODEL_CACHE_DIR", str(Path(__file__).resolve().parents[2] / "data" / "uploads" / "models")))

_ml_cache: dict[str, tuple[float, MlModel]] = {}


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
    training_rows: list[TrainingSample]

    def score(self, features: list[float]) -> float:
        if not self.trained:
            return 0.5
        positive_distance = euclidean(features, self.positive_centroid)
        negative_distance = euclidean(features, self.negative_centroid)
        total = positive_distance + negative_distance
        if total == 0:
            centroid_score = 0.5
        else:
            centroid_score = negative_distance / total
        neighbor_score = knn_score(features, self.training_rows)
        blended = centroid_score * 0.55 + neighbor_score * 0.45
        return round(max(0.05, min(0.95, blended)), 2)

    def to_dict(self) -> dict[str, object]:
        return {
            "trained": self.trained,
            "samples": self.samples,
            "positiveSamples": self.positive_samples,
            "negativeSamples": self.negative_samples,
            "trainAccuracy": round(self.train_accuracy, 2),
            "features": FEATURE_NAMES,
            "modelVersion": MODEL_VERSION,
            "referenceRows": len(self.training_rows),
            "freezeAt": os.getenv("ML_FREEZE_AT_TIME") or DEFAULT_FREEZE_AT,
        }


def train_signal_quality_model(candles: list[Candle], respect_freeze: bool = True) -> MlModel:
    cache_key = _cache_key(candles)
    cached = _cached_model(cache_key)
    if cached:
        return cached

    if respect_freeze:
        candles = frozen_training_candles(candles)
    samples = build_training_samples(candles)
    positive = [sample.features for sample in samples if sample.label == 1]
    negative = [sample.features for sample in samples if sample.label == 0]

    if len(positive) < 3 or len(negative) < 3:
        model = MlModel(False, len(samples), len(positive), len(negative), 0.0, [], [], [])
        _set_cached(cache_key, model)
        return model

    model = MlModel(
        trained=True,
        samples=len(samples),
        positive_samples=len(positive),
        negative_samples=len(negative),
        train_accuracy=0.0,
        positive_centroid=centroid(positive),
        negative_centroid=centroid(negative),
        training_rows=representative_rows(samples),
    )
    model = MlModel(
        trained=True,
        samples=model.samples,
        positive_samples=model.positive_samples,
        negative_samples=model.negative_samples,
        train_accuracy=validation_accuracy(samples),
        positive_centroid=model.positive_centroid,
        negative_centroid=model.negative_centroid,
        training_rows=model.training_rows,
    )
    _set_cached(cache_key, model)
    return model


def build_training_samples(candles: list[Candle], lookahead: int = 6) -> list[TrainingSample]:
    samples: list[TrainingSample] = []
    for index in range(20, len(candles) - lookahead):
        features = extract_features(candles[max(0, index - 31) : index + 1])
        if features is None:
            continue
        label = label_future_move(candles, index, lookahead)
        samples.append(TrainingSample(features=features, label=label))
    return samples


def extract_features(candles: list[Candle]) -> list[float] | None:
    # Every current feature uses at most 21 recent candles. Keeping a small
    # bounded window makes training linear even with year-long M5 datasets.
    candles = candles[-32:]
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
    prev_momentum = rsi(closes[:-1], 14)
    candle_range = max(last.high - last.low, 0.00001)
    trend = clamp((fast - slow) / max(volatility, 0.00001), -2, 2) / 2
    normalized_momentum = (momentum - 50) / 50
    normalized_volatility = clamp(volatility / max(last.close, 0.00001) * 1000, 0, 2) / 2
    body_strength = clamp((last.close - last.open) / candle_range, -1, 1)
    last_return = clamp((last.close - previous.close) / max(volatility, 0.00001), -2, 2) / 2
    range_expansion = clamp(candle_range / max(average_range, 0.00001), 0, 3) / 3
    distance_fast = clamp((last.close - fast) / max(volatility, 0.00001), -2, 2) / 2
    distance_slow = clamp((last.close - slow) / max(volatility, 0.00001), -3, 3) / 3
    momentum_slope = clamp(((momentum - prev_momentum) if prev_momentum is not None else 0.0) / 20, -1, 1)
    upper_wick = clamp((last.high - max(last.close, last.open)) / candle_range, 0, 1)
    lower_wick = clamp((min(last.close, last.open) - last.low) / candle_range, 0, 1)
    return [
        round(trend, 4),
        round(normalized_momentum, 4),
        round(normalized_volatility, 4),
        round(body_strength, 4),
        round(last_return, 4),
        round(range_expansion, 4),
        round(distance_fast, 4),
        round(distance_slow, 4),
        round(momentum_slope, 4),
        round(upper_wick, 4),
        round(lower_wick, 4),
    ]


def label_future_move(candles: list[Candle], index: int, lookahead: int) -> int:
    current = candles[index]
    future = candles[index + 1 : index + 1 + lookahead]
    volatility = atr(candles[max(0, index - 31) : index + 1], 14) or max(current.high - current.low, 0.00001)
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


def validation_accuracy(samples: list[TrainingSample]) -> float:
    if len(samples) < 20:
        correct = sum(1 for sample in samples if sample.label == majority_label(samples))
        return correct / len(samples) if samples else 0.0

    split = max(10, int(len(samples) * 0.7))
    train = samples[:split]
    test = samples[split:]
    positive = [sample.features for sample in train if sample.label == 1]
    negative = [sample.features for sample in train if sample.label == 0]
    if len(positive) < 3 or len(negative) < 3 or not test:
        correct = sum(1 for sample in samples if sample.label == majority_label(samples))
        return correct / len(samples) if samples else 0.0

    model = MlModel(
        trained=True,
        samples=len(train),
        positive_samples=len(positive),
        negative_samples=len(negative),
        train_accuracy=0.0,
        positive_centroid=centroid(positive),
        negative_centroid=centroid(negative),
        training_rows=representative_rows(train),
    )
    correct = sum(1 for sample in test if int(model.score(sample.features) >= 0.5) == sample.label)
    return correct / len(test)


def majority_label(samples: list[TrainingSample]) -> int:
    positives = sum(sample.label for sample in samples)
    return int(positives >= (len(samples) - positives))


def euclidean(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def knn_score(features: list[float], rows: list[TrainingSample], k: int = 11) -> float:
    if not rows:
        return 0.5
    neighbor_count = max(3, min(k, len(rows)))
    neighbors = heapq.nsmallest(
        neighbor_count,
        ((euclidean(features, sample.features), sample.label) for sample in rows),
        key=lambda item: item[0],
    )
    weighted_positive = 0.0
    total_weight = 0.0
    for distance, label in neighbors:
        weight = 1 / max(distance, 0.0001)
        weighted_positive += weight * label
        total_weight += weight
    if total_weight <= 0:
        return 0.5
    return weighted_positive / total_weight


def representative_rows(rows: list[TrainingSample], limit: int = 150) -> list[TrainingSample]:
    """Keep a temporally distributed KNN reference set for bounded scoring cost."""
    if len(rows) <= limit:
        return rows
    return [rows[min(len(rows) - 1, int(index * len(rows) / limit))] for index in range(limit)]


def frozen_training_candles(candles: list[Candle]) -> list[Candle]:
    raw = str(os.getenv("ML_FREEZE_AT_TIME") or DEFAULT_FREEZE_AT).strip()
    try:
        cutoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        cutoff = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    except ValueError:
        return candles
    result = []
    for candle in candles:
        try:
            stamp = datetime.fromisoformat(candle.time.replace("Z", "+00:00"))
            stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if stamp <= cutoff:
            result.append(candle)
    return result if len(result) >= 25 else candles


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _cache_key(candles: list[Candle]) -> str:
    if not candles:
        return "empty"
    last_time = candles[-1].time
    count = len(candles)
    return f"ml-{last_time}-{count}"


def _cached_model(key: str) -> MlModel | None:
    cached = _ml_cache.get(key)
    if cached is None:
        return _load_persisted_model(key)
    stored_at, model = cached
    if time.time() - stored_at > CACHE_TTL_SECONDS:
        del _ml_cache[key]
        return None
    return model


def _set_cached(key: str, model: MlModel) -> None:
    _ml_cache[key] = (time.time(), model)
    _persist_model(key, model)
    if len(_ml_cache) > 20:
        oldest = min(_ml_cache.keys(), key=lambda k: _ml_cache[k][0])
        del _ml_cache[oldest]


def _persist_model(key: str, model: MlModel) -> None:
    try:
        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = MODEL_CACHE_DIR / f"{key}.json"
        path.write_text(json.dumps({
            "key": key,
            "trained": model.trained,
            "samples": model.samples,
            "positive_samples": model.positive_samples,
            "negative_samples": model.negative_samples,
            "train_accuracy": model.train_accuracy,
            "positive_centroid": model.positive_centroid,
            "negative_centroid": model.negative_centroid,
            "training_rows_count": len(model.training_rows),
            "training_rows": [
                {"features": s.features, "label": s.label}
                for s in model.training_rows
            ],
        }, indent=2), encoding="utf-8")
    except OSError:
        pass


def _load_persisted_model(key: str) -> MlModel | None:
    try:
        path = MODEL_CACHE_DIR / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("key") != key:
            return None
        training_rows = [
            TrainingSample(features=row["features"], label=row["label"])
            for row in data.get("training_rows", [])
        ]
        model = MlModel(
            trained=bool(data["trained"]),
            samples=int(data["samples"]),
            positive_samples=int(data["positive_samples"]),
            negative_samples=int(data["negative_samples"]),
            train_accuracy=float(data["train_accuracy"]),
            positive_centroid=data["positive_centroid"],
            negative_centroid=data["negative_centroid"],
            training_rows=training_rows,
        )
        _ml_cache[key] = (time.time(), model)
        return model
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None
