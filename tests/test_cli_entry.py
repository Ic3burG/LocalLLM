import asyncio
from unittest.mock import patch

from localllm.cli import _bridge_is_up, main


def test_main_exits_2_when_bridge_down(capsys):
    async def _fake_health(_url):
        return False

    with patch("localllm.cli._bridge_is_up", side_effect=_fake_health):
        code = main(["--no-tui"])
    assert code == 2
    err = capsys.readouterr().err
    assert "Bridge unreachable" in err
    assert "launchctl kickstart" in err


def test_main_no_tui_prints_ok_when_bridge_up(capsys):
    async def _fake_health(_url):
        return True

    with patch("localllm.cli._bridge_is_up", side_effect=_fake_health):
        code = main(["--no-tui"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Bridge OK" in out


def test_bridge_is_up_returns_bool():
    async def _runner():
        return await _bridge_is_up("http://127.0.0.1:1")  # nothing listening

    assert asyncio.run(_runner()) is False
