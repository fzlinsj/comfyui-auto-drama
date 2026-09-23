import builtins
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = PROJECT_ROOT / "workflows"
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

import build_api_graphs as bg


class WorkflowEncodingTests(unittest.TestCase):
    def test_workflow_json_is_read_as_utf8(self):
        real_open = builtins.open
        workflow_paths = {
            os.path.abspath(bg.T2V_WF),
            os.path.abspath(bg.I2V_TEMPLATE),
            os.path.abspath(bg.R2V_TEMPLATE),
        }

        def windows_default_open(file, mode="r", *args, **kwargs):
            path = os.path.abspath(os.fspath(file))
            if path in workflow_paths and "b" not in mode and kwargs.get("encoding") is None:
                raise UnicodeDecodeError("gbk", b"\xa4", 0, 1, "illegal multibyte sequence")
            return real_open(file, mode, *args, **kwargs)

        task = {
            "prompt": "test prompt",
            "image": "first.png",
            "images": ["first.png"],
            "duration": 4,
            "seed": 1,
            "prefix": "test/output",
            "mp": 0.4,
            "steps": 4,
        }
        with patch("builtins.open", side_effect=windows_default_open):
            bg.convert_t2v(task)
            bg.build_i2v(task)
            bg.build_r2v(task)


if __name__ == "__main__":
    unittest.main()
