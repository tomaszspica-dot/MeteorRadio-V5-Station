#!/bin/bash
set -Eeuo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
cd "$SELF"

./VALIDATE_BEFORE_GITHUB.command

if [ ! -d .git ]; then
  git init -b main
else
  echo "Git repository already exists."
fi

cat <<'MSG'

Local Git repository is initialized.

Recommended next steps:
  1. Review: git status
  2. Review UPSTREAM_LICENSE_NOTICE.md
  3. Add sanitized screenshots
  4. git add .
  5. git status --short
  6. git commit -m "Initial MeteorRadio V5 station overlay"
  7. Create a PRIVATE GitHub repository and add its remote.

This script intentionally does NOT push anything to GitHub.
MSG
