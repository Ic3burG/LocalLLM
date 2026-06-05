# Close the CI/local Python version gap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CI test both ends of the supported Python range and make the pre-push hook tell the truth about what it guarantees, while keeping the `>=3.10` floor.

**Architecture:** Two source edits — a `fail-fast: false` matrix (`3.10`, `3.13`) on CI's `test` job, and an honest header plus a non-fatal interpreter-mismatch notice in `scripts/hooks/pre-push` — then reinstall the hook and verify through the full pre-push gate and a green Actions run.

**Tech Stack:** GitHub Actions (`actions/setup-python@v6`), Bash, ruff/prettier/pytest CI gate, `gh` CLI for run monitoring.

**Spec:** `docs/superpowers/specs/2026-06-05-ci-local-python-version-gap-design.md`

**TDD note:** This change is CI config + a bash hook, so there is no pytest harness for it. Each task defines an _observable_ success check before editing (prettier parses the YAML; the hook runs and the notice fires; both CI legs go green) and verifies it after. That is the real discipline applied to infra.

---

## File Structure

- **Modify** `.github/workflows/ci.yml` — add a `strategy.matrix` over `python-version` to the `test` job; reference `${{ matrix.python-version }}` in `setup-python`. The `lint` job is unchanged.
- **Modify** `scripts/hooks/pre-push` — replace the false "mirrors CI exactly" header comment; append a non-fatal coverage notice after the pytest step.
- **Regenerate** `.git/hooks/pre-push` via `bash scripts/install-hooks.sh` (NOT hand-edited, NOT committed — `.git/` is outside the repo tree; only `scripts/hooks/pre-push` is version-controlled).

No production code changes. `localllm/config.py` and `agent.py` are untouched.

---

## Task 1: Add the CI test matrix (3.10, 3.13)

**Files:**

- Modify: `.github/workflows/ci.yml` (the `test` job, currently lines 31–47)

- [ ] **Step 1: Establish the success check (baseline)**

Run: `npx prettier --check .github/workflows/ci.yml`
Expected: `All matched files use Prettier code style!` (this both proves the YAML is valid and is the check we re-run after editing).

Run: `grep -n "fail-fast\|matrix\|3.13" .github/workflows/ci.yml`
Expected: no output yet (no matrix exists). This is the "red" state.

- [ ] **Step 2: Add the matrix to the `test` job**

Use Edit on `.github/workflows/ci.yml`.

old_string (note the real file indents the `test:` job two spaces under `jobs:` — match it exactly):

```text
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.10"
```

new_string:

```text
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
```

Leave the `Install dependencies` and `Run Tests (Skip GPU)` steps exactly as they are — they already work per-version (`requirements.txt` installs `tomli` only on `python_version < "3.11"`, so the 3.10 leg gets it and the 3.13 leg does not).

- [ ] **Step 3: Verify the YAML is valid and the matrix is present (green)**

Run: `npx prettier --check .github/workflows/ci.yml`
Expected: `All matched files use Prettier code style!` (malformed YAML would make prettier error here).

Run: `grep -nE "fail-fast: false|python-version: \[\"3.10\", \"3.13\"\]|\\$\\{\\{ matrix.python-version \\}\\}" .github/workflows/ci.yml`
Expected: three matching lines (the `fail-fast`, the matrix list, and the `setup-python` reference).

> If prettier rewrites the flow sequence spacing, that is fine — the pre-commit hook in Step 4 auto-formats and re-stages. The structural `grep` is what must pass.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run the test suite on a 3.10/3.13 Python matrix" \
  -m "Keep the >=3.10 floor while also testing a recent interpreter, so CI covers both ends for contributors whose PRs never run the local pre-push hook. 3.13 (not 3.14) because torch/scipy lack cp314 Linux wheels; local 3.14 is still exercised by the maintainer's own runs." \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Expected: the pre-commit hook prints `✅ pre-commit: all checks passed.` and the commit is created.

---

## Task 2: Make the pre-push hook honest

**Files:**

- Modify: `scripts/hooks/pre-push` (header comment line 2; insertion after the pytest line)

- [ ] **Step 1: Establish the success checks (baseline)**

Run: `grep -c "Mirrors the CI pipeline exactly" scripts/hooks/pre-push`
Expected: `1` (the false claim is still there — the "red" state).

Run: `grep -c "CI_PY_VERSIONS" scripts/hooks/pre-push`
Expected: `0` (no notice yet).

- [ ] **Step 2: Replace the misleading header comment**

Use Edit on `scripts/hooks/pre-push`.

old_string:

```bash
#!/usr/bin/env bash
# Mirrors the CI pipeline exactly — if this passes locally, CI will pass.
set -e
```

new_string:

```bash
#!/usr/bin/env bash
# Runs the same checks as GitHub Actions CI (ruff, prettier, pytest) against your
# LOCAL Python interpreter. It is NOT a perfect mirror: CI runs the pytest suite
# on every version in its matrix (currently 3.10 and 3.13), while this hook only
# exercises whatever Python your .venv uses. The notice after the pytest step
# flags when your local version isn't one CI tests, so a version-specific failure
# can still surface in CI after a green local run.
set -e
```

- [ ] **Step 3: Append the non-fatal coverage notice after the pytest step**

Use Edit on `scripts/hooks/pre-push`.

old_string:

```bash
echo "▶ pytest..."
"${ARCH_PREFIX[@]}" "$VENV_PYTHON" -m pytest -q -m "not needs_gpu" --ignore=tests/contracts/test_mlx_contract.py

echo "✅ All checks passed."
```

new_string:

```bash
echo "▶ pytest..."
"${ARCH_PREFIX[@]}" "$VENV_PYTHON" -m pytest -q -m "not needs_gpu" --ignore=tests/contracts/test_mlx_contract.py

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

echo "✅ All checks passed."
```

> The space-padded `case` glob (`" $CI_PY_VERSIONS "` vs `*" $LOCAL_PYV "*`) prevents prefix collisions: `3.1` will not match `3.10`. On the maintainer's 3.14, `" 3.10 3.13 "` does not contain `" 3.14 "`, so the notice fires.

- [ ] **Step 4: Reinstall the hook so `.git/hooks/pre-push` matches source**

Run: `bash scripts/install-hooks.sh`
Expected: installer output indicating hooks were (re)installed. Per CLAUDE.md, the installed copy must never drift from `scripts/hooks/`.

- [ ] **Step 5: Verify the hook is honest and the notice fires (green)**

Run: `grep -c "Mirrors the CI pipeline exactly" scripts/hooks/pre-push`
Expected: `0` (false claim removed).

Run the full hook to confirm it still passes AND prints the notice (maintainer is on 3.14):

Run: `bash .git/hooks/pre-push`
Expected: ends with `✅ All checks passed.` (exit 0), and includes a line like
`⚠ pytest ran on local Python 3.14; CI runs it on: 3.10 3.13.`

> This single run is the real test of Task 2: it proves the edited hook still gates correctly (exit 0) and that the new notice triggers for an out-of-matrix local interpreter.

- [ ] **Step 6: Commit**

```bash
git add scripts/hooks/pre-push
git commit -m "chore(hooks): make pre-push honest about the CI Python matrix" \
  -m "Drop the false 'mirrors CI exactly' claim and add a non-fatal notice when the local interpreter isn't one CI tests (3.10, 3.13), so a version-specific failure can't slip through a green local run unannounced." \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Expected: `✅ pre-commit: all checks passed.` and the commit is created. (`.git/hooks/pre-push` is intentionally NOT staged — it lives outside the repo tree.)

---

## Task 3: Full gate, push, and verify green CI (Definition of Done)

**Files:** none — this is the verification gate from CLAUDE.md.

- [ ] **Step 1: Run the full pre-push pipeline locally**

Run: `bash .git/hooks/pre-push`
Expected: exit 0, ending in `✅ All checks passed.`, with the 3.14 mismatch notice shown. If it fails, fix the cause before pushing — do not use `--no-verify`.

- [ ] **Step 2: Push both commits to main**

Run: `git push origin main`
Expected: push succeeds (the pre-push hook runs again as part of `git push` and must pass).

- [ ] **Step 3: Watch the Actions run for both matrix legs**

Run: `gh run list --branch main --limit 3`
Then watch the newest run: `gh run watch <run-id> --exit-status`
Expected: the `lint` job and **both** `test (3.10)` and `test (3.13)` legs conclude **success**.

- [ ] **Step 4: If the 3.13 leg fails, diagnose and fix**

The 3.13 leg has never run before, so it may surface a genuine latent issue (that is the footgun being exposed) or a dependency-wheel issue. Inspect with:

Run: `gh run view <run-id> --log-failed`

Then fix the root cause (e.g. a 3.13-incompatible call, or — if a dependency genuinely lacks 3.13 Linux wheels — reconsider the recent-leg version with the user). Re-run Task 3 from Step 1. Do not declare done until CI is green.

- [ ] **Step 5: Report done with the CLAUDE.md checklist**

Only after a green Actions run, report completion using the project's Definition-of-Done checklist (all changes implemented; `bash .git/hooks/pre-push` ran and exited 0 this session; frontend untouched; GitHub Actions CI green).

---

## Self-Review

- **Spec coverage:** CI matrix → Task 1. Honest header + notice + `CI_PY_VERSIONS` constant → Task 2. Hook reinstall → Task 2 Step 4. Verification / Definition of Done → Task 3. "Keep `config.py` / defer `datetime.utcnow()`" → respected (those files are untouched). All spec sections map to a task.
- **Placeholder scan:** none — every code/edit step shows the exact `old_string`/`new_string` or command and expected output.
- **Consistency:** `CI_PY_VERSIONS="3.10 3.13"` in the hook matches the matrix `["3.10", "3.13"]` in `ci.yml`; the notice's expected output (`3.10 3.13`) matches the constant; commit trailers match the repo mandate.
