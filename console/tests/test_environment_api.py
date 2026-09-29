import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

CONSOLE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CONSOLE_DIR.parent
sys.path.insert(0, str(CONSOLE_DIR))

from environment_models import EnvironmentError
from environment_manager import EnvironmentManager
from environment_ssh import FakeSSHSession
from task_store import TaskStore


class FakeCredentialStore:
    supported = True

    def __init__(self):
        self.values = {}

    def save(self, password, credential_ref=None):
        ref = credential_ref or "saved-ref"
        self.values[ref] = password
        return ref

    def load(self, credential_ref):
        return self.values.get(credential_ref)

    def delete(self, credential_ref):
        return self.values.pop(credential_ref, None) is not None


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

    def test_successful_scan_can_save_and_reuse_password(self):
        credentials = FakeCredentialStore()
        captured = []
        manager = EnvironmentManager(
            self.store,
            session_factory=lambda connection, credential=None: (
                captured.append(dict(credential or {})) or self.session
            ),
            credential_store=credentials,
        )
        first = manager.scan_target({
            "platform": "autodl",
            "ssh_command": "ssh root@host",
            "password": "secret",
            "remember_password": True,
        })
        self.assertTrue(first["credential_saved"])
        self.assertTrue(first["has_saved_password"])
        self.assertNotIn("secret", json.dumps(first, ensure_ascii=False))
        second = manager.scan_target({
            "platform": "autodl",
            "ssh_command": "ssh root@host",
            "password": "",
        })
        self.assertEqual(captured[-1]["password"], "secret")
        self.assertTrue(second["has_saved_password"])

    def test_password_is_not_saved_when_authentication_fails(self):
        credentials = FakeCredentialStore()

        class FailingSession(FakeSSHSession):
            def observe_fingerprint(self):
                raise EnvironmentError("SSH 认证失败", "E-SSH-AUTH")

        manager = EnvironmentManager(
            self.store,
            session_factory=lambda *args, **kwargs: FailingSession(),
            credential_store=credentials,
        )
        with self.assertRaises(EnvironmentError):
            manager.scan_target({
                "platform": "autodl",
                "ssh_command": "ssh root@host",
                "password": "wrong",
                "remember_password": True,
            })
        self.assertEqual(credentials.values, {})

    def test_saved_password_auth_failure_is_marked_without_exposing_password(self):
        credentials = FakeCredentialStore()
        target_id = self.store.create_environment_target(
            "autodl", "host", username="root", credential_ref="saved-ref"
        )
        credentials.values["saved-ref"] = "old-secret"

        class FailingSession(FakeSSHSession):
            def observe_fingerprint(self):
                raise EnvironmentError("SSH 认证失败", "E-SSH-AUTH")

        manager = EnvironmentManager(
            self.store,
            session_factory=lambda *args, **kwargs: FailingSession(),
            credential_store=credentials,
        )
        with self.assertRaises(EnvironmentError) as ctx:
            manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host"})
        self.assertTrue(ctx.exception.details["saved_credential_invalid"])
        self.assertEqual(self.store.get_environment_target(target_id)["credential_ref"], "saved-ref")
        self.assertNotIn("old-secret", str(ctx.exception.details))

    def test_credential_status_and_clear_are_target_scoped(self):
        credentials = FakeCredentialStore()
        manager = EnvironmentManager(
            self.store,
            session_factory=lambda *args, **kwargs: self.session,
            credential_store=credentials,
        )
        scan = manager.scan_target({
            "platform": "autodl",
            "ssh_command": "ssh root@host",
            "password": "secret",
            "remember_password": True,
        })
        status = manager.get_credential_status("autodl", "ssh root@host")
        self.assertEqual(status["target_id"], scan["target_id"])
        self.assertTrue(status["has_saved_password"])
        cleared = manager.clear_saved_password(scan["target_id"])
        self.assertFalse(cleared["has_saved_password"])
        self.assertFalse(manager.clear_saved_password(scan["target_id"])["has_saved_password"])

    def test_plan_references_recipe_version(self):
        scan = self.manager.scan_target({"platform": "autodl", "ssh_command": "ssh root@host", "password": "secret"})
        plan = self.manager.make_plan(scan["target_id"], scan["scan_id"], "minimax-h3-sdxl")
        self.assertEqual(plan["recipe_version"], "1.0.0")
        self.assertIn(plan["status"], {"plan_ready", "blocked"})

    def test_deploy_requires_plan_version_and_confirmation(self):
        with self.assertRaises(EnvironmentError) as ctx:
            self.manager.start_deploy("p1", recipe_version="1.0.0", confirm=False)
        self.assertEqual(ctx.exception.code, "E-CONFIRMATION-REQUIRED")

    def test_start_deploy_passes_configured_verifier_to_deployer(self):
        verifier = object()
        manager = EnvironmentManager(
            self.store,
            downloader_factory=lambda: object(),
            verifier=verifier,
        )
        manager._plans["p1"] = {
            "plan": {
                "plan_id": "p1",
                "target_id": "target-1",
                "recipe_version": "1.0.0",
                "status": "plan_ready",
                "download_tasks": [],
            },
            "recipe": {},
            "scan": {"has_gpu": True},
        }
        manager._sessions["target-1"] = object()

        with patch("environment_manager.EnvironmentDeployer") as deployer_class, patch(
            "environment_manager.threading.Thread"
        ) as thread_class:
            manager.start_deploy("p1", recipe_version="1.0.0", confirm=True)

        self.assertIs(deployer_class.call_args.kwargs["verifier"], verifier)
        thread_class.return_value.start.assert_called_once_with()

    def test_job_payload_is_redacted(self):
        payload = self.manager.redact_payload({"message": "password=secret", "credential_ref": "ref"})
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("private_key", rendered)


if __name__ == "__main__":
    unittest.main()
