import pytest
from fastapi.testclient import TestClient
from gemma_bridge import app
import psutil

client = TestClient(app)

def test_stats_endpoint_schema():
    response = client.get("/v1/stats")
    assert response.status_code == 200
    data = response.json()
    
    # Check top-level blocks
    assert "system" in data
    assert "agent" in data
    assert "pipeline" in data
    
    # Check system block
    system = data["system"]
    assert isinstance(system["ram_mb"], (int, float))
    assert isinstance(system["vram_gb"], (int, float))
    assert isinstance(system["cpu_percent"], (int, float))
    assert system["thermal_pressure"] in ["nominal", "fair", "serious", "critical", "unknown"]
    assert isinstance(system["latency_ms"], (int, float))
    assert isinstance(system["models"], list)
    
    # Check agent block
    agent = data["agent"]
    assert "total_tasks" in agent
    assert "success_rate" in agent
    assert "top_tools" in agent
    assert "recent" in agent
    
    # Check pipeline block
    pipeline = data["pipeline"]
    assert isinstance(pipeline["doc_count"], int)
    assert isinstance(pipeline["chunk_count"], int)
    assert isinstance(pipeline["ingestion_avg_s"], (int, float))
    assert isinstance(pipeline["embedding_latency_ms"], (int, float))

def test_pipeline_stats_update():
    # Initially 0
    response = client.get("/v1/stats")
    initial_doc_count = response.json()["pipeline"]["doc_count"]
    
    # Mock adding a document to doc_store
    from gemma_bridge import doc_store
    doc_store["test_doc"] = {"chunks": [{"text": "hello"}, {"text": "world"}]}
    
    response = client.get("/v1/stats")
    data = response.json()
    assert data["pipeline"]["doc_count"] == initial_doc_count + 1
    assert data["pipeline"]["chunk_count"] >= 2
    
    # Cleanup
    del doc_store["test_doc"]
    
def test_pipeline_telemetry_tracking():
    from gemma_bridge import record_ingestion_time, record_embedding_latency
    
    # Record some stats
    record_ingestion_time(0.5)
    record_ingestion_time(1.5)
    record_embedding_latency(40)
    record_embedding_latency(60)
    
    response = client.get("/v1/stats")
    data = response.json()
    
    pipeline = data["pipeline"]
    assert pipeline["ingestion_avg_s"] == 1.0  # (0.5 + 1.5) / 2
    assert pipeline["embedding_latency_ms"] == 50.0  # (40 + 60) / 2
