# 🛑 LocalLLM — Project Mandates for Claude Code

This file is loaded automatically into every Claude Code session. The rules
below are **absolute** and override any default behavior.

## 🚦 CI is the Gate of "Done"

CI **MUST** pass locally AND remotely for any task to be considered complete.

1. Before claiming any work is done, you MUST run the full pre-push pipeline:

   ```bash
   bash .git/hooks/pre-push
   ```

   (Or equivalently: `ruff check .` + `ruff format --check .` + `npx prettier --check .` + `.venv/bin/python -m pytest -q -m "not needs_gpu" --ignore=tests/contracts/test_mlx_contract.py`.)

   If ANY check fails, you have NOT completed the task. Fix the failures and
   re-run before reporting back to the user.

2. **Never** push, open a PR, or say "done" until you have verification evidence
   from a freshly-run pre-push command in the current message. Saying it
   "should pass" without running it is dishonesty, not efficiency.

3. After any `git push`, monitor the GitHub Actions run for `main` (or your
   feature branch). If CI fails on GitHub, you have NOT completed the task —
   diagnose, fix, push again, and re-verify green CI before returning control
   to the user.

4. **Never** use `--no-verify`, `--no-gpg-sign`, or any flag that bypasses the
   hooks. If a hook fails, fix the underlying problem.

## 🪝 Git Hooks (Auto-Format + Verify)

Git hooks live in `scripts/hooks/` and are the source of truth. To install
them into a fresh clone (or after a hook edit), run:

```bash
bash scripts/install-hooks.sh
```

- **`pre-commit`** auto-runs `prettier --write` and `ruff format` on staged
  files, re-stages them, then verifies the full repo passes
  `prettier --check`, `ruff check`, and `ruff format --check`. If any of those
  fail, the commit is blocked until a human resolves it.
- **`pre-push`** mirrors the GitHub Actions CI exactly. If it passes, CI will
  pass. Never push without it.

If you find the installed hook in `.git/hooks/` is out of sync with the source
in `scripts/hooks/`, re-run the installer immediately.

## 🛡️ Feature Integrity (mirrors GEMINI.md)

- **DO NOT** remove or disable any existing feature without explicit, unambiguous
  instruction from the user.
- Always read `PROGRESS.md` before structural UI/UX changes — it is the project
  log and explains why each piece is the way it is.
- When you find duplicate-looking code or seemingly-buggy logic, **ASK FOR
  CLARIFICATION** before deleting; you may be looking at in-progress work.

## 🧠 Memory & Settings Locations

- Learned memory context lives in the **Settings → Memory** tab — do not add
  preview widgets or sidebar mirrors for memory unless asked.
- Vitals/telemetry lives in the **Settings → Vitals** tab.
- Sidebar contains: Starred (top), Recents (fills available height), Scheduled
  Tasks (collapsible), All Chats button (pinned at bottom).

## 🛠️ Where Things Live

- `gemma_bridge.py` — Python FastAPI bridge on port 9379 (model inference, agent
  routes, RAG, stats).
- `agent.py` — ReAct loop + SSE streaming router mounted at `/v1/agent/*`.
- `agent_utils.py` — Tool registry, telemetry, validation helpers.
- `gemma-web/server.js` — Node Express proxy on port 3001.
- `gemma-web/index.html` — Single-file frontend (glass UI, see PROGRESS Session 7).
- `tests/` — `pytest` suite; GPU tests are marked `needs_gpu` and skipped in CI.

## ✅ Definition of Done — copy this checklist into every task report

- [ ] All requested changes implemented.
- [ ] `bash .git/hooks/pre-push` ran in this session and exited 0.
- [ ] If anything touched the frontend, the change was sanity-checked by reading
      the file (or by browser if available).
- [ ] If pushed, GitHub Actions CI is green (or honestly reported red with
      diagnosis).
