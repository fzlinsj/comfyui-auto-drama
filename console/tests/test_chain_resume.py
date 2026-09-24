import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


CONSOLE_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = CONSOLE_DIR.parent / "workflows"
import sys

if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))

import batch_console as bc


class ChainResumeTests(unittest.TestCase):
    def test_waiting_retry_can_use_predecessor_already_marked_chain_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "outputs" / "output" / "video"
            output_dir.mkdir(parents=True)
            video = output_dir / "previous.mp4"
            video.write_bytes(b"video")
            last_frame = Path(tmp) / "last.png"
            last_frame.write_bytes(b"png")
            state = {
                "tasks": [
                    {
                        "id": "prev",
                        "name": "segment_03",
                        "prompt_id": "prev-prompt",
                        "chain_done": True,
                        "downloaded": True,
                        "output_file": {
                            "filename": video.name,
                            "subfolder": "video",
                            "type": "output",
                        },
                    },
                    {
                        "id": "original-next",
                        "name": "segment_04",
                        "prompt_id": "original-prompt",
                    },
                    {
                        "id": "retry",
                        "name": "segment_04_v2",
                        "mode": "i2v",
                        "prompt": "continue the shot",
                        "duration": 2,
                        "mp": 0.4,
                        "chain_waiting": True,
                        "chain_prev": "prev",
                        "prompt_id": None,
                    },
                ]
            }
            import build_api_graphs as bg

            with patch.object(bc, "OUTPUTS_DIR", str(Path(tmp) / "outputs")), \
                 patch.object(bc, "extract_last_frame", return_value=str(last_frame)), \
                 patch.object(bc, "upload_image"), \
                 patch.object(bc, "api_post", return_value={"prompt_id": "retry-prompt"}), \
                 patch.object(bg, "build_i2v", return_value={"1": {"class_type": "Test"}}):
                changed = bc.advance_chain("http://comfy.test", state)

            self.assertTrue(changed)
            retry = next(t for t in state["tasks"] if t["id"] == "retry")
            self.assertEqual(retry["prompt_id"], "retry-prompt")
            self.assertFalse(retry["chain_waiting"])
            self.assertEqual(retry["image"], "chain_prev.png")


if __name__ == "__main__":
    unittest.main()
