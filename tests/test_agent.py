import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_run_inference_is_importable():
    import inspect, gemma_bridge
    assert hasattr(gemma_bridge, "run_inference")
    sig = inspect.signature(gemma_bridge.run_inference)
    assert "messages" in sig.parameters
    assert "model_id" in sig.parameters
