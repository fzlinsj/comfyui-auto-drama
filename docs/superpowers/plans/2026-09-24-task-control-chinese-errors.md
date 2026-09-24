# Task Control Chinese UI and Error Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the task control center fully Chinese for user-facing text and prevent non-JSON API responses from surfacing as JavaScript parse errors.

**Architecture:** Keep technical identifiers such as attempt IDs, prompt IDs, GPU names, filenames, and node names unchanged. Add one shared response parser in the task-control JavaScript path, use it for task-control GET/POST calls, and return JSON for unmatched API routes so the UI always receives a structured error.

**Tech Stack:** Vanilla JavaScript, Python `BaseHTTPRequestHandler`, `unittest` source-contract tests.

---

### Task 1: Lock the requested behavior with regression tests

**Files:**
- Modify: `console/tests/test_task_control_ui.py`

- [x] Add assertions for Chinese task-control labels and non-JSON parsing markers.
- [x] Run `python -m unittest console.tests.test_task_control_ui -v` and confirm the new assertions fail against the current page.

### Task 2: Localize task-control UI and harden response parsing

**Files:**
- Modify: `console/index.html`

- [x] Translate task-control headings, filters, buttons, status labels, summaries, modal text, confirmations, and error messages while leaving technical values untouched.
- [x] Add a response helper that reads text first, parses JSON when possible, and emits `任务控制接口未找到，请重启控制台服务` for a 404/non-JSON task-control response.
- [x] Use the helper for task-control list loading, attempt details, and task-control POST actions.
- [x] Run the focused UI contract test and confirm it passes.

### Task 3: Normalize unmatched API responses and verify the whole change

**Files:**
- Modify: `console/batch_console.py`
- Modify: `console/CHANGELOG.md`

- [x] Return JSON `{ "error": "not found" }` for unmatched GET/POST API routes instead of plain text.
- [x] Add a changelog entry describing the Chinese UI and structured error handling, including verification commands and impact.
- [x] Run the full unittest suite, Python compilation checks, and `git diff --check`.
