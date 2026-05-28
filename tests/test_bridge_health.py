from fastapi.testclient import TestClient

from gemma_bridge import app


def test_health_returns_ok():
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
