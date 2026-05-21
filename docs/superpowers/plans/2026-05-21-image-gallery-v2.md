# Image Gallery v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist generated images across page reloads (IndexedDB) and enrich the image gallery with click-to-lightbox, download, copy-prompt, prompt-based filenames, search, and delete.

**Architecture:** All work is in the single-file frontend `gemma-web/index.html`. An IndexedDB layer persists each generated image; the existing in-memory `_imageStore` Map stays as the read cache that every existing handler (lightbox, Save, Regenerate, Edit) uses, and is rehydrated from IndexedDB on load. The gallery modal is rewritten to render from that Map with per-card actions, reusing the already-built lightbox.

**Tech Stack:** Vanilla JS, IndexedDB, plain DOM. No build step. Lint/format gate: `ruff` (Python, unaffected) + `prettier` (HTML/JS).

**Testing note:** This frontend has no JS unit-test harness; the repo's pytest suite is backend-only. Per `CLAUDE.md`, verification = (a) `bash .git/hooks/pre-push` exits 0 (prettier must pass on `index.html`), and (b) manual browser observation. Browser checks can be driven with Claude-in-Chrome against the running app (node proxy on `:3001`). Each task below ends with a concrete observable check and a commit.

**Reference spec:** `docs/superpowers/specs/2026-05-21-image-gallery-v2-design.md`

---

## File Structure

- **Modify only:** `gemma-web/index.html`
  - CSS block (`<style>`): bump `.lightbox-overlay` z-index; add gallery card styles.
  - JS image-mode block (~line 2805–3020): IndexedDB helpers, `_storeImageData` extension, `_rehydrateImages`, `downloadImage`.
  - `showImageGallery` (~line 3128–3193): full rewrite + new `renderGalleryGrid`.
  - Two existing download sites (chat-card handler ~line 5322, lightbox Save ~line 5350): swap to `downloadImage`.

No new files. No backend/API changes.

---

## Task 1: Raise lightbox above the gallery modal

The gallery modal is `z-index:300`; the lightbox overlay is `z-index:200`, so a lightbox opened from the gallery would render *behind* it. Fix the layering first so later tasks are verifiable.

**Files:**

- Modify: `gemma-web/index.html:1407`

- [ ] **Step 1: Edit the z-index**

Find (around line 1403–1412):

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
```

Change `z-index: 200;` to `z-index: 400;` (above the gallery modal's 300).

- [ ] **Step 2: Verify formatting**

Run: `cd "/Users/ojdavis/Claude Code/LocalLLM" && npx prettier --check gemma-web/index.html`
Expected: `All matched files use Prettier code style!`

- [ ] **Step 3: Commit**

```bash
git add gemma-web/index.html
git commit -m "fix(gallery): raise lightbox z-index above gallery modal"
```

---

## Task 2: IndexedDB wrapper helpers

Add a small, dependency-free, promise-returning IndexedDB layer. Every call is wrapped so failures (e.g. private browsing) degrade to no-ops — the app keeps working session-only.

**Files:**

- Modify: `gemma-web/index.html` (insert after the `_storeImageData` block, currently ending at line 2814)

- [ ] **Step 1: Insert the IndexedDB helpers**

Locate this existing block (lines ~2808–2814):

```js
      const _imageStore = new Map();
      let _imageIdCounter = 0;
      function _storeImageData(data) {
        const id = String(++_imageIdCounter);
        _imageStore.set(id, data);
        return id;
      }
```

Immediately **after** it, insert:

```js
      // ── IndexedDB persistence for generated images ────────────────────
      // Stores the same record shape _imageStore uses, keyed by id, plus a
      // createdAt timestamp. All ops are best-effort: any failure (e.g.
      // private browsing) degrades to session-only behavior.
      const _IMG_DB_NAME = "localllm_images";
      const _IMG_STORE = "images";
      let _imgDBPromise = null;

      function _imgDBOpen() {
        if (_imgDBPromise) return _imgDBPromise;
        _imgDBPromise = new Promise((resolve, reject) => {
          if (!("indexedDB" in window)) {
            reject(new Error("no indexedDB"));
            return;
          }
          const req = indexedDB.open(_IMG_DB_NAME, 1);
          req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains(_IMG_STORE)) {
              db.createObjectStore(_IMG_STORE, { keyPath: "id" });
            }
          };
          req.onsuccess = () => resolve(req.result);
          req.onerror = () => reject(req.error);
        }).catch((err) => {
          console.warn("[gallery] IndexedDB unavailable:", err);
          return null;
        });
        return _imgDBPromise;
      }

      async function _imgDBPut(record) {
        try {
          const db = await _imgDBOpen();
          if (!db) return;
          await new Promise((resolve, reject) => {
            const tx = db.transaction(_IMG_STORE, "readwrite");
            tx.objectStore(_IMG_STORE).put(record);
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
          });
        } catch (err) {
          console.warn("[gallery] persist failed:", err);
        }
      }

      async function _imgDBGetAll() {
        try {
          const db = await _imgDBOpen();
          if (!db) return [];
          return await new Promise((resolve, reject) => {
            const tx = db.transaction(_IMG_STORE, "readonly");
            const req = tx.objectStore(_IMG_STORE).getAll();
            req.onsuccess = () => resolve(req.result || []);
            req.onerror = () => reject(req.error);
          });
        } catch (err) {
          console.warn("[gallery] load failed:", err);
          return [];
        }
      }

      async function _imgDBDelete(id) {
        try {
          const db = await _imgDBOpen();
          if (!db) return;
          await new Promise((resolve, reject) => {
            const tx = db.transaction(_IMG_STORE, "readwrite");
            tx.objectStore(_IMG_STORE).delete(id);
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
          });
        } catch (err) {
          console.warn("[gallery] delete failed:", err);
        }
      }

      async function _imgDBClear() {
        try {
          const db = await _imgDBOpen();
          if (!db) return;
          await new Promise((resolve, reject) => {
            const tx = db.transaction(_IMG_STORE, "readwrite");
            tx.objectStore(_IMG_STORE).clear();
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
          });
        } catch (err) {
          console.warn("[gallery] clear failed:", err);
        }
      }
      // ── end IndexedDB persistence ─────────────────────────────────────
```

- [ ] **Step 2: Verify formatting**

Run: `cd "/Users/ojdavis/Claude Code/LocalLLM" && npx prettier --check gemma-web/index.html`
Expected: `All matched files use Prettier code style!` (if it reports issues, run `npx prettier --write gemma-web/index.html` and re-check)

- [ ] **Step 3: Smoke-check in browser console**

With the app open at `http://localhost:3001`, in DevTools console run:

```js
_imgDBPut({ id: "test", prompt: "hi", createdAt: Date.now() }).then(() =>
  _imgDBGetAll().then((r) => console.log("rows:", r))
);
```

Expected: logs `rows: [ { id: "test", ... } ]`. Then clean up: `_imgDBDelete("test")`.

- [ ] **Step 4: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat(gallery): add IndexedDB persistence helpers for images"
```

---

## Task 3: Persist on store + rehydrate on load

Extend `_storeImageData` so every generated image is stamped with `id`/`createdAt`, written to IndexedDB, and so `data.id` is available for downloads. Add `_rehydrateImages()` and call it on startup so persisted images repopulate `_imageStore` and the id counter never collides.

**Files:**

- Modify: `gemma-web/index.html` (the `_storeImageData` block at lines ~2810–2814, and add a rehydrate call)

- [ ] **Step 1: Replace `_storeImageData`**

Find:

```js
      function _storeImageData(data) {
        const id = String(++_imageIdCounter);
        _imageStore.set(id, data);
        return id;
      }
```

Replace with:

```js
      function _storeImageData(data) {
        const id = String(++_imageIdCounter);
        data.id = id;
        if (!data.createdAt) data.createdAt = Date.now();
        _imageStore.set(id, data);
        _imgDBPut(data); // fire-and-forget; do not block generation UX
        return id;
      }
```

- [ ] **Step 2: Add `_rehydrateImages` after the IndexedDB block**

Immediately after the `// ── end IndexedDB persistence ──` comment added in Task 2, insert:

```js
      async function _rehydrateImages() {
        const rows = await _imgDBGetAll();
        let maxId = _imageIdCounter;
        for (const row of rows) {
          if (!row || row.id == null) continue;
          _imageStore.set(String(row.id), row);
          const n = parseInt(row.id, 10);
          if (!Number.isNaN(n) && n > maxId) maxId = n;
        }
        _imageIdCounter = maxId;
      }
      _rehydrateImages();
```

> Placement matters: `_rehydrateImages` calls the Task 2 helpers, so it must sit *after* them. Keep the `_storeImageData` change from Step 1 where the original function was.

- [ ] **Step 3: Verify formatting**

Run: `cd "/Users/ojdavis/Claude Code/LocalLLM" && npx prettier --check gemma-web/index.html`
Expected: `All matched files use Prettier code style!`

- [ ] **Step 4: Browser verification — persistence across reload**

1. Open `http://localhost:3001`, switch to Image mode, generate one image.
2. Open the gallery (rail image button) — confirm the image appears.
3. **Reload the page.** Open the gallery again.
   Expected: the image is still present (it was rehydrated from IndexedDB).
4. In console: `_imageStore.size` should be ≥ 1 after reload, and `_imageIdCounter` should equal the max stored id.

- [ ] **Step 5: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat(gallery): persist generated images and rehydrate on load"
```

---

## Task 4: Shared `downloadImage` helper + prompt-based filenames

Replace the three copies of the `<a download="generated.png">` anchor trick with one helper that names files from a prompt slug + id.

**Files:**

- Modify: `gemma-web/index.html` — add helper near the image block; edit chat-card handler (~line 5322) and lightbox Save (~line 5350)

- [ ] **Step 1: Add the helper**

Insert immediately after the `_rehydrateImages();` call added in Task 3:

```js
      function downloadImage(data) {
        if (!data || !data.image_b64) return;
        const slug =
          (data.prompt || "image")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 40) || "image";
        const idPart = data.id != null ? "-" + data.id : "";
        const a = document.createElement("a");
        a.href = "data:image/png;base64," + data.image_b64;
        a.download = `localllm-${slug}${idPart}.png`;
        a.click();
      }
```

- [ ] **Step 2: Swap the chat-card Save handler**

Find (around lines 5322–5326):

```js
        if (btn.textContent.includes("Save")) {
          const a = document.createElement("a");
          a.href = "data:image/png;base64," + data.image_b64;
          a.download = "generated.png";
          a.click();
        } else if (btn.textContent.includes("Regenerate")) {
```

Replace with:

```js
        if (btn.textContent.includes("Save")) {
          downloadImage(data);
        } else if (btn.textContent.includes("Regenerate")) {
```

- [ ] **Step 3: Swap the lightbox Save handler**

Find (around lines 5349–5358):

```js
      document
        .getElementById("lb-save-btn")
        .addEventListener("click", function () {
          const data = _imageStore.get(_lightboxImageId);
          if (!data) return;
          const a = document.createElement("a");
          a.href = "data:image/png;base64," + data.image_b64;
          a.download = "generated.png";
          a.click();
        });
```

Replace with:

```js
      document
        .getElementById("lb-save-btn")
        .addEventListener("click", function () {
          downloadImage(_imageStore.get(_lightboxImageId));
        });
```

- [ ] **Step 4: Verify formatting**

Run: `cd "/Users/ojdavis/Claude Code/LocalLLM" && npx prettier --check gemma-web/index.html`
Expected: `All matched files use Prettier code style!`

- [ ] **Step 5: Browser verification**

Generate an image with prompt "a red fox". Click the chat-card **Save** and the lightbox **Save**.
Expected: both download a file named like `localllm-a-red-fox-<id>.png` (not `generated.png`).

- [ ] **Step 6: Commit**

```bash
git add gemma-web/index.html
git commit -m "refactor(gallery): unify downloads into prompt-named downloadImage helper"
```

---

## Task 5: Gallery card CSS

Add styles for the rewritten gallery: a 2-line-clamped prompt caption, an action row, and a delete button. Reuse the existing `.img-action-btn` look where possible.

**Files:**

- Modify: `gemma-web/index.html` — insert in the `<style>` block right after the `.img-action-btn:hover` rule (around line 995)

- [ ] **Step 1: Insert gallery CSS**

After the existing `.img-action-btn:hover { ... }` rule, add:

```css
      .gallery-card {
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        overflow: hidden;
        width: 220px;
        flex-shrink: 0;
        display: flex;
        flex-direction: column;
        position: relative;
      }
      .gallery-card img {
        width: 100%;
        display: block;
        cursor: zoom-in;
      }
      .gallery-card-prompt {
        padding: 8px 10px;
        font-size: 11px;
        color: #c9c6e6;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }
      .gallery-card-actions {
        display: flex;
        gap: 6px;
        padding: 0 10px 10px;
        margin-top: auto;
      }
      .gallery-card-actions .img-action-btn {
        flex: 1;
        font-size: 11px;
      }
      .gallery-delete-btn {
        position: absolute;
        top: 6px;
        right: 6px;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        border: none;
        background: rgba(0, 0, 0, 0.6);
        color: #fff;
        cursor: pointer;
        font-size: 13px;
        line-height: 1;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .gallery-delete-btn:hover {
        background: #ef4444;
      }
      .gallery-toolbar-input {
        flex: 1;
        max-width: 320px;
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 8px;
        padding: 6px 12px;
        color: #f0eeff;
        font-size: 13px;
      }
      .gallery-toolbar-btn {
        background: none;
        border: 1px solid rgba(255, 255, 255, 0.2);
        color: #9d9abf;
        padding: 6px 14px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 13px;
        white-space: nowrap;
      }
      .gallery-toolbar-btn:hover {
        color: #f0eeff;
        border-color: rgba(255, 255, 255, 0.4);
      }
```

- [ ] **Step 2: Verify formatting**

Run: `cd "/Users/ojdavis/Claude Code/LocalLLM" && npx prettier --check gemma-web/index.html`
Expected: `All matched files use Prettier code style!`

- [ ] **Step 3: Commit**

```bash
git add gemma-web/index.html
git commit -m "style(gallery): add gallery card and toolbar styles"
```

---

## Task 6: Rewrite `showImageGallery`

Replace the bare grid with: a header (title + count, search box, Clear all, Close), and a `renderGalleryGrid()` that renders sorted, filtered cards. Each card: thumbnail (click → `openLightbox`), 2-line prompt, and Copy/Download/Delete actions. The grid and modal are emptied with `replaceChildren()` (safe — no markup strings).

**Files:**

- Modify: `gemma-web/index.html` — replace the entire `showImageGallery` function (lines ~3128–3193)

- [ ] **Step 1: Replace the whole function**

Find the block from `// --- Image Gallery ---` through the end of `showImageGallery` (the closing `}` before `// --- All Chats Modal Logic ---`, ~lines 3128–3193) and replace it entirely with:

```js
      // --- Image Gallery ---
      let _galleryQuery = "";

      function showImageGallery() {
        let modal = document.getElementById("image-gallery-modal");
        if (!modal) {
          modal = document.createElement("div");
          modal.id = "image-gallery-modal";
          modal.style.cssText =
            "position:fixed;inset:0;z-index:300;background:rgba(0,0,0,0.88);display:flex;flex-direction:column;overflow:hidden;";
          document.body.appendChild(modal);
        }
        modal.style.display = "flex";
        _galleryQuery = "";

        const header = document.createElement("div");
        header.style.cssText =
          "display:flex;align-items:center;gap:12px;padding:16px 24px;border-bottom:1px solid rgba(255,255,255,0.10);flex-shrink:0;";

        const title = document.createElement("h2");
        title.id = "gallery-title";
        title.style.cssText =
          "margin:0;font-size:16px;font-weight:700;color:#f0eeff;white-space:nowrap;";

        const search = document.createElement("input");
        search.type = "text";
        search.placeholder = "Search prompts…";
        search.className = "gallery-toolbar-input";
        search.addEventListener("input", (e) => {
          _galleryQuery = e.target.value;
          renderGalleryGrid();
        });

        const clearBtn = document.createElement("button");
        clearBtn.textContent = "Clear all";
        clearBtn.className = "gallery-toolbar-btn";
        clearBtn.addEventListener("click", async () => {
          if (_imageStore.size === 0) return;
          if (
            !confirm("Delete all images from the gallery? This cannot be undone.")
          )
            return;
          _imageStore.clear();
          await _imgDBClear();
          renderGalleryGrid();
        });

        const closeBtn = document.createElement("button");
        closeBtn.textContent = "✕ Close";
        closeBtn.className = "gallery-toolbar-btn";
        closeBtn.addEventListener("click", () => {
          modal.style.display = "none";
        });

        const spacer = document.createElement("div");
        spacer.style.flex = "1";

        header.append(title, search, spacer, clearBtn, closeBtn);

        const grid = document.createElement("div");
        grid.id = "gallery-grid";
        grid.style.cssText =
          "flex:1;overflow-y:auto;padding:16px 24px;display:flex;flex-wrap:wrap;gap:16px;align-content:flex-start;";

        modal.replaceChildren(header, grid);
        renderGalleryGrid();
      }

      function renderGalleryGrid() {
        const grid = document.getElementById("gallery-grid");
        const title = document.getElementById("gallery-title");
        if (!grid) return;

        const q = _galleryQuery.trim().toLowerCase();
        const entries = Array.from(_imageStore.values())
          .filter((d) => !q || (d.prompt || "").toLowerCase().includes(q))
          .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));

        if (title) {
          const total = _imageStore.size;
          title.textContent =
            total === 0
              ? "Image Gallery — No images yet"
              : `Image Gallery — ${entries.length}/${total} image${total === 1 ? "" : "s"}`;
        }

        grid.replaceChildren();

        if (entries.length === 0) {
          const empty = document.createElement("p");
          empty.textContent =
            _imageStore.size === 0
              ? "No images yet. Use Image mode to generate some."
              : "No images match your search.";
          empty.style.cssText = "color:#9d9abf;font-size:14px;padding:20px 0;";
          grid.appendChild(empty);
          return;
        }

        entries.forEach((data) => {
          const card = document.createElement("div");
          card.className = "gallery-card";

          const img = document.createElement("img");
          img.src = "data:image/png;base64," + data.image_b64;
          img.alt = "Generated: " + (data.prompt || "");
          img.addEventListener("click", () => openLightbox(data.id));

          const del = document.createElement("button");
          del.className = "gallery-delete-btn";
          del.textContent = "✕";
          del.title = "Delete";
          del.addEventListener("click", async (e) => {
            e.stopPropagation();
            _imageStore.delete(data.id);
            await _imgDBDelete(data.id);
            renderGalleryGrid();
          });

          const prompt = document.createElement("div");
          prompt.className = "gallery-card-prompt";
          prompt.textContent = data.prompt || "No prompt";

          const actions = document.createElement("div");
          actions.className = "gallery-card-actions";

          const copyBtn = document.createElement("button");
          copyBtn.className = "img-action-btn";
          copyBtn.type = "button";
          copyBtn.textContent = "Copy prompt";
          copyBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            try {
              await navigator.clipboard.writeText(data.prompt || "");
              const prev = copyBtn.textContent;
              copyBtn.textContent = "Copied!";
              setTimeout(() => (copyBtn.textContent = prev), 1200);
            } catch (err) {
              console.warn("[gallery] clipboard failed:", err);
            }
          });

          const dlBtn = document.createElement("button");
          dlBtn.className = "img-action-btn";
          dlBtn.type = "button";
          dlBtn.textContent = "⬇ Download";
          dlBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            downloadImage(data);
          });

          actions.append(copyBtn, dlBtn);
          card.append(del, img, prompt, actions);
          grid.appendChild(card);
        });
      }
```

- [ ] **Step 2: Verify formatting**

Run: `cd "/Users/ojdavis/Claude Code/LocalLLM" && npx prettier --check gemma-web/index.html`
Expected: `All matched files use Prettier code style!` (run `--write` then re-check if needed)

- [ ] **Step 3: Browser verification — full gallery behavior**

With the app at `http://localhost:3001`:

1. Generate 2–3 images with distinct prompts.
2. Open the gallery (rail image button).
   - Each card shows thumbnail, 2-line prompt, Copy/Download buttons, and a ✕ in the top-right.
   - Cards are newest-first.
3. **Click a thumbnail** → the lightbox opens *on top of* the gallery (full prompt + metadata visible). Close it → returns to gallery.
4. **Copy prompt** → button flips to "Copied!"; paste elsewhere confirms the full prompt.
5. **⬇ Download** → file named `localllm-<slug>-<id>.png`.
6. **Search** → typing a word present in only one prompt filters to it; title shows `N/total`.
7. **Delete (✕)** on one card → it disappears; reload page → it stays gone (removed from IndexedDB).
8. **Clear all** → confirm dialog; accepting empties the gallery; reload → still empty.

- [ ] **Step 4: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat(gallery): rewrite gallery with lightbox, search, copy, download, delete"
```

---

## Task 7: Full gate + end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full pre-push pipeline**

Run: `cd "/Users/ojdavis/Claude Code/LocalLLM" && bash .git/hooks/pre-push`
Expected: exits 0 (ruff check, ruff format --check, prettier --check, pytest all pass).

- [ ] **Step 2: Restart bridge if backend was touched**

Not applicable — this change is frontend-only. The node proxy serves `index.html` directly; a browser reload picks up changes. (No `kickstart` needed.)

- [ ] **Step 3: End-to-end smoke**

In the browser: generate → reload → image persists in gallery → lightbox → copy → download → delete → clear all. Confirm no unexpected console errors (`[gallery]` warnings should not appear on a normal run).

- [ ] **Step 4: Update PROGRESS.md**

Append a short session entry to `PROGRESS.md` describing the gallery v2 work (persistence + gallery actions), matching the existing log style. Then:

```bash
git add PROGRESS.md
git commit -m "docs: log image gallery v2 (persistence + gallery actions)"
```

---

## Self-Review (completed during planning)

- **Spec coverage:** persistence (Tasks 2–3), download from gallery (Tasks 4, 6), view prompt / click-to-lightbox (Task 6 + reused lightbox), copy prompt (Task 6), search (Task 6), delete single + clear all (Task 6), graceful degradation (Task 2 try/catch), prompt-based filenames (Task 4), z-index fix (Task 1). All spec sections map to a task.
- **Type consistency:** records carry `id` and `createdAt` (set in `_storeImageData`, Task 3); `downloadImage(data)` reads `data.id`/`data.image_b64`/`data.prompt`; gallery reads the same fields and `_imageStore.values()`. `openLightbox(data.id)` matches the existing signature (`openLightbox(imageId)` reads `_imageStore.get(imageId)`).
- **No placeholders:** every code step contains full code; verification steps give concrete expected output.
```
