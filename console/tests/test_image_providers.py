import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "console"))

from image_providers import generate_image, normalize_image_provider


class ImageProviderTests(unittest.TestCase):
    def test_legacy_provider_values_are_normalized(self):
        self.assertEqual(normalize_image_provider({"provider": "local"})["active_provider"], "boogu")
        self.assertEqual(normalize_image_provider({"provider": "cloud", "provider_type": "agnes"})["active_provider"], "agnes")

    def test_selected_provider_is_the_only_provider_called(self):
        calls = []
        adapters = {
            "comfyui": lambda request: calls.append("comfyui") or (_ for _ in ()).throw(RuntimeError("offline")),
            "agnes": lambda request: calls.append("agnes") or {"filename": "a.png"},
            "boogu": lambda request: calls.append("boogu") or {"filename": "b.png"},
        }
        with self.assertRaisesRegex(RuntimeError, "offline"):
            generate_image("comfyui", {"prompt": "x"}, adapters=adapters)
        self.assertEqual(calls, ["comfyui"])

    def test_agnes_failure_does_not_fallback(self):
        calls = []
        adapters = {
            "agnes": lambda request: calls.append("agnes") or (_ for _ in ()).throw(RuntimeError("agnes failed")),
            "boogu": lambda request: calls.append("boogu") or {"filename": "b.png"},
        }
        with self.assertRaisesRegex(RuntimeError, "agnes failed"):
            generate_image("agnes", {"prompt": "x"}, adapters=adapters)
        self.assertEqual(calls, ["agnes"])


if __name__ == "__main__":
    unittest.main()
