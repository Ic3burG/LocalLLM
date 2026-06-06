# MLX Batched Generation — multi-client serving throughput

## Problem

Every generation in LocalLLM funnels through **one OS thread** fed by a single
FIFO queue (`inference_engine._inference_worker`, backed by `_inference_queue`).
The design is deliberate: MLX GPU streams are **thread-local**, and `mlx_vlm`
creates its `generation_stream` at import time, so all inference must live on one
thread forever (see `inference_engine.py:44-58`). `_is_job_running` is a single
global boolean.

The consequence is that requests **do not run concurrently — they queue and run
one at a time**. When two browser tabs / devices hit the bridge at once, the
second waits for the first to fully finish. That serialization is the throughput
ceiling for multi-client serving.

The fix is **batched generation**: feed multiple prompts into a _single batched
forward pass_ on that same thread so concurrent requests share GPU work, instead
of adding threads or processes (the GPU is one shared resource and unified
memory is limited — more processes multiply VRAM without adding throughput).

## Decision

Build a **unified batching scheduler** on the existing single MLX thread, with
two pluggable backends behind one interface:

- **`TextBatchSession`** wraps `mlx_lm.server.BatchGenerator` → true
  **continuous batching** for text-only models (`phi4-mini`,
  `deepseek-v4-mini`). Requests join and leave a running batch at token
  boundaries.
- **`VisionBatchRunner`** wraps `mlx_vlm.batch_generate` → **static** batching
  for the vision-capable gemma models. A group of pending same-model requests
  runs as one call and finishes together.

The public contract is **preserved byte-for-byte**: `run_inference(messages,
model_id) -> str` still buffers and returns a full response. The app already does
_not_ stream tokens live — both `_react_loop_internal` (`agent.py:319`) and
`react_loop_sse` (`agent.py:531`) call the buffered `run_inference`, and the SSE
endpoints stream _events_ per ReAct step, not tokens. So batching happens
**internally**: the **inference path** never learns it exists — `agent.py` is not
edited, and the bridge's chat routes (`/v1/chat/completions`, `/v1/chat/stream`)
are unchanged. The only bridge edit is an _additive_ batch block in the read-only
`/v1/stats` telemetry route (see Design §7).

Alternatives rejected: routing everything through `mlx_lm` (loses image support —
violates the feature-integrity mandate); multiple model processes (wrong lever —
GPU is shared, VRAM is the constraint).

## Goals

- Concurrent same-model requests share GPU forward passes instead of serializing.
- The `run_inference` contract and all current behavior are unchanged; no edits
  to its callers (the bridge chat routes and `agent.py`).
- Scheduler logic is unit-testable in CI **without** a GPU (MLX stubbed, as
  today).
- A master feature flag reverts to today's serial path for rollback / A/B.
- Idle (single-request) latency stays identical to today — no artificial batching
  delay.

## Non-goals

- **Live token streaming** to clients. The contract stays buffered. Continuous
  batching _can_ stream text, but the static vision path cannot, and adding
  streaming would change the public contract. Out of scope for v1.
- **Per-request cancellation / client-disconnect handling.** Today's contract
  shields the future to completion; that stays. Out of scope for v1.
- **Cross-model co-batching.** A batch shares one model's weights, so requests
  for _different_ models still take turns. Out of scope (and physically required).
- Raising throughput of _document ingestion_ — that already shipped (parallel
  parse + one batched embed) and is a different problem.

## Design

### 1. Module decomposition & preserved contract

`inference_engine.py` (437 lines) already does four jobs. Adding a scheduler plus
two backends inline would overload it, so split along responsibility lines:

| Module                | Responsibility                                                                                                                   | Touches MLX |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| `model_cache.py`      | LRU model/processor caches, `get_mlx_vlm_model`, `get_mlx_lm_model`, `_TEXT_ONLY_MODELS`, `is_model_loaded`, `get_loaded_models` | load only   |
| `batch_backends.py`   | `TextBatchSession` + `VisionBatchRunner`; the **only** module that calls MLX batch APIs                                          | yes         |
| `batch_scheduler.py`  | Owns the single MLX thread, pending queue, scheduling loop, fairness, watchdog, batch telemetry                                  | no          |
| `inference_engine.py` | Thin **facade**: `run_inference()` builds a request, submits it, awaits the future; re-exports status/cache symbols              | no          |

**Contract preservation.** `run_inference(messages, model_id) -> str` stays
byte-identical. `inference_engine` re-exports the cache/status symbols that
callers and tests import (`is_model_loaded`, `get_avg_latency`,
`get_status_info`, `get_loaded_models`, `get_mlx_vlm_model`, `_vlm_cache`, …) so
no import sites break. The scheduler exposes a `run_on_thread(fn, *args)` escape
hatch (replacing today's `run_in_inference_thread`) for non-batchable one-off
work on the MLX thread — used by the contract test for cache inspection/cleanup.

This split is driven by **testability**: `batch_scheduler` has no MLX dependency,
so grouping / fairness / future-resolution / error-isolation are unit-testable in
CI against a `FakeBackend`; the GPU wiring is quarantined in `batch_backends`
behind a `needs_gpu` contract test.

### 2. Request lifecycle & scheduler loop

A submission becomes an `InferenceRequest` dataclass:

```python
@dataclass
class InferenceRequest:
    id: str
    engine_kind: str          # "text" if model_id in _TEXT_ONLY_MODELS else "vision"
    model_id: str
    messages: list
    max_tokens: int
    future: asyncio.Future
    loop: asyncio.AbstractEventLoop
    created_at: float
```

`engine_kind` follows **today's exact routing**, so a gemma request with no image
still uses the vision path — no behavior change.

The scheduler loop (single thread), each tick:

1. **Drain** pending requests into in-memory groups keyed by
   `(engine_kind, model_id)`.
2. **If a text session is active** for model X: admit pending text-X requests up
   to `completion_batch_size`, `step()` once, resolve any finished sequences'
   futures. Continue while it has work _and_ fairness allows (below).
3. **Else pick the oldest-waiting group** and serve it:
   - **vision** → gather everything pending for that model _now_ and run one
     static `batch_generate` (no artificial wait timer).
   - **text** → create a `TextBatchSession`, insert the pending requests, begin
     stepping.
4. Resolve each request via `loop.call_soon_threadsafe(future.set_result, text)`
   (or `set_exception`).

**No window timer.** When busy, multiple requests are already pending at dispatch
and batch naturally; when idle, a lone request runs immediately. This keeps idle
latency identical to today and removes a config knob.

**Fairness / model switching.** The active text session admits same-model
requests freely _until a request for a different model has been waiting_. At that
point it stops admitting new ones, drains its in-flight sequences, then the
scheduler switches models. This bounds another model's wait to "current in-flight
completion." In practice clients share one model, so switches are rare; the guard
exists to prevent starvation, not as the common path.

### 3. Text backend — `TextBatchSession` (continuous)

Built once per active text model from `model_cache.get_mlx_lm_model(model_id)`;
constructs `BatchGenerator(model, completion_batch_size=…, prefill_batch_size=…,
max_kv_size=…, stop_tokens=…)`.

- `insert(req)` — render `tokenizer.apply_chat_template(...)` → token ids →
  `gen.insert(uid, ids)`; track `uid → (req, accumulator)`.
- `step()` — advance one round; append each uid's new token text to its
  accumulator; for any sequence that hit EOS / a stop token / its `max_tokens`,
  decode the full text, resolve that request's future, and `gen.remove(uid)` to
  free the slot. **This is the essence of continuous batching: finished requests
  leave mid-flight while others keep running.**
- `active_count()` / `has_capacity()` — for admission decisions.
- `close()` — called before the model can be evicted (it holds KV-cache state).

The exact `BatchGenerator` stepping protocol
(`insert`/`next`/`next_generated`/`remove`/`stream`) is internal to
`mlx_lm.server` and undocumented in inspection — the **contract test pins down
the real call sequence** (see Risks).

### 4. Vision backend — `VisionBatchRunner` (static)

Given a group of same-model vision requests:

1. Load via `model_cache.get_mlx_vlm_model(model_id)`.
2. Render each prompt with `processor.apply_chat_template`; decode each request's
   inline base64 image to a temp file. **The image-decode + chat-template logic
   currently in `handle_mlx_vlm_request` moves here, reused not duplicated.**
3. Build aligned lists `prompts: list[str]`, `images: list[str | None]`,
   `max_tokens: list[int]`.
4. One call: `mlx_vlm.batch_generate(model, processor, images=images,
prompts=prompts, max_tokens=max_tokens, group_by_shape=True)`.
5. Map the `BatchResponse` back to requests in original order, resolve each
   future, clean up temp images in `finally`.

`VisionBatchRunner` is **transactional** (one call in, all results out, everyone
finishes together) where `TextBatchSession` is **temporal** (admits and retires
sequences over time). Same `BatchBackend` interface, opposite lifecycles — which
is why the scheduler can't use a single `run_group(list)` method.

`LOCALLLM_VISION_MAX_BATCH` caps a static batch; overflow waits for the next one.

### 5. Watchdog, error isolation, cancellation

**Error isolation — one bad request must not poison the batch.**

- _Text:_ a render/insert failure resolves just that future with the exception;
  others proceed.
- _Vision:_ `batch_generate` is all-or-nothing, so on a batch-level exception the
  runner **retries each request individually** (batch-of-1) to isolate the
  culprit — good requests succeed, the bad one gets its error. Errors are rare,
  so the re-run cost is acceptable.

**Watchdog.** Keep the existing 180s idle guard, made batch-aware: `_last_progress`
updates on any produced token or completed batch. If no progress for 180s while
work is active, abort the active batch/session and resolve all its in-flight
futures with `RuntimeError("inference watchdog: stalled")`, then reset. Because a
GPU step advances the whole batch together, a stall is inherently global —
aborting the active batch is the right granularity (no per-request stop needed).

**Cancellation.** None — today's contract shields the future to completion. Out
of scope for v1 (would change the public contract).

### 6. Configuration (env vars, app style)

Conservative defaults for a memory-bound Mac:

| Var                              | Default | Effect                                                                                                           |
| -------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| `LOCALLLM_BATCH_ENABLED`         | `1`     | Master flag. `0` → scheduler processes one request per tick = today's serial behavior (rollback / A/B baseline). |
| `LOCALLLM_TEXT_COMPLETION_BATCH` | `8`     | `BatchGenerator.completion_batch_size`.                                                                          |
| `LOCALLLM_TEXT_PREFILL_BATCH`    | `8`     | `BatchGenerator.prefill_batch_size`.                                                                             |
| `LOCALLLM_MAX_KV_SIZE`           | unset   | `BatchGenerator.max_kv_size` (memory guard).                                                                     |
| `LOCALLLM_VISION_MAX_BATCH`      | `4`     | Cap on a static vision batch.                                                                                    |

`max_tokens` continues to default to 8192 as today.

### 7. Telemetry

The scheduler maintains batch counters exposed via a new
`batch_scheduler.get_batch_stats()` helper:

- current batch occupancy (active sequences) per engine,
- peak batch size observed,
- aggregate tokens/sec,
- count of model switches.

These derive from `BatchGenerator.stats()` / `BatchStats` where available, plus
scheduler-side counters. The bridge's `/v1/stats` route (`gemma_bridge.py:307`)
gains **one additive `batch` block** alongside the existing `system` / `agent` /
`pipeline` blocks — a read-only change that does not touch the inference path.

Wiring those numbers into the **Settings → Vitals** tab UI
(`gemma-web/index.html`) is a **small optional follow-up**, not required for the
throughput goal — the data is available on the endpoint regardless. Per CLAUDE.md,
telemetry belongs on the Vitals tab, so if displayed it goes there and nowhere
else (no sidebar/preview mirrors).

## Testing strategy (CI-safe, no GPU)

The scheduler is pure orchestration, so its hard logic is tested in CI with a
`FakeBackend` that "generates" deterministic tokens:

- grouping by `(engine_kind, model_id)`,
- continuous admission/retirement (requests finishing at different lengths
  resolve in the right order, free slots, let queued requests in),
- fairness/model-switching guard (a waiting other-model request forces a drain +
  switch, no starvation),
- error isolation (one failing request doesn't fail its batch-mates),
- watchdog abort resolves in-flight futures with the stall error,
- `BATCH_ENABLED=0` falls back to serial.

Real MLX wiring lives in `batch_backends` and is validated by a **`needs_gpu`**
contract test in `tests/contracts/` (excluded from the CI gate like
`test_mlx_contract.py`): it exercises the real `BatchGenerator` step protocol,
real `batch_generate`, and a **mixed** vision batch (some requests with images,
some without) — see Risks.

## Acceptance benchmark

A `needs_gpu` benchmark script (`scripts/bench_batching.py`, documented for manual
run, not in the CI gate): fire K concurrent `run_inference` calls for one model
and compare against the serial baseline (`LOCALLLM_BATCH_ENABLED=0`). Pass
criteria:

- aggregate tokens/sec for K concurrent requests **exceeds** the serial baseline
  at K ≥ 2,
- single-request (K=1) latency is within noise of today's serial latency
  (no regression when there's nothing to batch).

## Implementation phasing

One spec, phased build behind the shared interface:

1. **Scaffolding** — `model_cache.py` extracted from `inference_engine.py`;
   `InferenceRequest`; `batch_scheduler.py` with the loop, `FakeBackend`, and the
   `BATCH_ENABLED=0` serial path; `inference_engine` re-exports + facade. Full
   unit-test suite green. No MLX behavior change yet (serial path only).
2. **Text continuous batching** — `TextBatchSession`; scheduler text path;
   contract test for the `BatchGenerator` protocol.
3. **Vision static batching** — `VisionBatchRunner` (move image/template logic);
   scheduler vision path; mixed-batch contract test.
4. **Telemetry + benchmark** — Vitals batch fields; `bench_batching.py`; tune
   default batch sizes from real numbers.

Each phase is independently shippable and leaves the app fully working.

## Affected tests

Tests that reach into `inference_engine` internals and will be updated to target
the new modules:

- `tests/test_telemetry_unit.py` — patches `run_in_inference_thread` → repoint to
  the scheduler facade.
- `tests/test_longevity.py` — uses `handle_mlx_vlm_request`, `_stop_inference`,
  `_last_inference_activity`, `_mlx_vlm_stream_generate` → rewrite against the
  watchdog's new batch-aware progress tracking.
- `tests/test_lru_cache.py` — uses `get_mlx_vlm_model`, `_vlm_cache`,
  `_inference_ready` → repoint to `model_cache` (symbols re-exported, so changes
  are minimal).
- `tests/test_logging_config.py` — patches `run_in_inference_thread` → repoint.
- `tests/contracts/test_mlx_contract.py` — imports `get_mlx_vlm_model`,
  `run_in_inference_thread`, `run_inference` → keep working via re-exports +
  `run_on_thread`.

## Risks

- **`BatchGenerator` is an internal `mlx_lm.server` API.** Its step protocol is
  undocumented and may shift across mlx_lm releases. Mitigation: the contract
  test pins the exact call sequence; `mlx_lm` is version-pinned (0.31.3); the
  `BATCH_ENABLED=0` flag is an instant fallback.
- **Mixed vision batches** (some requests with images, some without) may not be
  supported by `batch_generate`. Mitigation: contract test validates it; if
  unsupported, `VisionBatchRunner` splits into image / no-image subgroups.
- **KV-cache memory under load.** A full text batch holds KV cache for every
  active sequence; on a memory-bound Mac this can pressure unified memory.
  Mitigation: conservative default batch sizes + `LOCALLLM_MAX_KV_SIZE`; tune
  from the benchmark.
- **Static vision coupling.** A short prompt in a vision batch waits for the
  longest one. Accepted tradeoff for v1; per-request `max_tokens` caps the worst
  case; `LOCALLLM_VISION_MAX_BATCH` limits the blast radius.
- **Real concurrency may be low** on a single-user machine, so the win only
  materializes under genuine overlap. The benchmark measures this honestly; the
  serial fallback means no downside when requests don't overlap.

## Verification (Definition of Done)

- `bash .git/hooks/pre-push` runs in-session and exits 0 (full unit suite,
  including the new scheduler tests, green).
- The `needs_gpu` contract test passes locally on the Mac (real
  `BatchGenerator` + `batch_generate`, including a mixed vision batch).
- `scripts/bench_batching.py` shows aggregate tokens/sec at K=2+ exceeding the
  serial baseline, with no K=1 latency regression.
- `run_inference`'s signature and return type are unchanged; `agent.py` and the
  bridge's chat routes are not edited (only `/v1/stats` gains an additive `batch`
  block).
- After push, GitHub Actions CI is green.

## Files touched

- `model_cache.py` — **new**; caches/loaders extracted from `inference_engine`.
- `batch_scheduler.py` — **new**; thread owner, loop, fairness, watchdog,
  telemetry.
- `batch_backends.py` — **new**; `TextBatchSession`, `VisionBatchRunner`,
  `BatchBackend` interface.
- `inference_engine.py` — slimmed to a facade + re-exports.
- `gemma_bridge.py` — `/v1/stats` gains one additive `batch` block (telemetry
  read only; inference path untouched).
- `gemma-web/index.html` — _optional_ follow-up to render the batch block on the
  Vitals tab; not required for the throughput goal.
- `tests/` — new scheduler unit tests + `FakeBackend`; updated internal-reaching
  tests; new `needs_gpu` batching contract test.
- `scripts/bench_batching.py` — **new**; acceptance benchmark.
- `docs/superpowers/specs/2026-06-06-mlx-batched-generation-design.md` — this
  spec.

Estimated change surface: ~600–800 lines net across the new modules, the facade
slim-down, and tests.
