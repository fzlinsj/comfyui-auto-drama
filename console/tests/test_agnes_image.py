import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


CONSOLE_DIR = Path(__file__).resolve().parents[1]
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

import batch_console as bc


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class _Opener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if isinstance(request, str):
            return _Response(b"image-bytes")
        return _Response(json.dumps({"data": [{"url": "https://cdn.example/image.png"}]}).encode())


class AgnesImageTests(unittest.TestCase):
    def test_image_error_message_does_not_mislabel_agnes_as_boogu(self):
        message = bc._image_error_message(FileNotFoundError("missing"))
        self.assertEqual(message, "生图失败：missing")

    def test_image_directories_are_created_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "素材"
            with patch.object(bc, "IMAGE_DIRS", [str(target)]):
                bc._ensure_image_dirs()
            self.assertTrue(target.is_dir())

    def test_cloud_failure_does_not_mask_error_with_local_fallback(self):
        main = {"provider": "cloud", "provider_type": "agnes", "url": "https://apihub.agnes-ai.com/v1"}
        backup = {"provider": "local", "url": "http://127.0.0.1:8081"}
        with patch.object(bc, "_image_gen_endpoints", return_value=(main, backup)), \
             patch.dict(bc._IMG_ADAPTERS, {"agnes": unittest.mock.Mock(side_effect=RuntimeError("Agnes 返回缺少图片 URL"))}), \
             patch.object(bc, "_boogu_local", side_effect=AssertionError("不应回退本地 Boogu")):
            with self.assertRaisesRegex(RuntimeError, "Agnes 返回缺少图片 URL"):
                bc.boogu_generate("a test prompt", "test.png")

    def test_agnes_payload_uses_size_ratio_and_base64_response(self):
        payload = bc._agnes_payload("a test prompt", "768x1024", "agnes-image-2.5-flash")

        self.assertEqual(payload["model"], "agnes-image-2.5-flash")
        self.assertEqual(payload["prompt"], "a test prompt")
        self.assertEqual(payload["size"], "2K")
        self.assertEqual(payload["ratio"], "3:4")
        self.assertTrue(payload["return_base64"])
        self.assertNotIn("extra_body", payload)
        self.assertNotIn("response_format", payload)

    def test_agnes_url_response_is_downloaded(self):
        opener = _Opener()
        with tempfile.TemporaryDirectory() as tmp, patch.object(bc, "_opener", return_value=opener), patch.object(bc, "IMAGE_DIRS", [tmp]):
            filename, path = bc._img_agnes(
                {"url": "https://apihub.agnes-ai.com/v1", "api_key": "token", "model": "agnes-image-2.5-flash"},
                "a test prompt",
                "test.png",
                "768x1024",
                timeout=1,
            )

            self.assertEqual(filename, "test.png")
            self.assertEqual(Path(path).read_bytes(), b"image-bytes")
            request_payload = json.loads(opener.requests[0].data.decode())
            self.assertEqual(request_payload["ratio"], "3:4")
            self.assertTrue(request_payload["return_base64"])

    def test_comfyui_image_uses_selected_checkpoint_and_quality_settings(self):
        class FakeComfyClient:
            submitted_graph = None

            def __init__(self, server):
                self.server = server

            def preflight(self, graph):
                return {"ok": True}

            def submit(self, graph, client_id=None):
                type(self).submitted_graph = graph
                return {"prompt_id": "image-prompt"}

            def history(self, prompt_id):
                return {
                    prompt_id: {
                        "outputs": {
                            "7": {"images": [{"filename": "image.png", "subfolder": "", "type": "output"}]}
                        }
                    }
                }

            def download_output(self, output, destination):
                Path(destination).write_bytes(b"generated image")

        endpoint = {
            "url": "http://127.0.0.1:6006",
            "model": "cinematic-xl.safetensors",
            "steps": 30,
            "cfg": 6.0,
            "sampler": "euler_ancestral",
            "scheduler": "normal",
        }
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(bc, "ComfyUIClient", FakeComfyClient), \
             patch.object(bc, "IMAGE_DIRS", [tmp]):
            bc._img_comfyui(endpoint, "电影感产品主视觉，主体清晰", "test.png", "896x1152", timeout=1)

        graph = FakeComfyClient.submitted_graph
        checkpoint = next(node for node in graph.values() if node["class_type"] == "CheckpointLoaderSimple")
        latent = next(node for node in graph.values() if node["class_type"] == "EmptyLatentImage")
        sampler = next(node for node in graph.values() if node["class_type"] == "KSampler")
        prompts = [node["inputs"].get("text") for node in graph.values() if node["class_type"] == "CLIPTextEncode"]
        self.assertEqual(checkpoint["inputs"]["ckpt_name"], endpoint["model"])
        self.assertEqual((latent["inputs"]["width"], latent["inputs"]["height"]), (896, 1152))
        self.assertEqual(sampler["inputs"]["steps"], 30)
        self.assertEqual(sampler["inputs"]["cfg"], 6.0)
        self.assertEqual(sampler["inputs"]["sampler_name"], "euler_ancestral")
        self.assertEqual(sampler["inputs"]["scheduler"], "normal")
        self.assertIn("电影感产品主视觉，主体清晰", prompts)


if __name__ == "__main__":
    unittest.main()
