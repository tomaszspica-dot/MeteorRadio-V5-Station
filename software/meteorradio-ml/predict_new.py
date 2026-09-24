#!/usr/bin/env python3
"""Predict ML labels for currently retained, already-scored detections."""

from __future__ import annotations

import os
import time

from ml_common import (
    PREDICTIONS_FILE,
    RADAR,
    atomic_json,
    extract_features,
    fetch_classification,
    load_model,
    load_predictions,
    predict_features,
    read_scores,
    utc_timestamp,
)


def log(*args) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


def main() -> None:
    model = load_model()
    if not model:
        log("NO_MODEL", "nothing to do")
        return

    model_id = model.get("model_id")
    scores = read_scores()
    state = load_predictions()
    items = state.get("items", {}) if isinstance(state.get("items"), dict) else {}
    max_per_run = max(0, int(os.environ.get("MR_ML_MAX_PER_RUN", "0")))

    candidates = []
    for name, score in scores.items():
        if not (RADAR / name).is_file():
            continue
        old = items.get(name)
        if isinstance(old, dict) and old.get("model_id") == model_id:
            continue
        candidates.append((name, score))

    candidates.sort(key=lambda pair: (RADAR / pair[0]).stat().st_mtime)
    if max_per_run:
        candidates = candidates[:max_per_run]

    log("START", f"model={model_id}", f"pending={len(candidates)}")
    changed = 0
    errors = 0

    for name, score in candidates:
        try:
            classification = fetch_classification(name)
            features = extract_features(classification)
            prediction = predict_features(model, features)
            items[name] = {
                **prediction,
                "evaluated_utc": utc_timestamp(),
                "heuristic_score": score,
                "heuristic_version": classification.get("heuristic_version"),
            }
            changed += 1
            log(
                "PREDICT",
                name,
                prediction["predicted_label"],
                f"p={prediction['confidence']:.3f}",
            )
            if changed % 25 == 0:
                atomic_json(
                    PREDICTIONS_FILE,
                    {
                        "version": 1,
                        "updated": utc_timestamp(),
                        "model_id": model_id,
                        "items": items,
                    },
                )
        except Exception as exc:
            errors += 1
            log("ERROR", name, repr(exc))

    atomic_json(
        PREDICTIONS_FILE,
        {
            "version": 1,
            "updated": utc_timestamp(),
            "model_id": model_id,
            "items": items,
        },
    )
    log("DONE", f"predicted={changed}", f"errors={errors}")


if __name__ == "__main__":
    main()
