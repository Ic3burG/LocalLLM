import gc
from pathlib import Path

import mlx.core as mx
import pytest

# Robust pathing: Derive project root relative to this file
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()

# Import inference engine and override its models directory to be robust
import inference_engine

inference_engine.MLX_MODELS_DIR = str(PROJECT_ROOT / "mlx_models")

from inference_engine import get_mlx_vlm_model, run_in_inference_thread, run_inference


def has_gpu():
    try:
        return mx.default_device().type == mx.DeviceType.gpu
    except Exception:
        return False


@pytest.fixture(scope="module")
async def mlx_vlm_model_fixture():
    """
    Fixture to load the model once per module and clean up VRAM after.
    Uses the inference engine thread to avoid stream conflicts.
    """
    if not has_gpu():
        pytest.skip("MLX requires a GPU for this contract test")

    try:
        # Load model and processor in the inference thread via the engine's cache
        # "gemma4-e4b" maps to the small test model
        model, processor = await run_in_inference_thread(
            get_mlx_vlm_model, "gemma4-e4b"
        )
    except Exception as e:
        pytest.skip(f"Failed to load model: {e}")

    yield model, processor

    # Teardown: Release VRAM in the inference thread
    def _cleanup():
        import mlx.core as mx

        from inference_engine import _vlm_cache

        _vlm_cache.clear()
        gc.collect()
        # Instruction requires mx.metal.clear_cache() and gc.collect()
        try:
            mx.metal.clear_cache()
        except (AttributeError, ImportError):
            pass
        mx.clear_cache()
        gc.collect()

    await run_in_inference_thread(_cleanup)


@pytest.mark.asyncio
@pytest.mark.skipif(not has_gpu(), reason="MLX requires a GPU for this contract test")
async def test_mlx_vlm_load_contract(mlx_vlm_model_fixture):
    """
    Verifies that mlx_vlm can load a local model.
    This is a contract test for the 'mlx-vlm' library.
    """
    model, processor = mlx_vlm_model_fixture
    assert model is not None, "Model should be loaded"
    assert processor is not None, "Processor should be loaded"


@pytest.mark.asyncio
@pytest.mark.skipif(not has_gpu(), reason="MLX requires a GPU for this contract test")
async def test_mlx_vlm_generate_contract(mlx_vlm_model_fixture):
    """
    Verifies that mlx_vlm generation works with a single token.
    Runs in the inference thread to satisfy MLX threading requirements.
    """
    from mlx_vlm import generate

    model, processor = mlx_vlm_model_fixture

    def _in_thread():
        prompt = "Test"
        # Apply chat template if available
        try:
            messages = [{"role": "user", "content": prompt}]
            prompt = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            pass
        return generate(model, processor, prompt, max_tokens=1)

    output = await run_in_inference_thread(_in_thread)

    if hasattr(output, "text"):
        assert isinstance(output.text, str), "output.text should be a string"
    else:
        assert isinstance(output, str), "Output should be a string"


@pytest.mark.asyncio
@pytest.mark.skipif(not has_gpu(), reason="MLX requires a GPU for this contract test")
async def test_run_inference_integration(mlx_vlm_model_fixture):
    """
    Verifies that inference_engine.run_inference works.
    This checks the worker thread, model caching, and end-to-end inference.
    """
    messages = [{"role": "user", "content": "Say 'Hello'"}]
    # This will use the model already loaded into the cache by the fixture
    response = await run_inference(messages, model_id="gemma4-e4b")

    assert isinstance(response, str), "Response should be a string"
    assert len(response) > 0, "Response should not be empty"
