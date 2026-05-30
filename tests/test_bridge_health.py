from unittest.mock import patch

from fastapi.testclient import TestClient

from gemma_bridge import app


def test_health_returns_ok():
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "ready" in body
    assert body["model_id"] == "gemma4-e4b"


def test_health_ready_reflects_model_loaded():
    client = TestClient(app)
    with patch("inference_engine.is_model_loaded", return_value=True):
        resp = client.get("/v1/health")
        assert resp.json()["ready"] is True
    with patch("inference_engine.is_model_loaded", return_value=False):
        resp = client.get("/v1/health")
        assert resp.json()["ready"] is False


def test_health_accepts_model_id_query():
    client = TestClient(app)
    with patch("inference_engine.is_model_loaded", return_value=True) as m:
        resp = client.get("/v1/health?model_id=gemma-31b")
        assert resp.json()["model_id"] == "gemma-31b"
        m.assert_called_once_with("gemma-31b")
