import sys
import unittest
from pathlib import Path
from unittest.mock import patch


CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

import batch_console


class BatchConsoleFactoryTests(unittest.TestCase):
    def test_service_diagnostics_uses_resolved_output_directory(self):
        previous = batch_console._SERVICE_DIAGNOSTICS
        batch_console._SERVICE_DIAGNOSTICS = None
        try:
            with patch.object(batch_console, "get_task_store", return_value=object()):
                diagnostics = batch_console.get_service_diagnostics()
            self.assertEqual(diagnostics.output_dir, batch_console.OUTPUTS_DIR)
            self.assertTrue(Path(diagnostics.output_dir).is_absolute())
        finally:
            batch_console._SERVICE_DIAGNOSTICS = previous


class ImageGenerationPolicyTests(unittest.TestCase):
    def test_comfyui_endpoint_does_not_silently_fill_checkpoint(self):
        with patch.object(batch_console, "_CONFIG", {
            "comfyui": {"server": "http://127.0.0.1:6006"},
            "image_gen": {"provider": "comfyui", "comfyui": {"checkpoint": ""}},
        }):
            endpoint, backup = batch_console._image_gen_endpoints()
        self.assertIsNone(backup)
        self.assertEqual(endpoint["model"], "")

    def test_comfyui_negative_prompt_contains_realistic_exclusions(self):
        result = batch_console._merge_negative_prompt("text, watermark")
        self.assertIn("text", result)
        self.assertIn("古画", result)
        self.assertIn("3D", result)

    def test_missing_checkpoint_has_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "image_gen.comfyui.checkpoint"):
            batch_console._validate_comfyui_checkpoint({"model": ""})

    def test_animal_asset_verification_does_not_apply_human_gender_rules(self):
        with patch.object(batch_console, "vision_ask", return_value='{"ok": true, "issues": []}') as ask:
            result = batch_console.verify_asset(
                "unused.png",
                "role",
                {"role_type": "animal", "look": "公鸡"},
            )
        self.assertTrue(result["ok"])
        prompt = ask.call_args.args[1]
        self.assertIn("真实动物物种", prompt)
        self.assertIn("不得出现人脸", prompt)
        self.assertNotIn("人物性别必须是", prompt)


if __name__ == "__main__":
    unittest.main()
