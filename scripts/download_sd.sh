#!/usr/bin/env bash
# Warm up the mflux FLUX.1-schnell model by triggering its first-run download.
# mflux downloads weights from HuggingFace automatically on first use.
# Run this once after installing mflux to avoid a cold start during generation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Warming up FLUX.1-schnell (4-bit quantized)..."
echo "This will download weights from HuggingFace on first run (~few GB)."
echo ""

source "$REPO_ROOT/.venv/bin/activate"
python3 - <<'PYEOF'
from mflux import Flux1, Config
print("Initializing FLUX.1-schnell (quantize=4)...")
flux = Flux1.from_name("flux-schnell", quantize=4)
print("Model ready. Generating a 1-step test image to verify...")
img = flux.generate_image(
    seed=0,
    prompt="test",
    config=Config(num_inference_steps=1, height=256, width=256),
)
print("FLUX.1-schnell is ready for use.")
PYEOF
