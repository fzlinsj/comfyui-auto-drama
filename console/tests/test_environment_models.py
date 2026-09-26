import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_models import environment_status_after_prepare, redact_environment_data


class EnvironmentModelTests(unittest.TestCase):
    def test_gpu_free_prepare_is_not_available(self):
        self.assertEqual(environment_status_after_prepare(has_gpu=False), "prepared_waiting_gpu")
        self.assertNotEqual(environment_status_after_prepare(has_gpu=False), "available")

    def test_secret_redaction_removes_password_and_token(self):
        value = redact_environment_data("ssh root@host -p 22 password=abc token=xyz")
        self.assertNotIn("abc", value)
        self.assertNotIn("xyz", value)
        self.assertIn("password=***", value)


if __name__ == "__main__":
    unittest.main()
