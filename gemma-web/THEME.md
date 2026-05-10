# LocalLLM UI — Theme Quick Reference

> Full design rationale: `docs/superpowers/specs/2026-05-10-localllm-redesign-design.md`

## Token Reference

| Token                    | Light                        | Dark                         | Use for                                    |
|--------------------------|------------------------------|------------------------------|--------------------------------------------|
| `--llm-bg`               | lavender gradient            | deep purple gradient         | `body` background only (gradient, not solid) |
| `--llm-panel`            | `rgba(255,255,255,0.65)`     | `rgba(255,255,255,0.06)`     | All glass panels, input shells, modals     |
| `--llm-panel-border`     | `rgba(139,92,246,0.13)`      | `rgba(255,255,255,0.10)`     | All borders and dividers                   |
| `--llm-blur`             | `blur(12px)`                 | `blur(12px)`                 | `backdrop-filter` on glass panels          |
| `--llm-text`             | `#1e1b4b`                    | `#f0eeff`                    | Primary text                               |
| `--llm-text-muted`       | `#6d6a8a`                    | `#9d9abf`                    | Timestamps, labels, placeholders           |
| `--llm-shadow`           | purple-tinted shadow         | dark shadow                  | Box shadows on panels                      |
| `--llm-accent`           | cyan→sky gradient            | cyan→sky gradient            | Gradient backgrounds (send btn, logo)      |
| `--llm-accent-solid`     | `#06b6d4`                    | `#06b6d4`                    | Solid accent: borders, text, focus rings   |
| `--llm-accent-glow`      | `rgba(6,182,212,0.35)`       | `rgba(6,182,212,0.35)`       | Box shadows with glow                      |

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
