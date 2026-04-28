import pytest
import os
from pathlib import Path
from agent_utils import _read_file, _write_file, _append_file, _list_dir, _grep_search

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
