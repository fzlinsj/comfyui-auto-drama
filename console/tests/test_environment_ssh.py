import base64
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_models import EnvironmentError
from environment_ssh import (
    FakeSSHSession,
    SSHConnectionInfo,
    SSHSession,
    build_recipe_command,
    fingerprint_from_keyscan,
    parse_ssh_command,
)


class EnvironmentSSHTests(unittest.TestCase):
    def test_parse_ssh_command(self):
        info = parse_ssh_command("ssh -p 18078 root@connect.example.com")
        self.assertEqual(info.host, "connect.example.com")
        self.assertEqual(info.port, 18078)
        self.assertEqual(info.username, "root")

    def test_changed_fingerprint_is_blocked(self):
        session = FakeSSHSession(fingerprint="SHA256:new")
        with self.assertRaises(EnvironmentError) as ctx:
            session.verify_fingerprint("SHA256:old", confirmed=False)
        self.assertEqual(ctx.exception.code, "E-SSH-FINGERPRINT")

    def test_command_builder_never_accepts_arbitrary_shell(self):
        command = build_recipe_command("disk_probe", {"path": "/data"})
        self.assertIn("/data", command)
        self.assertNotIn("password", command)
        with self.assertRaises(ValueError):
            build_recipe_command("arbitrary", {"shell": "rm -rf /"})

    def test_model_probe_accepts_only_configured_paths(self):
        command = build_recipe_command(
            "model_probe",
            {"comfy_path": "/root/ComfyUI", "data_path": "/root/autodl-tmp"},
        )
        self.assertIn("/root/ComfyUI", command)
        self.assertIn("/root/autodl-tmp", command)
        self.assertNotIn("password", command.lower())
        with self.assertRaises(ValueError):
            build_recipe_command("model_probe", {"comfy_path": "/root/ComfyUI", "shell": "rm -rf /"})

    def test_model_probe_succeeds_when_optional_model_roots_are_missing(self):
        command = build_recipe_command(
            "model_probe",
            {"comfy_path": "/root/ComfyUI", "data_path": "/root/autodl-tmp"},
        )
        # Missing candidate directories are normal on a clean or partially
        # configured machine and must not turn an inventory probe into an SSH
        # authentication failure.
        self.assertTrue(command.rstrip().endswith("; true"))

    def test_download_file_recipe_is_remote_and_checksum_guarded(self):
        command = build_recipe_command(
            "download_file",
            {
                "url": "https://example.com/model.safetensors",
                "target": "/root/autodl-tmp/models/checkpoints/model.safetensors",
                "sha256": "a" * 64,
                "size_bytes": 123,
            },
        )
        self.assertIn("curl", command)
        self.assertIn("/root/autodl-tmp/models/checkpoints/model.safetensors", command)
        self.assertIn("sha256sum", command)
        self.assertIn("123", command)
        self.assertNotIn("api_key", command.lower())
        self.assertIn("--connect-timeout 20", command)

    def test_download_file_recipe_rejects_credentials_and_shell_paths(self):
        with self.assertRaises(ValueError):
            build_recipe_command("download_file", {
                "url": "https://user:secret@example.com/model",
                "target": "/tmp/model",
                "sha256": "a" * 64,
                "size_bytes": 1,
            })
        with self.assertRaises(ValueError):
            build_recipe_command("download_file", {
                "url": "https://example.com/model",
                "target": "/tmp/model; touch /tmp/pwned",
                "sha256": "a" * 64,
                "size_bytes": 1,
            })

    def test_clone_node_recipe_only_accepts_git_http_url(self):
        command = build_recipe_command(
            "clone_node",
            {"url": "https://github.com/example/Node.git", "target": "/root/ComfyUI/custom_nodes/Node"},
        )
        self.assertIn("git clone", command)
        self.assertIn("/root/ComfyUI/custom_nodes/Node", command)
        self.assertIn("rmdir", command)
        self.assertIn("remote set-url origin", command)
        with self.assertRaises(ValueError):
            build_recipe_command("clone_node", {"url": "file:///tmp/Node.git", "target": "/tmp/Node"})

    def test_fake_session_records_only_recipe_commands(self):
        session = FakeSSHSession({"gpu": {"name": "RTX 3090"}})
        self.assertEqual(session.run_recipe("system_probe", {}), {"gpu": {"name": "RTX 3090"}})
        self.assertEqual(len(session.install_commands), 0)

    def test_keyscan_fingerprint_is_derived_from_public_key_blob(self):
        key_blob = b"test-public-key-blob"
        encoded = base64.b64encode(key_blob).decode("ascii")
        output = f"example.com ssh-ed25519 {encoded}\n"
        expected = "SHA256:" + base64.b64encode(hashlib.sha256(key_blob).digest()).decode("ascii").rstrip("=")
        self.assertEqual(fingerprint_from_keyscan(output), expected)

    def test_session_observes_fingerprint_before_authenticated_probe(self):
        key_blob = b"test-public-key-blob"
        encoded = base64.b64encode(key_blob).decode("ascii")
        calls = []

        def runner(args, **kwargs):
            calls.append(args)
            known_hosts = next(item.split("=", 1)[1] for item in args if item.startswith("UserKnownHostsFile="))
            Path(known_hosts).write_text(f"host ssh-ed25519 {encoded}\n", encoding="utf-8")
            return type("Result", (), {"returncode": 255, "stdout": "", "stderr": "Permission denied"})()

        session = SSHSession(SSHConnectionInfo("host"), runner=runner)
        self.assertTrue(session.observe_fingerprint().startswith("SHA256:"))
        self.assertEqual(calls[0][0], "ssh")
        self.assertIn("KexAlgorithms=curve25519-sha256,ecdh-sha2-nistp256,diffie-hellman-group14-sha256", calls[0])
        self.assertIn("StrictHostKeyChecking=accept-new", calls[0])
        self.assertIn("PreferredAuthentications=none", calls[0])
        known_hosts = next(item.split("=", 1)[1] for item in calls[0] if item.startswith("UserKnownHostsFile="))
        self.assertFalse(Path(known_hosts).exists())

    def test_private_key_content_is_cleaned_after_probe(self):
        calls = []

        def runner(args, **kwargs):
            calls.append(list(args))
            if "exit" in args:
                known_hosts = next(item.split("=", 1)[1] for item in args if item.startswith("UserKnownHostsFile="))
                Path(known_hosts).write_text("host ssh-ed25519 dGVzdA==\n", encoding="utf-8")
                return type("Result", (), {"returncode": 255, "stdout": "", "stderr": "Permission denied"})()
            key_path = args[args.index("-i") + 1]
            self.assertTrue(Path(key_path).exists())
            return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

        session = SSHSession(
            SSHConnectionInfo("host"),
            credential={"private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n-----END OPENSSH PRIVATE KEY-----"},
            runner=runner,
        )
        session.verify_fingerprint(session.observe_fingerprint(), confirmed=True)
        self.assertEqual(session.run_recipe("system_probe"), "ok")
        key_path = calls[-1][calls[-1].index("-i") + 1]
        self.assertFalse(Path(key_path).exists())
        self.assertNotIn("SSH_ASKPASS", calls[-1])

    def test_password_session_uses_askpass_and_cleans_helper(self):
        calls = []

        def runner(args, **kwargs):
            calls.append((list(args), dict(kwargs)))
            if args[-1] == "exit":
                known_hosts = next(item.split("=", 1)[1] for item in args if item.startswith("UserKnownHostsFile="))
                Path(known_hosts).write_text("host ssh-ed25519 dGVzdA==\n", encoding="utf-8")
                return type("Result", (), {"returncode": 255, "stdout": "", "stderr": "Permission denied"})()
            env = calls[-1][1]["env"]
            self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
            self.assertIn("SSH_ASKPASS", env)
            self.assertEqual(env["TOONFLOW_SSH_ASKPASS_SECRET"], "secret")
            self.assertNotIn("secret", " ".join(args))
            helper = Path(env["SSH_ASKPASS"])
            self.assertTrue(helper.exists())
            return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

        session = SSHSession(SSHConnectionInfo("host"), credential={"password": "secret"}, runner=runner)
        observed = session.observe_fingerprint()
        session.verify_fingerprint(observed, confirmed=True)
        self.assertEqual(session.run_recipe("system_probe"), "ok")
        helper = calls[-1][1]["env"]["SSH_ASKPASS"]
        self.assertFalse(Path(helper).exists())

    def test_password_auth_failure_is_redacted_and_has_auth_code(self):
        def runner(args, **kwargs):
            if args[-1] == "exit":
                known_hosts = next(item.split("=", 1)[1] for item in args if item.startswith("UserKnownHostsFile="))
                Path(known_hosts).write_text("host ssh-ed25519 dGVzdA==\n", encoding="utf-8")
                return type("Result", (), {"returncode": 255, "stdout": "", "stderr": "Permission denied"})()
            return type("Result", (), {"returncode": 255, "stdout": "", "stderr": "password=secret"})()

        session = SSHSession(SSHConnectionInfo("host"), credential={"password": "secret"}, runner=runner)
        session.verify_fingerprint(session.observe_fingerprint(), confirmed=True)
        with self.assertRaises(EnvironmentError) as ctx:
            session.run_recipe("system_probe")
        self.assertEqual(ctx.exception.code, "E-SSH-AUTH")
        self.assertNotIn("secret", str(ctx.exception))

    def test_password_helper_is_cleaned_after_timeout(self):
        helper_path = {}

        def runner(args, **kwargs):
            if args[-1] == "exit":
                known_hosts = next(item.split("=", 1)[1] for item in args if item.startswith("UserKnownHostsFile="))
                Path(known_hosts).write_text("host ssh-ed25519 dGVzdA==\n", encoding="utf-8")
                return type("Result", (), {"returncode": 255, "stdout": "", "stderr": "Permission denied"})()
            helper_path["path"] = kwargs["env"]["SSH_ASKPASS"]
            raise subprocess.TimeoutExpired(args, 1)

        session = SSHSession(SSHConnectionInfo("host"), credential={"password": "secret"}, runner=runner)
        session.verify_fingerprint(session.observe_fingerprint(), confirmed=True)
        with self.assertRaises(EnvironmentError) as ctx:
            session.run_recipe("system_probe")
        self.assertEqual(ctx.exception.code, "E-SSH-AUTH")
        self.assertFalse(Path(helper_path["path"]).exists())


if __name__ == "__main__":
    unittest.main()
