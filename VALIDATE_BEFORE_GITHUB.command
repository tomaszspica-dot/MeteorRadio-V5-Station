#!/bin/bash
set -Eeuo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)"
exec "$SELF/scripts/validate_public_repo.sh"
