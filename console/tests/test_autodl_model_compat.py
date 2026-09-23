import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = PROJECT_ROOT / "workflows"
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

import build_api_graphs as bg


AUTODL_TURBO_LORA = "minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors"
AUTODL_I2V_CLIP = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"


def sample_task():
    return {
        "prompt": "test prompt",
        "image": "first.png",
        "images": ["first.png"],
        "duration": 2,
        "seed": 1,
        "prefix": "test/output",
        "mp": 0.4,
        "steps": 4,
    }


def node_inputs(graph, class_type):
    return [node["inputs"] for node in graph.values() if node["class_type"] == class_type]


class AutoDLModelCompatibilityTests(unittest.TestCase):
    def test_t2v_uses_installed_turbo_lora(self):
        graph = bg.convert_t2v(sample_task())

        loras = node_inputs(graph, "MiniMaxH3TurboLoRA")
        self.assertTrue(loras)
        self.assertTrue(all(node["lora_name"] == AUTODL_TURBO_LORA for node in loras))

    def test_i2v_uses_installed_heretic_clip(self):
        graph = bg.build_i2v(sample_task())

        clips = node_inputs(graph, "CLIPLoader")
        loras = node_inputs(graph, "MiniMaxH3TurboLoRA")
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["clip_name"], AUTODL_I2V_CLIP)
        self.assertTrue(loras)
        self.assertTrue(all(node["lora_name"] == AUTODL_TURBO_LORA for node in loras))

    def test_r2v_uses_installed_lora_and_keeps_official_models(self):
        graph = bg.build_r2v(sample_task())

        loras = node_inputs(graph, "MiniMaxH3TurboLoRA")
        clips = node_inputs(graph, "CLIPLoader")
        unets = node_inputs(graph, "UNETLoader")
        self.assertEqual(len(loras), 1)
        self.assertEqual(loras[0]["lora_name"], AUTODL_TURBO_LORA)
        self.assertEqual(clips[0]["clip_name"], bg.R2V_CLIP_DEFAULT)
        self.assertEqual(unets[0]["unet_name"], bg.R2V_UNET_DEFAULT)


if __name__ == "__main__":
    unittest.main()
