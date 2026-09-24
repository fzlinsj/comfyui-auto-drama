import sys
import tempfile
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from task_service import TaskService
from task_store import TaskStore


class FakeComfyClient:
    def __init__(self):
        self.preflight_result = {"ok": True, "missing_nodes": [], "missing_models": [], "warnings": []}
        self.queue_result = {"queue_running": [], "queue_pending": []}
        self.history_result = {}
        self.queue_error = None
        self.submitted_graphs = []
        self.deleted_prompt_ids = []
        self.interrupt_calls = 0

    def preflight(self, graph):
        return self.preflight_result

    def profile(self):
        return {"gpu_name": "NVIDIA GeForce RTX 3090", "vram_free": 12_000, "vram_total": 24_000}

    def submit(self, graph, client_id="batch_console"):
        self.submitted_graphs.append(graph)
        return {"prompt_id": "submitted-prompt"}

    def queue(self):
        if self.queue_error:
            raise self.queue_error
        return self.queue_result

    def history(self, prompt_id=None):
        if self.queue_error:
            raise self.queue_error
        return self.history_result

    def delete_pending(self, prompt_id):
        self.deleted_prompt_ids.append(prompt_id)
        return {"ok": True}

    def interrupt(self):
        self.interrupt_calls += 1
        return {"ok": True}


class TaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(str(Path(self.temp_dir.name) / "tasks.db"))
        self.client = FakeComfyClient()
        self.service = TaskService(self.store, lambda _server: self.client)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create(self, status="preflight_pending", **kwargs):
        return self.store.create_attempt(
            segment_key=kwargs.pop("segment_key", "episode_01"),
            status=status,
            server_url="http://comfy",
            parameters=kwargs.pop("parameters", {"graph": {"1": {"class_type": "KSampler", "inputs": {}}}}),
            prompt_id=kwargs.pop("prompt_id", None),
            batch_id=kwargs.pop("batch_id", "batch-1"),
            **kwargs,
        )

    def test_missing_model_blocks_submission(self):
        attempt_id = self._create()
        self.client.preflight_result = {"ok": False, "missing_nodes": [], "missing_models": ["model.safetensors"], "warnings": []}
        result = self.service.preflight_attempt(attempt_id)
        self.assertEqual(result["status"], "preflight_failed")
        self.assertEqual(result["failure"]["code"], "F-MODEL-MISSING")
        self.assertEqual(self.client.submitted_graphs, [])

    def test_two_successful_missing_polls_mark_attempt_stale(self):
        attempt_id = self._create("queued", prompt_id="queued-prompt")
        self.service.refresh_attempt(attempt_id)
        first = self.store.get_attempt(attempt_id)
        self.assertEqual(first["status"], "queued")
        self.assertEqual(first["missing_poll_count"], 1)
        self.service.refresh_attempt(attempt_id)
        self.assertEqual(self.store.get_attempt(attempt_id)["status"], "stale")

    def test_connection_failure_never_increments_missing_poll_count(self):
        attempt_id = self._create("queued", prompt_id="queued-prompt")
        self.client.queue_error = ConnectionError("offline")
        self.service.refresh_attempt(attempt_id)
        self.assertEqual(self.store.get_attempt(attempt_id)["missing_poll_count"], 0)

    def test_retry_creates_child_attempt_and_does_not_mutate_failed_parent(self):
        parent_id = self._create("failed", parameters={"mp": 1.0, "steps": 8, "graph": {}})
        child = self.service.retry_attempt(parent_id, {"mp": 0.4, "steps": 4})
        self.assertEqual(child["parent_attempt_id"], parent_id)
        self.assertEqual(child["parameters"]["mp"], 0.4)
        self.assertEqual(self.store.get_attempt(parent_id)["status"], "failed")

    def test_cancel_pending_deletes_only_requested_prompt(self):
        attempt_id = self._create("queued", prompt_id="queued-prompt")
        self.service.cancel_attempt(attempt_id)
        self.assertEqual(self.client.deleted_prompt_ids, ["queued-prompt"])
        self.assertEqual(self.store.get_attempt(attempt_id)["status"], "cancelled")

    def test_running_task_requires_confirmation_then_interrupts(self):
        attempt_id = self._create("running", prompt_id="running-prompt")
        result = self.service.cancel_attempt(attempt_id)
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(self.client.interrupt_calls, 0)
        self.service.cancel_attempt(attempt_id, confirm_interrupt=True)
        self.assertEqual(self.client.interrupt_calls, 1)
        self.assertEqual(self.store.get_attempt(attempt_id)["status"], "cancel_requested")


if __name__ == "__main__":
    unittest.main()
