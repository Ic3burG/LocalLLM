import asyncio
from unittest.mock import patch

import pytest

from localllm.app import LocalLLMApp
from localllm.widgets.input_box import InputBox
from localllm.widgets.model_picker import ModelPicker
from localllm.widgets.status_bar import StatusBar
from localllm.widgets.transcript import Transcript

pytestmark = pytest.mark.needs_tty


async def test_app_mounts_and_status_populates():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        assert status.cwd
        assert status.session_id.startswith("cli-")
        transcript = app.query_one(Transcript)
        assert transcript is not None


async def test_slash_model_opens_picker_via_handler():
    """Regression: /model goes through on_input_submitted -> worker ->
    push_screen_wait. Before the worker fix this raised NoActiveWorker."""
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")

    async def fake_list(self):
        return ["gemma4-e4b", "phi4-mini", "gemma4-31b-mlx"]

    with patch("localllm.agent_client.AgentClient.list_models", fake_list):
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.query_one(InputBox)
            app.post_message(InputBox.Submitted(inp, "/model"))
            await pilot.pause()
            await asyncio.sleep(0.3)
            await pilot.pause()
            assert isinstance(app.screen, ModelPicker)
            # Input was cleared on submit.
            assert app.query_one(InputBox).value == ""
