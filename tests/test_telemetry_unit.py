import unittest
import time
import collections
from unittest.mock import MagicMock, patch
import asyncio

# Mocking parts of inference_engine that depend on MLX
import sys
sys.modules['mlx'] = MagicMock()
sys.modules['mlx.core'] = MagicMock()
sys.modules['mlx_vlm'] = MagicMock()
sys.modules['mlx_lm'] = MagicMock()

import inference_engine

class TestInferenceEngineTelemetry(unittest.TestCase):
    def test_latency_tracking(self):
        # Reset or initialize latencies if we can access them
        if hasattr(inference_engine, '_inference_latencies'):
            inference_engine._inference_latencies.clear()
        
        # We need to mock run_in_inference_thread because it's an async function 
        # that actually puts things in a queue.
        # But we want to test the timing logic in run_inference.
        
        async def mock_run_inference():
            with patch('inference_engine.run_in_inference_thread', return_value={"choices": [{"message": {"content": "test"}}]}) as mock_run:
                await inference_engine.run_inference([{"role": "user", "content": "hi"}])
                await inference_engine.run_inference([{"role": "user", "content": "hi"}])
        
        asyncio.run(mock_run_inference())
        
        self.assertTrue(len(inference_engine._inference_latencies) >= 2)
        avg = sum(inference_engine._inference_latencies) / len(inference_engine._inference_latencies)
        self.assertGreaterEqual(avg, 0)

if __name__ == '__main__':
    unittest.main()
