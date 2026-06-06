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
