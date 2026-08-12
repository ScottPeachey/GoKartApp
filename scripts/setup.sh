#!/usr/bin/env bash
# One-time (or after clone) setup for GoKartApp.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  source "$HOME/.local/bin/env"
fi

echo "Installing Python 3.12 (required for PyTorch / RL training)..."
uv python install 3.12

echo "Syncing dependencies..."
uv sync --python 3.12
uv sync --group rl --python 3.12

echo "Verifying install..."
uv run python -c "import torch; print(f'torch {torch.__version__}')"
uv run gokart --help >/dev/null

echo ""
echo "Setup complete."
echo "  Dashboard:  uv run gokart dashboard"
echo "  RL train:   uv run gokart rl train --track test-hairpin --vehicle \"Scott Kart V1\" --version V1.0 --timesteps 50000"
echo ""
if [ "$(git --version 2>/dev/null | awk '{print $3}')" = "2.15.0" ]; then
  echo "Note: /usr/local/bin/git is very old (2.15). Use /usr/bin/git for commits, or: brew install git"
fi
