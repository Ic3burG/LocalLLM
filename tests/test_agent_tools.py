import json
from unittest.mock import MagicMock, patch

import pytest

from agent_utils import _generate_image, _google_search, _web_fetch


@pytest.mark.asyncio
async def test_google_search():
    with patch('ddgs.DDGS') as mock_ddgs_cls:
        mock_ddgs = mock_ddgs_cls.return_value
        mock_ddgs.text.return_value = [
            {"title": "Title 1", "href": "https://example.com/1"},
            {"title": "Title 2", "href": "https://example.com/2"},
            {"title": "Title 3", "href": "https://example.com/3"},
            {"title": "Title 4", "href": "https://example.com/4"},
            {"title": "Title 5", "href": "https://example.com/5"}
        ]
        
        query = "test query"
        result = await _google_search(query)
        
        mock_ddgs.text.assert_called_once_with(query, max_results=5)
        expected = "\n\n".join([
            "Title 1\nhttps://example.com/1",
            "Title 2\nhttps://example.com/2",
            "Title 3\nhttps://example.com/3",
            "Title 4\nhttps://example.com/4",
            "Title 5\nhttps://example.com/5"
        ])
        assert result == expected

@pytest.mark.asyncio
async def test_web_fetch():
    html_content = """
    <html>
        <head><title>Test</title></head>
        <body>
            <script>alert('bad');</script>
            <style>body { color: red; }</style>
            <div>
                <h1>Hello World</h1>
                <p>This is a test.</p>
            </div>
        </body>
    </html>
    """
    
    mock_response = MagicMock()
    mock_response.text = html_content
    mock_response.raise_for_status = MagicMock()
    
    with patch('requests.get') as mock_get:
        mock_get.return_value = mock_response
        
        url = "https://example.com"
        result = await _web_fetch(url)
        
        mock_get.assert_called_once_with(url, timeout=10)
        # Should remove script and style, and strip whitespace
        assert "alert('bad')" not in result
        assert "color: red" not in result
        assert "Hello World" in result
        assert "This is a test." in result

@pytest.mark.asyncio
async def test_web_fetch_error():
    with patch('requests.get') as mock_get:
        mock_get.side_effect = Exception("Connection error")
        
        url = "https://example.com"
        result = await _web_fetch(url)
        
        assert "ERROR: Connection error" in result


@pytest.mark.asyncio
async def test_generate_image_tool_returns_image_marker():
    fake_result = {
        "image_b64": "iVBORw0KGgo=",
        "width": 512,
        "height": 512,
        "steps": 4,
        "elapsed_ms": 3000,
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = fake_result

    with patch("requests.post", return_value=mock_response):
        result = await _generate_image("a sunset", "512x512", 4)

    parsed = json.loads(result)
    assert parsed["__image__"] is True
    assert parsed["image_b64"] == "iVBORw0KGgo="
    assert parsed["width"] == 512
    assert parsed["prompt"] == "a sunset"


@pytest.mark.asyncio
async def test_generate_image_tool_handles_error():
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.json.return_value = {"error": "model_not_found"}

    with patch("requests.post", return_value=mock_response):
        result = await _generate_image("a cat")

    assert "model_not_found" in result
    assert result.startswith("ERROR:")
