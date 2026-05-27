"""Regression tests for USER_MEMORY.md write path.

The learner subagent and manual save endpoint both go through
``write_user_memory``. The file MUST always end with a single trailing
newline; otherwise prettier --check fails on every CI run after the bridge
touches it.

We test in a SUBPROCESS so importing ``gemma_bridge`` doesn't load native
extensions (mlx_vlm, mflux) into this test process and poison sys.modules
for later tests in the suite — same defense as the mock_deps fixture in
``test_agent.py`` (see PROGRESS Session 9 for the original incident).
"""

import subprocess
import sys
import textwrap


def _run(target_path: str, payload: str) -> str:
    """Invoke gemma_bridge.write_user_memory in a fresh Python process."""
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, ".")
        import gemma_bridge
        gemma_bridge.MEMORY_FILE = {target_path!r}
        gemma_bridge.write_user_memory({payload!r})
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"subprocess failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    with open(target_path) as f:
        return f.read()


def test_write_user_memory_adds_trailing_newline(tmp_path):
    target = tmp_path / "USER_MEMORY.md"
    contents = _run(str(target), "# Header\n\n- bullet")
    assert contents.endswith("\n"), "memory file must end with newline"
    assert not contents.endswith("\n\n"), "no double trailing newline"


def test_write_user_memory_normalizes_existing_trailing_newlines(tmp_path):
    target = tmp_path / "USER_MEMORY.md"
    contents = _run(str(target), "body\n\n\n")
    assert contents == "body\n"


def test_write_user_memory_handles_empty(tmp_path):
    target = tmp_path / "USER_MEMORY.md"
    contents = _run(str(target), "")
    assert contents == "\n"


def test_write_user_memory_redacts_secrets(tmp_path):
    target = tmp_path / "USER_MEMORY.md"
    contents = _run(
        str(target),
        "# User Memory\n\n- verification code is 482913\n- day rate is $700",
    )
    assert "482913" not in contents  # secret redacted
    assert "[REDACTED]" in contents
    assert "$700" in contents  # benign context preserved
