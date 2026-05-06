import pytest
import os
import mlx.core as mx

def has_gpu():
    try:
        return mx.default_device().type == mx.DeviceType.gpu
    except Exception:
        return False

@pytest.mark.skipif(not has_gpu(), reason="MLX requires a GPU for this contract test")
def test_mlx_vlm_load_contract():
    """
    Verifies that mlx_vlm can load a local model.
    This is a contract test for the 'mlx-vlm' library.
    """
    try:
        from mlx_vlm import load
    except ImportError:
        pytest.skip("mlx_vlm is not installed")

    # Use the small gemma-4-e4b-it-4bit model for testing
    model_path = os.path.join(os.getcwd(), "mlx_models", "gemma-4-e4b-it-4bit")
    
    if not os.path.exists(model_path):
        pytest.skip(f"Model path {model_path} does not exist")

    # Verify load works without crashing
    model, processor = load(model_path)
    
    assert model is not None, "Model should be loaded"
    assert processor is not None, "Processor should be loaded"

@pytest.mark.skipif(not has_gpu(), reason="MLX requires a GPU for this contract test")
def test_mlx_vlm_generate_contract():
    """
    Verifies that mlx_vlm generation works with a single token.
    """
    try:
        from mlx_vlm import load, generate
    except ImportError:
        pytest.skip("mlx_vlm is not installed")

    model_path = os.path.join(os.getcwd(), "mlx_models", "gemma-4-e4b-it-4bit")
    
    if not os.path.exists(model_path):
        pytest.skip(f"Model path {model_path} does not exist")

    # Load model and processor
    model, processor = load(model_path)
    
    # Test single-token generation
    # We use a simple prompt. Note: mlx_vlm.generate usually takes (model, processor, prompt, ...)
    prompt = "Test"
    
    # Apply chat template if available to make it a realistic prompt
    try:
        messages = [{"role": "user", "content": prompt}]
        prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    except Exception:
        pass # Fallback to raw prompt if template fails

    output = generate(model, processor, prompt, max_tokens=1)
    
    # In newer mlx-vlm versions, generate returns a GenerationResult object
    # with a .text attribute. In older ones, it might be a string.
    if hasattr(output, "text"):
        assert isinstance(output.text, str), "output.text should be a string"
    else:
        assert isinstance(output, str), "Output should be a string"
