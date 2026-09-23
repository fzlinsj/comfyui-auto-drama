import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


CONSOLE_DIR = Path(__file__).resolve().parents[1]
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

import batch_console as bc


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class _Opener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if isinstance(request, str):
            return _Response(b"image-bytes")
        return _Response(json.dumps({"data": [{"url": "https://cdn.example/image.png"}]}).encode())


class AgnesImageTests(unittest.TestCase):
    def test_image_error_message_does_not_mislabel_agnes_as_boogu(self):
        message = bc._image_error_message(FileNotFoundError("missing"))
        self.assertEqual(message, "生图失败：missing")

    def test_image_directories_are_created_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "素材"
            with patch.object(bc, "IMAGE_DIRS", [str(target)]):
                bc._ensure_image_dirs()
            self.assertTrue(target.is_dir())

    def test_cloud_failure_does_not_mask_error_with_local_fallback(self):
        main = {"provider": "cloud", "provider_type": "agnes", "url": "https://apihub.agnes-ai.com/v1"}
        backup = {"provider": "local", "url": "http://127.0.0.1:8081"}
        with patch.object(bc, "_image_gen_endpoints", return_value=(main, backup)), \
             patch.dict(bc._IMG_ADAPTERS, {"agnes": unittest.mock.Mock(side_effect=RuntimeError("Agnes 返回缺少图片 URL"))}), \
             patch.object(bc, "_boogu_local", side_effect=AssertionError("不应回退本地 Boogu")):
            with self.assertRaisesRegex(RuntimeError, "Agnes 返回缺少图片 URL"):
                bc.boogu_generate("a test prompt", "test.png")

    def test_agnes_payload_uses_size_ratio_and_base64_response(self):
        payload = bc._agnes_payload("a test prompt", "768x1024", "agnes-image-2.5-flash")

        self.assertEqual(payload["model"], "agnes-image-2.5-flash")
        self.assertEqual(payload["prompt"], "a test prompt")
        self.assertEqual(payload["size"], "2K")
        self.assertEqual(payload["ratio"], "3:4")
        self.assertTrue(payload["return_base64"])
        self.assertNotIn("extra_body", payload)
        self.assertNotIn("response_format", payload)

    def test_agnes_url_response_is_downloaded(self):
        opener = _Opener()
        with tempfile.TemporaryDirectory() as tmp, patch.object(bc, "_opener", return_value=opener), patch.object(bc, "IMAGE_DIRS", [tmp]):
            filename, path = bc._img_agnes(
                {"url": "https://apihub.agnes-ai.com/v1", "api_key": "token", "model": "agnes-image-2.5-flash"},
                "a test prompt",
                "test.png",
                "768x1024",
                timeout=1,
            )

            self.assertEqual(filename, "test.png")
            self.assertEqual(Path(path).read_bytes(), b"image-bytes")
            request_payload = json.loads(opener.requests[0].data.decode())
            self.assertEqual(request_payload["ratio"], "3:4")
            self.assertTrue(request_payload["return_base64"])


if __name__ == "__main__":
    unittest.main()
