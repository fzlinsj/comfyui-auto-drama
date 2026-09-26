import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CONSOLE_DIR.parent
sys.path.insert(0, str(CONSOLE_DIR))

from environment_recipes import extract_workflow_model_refs, load_recipe, validate_recipe


class EnvironmentRecipeTests(unittest.TestCase):
    def test_recipe_contains_all_four_verification_modes(self):
        recipe = load_recipe("minimax-h3-sdxl")
        self.assertEqual(recipe["version"], "1.0.0")
        self.assertEqual(
            {item["service"] for item in recipe["checks"]},
            {"sdxl", "t2v", "i2v", "r2v"},
        )
        self.assertEqual(recipe["platforms"], ["autodl", "chenyu"])
        self.assertGreaterEqual(recipe["requirements"]["min_vram_bytes"], 24 * 1024**3)

    def test_recipe_uses_official_minimax_h3_text_encoder_url(self):
        recipe = load_recipe("minimax-h3-sdxl")
        text_encoder = next(
            item for item in recipe["models"]
            if item["filename"] == "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
        )
        self.assertEqual(
            text_encoder["primary_url"],
            "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/"
            "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        )

    def test_recipe_resources_have_checksum_and_safe_paths(self):
        recipe = load_recipe("minimax-h3-sdxl")
        for resource in recipe["models"] + recipe["nodes"]:
            for key in ("filename", "target_dir", "size_bytes", "sha256", "primary_url", "fallback_urls", "shareable"):
                self.assertIn(key, resource)
            self.assertFalse(Path(resource["filename"]).is_absolute())
            self.assertEqual(len(resource["sha256"]), 64)

    def test_extracts_models_from_api_and_editor_workflows(self):
        api_refs = extract_workflow_model_refs(PROJECT_ROOT / "workflows" / "sdxl_image_api_template.json")
        self.assertIn(("models/checkpoints", "sd_xl_base_1.0.safetensors"), api_refs)

        editor_refs = extract_workflow_model_refs(PROJECT_ROOT / "workflows" / "minimax_h3_t2v_turbo.json")
        self.assertIn(("models/vae", "minimax_h3_video_vae_fp16.safetensors"), editor_refs)
        self.assertIn(("models/vae", "minimax_h3_audio_vae_fp32.safetensors"), editor_refs)
        self.assertIn(("models/diffusion_models", "minimax_h3_fl2va_int8_convrot.safetensors"), editor_refs)
        i2v_refs = extract_workflow_model_refs(PROJECT_ROOT / "workflows" / "video_minimax_h3_i2v_uncensored_enhancer.json")
        self.assertIn(("models/text_encoders", "qwen3vl_32b_h3_generation_tail_50_63_int8_convrot.safetensors"), i2v_refs)

    def test_recipe_covers_all_workflow_model_references(self):
        recipe = load_recipe("minimax-h3-sdxl")
        declared = {(item["target_dir"], item["filename"]) for item in recipe["models"]}
        for workflow in recipe["workflows"]:
            refs = extract_workflow_model_refs(PROJECT_ROOT / workflow)
            self.assertTrue(refs <= declared, f"未纳入配方的工作流模型: {sorted(refs - declared)}")

    def test_unknown_resource_mode_and_missing_field_are_rejected(self):
        recipe = {"id": "x", "version": "1", "models": [], "nodes": [], "checks": [{"service": "x", "resource_mode": "bad"}]}
        with self.assertRaises(ValueError):
            validate_recipe(recipe)

    def test_manual_resource_can_omit_download_source(self):
        recipe = {
            "id": "manual",
            "version": "1",
            "platforms": ["autodl"],
            "requirements": {"min_comfyui": "0.31.0", "min_python": ">=3.10", "min_vram_bytes": 1, "min_disk_bytes": 1},
            "workflows": ["workflows/sdxl_image_api_template.json"],
            "models": [{
                "filename": "private.safetensors",
                "target_dir": "models/text_encoders",
                "size_bytes": 0,
                "sha256": "0" * 64,
                "primary_url": "",
                "fallback_urls": [],
                "shareable": False,
                "managed": False,
            }],
            "nodes": [],
            "checks": [{"service": "sdxl", "resource_mode": "gpu_required"}],
        }
        self.assertIs(validate_recipe(recipe), recipe)


if __name__ == "__main__":
    unittest.main()
