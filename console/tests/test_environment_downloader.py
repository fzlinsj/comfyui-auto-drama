import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_models import EnvironmentError
from environment_downloader import RemoteDownloader, ResumableDownloader, build_download_sources, finalize_download


class EnvironmentDownloaderTests(unittest.TestCase):
    def test_checksum_failure_never_promotes_part_file(self):
        with tempfile.TemporaryDirectory() as directory:
            part = Path(directory) / "model.safetensors.part"
            target = Path(directory) / "model.safetensors"
            part.write_bytes(b"wrong")
            with self.assertRaises(EnvironmentError) as ctx:
                finalize_download(part, target, sha256="bad")
            self.assertEqual(ctx.exception.code, "E-CHECKSUM")
            self.assertTrue(part.exists())
            self.assertFalse(target.exists())

    def test_verified_target_is_reused_without_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "model.bin"
            target.write_bytes(b"already here")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            calls = []
            downloader = ResumableDownloader(fetcher=lambda url, path, offset: calls.append(url))
            result = downloader.download({"filename": str(target), "primary_url": "https://example.invalid/model", "fallback_urls": [], "sha256": digest, "size_bytes": target.stat().st_size})
            self.assertEqual(result.status, "reused")
            self.assertEqual(calls, [])

    def test_fallback_source_is_used_after_first_source_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "model.bin"
            calls = []

            def fetch(url, path, offset):
                calls.append(url)
                if len(calls) == 1:
                    raise OSError("source unavailable")
                Path(path).write_bytes(b"payload")

            downloader = ResumableDownloader(fetcher=fetch, max_attempts=1)
            digest = hashlib.sha256(b"payload").hexdigest()
            result = downloader.download({"filename": str(target), "primary_url": "https://one.invalid/model", "fallback_urls": ["https://two.invalid/model"], "sha256": digest, "size_bytes": 7})
            self.assertEqual(result.status, "downloaded")
            self.assertEqual(calls, ["https://one.invalid/model", "https://two.invalid/model"])
            self.assertEqual(target.read_bytes(), b"payload")

    def test_remote_downloader_sends_model_to_remote_data_disk(self):
        class Session:
            def __init__(self):
                self.calls = []

            def run_recipe(self, name, params=None, timeout=60):
                self.calls.append((name, params, timeout))
                return "verified"

        session = Session()
        downloader = RemoteDownloader(session, "/root/autodl-tmp", "/root/ComfyUI")
        result = downloader.download({
            "resource_kind": "model",
            "filename": "model.safetensors",
            "target_dir": "models/checkpoints",
            "primary_url": "https://example.com/model.safetensors",
            "sha256": "a" * 64,
            "size_bytes": 123,
        })
        self.assertEqual(result.status, "downloaded")
        name, params, timeout = session.calls[0]
        self.assertEqual(name, "download_file")
        self.assertEqual(params["target"], "/root/autodl-tmp/models/checkpoints/model.safetensors")
        self.assertGreaterEqual(timeout, 7200)

    def test_remote_downloader_clones_node_into_comfy_custom_nodes(self):
        class Session:
            def __init__(self):
                self.calls = []

            def run_recipe(self, name, params=None, timeout=60):
                self.calls.append((name, params, timeout))
                return "cloned"

        session = Session()
        downloader = RemoteDownloader(session, "/root/autodl-tmp", "/root/ComfyUI")
        result = downloader.download({
            "resource_kind": "node",
            "filename": "ComfyUI-Manager",
            "target_dir": "custom_nodes",
            "primary_url": "https://github.com/example/ComfyUI-Manager.git",
        })
        self.assertEqual(result.status, "downloaded")
        self.assertEqual(session.calls[0][0], "clone_node")
        self.assertEqual(session.calls[0][1]["target"], "/root/ComfyUI/custom_nodes/ComfyUI-Manager")

    def test_remote_downloader_tries_mirror_after_huggingface_timeout(self):
        class Session:
            def __init__(self):
                self.calls = []

            def run_recipe(self, name, params=None, timeout=60):
                self.calls.append((name, params, timeout))
                if len(self.calls) == 1:
                    raise EnvironmentError("curl timeout", "E-SSH-AUTH")
                return "verified"

        session = Session()
        downloader = RemoteDownloader(session, "/root/autodl-tmp", "/root/ComfyUI")
        result = downloader.download({
            "resource_kind": "model",
            "filename": "model.safetensors",
            "target_dir": "models/checkpoints",
            "primary_url": "https://huggingface.co/org/repo/resolve/main/model.safetensors",
            "fallback_urls": [],
            "sha256": "a" * 64,
            "size_bytes": 123,
        })
        self.assertEqual(result.source, "https://huggingface.co/org/repo/resolve/main/model.safetensors")
        self.assertEqual(session.calls[0][1]["url"], "https://hf-mirror.com/org/repo/resolve/main/model.safetensors")

    def test_huggingface_mirror_is_added_when_recipe_has_no_fallback(self):
        sources = build_download_sources({
            "primary_url": "https://huggingface.co/org/repo/resolve/main/model.safetensors",
            "fallback_urls": [],
        })
        self.assertEqual(sources[0], "https://hf-mirror.com/org/repo/resolve/main/model.safetensors")
        self.assertIn("https://huggingface.co/org/repo/resolve/main/model.safetensors", sources)

    def test_explicit_mirror_is_not_duplicated(self):
        sources = build_download_sources({
            "primary_url": "https://huggingface.co/org/repo/file.bin",
            "fallback_urls": ["https://hf-mirror.com/org/repo/file.bin"],
        })
        self.assertEqual(sources.count("https://hf-mirror.com/org/repo/file.bin"), 1)

    def test_github_clone_sources_include_domestic_git_proxy_fallbacks(self):
        sources = build_download_sources({
            "resource_kind": "node",
            "primary_url": "https://github.com/org/Node.git",
            "fallback_urls": [],
        })
        self.assertEqual(sources[0], "https://ghfast.top/https://github.com/org/Node.git")
        self.assertIn("https://gh-proxy.com/https://github.com/org/Node.git", sources)
        self.assertIn("https://ghproxy.net/https://github.com/org/Node.git", sources)


if __name__ == "__main__":
    unittest.main()
