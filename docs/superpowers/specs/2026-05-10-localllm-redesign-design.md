# LocalLLM Frontend Redesign — Design Spec

**Date:** 2026-05-10
**Status:** Approved

## Summary

Full rewrite of `gemma-web/index.html` with a modern glass-and-gradient aesthetic, updated branding from "Gemma 4" to "LocalLLM", and an icon-rail sidebar. All existing features (streaming chat, agent trace, tool approval, image generation, scheduled tasks, file uploads, dark/light mode) are preserved with identical behavior. Only the visual treatment changes.

---

## Design Decisions

| Decision | Choice |
|---|---|
| Aesthetic | Glass & gradient — frosted semi-transparent panels, backdrop blur |
| Dark bg | `linear-gradient(160deg, #0f0c29, #1a1040, #1e1535)` — deep purple/indigo |
| Light bg | `linear-gradient(160deg, #ede9fe, #e0e7ff, #f0f4ff)` — lavender/periwinkle |
| Panels | `rgba(255,255,255,0.06)` dark / `rgba(255,255,255,0.65)` light + `backdrop-filter: blur(12px)` |
| Sidebar | Icon rail (~56px, always visible) + overlay panel (240px) that opens on click |
| Accent | Cyan→Sky `linear-gradient(135deg, #06b6d4, #0ea5e9)` |
| Text (dark) | `#f0eeff` primary, `#9d9abf` muted |
| Text (light) | `#1e1b4b` primary, `#6d6a8a` muted |
| Status colors | `#22c55e` green, `#ef4444` red, `#f59e0b` amber — unchanged |
| Image gen accent | `linear-gradient(135deg, #7c3aed, #6366f1)` — violet, unchanged |
| Branding | "LocalLLM" everywhere; page `<title>` = "LocalLLM"; rail logo = "L" |

---

## CSS Token System

Replace the existing `--color-*` token set with a new set. Light values in `:root`, dark values in `html.dark {}`. The `THEME.md` rules still apply: never hardcode colors in CSS classes.

```css
:root {
  --llm-bg: linear-gradient(160deg, #ede9fe 0%, #e0e7ff 50%, #f0f4ff 100%);
  --llm-panel: rgba(255,255,255,0.65);
  --llm-panel-border: rgba(139,92,246,0.13);
  --llm-blur: blur(12px);
  --llm-text: #1e1b4b;
  --llm-text-muted: #6d6a8a;
  --llm-shadow: 0 4px 24px rgba(139,92,246,0.1);
  --llm-accent: linear-gradient(135deg, #06b6d4, #0ea5e9);
  --llm-accent-solid: #06b6d4;
  --llm-accent-glow: rgba(6,182,212,0.35);
}
html.dark {
  --llm-bg: linear-gradient(160deg, #0f0c29 0%, #1a1040 45%, #1e1535 100%);
  --llm-panel: rgba(255,255,255,0.06);
  --llm-panel-border: rgba(255,255,255,0.1);
  --llm-text: #f0eeff;
  --llm-text-muted: #9d9abf;
  --llm-shadow: 0 4px 24px rgba(0,0,0,0.4);
}
```

The old `--color-bg`, `--color-surface`, `--color-border`, `--color-text`, `--color-text-muted`, `--color-accent` tokens are retired. All existing CSS classes that reference them must be updated to the new tokens.

---

## Layout

```
┌──────┬──────────────────────────────────────────┐
│      │  Topbar (glass, border-bottom)            │
│ Rail │──────────────────────────────────────────│
│      │                                           │
│ 56px │  Messages (scrollable)                    │
│      │                                           │
│      │──────────────────────────────────────────│
│      │  Input area                               │
└──────┴──────────────────────────────────────────┘
         ↑ Sidebar overlay panel slides over this
           when rail chat icon is clicked
```

- `body`: `display:flex`, `height:100vh`, `overflow:hidden`, `background: var(--llm-bg)`
- Rail: `width:56px`, `flex-shrink:0`, `z-index:20`
- Sidebar overlay: `position:absolute; left:56px; width:240px; height:100%`, `z-index:15`, slides in/out with CSS transform + opacity transition
- Main: `flex:1`, `display:flex; flex-direction:column`, `margin-left` is NOT applied — the overlay panel floats over the chat area

---

## Icon Rail

Always visible. Contains:

| Slot | Element | Behavior |
|---|---|---|
| Top | Logo mark "L" | Cyan gradient box, 32×32, no action |
| | Chat icon | Toggles sidebar panel open/closed; `.active` when panel open |
| | Image gen icon | Switches to image mode (same as existing mode pill) |
| | Scheduled tasks icon | Toggles scheduled tasks panel in sidebar |
| | Divider | Visual separator |
| | Settings icon | Opens settings modal |
| Bottom | Theme toggle | Mini pill toggle, switches `html.dark` class |
| | Avatar initials | Shows first letter of a future user profile; no action for now |

Active rail button style: `background: rgba(6,182,212,0.15); box-shadow: 0 0 0 1px rgba(6,182,212,0.3); color: #06b6d4`.

---

## Sidebar Overlay Panel

Opens when the chat rail icon is clicked. Overlays the chat area (does not push it). Closes when clicking outside or clicking the rail icon again.

Contents (top to bottom):
1. **New chat button** — cyan ghost button, full width
2. **Chat history list** — grouped by Today / Yesterday / Older, same data as current sidebar
   - Active item: left border `2px solid #06b6d4`, `background: rgba(6,182,212,0.12)`
   - Right-click context menu: Rename, Delete (existing behavior preserved)
3. **Scheduled tasks sub-section** — collapsible, same task cards as current implementation
4. **All Chats button** — at bottom, same modal trigger as current

---

## Topbar

Glass strip at top of main area. Contains:

- **Conversation title** (truncated) — left
- **Model pill** — green status dot + model name + dropdown chevron — same model-switch behavior
- **Mode toggle** (Chat / Image) — glass pill with two tabs — same behavior as current `.mode-pill`

---

## Chat Messages

| Element | Style |
|---|---|
| AI bubble | `background: var(--llm-panel)`, `border: 1px solid var(--llm-panel-border)`, `border-radius: 16px 16px 16px 3px`, backdrop blur |
| User bubble | `background: var(--llm-accent)` gradient, `border-radius: 16px 16px 3px 16px`, cyan glow shadow |
| Timestamp/model | Small muted text below bubble |
| Thinking block | `background: rgba(139,92,246,0.06)`, `border: 1px solid rgba(139,92,246,0.15)`, italic, muted text |
| Reasoning `<details>` | Same collapsible behavior, restyled with new tokens |
| Code blocks | `background: var(--llm-panel)`, `border: 1px solid var(--llm-panel-border)`, monospace, highlight.js theme unchanged |
| Inline code | `background: rgba(139,92,246,0.1)`, rounded, accent-colored text |

---

## Tool Approval Card

Preserved behavior. Restyled:
- Container: `background: var(--llm-panel)`, `border: 1px solid rgba(245,158,11,0.4)`, `border-radius:12px`, backdrop blur
- Header: amber `#f59e0b`, "⚡ Tool request" label
- Args block: `background: var(--llm-panel)`, monospace, muted
- Buttons: Allow (green), Deny (red ghost), Always Allow (muted ghost) — same callbacks

---

## Agent Trace

Preserved behavior. Restyled:
- Summary row: muted text, `▶` chevron rotates on open
- Steps: left border `2px solid var(--llm-panel-border)`, monospace
- Tool call lines: `#22c55e` green
- Result lines: muted, smaller, indented

---

## Input Area

Glass shell at bottom of main area:
- Outer container: `background: var(--llm-panel)`, `border: 1px solid var(--llm-panel-border)`, `border-radius:16px`, backdrop blur
- Focus state: `border-color: rgba(6,182,212,0.5)`, `box-shadow: 0 0 0 3px rgba(6,182,212,0.08)`
- Attach button (📎): icon button, muted color, hover reveals panel bg
- Textarea: auto-grow, transparent background, `var(--llm-text)` color
- Send button: cyan gradient, `box-shadow: 0 2px 8px rgba(6,182,212,0.4)`, hover lifts
- Footer row: "⌘↵ to send" left, "Local · Private · Fast" right, both muted

Drag-and-drop zone: existing `.drop-zone.active` behavior preserved, border color updated to `#06b6d4`.

Image controls row (visible in image mode): same controls, restyled with new tokens. Violet accent (`#7c3aed`) kept for image-mode elements.

---

## Image Generation Mode

Mode activated by clicking Image tab in topbar or Image rail button.

Preserved:
- Image controls row (model, steps, size selectors)
- Warmup banner
- Image card with shimmer loading state + expand/download overlay
- Violet (`#7c3aed`) accent for image-specific UI elements

Restyled:
- Controls row uses `var(--llm-panel)` background and `var(--llm-panel-border)` border
- Warmup banner: `background: rgba(124,58,237,0.1)`, `border: 1px solid rgba(124,58,237,0.25)`
- Image card: `border-radius:16px`, glass panel style

---

## Welcome Screen

Shown when no active conversation. Centered in the main area:
- Logo mark (56×56, cyan gradient, "L")
- Greeting: "Good morning / afternoon / evening, [name]" (time-based, name = "Omar" for now)
- Subtitle: "LocalLLM is ready. Your models run privately on this machine — no data leaves."
- Prompt chip row: 4 suggestion chips (Write · Debug · Image · Summarize) — clicking pre-fills the input

---

## Modals

All existing modals (settings, all-chats, image preview lightbox) preserved. Restyled:
- Overlay: `background: rgba(0,0,0,0.5)`, `backdrop-filter: blur(4px)`
- Modal content: `background: var(--llm-panel)`, `border: 1px solid var(--llm-panel-border)`, `border-radius:16px`, backdrop blur
- Entry animation: `scale(0.95) translateY(16px)` → `scale(1) translateY(0)`

---

## Implementation Approach

**Full rewrite** of `gemma-web/index.html`. The existing file is ~1700 lines; the rewrite must:

1. Reproduce every JS function and event listener exactly — streaming SSE, tool approval callbacks, image gen pipeline, scheduled task CRUD, chat history persistence, file upload, markdown + highlight.js rendering
2. Replace all CSS with the new token system and glass aesthetic
3. Update all hardcoded strings "Gemma 4" / "Gemma4" / "gemma" (in UI text only — not model names like `gemma3:27b` which come from the backend)
4. Update `THEME.md` to reflect the new token names

The server (`server.js`) and all backend Python files are out of scope.

---

## Files Changed

| File | Change |
|---|---|
| `gemma-web/index.html` | Full rewrite |
| `gemma-web/THEME.md` | Update token reference table to new `--llm-*` names |

---

## Out of Scope

- `gemma-web/server.js` — no changes
- Any Python backend file — no changes
- Adding or removing features — this is a visual-only redesign
- Mobile layout — preserve existing `@media (max-width: 768px)` behavior with updated styling
