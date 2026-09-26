import json
import sys
import tempfile
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CONSOLE_DIR.parent
sys.path.insert(0, str(CONSOLE_DIR))

from environment_models import EnvironmentError
from environment_manager import EnvironmentManager
from environment_ssh import FakeSSHSession
from task_store import TaskStore


class EnvironmentApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TaskStore(str(Path(self.temp.name) / "console.db"))
        fixture = {
            "system_probe": {"platform": "autodl", "host_fingerprint": "SHA256:test"},
            "gpu_probe": {"name": "RTX 3090", "memory_bytes": 24 * 1024**3},
            "disk_probe": {"free_bytes": 200 * 1024**3},
            "python_probe": {"version": "3.10.14"},
            "comfy_probe": {"present": True, "version": "0.31.0"},
        }
        self.session = FakeSSHSession(fixture)
        self.manager = EnvironmentManager(self.store, session_factory=lambda *args, **kwargs: self.session)

    def tearDown(self):
        self.temp.cleanup()

    def test_first_scan_authenticates_without_fingerprint_payload(self):
        result = self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret"})
        self.assertEqual(result["scan"]["gpu"]["name"], "RTX 3090")
        self.assertNotIn("host_fingerprint", result["scan"])
        self.assertNotIn("SHA256:test", json.dumps(result["scan"], ensure_ascii=False))
        self.assertEqual(self.session.install_commands, [])
        target = self.store.find_environment_target("autodl", "host", "root", 22)
        self.assertEqual(target["fingerprint"], "SHA256:test")

    def test_same_target_fingerprint_is_reused_without_confirmation(self):
        self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret"})
        result = self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret"})
        self.assertEqual(result["scan"]["gpu"]["name"], "RTX 3090")
        self.assertEqual(self.session.commands, ["system_probe", "gpu_probe", "disk_probe", "python_probe", "comfy_probe", "model_probe"] * 2)

    def test_changed_fingerprint_is_blocked_without_retrust(self):
        self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret"})
        self.session.fingerprint = "SHA256:changed"
        with self.assertRaises(EnvironmentError) as ctx:
            self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret"})
        self.assertEqual(ctx.exception.code, "E-SSH-FINGERPRINT")
        self.assertTrue(ctx.exception.details["can_retrust"])

    def test_retrust_updates_fingerprint_after_authenticated_scan(self):
        self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret"})
        self.session.fingerprint = "SHA256:changed"
        result = self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret", "retrust": True})
        self.assertEqual(result["scan"]["gpu"]["name"], "RTX 3090")
        target = self.store.find_environment_target("autodl", "host", "root", 22)
        self.assertEqual(target["fingerprint"], "SHA256:changed")

    def test_plan_references_recipe_version(self):
        scan = self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret"})
        plan = self.manager.make_plan(scan["target_id"], scan["scan_id"], "minimax-h3-sdxl")
        self.assertEqual(plan["recipe_version"], "1.0.0")
        self.assertIn(plan["status"], {"plan_ready", "blocked"})

    def test_deploy_requires_plan_version_and_confirmation(self):
        with self.assertRaises(EnvironmentError) as ctx:
            self.manager.start_deploy("p1", recipe_version="1.0.0", confirm=False)
        self.assertEqual(ctx.exception.code, "E-CONFIRMATION-REQUIRED")

    def test_job_payload_is_redacted(self):
        payload = self.manager.redact_payload({"message": "password=secret", "credential_ref": "ref"})
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("private_key", rendered)


if __name__ == "__main__":
    unittest.main()
