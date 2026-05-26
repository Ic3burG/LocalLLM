import json
from unittest.mock import MagicMock, patch

import pytest

from agent_utils import (
    _calendar_create,
    _calendar_list,
    _delete_file,
    _generate_image,
    _google_search,
    _json_query,
    _move_file,
    _read_csv,
    _read_ics,
    _recall,
    _say,
    _screenshot,
    _sqlite_exec,
    _web_fetch,
)


@pytest.mark.asyncio
async def test_google_search():
    with patch("ddgs.DDGS") as mock_ddgs_cls:
        mock_ddgs = mock_ddgs_cls.return_value
        mock_ddgs.text.return_value = [
            {"title": "Title 1", "href": "https://example.com/1"},
            {"title": "Title 2", "href": "https://example.com/2"},
            {"title": "Title 3", "href": "https://example.com/3"},
            {"title": "Title 4", "href": "https://example.com/4"},
            {"title": "Title 5", "href": "https://example.com/5"},
        ]

        query = "test query"
        result = await _google_search(query)

        mock_ddgs.text.assert_called_once_with(query, max_results=5)
        assert isinstance(result, dict)
        assert len(result["sources"]) == 5
        urls = [s["url"] for s in result["sources"]]
        assert urls == [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
            "https://example.com/4",
            "https://example.com/5",
        ]
        titles = [s["title"] for s in result["sources"]]
        assert titles == ["Title 1", "Title 2", "Title 3", "Title 4", "Title 5"]
        # All entries should be web sources with the expected domain
        for s in result["sources"]:
            assert s["kind"] == "web"
            assert s["domain"] == "example.com"


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

    with patch("requests.get") as mock_get:
        mock_get.return_value = mock_response

        url = "https://example.com"
        result = await _web_fetch(url)

        mock_get.assert_called_once_with(url, timeout=10)
        assert isinstance(result, dict)
        body = result["model_text"]
        # Should remove script and style, and strip whitespace
        assert "alert('bad')" not in body
        assert "color: red" not in body
        assert "Hello World" in body
        assert "This is a test." in body
        assert len(result["sources"]) == 1
        assert result["sources"][0]["url"] == url
        assert result["sources"][0]["domain"] == "example.com"


@pytest.mark.asyncio
async def test_web_fetch_error():
    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception("Connection error")

        url = "https://example.com"
        result = await _web_fetch(url)

        assert result["sources"] == []
        assert "ERROR: Connection error" in result["model_text"]


@pytest.mark.asyncio
async def test_recall_returns_results():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": "[1] (a.pdf): hi", "count": 1}
    with patch("requests.post", return_value=mock_resp) as mock_post:
        out = await _recall("what is x")
    assert "[1]" in out
    assert mock_post.call_args.kwargs["json"]["query"] == "what is x"


@pytest.mark.asyncio
async def test_recall_empty():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": "", "count": 0}
    with patch("requests.post", return_value=mock_resp):
        out = await _recall("nothing")
    assert "No relevant" in out


@pytest.mark.asyncio
async def test_recall_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("requests.post", return_value=mock_resp):
        out = await _recall("boom")
    assert out.startswith("ERROR")


@pytest.mark.asyncio
async def test_read_ics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "c.ics").write_text(
        "BEGIN:VEVENT\nSUMMARY:Standup\nDTSTART:20260601T090000\n"
        "DTEND:20260601T093000\nEND:VEVENT\n"
    )
    out = await _read_ics("c.ics")
    assert "Standup" in out


@pytest.mark.asyncio
async def test_json_query_on_raw_text():
    out = await _json_query('{"users": [{"name": "Ada"}]}', "users[0].name")
    assert "Ada" in out


@pytest.mark.asyncio
async def test_read_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "d.csv").write_text("a,b\n1,2\n3,4\n")
    out = await _read_csv("d.csv")
    assert "a\tb" in out
    assert "1\t2" in out


@pytest.mark.asyncio
async def test_delete_file_uses_finder_trash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "junk.txt").write_text("x")
    with patch("subprocess.run") as mock_run:
        out = await _delete_file("junk.txt")
    assert out.startswith("OK")
    script = mock_run.call_args.args[0][2]
    assert "Finder" in script and "delete" in script


@pytest.mark.asyncio
async def test_move_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hi")
    out = await _move_file("a.txt", "b.txt")
    assert out.startswith("OK")
    assert (tmp_path / "b.txt").read_text() == "hi"
    assert not (tmp_path / "a.txt").exists()


@pytest.mark.asyncio
async def test_screenshot_uses_screencapture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("subprocess.run") as mock_run:
        out = await _screenshot("shot.png")
    assert out.startswith("OK")
    assert mock_run.call_args.args[0][0] == "screencapture"
    assert mock_run.call_args.args[0][1] == "-x"


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
async def test_say_invokes_say_command():
    with patch("subprocess.run") as mock_run:
        out = await _say("hello there")
    assert out.startswith("OK")
    assert mock_run.call_args.args[0] == ["say", "hello there"]


@pytest.mark.asyncio
async def test_generate_image_tool_handles_error():
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.json.return_value = {"error": "model_not_found"}

    with patch("requests.post", return_value=mock_response):
        result = await _generate_image("a cat")

    assert "model_not_found" in result
    assert result.startswith("ERROR:")


@pytest.mark.asyncio
async def test_sqlite_exec_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import sqlite3

    out1 = await _sqlite_exec("t.db", "CREATE TABLE t (x INTEGER)")
    assert out1 == "OK: done"
    out2 = await _sqlite_exec("t.db", "INSERT INTO t VALUES (1)")
    assert out2 == "OK: 1 row(s) affected"
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    conn.close()


@pytest.mark.asyncio
async def test_calendar_list_runs_osascript():
    mock_res = MagicMock(stdout="Standup - date\n")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        out = await _calendar_list(3)
    assert "Standup" in out
    assert mock_run.call_args.args[0][0] == "osascript"


@pytest.mark.asyncio
async def test_calendar_create_builds_event():
    mock_res = MagicMock(stdout="")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        out = await _calendar_create("Lunch", "6/1/2026 12:00:00")
    assert out.startswith("OK")
    assert "make new event" in mock_run.call_args.args[0][2]
