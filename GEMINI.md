# 🛑 CRITICAL PROJECT MANDATES

## 🚦 CI is the Gate of "Done" (NON-NEGOTIABLE)

- CI **MUST** pass locally AND on GitHub for any task to be considered complete.
- Before claiming "done", run `bash .git/hooks/pre-push`. It mirrors CI exactly.
- If any check fails, the task is NOT done — fix and re-run.
- After pushing, monitor the GitHub Actions run. Red CI = failed task; diagnose and fix before returning to the user.
- Never bypass hooks (`--no-verify`, etc.). If a hook fails, fix the cause.
- Git hooks source-of-truth lives in `scripts/hooks/`. Install with `bash scripts/install-hooks.sh`.
- The pre-commit hook auto-runs `prettier --write` + `ruff format` on staged files and re-stages them, then verifies. So formatting drift cannot reach CI.

## 🛡️ Feature Integrity Policy

- **DO NOT** remove or disable any existing features without explicit, unambiguous instruction from the user.
- **NEVER** assume a feature is redundant or accidental.
- Always consult `PROGRESS.md` to understand the current feature set and project status before proposing or making structural UI/UX changes.
- If you find duplicated code or logic that appears buggy, **ASK FOR CLARIFICATION** before performing a cleanup that might delete partially implemented work.

## 🎨 UI/UX Stability

- Respect the premium, minimalist aesthetic established in recent sessions.
- Preserve the Advanced Sidebar structure:
  - **Starred** chats at the top.
  - **Recents** list fills available height (scrolls if there are more chats than fit).
  - **Scheduled Tasks** collapsible section.
  - **All Chats** button pinned at the bottom of the sidebar (always visible).
  - The sidebar is **persistent** (always visible). It is a flex column to the right of the rail and never overlays the main area.
  - Each chat row has a visible kebab "⋯" on hover that opens Star / Rename / Delete.
- **Settings Modal** is the primary location for system configurations, memory management, and technical telemetry (Vitals).

## 🧠 Memory System

- Learned memory context now lives exclusively in the **Settings > Memory** tab.
- Do not add preview widgets or live-update sidebars for memory unless explicitly requested.

## 🤖 Agentic & Reasoning Modes

- "Agent Mode" is implicit; the model automatically decides when to use tools. No toggle buttons should be added to the input area.
- **Deep Thinking** (Council of Three) is triggered via the toggle next to the model selector. This must be preserved.

## 🧪 Testing & Persistence

- All reasoning logs (Deep Thinking) must be persisted in `localStorage` within the chat message objects.
- 100% test pass rate must be maintained.
