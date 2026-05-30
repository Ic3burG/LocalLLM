import pytest

from localllm.app import LocalLLMApp
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
