import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_credentials import CredentialStoreError, EnvironmentCredentialStore


class ReversibleProtector:
    def protect(self, value):
        return b"cipher:" + bytes(value)[::-1]

    def unprotect(self, value):
        raw = bytes(value)
        if not raw.startswith(b"cipher:"):
            raise CredentialStoreError("invalid ciphertext")
        return raw[len(b"cipher:"):][::-1]


class EnvironmentCredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "credentials.json"
        self.store = EnvironmentCredentialStore(
            path=self.path,
            protector=ReversibleProtector(),
            supported=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_replace_and_delete(self):
        ref = self.store.save("first-secret")
        self.assertEqual(self.store.load(ref), "first-secret")
        self.assertEqual(self.store.save("second-secret", credential_ref=ref), ref)
        self.assertEqual(self.store.load(ref), "second-secret")
        self.assertTrue(self.store.delete(ref))
        self.assertIsNone(self.store.load(ref))
        self.assertFalse(self.store.delete(ref))

    def test_file_never_contains_plaintext(self):
        self.store.save("plain-secret-marker")
        rendered = self.path.read_text(encoding="utf-8")
        self.assertNotIn("plain-secret-marker", rendered)
        self.assertEqual(json.loads(rendered)["version"], 1)

    def test_corrupt_file_is_treated_as_missing(self):
        self.path.write_text("not-json", encoding="utf-8")
        self.assertIsNone(self.store.load("missing"))

    def test_unsupported_store_refuses_save_without_plaintext_fallback(self):
        store = EnvironmentCredentialStore(path=self.path, supported=False)
        with self.assertRaises(CredentialStoreError):
            store.save("must-not-be-written")
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_default_windows_dpapi_round_trip(self):
        store = EnvironmentCredentialStore(path=self.path)
        ref = store.save("dpapi-round-trip-marker")
        self.assertEqual(store.load(ref), "dpapi-round-trip-marker")
        self.assertNotIn("dpapi-round-trip-marker", self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
