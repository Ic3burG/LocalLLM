# Dark & Light Mode Design — Spec

**Date:** 2026-04-28
**Scope:** `gemma-web/index.html`
**Approach:** Fix CSS variable wiring + semantic token rename + written design rules

---

## Problem

The site has two theming mechanisms that are not in sync:

1. **Tailwind `dark:` utilities** — switch when `<html>` receives the `dark` class (set by the JS toggle).
2. **CSS custom properties** — defined in `:root` (dark defaults) and overridden in `.light`. The `.light` class is **never applied** by the JS toggle, so all CSS-var-driven components are permanently stuck in dark mode regardless of which theme is active.

This causes every agent/sidebar component (trace panel, confirm cards, task cards, task inputs, sidebar sections) to render with dark backgrounds and borders on a white page in light mode. Code blocks always show the dark highlight.js theme. The scrollbar always shows a dark thumb. One CSS variable (`--text`) is referenced but never defined, causing a white-on-white text bug in task inputs.

---

## Solution Overview

Three coordinated changes:

1. **Fix the CSS variable wiring** — swap `:root`/`.light` to `:root` (light defaults) / `html.dark` (dark overrides). This aligns with Tailwind's toggle mechanism and fixes the root cause in one block.
2. **Rename tokens to semantic names** — `--surface` → `--color-surface`, etc. Add the missing `--color-text` token.
3. **Fix hardcoded colors** — prose, scrollbar, thought-block switch to tokens. highlight.js swaps stylesheets on theme toggle.

---

## Token System

### CSS Variable Definitions

```css
/* Light mode is the default — no class needed */
:root {
  --color-bg:         #f8f9fa;
  --color-surface:    #ffffff;
  --color-border:     #e5e7eb;
  --color-text:       #111827;
  --color-text-muted: #6b7280;
  --color-accent:     #3b82f6;  /* same in both modes */
}

/* Dark mode overrides — matches Tailwind's html.dark toggle */
html.dark {
  --color-bg:         #0e0e11;
  --color-surface:    #1e1f20;
  --color-border:     #3c3d40;
  --color-text:       #f3f4f6;
  --color-text-muted: #9ca3af;
}
```

### Token Reference

| Token | Light | Dark | Use for |
|---|---|---|---|
| `--color-bg` | `#f8f9fa` | `#0e0e11` | Page background, confirm card background |
| `--color-surface` | `#ffffff` | `#1e1f20` | Cards, inputs, code arg blocks, panel backgrounds |
| `--color-border` | `#e5e7eb` | `#3c3d40` | All borders, dividers, trace step lines |
| `--color-text` | `#111827` | `#f3f4f6` | Primary text, input values, interactive labels |
| `--color-text-muted` | `#6b7280` | `#9ca3af` | Timestamps, descriptions, placeholders |
| `--color-accent` | `#3b82f6` | `#3b82f6` | Focus rings, active states, accent buttons |

### Old → New Token Names (retired)

| Old name | New name |
|---|---|
| `--bg` | `--color-bg` |
| `--surface` | `--color-surface` |
| `--border` | `--color-border` |
| `--text-secondary` | `--color-text-muted` |
| `--accent` | `--color-accent` |
| *(undefined)* | `--color-text` ← new |

---

## Component Fixes

### Fix 1 — Token variable definitions (~20 lines)
Replace the `:root` (dark defaults) + `.light` (never-applied overrides) block with `:root` (light defaults) + `html.dark` (dark overrides).

### Fix 2 — Rename all old token names (~15 occurrences)
Find-and-replace throughout all CSS classes in `<style>`:
- `var(--surface)` → `var(--color-surface)`
- `var(--border)` → `var(--color-border)`
- `var(--bg)` → `var(--color-bg)`
- `var(--text-secondary)` → `var(--color-text-muted)`
- `var(--accent` → `var(--color-accent`
- `var(--text, #fff)` → `var(--color-text)` (removes broken fallback)

### Fix 3 — Prose and scrollbar use tokens (4 rules)
Replace hardcoded hex values with tokens. Remove the now-redundant `.light` overrides:
```css
/* before */
.prose pre { background-color: #1e1f20; }
.prose code { color: #60a5fa; }
::-webkit-scrollbar-thumb { background: #3c3d40; }
.light .prose pre { background-color: #f1f3f5; }   /* removed */
.light .prose code { color: #1d4ed8; }              /* removed */
.light ::-webkit-scrollbar-thumb { background: #cbd5e1; } /* removed */

/* after */
.prose pre { background-color: var(--color-surface); }
.prose code { color: var(--color-accent); }
::-webkit-scrollbar-thumb { background: var(--color-border); }
```

### Fix 4 — thought-block uses token (2 lines)
```css
/* before */
.thought-block { color: #6b7280; }
.dark .thought-block { color: #9ca3af; }

/* after */
.thought-block { color: var(--color-text-muted); }
```

### Fix 5 — highlight.js theme swaps on toggle (~8 lines)
Add `id="hljs-theme"` to the stylesheet link. In `updateThemeUI()`, swap the `href` between `github-dark.min.css` (dark) and `github.min.css` (light) based on the current theme.

```html
<!-- before -->
<link rel="stylesheet" href="...github-dark.min.css">

<!-- after -->
<link id="hljs-theme" rel="stylesheet" href="...github-dark.min.css">
```

```js
// added to updateThemeUI()
const theme = isDark ? 'github-dark' : 'github';
document.getElementById('hljs-theme').href =
  `https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/${theme}.min.css`;
```

---

## Design Rules

These rules apply to all future UI work in `gemma-web/index.html`.

### The Two Systems

This project uses two complementary mechanisms wired to the same theme toggle:

- **Tailwind `dark:` utilities** — used directly on HTML elements. Switch automatically when `<html>` has the `dark` class.
- **CSS custom properties (tokens)** — used inside `<style>` CSS class definitions. Defined in `:root` (light) and overridden in `html.dark` (dark).

**Do not mix systems on the same element.** HTML elements use Tailwind `dark:`. CSS class definitions use tokens.

### Rules

**Rule 1 — Never hardcode a color in a CSS class.**
If you are writing a CSS class that sets `background`, `color`, or `border-color`, it must use a `--color-*` token. Hardcoded hex values break one of the two modes.

**Rule 2 — Never use the retired token names.**
`--bg`, `--surface`, `--border`, `--text-secondary`, `--accent` are no longer defined. Using them silently produces invisible or wrong colors.

**Rule 3 — Never use `.light` as a CSS selector.**
The `.light` class is never applied by the JS toggle. Light-mode values belong in `:root` as the default. Dark-mode overrides belong in `html.dark { }`.

**Rule 4 — Name tokens by role, not by color.**
`--color-surface` not `--color-white`. The value changes per theme; the role does not.

**Rule 5 — Status and accent colors may be hardcoded.**
Green (`#22c55e`), red (`#ef4444`), and amber (`#f59e0b`) are intentionally the same in both modes. These do not require tokens.

### New Component Checklist

Before shipping any new UI component:
- [ ] All CSS class colors use `--color-*` tokens
- [ ] Inline HTML colors use Tailwind `dark:` utilities
- [ ] No `.light` selectors added
- [ ] No retired token names used
- [ ] Manually toggled the theme and verified both modes visually

### Quick-Reference Template

```css
/* ✅ Correct — CSS class using tokens */
.my-panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  color: var(--color-text);
}
.my-panel-subtitle {
  color: var(--color-text-muted);
}
```

```html
<!-- ✅ Correct — inline HTML using Tailwind dark: -->
<div class="bg-white dark:bg-darkSurface border border-gray-200 dark:border-[#3c3d40]">
```

```css
/* ❌ Wrong — hardcoded color in CSS class */
.my-panel { background: #1e1f20; }

/* ❌ Wrong — .light selector */
.light .my-panel { background: #fff; }

/* ❌ Wrong — retired token name */
.my-panel { background: var(--surface); }
```
