import pytest
from textual.app import App
from textual.widgets import OptionList

from localllm.widgets.model_picker import ModelPicker

pytestmark = pytest.mark.needs_tty


class _Host(App):
    """Bare host app so the modal has a screen stack to push onto."""


async def test_picker_lists_models_and_prehighlights_current():
    app = _Host()
    async with app.run_test() as pilot:
        screen = ModelPicker(["a", "b", "c"], current="b")
        await app.push_screen(screen)
        await pilot.pause()
        option_list = screen.query_one(OptionList)
        assert option_list.option_count == 3
        assert option_list.get_option_at_index(1).id == "b"
        # Current model is pre-highlighted and marked.
        assert option_list.highlighted == 1
        assert "(current)" in option_list.get_option_at_index(1).prompt


async def test_picker_enter_returns_highlighted_id():
    app = _Host()
    async with app.run_test() as pilot:
        chosen: dict = {}
        await app.push_screen(
            ModelPicker(["a", "b", "c"], current="b"), lambda v: chosen.update(v=v)
        )
        await pilot.pause()
        await pilot.press("down")  # b -> c
        await pilot.press("enter")
        await pilot.pause()
        assert chosen["v"] == "c"


async def test_picker_escape_returns_none():
    app = _Host()
    async with app.run_test() as pilot:
        chosen: dict = {}
        await app.push_screen(
            ModelPicker(["a", "b"], current="a"), lambda v: chosen.update(v=v)
        )
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert chosen["v"] is None
