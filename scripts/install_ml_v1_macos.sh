#!/usr/bin/env bash
set -euo pipefail

ROOT="${METEORRADIO_MAC_ROOT:-$HOME/MeteorRadio-Mac}"
SRC_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$SRC_REPO_ROOT/software/meteorradio-ml"
DEST="$ROOT/panels/meteorradio-ml"
STATE="$ROOT/state/meteorradio-ml"
LOGS="$ROOT/logs"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
UID_NOW="$(id -u)"
PYTHON3="$(command -v python3 || true)"

if [[ -z "$PYTHON3" ]]; then
  echo "ERROR: python3 not found in PATH" >&2
  exit 2
fi

if [[ ! -d "$ROOT" ]]; then
  echo "ERROR: MeteorRadio Mac root not found: $ROOT" >&2
  exit 2
fi

if [[ ! -f "$ROOT/panel-app/app.py" ]]; then
  echo "ERROR: current 8094 panel not found at $ROOT/panel-app/app.py" >&2
  exit 2
fi

if [[ ! -f "$ROOT/panels/meteorradio-web/likes_server.py" ]]; then
  echo "ERROR: current 8096 backend not found at $ROOT/panels/meteorradio-web/likes_server.py" >&2
  exit 2
fi

if [[ ! -f "$SRC/server.py" ]]; then
  echo "ERROR: ML source files not found in repository" >&2
  exit 2
fi

echo "===== CURRENT LOCAL SERVICES ====="
curl -fsS http://127.0.0.1:8094/ >/dev/null
echo "8094 OK"
curl -fsS http://127.0.0.1:8096/healthz >/dev/null 2>&1 || curl -fsS http://127.0.0.1:8096/ >/dev/null
echo "8096 OK"

SCORE_INDEX=""
for candidate in   "$ROOT/panels/meteorradio-web/cache/v562_score_index.json"   "$ROOT/panel-app/cache/v562_score_index.json"   "$ROOT/cache/v562_score_index.json"
do
  if [[ -f "$candidate" ]]; then
    SCORE_INDEX="$candidate"
    break
  fi
done

if [[ -z "$SCORE_INDEX" ]]; then
  SCORE_INDEX="$(find "$ROOT" -type f -name 'v562_score_index.json' -print -quit 2>/dev/null || true)"
fi

if [[ -z "$SCORE_INDEX" ]]; then
  echo "ERROR: v562_score_index.json not found under $ROOT" >&2
  exit 3
fi

RADAR_DIR=""
# Current macOS layout keeps detections in nested per-event directories below inbox.
if [[ -d "$ROOT/inbox" ]]; then
  RADAR_DIR="$ROOT/inbox"
fi

if [[ -z "$RADAR_DIR" ]]; then
  RADAR_DIR="$(find "$ROOT" -type d -name 'radar_data' -print -quit 2>/dev/null || true)"
fi

if [[ -z "$RADAR_DIR" ]]; then
  FIRST_SMP="$(find "$ROOT" -type f -name 'SMP_*.npz' -print -quit 2>/dev/null || true)"
  if [[ -n "$FIRST_SMP" ]]; then
    RADAR_DIR="$ROOT"
  fi
fi

if [[ -z "$RADAR_DIR" ]]; then
  echo "ERROR: could not locate local SMP/radar_data directory under $ROOT" >&2
  exit 3
fi

echo "ROOT        = $ROOT"
echo "PYTHON3     = $PYTHON3"
echo "RADAR_DIR   = $RADAR_DIR"
echo "SCORE_INDEX = $SCORE_INDEX"

mkdir -p "$DEST" "$STATE" "$LOGS" "$LAUNCH_AGENTS"

install -m 0644 "$SRC/ml_common.py" "$DEST/ml_common.py"
install -m 0755 "$SRC/server.py" "$DEST/server.py"
install -m 0755 "$SRC/train_model.py" "$DEST/train_model.py"
install -m 0755 "$SRC/predict_new.py" "$DEST/predict_new.py"
install -m 0644 "$SRC/README.md" "$DEST/README.md"

SERVER_PLIST="$LAUNCH_AGENTS/pl.tomek.meteorradio.ml8101.plist"
SCORE_PLIST="$LAUNCH_AGENTS/pl.tomek.meteorradio.mlscore.plist"

cat >"$SERVER_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>pl.tomek.meteorradio.ml8101</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON3</string>
    <string>-u</string>
    <string>$DEST/server.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MR_ML_PORT</key><string>8101</string>
    <key>MR_ML_STATE_DIR</key><string>$STATE</string>
    <key>MR_RADAR_DIR</key><string>$RADAR_DIR</string>
    <key>MR_SCORE_INDEX</key><string>$SCORE_INDEX</string>
    <key>MR_CLASSIFICATION_URL</key><string>http://127.0.0.1:8094/api/classification</string>
    <key>MR_IMAGE_URL</key><string>http://127.0.0.1:8096/image</string>
    <key>MR_ML_UNKNOWN_THRESHOLD</key><string>0.70</string>
    <key>MR_ML_MIN_CLASS</key><string>5</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOGS/meteorradio-ml8101.out.log</string>
  <key>StandardErrorPath</key><string>$LOGS/meteorradio-ml8101.err.log</string>
</dict>
</plist>
PLIST

cat >"$SCORE_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>pl.tomek.meteorradio.mlscore</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON3</string>
    <string>-u</string>
    <string>$DEST/predict_new.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MR_ML_STATE_DIR</key><string>$STATE</string>
    <key>MR_RADAR_DIR</key><string>$RADAR_DIR</string>
    <key>MR_SCORE_INDEX</key><string>$SCORE_INDEX</string>
    <key>MR_CLASSIFICATION_URL</key><string>http://127.0.0.1:8094/api/classification</string>
    <key>MR_IMAGE_URL</key><string>http://127.0.0.1:8096/image</string>
    <key>MR_ML_UNKNOWN_THRESHOLD</key><string>0.70</string>
    <key>MR_ML_MIN_CLASS</key><string>5</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>$LOGS/meteorradio-mlscore.out.log</string>
  <key>StandardErrorPath</key><string>$LOGS/meteorradio-mlscore.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$SERVER_PLIST"
plutil -lint "$SCORE_PLIST"

launchctl bootout "gui/$UID_NOW/pl.tomek.meteorradio.ml8101" 2>/dev/null || true
launchctl bootout "gui/$UID_NOW/pl.tomek.meteorradio.mlscore" 2>/dev/null || true

launchctl bootstrap "gui/$UID_NOW" "$SERVER_PLIST"
launchctl bootstrap "gui/$UID_NOW" "$SCORE_PLIST"

sleep 2

echo
echo "===== ML 8101 HEALTH ====="
curl -fsS http://127.0.0.1:8101/healthz
echo

echo
echo "===== LAUNCHD ====="
launchctl print "gui/$UID_NOW/pl.tomek.meteorradio.ml8101" | grep -E 'state =|pid =|last exit code' || true
launchctl print "gui/$UID_NOW/pl.tomek.meteorradio.mlscore" | grep -E 'state =|pid =|last exit code' || true

echo
echo "Installed:"
echo "  UI:    http://127.0.0.1:8101/"
echo "  code:  $DEST"
echo "  state: $STATE"
