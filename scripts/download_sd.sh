#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
MODEL_DIR="$REPO_ROOT/mlx_models/sd-1.5"

if [ -d "$MODEL_DIR" ]; then
  echo "SD 1.5 already downloaded at $MODEL_DIR"
  exit 0
fi

echo "Downloading mlx-community/stable-diffusion-2-1-mlx to $MODEL_DIR..."
mkdir -p "$MODEL_DIR"
huggingface-cli download mlx-community/stable-diffusion-2-1-mlx \
  --local-dir "$MODEL_DIR" \
  --local-dir-use-symlinks False
echo "Done. Model saved to $MODEL_DIR"
