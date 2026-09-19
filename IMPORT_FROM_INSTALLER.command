#!/bin/bash
set -Eeuo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)"
ZIP="${1:-$HOME/Desktop/MeteorRadio_V5_ChatGPT_Installer.zip}"
STAGE="$(mktemp -d /tmp/mr-gh-import.XXXXXX)"
PKG="$STAGE/MeteorRadio_V5_ChatGPT_Installer"

cleanup() {
  RC=$?
  trap - EXIT
  rm -rf "$STAGE"
  exit "$RC"
}
trap cleanup EXIT

say() { printf '\n===== %s =====\n' "$1"; }

say "MeteorRadio V5 -> MR_GH import"
echo "REPO=$SELF"
echo "INSTALLER=$ZIP"

test -f "$ZIP" || {
  echo "ABORT: installer ZIP not found: $ZIP"
  exit 1
}

say "Extract installer"
unzip -q "$ZIP" -d "$STAGE"
test -d "$PKG"
test -f "$PKG/PACKAGE_SHA256SUMS.txt"

say "Verify installer manifest"
(
  cd "$PKG"
  shasum -a 256 -c PACKAGE_SHA256SUMS.txt
)
echo "INSTALLER_MANIFEST=PASS"

say "Prepare public station layer"

rm -rf \
  "$SELF/software/meteorradio-web" \
  "$SELF/software/meteorradio-stats" \
  "$SELF/deployment/systemd/reference"

mkdir -p \
  "$SELF/software/meteorradio-web" \
  "$SELF/software/meteorradio-stats" \
  "$SELF/software/tools" \
  "$SELF/deployment/systemd/reference"

cp -a "$PKG/payload/home/pi/meteorradio-web/." \
      "$SELF/software/meteorradio-web/"

cp -a "$PKG/payload/home/pi/meteorradio-stats/." \
      "$SELF/software/meteorradio-stats/"

if [ -f "$PKG/payload/usr/local/sbin/meteorradio-healthcheck.py" ]; then
  cp -a "$PKG/payload/usr/local/sbin/meteorradio-healthcheck.py" \
        "$SELF/software/tools/"
fi

if [ -f "$PKG/payload/usr/local/sbin/radio-owner-control" ]; then
  cp -a "$PKG/payload/usr/local/sbin/radio-owner-control" \
        "$SELF/software/tools/"
fi

cp -a "$PKG/payload/etc/systemd/system/." \
      "$SELF/deployment/systemd/reference/"

# Runtime/private state is never part of the public code tree.
rm -rf \
  "$SELF/software/meteorradio-web/cache" \
  "$SELF/software/meteorradio-web/health"

find "$SELF/software" "$SELF/deployment" \
  -name '.DS_Store' -delete 2>/dev/null || true
find "$SELF/software" "$SELF/deployment" \
  -name '._*' -delete 2>/dev/null || true
find "$SELF/software" \
  -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$SELF/software" \
  -type f -name '*.pyc' -delete 2>/dev/null || true


# MR_GH_PUBLIC_SANITIZER_V1
say "Sanitize public station identifiers"

python3 \
  "$SELF/scripts/sanitize_public_import.py" \
  "$SELF"


say "Prepare LOCAL-ONLY reference"

rm -rf "$SELF/private_reference"
mkdir -p "$SELF/private_reference"

if [ -d "$PKG/payload/home/pi/MeteorRadio" ]; then
  cp -a "$PKG/payload/home/pi/MeteorRadio" \
        "$SELF/private_reference/upstream-meteorradio-modified"
fi

if [ -d "$PKG/reference_metadata" ]; then
  cp -a "$PKG/reference_metadata" \
        "$SELF/private_reference/reference_metadata"
fi

cp "$PKG/PACKAGE_INFO.txt" \
   "$SELF/private_reference/INSTALLER_PACKAGE_INFO.txt" 2>/dev/null || true

cat > "$SELF/private_reference/README_PRIVATE.txt" <<'PRIVATE'
LOCAL REFERENCE ONLY - DO NOT COMMIT

This directory intentionally contains the modified upstream MeteorRadio
reference and machine-specific Golden metadata. It is excluded by .gitignore.

Keep it locally for comparison, restoration and future patch generation.
Do not publish the upstream-derived core until licensing/permission is clear.
PRIVATE

say "Generate import report"

PUBLIC_PY="$(find "$SELF/software" -type f -name '*.py' | wc -l | tr -d ' ')"
SYSTEMD_FILES="$(find "$SELF/deployment/systemd/reference" -type f | wc -l | tr -d ' ')"
PRIVATE_FILES="$(find "$SELF/private_reference" -type f | wc -l | tr -d ' ')"

cat > "$SELF/IMPORT_REPORT.txt" <<REPORT
MeteorRadio V5 -> MR_GH import
Built: $(date '+%Y-%m-%dT%H:%M:%S%z')
Installer: $(basename "$ZIP")
Public Python files: $PUBLIC_PY
Reference systemd files: $SYSTEMD_FILES
Local-only private reference files: $PRIVATE_FILES

Installer manifest verification: PASS

Next step:
  ./VALIDATE_BEFORE_GITHUB.command
REPORT

say "Compile imported Python"
FAIL=0
while IFS= read -r -d '' F; do
  if python3 -m py_compile "$F"; then
    echo "PASS $F"
  else
    echo "FAIL $F"
    FAIL=$((FAIL+1))
  fi
done < <(find "$SELF/software" -type f -name '*.py' -print0)

test "$FAIL" = "0"

say "Done"
echo "PUBLIC_PY=$PUBLIC_PY"
echo "SYSTEMD_FILES=$SYSTEMD_FILES"
echo "PRIVATE_FILES=$PRIVATE_FILES"
echo "IMPORT=PASS"
echo
echo "Now run:"
echo "  $SELF/VALIDATE_BEFORE_GITHUB.command"
