#!/usr/bin/env python3
"""Shared helpers for the MeteorRadio ML station layer.

This module intentionally has no third-party dependencies.  Training may use
scikit-learn, but runtime inference on the Raspberry Pi is pure Python.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


RADAR = Path(os.environ.get("MR_RADAR_DIR", "/home/pi/radar_data"))
SCORE_INDEX = Path(
    os.environ.get(
        "MR_SCORE_INDEX",
        "/home/pi/meteorradio-web/cache/v562_score_index.json",
    )
)
STATE_DIR = Path(
    os.environ.get("MR_ML_STATE_DIR", "/home/pi/meteorradio-ml-state")
)
LABELS_FILE = STATE_DIR / "ml_labels_v1.json"
MODEL_FILE = STATE_DIR / "ml_model_v1.json"
PREDICTIONS_FILE = STATE_DIR / "ml_predictions_v1.json"

CLASSIFICATION_URL = os.environ.get(
    "MR_CLASSIFICATION_URL",
    "http://127.0.0.1:8094/api/classification",
)
IMAGE_URL = os.environ.get(
    "MR_IMAGE_URL",
    "http://127.0.0.1:8096/image",
)

VALID_LABELS = ("meteor", "aircraft", "satellite", "rfi", "unknown")
TRAIN_LABELS = ("meteor", "aircraft", "satellite", "rfi")

# Feature order is part of the model format.  Never silently reorder it.
FEATURE_NAMES = (
    "flag_head_echo",
    "flag_trail",
    "flag_join",
    "flag_narrow",
    "flag_duration",
    "flag_peak",
    "flag_continuity",
    "strict_features_passed",
    "event_duration_s",
    "instant_width_p90_hz",
    "broadband_occupancy",
    "anchor_peak_db",
    "anchor_frequency_hz",
    "head_duration_s",
    "head_peak_db",
    "head_r2",
    "head_occupancy",
    "head_excursion_hz",
    "head_drift_hz_per_s",
    "trail_duration_s",
    "trail_stability_hz",
    "trail_strength_db",
    "trail_continuity",
    "head_trail_join_hz",
)

_FLAG_MAP = {
    "flag_head_echo": "head_echo",
    "flag_trail": "trail",
    "flag_join": "join",
    "flag_narrow": "narrow",
    "flag_duration": "duration",
    "flag_peak": "peak",
    "flag_continuity": "continuity",
}


class MLDataError(RuntimeError):
    pass


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:
        return default


def atomic_json(path: Path, payload: Any) -> None:
    ensure_state_dir()
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                payload,
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass


def safe_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValueError("file must be a string")
    if Path(name).name != name:
        raise ValueError("invalid file name")
    if not name.startswith("SMP_") or not name.lower().endswith(".npz"):
        raise ValueError("expected SMP_*.npz")
    return name


def read_scores() -> Dict[str, int]:
    raw = load_json(SCORE_INDEX, {})
    if isinstance(raw, dict) and isinstance(raw.get("scores"), dict):
        raw = raw["scores"]
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for name, score in raw.items():
        try:
            name = safe_name(name)
            score = int(score)
        except Exception:
            continue
        if 1 <= score <= 7:
            out[name] = score
    return out


def fetch_classification(name: str, timeout: float = 65.0) -> Dict[str, Any]:
    name = safe_name(name)
    query = urllib.parse.urlencode({"file": name, "v": "562p1"})
    request = urllib.request.Request(
        f"{CLASSIFICATION_URL}?{query}",
        headers={"User-Agent": "MeteorRadio-ML/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not data.get("ok"):
        raise MLDataError(
            str(data.get("error", "classification failed"))
            if isinstance(data, dict)
            else "classification failed"
        )
    return data


def _finite_or_none(value: Any) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def extract_features(classification: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    metrics = classification.get("metrics")
    if not isinstance(metrics, Mapping):
        raise MLDataError("classification has no metrics")

    result: Dict[str, Optional[float]] = {}
    for target, source in _FLAG_MAP.items():
        result[target] = 1.0 if bool(metrics.get(source)) else 0.0

    numeric = {
        "strict_features_passed": "strict_features_passed",
        "event_duration_s": "event_duration_s",
        "instant_width_p90_hz": "instant_width_p90_hz",
        "broadband_occupancy": "broadband_occupancy",
        "anchor_peak_db": "anchor_peak_db",
        "anchor_frequency_hz": "anchor_frequency_hz",
        "head_duration_s": "head_duration_s",
        "head_peak_db": "head_peak_db",
        "head_r2": "head_r2",
        "head_occupancy": "head_occupancy",
        "head_excursion_hz": "head_excursion_hz",
        "head_drift_hz_per_s": "head_drift_hz_per_s",
        "trail_duration_s": "trail_duration_s",
        "trail_stability_hz": "trail_stability_hz",
        "trail_strength_db": "trail_strength_db",
        "trail_continuity": "trail_continuity",
        "head_trail_join_hz": "head_trail_join_hz",
    }
    for target, source in numeric.items():
        result[target] = _finite_or_none(metrics.get(source))

    # Fail loudly if a code change accidentally drops a model feature.
    missing = [name for name in FEATURE_NAMES if name not in result]
    if missing:
        raise MLDataError(f"feature schema mismatch: {missing}")

    return result


def load_labels() -> Dict[str, Any]:
    raw = load_json(
        LABELS_FILE,
        {"version": 1, "updated": None, "labels": {}},
    )
    if not isinstance(raw, dict):
        raw = {"version": 1, "updated": None, "labels": {}}
    if not isinstance(raw.get("labels"), dict):
        raw["labels"] = {}
    return raw


def load_predictions() -> Dict[str, Any]:
    raw = load_json(
        PREDICTIONS_FILE,
        {"version": 1, "updated": None, "model_id": None, "items": {}},
    )
    if not isinstance(raw, dict):
        raw = {"version": 1, "updated": None, "model_id": None, "items": {}}
    if not isinstance(raw.get("items"), dict):
        raw["items"] = {}
    return raw


def load_model() -> Optional[Dict[str, Any]]:
    raw = load_json(MODEL_FILE, None)
    if not isinstance(raw, dict):
        return None
    if raw.get("format") != "meteorradio-logistic-v1":
        return None
    if raw.get("feature_names") != list(FEATURE_NAMES):
        return None
    return raw


def _impute_and_scale(model: Mapping[str, Any], features: Mapping[str, Any]) -> List[float]:
    medians = model.get("imputer_median")
    means = model.get("scaler_mean")
    scales = model.get("scaler_scale")
    if not all(isinstance(x, list) for x in (medians, means, scales)):
        raise MLDataError("invalid model preprocessing")
    if not (len(medians) == len(means) == len(scales) == len(FEATURE_NAMES)):
        raise MLDataError("invalid model feature length")

    out: List[float] = []
    for i, name in enumerate(FEATURE_NAMES):
        value = _finite_or_none(features.get(name))
        if value is None:
            value = float(medians[i])
        scale = float(scales[i])
        if not math.isfinite(scale) or abs(scale) < 1e-12:
            scale = 1.0
        out.append((value - float(means[i])) / scale)
    return out


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _softmax(values: Iterable[float]) -> List[float]:
    values = list(values)
    top = max(values)
    exps = [math.exp(v - top) for v in values]
    total = sum(exps) or 1.0
    return [v / total for v in exps]


def predict_features(
    model: Mapping[str, Any], features: Mapping[str, Any]
) -> Dict[str, Any]:
    x = _impute_and_scale(model, features)
    classes = model.get("classes")
    coef = model.get("coef")
    intercept = model.get("intercept")
    mode = model.get("mode")
    if not isinstance(classes, list) or len(classes) < 2:
        raise MLDataError("invalid model classes")
    if not isinstance(coef, list) or not isinstance(intercept, list):
        raise MLDataError("invalid model coefficients")

    def linear(row: List[float], bias: float) -> float:
        if len(row) != len(x):
            raise MLDataError("invalid coefficient width")
        return sum(a * b for a, b in zip(row, x)) + float(bias)

    if mode == "binary_logistic":
        if len(classes) != 2 or len(coef) != 1 or len(intercept) != 1:
            raise MLDataError("invalid binary model")
        p1 = _sigmoid(linear(coef[0], intercept[0]))
        probs = [1.0 - p1, p1]
    elif mode == "multinomial_logistic":
        if len(coef) != len(classes) or len(intercept) != len(classes):
            raise MLDataError("invalid multinomial model")
        logits = [linear(row, bias) for row, bias in zip(coef, intercept)]
        probs = _softmax(logits)
    else:
        raise MLDataError("unsupported model mode")

    pairs = {str(c): float(p) for c, p in zip(classes, probs)}
    best_class = max(pairs, key=pairs.get)
    confidence = float(pairs[best_class])
    threshold = float(model.get("unknown_threshold", 0.70))
    predicted = best_class if confidence >= threshold else "unknown"

    return {
        "predicted_label": predicted,
        "best_class": best_class,
        "confidence": confidence,
        "unknown_threshold": threshold,
        "probabilities": pairs,
        "model_id": model.get("model_id"),
    }


def dataset_rows(labels_payload: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    labels_payload = labels_payload or load_labels()
    labels = labels_payload.get("labels", {})
    if not isinstance(labels, Mapping):
        return []

    rows: List[Dict[str, Any]] = []
    for name, entry in labels.items():
        if not isinstance(entry, Mapping):
            continue
        label = entry.get("label")
        if label not in VALID_LABELS:
            continue
        features = entry.get("feature_vector")
        if not isinstance(features, Mapping):
            heuristic = entry.get("heuristic")
            if isinstance(heuristic, Mapping):
                try:
                    features = extract_features(heuristic)
                except Exception:
                    features = None
        row: Dict[str, Any] = {
            "file": name,
            "label": label,
            "labeled_at": entry.get("labeled_at"),
            "heuristic_score": entry.get("heuristic_score"),
            "heuristic_version": entry.get("heuristic_version"),
        }
        for feature in FEATURE_NAMES:
            row[feature] = features.get(feature) if isinstance(features, Mapping) else None
        rows.append(row)
    return rows


def dataset_csv_bytes() -> bytes:
    rows = dataset_rows()
    fieldnames = [
        "file",
        "label",
        "labeled_at",
        "heuristic_score",
        "heuristic_version",
        *FEATURE_NAMES,
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")
