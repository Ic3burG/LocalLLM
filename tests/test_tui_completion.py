from pathlib import Path

import pytest

from localllm.app import LocalLLMApp
from localllm.widgets.completion_menu import CompletionMenu
from localllm.widgets.input_box import InputBox

pytestmark = pytest.mark.needs_tty


async def test_slash_opens_command_menu():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(InputBox).focus()
        await pilot.press("/")
        await pilot.pause()
        menu = app.query_one(CompletionMenu)
        assert menu.display is True
        assert menu.option_count > 0


async def test_command_menu_filters_and_accepts():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(InputBox).focus()
        await pilot.press("/")
        await pilot.press("m")  # "/m" -> only "/model"
        await pilot.pause()
        await pilot.press("enter")  # accept (must NOT submit)
        await pilot.pause()
        assert app.query_one(InputBox).value.startswith("/model")
        assert app.query_one(CompletionMenu).display is False


async def test_at_opens_file_menu(tmp_path):
    (tmp_path / "alpha.py").write_text("x")
    (tmp_path / "beta.txt").write_text("y")
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        inp = app.query_one(InputBox)
        inp.cwd = str(tmp_path)
        inp.focus()
        await pilot.press("@")
        await pilot.pause()
        menu = app.query_one(CompletionMenu)
        assert menu.display is True
        assert menu.option_count == 2


async def test_escape_dismisses_menu():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(InputBox).focus()
        await pilot.press("/")
        await pilot.pause()
        assert app.query_one(CompletionMenu).display is True
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one(CompletionMenu).display is False


async def test_picked_message_applies_completion():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        inp = app.query_one(InputBox)
        inp.focus()
        await pilot.press("/")
        await pilot.press("m")
        await pilot.pause()
        menu = app.query_one(CompletionMenu)
        menu.post_message(CompletionMenu.Picked("/model"))
        await pilot.pause()
        assert inp.value.startswith("/model")


async def test_history_navigation_when_menu_closed():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        inp = app.query_one(InputBox)
        inp.focus()
        inp.push_history("previous command")
        await pilot.press("up")
        await pilot.pause()
        assert inp.value == "previous command"
        assert app.query_one(CompletionMenu).display is False


async def test_submit_injects_mentioned_file(tmp_path, monkeypatch):
    (tmp_path / "note.txt").write_text("hello-from-file")
    captured = {}

    async def fake_stream(self, *, prompt, model_id, cwd, cli_session_id):
        captured["prompt"] = prompt
        return
        yield  # pragma: no cover  -- makes this an async generator

    monkeypatch.setattr("localllm.agent_client.AgentClient.run_and_stream", fake_stream)

    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        app._cwd = str(tmp_path)
        inp = app.query_one(InputBox)
        app.post_message(InputBox.Submitted(inp, "read @note.txt"))
        await pilot.pause()
        await pilot.pause(0.3)
        assert "hello-from-file" in captured["prompt"]
        assert '<file path="note.txt">' in captured["prompt"]


async def test_cwd_command_retargets_picker(tmp_path):
    (tmp_path / "findme.py").write_text("x")
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        inp = app.query_one(InputBox)
        inp.focus()
        app.post_message(InputBox.Submitted(inp, f"/cwd {tmp_path}"))
        await pilot.pause()
        await pilot.pause(0.3)
        assert inp.cwd == str(Path(tmp_path).resolve())
        await pilot.press("@")
        await pilot.pause()
        menu = app.query_one(CompletionMenu)
        assert menu.display is True
        assert menu.option_count == 1
