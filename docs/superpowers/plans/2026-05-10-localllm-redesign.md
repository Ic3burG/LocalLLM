# LocalLLM Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full rewrite of `gemma-web/index.html` with glass-and-gradient aesthetic, icon rail sidebar, and "LocalLLM" branding — preserving every JS behavior exactly.

**Architecture:** Single-file rewrite of `gemma-web/index.html`. All existing DOM element IDs are preserved so existing JavaScript works without change. New CSS variables (`--llm-*`) replace the old `--color-*` token set. A 56px icon rail replaces the old fixed sidebar; the chat history panel becomes a floating overlay. One new JS block at the end of the `<script>` manages the rail toggle and sidebar panel open/close.

**Tech Stack:** Tailwind CDN (same config), Inter font, marked.js, highlight.js — all from same CDN URLs as current file.

---

## DOM ID Contract

**Every ID listed here MUST appear in the rewritten HTML exactly as spelled.** The JavaScript references these directly. Do not rename, remove, or split any of them.

```
chat-box            chat-form           user-input          typing
send-btn            theme-toggle        theme-icon-container theme-text
file-input          attach-btn          attachment-preview
sidebar             mobile-menu-btn     sidebar-overlay
history-list        new-chat-btn        chat-title          welcome-message
model-select        mode-chat-btn       mode-image-btn      image-controls-row
img-size            img-steps           img-steps-val       img-style
warmup-banner       warmup-close-btn    mode-pill
lightbox-overlay    lb-close-btn        lb-save-btn         lb-regen-btn
lb-edit-btn         lightbox-img        lb-prompt-text      lb-meta-text
context-menu        context-star-icon   context-star-text
all-chats-modal     all-chats-list      chat-search
bulk-delete-btn     selected-count
settings-modal      open-settings-btn   close-settings-btn
memory-editor       save-memory-btn     save-status
tab-vitals          tab-prompt          tab-memory
vitals-pane         system-prompt-pane  memory-pane
system-prompt-display
vital-ram           vital-vram          vital-latency       vital-models
vital-cpu           vital-thermal       run-check-btn       check-output
restart-backend-btn restart-status      restart-container   save-container
agent-success-rate  agent-success-bar   agent-total-tasks
agent-top-tools     agent-recent-tasks
vitals-subtab-system  vitals-subtab-agent   vitals-subtab-pipeline
vitals-subpane-system vitals-subpane-agent  vitals-subpane-pipeline
pipeline-doc-count  pipeline-chunk-count pipeline-ingestion-avg pipeline-embed-latency
server-status       status-dot          status-label
deep-think-toggle
scheduled-tasks-body scheduled-chevron  in-app-tasks-list
add-task-form       new-task-name       new-task-schedule   new-task-prompt
starred-section     starred-list
hljs-theme
```

---

## File Structure

| File                   | Action                          |
| ---------------------- | ------------------------------- |
| `gemma-web/index.html` | Full rewrite                    |
| `gemma-web/THEME.md`   | Update token names to `--llm-*` |

---

## Task 1: `<head>` block — CDN links, Tailwind config, CSS variables

**Files:**

- Rewrite: `gemma-web/index.html` (head section only, lines 1–36 of current file)

- [ ] **Step 1: Open the current file and read lines 1–36** to confirm existing CDN URLs before replacing.

  ```bash
  head -40 gemma-web/index.html
  ```

- [ ] **Step 2: Write the new `<head>` block**

  The new `<head>` must contain exactly these elements in this order:

  ```html
  <!doctype html>
  <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>LocalLLM</title>
      <script src="https://cdn.tailwindcss.com"></script>
      <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
      <link
        id="hljs-theme"
        rel="stylesheet"
        href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css"
      />
      <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
      <link
        href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
        rel="stylesheet"
      />
      <script>
        if (window.tailwind) {
          tailwind.config = {
            darkMode: "class",
            theme: { extend: {} },
          };
        }
      </script>
    </head>
  </html>
  ```

  Note: Tailwind custom color extensions (`darkBg`, `darkSurface`, etc.) are removed — all colors now come from CSS variables.

- [ ] **Step 3: Write the `<style>` block immediately after the Tailwind config script**

  The full `<style>` block contents (in order):

  **3a — Theme initialization (must be first — prevents FOUC):**

  ```html
  <style>
    /* ── Theme init — must run before paint ── */
  ```

  **3b — CSS Variables:**

  ```css
  :root {
    --llm-bg: linear-gradient(160deg, #ede9fe 0%, #e0e7ff 50%, #f0f4ff 100%);
    --llm-panel: rgba(255, 255, 255, 0.65);
    --llm-panel-border: rgba(139, 92, 246, 0.13);
    --llm-blur: blur(12px);
    --llm-text: #1e1b4b;
    --llm-text-muted: #6d6a8a;
    --llm-shadow: 0 4px 24px rgba(139, 92, 246, 0.1);
    --llm-accent: linear-gradient(135deg, #06b6d4, #0ea5e9);
    --llm-accent-solid: #06b6d4;
    --llm-accent-glow: rgba(6, 182, 212, 0.35);
  }
  html.dark {
    --llm-bg: linear-gradient(160deg, #0f0c29 0%, #1a1040 45%, #1e1535 100%);
    --llm-panel: rgba(255, 255, 255, 0.06);
    --llm-panel-border: rgba(255, 255, 255, 0.1);
    --llm-text: #f0eeff;
    --llm-text-muted: #9d9abf;
    --llm-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
  }
  ```

  **3c — Base body:**

  ```css
  body {
    font-family: "Inter", sans-serif;
    background: var(--llm-bg);
    color: var(--llm-text);
    height: 100vh;
    display: flex;
    overflow: hidden;
    min-height: 0;
    transition:
      background 0.3s,
      color 0.3s;
  }
  ```

  **3d — Icon rail:**

  ```css
  .rail {
    width: 56px;
    flex-shrink: 0;
    background: var(--llm-panel);
    border-right: 1px solid var(--llm-panel-border);
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 14px 0;
    gap: 4px;
    z-index: 20;
    position: relative;
  }
  .rail-logo {
    width: 32px;
    height: 32px;
    background: linear-gradient(135deg, #06b6d4, #0ea5e9);
    border-radius: 9px;
    box-shadow: 0 2px 10px rgba(6, 182, 212, 0.45);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 800;
    color: white;
    letter-spacing: -0.5px;
    flex-shrink: 0;
  }
  .rail-divider {
    width: 28px;
    height: 1px;
    background: var(--llm-panel-border);
    margin: 6px 0;
  }
  .rail-btn {
    width: 36px;
    height: 36px;
    border-radius: 9px;
    border: none;
    background: transparent;
    color: var(--llm-text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    transition: all 0.15s;
  }
  .rail-btn:hover {
    background: var(--llm-panel);
    color: var(--llm-text);
  }
  .rail-btn.active {
    background: rgba(6, 182, 212, 0.15);
    color: var(--llm-accent-solid);
    box-shadow: 0 0 0 1px rgba(6, 182, 212, 0.3);
  }
  .rail-spacer {
    flex: 1;
  }
  .rail-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: linear-gradient(135deg, #8b5cf6, #6366f1);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    font-weight: 700;
    color: white;
    cursor: default;
  }
  .rail-theme-toggle {
    width: 36px;
    height: 20px;
    background: rgba(6, 182, 212, 0.15);
    border: 1px solid rgba(6, 182, 212, 0.35);
    border-radius: 10px;
    cursor: pointer;
    position: relative;
    margin-bottom: 6px;
  }
  .rail-theme-toggle::after {
    content: "";
    position: absolute;
    left: 3px;
    top: 3px;
    width: 12px;
    height: 12px;
    background: var(--llm-accent-solid);
    border-radius: 50%;
    transition: left 0.2s;
  }
  html.dark .rail-theme-toggle::after {
    left: 19px;
  }
  ```

  **3e — Sidebar overlay panel (replaces the old `<aside>` fixed sidebar):**

  ```css
  .sidebar-panel {
    position: absolute;
    left: 56px;
    top: 0;
    bottom: 0;
    width: 240px;
    background: var(--llm-panel);
    border-right: 1px solid var(--llm-panel-border);
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    box-shadow: var(--llm-shadow);
    display: flex;
    flex-direction: column;
    padding: 12px 10px;
    z-index: 15;
    transition:
      transform 0.22s cubic-bezier(0.4, 0, 0.2, 1),
      opacity 0.22s;
  }
  .sidebar-panel.panel-hidden {
    transform: translateX(-8px);
    opacity: 0;
    pointer-events: none;
  }
  .sidebar-new-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    background: rgba(6, 182, 212, 0.1);
    border: 1px solid rgba(6, 182, 212, 0.28);
    border-radius: 9px;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 600;
    color: var(--llm-accent-solid);
    cursor: pointer;
    width: 100%;
    margin-bottom: 12px;
    transition: background 0.15s;
  }
  .sidebar-new-btn:hover {
    background: rgba(6, 182, 212, 0.18);
  }
  .sidebar-section-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--llm-text-muted);
    padding: 0 4px;
    margin-bottom: 4px;
    margin-top: 8px;
  }
  .chat-history-item {
    border-radius: 8px;
    padding: 7px 10px;
    cursor: pointer;
    margin-bottom: 2px;
    transition: background 0.12s;
    position: relative;
  }
  .chat-history-item:hover {
    background: var(--llm-panel);
  }
  .chat-history-item.active {
    background: rgba(6, 182, 212, 0.1);
    border-left: 2px solid var(--llm-accent-solid);
    padding-left: 8px;
  }
  .chat-history-item .item-title {
    font-size: 12px;
    font-weight: 500;
    color: var(--llm-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chat-history-item .item-meta {
    font-size: 10px;
    color: var(--llm-text-muted);
    margin-top: 1px;
  }
  .all-chats-link {
    margin-top: auto;
    padding-top: 10px;
    border-top: 1px solid var(--llm-panel-border);
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    font-size: 12px;
    font-weight: 500;
    color: var(--llm-text-muted);
    cursor: pointer;
    border-radius: 8px;
    transition: all 0.12s;
    border: 1px dashed var(--llm-panel-border);
    margin-top: 8px;
  }
  .all-chats-link:hover {
    color: var(--llm-accent-solid);
    border-color: rgba(6, 182, 212, 0.35);
  }
  ```

  **3f — Scheduled tasks in sidebar:**

  ```css
  .sidebar-section {
    border-top: 1px solid var(--llm-panel-border);
    padding-top: 8px;
    margin-top: 8px;
  }
  .sidebar-section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
    padding: 4px 0;
    font-size: 12px;
    font-weight: 600;
    color: var(--llm-text-muted);
    user-select: none;
  }
  .sidebar-section-header:hover {
    color: var(--llm-text);
  }
  .task-card {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    padding: 8px;
    border-radius: 8px;
    margin-bottom: 6px;
    font-size: 11px;
  }
  .task-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 3px;
  }
  .task-active-badge {
    color: #22c55e;
    font-size: 10px;
  }
  .task-delete-btn {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 12px;
    opacity: 0.6;
    padding: 0 2px;
  }
  .task-delete-btn:hover {
    opacity: 1;
  }
  .task-schedule {
    font-family: monospace;
    color: var(--llm-text-muted);
    font-size: 10px;
    margin-bottom: 2px;
  }
  .task-prompt {
    color: var(--llm-text-muted);
    font-size: 10px;
    font-style: italic;
  }
  .tasks-empty {
    color: var(--llm-text-muted);
    font-size: 11px;
    font-style: italic;
    padding: 4px 0;
  }
  .add-task-btn {
    background: none;
    border: 1px dashed var(--llm-panel-border);
    color: var(--llm-text-muted);
    padding: 4px 10px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 11px;
    margin-top: 4px;
    width: 100%;
  }
  .add-task-btn:hover {
    border-color: var(--llm-accent-solid);
    color: var(--llm-accent-solid);
  }
  .task-input {
    width: 100%;
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    color: var(--llm-text);
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
    margin-top: 4px;
    box-sizing: border-box;
  }
  .btn-save-task {
    background: var(--llm-accent-solid);
    color: white;
    border: none;
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
  }
  .btn-cancel-task {
    background: var(--llm-panel);
    color: var(--llm-text-muted);
    border: 1px solid var(--llm-panel-border);
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 11px;
  }
  ```

  **3g — Main area, topbar:**

  ```css
  .llm-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    position: relative;
  }
  .llm-topbar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 20px;
    border-bottom: 1px solid var(--llm-panel-border);
    background: var(--llm-panel);
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    flex-shrink: 0;
  }
  .topbar-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--llm-text);
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .model-pill {
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 20px;
    padding: 4px 10px 4px 8px;
    font-size: 12px;
    font-weight: 600;
    color: var(--llm-text-muted);
    cursor: pointer;
    transition: all 0.15s;
  }
  .model-pill:hover {
    border-color: rgba(6, 182, 212, 0.4);
    color: var(--llm-text);
  }
  .model-status-dot {
    width: 7px;
    height: 7px;
    background: #22c55e;
    border-radius: 50%;
    box-shadow: 0 0 6px rgba(34, 197, 94, 0.6);
  }
  .mode-pill {
    display: flex;
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 20px;
    padding: 3px;
    gap: 2px;
  }
  .mode-btn {
    padding: 4px 12px;
    border-radius: 14px;
    font-size: 11px;
    font-weight: 600;
    border: none;
    cursor: pointer;
    color: var(--llm-text-muted);
    background: transparent;
    transition: all 0.15s;
  }
  .mode-btn.active-chat {
    background: rgba(255, 255, 255, 0.7);
    color: var(--llm-text);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
  }
  html.dark .mode-btn.active-chat {
    background: rgba(255, 255, 255, 0.12);
  }
  .mode-btn.active-image {
    background: linear-gradient(135deg, #7c3aed, #6366f1);
    color: white;
    box-shadow: 0 2px 8px rgba(124, 58, 237, 0.35);
  }
  ```

  **3h — Messages area:**

  ```css
  .llm-messages {
    flex: 1;
    overflow-y: auto;
    padding: 24px 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-height: 0;
  }
  .llm-messages::-webkit-scrollbar {
    width: 5px;
  }
  .llm-messages::-webkit-scrollbar-thumb {
    background: var(--llm-panel-border);
    border-radius: 10px;
  }
  .message-user {
    align-self: flex-end;
    max-width: 80%;
    background: linear-gradient(135deg, #06b6d4, #0ea5e9);
    border-radius: 16px 16px 3px 16px;
    padding: 11px 16px;
    color: white;
    box-shadow: 0 3px 14px rgba(6, 182, 212, 0.3);
    font-size: 14px;
    line-height: 1.6;
  }
  .message-gemma {
    align-self: flex-start;
    max-width: 85%;
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 16px 16px 16px 3px;
    padding: 11px 16px;
    color: var(--llm-text);
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    box-shadow: 0 2px 12px rgba(139, 92, 246, 0.07);
    font-size: 14px;
    line-height: 1.6;
  }
  .msg-meta {
    font-size: 11px;
    color: var(--llm-text-muted);
    margin-top: 4px;
    padding: 0 4px;
  }
  ```

  **3i — Welcome screen:**

  ```css
  .welcome-screen {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    gap: 14px;
    padding: 40px;
    text-align: center;
  }
  .welcome-logo {
    width: 56px;
    height: 56px;
    background: linear-gradient(135deg, #06b6d4, #0ea5e9);
    border-radius: 16px;
    box-shadow: 0 4px 20px rgba(6, 182, 212, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    font-weight: 800;
    color: white;
  }
  .welcome-title {
    font-size: 22px;
    font-weight: 700;
    color: var(--llm-text);
  }
  .welcome-sub {
    font-size: 14px;
    color: var(--llm-text-muted);
    max-width: 340px;
    line-height: 1.6;
  }
  .welcome-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
    margin-top: 4px;
  }
  .welcome-chip {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 20px;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 500;
    color: var(--llm-text-muted);
    cursor: pointer;
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    transition: all 0.15s;
  }
  .welcome-chip:hover {
    border-color: rgba(6, 182, 212, 0.4);
    color: var(--llm-accent-solid);
  }
  ```

  **3j — Prose / markdown styles:**

  ```css
  .prose pre {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 10px;
    padding: 1rem;
    margin-top: 0.5rem;
    overflow-x: auto;
  }
  .prose code {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.875em;
    background: rgba(139, 92, 246, 0.1);
    padding: 1px 5px;
    border-radius: 4px;
    color: var(--llm-accent-solid);
  }
  .prose pre code {
    background: none;
    padding: 0;
    color: inherit;
  }
  .prose p {
    margin-bottom: 0.75rem;
  }
  .prose p:last-child {
    margin-bottom: 0;
  }
  .prose strong {
    font-weight: 600;
  }
  .prose ul {
    list-style-type: disc;
    padding-left: 1.25rem;
    margin-bottom: 0.75rem;
  }
  .prose ol {
    list-style-type: decimal;
    padding-left: 1.25rem;
    margin-bottom: 0.75rem;
  }
  ```

  **3k — Thinking / reasoning blocks:**

  ```css
  .thought-block {
    background: rgba(139, 92, 246, 0.06);
    border: 1px solid rgba(139, 92, 246, 0.15);
    border-radius: 10px;
    padding: 10px 14px;
    margin-bottom: 10px;
    font-style: italic;
    font-size: 0.85em;
    color: var(--llm-text-muted);
  }
  .reasoning-block {
    border: 1px solid var(--llm-panel-border);
    border-radius: 10px;
    margin-bottom: 8px;
    overflow: hidden;
  }
  .reasoning-block summary {
    cursor: pointer;
    padding: 6px 12px;
    font-size: 0.75em;
    font-weight: 600;
    color: var(--llm-text-muted);
    background: var(--llm-panel);
    user-select: none;
    list-style: none;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .reasoning-block summary::before {
    content: "▶";
    font-size: 0.65em;
    transition: transform 0.15s;
  }
  .reasoning-block[open] summary::before {
    transform: rotate(90deg);
  }
  .reasoning-block .reasoning-body {
    padding: 10px 14px;
    font-size: 0.82em;
    color: var(--llm-text-muted);
    border-top: 1px solid var(--llm-panel-border);
  }
  ```

  **3l — Typing indicator:**

  ```css
  .typing-indicator {
    animation: llm-pulse 1.5s infinite;
  }
  @keyframes llm-pulse {
    0%,
    100% {
      opacity: 0.4;
    }
    50% {
      opacity: 1;
    }
  }
  ```

  **3m — Input area:**

  ```css
  .llm-input-area {
    padding: 14px 20px 20px;
    flex-shrink: 0;
  }
  .llm-input-shell {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 16px;
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    box-shadow: var(--llm-shadow);
    overflow: hidden;
    transition:
      border-color 0.15s,
      box-shadow 0.15s;
  }
  .llm-input-shell:focus-within {
    border-color: rgba(6, 182, 212, 0.5);
    box-shadow:
      0 0 0 3px rgba(6, 182, 212, 0.08),
      var(--llm-shadow);
  }
  .llm-input-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 10px 12px;
  }
  .llm-attach-btn {
    width: 34px;
    height: 34px;
    border-radius: 9px;
    border: none;
    background: transparent;
    color: var(--llm-text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
    transition: all 0.15s;
  }
  .llm-attach-btn:hover {
    color: var(--llm-text);
    background: var(--llm-panel);
  }
  .llm-send-btn {
    width: 34px;
    height: 34px;
    border-radius: 9px;
    border: none;
    background: linear-gradient(135deg, #06b6d4, #0ea5e9);
    color: white;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: all 0.15s;
    box-shadow: 0 2px 8px rgba(6, 182, 212, 0.4);
  }
  .llm-send-btn:hover {
    box-shadow: 0 4px 14px rgba(6, 182, 212, 0.5);
    transform: translateY(-1px);
  }
  .llm-send-btn:disabled {
    opacity: 0.5;
    transform: none;
  }
  .llm-textarea {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    font-family: "Inter", sans-serif;
    font-size: 14px;
    color: var(--llm-text);
    resize: none;
    max-height: 160px;
    line-height: 1.5;
  }
  .llm-textarea::placeholder {
    color: var(--llm-text-muted);
  }
  .llm-input-footer {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px 8px;
    font-size: 11px;
    color: var(--llm-text-muted);
  }
  .drop-zone {
    transition: box-shadow 0.2s;
  }
  .drop-zone.active {
    box-shadow: 0 0 0 2px var(--llm-accent-solid) inset;
  }
  ```

  **3n — Image mode controls:**

  ```css
  .image-controls-row {
    display: none;
    padding: 8px 12px 4px;
    border-top: 1px solid var(--llm-panel-border);
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  .image-controls-row.visible {
    display: flex;
  }
  .img-ctrl {
    display: flex;
    align-items: center;
    gap: 5px;
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
  }
  .img-ctrl label {
    color: var(--llm-text-muted);
    font-weight: 600;
  }
  .img-ctrl select {
    border: none;
    background: transparent;
    font-size: 11px;
    color: var(--llm-text);
    font-weight: 600;
    cursor: pointer;
    outline: none;
  }
  .img-ctrl input[type="range"] {
    width: 56px;
    accent-color: #7c3aed;
    border: none;
    background: transparent;
    cursor: pointer;
  }
  .img-ctrl .steps-val {
    color: var(--llm-text);
    font-weight: 700;
    min-width: 20px;
  }
  .warmup-banner {
    display: none;
    background: rgba(124, 58, 237, 0.1);
    border: 1px solid rgba(124, 58, 237, 0.25);
    border-radius: 10px;
    padding: 7px 12px;
    font-size: 11px;
    color: #7c3aed;
    align-items: center;
    gap: 8px;
    margin: 0 12px 6px;
  }
  .warmup-banner.visible {
    display: flex;
  }
  .warmup-dot {
    width: 6px;
    height: 6px;
    background: #7c3aed;
    border-radius: 50%;
    animation: wdot 1s ease-in-out infinite alternate;
  }
  @keyframes wdot {
    from {
      opacity: 0.4;
    }
    to {
      opacity: 1;
    }
  }
  ```

  **3o — Image card:**

  ```css
  .img-card {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 16px;
    overflow: hidden;
    max-width: 420px;
  }
  .img-card-shimmer {
    height: 220px;
    background: linear-gradient(
      90deg,
      var(--llm-panel) 25%,
      var(--llm-panel-border) 50%,
      var(--llm-panel) 75%
    );
    background-size: 200% 100%;
    animation: shimmer 1.4s infinite;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
  }
  @keyframes shimmer {
    0% {
      background-position: 200% 0;
    }
    100% {
      background-position: -200% 0;
    }
  }
  .img-spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--llm-panel-border);
    border-top-color: #7c3aed;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .img-gen-label {
    font-size: 11px;
    color: var(--llm-text-muted);
    font-weight: 600;
  }
  .img-thumb-wrap {
    position: relative;
    cursor: pointer;
  }
  .img-thumb-wrap:hover .img-expand {
    opacity: 1;
  }
  .img-expand {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 13px;
    font-weight: 600;
    opacity: 0;
    transition: opacity 0.18s;
  }
  .img-thumb {
    width: 100%;
    display: block;
  }
  .img-meta {
    padding: 6px 12px;
    font-size: 11px;
    color: var(--llm-text-muted);
    border-bottom: 1px solid var(--llm-panel-border);
  }
  .img-actions {
    display: flex;
  }
  .img-action-btn {
    flex: 1;
    padding: 7px 0;
    font-size: 11px;
    font-weight: 600;
    color: var(--llm-text-muted);
    background: none;
    border: none;
    border-right: 1px solid var(--llm-panel-border);
    cursor: pointer;
    transition:
      background 0.12s,
      color 0.12s;
  }
  .img-action-btn:last-child {
    border-right: none;
  }
  .img-action-btn:hover {
    background: rgba(6, 182, 212, 0.08);
    color: var(--llm-accent-solid);
  }
  ```

  **3p — Agent trace:**

  ```css
  .agent-trace {
    margin: 8px 0;
    font-size: 12px;
  }
  .trace-summary {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    padding: 6px 10px;
    border-radius: 8px;
    cursor: pointer;
    color: var(--llm-text-muted);
    user-select: none;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .trace-steps {
    padding-left: 8px;
    border-left: 2px solid var(--llm-panel-border);
    margin-top: 4px;
  }
  .trace-step {
    margin: 4px 0;
  }
  .trace-call {
    font-family: monospace;
    color: #22c55e;
    font-size: 11px;
  }
  .trace-result {
    font-family: monospace;
    color: var(--llm-text-muted);
    font-size: 10px;
    padding-left: 12px;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 60px;
    overflow: hidden;
  }
  .agent-done-message {
    padding: 8px 12px;
    color: #22c55e;
    font-size: 13px;
  }
  .agent-error-message {
    padding: 8px 12px;
    color: #ef4444;
    font-size: 13px;
  }
  ```

  **3q — Tool confirm card:**

  ```css
  .confirm-card {
    background: var(--llm-panel);
    border: 1px solid rgba(245, 158, 11, 0.4);
    border-radius: 12px;
    padding: 14px;
    margin: 8px 0;
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    max-width: 440px;
  }
  .confirm-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
    font-weight: 600;
    color: #f59e0b;
    font-size: 13px;
  }
  .confirm-args {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    padding: 8px;
    border-radius: 8px;
    font-family: monospace;
    font-size: 10px;
    margin: 8px 0;
    white-space: pre-wrap;
    color: var(--llm-text-muted);
  }
  .confirm-desc {
    color: var(--llm-text-muted);
    font-size: 11px;
    margin-bottom: 10px;
  }
  .confirm-buttons {
    display: flex;
    gap: 8px;
  }
  .btn-allow {
    background: #22c55e;
    color: white;
    border: none;
    padding: 6px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
  }
  .btn-deny {
    background: rgba(239, 68, 68, 0.12);
    color: #ef4444;
    border: 1px solid rgba(239, 68, 68, 0.3);
    padding: 6px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
  }
  .btn-always {
    background: transparent;
    color: var(--llm-text-muted);
    border: 1px solid var(--llm-panel-border);
    padding: 6px 14px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 11px;
  }
  ```

  **3r — Context menu:**

  ```css
  #context-menu {
    position: fixed;
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 10px;
    box-shadow: var(--llm-shadow);
    padding: 4px;
    z-index: 1000;
    min-width: 160px;
    display: none;
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
  }
  .context-menu-item {
    padding: 8px 12px;
    cursor: pointer;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-radius: 6px;
    color: var(--llm-text);
    transition: background 0.12s;
  }
  .context-menu-item:hover {
    background: var(--llm-panel);
  }
  .context-menu-item.danger {
    color: #ef4444;
  }
  .context-menu-item.danger:hover {
    background: rgba(239, 68, 68, 0.08);
  }
  ```

  **3s — All Chats modal list items:**

  ```css
  .all-chats-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--llm-panel-border);
    cursor: pointer;
    transition: background 0.12s;
  }
  .all-chats-item:hover {
    background: var(--llm-panel);
  }
  .all-chats-item.selected {
    background: rgba(6, 182, 212, 0.08);
  }
  .all-chats-checkbox {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 2px solid var(--llm-panel-border);
    cursor: pointer;
    accent-color: var(--llm-accent-solid);
  }
  ```

  **3t — Modals:**

  ```css
  .modal-overlay {
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    transition: opacity 0.3s;
  }
  .modal-content {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    border-radius: 18px;
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    box-shadow: var(--llm-shadow);
    transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  .hidden-modal {
    opacity: 0;
    pointer-events: none;
  }
  .hidden-modal .modal-content {
    transform: scale(0.95) translateY(16px);
  }
  ```

  **3u — Lightbox:**

  ```css
  .lightbox-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.88);
    z-index: 200;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  .lightbox-overlay.open {
    display: flex;
  }
  .lightbox-inner {
    display: flex;
    gap: 20px;
    max-width: 900px;
    width: 100%;
    align-items: flex-start;
  }
  .lightbox-img-wrap {
    flex: 1;
    min-width: 0;
  }
  .lightbox-img-wrap img {
    width: 100%;
    border-radius: 12px;
    display: block;
  }
  .lightbox-sidebar {
    width: 180px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-top: 4px;
  }
  .lb-title {
    color: white;
    font-size: 14px;
    font-weight: 700;
  }
  .lb-prompt-text {
    color: #9ca3af;
    font-size: 12px;
    line-height: 1.5;
    word-break: break-word;
  }
  .lb-meta-text {
    color: #6b7280;
    font-size: 11px;
  }
  .lb-btn {
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    border: none;
    cursor: pointer;
    width: 100%;
    text-align: center;
  }
  .lb-btn-primary {
    background: #7c3aed;
    color: white;
  }
  .lb-btn-primary:hover {
    background: #6d28d9;
  }
  .lb-btn-secondary {
    background: rgba(255, 255, 255, 0.1);
    color: white;
    margin-top: 4px;
  }
  .lb-btn-secondary:hover {
    background: rgba(255, 255, 255, 0.18);
  }
  .lb-close-btn {
    color: #6b7280;
    font-size: 12px;
    text-align: center;
    cursor: pointer;
    margin-top: 6px;
    background: none;
    border: none;
    width: 100%;
  }
  .lb-close-btn:hover {
    color: white;
  }
  ```

  **3v — Mobile sidebar override:**

  ```css
  @media (max-width: 768px) {
    .sidebar-panel { position: fixed; left: 56px; height: 100%; }
    .sidebar-panel.panel-hidden { display: none; }
  }
  </style>
  </head>
  ```

- [ ] **Step 4: Start the server to confirm the file loads without error**

  ```bash
  cd gemma-web && node server.js &
  ```

  Open http://localhost:3001. Expected: page loads, no JS console errors about missing CSS (there will be missing HTML errors — that's fine at this step).

- [ ] **Step 5: Stop the dev server**

  ```bash
  kill %1
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "feat: add new CSS foundation and token system for LocalLLM redesign"
  ```

---

## Task 2: `<body>` — Icon rail HTML

**Files:**

- Rewrite: `gemma-web/index.html` (body opening through rail)

- [ ] **Step 1: Write the `<body>` opening tag and icon rail**

  Replace the old `<body class="bg-lightBg ...">` with:

  ```html
  <body>
    <!-- ── Icon Rail ── -->
    <div class="rail" id="rail">
      <div class="rail-logo">L</div>

      <button class="rail-btn active" id="rail-chat-btn" title="Chat history">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path
            d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
          />
        </svg>
      </button>

      <button class="rail-btn" id="rail-image-btn" title="Image generation">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
          <circle cx="9" cy="9" r="2" />
          <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
        </svg>
      </button>

      <button
        class="rail-btn"
        id="rail-tasks-btn"
        title="Scheduled tasks"
        onclick="toggleScheduledPanel()"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect width="18" height="18" x="3" y="4" rx="2" ry="2" />
          <line x1="16" x2="16" y1="2" y2="6" />
          <line x1="8" x2="8" y1="2" y2="6" />
          <line x1="3" x2="21" y1="10" y2="10" />
        </svg>
      </button>

      <div class="rail-divider"></div>

      <button class="rail-btn" id="open-settings-btn" title="Settings">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path
            d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 1 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
          />
          <circle cx="12" cy="12" r="3" />
        </svg>
      </button>

      <div class="rail-spacer"></div>

      <button
        class="rail-theme-toggle"
        id="theme-toggle"
        title="Toggle theme"
      ></button>
      <div class="rail-avatar" title="You">O</div>
    </div>
  </body>
  ```

- [ ] **Step 2: Verify rail renders correctly**

  Start the server and open http://localhost:3001. Expected: a narrow 56px column appears on the left. No console errors.

- [ ] **Step 3: Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "feat: add icon rail to LocalLLM redesign"
  ```

---

## Task 3: Sidebar overlay panel HTML

**Files:**

- Rewrite: `gemma-web/index.html` (sidebar section)

- [ ] **Step 1: Write the sidebar overlay panel immediately after the rail `</div>`**

  This element keeps `id="sidebar"` so the existing JS (`sidebar.classList.add("closed")` etc.) keeps working. CSS class `sidebar-panel` provides the new glass styling. Class `panel-hidden` replaces `.closed` for the new open/close toggle.

  ```html
  <!-- ── Sidebar Overlay Panel ── id="sidebar" preserved for JS compat -->
  <div class="sidebar-panel" id="sidebar">
    <!-- New chat button — id="new-chat-btn" preserved -->
    <button class="sidebar-new-btn" id="new-chat-btn">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M5 12h14" />
        <path d="M12 5v14" />
      </svg>
      New Chat
    </button>

    <!-- Starred chats — id="starred-section" and id="starred-list" preserved -->
    <div id="starred-section" class="hidden">
      <div class="sidebar-section-label" style="color:#f59e0b;">★ Starred</div>
      <div id="starred-list"></div>
    </div>

    <!-- Chat history — id="history-list" preserved -->
    <div class="sidebar-section-label">Recents</div>
    <div
      id="history-list"
      style="flex:1;overflow-y:auto;overflow-x:hidden;min-height:0;"
    ></div>

    <!-- Scheduled tasks — ids preserved -->
    <div class="sidebar-section">
      <div class="sidebar-section-header" onclick="toggleScheduledPanel()">
        <span>📅 Scheduled Tasks</span>
        <span id="scheduled-chevron">▼</span>
      </div>
      <div id="scheduled-tasks-body" style="display:none;">
        <div style="margin:8px 0;">
          <div
            style="font-size:11px;font-weight:600;color:var(--llm-accent-solid);margin-bottom:6px;"
          >
            🤖 In-App Tasks
          </div>
          <div id="in-app-tasks-list"></div>
          <button class="add-task-btn" onclick="showAddTaskForm()">
            + Add Task
          </button>
          <div id="add-task-form" style="display:none;">
            <input
              id="new-task-name"
              type="text"
              placeholder="Task name"
              class="task-input"
            />
            <input
              id="new-task-schedule"
              type="text"
              placeholder="Cron (e.g. 0 9 * * *)"
              class="task-input"
            />
            <textarea
              id="new-task-prompt"
              placeholder="Prompt"
              class="task-input"
              rows="2"
              style="resize:vertical;"
            ></textarea>
            <div style="display:flex;gap:6px;margin-top:4px;">
              <button class="btn-save-task" onclick="submitAddTask()">
                Save
              </button>
              <button class="btn-cancel-task" onclick="showAddTaskForm()">
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- All Chats button -->
    <div class="all-chats-link" onclick="showAllChats()">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path
          d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
        />
        <path d="M12 7v10" />
        <path d="M8 11h8" />
      </svg>
      All Chats
    </div>
  </div>
  ```

- [ ] **Step 2: Verify sidebar panel renders**

  Start server. Open http://localhost:3001. Expected: 240px glass panel visible to right of the rail. No errors.

- [ ] **Step 3: Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "feat: add sidebar overlay panel to LocalLLM redesign"
  ```

---

## Task 4: Main area — topbar HTML

**Files:**

- Rewrite: `gemma-web/index.html` (main area + topbar)

- [ ] **Step 1: Open the main area and write the topbar**

  The main area wraps everything that isn't the rail or sidebar. Write it immediately after the sidebar panel closing `</div>`:

  ```html
  <!-- ── Main Area ── -->
  <div class="llm-main">
    <!-- Topbar -->
    <header class="llm-topbar">
      <!-- Mobile menu button — id="mobile-menu-btn" preserved for JS -->
      <button
        id="mobile-menu-btn"
        class="rail-btn md:hidden"
        style="margin-right:4px;"
        title="Menu"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <line x1="4" x2="20" y1="12" y2="12" />
          <line x1="4" x2="20" y1="6" y2="6" />
          <line x1="4" x2="20" y1="18" y2="18" />
        </svg>
      </button>

      <!-- Chat title — id="chat-title" preserved -->
      <div class="topbar-title" id="chat-title">LocalLLM</div>

      <!-- Model selector — id="model-select" preserved -->
      <div class="model-pill">
        <div class="model-status-dot"></div>
        <select
          id="model-select"
          style="border:none;background:transparent;font-size:12px;font-weight:600;color:var(--llm-text-muted);cursor:pointer;outline:none;"
        >
          <option value="gemma4-e4b">gemma4:e4b</option>
          <option value="gemma3:27b">gemma3:27b</option>
          <option value="gemma3:12b">gemma3:12b</option>
          <option value="llama3.2">llama3.2</option>
          <option value="qwen2.5:32b">qwen2.5:32b</option>
          <option value="deepseek-r1:8b">deepseek-r1:8b</option>
        </select>
      </div>

      <!-- Mode pill — id="mode-pill", id="mode-chat-btn", id="mode-image-btn" preserved -->
      <div class="mode-pill" id="mode-pill">
        <button type="button" class="mode-btn active-chat" id="mode-chat-btn">
          💬 Chat
        </button>
        <button type="button" class="mode-btn" id="mode-image-btn">
          🎨 Image
        </button>
      </div>

      <!-- Deep think toggle — id="deep-think-toggle" preserved -->
      <label
        style="display:flex;align-items:center;gap:6px;font-size:11px;font-weight:600;color:var(--llm-text-muted);cursor:pointer;flex-shrink:0;"
        title="Enable extended reasoning"
      >
        <input
          type="checkbox"
          id="deep-think-toggle"
          style="accent-color:var(--llm-accent-solid);"
        />
        Deep Think
      </label>

      <!-- Server status — id="server-status", id="status-dot", id="status-label" preserved -->
      <div
        id="server-status"
        class="hidden"
        style="display:flex;align-items:center;gap:6px;font-size:10px;font-family:monospace;cursor:default;flex-shrink:0;"
      >
        <span
          id="status-dot"
          style="width:8px;height:8px;border-radius:50%;background:#9ca3af;flex-shrink:0;"
        ></span>
        <span id="status-label" style="color:var(--llm-text-muted);"
          >checking…</span
        >
      </div>
    </header>
  </div>
  ```

- [ ] **Step 2: Verify topbar renders**

  Start server. Expected: a glass strip at the top of the main area with title, model dropdown, mode pill.

- [ ] **Step 3: Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "feat: add topbar to LocalLLM redesign"
  ```

---

## Task 5: Messages area + welcome screen HTML

**Files:**

- Rewrite: `gemma-web/index.html` (messages section)

- [ ] **Step 1: Write the messages area and welcome screen** immediately after the closing `</header>`:

  ```html
  <!-- Messages area — id="chat-box" preserved -->
  <main id="chat-box" class="llm-messages drop-zone">
    <!-- Welcome message — id="welcome-message" preserved -->
    <div id="welcome-message" class="welcome-screen">
      <div class="welcome-logo">L</div>
      <div class="welcome-title" id="welcome-greeting">Good morning, Omar</div>
      <div class="welcome-sub">
        LocalLLM is ready. Your models run privately on this machine — no data
        leaves.
      </div>
      <div class="welcome-chips">
        <div
          class="welcome-chip"
          onclick="document.getElementById('user-input').value='Help me write something'; document.getElementById('user-input').focus();"
        >
          ✍️ Help me write
        </div>
        <div
          class="welcome-chip"
          onclick="document.getElementById('user-input').value='Debug this code: '; document.getElementById('user-input').focus();"
        >
          🐍 Debug code
        </div>
        <div
          class="welcome-chip"
          onclick="setMode('image'); document.getElementById('user-input').focus();"
        >
          🎨 Generate image
        </div>
        <div
          class="welcome-chip"
          onclick="document.getElementById('user-input').value='Summarize: '; document.getElementById('user-input').focus();"
        >
          📄 Summarize
        </div>
      </div>
    </div>
  </main>
  ```

- [ ] **Step 2: Add the time-based greeting script** at the end of the `<script>` block (Task 9 will add the full JS):

  Note: this will be wired in Task 9. For now just ensure the `id="welcome-greeting"` element exists.

- [ ] **Step 3: Verify messages area renders**

  Start server. Expected: main area shows the welcome screen centered vertically with logo, greeting, and 4 chips.

- [ ] **Step 4: Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "feat: add messages area and welcome screen to LocalLLM redesign"
  ```

---

## Task 6: Input area HTML

**Files:**

- Rewrite: `gemma-web/index.html` (footer/input section)

- [ ] **Step 1: Write the input area** immediately after the closing `</main>`:

  ```html
    <!-- Input area — id="chat-form", id="user-input", id="send-btn", id="attach-btn" preserved -->
    <footer class="llm-input-area">

      <!-- Typing indicator — id="typing" preserved -->
      <div id="typing" class="hidden typing-indicator" style="font-size:12px;color:var(--llm-accent-solid);font-weight:500;margin-bottom:6px;padding:0 4px;">
        Thinking...
      </div>

      <!-- Attachment preview — id="attachment-preview" preserved -->
      <div id="attachment-preview" class="hidden" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;padding:0 4px;"></div>

      <!-- Warmup banner — id="warmup-banner" preserved -->
      <div class="warmup-banner" id="warmup-banner">
        <div class="warmup-dot"></div>
        <span>Image model warming up · ~16s</span>
        <button type="button" id="warmup-close-btn" style="margin-left:auto;background:none;border:none;cursor:pointer;color:var(--llm-text-muted);font-size:13px;">✕</button>
      </div>

      <form id="chat-form">
        <input type="file" id="file-input" class="hidden" multiple />

        <div class="llm-input-shell">
          <div class="llm-input-row">
            <button type="button" class="llm-attach-btn" id="attach-btn" title="Attach file">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
            </button>

            <textarea
              id="user-input"
              placeholder="Message LocalLLM…"
              rows="1"
              class="llm-textarea"
            ></textarea>

            <button type="submit" class="llm-send-btn" id="send-btn">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>
            </button>
          </div>

          <!-- Image controls — id="image-controls-row" and children preserved -->
          <div class="image-controls-row" id="image-controls-row">
            <div class="img-ctrl">
              <label for="img-size">Size</label>
              <select id="img-size">
                <option value="512x512">512×512</option>
                <option value="768x768">768×768</option>
                <option value="512x768">512×768</option>
              </select>
            </div>
            <div class="img-ctrl">
              <label for="img-steps">Steps</label>
              <input type="range" id="img-steps" min="1" max="12" value="4" />
              <span class="steps-val" id="img-steps-val">4</span>
            </div>
            <div class="img-ctrl">
              <label for="img-style">Style</label>
              <select id="img-style">
                <option value="default">Default</option>
                <option value="photorealistic">Photorealistic</option>
                <option value="anime">Anime</option>
                <option value="sketch">Sketch</option>
              </select>
            </div>
          </div>

          <div class="llm-input-footer">
            <span>⌘↵ to send</span>
            <span style="margin-left:auto;">Local · Private · Fast</span>
          </div>
        </div>
      </form>

    </footer>

  </div><!-- /.llm-main -->
  ```

- [ ] **Step 2: Verify input area renders**

  Start server. Expected: glass input box at the bottom of the main area with attach, textarea, send button.

- [ ] **Step 3: Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "feat: add input area to LocalLLM redesign"
  ```

---

## Task 7: Modals HTML

**Files:**

- Rewrite: `gemma-web/index.html` (modals section — copy from original with CSS class updates)

The modals contain extensive HTML that must be preserved exactly for the JS to work. Copy the Settings modal, All Chats modal, and Lightbox from the original file, then update only these CSS class references:

| Old class                                        | Replace with                                   |
| ------------------------------------------------ | ---------------------------------------------- |
| `bg-white dark:bg-darkSurface` (modal content)   | `modal-content`                                |
| `border-gray-100 dark:border-[#3c3d40]`          | `style="border-color:var(--llm-panel-border)"` |
| `bg-gray-50 dark:bg-[#0e0e11]` (stat cards)      | `style="background:var(--llm-panel)"`          |
| `text-blue-600 dark:text-blue-400` (stat values) | `style="color:var(--llm-accent-solid)"`        |
| `bg-gray-100 dark:bg-gray-800`                   | `style="background:var(--llm-panel)"`          |
| `text-gray-500`                                  | `style="color:var(--llm-text-muted)"`          |
| `text-gray-400`                                  | `style="color:var(--llm-text-muted)"`          |
| `dark:text-white` (modal title)                  | `style="color:var(--llm-text)"`                |

- [ ] **Step 1: Read the modals from the original file**

  ```bash
  sed -n '1253,1700p' gemma-web/index.html.bak
  ```

  (Take a backup of the original before starting the rewrite: `cp gemma-web/index.html gemma-web/index.html.bak`)

- [ ] **Step 2: Write the Settings modal** after the `.llm-main` closing div, updating CSS classes per the table above. Preserve every `id=` attribute exactly.

  The Settings modal has three tabs: Vitals (with System/Agent/Pipeline sub-tabs), Prompt, and Memory. The entire inner HTML structure must be preserved exactly — only change class names for colors to use `var(--llm-*)` tokens.

- [ ] **Step 3: Write the All Chats modal** immediately after the Settings modal. Preserve all IDs.

- [ ] **Step 4: Write the Lightbox** immediately after the All Chats modal. Preserve all IDs.

- [ ] **Step 5: Write the mobile sidebar overlay and context menu**

  ```html
  <!-- Mobile sidebar overlay — id="sidebar-overlay" preserved -->
  <div
    id="sidebar-overlay"
    class="fixed inset-0 z-10 hidden md:hidden"
    style="background:rgba(0,0,0,0.5);"
  ></div>

  <!-- Context menu — id="context-menu" preserved -->
  <div id="context-menu">
    <div class="context-menu-item" onclick="handleContextAction('star')">
      <svg
        id="context-star-icon"
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <polygon
          points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
        />
      </svg>
      <span id="context-star-text">Star</span>
    </div>
    <div class="context-menu-item" onclick="handleContextAction('rename')">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
      </svg>
      Rename
    </div>
    <div
      style="height:1px;background:var(--llm-panel-border);margin:4px 0;"
    ></div>
    <div
      class="context-menu-item danger"
      onclick="handleContextAction('delete')"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <path d="M3 6h18" />
        <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
        <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
      </svg>
      Delete
    </div>
  </div>
  ```

- [ ] **Step 6: Verify modals render**

  Start server. Click the settings button (gear icon in rail). Expected: settings modal opens with glass panel style.

- [ ] **Step 7: Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "feat: add modals and context menu to LocalLLM redesign"
  ```

---

## Task 8: JavaScript — complete port

**Files:**

- Rewrite: `gemma-web/index.html` (`<script>` block)

The JavaScript from the original file is copied in full with these changes only:

1. **DOM variable updates**: The old `sidebar` was an `<aside>`. Now `id="sidebar"` is the overlay panel. Update only these references:
   - `sidebar.classList.add("closed")` → `sidebar.classList.add("panel-hidden")`
   - `sidebar.classList.remove("closed")` → `sidebar.classList.remove("panel-hidden")`
   - Any `.sidebar.closed` CSS reference in JS strings → `.sidebar-panel.panel-hidden`

2. **Branding strings**: Change these string literals (not HTML attributes, not JS variable names):
   - `"Gemma 4"` → `"LocalLLM"` (in `chatTitle.textContent`, `bulkDelete`, `deleteChat`, model display in all-chats list)
   - `"Gemma 4 Local"` → `"LocalLLM"` (in `bulkDelete` and `deleteChat` fallback title)
   - `"gemma_chats"` localStorage key → **DO NOT CHANGE** (would break existing saved chats)
   - The `appendMessage` "Gemma" label → `"LocalLLM"` in the display string

3. **Trace summary accent** (one line): `chevron.style.color = "var(--color-accent)"` → `"var(--llm-accent-solid)"`

4. **setMode adjustments**: The old `setMode` sets `sendBtn.style.background = ""` to reset to default (dark mode: white; light mode: dark). In the new design the send button always uses the cyan gradient. Update:

   ```js
   // Old reset in setMode chat branch:
   sendBtn.style.background = "";
   sendBtn.style.color = "";
   // New — remove these two lines entirely; the CSS class handles it
   ```

5. **`updateThemeUI`**: This function updates `themeIconContainer.innerHTML` (which no longer exists in the rail — we use `rail-theme-toggle` CSS instead). Remove the two lines that set `themeIconContainer.innerHTML` and `theme-text`. Keep the highlight.js theme swap:

   ```js
   function updateThemeUI() {
     const isDark = document.documentElement.classList.contains("dark");
     const hljsTheme = isDark ? "github-dark" : "github";
     document.getElementById("hljs-theme").href =
       `https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/${hljsTheme}.min.css`;
   }
   ```

6. **`renderChatItem`**: Replace the Tailwind-heavy `renderChatItem` function with one using the new CSS classes:

   ```js
   function renderChatItem(chat) {
     return `
       <div onclick="loadChat('${chat.id}')"
            oncontextmenu="showContextMenu(event,'${chat.id}')"
            class="chat-history-item ${currentChatId === chat.id ? "active" : ""}">
         <div class="item-title">${chat.title}</div>
         <div class="item-meta">${formatTimeAgo(chat.timestamp)}</div>
       </div>
     `;
   }
   ```

7. **Add rail toggle logic** at the very end of the `<script>` block (after all existing code):

   ```js
   // ── Rail sidebar toggle ──────────────────────────────────────────────
   const railChatBtn = document.getElementById("rail-chat-btn");
   const sidebarPanel = document.getElementById("sidebar");

   function openSidebar() {
     sidebarPanel.classList.remove("panel-hidden");
     railChatBtn.classList.add("active");
   }
   function closeSidebar() {
     sidebarPanel.classList.add("panel-hidden");
     railChatBtn.classList.remove("active");
   }
   function toggleSidebar() {
     if (sidebarPanel.classList.contains("panel-hidden")) openSidebar();
     else closeSidebar();
   }
   railChatBtn.addEventListener("click", toggleSidebar);

   // Clicking outside closes the panel
   document.addEventListener("click", (e) => {
     if (!sidebarPanel.contains(e.target) && !railChatBtn.contains(e.target)) {
       closeSidebar();
     }
   });

   // Rail image button also sets image mode
   document.getElementById("rail-image-btn").addEventListener("click", () => {
     setMode("image");
     document.getElementById("rail-image-btn").classList.add("active");
     document.getElementById("rail-chat-btn").classList.remove("active");
   });

   // Reset rail-image-btn active state when chat mode selected
   const _origSetMode = setMode;
   // (setMode is already defined above — override it to manage rail state)
   ```

   Actually, wire the image rail button by adding to the existing `setMode` function: at the top of `setMode`, add:

   ```js
   document
     .getElementById("rail-image-btn")
     .classList.toggle("active", mode === "image");
   ```

8. **Welcome greeting**: Add time-based greeting after `renderHistory()` / `loadChat()` init block:

   ```js
   // Time-based greeting
   (function setWelcomeGreeting() {
     const hour = new Date().getHours();
     const period = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";
     const el = document.getElementById("welcome-greeting");
     if (el) el.textContent = `Good ${period}, Omar`;
   })();
   ```

9. **Server status display**: The `updateServerStatus` function sets `statusDot.className` using Tailwind classes. Replace the className assignments with direct style changes:
   ```js
   // Replace className assignments like:
   statusDot.className = `w-2 h-2 rounded-full flex-shrink-0 ${online ? "bg-green-500" : "bg-red-500"}`;
   // With:
   statusDot.style.background = online ? "#22c55e" : "#ef4444";
   statusLabel.textContent = online ? "backend online" : "backend offline";
   statusLabel.style.color = online ? "#22c55e" : "#ef4444";
   ```

- [ ] **Step 1: Copy the full `<script>` block from the original file**

  ```bash
  sed -n '1893,4100p' gemma-web/index.html.bak > /tmp/original_script.js
  wc -l /tmp/original_script.js
  ```

- [ ] **Step 2: Apply change #1** — `sidebar.classList.add/remove("closed")` → `panel-hidden`

  Use search-and-replace. Verify count before and after:

  ```bash
  grep -c '"closed"' /tmp/original_script.js
  ```

- [ ] **Step 3: Apply change #5** — `updateThemeUI` function, remove the `themeIconContainer` and `theme-text` lines.

- [ ] **Step 4: Apply change #6** — `renderChatItem` function replacement.

- [ ] **Step 5: Apply change #2** — branding string literals.

  ```bash
  grep -n '"Gemma 4"' /tmp/original_script.js
  grep -n '"Gemma"' /tmp/original_script.js
  ```

  Update each occurrence to "LocalLLM". Do NOT change `"gemma_chats"` or model IDs like `"gemma4-e4b"`.

- [ ] **Step 6: Apply change #3** — `var(--color-accent)` → `var(--llm-accent-solid)`.

- [ ] **Step 7: Apply change #4** — remove the two `sendBtn.style` reset lines in `setMode`.

- [ ] **Step 8: Apply change #9** — `statusDot.className` → direct style assignments.

- [ ] **Step 9: Paste the modified script into the `<script>` block in index.html**

- [ ] **Step 10: Add the rail toggle logic and welcome greeting** (changes #7 and #8) at the end of the `<script>` block.

- [ ] **Step 11: Close the script and body**

  ```html
    </script>
  </body>
  </html>
  ```

- [ ] **Step 12: Start the server and test basic functionality**

  ```bash
  cd gemma-web && node server.js
  ```

  Open http://localhost:3001. Check:
  - [ ] Chat history panel opens/closes when clicking the chat rail icon
  - [ ] New Chat button creates a new chat
  - [ ] Theme toggle switches between light and dark mode
  - [ ] No JS console errors on load

- [ ] **Step 13: Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "feat: port JavaScript to new LocalLLM redesign"
  ```

---

## Task 9: Full feature verification

**Files:** No code changes — verification only.

Start the server: `cd gemma-web && node server.js`

- [ ] **Chat flow**
  - [ ] Type a message and send → message appears as cyan user bubble
  - [ ] Response streams in → AI message appears as glass bubble
  - [ ] "Thinking..." indicator appears during streaming
  - [ ] Markdown renders (bold, lists, code blocks with syntax highlighting)
  - [ ] Press ⌘+Enter to send (keyboard shortcut works)

- [ ] **Reasoning / thinking blocks**
  - [ ] With deep-think-toggle ON, a response with reasoning shows a collapsible `<details>` block above the message
  - [ ] Clicking the summary expands/collapses the reasoning

- [ ] **Chat history**
  - [ ] Chat appears in sidebar panel after first message
  - [ ] Clicking a history item loads that chat
  - [ ] Right-click on a chat item shows context menu with Star / Rename / Delete
  - [ ] Rename dialog works (browser prompt)
  - [ ] Delete removes the chat

- [ ] **All Chats modal**
  - [ ] "All Chats" link at bottom of sidebar opens modal
  - [ ] Search filters chats by title and message content
  - [ ] Checkbox selection and bulk delete work
  - [ ] Clicking a chat in the modal loads it and closes the modal

- [ ] **File uploads**
  - [ ] Click 📎 → file picker opens
  - [ ] Image file: thumbnail preview appears above input
  - [ ] Text/markdown file: chip preview appears
  - [ ] PDF file: "Processing…" chip → "N pages · indexed" chip after upload
  - [ ] Drag-and-drop file onto the chat area also triggers upload
  - [ ] Remove button (×) on each chip removes the attachment

- [ ] **Image generation mode**
  - [ ] Click 🎨 Image tab in topbar → mode pill switches, image controls appear
  - [ ] Size / Steps / Style dropdowns respond
  - [ ] Submit a prompt → shimmer loading card appears → image card renders
  - [ ] Click image → lightbox opens
  - [ ] Lightbox: Save to disk, Regenerate, Edit prompt buttons all work
  - [ ] Warmup banner appears and can be dismissed

- [ ] **Scheduled tasks**
  - [ ] 📅 icon in rail or sidebar section header expands the tasks panel
  - [ ] "+ Add Task" form shows name / cron / prompt fields
  - [ ] Save creates a task, Cancel hides the form

- [ ] **Settings modal**
  - [ ] Gear icon in rail opens settings
  - [ ] Vitals tab → System / Agent / Pipeline sub-tabs switch
  - [ ] RAM, VRAM, Latency, CPU, Thermal values populate from API
  - [ ] "Run Post-Update Check" button fires and shows results
  - [ ] "Restart Backend" button fires
  - [ ] Prompt tab → system prompt textarea shows current value
  - [ ] Memory tab → memory editor shows current memory, Save Memory works

- [ ] **Agent tool approval**
  - [ ] When agent requests a tool, confirm card appears with amber border
  - [ ] "Allow" posts approval to backend
  - [ ] "Deny" posts denial
  - [ ] "Always Allow" auto-approves for the session

- [ ] **Agent trace**
  - [ ] After a multi-step agent response, trace container shows step count
  - [ ] Click "▼ expand" to see step details with green tool calls

- [ ] **Dark / light mode**
  - [ ] Click the rail theme toggle → switches between lavender/light and deep purple/dark
  - [ ] All panels, bubbles, inputs, modals update correctly
  - [ ] Preference persists on page reload (stored in localStorage)

- [ ] **Commit**

  ```bash
  git add gemma-web/index.html
  git commit -m "test: complete LocalLLM redesign feature verification"
  ```

---

## Task 10: Update THEME.md

**Files:**

- Modify: `gemma-web/THEME.md`

- [ ] **Step 1: Replace the token reference table** with the new `--llm-*` tokens:

  ````markdown
  # LocalLLM UI — Theme Quick Reference

  > Full design rationale: `docs/superpowers/specs/2026-05-10-localllm-redesign-design.md`

  ## Token Reference

  | Token                | Light                    | Dark                     | Use for                                      |
  | -------------------- | ------------------------ | ------------------------ | -------------------------------------------- |
  | `--llm-bg`           | lavender gradient        | deep purple gradient     | `body` background only (gradient, not solid) |
  | `--llm-panel`        | `rgba(255,255,255,0.65)` | `rgba(255,255,255,0.06)` | All glass panels, input shells, modals       |
  | `--llm-panel-border` | `rgba(139,92,246,0.13)`  | `rgba(255,255,255,0.10)` | All borders and dividers                     |
  | `--llm-blur`         | `blur(12px)`             | `blur(12px)`             | `backdrop-filter` on glass panels            |
  | `--llm-text`         | `#1e1b4b`                | `#f0eeff`                | Primary text                                 |
  | `--llm-text-muted`   | `#6d6a8a`                | `#9d9abf`                | Timestamps, labels, placeholders             |
  | `--llm-shadow`       | purple-tinted shadow     | dark shadow              | Box shadows on panels                        |
  | `--llm-accent`       | cyan→sky gradient        | cyan→sky gradient        | Gradient backgrounds (send btn, logo)        |
  | `--llm-accent-solid` | `#06b6d4`                | `#06b6d4`                | Solid accent: borders, text, focus rings     |
  | `--llm-accent-glow`  | `rgba(6,182,212,0.35)`   | `rgba(6,182,212,0.35)`   | Box shadows with glow                        |

  ## The Rules

  1. **Never hardcode a color in a CSS class.** Use a `--llm-*` token.
  2. **Never use retired token names** (`--color-bg`, `--color-surface`, `--color-border`, `--color-text`, `--color-text-muted`, `--color-accent`) — they are undefined.
  3. **Never use `.light` as a selector.** Light values go in `:root`; dark values in `html.dark {}`.
  4. **Name tokens by role, not color.** `--llm-panel` not `--llm-white`.
  5. **Status colors may be hardcoded.** `#22c55e` green, `#ef4444` red, `#f59e0b` amber, `#7c3aed` violet (image gen) — same in both modes.

  ## New component template

  ```css
  .my-panel {
    background: var(--llm-panel);
    border: 1px solid var(--llm-panel-border);
    backdrop-filter: var(--llm-blur);
    -webkit-backdrop-filter: var(--llm-blur);
    color: var(--llm-text);
  }
  .my-panel-label {
    color: var(--llm-text-muted);
  }
  ```
  ````

  ```

  ```

- [ ] **Step 2: Commit**

  ```bash
  git add gemma-web/THEME.md
  git commit -m "docs: update THEME.md to new --llm-* token system"
  ```

---

## Self-Review

**Spec coverage check:**

| Spec section                    | Covered by task                                                 |
| ------------------------------- | --------------------------------------------------------------- |
| CSS Token System                | Task 1 (step 3b)                                                |
| Layout structure                | Tasks 1–6                                                       |
| Icon Rail                       | Task 2                                                          |
| Sidebar Overlay Panel           | Task 3                                                          |
| Topbar                          | Task 4                                                          |
| Welcome Screen                  | Task 5                                                          |
| Chat Messages (AI/user bubbles) | Task 1 (3h) + Task 8 (renderChatItem, appendMessage)            |
| Thinking block                  | Task 1 (3k)                                                     |
| Reasoning `<details>`           | Task 1 (3k) + Task 8 (buildReasoningBlock)                      |
| Tool Approval Card              | Task 1 (3q) + Task 8 (createConfirmCard)                        |
| Agent Trace                     | Task 1 (3p) + Task 8 (createTraceContainer, addTraceStep)       |
| Input Area                      | Task 6                                                          |
| Drop zone                       | Task 1 (3m) + Task 8 (drag/drop handlers)                       |
| Image Generation Mode           | Tasks 1 (3n–3o) + 6 (controls HTML) + 8 (submitImageGeneration) |
| Welcome Screen                  | Task 5 + Task 8 (greeting)                                      |
| Modals                          | Task 7                                                          |
| Dark/light mode                 | Task 1 (3a–3b) + Task 8 (updateThemeUI, themeToggle listener)   |
| Branding "LocalLLM"             | Task 8 (change #2)                                              |
| THEME.md update                 | Task 10                                                         |
| Verification                    | Task 9                                                          |

**Placeholder scan:** None found. All steps include concrete HTML/CSS/JS.

**Type consistency:** All DOM IDs referenced in JS match IDs in HTML. `panel-hidden` class is used consistently in both HTML (not set by default — sidebar starts visible) and JS.

**One ambiguity resolved:** The sidebar starts in what state? Per the original behavior: if `chats.length > 0`, load the first chat and add `"closed"` class. In the new design, `"closed"` maps to `"panel-hidden"`. So: sidebar starts open by default (no `panel-hidden` class on the HTML element), then JS closes it after loading the first chat. This matches original behavior where the sidebar was visible then hidden after chat selection.
