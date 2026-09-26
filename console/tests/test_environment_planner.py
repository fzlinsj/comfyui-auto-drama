import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_models import EnvironmentError
from environment_planner import build_plan, estimate_required_space


class EnvironmentPlannerTests(unittest.TestCase):
    def test_disk_estimate_includes_fifteen_percent_reserve(self):
        estimate = estimate_required_space([{"size_bytes": 1000}], temp_bytes=200, extract_bytes=300)
        self.assertEqual(estimate.required_bytes, 1725)

    def test_insufficient_disk_blocks_plan_before_download(self):
        scan = {"disk": {"free_bytes": 100}, "comfyui": {}, "python": {}}
        recipe = {
            "id": "small", "version": "1", "requirements": {"min_comfyui": "0.31.0", "min_python": ">=3.10"},
            "models": [{"filename": "a", "size_bytes": 1000, "target_dir": "models", "shareable": True}],
            "nodes": [], "checks": [], "workflows": [],
        }
        plan = build_plan(scan=scan, recipe=recipe)
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.error.code, "E-DISK")
        self.assertFalse(plan.download_tasks)

    def test_compatible_comfyui_reuses_existing_environment(self):
        scan = {
            "disk": {"free_bytes": 100000},
            "comfyui": {"present": True, "version": "0.31.2"},
            "python": {"version": "3.10.14"},
        }
        recipe = {"id": "small", "version": "1", "requirements": {"min_comfyui": "0.31.0", "min_python": ">=3.10", "min_disk_bytes": 1}, "models": [], "nodes": [], "checks": [], "workflows": []}
        plan = build_plan(scan=scan, recipe=recipe)
        self.assertEqual(plan.mode, "reuse")
        self.assertEqual(plan.status, "plan_ready")

    def test_existing_model_and_node_are_not_counted_as_downloads(self):
        scan = {
            "disk": {"free_bytes": 1000},
            "comfyui": {
                "present": True,
                "version": "0.31.2",
                "models": [{"target_dir": "models/checkpoints", "filename": "a.safetensors", "size_bytes": 1000}],
                "nodes": [{"filename": "NodeA", "size_bytes": 0}],
            },
            "python": {"version": "3.10.14"},
        }
        recipe = {
            "id": "small", "version": "1",
            "requirements": {"min_comfyui": "0.31.0", "min_python": ">=3.10", "min_disk_bytes": 1},
            "models": [{"filename": "a.safetensors", "target_dir": "models/checkpoints", "size_bytes": 1000}],
            "nodes": [{"filename": "NodeA", "target_dir": "custom_nodes", "size_bytes": 0}],
            "checks": [], "workflows": [],
        }
        plan = build_plan(scan=scan, recipe=recipe)
        self.assertEqual(plan.status, "plan_ready")
        self.assertEqual(plan.estimate.content_bytes, 0)
        self.assertEqual(plan.estimate.required_bytes, 0)
        self.assertEqual(plan.download_tasks, [])
        self.assertEqual(len(plan.reused_resources), 2)

    def test_existing_model_with_wrong_size_is_reused_and_reported(self):
        scan = {
            "disk": {"free_bytes": 2000},
            "comfyui": {"present": True, "version": "0.31.2", "models": [{"target_dir": "models/checkpoints", "filename": "a.safetensors", "size_bytes": 9}]},
            "python": {"version": "3.10.14"},
        }
        recipe = {
            "id": "small", "version": "1",
            "requirements": {"min_comfyui": "0.31.0", "min_python": ">=3.10", "min_disk_bytes": 1},
            "models": [{"filename": "a.safetensors", "target_dir": "models/checkpoints", "size_bytes": 1000}],
            "nodes": [], "checks": [], "workflows": [],
        }
        plan = build_plan(scan=scan, recipe=recipe)
        self.assertEqual(plan.status, "plan_ready")
        self.assertEqual(plan.download_tasks, [])
        self.assertEqual([item["filename"] for item in plan.reused_resources], ["a.safetensors"])
        self.assertTrue(any("大小" in risk for risk in plan.risks))

    def test_missing_manual_resource_is_warning_without_blocking_plan(self):
        scan = {
            "disk": {"free_bytes": 100000},
            "comfyui": {"present": True, "version": "0.31.2", "models": []},
            "python": {"version": "3.10.14"},
        }
        recipe = {
            "id": "manual", "version": "1",
            "requirements": {"min_comfyui": "0.31.0", "min_python": ">=3.10", "min_disk_bytes": 1},
            "models": [{
                "filename": "private.safetensors", "target_dir": "models/text_encoders",
                "size_bytes": 0, "sha256": "0" * 64, "primary_url": "", "fallback_urls": [],
                "shareable": False, "managed": False,
            }],
            "nodes": [], "checks": [], "workflows": [],
        }
        plan = build_plan(scan=scan, recipe=recipe)
        self.assertEqual(plan.status, "plan_ready")
        self.assertIsNone(plan.error)
        self.assertEqual(plan.download_tasks, [])
        self.assertTrue(any("增强资源" in risk for risk in plan.risks))

    def test_installed_manual_resource_is_reused_without_size(self):
        scan = {
            "disk": {"free_bytes": 100000},
            "comfyui": {
                "present": True, "version": "0.31.2",
                "models": [{"target_dir": "models/text_encoders", "filename": "private.safetensors", "size_bytes": 123}],
            },
            "python": {"version": "3.10.14"},
        }
        recipe = {
            "id": "manual", "version": "1",
            "requirements": {"min_comfyui": "0.31.0", "min_python": ">=3.10", "min_disk_bytes": 1},
            "models": [{
                "filename": "private.safetensors", "target_dir": "models/text_encoders",
                "size_bytes": 0, "sha256": "0" * 64, "primary_url": "", "fallback_urls": [],
                "shareable": False, "managed": False,
            }],
            "nodes": [], "checks": [], "workflows": [],
        }
        plan = build_plan(scan=scan, recipe=recipe)
        self.assertEqual(plan.status, "plan_ready")
        self.assertEqual(plan.download_tasks, [])
        self.assertEqual([item["filename"] for item in plan.reused_resources], ["private.safetensors"])

    def test_installed_compatible_model_variant_is_reused(self):
        scan = {
            "disk": {"free_bytes": 100},
            "comfyui": {
                "present": True, "version": "0.31.2",
                "models": [{
                    "target_dir": "models/diffusion_models",
                    "filename": "minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
                    "size_bytes": 123,
                    "path": "/root/autodl-tmp/models/diffusion_models/minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
                }],
            },
            "python": {"version": "3.10.14"},
        }
        recipe = {
            "id": "variant", "version": "1",
            "requirements": {"min_comfyui": "0.31.0", "min_python": ">=3.10", "min_disk_bytes": 1},
            "models": [{
                "filename": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                "target_dir": "models/diffusion_models", "size_bytes": 999,
                "sha256": "a" * 64, "primary_url": "https://example.com/model",
                "fallback_urls": [], "shareable": True, "managed": True,
            }],
            "nodes": [], "checks": [], "workflows": [],
        }
        plan = build_plan(scan, recipe)
        self.assertEqual(plan.status, "plan_ready")
        self.assertEqual(plan.download_tasks, [])
        self.assertEqual(plan.reused_resources[0]["filename"], "minimax_h3_fl2va_pruned_fp8_scaled.safetensors")


if __name__ == "__main__":
    unittest.main()
