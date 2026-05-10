# Code Integrity & Health Design Spec

**Goal:** Establish a robust "Integrity Layer" to catch regressions across the frontend-backend bridge, external dependencies, and system performance.

**Architecture:**
1. **Connectivity Layer:** A standalone `smoke_test.py` to verify the full network path (Browser -> Node -> Python -> MLX).
2. **Contract Layer:** Integration tests in `tests/contracts/` that verify the API stability of external libraries (Search, MLX, Vision).
3. **Observability Layer:** A "Vitals" dashboard in the Settings UI showing real-time RAM, VRAM, and Latency stats.

**Components:**
- `scripts/smoke_test.py`: CLI utility for post-update verification.
- `tests/contracts/`: New test suite for unmocked library verification.
- `GET /api/stats`: Backend endpoint for system resource telemetry.
- `Settings > Vitals`: Frontend tab for health monitoring.

**Testing Strategy:**
- Smoke tests verify connectivity.
- Contract tests verify third-party reliability.
- Vitals verify performance stability.
