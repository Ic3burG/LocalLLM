import unittest.mock as mock

import pytest

import inference_engine


@pytest.mark.asyncio
async def test_lru_cache_eviction():
    # Mock _mlx_vlm_load to avoid actual model loading
    # Mock os.path.exists to avoid FileNotFoundError
    with (
        mock.patch("inference_engine._mlx_vlm_load") as mock_load,
        mock.patch("os.path.exists") as mock_exists,
    ):
        mock_load.return_value = ("model", "processor")
        mock_exists.return_value = True

        # Reset cache
        inference_engine._vlm_cache = {}
        # Ensure worker is "ready"
        inference_engine._inference_ready.set()

        # Load 1st model
        inference_engine.get_mlx_vlm_model("model1")
        assert len(inference_engine._vlm_cache) == 1
        assert "model1" in inference_engine._vlm_cache

        # Load 2nd model
        inference_engine.get_mlx_vlm_model("model2")
        assert len(inference_engine._vlm_cache) == 2
        assert "model1" in inference_engine._vlm_cache
        assert "model2" in inference_engine._vlm_cache

        # Access model1 to make it most recent
        inference_engine.get_mlx_vlm_model("model1")
        # In our implementation, model1 should now be at the end of the dict
        assert list(inference_engine._vlm_cache.keys()) == ["model2", "model1"]

        # Load 3rd model - should evict model2 (least recently used)
        inference_engine.get_mlx_vlm_model("model3")
        assert len(inference_engine._vlm_cache) == 2
        assert "model2" not in inference_engine._vlm_cache
        assert "model1" in inference_engine._vlm_cache
        assert "model3" in inference_engine._vlm_cache
        assert list(inference_engine._vlm_cache.keys()) == ["model1", "model3"]
