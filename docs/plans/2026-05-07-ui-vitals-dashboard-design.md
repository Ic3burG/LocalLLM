# Design Document: Task 4 - UI Vitals Dashboard

## Goal

Add a "Vitals" tab to the Settings modal in the UI to display system health and performance stats.

## Architecture

- **Backend (Python Bridge):** Provides `/v1/stats` (RAM, VRAM, etc.).
- **Backend (Node.js Proxy):**
  - Proxies `/api/stats` to the bridge.
  - New `/api/backend/check` endpoint that executes `scripts/smoke_test.py --json`.
- **Frontend (index.html):**
  - Settings modal converted to a tabbed interface ("Vitals" and "Memory").
  - "Vitals" tab (default) polls `/api/stats` every 5 seconds.
  - Displays RAM, VRAM, and Latency in cards.
  - Lists loaded models.
  - "Run Integrity Check" button to trigger smoke test and display output.

## Components & UI

- **Tabs:** Navigation at the top of the modal.
- **Stats Cards:** Grid of 3 cards (RAM, VRAM, Latency).
- **Model List:** Simple list of currently loaded models from stats.
- **Integrity Check:** Button + scrollable `<pre>` block for raw output.
- **Styling:** Adherence to `THEME.md` tokens (`--color-*`).

## Data Flow

1. User opens Settings.
2. `updateVitals()` is called immediately and then every 5s.
3. `updateVitals()` fetches `/api/stats` via Node.js proxy.
4. UI updates based on response.
5. User clicks "Run Integrity Check" -> `POST /api/backend/check`.
6. Node.js runs `python3 scripts/smoke_test.py --json`.
7. UI displays JSON result or raw output if JSON fails.

## Testing Strategy

- Manual verification of theme consistency.
- Verify polling starts/stops correctly when modal is opened/closed.
- Mock `/api/stats` and `/api/backend/check` if bridge is unavailable.
