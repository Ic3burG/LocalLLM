import asyncio
import logging
from unittest.mock import patch

from textual.app import App

from localllm.app import LocalLLMApp
from localllm.cli import _bridge_is_up, main


def test_handle_exception_logs_full_traceback(caplog):
    """The global hook must log any unhandled TUI exception (with traceback)
    before deferring to Textual's teardown."""
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    err = RuntimeError("boom")
    with patch.object(App, "_handle_exception") as mock_super:
        with caplog.at_level(logging.CRITICAL, logger="localllm"):
            app._handle_exception(err)
    mock_super.assert_called_once_with(err)
    crit = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert crit, "expected a CRITICAL record"
    assert any(r.exc_info and r.exc_info[1] is err for r in crit)


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
