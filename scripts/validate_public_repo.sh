#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAIL=0
warn() { printf 'WARN: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*"; FAIL=$((FAIL+1)); }
pass() { printf 'PASS: %s\n' "$*"; }

printf '\n============================================================\n'
printf ' MR_GH PUBLICATION VALIDATION\n'
printf '============================================================\n\n'

# Private/local material must remain ignored.
if [ -d private_reference ]; then
  if git check-ignore private_reference >/dev/null 2>&1; then
    pass "private_reference is ignored by Git"
  elif [ -f .gitignore ] && grep -q '^/private_reference/' .gitignore; then
    pass "private_reference is covered by .gitignore"
  else
    fail "private_reference exists but is not clearly ignored"
  fi
fi

# Files that must never be public by accident.
BAD_FILES="$(find . \
  -path './.git' -prune -o \
  -path './private_reference' -prune -o \
  -type f \
  \( -name '.radar_config' \
     -o -name 'SMP_*.npz' \
     -o -name 'SPG_*.npz' \
     -o -name 'AUD_*.raw' \
     -o -name 'v562_score_index.json' \
     -o -name 'v562_likes.json' \
     -o -name 'v562_retention_state.json' \
  \) -print)"

if [ -n "$BAD_FILES" ]; then
  printf '%s\n' "$BAD_FILES"
  fail "private/runtime data found in public tree"
else
  pass "no raw/private runtime data in public tree"
fi

# Common station/user leakage checks. Example placeholders are excluded.
for P in '/Users/tomek' 'Air-Tomasz' 'satnogspi' '192.168.1.102' 'BEGIN OPENSSH PRIVATE KEY' 'BEGIN RSA PRIVATE KEY'; do
  if grep -RIl --exclude-dir=.git --exclude-dir=private_reference --exclude='*.example' --exclude='validate_public_repo.sh' "$P" . >/dev/null 2>&1; then
    grep -RIn --exclude-dir=.git --exclude-dir=private_reference --exclude='*.example' --exclude='validate_public_repo.sh' "$P" . | head -20
    fail "possible private identifier/key pattern: $P"
  else
    pass "pattern absent from public tree: $P"
  fi
done

# Client-specific/private modules must never enter the public tree.
BAD_PRIVATE_PATHS="$(
  find . \
    -path './.git' -prune -o \
    -path './private_reference' -prune -o \
    -type f \
    \( -iname '*iphone*' \
       -o -iname '*scriptable*' \
    \) -print
)"

if [ -n "$BAD_PRIVATE_PATHS" ]; then
  printf '%s\n' "$BAD_PRIVATE_PATHS"
  fail "private client-specific files found"
else
  pass "no private client-specific files"
fi

for P in \
  'iphone_widget_server' \
  'meteorradio-iphone-widget' \
  'Scriptable' \
  '192.168.1.102' \
  'satnogspi' \
  '54.1875' \
  '16.2083333333' \
  'JO84ce' \
  'Koszalin_North'
do

  if grep -RIl \
      --exclude-dir=.git \
      --exclude-dir=private_reference \
      --exclude='validate_public_repo.sh' \
      "$P" . >/dev/null 2>&1
  then

      grep -RIn \
        --exclude-dir=.git \
        --exclude-dir=private_reference \
        --exclude='validate_public_repo.sh' \
        "$P" . \
        | head -20

      fail "station/private pattern: $P"

  else

      pass "station/private pattern absent: $P"

  fi

done

if find . \
    -path './.git' -prune -o \
    -type d \
    -name 'cache.before-*' \
    -print \
    | grep -q .
then

    fail "historical cache.before-* directory found"

else

    pass "no historical cache.before-* directories"

fi

# Python syntax.
PYCOUNT=0
while IFS= read -r -d '' F; do
  PYCOUNT=$((PYCOUNT+1))
  if ! python3 -m py_compile "$F"; then
    fail "Python syntax: $F"
  fi
done < <(find software -type f -name '*.py' -print0 2>/dev/null || true)

if [ "$PYCOUNT" -gt 0 ]; then
  pass "Python syntax checked: $PYCOUNT files"
else
  warn "No imported Python files yet; run IMPORT_FROM_INSTALLER.command"
fi

# Shell syntax.
SHCOUNT=0
while IFS= read -r -d '' F; do
  SHCOUNT=$((SHCOUNT+1))
  if ! bash -n "$F"; then
    fail "Shell syntax: $F"
  fi
done < <(find . -path './.git' -prune -o -path './private_reference' -prune -o \
  -type f \( -name '*.sh' -o -name '*.command' \) -print0)
pass "shell syntax checked: $SHCOUNT files"

# Upstream core must not be present in public tree.
if [ -f software/meteor_radar.py ] || [ -f upstream/meteor_radar.py ] || [ -d software/MeteorRadio ]; then
  fail "upstream-derived acquisition core appears in public tree"
else
  pass "upstream core not vendored in public tree"
fi

# Finder metadata.
JUNK="$(find . -path './.git' -prune -o -type f \( -name '.DS_Store' -o -name '._*' \) -print)"
if [ -n "$JUNK" ]; then
  printf '%s\n' "$JUNK"
  fail "macOS metadata found"
else
  pass "no macOS metadata"
fi

printf '\n============================================================\n'
if [ "$FAIL" -eq 0 ]; then
  echo ' PUBLICATION_VALIDATION=PASS'
  echo ' Review docs/PUBLICATION_CHECKLIST.md before making repo public.'
else
  echo " PUBLICATION_VALIDATION=FAIL ($FAIL issue(s))"
  exit 1
fi
printf '============================================================\n'
