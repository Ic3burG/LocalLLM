# Dark & Light Mode Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all dark/light mode breakage in the Gemma 4 chat UI so every component renders correctly in both themes, and establish the token system and rules doc for future work.

**Architecture:** All changes are in `gemma-web/index.html` (one `<style>` block and one `<script>` block) plus a new `gemma-web/THEME.md`. The root cause is that CSS custom properties default to dark values and override with a `.light` class that JavaScript never applies — fixing the selector to `html.dark` wires both systems to the same toggle. Token renames follow mechanically.

**Tech Stack:** Vanilla HTML/CSS/JS, Tailwind CSS (CDN, class-based dark mode), highlight.js (CDN)

---

## Files

- **Modify:** `gemma-web/index.html` — `<style>` block (lines 27–134), `<link>` tag (line 9), and `updateThemeUI()` function (line 324)
- **Create:** `gemma-web/THEME.md` — standalone quick-reference design rules

---

## Task 1: Fix CSS variable definitions (root cause)

**Files:**
- Modify: `gemma-web/index.html` lines 79–92

Replace the `:root` (dark defaults) + `.light` (never-applied overrides) block with `:root` (light defaults) + `html.dark` (dark overrides). This single change fixes every CSS-var-driven component at once.

- [ ] **Step 1: Replace the variable block**

Find this exact block in `gemma-web/index.html` (lines 79–92):

```css
        /* CSS variables for agent UI */
        :root {
            --accent: #3b82f6;
            --border: #3c3d40;
            --surface: #1e1f20;
            --text-secondary: #9ca3af;
            --bg: #0e0e11;
        }
        .light {
            --border: #e5e7eb;
            --surface: #f9fafb;
            --text-secondary: #6b7280;
            --bg: #f8f9fa;
        }
```

Replace with:

```css
        /* CSS variables for agent UI — light is default, html.dark overrides */
        :root {
            --color-bg:         #f8f9fa;
            --color-surface:    #ffffff;
            --color-border:     #e5e7eb;
            --color-text:       #111827;
            --color-text-muted: #6b7280;
            --color-accent:     #3b82f6;
        }
        html.dark {
            --color-bg:         #0e0e11;
            --color-surface:    #1e1f20;
            --color-border:     #3c3d40;
            --color-text:       #f3f4f6;
            --color-text-muted: #9ca3af;
        }
```

- [ ] **Step 2: Verify the block is correct**

```bash
grep -n "color-bg\|color-surface\|color-border\|color-text\|color-accent\|html.dark\|\.light {" gemma-web/index.html
```

Expected: lines containing `--color-*` definitions and `html.dark {`. **No** `.light {` line should appear.

- [ ] **Step 3: Quick smoke check in browser**

Open http://localhost:3001 and reload. Toggle the theme via the sidebar button. The sidebar background, chat area, and form border should visibly switch between light and dark. The agent trace panel and task cards may still look wrong — those are fixed in Task 2.

- [ ] **Step 4: Commit**

```bash
git add gemma-web/index.html
git commit -m "fix: wire CSS vars to html.dark — fixes root cause of theme not switching"
```

---

## Task 2: Rename old token names throughout CSS

**Files:**
- Modify: `gemma-web/index.html` `<style>` block

All CSS classes still reference the old token names. None of those are defined anymore. This task renames every occurrence to the new `--color-*` names.

- [ ] **Step 1: Run bulk renames**

```bash
cd gemma-web

sed -i '' 's/var(--surface)/var(--color-surface)/g' index.html
sed -i '' 's/var(--border)/var(--color-border)/g' index.html
sed -i '' 's/var(--bg)/var(--color-bg)/g' index.html
sed -i '' 's/var(--text-secondary)/var(--color-text-muted)/g' index.html
sed -i '' 's/var(--accent, #a78bfa)/var(--color-accent)/g' index.html
sed -i '' 's/var(--text, #fff)/var(--color-text)/g' index.html

cd ..
```

- [ ] **Step 2: Verify no old names remain**

```bash
grep -n "var(--surface)\|var(--border)\|var(--bg)\|var(--text-secondary)\|var(--accent,\|var(--text," gemma-web/index.html
```

Expected: **no output**. If any lines appear, fix them manually using the same rename mapping.

- [ ] **Step 3: Verify new names are present**

```bash
grep -c "var(--color-" gemma-web/index.html
```

Expected: `17` (one per token usage across all CSS classes).

- [ ] **Step 4: Reload and verify in browser**

Toggle to light mode. Verify:
- Sidebar scheduled tasks panel: light background, dark text
- Task input fields: white background, dark text (not invisible white-on-white)
- Agent trace summary: light gray background with muted text
- Confirm card (visible when agent runs a risky tool): light background with amber border

Toggle back to dark and verify all of the above look correct in dark too.

- [ ] **Step 5: Commit**

```bash
git add gemma-web/index.html
git commit -m "fix: rename CSS vars to --color-* semantic token names"
```

---

## Task 3: Fix hardcoded colors in prose, scrollbar, and thought-block

**Files:**
- Modify: `gemma-web/index.html` lines 36, 39–40, 47–50, 67–77

Three areas still use hardcoded hex values that do not change with the theme. Replace them with tokens and remove the now-dead `.light` override rules.

- [ ] **Step 1: Fix the scrollbar thumb (line 36)**

Find:
```css
        ::-webkit-scrollbar-thumb { background: #3c3d40; border-radius: 10px; }
```

Replace with:
```css
        ::-webkit-scrollbar-thumb { background: var(--color-border); border-radius: 10px; }
```

- [ ] **Step 2: Fix prose pre and code (lines 39–40)**

Find:
```css
        .prose pre { background-color: #1e1f20; border-radius: 0.75rem; padding: 1rem; margin-top: 0.5rem; overflow-x: auto; }
        .prose code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.875em; color: #60a5fa; }
```

Replace with:
```css
        .prose pre { background-color: var(--color-surface); border-radius: 0.75rem; padding: 1rem; margin-top: 0.5rem; overflow-x: auto; }
        .prose code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.875em; color: var(--color-accent); }
```

- [ ] **Step 3: Delete the four dead .light and .dark overrides (lines 47–50)**

Find and delete these four lines entirely:
```css
        .dark .prose pre { background-color: #111114; }
        .light .prose pre { background-color: #f1f3f5; }
        .light .prose code { color: #1d4ed8; }
        .light ::-webkit-scrollbar-thumb { background: #cbd5e1; }
```

The token approach above makes them redundant.

- [ ] **Step 4: Fix thought-block (lines 67–77)**

Find:
```css
        .thought-block { 
            background: rgba(59, 130, 246, 0.05); 
            border-left: 3px solid #3b82f6; 
            padding: 10px 15px; 
            margin-bottom: 15px; 
            border-radius: 0 8px 8px 0; 
            font-style: italic; 
            font-size: 0.85em; 
            color: #6b7280;
        }
        .dark .thought-block { background: rgba(59, 130, 246, 0.1); color: #9ca3af; }
```

Replace with (token handles color; background opacity difference is dropped in favour of a single neutral value):
```css
        .thought-block { 
            background: rgba(59, 130, 246, 0.07); 
            border-left: 3px solid #3b82f6; 
            padding: 10px 15px; 
            margin-bottom: 15px; 
            border-radius: 0 8px 8px 0; 
            font-style: italic; 
            font-size: 0.85em; 
            color: var(--color-text-muted);
        }
```

- [ ] **Step 5: Verify no .light selectors remain**

```bash
grep -n "\.light" gemma-web/index.html
```

Expected: **no output**.

- [ ] **Step 6: Verify no hardcoded dark hex colors remain in CSS**

```bash
grep -n "#1e1f20\|#3c3d40\|#0e0e11\|#9ca3af\|#60a5fa\|#6b7280\|#1d4ed8\|#cbd5e1\|#111114" gemma-web/index.html
```

Expected: **no output**.

- [ ] **Step 7: Reload and verify in browser**

In light mode:
- Scrollbar thumb is light gray
- Code blocks have a white/light background
- Inline code spans are blue
- Thought/reasoning blocks show muted gray text on a faint blue tint

In dark mode: all the above still look correct.

- [ ] **Step 8: Commit**

```bash
git add gemma-web/index.html
git commit -m "fix: prose, scrollbar, thought-block use CSS tokens instead of hardcoded colors"
```

---

## Task 4: highlight.js theme swaps with the toggle

**Files:**
- Modify: `gemma-web/index.html` line 9 (link tag) and `updateThemeUI()` function (~line 324)

highlight.js always loads `github-dark.min.css`. In light mode it should use `github.min.css`. The fix adds an `id` to the link element and swaps its `href` inside `updateThemeUI()`.

- [ ] **Step 1: Add id to the highlight.js stylesheet link (line 9)**

Find:
```html
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
```

Replace with:
```html
    <link id="hljs-theme" rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
```

- [ ] **Step 2: Add two lines to updateThemeUI()**

Find the closing lines of `updateThemeUI()`:
```javascript
            document.getElementById('theme-text').textContent = isDark ? 'Switch to Light' : 'Switch to Dark';
        }
```

Replace with:
```javascript
            document.getElementById('theme-text').textContent = isDark ? 'Switch to Light' : 'Switch to Dark';
            const hljsTheme = isDark ? 'github-dark' : 'github';
            document.getElementById('hljs-theme').href =
                `https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/${hljsTheme}.min.css`;
        }
```

- [ ] **Step 3: Verify in browser**

Send a message that produces a code block (e.g. "write hello world in python"). Toggle the theme. The code block should switch: dark background with coloured tokens in dark mode, white background with dark tokens in light mode.

- [ ] **Step 4: Commit**

```bash
git add gemma-web/index.html
git commit -m "fix: highlight.js swaps github-dark/github theme on toggle"
```

---

## Task 5: Create gemma-web/THEME.md

**Files:**
- Create: `gemma-web/THEME.md`

A short standalone reference that lives next to `index.html`. Anyone adding new UI opens this first.

- [ ] **Step 1: Create the file**

Create `gemma-web/THEME.md`:

```markdown
# Gemma 4 UI — Theme Quick Reference

> Full design rationale: `docs/superpowers/specs/2026-04-28-dark-light-mode-design.md`

## Token Reference

| Token | Light | Dark | Use for |
|---|---|---|---|
| `--color-bg` | `#f8f9fa` | `#0e0e11` | Page background, modal/card background |
| `--color-surface` | `#ffffff` | `#1e1f20` | Cards, inputs, code arg blocks |
| `--color-border` | `#e5e7eb` | `#3c3d40` | All borders, dividers, separator lines |
| `--color-text` | `#111827` | `#f3f4f6` | Primary text, input values |
| `--color-text-muted` | `#6b7280` | `#9ca3af` | Timestamps, labels, placeholders |
| `--color-accent` | `#3b82f6` | `#3b82f6` | Focus rings, active states, buttons |

## The Rules

1. **Never hardcode a color in a CSS class.** Use a `--color-*` token.
2. **Never use retired token names** (`--bg`, `--surface`, `--border`, `--text-secondary`, `--accent`) — they are undefined and will silently produce wrong colors.
3. **Never use `.light` as a selector.** It is never applied by JavaScript. Light values go in `:root`; dark values go in `html.dark {}`.
4. **Name tokens by role, not color.** `--color-surface` not `--color-white`.
5. **Status colors may be hardcoded.** Green `#22c55e`, red `#ef4444`, amber `#f59e0b` are the same in both modes.

## Which system to use

| Where you are writing | System to use |
|---|---|
| Inside a CSS class in `<style>` | `var(--color-*)` tokens |
| Directly on an HTML element | Tailwind `dark:` utilities |

Do not mix both systems on the same element.

## New component template

CSS class (in the style block):

```css
.my-panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    color: var(--color-text);
}
.my-panel-label {
    color: var(--color-text-muted);
}
```

HTML element (inline Tailwind):

```html
<div class="bg-white dark:bg-darkSurface border border-gray-200 dark:border-[#3c3d40]">
```

## Checklist before shipping new UI

- [ ] CSS class colors use `--color-*` tokens
- [ ] HTML element colors use Tailwind `dark:` utilities
- [ ] No `.light` selectors added
- [ ] No retired token names used
- [ ] Theme toggled manually — both modes verified visually
```

- [ ] **Step 2: Verify the file exists and is non-empty**

```bash
wc -l gemma-web/THEME.md
```

Expected: 60+ lines.

- [ ] **Step 3: Commit**

```bash
git add gemma-web/THEME.md
git commit -m "docs: add gemma-web/THEME.md quick-reference for dark/light mode rules"
```

---

## Final Verification

- [ ] **Full end-to-end check in light mode**

Open http://localhost:3001. Toggle to light mode. Verify:

| Area | Expected in light mode |
|---|---|
| Sidebar background | White |
| Sidebar task cards | Light background, dark text |
| Task input fields | White background, dark text |
| Scheduled tasks section border | Light gray, visible |
| Chat form | White background, light gray border |
| Code blocks | White background, dark syntax tokens |
| Inline `code` spans | Blue text |
| Scrollbar thumb | Light gray |
| Thought/reasoning blocks | Faint blue tint, gray muted text |
| Confirm card (agent risky tool) | Light background, amber border |

- [ ] **Full end-to-end check in dark mode**

Toggle to dark mode. Verify all areas above look correct with dark backgrounds and light text.

- [ ] **Regression check — Tailwind-controlled elements**

Verify the following are unaffected (they use Tailwind `dark:` utilities, not CSS vars):
- Main chat header
- Message bubbles (user and assistant)
- Settings modal
- Send button
- New Chat button
