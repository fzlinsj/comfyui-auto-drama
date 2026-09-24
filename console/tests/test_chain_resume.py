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
    def test_persist_chain_frame_copies_extracted_frame_into_asset_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "last.png"
            source.write_bytes(b"png")
            asset_dir = Path(tmp) / "assets"
            video = Path(tmp) / "previous.mp4"
            video.write_bytes(b"video")

            with patch.object(bc, "IMAGE_DIRS", [str(asset_dir)]), \
                 patch.object(bc, "extract_last_frame", return_value=str(source)):
                result = bc.persist_chain_frame(str(video), "chain_prev.png")

            self.assertEqual(result, str(asset_dir / "chain_prev.png"))
            self.assertEqual((asset_dir / "chain_prev.png").read_bytes(), b"png")

    def test_missing_chain_image_is_rebuilt_from_predecessor_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "outputs" / "output" / "video"
            output_dir.mkdir(parents=True)
            video = output_dir / "previous.mp4"
            video.write_bytes(b"video")
            source = Path(tmp) / "last.png"
            source.write_bytes(b"png")
            asset_dir = Path(tmp) / "assets"
            state = {
                "tasks": [{
                    "id": "prev",
                    "output_file": {"filename": video.name, "subfolder": "video", "type": "output"},
                }]
            }
            task = {
                "id": "retry",
                "mode": "i2v",
                "image": "chain_task_3_previous.png",
                "chain_prev": "prev",
            }

            with patch.object(bc, "IMAGE_DIRS", [str(asset_dir)]), \
                 patch.object(bc, "OUTPUTS_DIR", str(Path(tmp) / "outputs")), \
                 patch.object(bc, "extract_last_frame", return_value=str(source)):
                result = bc.ensure_chain_image("http://comfy.test", task, state)

            self.assertEqual(result, str(asset_dir / "chain_task_3_previous.png"))
            self.assertTrue((asset_dir / "chain_task_3_previous.png").is_file())

    def test_submit_rebuilds_missing_chain_image_before_upload(self):
        task = {
            "id": "retry",
            "name": "segment_04_v2",
            "mode": "i2v",
            "image": "chain_task_3_previous.png",
            "chain_prev": "prev",
            "prompt": "continue",
        }
        state = {"tasks": [{"id": "prev", "output_file": {"filename": "previous.mp4"}}]}
        with patch.object(bc, "load_state", return_value=state), \
             patch.object(bc, "build_graphs", return_value=([(task, {"1": {}})], None)), \
             patch.object(bc, "api_get", return_value={"queue_running": [], "queue_pending": []}), \
             patch.object(bc, "api_post", return_value={"prompt_id": "retry-prompt"}), \
             patch.object(bc, "ensure_chain_image", return_value="D:/assets/chain_task_3_previous.png") as ensure, \
             patch.object(bc, "upload_image"), \
             patch.object(bc, "save_state"):
            results, error, _warnings = bc.submit_tasks("http://comfy.test", [task], auto_download=False)

        self.assertIsNone(error)
        self.assertTrue(results[0]["ok"])
        ensure.assert_called_once()

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
                 patch.object(bc, "persist_chain_frame", return_value=str(last_frame)) as persist, \
                 patch.object(bc, "upload_image"), \
                 patch.object(bc, "api_post", return_value={"prompt_id": "retry-prompt"}), \
                 patch.object(bg, "build_i2v", return_value={"1": {"class_type": "Test"}}):
                changed = bc.advance_chain("http://comfy.test", state)

            self.assertTrue(changed)
            retry = next(t for t in state["tasks"] if t["id"] == "retry")
            self.assertEqual(retry["prompt_id"], "retry-prompt")
            self.assertFalse(retry["chain_waiting"])
            self.assertEqual(retry["image"], "chain_prev.png")
            persist.assert_called_once_with(str(video), "chain_prev.png", frame_path=str(last_frame))


if __name__ == "__main__":
    unittest.main()
