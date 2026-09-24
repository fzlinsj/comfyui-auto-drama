import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from failure_diagnostics import parse_comfyui_failure, redact_secrets


class FailureDiagnosticTests(unittest.TestCase):
    def test_oom_contains_node_and_actionable_summary(self):
        entry = {"status": {"messages": [["execution_error", {
            "node_id": "125",
            "node_type": "SamplerCustomAdvanced",
            "exception_type": "torch.OutOfMemoryError",
            "exception_message": "Allocation on device",
        }]]}}
        failure = parse_comfyui_failure(entry)
        self.assertEqual(failure["code"], "F-OOM")
        self.assertEqual(failure["node_id"], "125")
        self.assertEqual(failure["node_type"], "SamplerCustomAdvanced")
        self.assertIn("显存不足", failure["summary"])

    def test_redaction_removes_bearer_and_configured_keys(self):
        text = "Authorization: Bearer secret-token api_key=cpk-private"
        cleaned = redact_secrets(text, ["secret-token", "cpk-private"])
        self.assertNotIn("secret-token", cleaned)
        self.assertNotIn("cpk-private", cleaned)
        self.assertIn("***", cleaned)


if __name__ == "__main__":
    unittest.main()
