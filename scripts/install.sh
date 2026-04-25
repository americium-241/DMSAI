#!/usr/bin/env bash
# DMSAI native installer — Linux / macOS
# Usage: bash scripts/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT"

echo ""
echo "=== DMSAI Native Installer ==="
echo ""

# --- Environment file --------------------------------------------------------
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[1/5] Created .env from .env.example — fill in your secrets before starting."
else
  echo "[1/5] .env already exists, skipping."
fi

# --- Shared Python packages --------------------------------------------------
echo "[2/5] Installing shared Python packages..."
pip install -e core_framework -e shared

# --- API Gateway dependencies ------------------------------------------------
echo "[3/5] Installing api_gateway dependencies..."
pip install -r api_gateway/requirements.txt

# --- Node dependencies -------------------------------------------------------
echo "[4/5] Installing pipeline node dependencies..."
for dir in nodes/*/; do
  req="$dir/requirements.txt"
  if [ -f "$req" ]; then
    echo "      $dir"
    pip install -r "$req"
  fi
done

# --- Frontend ----------------------------------------------------------------
echo "[5/5] Installing frontend dependencies (npm install)..."
cd frontend
npm install
cd ..

# --- Done --------------------------------------------------------------------
echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env — set DMSAI_JWT_SECRET, DMSAI_INTERNAL_API_KEY, and your LLM provider keys."
echo "  2. Start the stack:   python dmsai.py start"
echo "  3. Open the app:      http://localhost:5173"
echo "  4. Default admin:     admin@dmsai.com / admin123"
echo ""
