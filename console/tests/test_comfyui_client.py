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
