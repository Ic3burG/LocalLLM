import socket

import pytest

from agent_utils import _google_search


def has_internet():
    try:
        # Connect to Google DNS to check for internet connectivity
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not has_internet(), reason="No internet connection")
async def test_google_search_contract():
    """
    Verifies that _google_search returns expected data from DuckDuckGo.
    This is a contract test for the 'ddgs' library and our scraping logic.
    """
    query = "python programming"
    result = await _google_search(query)

    # Implementation returns a string, verify it's not an error message
    assert isinstance(result, str), "Result should be a string"
    assert not result.startswith("ERROR:"), f"Search failed with error: {result}"
    assert result != "No results found.", "Search should return at least one result"

    # Verify structure: results are separated by double newlines
    blocks = result.split("\n\n")
    assert len(blocks) > 0, "Should have at least one block of results"

    # Verify each block looks like a search result
    # Format: title\nurl\nbody
    for block in blocks:
        lines = block.split("\n")
        assert len(lines) >= 2, "Each result block should have at least title and URL"
        assert lines[1].startswith("http"), (
            f"Second line should be a URL, got: {lines[1]}"
        )
        # The body might be empty or missing in some cases, but title and URL should be there.
