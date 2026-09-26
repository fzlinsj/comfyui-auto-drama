import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_scanner import EnvironmentScanner, classify_environment
from environment_ssh import FakeSSHSession


class EnvironmentScannerTests(unittest.TestCase):
    def test_scan_is_read_only(self):
        fixture = {
            "system_probe": {"platform": "autodl", "os": "Ubuntu 22.04", "memory_bytes": 96 * 1024**3},
            "gpu_probe": {"name": "NVIDIA GeForce RTX 3090", "memory_bytes": 24 * 1024**3, "cuda": "12.1"},
            "disk_probe": {"path": "/root/autodl-tmp", "free_bytes": 120 * 1024**3, "total_bytes": 200 * 1024**3},
            "python_probe": {"version": "3.10.14", "executable": "/opt/py/bin/python3"},
            "comfy_probe": {
                "path": "/root/ComfyUI",
                "present": True,
                "version": "0.31.0",
                "nodes": ["ComfyUI-Manager"],
                "models": ["sdxl_base_1.0.safetensors"],
                "ports": [8188],
                "processes": [{"name": "python", "status": "running"}],
            },
            "model_probe": "\n".join([
                "model\t/root/ComfyUI/models/checkpoints/sd_xl_base_1.0.safetensors\t6938078336",
                "node\tComfyUI-Manager\t0\t/root/ComfyUI/custom_nodes/ComfyUI-Manager",
            ]),
        }
        session = FakeSSHSession(fixture)
        result = EnvironmentScanner(session).scan()
        self.assertEqual(result.gpu.name, "NVIDIA GeForce RTX 3090")
        self.assertTrue(result.has_gpu)
        self.assertEqual(result.environment_kind, "pure_comfyui")
        self.assertEqual(result.comfyui["models"][0]["filename"], "sd_xl_base_1.0.safetensors")
        self.assertEqual(result.comfyui["models"][0]["target_dir"], "models/checkpoints")
        self.assertEqual(result.comfyui["models"][0]["size_bytes"], 6938078336)
        self.assertEqual(result.comfyui["nodes"][0]["filename"], "ComfyUI-Manager")
        self.assertEqual(session.install_commands, [])
        self.assertNotIn("password", repr(result))

    def test_scan_detects_platform_from_labels(self):
        result = EnvironmentScanner(FakeSSHSession({"system_probe": {"platform": "晨羽智云"}})).scan()
        self.assertEqual(result.platform, "chenyu")

    def test_scan_detects_clean_comfyui_and_bundle(self):
        self.assertEqual(classify_environment({"python": True, "comfyui": False}), "clean_system")
        self.assertEqual(classify_environment({"python": True, "comfyui": True, "bundle": False}), "pure_comfyui")
        self.assertEqual(classify_environment({"comfyui": True, "bundle": True}), "integrated_bundle")

    def test_scan_parses_plain_ssh_probe_output(self):
        fixture = {
            "system_probe": (
                "Linux autodl 5.15.0-100-generic #110-Ubuntu SMP x86_64 GNU/Linux\n"
                "uid=0(root) gid=0(root) groups=0(root)\n"
                "Python 3.10.14\n"
            ),
            "gpu_probe": "NVIDIA GeForce RTX 3090, 24576 MiB, 535.104.05\n",
            "disk_probe": (
                "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
                "/dev/sda1 1048576 524288 524288 50% /root/autodl-tmp\n"
            ),
            "python_probe": "Python 3.10.14\n",
            "comfy_probe": "/root/ComfyUI/main.py\n",
        }
        result = EnvironmentScanner(FakeSSHSession(fixture), data_path="/root/autodl-tmp", comfy_path="/root/ComfyUI").scan()
        self.assertEqual(result.platform, "autodl")
        self.assertTrue(result.has_gpu)
        self.assertEqual(result.gpu.name, "NVIDIA GeForce RTX 3090")
        self.assertEqual(result.gpu.memory_bytes, 24576 * 1024**2)
        self.assertEqual(result.gpu.driver, "535.104.05")
        self.assertEqual(result.disk["free_bytes"], 524288 * 1024)
        self.assertEqual(result.disk["total_bytes"], 1048576 * 1024)
        self.assertEqual(result.python["version"], "3.10.14")
        self.assertTrue(result.comfyui["present"])
        self.assertEqual(result.comfyui["path"], "/root/ComfyUI")
        self.assertEqual(result.environment_kind, "pure_comfyui")

    def test_scan_uses_selected_platform_when_hostname_has_no_provider_label(self):
        fixture = {
            "system_probe": "Linux cloud 5.15.0-100-generic #110-Ubuntu SMP x86_64 GNU/Linux\n",
            "gpu_probe": "",
            "disk_probe": "Filesystem 1024-blocks Used Available Capacity Mounted on\n",
            "python_probe": "Python 3.10.14\n",
            "comfy_probe": "",
        }
        result = EnvironmentScanner(FakeSSHSession(fixture), platform_hint="autodl").scan()
        self.assertEqual(result.platform, "autodl")

    def test_scan_parses_python_sys_version_output(self):
        fixture = {
            "system_probe": "Linux cloud 5.15.0-100-generic #110-Ubuntu SMP x86_64 GNU/Linux\n",
            "gpu_probe": "",
            "disk_probe": "Filesystem 1024-blocks Used Available Capacity Mounted on\n",
            "python_probe": "3.10.14 (main, Jun  7 2024, 12:00:00) [GCC 11.4.0]\n",
            "comfy_probe": "",
        }
        result = EnvironmentScanner(FakeSSHSession(fixture)).scan()
        self.assertEqual(result.python["version"], "3.10.14")

    def test_scan_finds_models_in_shared_models_mount_and_deduplicates(self):
        fixture = {
            "system_probe": "Linux cloud 5.15.0-100-generic #110-Ubuntu SMP x86_64 GNU/Linux\n",
            "gpu_probe": "",
            "disk_probe": "Filesystem 1024-blocks Used Available Capacity Mounted on\n",
            "python_probe": "Python 3.10.14\n",
            "comfy_probe": "/root/ComfyUI/main.py\n",
            "model_probe": "\n".join([
                "model\t/root/shared/models/checkpoints/sd_xl_base_1.0.safetensors\t123",
                "model\t/root/shared/models/checkpoints/sd_xl_base_1.0.safetensors\t123",
            ]),
        }
        result = EnvironmentScanner(FakeSSHSession(fixture)).scan()
        self.assertEqual(result.comfyui["models"], [{
            "filename": "sd_xl_base_1.0.safetensors",
            "target_dir": "models/checkpoints",
            "size_bytes": 123,
            "path": "/root/shared/models/checkpoints/sd_xl_base_1.0.safetensors",
        }])


if __name__ == "__main__":
    unittest.main()
