# Agnes Image API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the console send Agnes-compatible image generation requests and save returned images.

**Architecture:** Add a provider-specific Agnes adapter beside the existing OpenAI and DashScope adapters. Select it explicitly via the image provider type or automatically when the configured cloud URL is an Agnes URL. Keep `/api/asset_gen` and other providers unchanged.

**Tech Stack:** Python standard library HTTP/JSON/base64, `unittest`, vanilla HTML select.

---

### Task 1: Add failing Agnes adapter tests

**Files:**
- Create: `console/tests/test_agnes_image.py`

- [x] **Step 1: Write tests for payload, URL download, and error preservation**

  Assert `768x1024` maps to `size: 2K`, `ratio: 3:4`, and `return_base64: true`; simulate an Agnes URL response, assert the bytes are saved, and ensure a cloud failure is not masked by local fallback.

- [x] **Step 2: Run tests and verify they fail**

  Run `python -m unittest console.tests.test_agnes_image -v`.
  Expected: failure because the Agnes payload helper and adapter do not exist.

### Task 2: Implement Agnes adapter and provider selection

**Files:**
- Modify: `console/batch_console.py` near `_img_openai`, `_IMG_ADAPTERS`, and `boogu_generate`
- Modify: `console/index.html` near `imgProviderType`

- [x] **Step 1: Implement Agnes payload/response handling**

  Add size/ratio mapping, Agnes request payload construction, URL/b64 response handling, and explicit/URL-based adapter selection.

- [x] **Step 2: Run focused tests**

  Run `python -m unittest console.tests.test_agnes_image -v` and expect all tests to pass.

### Task 3: Document and verify

**Files:**
- Modify: `console/CHANGELOG.md` at the top

- [x] **Step 1: Add the required changelog entry**

  Record the Agnes request format, verification commands, compatibility impact, and error behavior.

- [x] **Step 2: Run full checks**

  Run `python -m unittest discover -s console/tests -p 'test_*.py' -v`, `python -m py_compile console/batch_console.py console/start_daemons.py console/chain_daemon.py`, and `git diff --check`.
