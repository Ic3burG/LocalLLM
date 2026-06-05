# Close the CI/local Python version gap

## Problem

CI and local development run **different Python interpreters**, and nothing makes
that divergence visible or fully tested:

- **CI** (`.github/workflows/ci.yml`) pins **3.10** for both the `lint` and
  `test` jobs.
- **Local** development runs **3.14** — both `.venv/bin/python` and the
  `python3` on `PATH` are 3.14.0. No 3.10/3.11/3.12 interpreter is installed.
- The project declares `requires-python = ">=3.10"` and `ruff` uses
  `target-version = "py310"`.

The `scripts/hooks/pre-push` hook claims, on lines 1–2, that it _"Mirrors the CI
pipeline exactly — if this passes locally, CI will pass."_ That promise is false
on one axis: it runs `pytest` against the local **3.14** interpreter, while CI
runs `pytest` on **3.10**.

This is a live footgun, not a hypothetical one:

- `localllm/config.py:11-13` uses the standard
  `try: import tomllib / except ImportError: import tomli as tomllib` pattern.
  On local 3.14, only the `tomllib` branch ever executes. The `tomli` fallback
  branch — and `requirements.txt`'s `tomli>=2.0; python_version < "3.11"`
  marker — are **only** exercised on CI's 3.10. So that code path is untested
  locally by construction. A green local pre-push cannot catch a break in it.
- `ruff` catches _syntax_ that 3.10 cannot parse (its `target-version` is
  `py310`), but it does **not** model the stdlib surface. Calling a 3.11+-only
  API such as `tomllib.load` under a bare import is invisible to ruff. Only
  _running on 3.10_ exercises the 3.10 stdlib — and nothing local does.

## Decision

**Keep the `>=3.10` floor.** The 3.10-compat code is deliberate, and the repo
has external contributors (e.g. the Ic3burG CLI PR) for whom broad
compatibility matters. We close the gap by making the untested side **covered in
CI** and the interpreter divergence **visible in the hook**, rather than
dropping support or forcing a 3.10 install on the maintainer's Mac.

## Goals

- CI is self-sufficient for both ends of the supported range — important for
  contributors whose PRs run CI but never run the maintainer's local hook.
- The pre-push hook tells the truth about what it does and does not guarantee.
- No new local toolchain (no second interpreter to install/maintain).
- No production code changes.

## Non-goals

- Raising or lowering the supported Python range.
- Making local pre-push run 3.10 (the heavier "belt and suspenders" option was
  considered and declined).
- Fixing unrelated deprecations (see Out of scope).

## Design

### 1. CI `test` job → version matrix

Convert the single `test` job to a matrix over **`["3.10", "3.13"]`**:

- `3.10` — the declared floor. Catches 3.10-only breakage such as the
  `config.py` `tomli` fallback path.
- `3.13` — the "recent" leg. Catches "newer than 3.10" breakage for
  contributors whose PRs only run CI.

**Why 3.13 and not 3.14 for the recent leg:** `requirements.txt` pulls
`sentence-transformers`, which depends on `torch` and `scipy` — packages that
are slow to publish wheels for a brand-new CPython. On `ubuntu-latest`, a
`cp314` leg would likely fail at `pip install` (no Linux `torch` wheel for 3.14
→ source build → failure) — a failure caused by the runner, not our code. 3.13
has solid Linux wheel coverage. The maintainer's actual 3.14 is still exercised
constantly by local pytest/pre-push runs, and the hook notice (below) flags that
local 3.14 sits above both CI legs.

Use `fail-fast: false` so one leg's failure does not cancel the other — both
results stay visible. The `lint` job stays single-version: `ruff` and `prettier`
output is interpreter-independent, and `ruff` already pins `target-version`.

Target shape for the `test` job:

```yaml
test:
  runs-on: ubuntu-latest
  strategy:
    fail-fast: false
    matrix:
      python-version: ["3.10", "3.13"]
  steps:
    - uses: actions/checkout@v5
    - name: Set up Python
      uses: actions/setup-python@v6
      with:
        python-version: ${{ matrix.python-version }}
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pytest pytest-asyncio
    - name: Run Tests (Skip GPU)
      run: |
        # Standard runners lack Apple Silicon/GPU, so skip MLX/GPU tests.
        pytest -v -m "not needs_gpu" --ignore=tests/contracts/test_mlx_contract.py
```

### 2. Make the pre-push hook honest (`scripts/hooks/pre-push`)

- **Rewrite the header (lines 1–2).** Drop the false "Mirrors the CI pipeline
  exactly" claim. State accurately that the hook runs CI's checks against the
  _local_ interpreter, and that CI additionally runs the pytest suite on each
  matrix version.
- **Add a non-fatal coverage notice** after the pytest step. Read the venv's
  `major.minor`; if it is not one of CI's matrix versions, print a clear `⚠`
  line telling the user a version-specific failure won't be caught locally and
  to watch the Actions run. It informs; it never changes the hook's exit code.
- **CI version list** lives as a commented constant in the hook
  (`CI_PY_VERSIONS="3.10 3.13"`) with a pointer to `ci.yml` as the source of
  truth. A true file-based single source of truth is awkward — GitHub Actions
  cannot read a matrix from a file without an extra job — and this value only
  feeds an _informational_ notice that never gates, so a commented constant is
  the right level of effort.

Target shape for the new hook logic (appended after the existing `pytest` line,
before the final success echo):

```bash
# CI runs the pytest suite on each of these versions (keep in sync with
# .github/workflows/ci.yml). Informational only — never affects exit status.
CI_PY_VERSIONS="3.10 3.13"
LOCAL_PYV="$("${ARCH_PREFIX[@]}" "$VENV_PYTHON" -c \
  'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case " $CI_PY_VERSIONS " in
  *" $LOCAL_PYV "*) : ;; # local interpreter matches a CI leg
  *)
    echo "⚠ pytest ran on local Python $LOCAL_PYV; CI runs it on: $CI_PY_VERSIONS."
    echo "  A failure specific to those versions won't be caught here — watch the"
    echo "  GitHub Actions run after pushing."
    ;;
esac
```

### 3. Reinstall the hook

After editing `scripts/hooks/pre-push`, run `bash scripts/install-hooks.sh` so
`.git/hooks/pre-push` matches source — per the CLAUDE.md mandate that source in
`scripts/hooks/` is authoritative and installed copies must not drift.

## Out of scope

- `localllm/config.py` `tomli` fallback: **keep it.** It is correct, and the new
  3.10 CI leg now genuinely exercises it.
- `agent.py:245` `datetime.utcnow()` is deprecated on 3.12+ (warns on local 3.14,
  silent on CI 3.10). Noted as a **separate follow-up cleanup**, not part of
  this version-gap fix.

## Risks

- **The 3.13 leg has never run.** It may surface a genuine latent issue on first
  push. That is the footgun working as intended — we fix what it finds before
  calling the task done.
- **Dependency install time/cost** roughly doubles for the `test` job (two
  legs). Acceptable for the coverage gained.
- **`actions/setup-python@v6` must offer 3.13** (it does, via the version
  manifest). If a future runner image lags, pin a patch version.

## Verification (Definition of Done)

- `bash .git/hooks/pre-push` runs in-session and exits 0, and the new mismatch
  notice fires (the maintainer is on 3.14, outside `{3.10, 3.13}`).
- After push, **both** matrix legs (`3.10` and `3.13`) and the `lint` job go
  green on GitHub Actions. If the 3.13 leg goes red, diagnose and fix before
  reporting done.

## Files touched

- `.github/workflows/ci.yml` — matrix on the `test` job.
- `scripts/hooks/pre-push` — honest header + non-fatal coverage notice.
- `.git/hooks/pre-push` — regenerated by `scripts/install-hooks.sh` (not edited
  by hand).
- `docs/superpowers/specs/2026-06-05-ci-local-python-version-gap-design.md` —
  this spec.

Estimated change surface: ~25–35 lines across the two source files.
