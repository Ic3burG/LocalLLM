# Task 4: UI Vitals Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "Vitals" tab to the Settings modal in the UI to display system health and performance stats, including a system integrity check.

**Architecture:** 
- Update `smoke_test.py` to support JSON output.
- Add `/api/backend/check` to `server.js` to execute the smoke test.
- Redesign the Settings modal in `index.html` to be tabbed ("Vitals" as default, "Memory").
- Implement real-time polling of `/api/stats` and a button to trigger the integrity check.

**Tech Stack:** JavaScript (ES6), Node.js (Express), Python, TailwindCSS.

---

### Task 1: Update `scripts/smoke_test.py` for JSON output

**Files:**
- Modify: `scripts/smoke_test.py`

**Step 1: Modify `print_result` and `main` to support JSON**

Update the script to collect results and print them as JSON if `--json` is passed.

**Step 2: Run test to verify it works**

Run: `python3 scripts/smoke_test.py --json`
Expected: A JSON object with test results.

**Step 3: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "feat: add --json flag to smoke_test.py"
```

### Task 2: Update `gemma-web/server.js` with new endpoint

**Files:**
- Modify: `gemma-web/server.js`

**Step 1: Add `GET /api/backend/check` route**

```javascript
app.get("/api/backend/check", (req, res) => {
  execFile("python3", ["../scripts/smoke_test.py", "--json"], (error, stdout, stderr) => {
    if (error) {
      // If JSON fails, return raw output
      return res.json({ success: false, raw: stdout + stderr });
    }
    try {
      res.json(JSON.parse(stdout));
    } catch (e) {
      res.json({ success: false, raw: stdout });
    }
  });
});
```

**Step 2: Verify endpoint**

Run: `node gemma-web/server.js` (in background) then `curl http://localhost:3001/api/backend/check`
Expected: JSON response from smoke test.

**Step 3: Commit**

```bash
git add gemma-web/server.js
git commit -m "feat: add /api/backend/check endpoint to server.js"
```

### Task 3: Redesign `index.html` Settings Modal to Tabbed Interface

**Files:**
- Modify: `gemma-web/index.html`

**Step 1: Add Tab HTML/CSS**

Update the modal header to include "Vitals" and "Memory" tabs. Ensure "Vitals" is default. Use `--color-accent` for active state.

**Step 2: Create Vitals Tab Content**

Add cards for RAM, VRAM, and Latency. Add a "Loaded Models" section. Add a "System Integrity" section with a "Run Check" button and `<pre>` block.

**Step 3: Update Modal JS Logic**

Implement tab switching logic. Initialize Vitals as active.

**Step 4: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat: redesign Settings modal with tabbed interface"
```

### Task 4: Implement Vitals Polling and Integrity Check Logic

**Files:**
- Modify: `gemma-web/index.html`

**Step 1: Implement `updateVitals()`**

Fetch `/api/stats` and update cards/model list. Format bytes to GB.

**Step 2: Implement polling logic**

Start polling (5s interval) when Settings modal is opened. Stop polling when closed.

**Step 3: Implement Integrity Check button**

Trigger `/api/backend/check` on click. Show "Running..." state. Display results in the `<pre>` block with color coding if possible (or just raw JSON/Text).

**Step 4: Verify UI**

Open modal, check if stats update. Click "Run Check" and verify output.

**Step 5: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat: implement vitals polling and integrity check logic"
```
