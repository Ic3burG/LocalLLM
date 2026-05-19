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

    # Implementation returns a {"sources": [...], "model_text": str} dict.
    assert isinstance(result, dict), "Result should be a dict"
    assert "sources" in result and "model_text" in result, (
        f"Result missing required keys: {result}"
    )
    assert not result["model_text"].startswith("ERROR:"), (
        f"Search failed with error: {result['model_text']}"
    )
    assert result["sources"], "Search should return at least one source"

    # Verify each source has the expected web-source structure.
    for s in result["sources"]:
        assert s["kind"] == "web", f"Expected web source, got: {s.get('kind')}"
        assert s.get("title"), "Source should have a title"
        assert s.get("url", "").startswith("http"), (
            f"Source url should be http(s), got: {s.get('url')}"
        )
        # body/snippet may be empty in some cases, but title and URL must be there.
