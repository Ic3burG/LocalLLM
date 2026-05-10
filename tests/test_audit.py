from pathlib import Path

import pytest

from agent_utils import _append_file, _grep_search, _list_dir, _read_file, _write_file


@pytest.mark.asyncio
async def test_read_file_outside_sandbox():
    # Attempt to read /etc/hosts (usually exists and is readable)
    # Without sandboxing, this should succeed.
    # With sandboxing, it should return an error message containing "PermissionError" or similar.
    # However, the task says validate_path should raise PermissionError.
    # The current implementations catch all exceptions and return "ERROR: {e}".
    
    path = "/etc/hosts"
    result = await _read_file(path)
    # Before fix, this returns the content of /etc/hosts
    # After fix, it should return "ERROR: Access denied: /etc/hosts is outside the sandbox."
    assert "Access denied" in result or "PermissionError" in result

@pytest.mark.asyncio
async def test_list_dir_outside_sandbox():
    path = "/"
    result = await _list_dir(path)
    assert "Access denied" in result or "PermissionError" in result

@pytest.mark.asyncio
async def test_write_file_outside_sandbox():
    path = "/tmp/gemma_sandbox_test.txt"
    # Even if /tmp is writable, it's outside our project root (cwd)
    result = await _write_file(path, "test")
    assert "Access denied" in result or "PermissionError" in result

@pytest.mark.asyncio
async def test_append_file_outside_sandbox():
    path = "/tmp/gemma_sandbox_test_append.txt"
    result = await _append_file(path, "test")
    assert "Access denied" in result or "PermissionError" in result

@pytest.mark.asyncio
async def test_grep_search_outside_sandbox():
    # Grep in /etc
    result = await _grep_search("root", "/etc")
    assert "Access denied" in result or "PermissionError" in result

from agent_utils import _web_fetch


@pytest.mark.asyncio
async def test_web_fetch_ssrf_localhost():
    # Attempt to fetch localhost
    # Before fix, this might succeed if something is running on port 9379 (like the bridge itself)
    # or it will just fail with a connection error but NOT a PermissionError/ValueError from our validation.
    # After fix, it should raise PermissionError or return an ERROR message containing "SSRF detected".
    url = "http://localhost:9379/v1/models"
    result = await _web_fetch(url)
    assert "SSRF detected" in result

@pytest.mark.asyncio
async def test_web_fetch_ssrf_ip():
    url = "http://127.0.0.1/etc"
    result = await _web_fetch(url)
    assert "SSRF detected" in result

from agent_utils import AUDIT_LOG_PATH, _python_interpreter, _shell


@pytest.mark.asyncio
async def test_audit_logging_expansion():
    log_path = Path(AUDIT_LOG_PATH)
    # Clean up before test
    if log_path.exists():
        try:
            log_path.unlink()
        except Exception:
            pass
    
    # 1. Test SHELL logging
    test_command = "echo 'hello shell audit'"
    await _shell(test_command)
    
    # 2. Test WRITE_FILE logging
    await _write_file("test_audit.txt", "some content")
    
    # 3. Test PYTHON logging
    await _python_interpreter("print('hello from python')")
    
    assert log_path.exists()
    content = log_path.read_text()
    assert "SHELL: echo 'hello shell audit'" in content
    assert "WRITE_FILE: test_audit.txt" in content
    assert "PYTHON: print('hello from python')" in content

    # Clean up test file
    Path("test_audit.txt").unlink(missing_ok=True)

