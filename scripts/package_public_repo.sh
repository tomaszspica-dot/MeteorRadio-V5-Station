#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

./scripts/validate_public_repo.sh

NAME="MeteorRadio-V5-GitHub-$(date '+%Y%m%d_%H%M%S')"
OUT="${1:-$HOME/Desktop/${NAME}.zip}"
TMP="$(mktemp -d /tmp/mr-gh-release.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/$NAME"
rsync -a \
  --exclude '.git/' \
  --exclude 'private_reference/' \
  --exclude '.DS_Store' \
  --exclude '._*' \
  ./ "$TMP/$NAME/"

(
  cd "$TMP"
  /usr/bin/zip -qry "$OUT" "$NAME"
)

echo "PUBLIC_REPO_ZIP=$OUT"
if command -v shasum >/dev/null 2>&1; then
  echo "SHA256=$(shasum -a 256 "$OUT" | awk '{print $1}')"
fi
