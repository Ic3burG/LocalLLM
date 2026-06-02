import asyncio
from unittest.mock import patch

from localllm.cli import _bridge_is_up, main


def test_main_exits_2_when_bridge_down(capsys):
    async def _fake_detail(_url, _model):
        return None  # bridge unreachable

    with patch("localllm.cli._bridge_health_detail", side_effect=_fake_detail):
        code = main(["--no-tui"])
    assert code == 2
    err = capsys.readouterr().err
    assert "Bridge unreachable" in err
    assert "launchctl kickstart" in err


def test_main_exits_4_when_model_not_loaded(capsys):
    async def _fake_detail(_url, _model):
        return {"status": "ok", "ready": False, "model_id": "gemma4-e4b"}

    with patch("localllm.cli._bridge_health_detail", side_effect=_fake_detail):
        code = main(["--no-tui"])
    assert code == 4
    err = capsys.readouterr().err
    assert "not loaded yet" in err


def test_main_no_tui_prints_ok_when_bridge_ready(capsys):
    async def _fake_detail(_url, _model):
        return {"status": "ok", "ready": True, "model_id": "gemma4-e4b"}

    with patch("localllm.cli._bridge_health_detail", side_effect=_fake_detail):
        code = main(["--no-tui"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Bridge OK" in out
    assert "ready" in out


def test_main_launches_tui_when_reachable_but_model_cold():
    """Interactive launch only needs a reachable bridge; the model warms on the
    first prompt, so a cold model must NOT block the TUI (no exit 4)."""

    async def _fake_detail(_url, _model):
        return {"status": "ok", "ready": False, "model_id": "gemma4-e4b"}

    with (
        patch("localllm.cli._bridge_health_detail", side_effect=_fake_detail),
        patch("localllm.cli.sys.stdout.isatty", return_value=True),
        patch("localllm.app.LocalLLMApp") as MockApp,
    ):
        code = main([])  # interactive (no --no-tui)

    assert code == 0
    MockApp.assert_called_once()
    assert MockApp.call_args.kwargs.get("model_ready") is False
    MockApp.return_value.run.assert_called_once()


def test_bridge_is_up_returns_bool():
    async def _runner():
        return await _bridge_is_up("http://127.0.0.1:1")  # nothing listening

    assert asyncio.run(_runner()) is False
