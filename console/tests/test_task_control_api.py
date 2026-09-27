import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_real_diagnostic_route_forwards_custom_parameters(self):
        source = Path(batch_console.__file__).read_text(encoding="utf-8")
        real_route = source.split('if path == "/api/diagnostics/real":', 1)[1].split('if path == "/api/llm/chat":', 1)[0]
        self.assertIn('parameters=body.get("parameters")', real_route)

    def test_output_media_route_serves_generated_images_as_images(self):
        source = Path(batch_console.__file__).read_text(encoding="utf-8")
        outputs_route = source.split("# 生成视频：递归查 outputs 目录", 1)[1].split('self._send(404, json.dumps({"error": "not found"}', 1)[0]
        self.assertIn('"image/png"', outputs_route)
        self.assertIn('"image/jpeg"', outputs_route)
        self.assertIn('"image/webp"', outputs_route)

    def test_media_resolver_falls_back_to_legacy_console_output_directory(self):
        resolver = getattr(batch_console, "find_media_path", None)
        self.assertTrue(callable(resolver), "media resolver is missing")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current = root / "current"
            legacy = root / "legacy"
            current.mkdir()
            legacy.mkdir()
            expected = legacy / "diagnostic-old.png"
            expected.write_bytes(b"png")
            with patch.object(batch_console, "IMAGE_DIRS", []), patch.object(
                batch_console, "OUTPUTS_DIR", str(current)
            ), patch.object(batch_console, "LEGACY_OUTPUTS_DIR", str(legacy)):
                self.assertEqual(Path(resolver(expected.name)), expected)

    def test_media_route_uses_shared_media_resolver(self):
        source = Path(batch_console.__file__).read_text(encoding="utf-8")
        media_route = source.split('if path.path.startswith("/media/"):', 1)[1].split(
            'if path.path == "/api/records":', 1
        )[0]
        self.assertIn("find_media_path(fn)", media_route)


if __name__ == "__main__":
    unittest.main()
