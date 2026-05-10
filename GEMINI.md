# 🛑 CRITICAL PROJECT MANDATES

## 🛡️ Feature Integrity Policy
- **DO NOT** remove or disable any existing features without explicit, unambiguous instruction from the user.
- **NEVER** assume a feature is redundant or accidental.
- Always consult `PROGRESS.md` to understand the current feature set and project status before proposing or making structural UI/UX changes.
- If you find duplicated code or logic that appears buggy, **ASK FOR CLARIFICATION** before performing a cleanup that might delete partially implemented work.

## 🎨 UI/UX Stability
- Respect the premium, minimalist aesthetic established in recent sessions.
- Preserve the Advanced Sidebar structure:
    - **Starred** chats at the top.
    - **Recents** list below (scrollable area).
    - **All Chats** button pinned below the Recents list (always visible).
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
