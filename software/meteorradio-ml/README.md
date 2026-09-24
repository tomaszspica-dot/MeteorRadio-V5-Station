# MeteorRadio ML classifier v1

This is an **optional station-layer module**. It does not acquire the RTL-SDR,
does not alter the MeteorRadio trigger, and does not delete detections.

## Design

The v1 pipeline is:

```text
MeteorRadio trigger
  -> SMP capture
  -> existing v5.6.2 heuristic classifier
  -> manual label dataset
  -> logistic ML model
  -> probability vector
  -> UNKNOWN when confidence is below threshold
```

The current 1–7 heuristic score remains independent and authoritative for the
existing retention policy until ML has been validated on enough local data.

## Labels

The review UI uses five manual labels:

- `meteor`
- `aircraft`
- `satellite`
- `rfi`
- `unknown`

`unknown` is **not trained as a physical class**. During inference it is emitted
when the best trained class is below `MR_ML_UNKNOWN_THRESHOLD` (default 0.70).

## Features

The model uses the numerical/boolean values already produced by the v5.6.2
classifier: HEAD/TRAIL/JOIN/NARROW/DURATION/PEAK/CONTINUITY plus event duration,
instantaneous width, broadband occupancy, anchor peak/frequency, head drift/R²/
occupancy/excursion, trail stability/strength/continuity and head-trail join.

The manual label record stores a snapshot of these features, so a labelled row
can remain usable after the original SMP file expires under retention.

## Runtime files

Default state directory: `/home/pi/meteorradio-ml-state`

- `ml_labels_v1.json` — manual labels + frozen feature snapshots
- `ml_model_v1.json` — exported logistic model
- `ml_predictions_v1.json` — predictions for currently retained detections

These are runtime observation data and should not be committed to GitHub.

## Services

- `meteorradio-ml.service` — review UI/API, port **8101**
- `meteorradio-ml-score.service` — pure-Python inference worker
- `meteorradio-ml-score.timer` — runs inference periodically

Training is intentionally manual. The station keeps collecting data even when no
model exists.

## Training

Training needs NumPy and scikit-learn, but **runtime inference does not**.

```bash
cd /home/pi/meteorradio-ml
python3 train_model.py
python3 predict_new.py
```

Defaults require at least 5 manually labelled examples in each of at least two
trainable classes. Change with `MR_ML_MIN_CLASS` only for experiments.

The training script stores cross-validated balanced accuracy when the dataset is
large enough. Do not enable automatic deletion/filtering from ML merely because
training accuracy is high.
