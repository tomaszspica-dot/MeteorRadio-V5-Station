#!/usr/bin/env python3
"""Train the MeteorRadio feature-based ML classifier.

Training is intentionally manual.  The acquisition process and automatic
retention never depend on this script.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter

from ml_common import (
    FEATURE_NAMES,
    MODEL_FILE,
    TRAIN_LABELS,
    atomic_json,
    dataset_rows,
    utc_timestamp,
)


def die(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def main() -> None:
    try:
        import numpy as np
        import sklearn
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:
        die(
            "training needs numpy + scikit-learn; "
            f"import failed: {exc!r}"
        )

    min_per_class = max(2, int(os.environ.get("MR_ML_MIN_CLASS", "5")))
    unknown_threshold = float(os.environ.get("MR_ML_UNKNOWN_THRESHOLD", "0.70"))
    if not (0.0 < unknown_threshold < 1.0):
        die("MR_ML_UNKNOWN_THRESHOLD must be between 0 and 1")

    rows = dataset_rows()
    counts_all = Counter(row["label"] for row in rows)
    eligible_classes = [
        label
        for label in TRAIN_LABELS
        if counts_all.get(label, 0) >= min_per_class
    ]
    if len(eligible_classes) < 2:
        die(
            "need at least two trainable classes with "
            f">={min_per_class} labelled detections each; counts={dict(counts_all)}"
        )

    usable = []
    for row in rows:
        if row["label"] not in eligible_classes:
            continue
        if all(row.get(name) is None for name in FEATURE_NAMES):
            continue
        usable.append(row)

    counts = Counter(row["label"] for row in usable)
    eligible_classes = [
        label for label in eligible_classes if counts.get(label, 0) >= min_per_class
    ]
    usable = [row for row in usable if row["label"] in eligible_classes]
    if len(eligible_classes) < 2:
        die(f"not enough feature-complete labels; counts={dict(counts)}")

    X = np.array(
        [
            [
                np.nan if row.get(name) is None else float(row[name])
                for name in FEATURE_NAMES
            ]
            for row in usable
        ],
        dtype=float,
    )
    y = np.array([row["label"] for row in usable], dtype=object)

    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    solver="lbfgs",
                    max_iter=5000,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ]
    )

    min_count = min(Counter(y).values())
    cv_score = None
    if min_count >= 2 and len(y) >= 10:
        folds = min(5, min_count)
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
        try:
            scores = cross_val_score(
                pipeline,
                X,
                y,
                cv=cv,
                scoring="balanced_accuracy",
            )
            cv_score = {
                "folds": folds,
                "balanced_accuracy_mean": float(np.mean(scores)),
                "balanced_accuracy_std": float(np.std(scores)),
                "scores": [float(v) for v in scores],
            }
        except Exception as exc:
            cv_score = {"error": repr(exc)}

    pipeline.fit(X, y)
    transformed = pipeline[:-1].transform(X)
    clf = pipeline.named_steps["clf"]
    pred = clf.predict(transformed)

    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scale"]
    classes = [str(v) for v in clf.classes_.tolist()]
    mode = "binary_logistic" if len(classes) == 2 else "multinomial_logistic"

    payload = {
        "format": "meteorradio-logistic-v1",
        "created_utc": utc_timestamp(),
        "feature_names": list(FEATURE_NAMES),
        "classes": classes,
        "mode": mode,
        "unknown_threshold": unknown_threshold,
        "imputer_median": [float(v) for v in imputer.statistics_.tolist()],
        "scaler_mean": [float(v) for v in scaler.mean_.tolist()],
        "scaler_scale": [float(v) for v in scaler.scale_.tolist()],
        "coef": [[float(v) for v in row] for row in clf.coef_.tolist()],
        "intercept": [float(v) for v in clf.intercept_.tolist()],
        "training": {
            "samples": int(len(y)),
            "class_counts": dict(Counter(str(v) for v in y)),
            "min_samples_per_class": min_per_class,
            "training_accuracy": float(accuracy_score(y, pred)),
            "cross_validation": cv_score,
            "sklearn_version": sklearn.__version__,
            "unknown_label_is_threshold_only": True,
        },
    }

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["model_id"] = "ml1-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    atomic_json(MODEL_FILE, payload)

    print("MODEL", payload["model_id"])
    print("FILE", MODEL_FILE)
    print("SAMPLES", len(y))
    print("CLASSES", ", ".join(classes))
    print("TRAIN_ACCURACY", f"{payload['training']['training_accuracy']:.4f}")
    if isinstance(cv_score, dict) and "balanced_accuracy_mean" in cv_score:
        print("CV_BALANCED_ACCURACY", f"{cv_score['balanced_accuracy_mean']:.4f}")
    print("UNKNOWN_THRESHOLD", f"{unknown_threshold:.3f}")


if __name__ == "__main__":
    main()
