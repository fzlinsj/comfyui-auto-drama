import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
CONSOLE_DIR = ROOT / "console"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

from workflows.build_sdxl_graph import build_sdxl_identity_graph
import batch_console as bc


class IdentityReferenceTests(unittest.TestCase):
    def _ipadapter_info(self):
        return {
            "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["portrait.safetensors"]]}}},
            "CLIPTextEncode": {"input": {"required": {"text": ["STRING"], "clip": ["CLIP"]}}},
            "EmptyLatentImage": {"input": {"required": {"width": ["INT"], "height": ["INT"], "batch_size": ["INT"]}}},
            "KSampler": {"input": {"required": {"model": ["MODEL"], "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "latent_image": ["LATENT"]}}},
            "VAEDecode": {"input": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}}},
            "SaveImage": {"input": {"required": {"images": ["IMAGE"]}}},
            "LoadImage": {"input": {"required": {"image": [["*", "anchor.png"]]} }},
            "IPAdapterUnifiedLoader": {"input": {"required": {"model": ["MODEL"], "preset": [["PLUS_FACE"]]}}},
            "IPAdapter": {"input": {"required": {"model": ["MODEL"], "ipadapter": ["IPADAPTER"], "image": ["IMAGE"], "weight": ["FLOAT"]}}},
        }

    def test_identity_graph_routes_checkpoint_through_ipadapter(self):
        graph = build_sdxl_identity_graph(
            {
                "prompt": "same actor, side view",
                "checkpoint": "portrait.safetensors",
                "reference_image": "anchor.png",
                "ipadapter_preset": "PLUS_FACE",
            },
            self._ipadapter_info(),
        )
        self.assertEqual(graph["8"]["class_type"], "LoadImage")
        self.assertEqual(graph["8"]["inputs"]["image"], "anchor.png")
        self.assertEqual(graph["9"]["class_type"], "IPAdapterUnifiedLoader")
        self.assertEqual(graph["10"]["class_type"], "IPAdapter")
        sampler = next(node for node in graph.values() if node["class_type"] == "KSampler")
        self.assertEqual(sampler["inputs"]["model"], ["10", 0])

    def test_missing_ipadapter_error_lists_available_identity_nodes(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "未找到 IPAdapter Plus 身份节点.*已检测到.*LoadImage",
        ):
            build_sdxl_identity_graph(
                {"reference_image": "anchor.png"},
                {
                    "CheckpointLoaderSimple": {},
                    "LoadImage": {"input": {"required": {"image": [["anchor.png"]]}}},
                },
            )

    def test_comfyui_generation_uploads_and_uses_reference_image(self):
        class FakeClient:
            submitted_graph = None
            uploaded = []

            def __init__(self, server):
                self.server = server

            def object_info(self):
                return self_info

            def upload_image(self, local_path, filename=None):
                type(self).uploaded.append((local_path, filename))
                return {"name": "anchor.png"}

            def preflight(self, graph):
                type(self).submitted_graph = graph
                return {"ok": True}

            def submit(self, graph, client_id=None):
                return {"prompt_id": "image-prompt"}

            def history(self, prompt_id):
                return {prompt_id: {"outputs": {"7": {"images": [{"filename": "out.png"}]}}}}

            def download_output(self, output, destination):
                Path(destination).write_bytes(b"generated image")

        self_info = self._ipadapter_info()
        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "front.png"
            reference.write_bytes(b"reference")
            with patch.object(bc, "ComfyUIClient", FakeClient), patch.object(bc, "IMAGE_DIRS", [tmp]):
                bc._img_comfyui(
                    {
                        "url": "http://127.0.0.1:6006",
                        "model": "portrait.safetensors",
                        "ipadapter_preset": "PLUS_FACE",
                    },
                    "same actor, back view",
                    "back.png",
                    "768x1024",
                    timeout=1,
                    reference_images=[str(reference)],
                )
        self.assertEqual(FakeClient.uploaded[0][1], "front.png")
        graph = FakeClient.submitted_graph
        self.assertIn("IPAdapter", [node["class_type"] for node in graph.values()])


class IdentityFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (CONSOLE_DIR / "index.html").read_text(encoding="utf-8")

    def test_role_generation_sends_reference_image(self):
        self.assertIn("reference_image", self.source)
        self.assertIn("reference_images", self.source)

    def test_batch_generation_does_not_skip_existing_assets(self):
        body = self.source.split("async function genAllAssets()", 1)[1]
        body = body.split("async function genRoleViewAsset", 1)[0]
        self.assertNotIn("if (has) return;", body)


if __name__ == "__main__":
    unittest.main()
