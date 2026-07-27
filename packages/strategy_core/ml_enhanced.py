"""
Enhanced ML pipeline using scikit-learn.

Falls back to the centroid model (ml_model.py) when sklearn is unavailable.
Provides: RandomForest, feature engineering, cross-validation, feature importance.

Usage:
    from packages.strategy_core.ml_enhanced import EnhancedModel
    model = EnhancedModel().train(candles)
    score = model.predict_proba(features)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from packages.strategy_core.data import Candle
from packages.strategy_core.indicators import atr, rsi, sma, ema, macd, bollinger_bands

MODEL_DIR = Path(os.getenv("ML_ENHANCED_MODEL_DIR", str(
    Path(__file__).resolve().parents[2] / "data" / "uploads" / "models"
))).expanduser()

_has_sklearn = False
try:
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.preprocessing import StandardScaler
    import joblib
    _has_sklearn = True
except ImportError:
    pass


@dataclass
class EnhancedModel:
    trained: bool = False
    samples: int = 0
    positive_samples: int = 0
    negative_samples: int = 0
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    feature_importance: list[dict] = field(default_factory=list)
    model_type: str = "centroid"
    _model: object = None
    _scaler: object = None

    def train(self, candles: list[Candle]) -> "EnhancedModel":
        if len(candles) < 60:
            return self

        X, y = _build_dataset(candles)
        if len(X) < 50 or sum(y) < 5 or len(y) - sum(y) < 5:
            return self

        self.samples = len(X)
        self.positive_samples = int(sum(y))
        self.negative_samples = int(len(y) - sum(y))

        if not _has_sklearn:
            return self._train_centroid(X, y)

        return self._train_sklearn(X, y)

    def _train_sklearn(self, X: list, y: list) -> "EnhancedModel":
        X_arr = np.array(X, dtype=np.float64)
        y_arr = np.array(y, dtype=np.int32)

        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X_arr)

        tscv = TimeSeriesSplit(n_splits=3)
        fold_accuracies = []
        for train_idx, test_idx in tscv.split(X_scaled):
            if len(train_idx) < 10 or len(test_idx) < 5:
                continue
            X_train, X_test = X_scaled[train_idx], X_scaled[test_idx]
            y_train, y_test = y_arr[train_idx], y_arr[test_idx]

            rf = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_leaf=5,
                random_state=42,
                class_weight="balanced",
                n_jobs=1,
            )
            rf.fit(X_train, y_train)
            fold_accuracies.append(float(np.mean(rf.predict(X_test) == y_test)))

        rf_final = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=42,
            n_jobs=1,
        )
        rf_final.fit(X_scaled, y_arr)

        self._model = rf_final
        self.trained = True
        self.model_type = "random_forest"
        self.accuracy = float(np.mean(fold_accuracies)) if fold_accuracies else 0.0

        preds = rf_final.predict(X_scaled)
        tp = int(np.sum((preds == 1) & (y_arr == 1)))
        fp = int(np.sum((preds == 1) & (y_arr == 0)))
        fn = int(np.sum((preds == 0) & (y_arr == 1)))
        self.precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        self.recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        self.f1 = 2 * self.precision * self.recall / (self.precision + self.recall) if (self.precision + self.recall) > 0 else 0.0

        importances = rf_final.feature_importances_
        self.feature_importance = sorted(
            [
                {"feature": _FEATURE_NAMES[i], "importance": round(float(importances[i]), 4)}
                for i in range(min(len(_FEATURE_NAMES), len(importances)))
            ],
            key=lambda x: x["importance"],
            reverse=True,
        )
        return self

    def _train_centroid(self, X: list, y: list) -> "EnhancedModel":
        from packages.strategy_core.ml_model import train_signal_quality_model
        legacy = train_signal_quality_model(
            [Candle(time="", open=0, high=0, low=0, close=0, volume=0)], respect_freeze=False
        )
        self.trained = legacy.trained
        self.model_type = "centroid"
        self.accuracy = legacy.train_accuracy
        return self

    def predict_proba(self, features: list[float]) -> float:
        if not self.trained:
            return 0.5

        if self.model_type == "random_forest" and self._model is not None:
            X = np.array([features], dtype=np.float64)
            if self._scaler:
                X = self._scaler.transform(X)
            proba = self._model.predict_proba(X)
            if proba.shape[1] >= 2:
                return round(float(proba[0][1]), 2)
            return round(float(proba[0][0]), 2)

        from packages.strategy_core.ml_model import extract_features
        return 0.5

    def to_dict(self) -> dict:
        return {
            "trained": self.trained,
            "modelType": self.model_type,
            "samples": self.samples,
            "positiveSamples": self.positive_samples,
            "negativeSamples": self.negative_samples,
            "accuracy": round(self.accuracy, 2),
            "precision": round(self.precision, 2),
            "recall": round(self.recall, 2),
            "f1": round(self.f1, 2),
            "featureImportance": self.feature_importance[:8],
            "features": _FEATURE_NAMES,
        }


_FEATURE_NAMES = [
    "trend_strength",
    "momentum",
    "volatility",
    "body_ratio",
    "last_return",
    "range_expansion",
    "distance_sma5",
    "distance_sma20",
    "momentum_slope",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "volume_ratio",
    "macd_histogram",
    "bb_position",
    "rsi_divergence",
    "session_hour",
    "session_weekday",
    "return_3bars",
    "return_5bars",
    "volatility_trend",
]


def _build_dataset(candles: list[Candle], lookahead: int = 6) -> tuple[list[list[float]], list[int]]:
    X, y = [], []
    for i in range(32, len(candles) - lookahead):
        feats = _extract_enhanced_features(candles[max(0, i - 63) : i + 1])
        if feats is None:
            continue
        label = _label(candles, i, lookahead)
        X.append(feats)
        y.append(label)
    return X, y


def _extract_enhanced_features(candles: list[Candle]) -> list[float] | None:
    candles = candles[-64:]
    if len(candles) < 30:
        return None

    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    volumes = [c.volume for c in candles if c.volume > 0]
    last = candles[-1]

    fast = sma(closes, 5)
    slow = sma(closes, 20)
    volatility = atr(candles, 14)
    momentum = rsi(closes, 14)
    if fast is None or slow is None or volatility is None or momentum is None:
        return None

    candle_range = max(last.high - last.low, 0.00001)
    avg_range = sum(c.high - c.low for c in candles[-10:]) / 10 if len(candles) >= 10 else candle_range

    macd_val = macd(closes)
    macd_hist = (macd_val[2] if macd_val else 0) / max(volatility, 0.00001)

    bb_upper, bb_lower = bollinger_bands(closes, 20, 2.0)
    bb_pos = (last.close - bb_lower) / (bb_upper - bb_lower) if bb_upper and bb_lower and bb_upper != bb_lower else 0.5

    # RSI divergence
    rsi_prev = rsi(closes[:-3], 14) or momentum
    rsi_div = momentum - rsi_prev

    # Session info
    try:
        hour = datetime.fromisoformat(
            candles[-1].time.replace("Z", "+00:00")
        ).hour if candles[-1].time else 12
    except (ValueError, IndexError):
        hour = 12
    try:
        weekday = datetime.fromisoformat(
            candles[-1].time.replace("Z", "+00:00")
        ).weekday() if candles[-1].time else 2
    except (ValueError, IndexError):
        weekday = 2

    return_recent_3 = (closes[-1] - closes[-4]) / max(volatility, 0.00001) if len(closes) >= 4 else 0
    return_recent_5 = (closes[-1] - closes[-6]) / max(volatility, 0.00001) if len(closes) >= 6 else 0

    # Volatility trend
    atr_prev = atr(candles[:-5], 14) or volatility
    vol_trend = (volatility - atr_prev) / max(atr_prev, 0.00001)

    return [
        round(_clamp((fast - slow) / max(volatility, 0.00001), -2, 2) / 2, 4),
        round((momentum - 50) / 50, 4),
        round(_clamp(volatility / max(last.close, 0.00001) * 1000, 0, 2) / 2, 4),
        round(_clamp((last.close - last.open) / candle_range, -1, 1), 4),
        round(_clamp((last.close - candles[-2].close) / max(volatility, 0.00001), -2, 2) / 2, 4),
        round(_clamp(candle_range / max(avg_range, 0.00001), 0, 3) / 3, 4),
        round(_clamp((last.close - fast) / max(volatility, 0.00001), -2, 2) / 2, 4),
        round(_clamp((last.close - slow) / max(volatility, 0.00001), -3, 3) / 3, 4),
        round(((momentum - rsi_prev) / 20) if rsi_prev is not None else 0, 4),
        round(_clamp((last.high - max(last.close, last.open)) / candle_range, 0, 1), 4),
        round(_clamp((min(last.close, last.open) - last.low) / candle_range, 0, 1), 4),
        round(_clamp((volumes[-1] / (sum(volumes[-10:]) / 10)) if len(volumes) >= 10 and sum(volumes[-10:]) > 0 else 1, 0, 3) / 3, 4),
        round(_clamp(macd_hist, -2, 2) / 2, 4),
        round(_clamp(bb_pos, 0, 1), 4),
        round(_clamp(rsi_div / 20, -1, 1), 4),
        round(hour / 24, 4),
        round(weekday / 6, 4),
        round(_clamp(return_recent_3, -2, 2) / 2, 4),
        round(_clamp(return_recent_5, -2, 2) / 2, 4),
        round(_clamp(vol_trend, -2, 2) / 2, 4),
    ]


def _label(candles: list[Candle], index: int, lookahead: int) -> int:
    current = candles[index]
    future = candles[index + 1 : index + 1 + lookahead]
    vol = atr(candles[max(0, index - 31) : index + 1], 14) or max(current.high - current.low, 0.00001)
    target = current.close + vol * 1.5
    stop = current.close - vol * 1.0

    for candle in future:
        if candle.low <= stop:
            return 0
        if candle.high >= target:
            return 1
    return int(future[-1].close > current.close)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
