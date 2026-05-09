#!/usr/bin/env bash
# DMSAI native installer — Linux / macOS
# Usage: bash scripts/install.sh
#
# Installs Python deps, frontend deps, and PostgreSQL natively, then
# provisions the dmsai role/database.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT"

# All install logic lives in the canonical Python script.
exec python3 "$SCRIPT_DIR/install.py" "$@"
