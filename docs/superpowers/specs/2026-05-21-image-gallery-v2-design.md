# Image Gallery v2 — Design

**Date:** 2026-05-21
**Status:** Approved (pending spec review)
**Area:** `gemma-web/index.html` (single-file frontend)

## Problem

The image gallery (`showImageGallery`, ~line 3129) is a bare grid of thumbnails
with one-line truncated captions and **no interactivity** — no click handler, no
download, no way to read the full prompt. Meanwhile, images in the chat stream
already have rich tooling (Save / Regenerate / Edit-prompt buttons and a
full-screen lightbox showing the full prompt + metadata), so the gallery is the
poor cousin.

Separately, generated images live only in an in-memory `Map` (`_imageStore`,
line 2808) that is wiped on page reload. So "previously generated" today means
only "generated since the last page load."

## Goals

1. Persist generated images across page reloads.
2. Let users **download** images from the gallery.
3. Let users **see the full prompt** for each image from the gallery.
4. Add quality-of-life features: click-to-lightbox, copy-prompt, search/filter
   by prompt, and delete (single + clear-all).

## Non-Goals

- Server-side image storage. Persistence stays client-side.
- Editing/inpainting images. Out of scope.
- Cross-device sync. IndexedDB is per-browser-profile only.

## Storage Decision: IndexedDB (not localStorage)

A 512×512 PNG is ~400–900 KB; base64 inflates it another ~33%. localStorage's
total budget is ~5 MB **and** `gemma_chats` already occupies it, so localStorage
would fit only ~5 images before risking quota errors that corrupt chat history.

IndexedDB has a much larger quota (hundreds of MB) and is designed for binary/
large data. It is the correct foundation. We store the **same record shape**
`_imageStore` already uses, to minimize churn:

```
store: "images" (keyPath: "id")
record: {
  id,            // string, same id scheme as _imageIdCounter
  prompt,
  image_b64,     // kept as base64 string (consistency with existing render path)
  width, height,
  steps,
  elapsed_ms,
  style,
  size,
  createdAt,     // Date.now() — new field, used for sort order
}
```

We keep `image_b64` as a string (rather than a Blob) because every render path
already does `"data:image/png;base64," + image_b64`; switching to Blobs would
ripple through unrelated code for no real benefit at these volumes.

### Graceful degradation

All IndexedDB calls are wrapped so that if the API is unavailable or throws
(e.g. private browsing), the app **silently falls back to session-only behavior**
— the in-memory `Map` still works, nothing hard-fails, errors are `console.warn`-ed.

## Architecture

### New module: IndexedDB wrapper

A small set of promise-returning helpers near the image-mode state block:

- `_imgDBOpen()` → opens/creates DB + `images` store (memoized).
- `_imgDBPut(record)` → write one record.
- `_imgDBGetAll()` → read all records.
- `_imgDBDelete(id)` → delete one record.
- `_imgDBClear()` → clear the store.

Each is a thin `try/catch` wrapper; failures resolve to a no-op / empty result.

### Generate flow (minimal change)

`appendImageCard` (line 2861) keeps calling `_storeImageData(data)` (the
in-memory Map remains the fast cache that lightbox/save handlers read from).
We extend `_storeImageData` to also stamp `createdAt` and fire `_imgDBPut`
(fire-and-forget; not awaited so generation UX is unaffected).

### Page-load rehydration

On startup, after the Map is declared, call an async `_rehydrateImages()` that:

1. `_imgDBGetAll()` → load records into `_imageStore`.
2. Set `_imageIdCounter` to the max numeric id seen, so new ids never collide
   with persisted ones.

Because `openLightbox`, the Save/Regenerate/Edit handlers, and the gallery all
read from `_imageStore`, persisted images work in every existing code path with
no further changes.

### Shared download helper (targeted dedup)

There are currently three copies of the `<a download="generated.png">` anchor
trick (chat-card Save line ~5322, lightbox Save line ~5350, and we need a third
for the gallery). Replace them with one helper:

```
function downloadImage(data) {
  const slug = (data.prompt || "image")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 40) || "image";
  const a = document.createElement("a");
  a.href = "data:image/png;base64," + data.image_b64;
  a.download = `localllm-${slug}-${data.id ?? ""}.png`.replace(/-+\.png$/, ".png");
  a.click();
}
```

This upgrades all download paths (chat card, lightbox, gallery) to descriptive
filenames like `localllm-a-red-fox-7.png` instead of `generated.png`.
(Requires that records carry their `id`; we add `id` into the stored `data`.)

### Gallery modal rewrite (`showImageGallery`)

Rebuilt to render from `_imageStore`, sorted by `createdAt` descending
(newest first). Structure:

**Header:** title + image count, a **search input** (filters cards by prompt
substring, case-insensitive — mirrors All-Chats search at line 3213), a
**Clear all** button, and the existing Close button.

**Grid card** (per image):
- Thumbnail — `click → openLightbox(id)` (delivers full prompt + metadata +
  Save/Regenerate/Edit, all already built).
- Caption: prompt (clamped to ~2 lines, not single-line truncate).
- Action row:
  - **Copy prompt** → `navigator.clipboard.writeText(data.prompt)`, with a brief
    "Copied!" affordance.
  - **Download** → `downloadImage(data)`.
  - **Delete (✕)** → removes from `_imageStore` + `_imgDBDelete(id)`, re-renders.
    Single click, **no confirm** (low-stakes per-item action).

**Clear all** → `confirm(...)` (mirrors `bulkDelete` at line 3302), then
`_imageStore.clear()` + `_imgDBClear()` + re-render.

**Search** is re-render-on-input: keep a module-scoped `_galleryQuery` string and
a `renderGalleryGrid()` that filters before building cards (same shape as
`renderAllChats`).

### Z-index note

The gallery modal is `z-index:300`. Implementation must confirm the
`lightbox-overlay` sits **above** the gallery (so clicking a gallery thumbnail
shows the lightbox on top, and closing it returns to the gallery). If not,
adjust the lightbox overlay's z-index.

## Error Handling

- IndexedDB open/read/write/delete failures: caught, `console.warn`, degrade to
  session-only. Never throw into UI flow.
- `navigator.clipboard` may be unavailable on insecure origins: wrap in
  `try/catch`; on failure, no crash (optionally fall back to a hidden textarea +
  `execCommand`, but only if trivial — otherwise just warn).

## Testing & Verification

- No JS unit-test harness exists; the repo's pytest suite is backend-only.
- Verification per `CLAUDE.md` Definition of Done:
  1. `bash .git/hooks/pre-push` must exit 0 (prettier + ruff + pytest unaffected,
     but formatting of `index.html` must pass prettier).
  2. Manual browser sanity check of: generate → reload → image still in gallery;
     click thumbnail → lightbox; copy prompt; download (descriptive filename);
     delete one; clear all; search filter. Can be driven via Claude-in-Chrome.

## Rollout / Risk

- Pure additive frontend change; no backend or API change.
- Worst case (IndexedDB blocked) reverts to today's session-only behavior.
- No existing feature removed (honors Feature Integrity mandate).
