# Generation Control, Diagnostics, and ComfyUI Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reliable task control center, two-level service diagnostics, and an SDXL-based ComfyUI image provider without breaking existing projects or silently spending API/GPU resources.

**Architecture:** Extract ComfyUI communication, error parsing, task attempts, and diagnostics from `batch_console.py` into focused standard-library modules. Keep the existing key/value SQLite state and legacy HTTP endpoints as a compatibility layer while new normalized task-attempt tables and APIs become the source of truth. Reuse one ComfyUI client and one polling/error model for video generation, diagnostic jobs, and SDXL image generation.

**Tech Stack:** Python 3 standard library, SQLite, `unittest`, Pillow, vanilla HTML/CSS/JavaScript, ComfyUI HTTP API, MiniMax H3 workflows, standard SDXL ComfyUI nodes.

---

## File responsibility map

The implementation must use these boundaries instead of adding more unrelated logic to `console/batch_console.py`:

- `console/comfyui_client.py`: ComfyUI HTTP requests, queue/history/profile access, uploads/downloads, cancellation, server fingerprint, and workflow preflight.
- `console/failure_diagnostics.py`: provider-neutral error codes, ComfyUI error extraction, user-facing summaries, and secret redaction.
- `console/task_store.py`: new SQLite schema, legacy task migration, task attempts, diagnostic runs, image jobs, and transition validation.
- `console/task_service.py`: task refresh, preflight, submission, single-attempt retry, cancellation, stale detection, and chain dependency handling.
- `console/service_diagnostics.py`: quick checks and explicitly confirmed real tests for LLM, image providers, vision, T2V, I2V, R2V, and SDXL.
- `console/image_providers.py`: Agnes, Boogu, OpenAI/DashScope compatibility, and ComfyUI SDXL provider selection without silent fallback.
- `workflows/build_sdxl_graph.py`: build the standard-node SDXL API graph from a checked-in template.
- `workflows/sdxl_image_api_template.json`: stable standard-node SDXL workflow.
- `console/batch_console.py`: HTTP routing and compatibility wrappers only; it must call the modules above.
- `console/index.html`: task control center, diagnostics UI, image-provider settings, and polling.
- `console/tests/`: isolated unit and integration-style tests using fake ComfyUI responses.

## Compatibility rules used by every task

- Do not delete or recreate `console/console.db`.
- Keep the existing `state` key/value table and current project snapshots.
- Keep `/api/status`, `/api/submit`, `/api/regenerate`, and `/api/asset_gen` working while new endpoints are introduced.
- Never infer success solely from HTTP connectivity; generation modes become `available` only after a real output is downloaded and validated.
- Never automatically lower resolution, retry a failed generation, or switch image providers.
- Every code, UI, rule, or workflow change adds a new entry at the top of `console/CHANGELOG.md`.
- Each implementation task starts with a failing test and ends with the focused test, full suite, `py_compile`, and `git diff --check`.

---

### Task 1: Extract the ComfyUI client and structured failure parser

**Files:**
- Create: `console/comfyui_client.py`
- Create: `console/failure_diagnostics.py`
- Create: `console/tests/test_comfyui_client.py`
- Create: `console/tests/test_failure_diagnostics.py`
- Modify: `console/batch_console.py:156-220`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: Write failing tests for profile, workflow preflight, cancellation, OOM parsing, and redaction**

Create `console/tests/test_comfyui_client.py` with a fake transport and these concrete assertions:

```python
import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from comfyui_client import ComfyUIClient


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.posts = []

    def get_json(self, path, timeout=15):
        return self.responses[path]

    def post_json(self, path, payload, timeout=30):
        self.posts.append((path, payload))
        return {"ok": True}


class ComfyUIClientTests(unittest.TestCase):
    def test_profile_reports_gpu_vram_and_queue(self):
        transport = FakeTransport({
            "/system_stats": {
                "system": {"comfyui_version": "0.31.0"},
                "devices": [{"name": "NVIDIA GeForce RTX 3090", "vram_total": 24_000, "vram_free": 12_000}],
            },
            "/queue": {"queue_running": [[1, "running-id"]], "queue_pending": [[2, "pending-id"]]},
        })
        profile = ComfyUIClient("http://comfy", transport=transport).profile()
        self.assertEqual(profile["gpu_name"], "NVIDIA GeForce RTX 3090")
        self.assertEqual(profile["queue_running"], 1)
        self.assertEqual(profile["queue_pending"], 1)

    def test_preflight_reports_missing_node_and_model(self):
        transport = FakeTransport({
            "/object_info": {
                "CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": [["installed.safetensors"]]}}
                }
            }
        })
        graph = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "missing.safetensors"}},
            "2": {"class_type": "UnknownNode", "inputs": {}},
        }
        result = ComfyUIClient("http://comfy", transport=transport).preflight(graph)
        self.assertEqual(result["missing_nodes"], ["UnknownNode"])
        self.assertEqual(result["missing_models"], ["missing.safetensors"])

    def test_delete_pending_posts_exact_prompt_id(self):
        transport = FakeTransport({})
        ComfyUIClient("http://comfy", transport=transport).delete_pending("prompt-1")
        self.assertEqual(transport.posts, [("/queue", {"delete": ["prompt-1"]})])


if __name__ == "__main__":
    unittest.main()
```

Create `console/tests/test_failure_diagnostics.py`:

```python
import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from failure_diagnostics import parse_comfyui_failure, redact_secrets


class FailureDiagnosticTests(unittest.TestCase):
    def test_oom_contains_node_and_actionable_summary(self):
        entry = {"status": {"messages": [["execution_error", {
            "node_id": "125",
            "node_type": "SamplerCustomAdvanced",
            "exception_type": "torch.OutOfMemoryError",
            "exception_message": "Allocation on device",
        }]]}}
        failure = parse_comfyui_failure(entry)
        self.assertEqual(failure["code"], "F-OOM")
        self.assertEqual(failure["node_id"], "125")
        self.assertEqual(failure["node_type"], "SamplerCustomAdvanced")
        self.assertIn("显存不足", failure["summary"])

    def test_redaction_removes_bearer_and_configured_keys(self):
        text = "Authorization: Bearer secret-token api_key=cpk-private"
        cleaned = redact_secrets(text, ["secret-token", "cpk-private"])
        self.assertNotIn("secret-token", cleaned)
        self.assertNotIn("cpk-private", cleaned)
        self.assertIn("***", cleaned)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused tests and verify they fail because the modules do not exist**

Run:

```powershell
python -m unittest console.tests.test_comfyui_client console.tests.test_failure_diagnostics -v
```

Expected: import failures for `comfyui_client` and `failure_diagnostics`.

- [ ] **Step 3: Implement the structured error model**

Create `console/failure_diagnostics.py` with these public functions and exact output keys:

```python
import re


FAILURE_SUMMARIES = {
    "F-OOM": "GPU 显存不足",
    "F-MODEL-MISSING": "工作流引用的模型不存在",
    "F-NODE-MISSING": "工作流依赖节点不存在",
    "F-WORKFLOW-INVALID": "ComfyUI 工作流校验失败",
    "F-ASSET-MISSING": "参考素材不存在或不可读取",
    "F-CONNECTION": "无法连接服务",
    "F-AUTH": "接口鉴权失败",
    "F-SERVER-STALE": "任务不属于当前服务器或已被远端清除",
    "F-CANCELLED": "任务已由用户取消",
    "F-PROVIDER-RESPONSE": "供应商返回格式异常",
}


def _execution_error(entry):
    for name, payload in (entry.get("status") or {}).get("messages", []):
        if name == "execution_error":
            return payload or {}
    return {}


def parse_comfyui_failure(entry):
    error = _execution_error(entry)
    exception_type = str(error.get("exception_type") or "")
    message = str(error.get("exception_message") or "")
    combined = f"{exception_type} {message}".lower()
    if "outofmemory" in combined or "out of memory" in combined or "allocation on device" in combined:
        code = "F-OOM"
    elif "does not exist" in combined or "not in list" in combined:
        code = "F-MODEL-MISSING"
    else:
        code = "F-WORKFLOW-INVALID"
    return {
        "code": code,
        "summary": FAILURE_SUMMARIES[code],
        "node_id": str(error.get("node_id") or ""),
        "node_type": str(error.get("node_type") or ""),
        "exception_type": exception_type,
        "raw_error": message,
    }


def redact_secrets(value, secrets=()):
    text = str(value or "")
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1***", text)
    text = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1***", text)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "***")
    return text
```

- [ ] **Step 4: Implement `ComfyUIClient` and workflow preflight**

Create `console/comfyui_client.py` with a default urllib transport and these methods:

```python
class ComfyUIClient:
    def __init__(self, server, transport=None): ...
    def profile(self): ...
    def queue(self): ...
    def history(self, prompt_id=None): ...
    def object_info(self): ...
    def preflight(self, graph): ...
    def submit(self, graph, client_id="batch_console"): ...
    def interrupt(self): ...
    def delete_pending(self, prompt_id): ...
    def upload_image(self, local_path, filename): ...
    def download_output(self, output_meta, destination): ...
    def server_fingerprint(self): ...
```

`preflight()` must inspect every `class_type`; for known model-loader input names (`ckpt_name`, `unet_name`, `clip_name`, `vae_name`, `lora_name`) it must compare the graph value with the option list exposed by the corresponding node. It returns:

```python
{
    "ok": not missing_nodes and not missing_models,
    "missing_nodes": sorted(missing_nodes),
    "missing_models": sorted(missing_models),
    "warnings": [],
}
```

`server_fingerprint()` must hash normalized server URL, ComfyUI version, GPU name, and the presence/model options of project-required nodes. Do not include free VRAM or queue contents because they change during normal use.

- [ ] **Step 5: Replace the old low-level wrappers with compatibility delegates**

In `console/batch_console.py`, keep the public names `api_get`, `api_post`, and `upload_image`, but make new code paths instantiate `ComfyUIClient`. Do not refactor `submit_tasks` in this task; Task 3 will do that after the task store exists.

- [ ] **Step 6: Update the changelog and verify Task 1**

Add a top changelog entry titled `抽离 ComfyUI 客户端与结构化错误解析` with verification and impact sections.

Run:

```powershell
python -m unittest console.tests.test_comfyui_client console.tests.test_failure_diagnostics -v
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/comfyui_client.py console/failure_diagnostics.py console/batch_console.py
git diff --check
```

Expected: all tests pass; no compilation or whitespace errors.

- [ ] **Step 7: Commit Task 1**

```powershell
git add console/comfyui_client.py console/failure_diagnostics.py console/tests/test_comfyui_client.py console/tests/test_failure_diagnostics.py console/batch_console.py console/CHANGELOG.md
git commit -m "refactor: add ComfyUI client and failure diagnostics"
```

---

### Task 2: Add normalized task-attempt storage and idempotent legacy migration

**Files:**
- Create: `console/task_store.py`
- Create: `console/tests/test_task_store.py`
- Modify: `console/batch_console.py:223-280`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: Write failing storage and migration tests**

Create tests that use a temporary SQLite file and assert:

```python
def test_migrate_legacy_tasks_is_idempotent(self):
    legacy = [{
        "id": "task-1", "name": "episode_01", "prompt_id": "prompt-1",
        "mode": "t2v", "duration": 5, "mp": 0.4,
        "downloaded": True,
        "output_file": {"filename": "episode.mp4", "subfolder": "video", "type": "output"},
    }]
    store.migrate_legacy_tasks(legacy, "http://comfy")
    store.migrate_legacy_tasks(legacy, "http://comfy")
    self.assertEqual(len(store.list_attempts()), 1)
    self.assertEqual(store.list_attempts()[0]["status"], "succeeded")


def test_illegal_transition_is_rejected(self):
    attempt_id = store.create_attempt(segment_key="episode_01", status="queued", parameters={})
    with self.assertRaisesRegex(ValueError, "queued.*ready"):
        store.transition(attempt_id, "ready")


def test_diagnostic_run_round_trip(self):
    run_id = store.create_diagnostic_run("comfyui_t2v", "real", {"mp": 0.2})
    store.finish_diagnostic_run(run_id, "succeeded", {"filename": "test.mp4"})
    self.assertEqual(store.get_diagnostic_run(run_id)["result"]["filename"], "test.mp4")
```

- [ ] **Step 2: Run the focused test and verify the missing module failure**

```powershell
python -m unittest console.tests.test_task_store -v
```

- [ ] **Step 3: Create the normalized schema**

`console/task_store.py` must create these tables without altering the existing `state` table:

```sql
CREATE TABLE IF NOT EXISTS task_segments (
    segment_key TEXT PRIMARY KEY,
    project_name TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_attempts (
    attempt_id TEXT PRIMARY KEY,
    legacy_task_id TEXT UNIQUE,
    segment_key TEXT NOT NULL,
    parent_attempt_id TEXT,
    batch_id TEXT,
    kind TEXT NOT NULL DEFAULT 'video',
    status TEXT NOT NULL,
    server_url TEXT NOT NULL DEFAULT '',
    server_fingerprint TEXT NOT NULL DEFAULT '',
    prompt_id TEXT,
    parameters_json TEXT NOT NULL,
    output_json TEXT,
    failure_json TEXT,
    missing_poll_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(segment_key) REFERENCES task_segments(segment_key)
);

CREATE TABLE IF NOT EXISTS diagnostic_runs (
    run_id TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    level TEXT NOT NULL,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    result_json TEXT,
    failure_json TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_segment_created
ON task_attempts(segment_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_attempts_prompt
ON task_attempts(prompt_id);
```

- [ ] **Step 4: Implement legal transitions and JSON serialization**

Use this transition table exactly:

```python
ALLOWED_TRANSITIONS = {
    "preflight_pending": {"preflight_failed", "ready", "cancelled"},
    "preflight_failed": {"preflight_pending", "cancelled"},
    "ready": {"submitting", "cancelled"},
    "submitting": {"queued", "failed", "cancelled"},
    "queued": {"running", "succeeded", "failed", "cancel_requested", "cancelled", "stale"},
    "running": {"succeeded", "failed", "cancel_requested", "cancelled", "stale"},
    "cancel_requested": {"cancelled", "succeeded", "failed"},
    "blocked": {"preflight_pending", "cancelled"},
    "failed": {"preflight_pending"},
    "cancelled": {"preflight_pending"},
    "stale": {"preflight_pending"},
    "succeeded": {"preflight_pending"},
}
```

Terminal attempts are not overwritten when retried; a retry creates a new attempt with `parent_attempt_id`.

- [ ] **Step 5: Implement legacy migration**

`migrate_legacy_tasks(tasks, server_url)` must use `legacy_task_id` uniqueness and map status as follows:

- `output_file` or `downloaded` -> `succeeded`
- `error` with `F-LOST` -> `stale`
- other `error` -> `failed`
- `chain_waiting` without `prompt_id` -> `blocked`
- `prompt_id` -> `queued`
- otherwise -> `ready`

It must preserve the complete original task dictionary inside `parameters_json["legacy"]` and copy `output_file`, failure code, error text, and timestamps into normalized fields.

- [ ] **Step 6: Initialize the normalized store without changing existing state APIs**

In `batch_console.py`, call schema initialization during startup and call the idempotent migration after `load_state()`. `load_state()` and `save_state()` remain unchanged for project/config compatibility.

- [ ] **Step 7: Update changelog, verify, and commit Task 2**

```powershell
python -m unittest console.tests.test_task_store -v
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/task_store.py console/batch_console.py
git diff --check
git add console/task_store.py console/tests/test_task_store.py console/batch_console.py console/CHANGELOG.md
git commit -m "feat: persist normalized task attempts"
```

---

### Task 3: Implement task orchestration, preflight, cancellation, stale detection, and retry APIs

**Files:**
- Create: `console/task_service.py`
- Create: `console/tests/test_task_service.py`
- Modify: `console/batch_console.py:1031-1633`
- Modify: `console/batch_console.py:3878-3883`
- Modify: `console/batch_console.py:4247-4854`
- Modify: `console/chain_daemon.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: Write failing service tests using fake ComfyUI clients**

Cover these exact behaviors:

```python
def test_missing_model_blocks_submission(self):
    client.preflight_result = {"ok": False, "missing_nodes": [], "missing_models": ["model.safetensors"], "warnings": []}
    result = service.preflight_attempt(attempt_id)
    self.assertEqual(result["status"], "preflight_failed")
    self.assertEqual(result["failure"]["code"], "F-MODEL-MISSING")
    self.assertEqual(client.submitted_graphs, [])


def test_two_successful_missing_polls_mark_attempt_stale(self):
    client.queue_result = {"queue_running": [], "queue_pending": []}
    client.history_result = {}
    service.refresh_attempt(attempt_id)
    first = store.get_attempt(attempt_id)
    self.assertEqual(first["status"], "queued")
    self.assertEqual(first["missing_poll_count"], 1)
    service.refresh_attempt(attempt_id)
    self.assertEqual(store.get_attempt(attempt_id)["status"], "stale")


def test_connection_failure_never_increments_missing_poll_count(self):
    client.queue_error = ConnectionError("offline")
    service.refresh_attempt(attempt_id)
    self.assertEqual(store.get_attempt(attempt_id)["missing_poll_count"], 0)


def test_retry_creates_child_attempt_and_does_not_mutate_failed_parent(self):
    child = service.retry_attempt(failed_attempt_id, {"mp": 0.4, "steps": 4})
    self.assertEqual(child["parent_attempt_id"], failed_attempt_id)
    self.assertEqual(store.get_attempt(failed_attempt_id)["status"], "failed")


def test_cancel_pending_deletes_only_requested_prompt(self):
    service.cancel_attempt(queued_attempt_id)
    self.assertEqual(client.deleted_prompt_ids, ["queued-prompt"])
    self.assertEqual(store.get_attempt(queued_attempt_id)["status"], "cancelled")
```

Also test running-task interrupt confirmation metadata, batch cancellation scope, blocked chain handling, selecting an earlier successful predecessor, and disabling chain mode for a retry.

- [ ] **Step 2: Run the focused tests and confirm they fail before implementation**

```powershell
python -m unittest console.tests.test_task_service -v
```

- [ ] **Step 3: Implement `TaskService` public operations**

Create these methods in `console/task_service.py`:

```python
class TaskService:
    def list_control_tasks(self, project_name="", status_filter=""): ...
    def preflight_attempt(self, attempt_id): ...
    def submit_attempt(self, attempt_id): ...
    def refresh_attempt(self, attempt_id): ...
    def refresh_active_attempts(self): ...
    def retry_attempt(self, attempt_id, overrides): ...
    def cancel_attempt(self, attempt_id): ...
    def cancel_batch(self, batch_id, cancel_running=False): ...
    def resolve_chain(self, attempt_id, predecessor_attempt_id=None, disable_chain=False): ...
```

`preflight_attempt()` builds the real graph before submission and returns three severities:

- `block`: missing server/node/model/asset or invalid input.
- `warning`: known VRAM risk.
- `pass`: submit is allowed.

For RTX 3090-class GPUs, R2V with `mp >= 1.0`, `duration >= 10`, and four or more references must return a high-risk warning containing the current parameters. It must not change them.

- [ ] **Step 4: Parse real history errors and validate downloaded outputs**

When history reports `execution_error`, call `parse_comfyui_failure()` and store the structured failure. When history reports success, download every output to a temporary `.part` file, verify non-zero size, and for video use `ffprobe`; only then atomically rename it and mark `succeeded`.

If a valid local output already exists, keep `succeeded` even when ComfyUI history is empty.

- [ ] **Step 5: Add the new task-control APIs while keeping legacy endpoints**

Add:

```text
GET  /api/tasks/control?project=&status=
GET  /api/task/attempt?attempt_id=
POST /api/task/preflight       {attempt_id}
POST /api/task/submit          {attempt_id, confirm_warnings}
POST /api/task/retry           {attempt_id, overrides}
POST /api/task/cancel          {attempt_id, confirm_interrupt}
POST /api/batch/cancel         {batch_id, cancel_running}
POST /api/task/resolve_chain   {attempt_id, predecessor_attempt_id, disable_chain}
```

Every POST returns the updated attempt. `/api/status`, `/api/submit`, and `/api/regenerate` must create/update normalized attempts through `TaskService` but retain their existing response shapes.

- [ ] **Step 6: Replace the daemon's implicit chain mutation with service refresh**

`console/chain_daemon.py` must call `TaskService.refresh_active_attempts()` every 20 seconds. It must not auto-fallback to an earlier video or T2V when a predecessor fails. A failed predecessor changes dependents to `blocked`; only `resolve_chain()` can choose a successful version or disable chaining.

- [ ] **Step 7: Update changelog, verify, and commit Task 3**

```powershell
python -m unittest console.tests.test_task_service console.tests.test_chain_resume -v
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/task_service.py console/batch_console.py console/chain_daemon.py
git diff --check
git add console/task_service.py console/tests/test_task_service.py console/batch_console.py console/chain_daemon.py console/CHANGELOG.md
git commit -m "feat: add controllable generation task lifecycle"
```

---

### Task 4: Replace Step 7 with the task control center UI

**Files:**
- Create: `console/tests/test_task_control_ui.py`
- Modify: `console/index.html:407-445`
- Modify: `console/index.html:1420-1480`
- Modify: `console/index.html:1765-1815`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: Write a failing source-level UI contract test**

The test must assert these stable DOM IDs and handlers exist:

```python
REQUIRED_IDS = [
    "taskServerSummary", "taskStatusFilter", "taskControlList",
    "btnCancelBatch", "taskDetailModalBg", "taskFailureDetail",
    "taskRetryMp", "taskRetrySteps", "taskRetryDuration",
    "taskRetryChain", "taskRetryPredecessor", "btnTaskRetrySubmit",
]

REQUIRED_FUNCTIONS = [
    "loadTaskControl", "renderTaskControl", "openTaskAttempt",
    "preflightTaskAttempt", "retryTaskAttempt", "cancelTaskAttempt",
    "cancelCurrentBatch", "resolveBlockedChain",
]
```

Run `python -m unittest console.tests.test_task_control_ui -v` and verify it fails against the existing page.

- [ ] **Step 2: Build the task control center markup**

The top of panel 7 must show:

- server address and fingerprint-short-id;
- GPU and VRAM summary;
- running/pending counts;
- last successful refresh time;
- filters for all, active, failed, cancelled, succeeded, stale, blocked;
- batch buttons for cancel waiting and cancel current batch.

Each segment row shows only the latest attempt by default and an expandable attempt history. Use badges for `queued`, `running`, `succeeded`, `failed`, `cancelled`, `stale`, and `blocked`; only `queued` and `running` receive spinners.

- [ ] **Step 3: Add the attempt detail/retry modal**

The modal must display prompt, mode, duration, megapixels, steps, references, chain predecessor, server fingerprint, prompt ID, failure summary, node ID/type, and raw redacted details.

Actions are status-specific:

- queued -> cancel;
- running -> interrupt with exact task-name confirmation;
- failed/cancelled/stale/succeeded -> original-parameter retry or modified retry;
- blocked -> choose a successful predecessor or disable chaining;
- succeeded -> play, download, select for assembly, regenerate.

- [ ] **Step 4: Wire new APIs and prevent whole-batch resubmission**

`retryTaskAttempt()` calls `/api/task/retry` and then `/api/task/submit` for the returned child attempt only. It must never call `/api/submit` or iterate `promptTasks`.

After a successful retry, reset the task page/filter, close the modal, load task control data, and keep polling every eight seconds.

- [ ] **Step 5: Preserve a compatibility path for old records**

If `/api/tasks/control` returns a migration error, show a visible failure card and leave the existing `/api/status` renderer available behind a “查看旧任务列表” link. Do not silently render an empty list.

- [ ] **Step 6: Verify UI behavior in a browser**

After unit tests pass, restart local daemons, reload `http://127.0.0.1:8890`, and verify:

1. completed videos still play;
2. failed attempt details show error and retry buttons;
3. stale attempts do not spin;
4. retry creates one child attempt;
5. cancellation asks for confirmation and updates without reload;
6. layout works at desktop width and 390px width.

- [ ] **Step 7: Update changelog, run checks, and commit Task 4**

```powershell
python -m unittest console.tests.test_task_control_ui -v
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/batch_console.py console/task_service.py
git diff --check
git add console/index.html console/tests/test_task_control_ui.py console/CHANGELOG.md
git commit -m "feat: add generation task control center"
```

---

### Task 5: Implement the two-level service diagnostics backend

**Files:**
- Create: `console/service_diagnostics.py`
- Create: `console/tests/test_service_diagnostics.py`
- Modify: `console/batch_console.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: Write failing diagnostics tests**

Test these behaviors with fake adapters:

```python
def test_quick_check_never_calls_generation(self):
    results = diagnostics.quick_check_all()
    self.assertEqual(fake_image.generate_calls, [])
    self.assertEqual(fake_comfy.submit_calls, [])
    self.assertEqual(results["comfyui"]["level"], "quick")


def test_provider_without_free_probe_requires_real_test(self):
    result = diagnostics.quick_check_service("agnes")
    self.assertEqual(result["status"], "needs_real_test")


def test_real_test_requires_explicit_confirmation(self):
    with self.assertRaisesRegex(ValueError, "confirm_cost"):
        diagnostics.start_real_test("agnes", confirm_cost=False)


def test_t2v_success_does_not_mark_i2v_or_r2v_available(self):
    diagnostics.finish_real_test("comfyui_t2v", output={"filename": "t2v.mp4"})
    summary = diagnostics.summary()
    self.assertEqual(summary["comfyui_t2v"]["status"], "available")
    self.assertNotEqual(summary["comfyui_i2v"]["status"], "available")
    self.assertNotEqual(summary["comfyui_r2v"]["status"], "available")
```

- [ ] **Step 2: Run the focused test and verify it fails**

```powershell
python -m unittest console.tests.test_service_diagnostics -v
```

- [ ] **Step 3: Implement quick checks**

`ServiceDiagnostics.quick_check_all()` returns entries for:

```text
comfyui
comfyui_t2v
comfyui_i2v
comfyui_r2v
comfyui_image
llm
agnes
boogu
vision
local_environment
```

Each result uses:

```python
{
    "service": "comfyui_t2v",
    "level": "quick",
    "status": "quick_passed",  # unconfigured / quick_passed / needs_real_test / failed
    "elapsed_ms": 12,
    "summary": "节点与模型齐全",
    "details": {},
    "failure": None,
    "checked_at": "2026-09-24 12:00:00",
}
```

Quick checks may call metadata/list endpoints but must never call `/prompt`, LLM chat completion, image generation, or vision inference.

- [ ] **Step 4: Implement explicitly confirmed real tests**

`start_real_test(service, confirm_cost, confirm_gpu)` creates one `diagnostic_runs` record and one background thread. It refuses requests when confirmation does not match the service risk:

- LLM, Agnes, cloud image, or cloud vision require `confirm_cost=True`.
- ComfyUI image/T2V/I2V/R2V require `confirm_gpu=True`.

Use these fixed test parameters:

- LLM: return JSON `{"ok": true, "service": "llm"}`.
- Agnes/Boogu: one 768x768 image with a diagnostic prompt.
- Vision: inspect a deterministic Pillow-generated test card.
- SDXL: 768x768, 12 steps for diagnostics.
- T2V/I2V/R2V: 0.2MP, 5 seconds, 4 steps.

Do not expose a backend operation that starts every real test at once.

- [ ] **Step 5: Add diagnostic endpoints**

```text
GET  /api/diagnostics/summary
POST /api/diagnostics/quick        {service: "all" | service_name}
POST /api/diagnostics/real         {service, confirm_cost, confirm_gpu}
GET  /api/diagnostics/run?run_id=
```

The run endpoint returns output media URLs only after the downloaded file passes validation. Redact configured keys from every failure and detail field.

- [ ] **Step 6: Update changelog, verify, and commit Task 5**

```powershell
python -m unittest console.tests.test_service_diagnostics -v
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/service_diagnostics.py console/batch_console.py
git diff --check
git add console/service_diagnostics.py console/tests/test_service_diagnostics.py console/batch_console.py console/CHANGELOG.md
git commit -m "feat: add service diagnostics backend"
```

---

### Task 6: Add the diagnostics center UI

**Files:**
- Create: `console/tests/test_diagnostics_ui.py`
- Modify: `console/index.html:500-665`
- Modify: `console/index.html:1856-1965`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: Write a failing UI contract test**

Require these IDs:

```python
[
    "diagnosticsPanel", "btnQuickCheckAll", "diagnosticsCards",
    "diagnosticConfirmModalBg", "diagnosticConfirmSummary",
    "diagnosticCostWarning", "diagnosticGpuWarning", "btnDiagnosticConfirm",
]
```

Require functions `loadDiagnostics`, `runQuickDiagnostic`, `openRealDiagnostic`, `confirmRealDiagnostic`, and `pollDiagnosticRun`.

- [ ] **Step 2: Add a diagnostics section to settings**

Each service card displays configured endpoint/model, masked credentials, quick status, real status, last checked time, elapsed time, output preview, and expandable redacted error details.

The page has one “快速检查全部” button. Every real test has its own button; do not add “真实测试全部”.

- [ ] **Step 3: Implement the confirmation modal**

Before a real test, display model, workflow, resolution, duration, steps, possible API cost, GPU use, and expected duration. The confirmation button sends only one service name.

- [ ] **Step 4: Render real outputs**

Image results use `<img>`; video results use `<video controls preload="metadata">`. A real test is shown as available only when the backend result is `succeeded` and the media URL is present.

- [ ] **Step 5: Browser verification**

Verify quick check does not create new remote queue entries. Verify the confirmation modal appears for each charged/GPU action. Run one harmless local-environment quick check and inspect mobile layout at 390px width.

- [ ] **Step 6: Update changelog, verify, and commit Task 6**

```powershell
python -m unittest console.tests.test_diagnostics_ui -v
python -m unittest discover -s console/tests -p 'test_*.py' -v
git diff --check
git add console/index.html console/tests/test_diagnostics_ui.py console/CHANGELOG.md
git commit -m "feat: add service diagnostics center"
```

---

### Task 7: Add ComfyUI SDXL as a formal image provider

**Files:**
- Create: `workflows/sdxl_image_api_template.json`
- Create: `workflows/build_sdxl_graph.py`
- Create: `console/image_providers.py`
- Create: `console/tests/test_sdxl_graph.py`
- Create: `console/tests/test_image_providers.py`
- Modify: `console/batch_console.py:2708-2939`
- Modify: `console/index.html:535-590`
- Modify: `config.example.json`
- Modify: `CONFIG.md`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: Write failing SDXL graph tests**

The graph test must assert:

```python
graph = build_sdxl_graph({
    "prompt": "cinematic signal room",
    "negative_prompt": "text, watermark",
    "width": 768,
    "height": 1024,
    "steps": 20,
    "seed": 123,
    "filename_prefix": "assets/test",
    "checkpoint": "sd_xl_base_1.0.safetensors",
})
self.assertEqual(nodes(graph, "CheckpointLoaderSimple")[0]["ckpt_name"], "sd_xl_base_1.0.safetensors")
self.assertEqual(nodes(graph, "EmptyLatentImage")[0]["width"], 768)
self.assertEqual(nodes(graph, "EmptyLatentImage")[0]["height"], 1024)
self.assertEqual(nodes(graph, "KSampler")[0]["sampler_name"], "dpmpp_2m")
self.assertEqual(nodes(graph, "KSampler")[0]["scheduler"], "karras")
```

- [ ] **Step 2: Write failing provider-selection and no-fallback tests**

Test legacy config normalization:

```python
self.assertEqual(normalize_image_provider({"provider": "local"})["active_provider"], "boogu")
self.assertEqual(normalize_image_provider({"provider": "cloud", "provider_type": "agnes"})["active_provider"], "agnes")
```

Test that a ComfyUI failure does not invoke Agnes or Boogu, and that an Agnes failure does not invoke another provider.

- [ ] **Step 3: Run focused tests and verify they fail**

```powershell
python -m unittest console.tests.test_sdxl_graph console.tests.test_image_providers -v
```

- [ ] **Step 4: Add the standard-node SDXL API workflow**

`workflows/sdxl_image_api_template.json` must contain only:

```text
CheckpointLoaderSimple
CLIPTextEncode (positive)
CLIPTextEncode (negative)
EmptyLatentImage
KSampler
VAEDecode
SaveImage
```

Use `sd_xl_base_1.0.safetensors`, `dpmpp_2m`, `karras`, CFG 7.0, denoise 1.0, and batch size 1. `build_sdxl_graph.py` loads the template with UTF-8 and overrides checkpoint, prompts, dimensions, seed, steps, and filename prefix.

- [ ] **Step 5: Implement provider normalization and adapters**

Use this new config shape while accepting legacy fields:

```json
"image_gen": {
  "active_provider": "agnes",
  "boogu": {"url": "http://127.0.0.1:8081"},
  "agnes": {"base_url": "https://apihub.agnes-ai.com/v1", "api_key": "", "model": "agnes-image-2.5-flash"},
  "openai": {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-image-1"},
  "dashscope": {"base_url": "https://dashscope.aliyuncs.com", "api_key": "", "model": "wanx-v1"},
  "comfyui": {
    "server": "inherit",
    "checkpoint": "sd_xl_base_1.0.safetensors",
    "steps": 20,
    "cfg": 7.0,
    "sampler": "dpmpp_2m",
    "scheduler": "karras"
  }
}
```

`generate_image(provider_name, request)` calls exactly one provider. Remove the existing automatic provider fallback. A vision QA failure returns the generated file and issues without automatically generating a second or third paid image.

- [ ] **Step 6: Add asynchronous ComfyUI image jobs**

For `active_provider=comfyui`, `/api/asset_gen` returns HTTP 202 with:

```json
{"async": true, "attempt_id": "...", "status": "queued"}
```

Add `GET /api/image_job?attempt_id=`. Poll through `TaskService`, download to a `.part` file, validate with Pillow `Image.verify()`, atomically move into the configured asset directory, and then run the existing asset QA once.

Synchronous providers keep HTTP 200 behavior, but they also return `provider` and must not retry automatically.

- [ ] **Step 7: Update the asset UI**

Settings must show a single provider selector with `Agnes`, `Boogu`, `ComfyUI`, `OpenAI`, and `DashScope`. Asset generation must handle both immediate HTTP 200 and async HTTP 202 responses. A ComfyUI image card shows queued/running/succeeded/failed and supports cancel/retry through the same task APIs.

- [ ] **Step 8: Add SDXL installation instructions without hard-coded code paths**

Update `CONFIG.md` with this AutoDL data-disk example, clearly labeling the path as an operational command rather than a code constant:

```bash
mkdir -p /root/autodl-tmp/ComfyUI/models/checkpoints
cd /root/autodl-tmp/ComfyUI/models/checkpoints
wget -c -O sd_xl_base_1.0.safetensors \
  https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors
```

Explain that the actual checkpoint directory must be the one exposed by that AutoDL image's ComfyUI. Diagnostics must verify the filename before generation.

- [ ] **Step 9: Update changelog, verify, and commit Task 7**

```powershell
python -m unittest console.tests.test_sdxl_graph console.tests.test_image_providers -v
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile workflows/build_sdxl_graph.py console/image_providers.py console/batch_console.py
python -m json.tool workflows/sdxl_image_api_template.json > $null
git diff --check
git add workflows/sdxl_image_api_template.json workflows/build_sdxl_graph.py console/image_providers.py console/tests/test_sdxl_graph.py console/tests/test_image_providers.py console/batch_console.py console/index.html config.example.json CONFIG.md console/CHANGELOG.md
git commit -m "feat: add ComfyUI SDXL image provider"
```

---

### Task 8: Run migration, regression, browser, and real RTX 3090 acceptance

**Files:**
- Create: `docs/testing/generation-control-acceptance.md`
- Modify: `console/README.md`
- Modify: `README.md`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: Add the acceptance matrix**

Create a table with rows for:

- legacy completed task remains completed after migration;
- legacy lost task becomes stale without spinner;
- queue/history connection failure does not mark stale;
- missing node preflight;
- missing model preflight;
- OOM shows `F-OOM`, node ID, and node type;
- cancel pending task;
- interrupt running task;
- cancel batch while preserving completed media;
- retry one failed segment only;
- blocked chain choose successful predecessor;
- blocked chain disable chaining;
- quick diagnostics cause no generation;
- LLM real test;
- Agnes/Boogu real image test;
- vision real test;
- ComfyUI SDXL real image test;
- T2V real video test;
- I2V real video test;
- R2V real video test;
- API keys absent from UI/log/error payloads.

Each row records expected result, actual result, timestamp, server fingerprint, and evidence file or prompt ID.

- [ ] **Step 2: Run the complete local verification suite**

```powershell
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/*.py workflows/*.py
Get-ChildItem workflows -Filter *.json | ForEach-Object { python -m json.tool $_.FullName > $null }
git diff --check
```

- [ ] **Step 3: Restart local daemons and verify migration is idempotent**

Start twice using `python console/start_daemons.py`. After each start, assert the normalized attempt count for a legacy task ID remains one. Confirm the old project and downloaded videos are still visible.

- [ ] **Step 4: Run browser acceptance**

Verify the task center and diagnostics center on desktop and 390px width. Capture evidence for failed/stale/blocked states, retry modal, cancellation confirmation, diagnostics confirmation, image preview, and video playback.

- [ ] **Step 5: Run real RTX 3090 tests one at a time**

Before each test, confirm the server fingerprint and empty queue. Run SDXL, T2V, I2V, and R2V individually. Record the prompt ID, parameters, elapsed time, output path, and playback result. Do not use a batch real-test operation.

- [ ] **Step 6: Exercise failure paths without wasting paid requests**

- Use a deliberately nonexistent local model name to test `F-MODEL-MISSING`; preflight must block before `/prompt`.
- Use a fake node name in an in-memory test graph to test `F-NODE-MISSING`; do not submit it.
- Use the known high-risk 3090 parameter combination only for warning display; do not intentionally trigger another OOM if one already exists in history.
- Disconnect the tunnel to verify `F-CONNECTION`, then reconnect without mutating task state.

- [ ] **Step 7: Update user documentation and changelog**

Document normal operation:

1. quick-check services;
2. run the needed real test;
3. submit/retry a single segment;
4. cancel a segment or batch;
5. interpret failed/stale/blocked states;
6. select Agnes, Boogu, or ComfyUI for assets;
7. stop/release AutoDL when the queue is empty.

- [ ] **Step 8: Run final verification and commit acceptance documentation**

```powershell
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/*.py workflows/*.py
git diff --check
git add docs/testing/generation-control-acceptance.md console/README.md README.md console/CHANGELOG.md
git commit -m "docs: add generation control acceptance guide"
```

---

## Final definition of done

- No queued, running, blocked, stale, failed, or cancelled state is inferred from a spinner alone.
- A retry creates exactly one child attempt and submits exactly one segment.
- A failed chain dependency never silently falls back to a different video or T2V.
- Server replacement and cleared remote history converge to `stale` after two successful missing polls.
- Connection failures never turn tasks stale.
- Every external service has an independent quick check and independent real test.
- No operation can start every paid/GPU real test at once.
- T2V, I2V, and R2V availability is tracked independently and requires a playable downloaded output.
- ComfyUI SDXL is available for role, scene, and storyboard images.
- Provider failures never trigger automatic cross-provider calls or automatic paid retries.
- Existing projects, task history, and downloaded media remain intact.
- All code/UI/workflow changes are represented in `console/CHANGELOG.md`.

