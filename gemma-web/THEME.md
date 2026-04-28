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
