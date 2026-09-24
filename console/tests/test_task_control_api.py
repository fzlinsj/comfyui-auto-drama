import sys
import unittest
from pathlib import Path


CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

import batch_console


class FakeService:
    def list_control_tasks(self, project_name="", status_filter=""):
        return [{"segment_key": "segment_01", "latest": {"status": "failed"}, "history": []}]


class OfflineClient:
    def profile(self):
        raise ConnectionError("server offline")


class TaskControlApiTests(unittest.TestCase):
    def test_offline_server_does_not_hide_local_task_attempts(self):
        build_payload = getattr(batch_console, "build_task_control_payload", None)
        self.assertTrue(callable(build_payload), "task control payload helper is missing")
        payload = build_payload(FakeService(), OfflineClient(), "project", "failed")
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertFalse(payload["server"]["online"])
        self.assertIn("offline", payload["server"]["error"])

    def test_unmatched_routes_return_json_errors(self):
        source = Path(batch_console.__file__).read_text(encoding="utf-8")
        self.assertNotIn('self._send(404, "not found", "text/plain; charset=utf-8")', source)
        self.assertGreaterEqual(source.count('self._send(404, json.dumps({"error": "not found"}'), 2)

    def test_llm_chat_route_requires_confirmation_and_message(self):
        source = Path(batch_console.__file__).read_text(encoding="utf-8")
        self.assertIn('if path == "/api/llm/chat":', source)
        self.assertIn("confirm_cost", source)
        self.assertIn("message", source)


if __name__ == "__main__":
    unittest.main()
