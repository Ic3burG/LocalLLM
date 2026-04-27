import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub out heavy/unavailable dependencies before importing gemma_bridge
from unittest.mock import MagicMock, AsyncMock, patch
import types

def _make_stub(*names):
    for name in names:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

_make_stub(
    "fastapi",
    "fastapi.responses",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "litert_lm",
    "uvicorn",
    "pdf_pipeline",
)

# FastAPI() is called at module level; make it return a proper mock
import fastapi as _fastapi_stub
_fastapi_stub.FastAPI.return_value = MagicMock()

import pytest

import importlib
import gemma_bridge
importlib.reload(gemma_bridge)


FAKE_RESPONSE = {"choices": [{"message": {"content": "hello"}}]}


@pytest.mark.asyncio
async def test_run_inference_routes_litert_for_default_model():
    with patch.object(gemma_bridge, "handle_litert_request", new_callable=AsyncMock, return_value=FAKE_RESPONSE) as mock_litert, \
         patch.object(gemma_bridge, "handle_mlx_request", new_callable=AsyncMock) as mock_mlx:
        result = await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-e4b")
        assert result == "hello"
        mock_litert.assert_called_once()
        mock_mlx.assert_not_called()


@pytest.mark.asyncio
async def test_run_inference_routes_mlx_for_mlx_model():
    with patch.object(gemma_bridge, "handle_mlx_request", new_callable=AsyncMock, return_value=FAKE_RESPONSE) as mock_mlx, \
         patch.object(gemma_bridge, "handle_litert_request", new_callable=AsyncMock) as mock_litert:
        result = await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-26b-mlx")
        assert result == "hello"
        mock_mlx.assert_called_once()
        mock_litert.assert_not_called()


@pytest.mark.asyncio
async def test_run_inference_raises_on_malformed_response():
    with patch.object(gemma_bridge, "handle_litert_request", new_callable=AsyncMock, return_value={}):
        with pytest.raises(RuntimeError, match="unexpected response structure"):
            await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-e4b")
