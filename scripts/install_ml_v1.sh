#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/software/meteorradio-ml"
UNITS="$ROOT/deployment/systemd/reference"

if [[ ! -f "$SRC/server.py" ]]; then
  echo "ERROR: run this script from the MeteorRadio-V5-Station repository" >&2
  exit 2
fi

sudo install -d -o pi -g pi /home/pi/meteorradio-ml /home/pi/meteorradio-ml-state
sudo install -o pi -g pi -m 0644 "$SRC/ml_common.py" /home/pi/meteorradio-ml/ml_common.py
sudo install -o pi -g pi -m 0755 "$SRC/server.py" /home/pi/meteorradio-ml/server.py
sudo install -o pi -g pi -m 0755 "$SRC/train_model.py" /home/pi/meteorradio-ml/train_model.py
sudo install -o pi -g pi -m 0755 "$SRC/predict_new.py" /home/pi/meteorradio-ml/predict_new.py
sudo install -o pi -g pi -m 0644 "$SRC/README.md" /home/pi/meteorradio-ml/README.md

sudo install -m 0644 "$UNITS/meteorradio-ml.service" /etc/systemd/system/meteorradio-ml.service
sudo install -m 0644 "$UNITS/meteorradio-ml-score.service" /etc/systemd/system/meteorradio-ml-score.service
sudo install -m 0644 "$UNITS/meteorradio-ml-score.timer" /etc/systemd/system/meteorradio-ml-score.timer

if [[ ! -f /etc/default/meteorradio-ml ]]; then
  sudo install -m 0644 "$ROOT/config/ml.example.env" /etc/default/meteorradio-ml
fi

sudo systemctl daemon-reload
sudo systemctl enable --now meteorradio-ml.service
sudo systemctl enable --now meteorradio-ml-score.timer

echo
echo "MeteorRadio ML v1 installed."
echo "UI: http://$(hostname -I | awk '{print $1}'):8101/"
echo "Health: http://127.0.0.1:8101/healthz"
echo "Labels: /home/pi/meteorradio-ml-state/ml_labels_v1.json"
echo
echo "Training is manual and needs numpy + scikit-learn."
