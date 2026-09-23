# Script Import Table Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve imported screenplay fields in the script table while keeping generation tasks unchanged.

**Architecture:** Add a backend normalizer beside the existing screenplay JSON parser. The import endpoint returns both the existing task rows and a normalized script object. The browser renders the normalized script when present and falls back to the existing task-only path for prompt blocks.

**Tech Stack:** Python `unittest`, existing `batch_console.py` HTTP handler, vanilla JavaScript in `console/index.html`.

---

### Task 1: Add failing parser and endpoint regression tests

**Files:**
- Create: `console/tests/test_script_import.py`
- Test: `console/tests/test_script_import.py`

- [x] **Step 1: Write the failing test**

  Add tests that call `batch_console.parse_script_json` and assert the returned metadata contains a normalized script with populated fields, plus an HTTP-level test that checks `/api/import_script` returns both `script` and `tasks`.

- [x] **Step 2: Run the focused tests to verify they fail**

  Run `python -m unittest discover -s console/tests -p 'test_*.py' -v`.
  Expected: failures because the parser metadata has no normalized script and the endpoint does not return `script`.

### Task 2: Return normalized script data from the backend

**Files:**
- Modify: `console/batch_console.py` near `_extract_roles`, `_extract_storyboards`, and `/api/import_script`

- [x] **Step 1: Implement the smallest normalizer**

  Normalize role and storyboard aliases into `{title, logline, role_list, storyboard_list}` while preserving `scene`, `roles`, `action`, `dialogue`, `emotion`, `camera`, `duration`, and source prompt fields. Add the normalized object to the import response without changing task generation.

- [x] **Step 2: Run the focused tests**

  Run `python -m unittest discover -s console/tests -p 'test_*.py' -v`.
  Expected: all focused tests pass.

### Task 3: Render the normalized script in the browser

**Files:**
- Modify: `console/index.html` in `doPaste()`

- [x] **Step 1: Prefer `d.script` for JSON imports**

  Keep the existing `d.script` branch and make `/api/import_script` provide that shape. Preserve the current task/prompt fallback branch for prompt blocks and legacy task imports.

- [x] **Step 2: Run static checks**

  Run `python -m py_compile console/batch_console.py` and inspect the changed JavaScript branch for balanced syntax.

### Task 4: Document and verify the change

**Files:**
- Modify: `console/CHANGELOG.md` at the top

- [x] **Step 1: Add the required changelog entry**

  Record the backend/frontend change, test commands, runtime impact, and error behavior using the repository's five required sections.

- [x] **Step 2: Run the full verification commands**

  Run `python -m unittest discover -s console/tests -p 'test_*.py' -v` and `python -m py_compile console/batch_console.py console/start_daemons.py console/chain_daemon.py`.
