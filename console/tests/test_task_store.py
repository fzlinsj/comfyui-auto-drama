import json
import sys
import tempfile
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from task_store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(str(Path(self.temp_dir.name) / "tasks.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_migrate_legacy_tasks_is_idempotent(self):
        legacy = [{
            "id": "task-1", "name": "episode_01", "prompt_id": "prompt-1",
            "mode": "t2v", "duration": 5, "mp": 0.4,
            "downloaded": True,
            "output_file": {"filename": "episode.mp4", "subfolder": "video", "type": "output"},
        }]
        self.store.migrate_legacy_tasks(legacy, "http://comfy")
        self.store.migrate_legacy_tasks(legacy, "http://comfy")
        self.assertEqual(len(self.store.list_attempts()), 1)
        self.assertEqual(self.store.list_attempts()[0]["status"], "succeeded")

    def test_illegal_transition_is_rejected(self):
        attempt_id = self.store.create_attempt(segment_key="episode_01", status="queued", parameters={})
        with self.assertRaisesRegex(ValueError, "queued.*ready"):
            self.store.transition(attempt_id, "ready")

    def test_diagnostic_run_round_trip(self):
        run_id = self.store.create_diagnostic_run("comfyui_t2v", "real", {"mp": 0.2})
        self.store.finish_diagnostic_run(run_id, "succeeded", {"filename": "test.mp4"})
        self.assertEqual(self.store.get_diagnostic_run(run_id)["result"]["filename"], "test.mp4")

    def test_legacy_payload_is_preserved(self):
        task = {"id": "lost", "name": "episode_02", "error": "F-LOST: old server"}
        self.store.migrate_legacy_tasks([task], "http://old")
        attempt = self.store.list_attempts()[0]
        self.assertEqual(attempt["status"], "stale")
        self.assertEqual(attempt["parameters"]["legacy"], task)
        self.assertEqual(attempt["failure"]["code"], "F-LOST")


if __name__ == "__main__":
    unittest.main()
