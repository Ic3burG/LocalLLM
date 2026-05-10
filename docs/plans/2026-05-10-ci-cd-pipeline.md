# CI/CD Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a GitHub Actions CI/CD pipeline for automated linting, testing, and security scanning.

**Architecture:** A GitHub Actions workflow (`ci.yml`) that runs on every push and pull request. It will use `ruff` for Python linting/formatting, `prettier` for Node.js/HTML/CSS, and `pytest` for unit testing (skipping GPU-dependent tests on standard runners).

**Tech Stack:** GitHub Actions, Ruff, Prettier, Pytest.

---

### Task 1: Initialize Linting and Formatting Configurations

**Files:**

- Create: `pyproject.toml`
- Create: `.prettierrc`
- Modify: `gemma-web/package.json`

**Step 1: Create pyproject.toml for Ruff**

```toml
[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I"]
ignore = []

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

**Step 2: Create .prettierrc for Web Assets**

```json
{
  "semi": true,
  "singleQuote": false,
  "tabWidth": 2,
  "trailingComma": "es5"
}
```

**Step 3: Update gemma-web/package.json with lint scripts**

```json
{
  "scripts": {
    "test": "echo \"Error: no test specified\" && exit 1",
    "lint": "npx prettier --check .",
    "format": "npx prettier --write ."
  }
}
```

**Step 4: Commit**

```bash
git add pyproject.toml .prettierrc gemma-web/package.json
git commit -m "chore: add linting and formatting configurations"
```

---

### Task 2: Create GitHub Actions Workflow

**Files:**

- Create: `.github/workflows/ci.yml`

**Step 1: Define the CI workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - name: Install Ruff
        run: pip install ruff
      - name: Run Ruff Check
        run: ruff check .
      - name: Run Ruff Format Check
        run: ruff format --check .
      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Run Prettier Check
        run: npx prettier --check .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio
      - name: Run Tests (Skip GPU)
        run: |
          # We skip MLX/GPU tests as standard runners don't have Apple Silicon/GPU
          pytest -v -m "not needs_gpu" --ignore=tests/contracts/test_mlx_contract.py
```

**Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "feat: add GitHub Actions CI workflow"
```

---

### Task 3: Verify and Push

**Step 1: Run local lint checks**

Run: `ruff check . && npx prettier --check .`
Expected: PASS (or minor fixes needed)

**Step 2: Push to remote**

Run: `git push origin main`
Expected: CI workflow triggers on GitHub.
