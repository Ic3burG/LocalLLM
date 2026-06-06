from localllm.commands import CommandResult, dispatch


def test_help_returns_help_text():
    result = dispatch("/help", model="gemma4-e4b")
    assert isinstance(result, CommandResult)
    assert result.kind == "show"
    assert "/help" in result.message


def test_model_with_arg_sets_model():
    result = dispatch("/model gemma-31b", model="gemma4-e4b")
    assert result.kind == "set_model"
    assert result.value == "gemma-31b"


def test_model_no_arg_opens_picker():
    result = dispatch("/model", model="gemma-31b")
    assert result.kind == "pick_model"


def test_clear():
    result = dispatch("/clear", model="x")
    assert result.kind == "clear"


def test_tools_lists_tools():
    result = dispatch("/tools", model="x")
    assert result.kind == "show"
    assert "read_file" in result.message


def test_cwd_with_arg_returns_set_cwd():
    result = dispatch("/cwd /tmp", model="x")
    assert result.kind == "set_cwd"
    assert result.value == "/tmp"


def test_cwd_no_arg_shows_usage():
    result = dispatch("/cwd", model="x")
    assert result.kind == "show"
    assert "usage" in result.message.lower()


def test_quit():
    result = dispatch("/quit", model="x")
    assert result.kind == "quit"


def test_reconnect_shows_message():
    result = dispatch("/reconnect", model="x")
    assert result.kind == "show"
    assert "retry" in result.message.lower()


def test_unknown_command_returns_show_with_hint():
    result = dispatch("/wat", model="x")
    assert result.kind == "show"
    assert "unknown" in result.message.lower()


def test_non_command_returns_none():
    assert dispatch("hello world", model="x") is None


def test_commands_table_drives_help():
    from localllm.commands import COMMANDS, HELP_TEXT

    names = [name for name, _ in COMMANDS]
    assert "/help" in names
    assert "/quit" in names
    # Every command appears in the generated help text.
    for name in names:
        assert name in HELP_TEXT
