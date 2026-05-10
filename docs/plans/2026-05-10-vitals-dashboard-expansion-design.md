# Design Document: Vitals Dashboard Expansion

## Goal
Transform the basic Vitals tab into a comprehensive "Command Center" that surfaces deep system, agent, and pipeline telemetry.

## Architecture
- **Data Collection (Python Bridge):**
    - **TelemetryManager (Singleton):** A new utility to track agent session stats (success rates, tool counts).
    - **System Hooks:** Use `psutil` and `subprocess` (for `sysctl` thermals) to gather hardware data.
    - **Pipeline Registry:** Expose internal counts from `doc_store` and ingestion timers.
- **Backend (Node.js Proxy):**
    - Continues to proxy `/api/stats` but handles the larger JSON payload.
- **Frontend (index.html):**
    - Convers the Vitals pane into a sub-tabbed interface.
    - Uses CSS Grid for a dense, widget-like layout within tabs.

## UI Components
### Sub-Tab 1: System
- **Current Stats:** RAM, VRAM, Latency.
- **CPU & Thermal:** Mini-charts or progress bars for CPU load and a color-coded indicator for Thermal Pressure (Nominal -> Critical).
- **Model Cache:** List of loaded models with their size/footprint if available.

### Sub-Tab 2: Agent
- **Analytics:** 
    - Success/Fail ratio donut chart or progress bar.
    - Tool leaderboard (e.g., "Top Tools: shell, read_file").
- **Recent Activity:** Table of last 5 agent tasks with duration and status.

### Sub-Tab 3: Pipeline
- **RAG Status:** Total documents, Total chunks, Memory used by embeddings.
- **Performance:** Avg. ingestion time per page, Embedding model status.

## Data Schema (Updated /v1/stats)
```json
{
  "system": {
    "ram_mb": 1024,
    "vram_gb": 4.5,
    "cpu_percent": 12.5,
    "thermal_pressure": "nominal",
    "latency_ms": 120,
    "models": ["gemma4-e4b"]
  },
  "agent": {
    "total_tasks": 42,
    "success_rate": 0.95,
    "top_tools": {"shell": 15, "read_file": 10},
    "recent": [
       {"id": "task-1", "status": "done", "duration": 4.2}
    ]
  },
  "pipeline": {
    "doc_count": 5,
    "chunk_count": 1200,
    "ingestion_avg_s": 0.8,
    "embedding_latency_ms": 45
  }
}
```

## Implementation Strategy
1. **Bridge Update:** Create `TelemetryManager` and update `get_stats` in `gemma_bridge.py`.
2. **Frontend Sub-tabs:** Add sub-navigation to `index.html`.
3. **Widget Implementation:** Build the new UI cards and lists.
4. **Validation:** Mock large data sets to ensure UI remains performant.
