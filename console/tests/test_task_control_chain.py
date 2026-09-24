import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


CONSOLE_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = CONSOLE_DIR.parent / "workflows"
sys.path.insert(0, str(CONSOLE_DIR))
sys.path.insert(0, str(WORKFLOW_DIR))

import batch_console as bc
from task_service import TaskService
from task_store import TaskStore


class FakeClient:
    def __init__(self):
        self.preflight_graphs = []
        self.uploads = []

    def preflight(self, graph):
        self.preflight_graphs.append(graph)
        return {"ok": True, "missing_nodes": [], "missing_models": [], "warnings": []}

    def profile(self):
        return {"gpu_name": "RTX 3090"}

    def upload_image(self, local_path, filename=None):
        self.uploads.append((local_path, filename))
        return {"name": filename or Path(local_path).name}


class TaskControlChainTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = TaskStore(str(self.root / "tasks.db"))
        self.client = FakeClient()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_retry_preflight_rebuilds_and_uploads_missing_chain_frame(self):
        output_dir = self.root / "outputs" / "output" / "video"
        output_dir.mkdir(parents=True)
        predecessor_video = output_dir / "previous.mp4"
        predecessor_video.write_bytes(b"video")
        extracted_frame = self.root / "last.png"
        extracted_frame.write_bytes(b"png")
        asset_dir = self.root / "assets"

        predecessor_id = self.store.create_attempt(
            segment_key="segment_03",
            status="succeeded",
            legacy_task_id="legacy-segment-03",
            parameters={"legacy": {"id": "legacy-segment-03", "name": "segment_03"}},
            output={"filename": predecessor_video.name, "subfolder": "video", "type": "output"},
            server_url="http://comfy.test",
        )
        attempt_id = self.store.create_attempt(
            segment_key="segment_04",
            status="preflight_pending",
            server_url="http://comfy.test",
            parameters={
                "legacy": {
                    "id": "legacy-segment-04",
                    "name": "segment_04_v2",
                    "mode": "i2v",
                    "prompt": "continue the shot",
                    "duration": 10,
                    "mp": 0.4,
                    "steps": 4,
                    "prefix": "video/segment_04",
                    "image": "old_missing_frame.png",
                },
                "chain_mode": True,
                "chain_prev": predecessor_id,
            },
        )
        service = TaskService(
            self.store,
            lambda _server: self.client,
            prepare_attempt=lambda attempt, client: bc.prepare_task_control_attempt(
                attempt, client, store=self.store
            ),
        )

        with patch.object(bc, "OUTPUTS_DIR", str(self.root / "outputs")), \
             patch.object(bc, "IMAGE_DIRS", [str(asset_dir)]), \
             patch.object(bc, "load_state", return_value={"tasks": []}), \
             patch.object(bc, "extract_last_frame", return_value=str(extracted_frame)):
            result = service.preflight_attempt(attempt_id)

        self.assertEqual(result["status"], "ready")
        attempt = self.store.get_attempt(attempt_id)
        graph = attempt["parameters"]["graph"]
        image_nodes = [node for node in graph.values() if node.get("class_type") == "LoadImage"]
        self.assertTrue(image_nodes)
        self.assertEqual(image_nodes[0]["inputs"]["image"], f"chain_{predecessor_id}.png")
        self.assertEqual(self.client.uploads[0][1], f"chain_{predecessor_id}.png")
        self.assertTrue((asset_dir / f"chain_{predecessor_id}.png").is_file())

    def test_missing_chain_predecessor_fails_preflight_with_actionable_code(self):
        attempt_id = self.store.create_attempt(
            segment_key="segment_04",
            status="preflight_pending",
            server_url="http://comfy.test",
            parameters={"chain_mode": True, "chain_prev": "missing-attempt", "graph": {"1": {"class_type": "KSampler", "inputs": {}}}},
        )
        service = TaskService(
            self.store,
            lambda _server: self.client,
            prepare_attempt=lambda attempt, client: bc.prepare_task_control_attempt(
                attempt, client, store=self.store
            ),
        )

        result = service.preflight_attempt(attempt_id)

        self.assertEqual(result["status"], "preflight_failed")
        self.assertEqual(result["failure"]["code"], "F-CHAIN-PREDECESSOR-MISSING")
        self.assertEqual(self.client.preflight_graphs, [])

    def test_legacy_submit_stops_when_chain_frame_cannot_be_restored(self):
        task = {
            "id": "retry",
            "name": "segment_04_v2",
            "mode": "i2v",
            "image": "chain_missing.png",
            "chain_prev": "missing-predecessor",
            "prompt": "continue",
        }
        with patch.object(bc, "load_state", return_value={"tasks": []}), \
             patch.object(bc, "build_graphs", return_value=([(task, {"1": {}})], None)), \
             patch.object(bc, "ensure_chain_image", return_value=None), \
             patch.object(bc, "api_get", return_value={"queue_running": [], "queue_pending": []}), \
             patch.object(bc, "api_post") as submit:
            results, error, _warnings = bc.submit_tasks("http://comfy.test", [task], auto_download=False)

        self.assertIsNone(results)
        self.assertIn("链式", error)
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
