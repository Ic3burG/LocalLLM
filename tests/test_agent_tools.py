import pytest
from unittest.mock import patch, MagicMock
from agent import _google_search, _web_fetch

@pytest.mark.asyncio
async def test_google_search():
    with patch('googlesearch.search') as mock_search:
        mock_search.return_value = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
            "https://example.com/4",
            "https://example.com/5"
        ]
        
        query = "test query"
        result = await _google_search(query)
        
        mock_search.assert_called_once_with(query, num=5, stop=5)
        expected = "\n".join([
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
            "https://example.com/4",
            "https://example.com/5"
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
