import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workflows"))

from build_sdxl_graph import build_sdxl_graph


def nodes(graph, class_type):
    return [node["inputs"] for node in graph.values() if node["class_type"] == class_type]


class SdxlGraphTests(unittest.TestCase):
    def test_standard_graph_overrides_request_parameters(self):
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
        self.assertEqual(nodes(graph, "SaveImage")[0]["filename_prefix"], "assets/test")


if __name__ == "__main__":
    unittest.main()
