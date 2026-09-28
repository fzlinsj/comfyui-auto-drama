import sys
import unittest
from unittest import mock
from urllib.error import HTTPError
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from comfyui_client import ComfyUIClient, UrllibTransport


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

    def test_preflight_reports_missing_ipadapter_model(self):
        transport = FakeTransport({
            "/object_info": {
                "IPAdapterModelLoader": {
                    "input": {"required": {"ipadapter_file": [["installed.bin"]]}}
                }
            }
        })
        graph = {
            "1": {
                "class_type": "IPAdapterModelLoader",
                "inputs": {"ipadapter_file": "missing.bin"},
            }
        }
        result = ComfyUIClient("http://comfy", transport=transport).preflight(graph)
        self.assertEqual(result["missing_models"], ["missing.bin"])

    def test_preflight_reports_clip_vision_required_by_unified_loader(self):
        transport = FakeTransport({
            "/object_info": {
                "IPAdapterUnifiedLoader": {
                    "input": {"required": {"model": ["MODEL"], "preset": [["PLUS_FACE"]]}}
                },
                "CLIPVisionLoader": {
                    "input": {"required": {"clip_name": [["other-vision.safetensors"]]}}
                },
            }
        })
        graph = {"1": {"class_type": "IPAdapterUnifiedLoader", "inputs": {
            "model": ["0", 0], "preset": "PLUS_FACE"
        }}}
        result = ComfyUIClient("http://comfy", transport=transport).preflight(graph)
        self.assertIn("CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors", result["missing_models"])

    def test_preflight_reports_clip_vision_when_loader_metadata_is_missing(self):
        transport = FakeTransport({
            "/object_info": {
                "IPAdapterUnifiedLoader": {
                    "input": {"required": {"model": ["MODEL"], "preset": [["PLUS_FACE"]]}}
                },
            }
        })
        graph = {"1": {"class_type": "IPAdapterUnifiedLoader", "inputs": {
            "model": ["0", 0], "preset": "PLUS_FACE"
        }}}
        result = ComfyUIClient("http://comfy", transport=transport).preflight(graph)
        self.assertFalse(result["ok"])
        self.assertIn("CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors", result["missing_models"])

    def test_preflight_accepts_explicit_installed_clip_vision_for_unified_loader(self):
        transport = FakeTransport({
            "/object_info": {
                "IPAdapterUnifiedLoader": {
                    "input": {"required": {"model": ["MODEL"], "preset": [["PLUS_FACE"]]}}
                },
                "CLIPVisionLoader": {
                    "input": {"required": {"clip_name": [["installed-clip-vision.safetensors"]]}}
                },
                "IPAdapter": {
                    "input": {"required": {"model": ["MODEL"], "ipadapter": ["IPADAPTER"], "image": ["IMAGE"]},
                              "optional": {"clip_vision": ["CLIP_VISION"]}}
                },
            }
        })
        graph = {
            "1": {"class_type": "IPAdapterUnifiedLoader", "inputs": {"model": ["0", 0], "preset": "PLUS_FACE"}},
            "2": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "installed-clip-vision.safetensors"}},
            "3": {"class_type": "IPAdapter", "inputs": {"model": ["1", 0], "ipadapter": ["1", 1], "image": ["4", 0], "clip_vision": ["2", 0]}},
        }
        result = ComfyUIClient("http://comfy", transport=transport).preflight(graph)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["missing_models"], [])

    def test_http_error_includes_comfyui_response_body(self):
        error = HTTPError(
            "http://comfy/prompt", 400, "Bad Request", {},
            __import__("io").BytesIO(b'{"error":"invalid node input"}'),
        )

        class FailingOpener:
            def open(self, request, timeout=30):
                raise error

        with mock.patch("urllib.request.build_opener", return_value=FailingOpener()):
            with self.assertRaisesRegex(RuntimeError, r'ComfyUI HTTP 400 Bad Request:.*invalid node input'):
                UrllibTransport("http://comfy").post_json("/prompt", {"prompt": {}})

    def test_delete_pending_posts_exact_prompt_id(self):
        transport = FakeTransport({})
        ComfyUIClient("http://comfy", transport=transport).delete_pending("prompt-1")
        self.assertEqual(transport.posts, [("/queue", {"delete": ["prompt-1"]})])

    def test_checkpoint_models_extracts_nested_checkpoint_choices(self):
        transport = FakeTransport({
            "/object_info": {
                "CheckpointLoaderSimple": {
                    "input": {
                        "required": {
                            "ckpt_name": [[
                                "zeta.safetensors",
                                "alpha.safetensors",
                                "alpha.safetensors",
                            ], {"tooltip": "checkpoint"}]
                        }
                    }
                }
            }
        })
        models = ComfyUIClient("http://comfy", transport=transport).checkpoint_models()
        self.assertEqual(models, ["alpha.safetensors", "zeta.safetensors"])

    def test_checkpoint_models_returns_empty_when_checkpoint_node_is_missing(self):
        transport = FakeTransport({"/object_info": {"CLIPTextEncode": {}}})
        models = ComfyUIClient("http://comfy", transport=transport).checkpoint_models()
        self.assertEqual(models, [])

    def test_checkpoint_models_accepts_flat_choice_list(self):
        transport = FakeTransport({
            "/object_info": {
                "CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": ["flat-a.safetensors", "flat-b.safetensors"]}}
                }
            }
        })
        models = ComfyUIClient("http://comfy", transport=transport).checkpoint_models()
        self.assertEqual(models, ["flat-a.safetensors", "flat-b.safetensors"])


if __name__ == "__main__":
    unittest.main()
