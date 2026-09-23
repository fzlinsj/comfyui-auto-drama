import json
import sys
import unittest
from pathlib import Path


CONSOLE_DIR = Path(__file__).resolve().parents[1]
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

import batch_console as bc


SCRIPT_JSON = {
    "title": "雨夜加班",
    "logline": "两人在雨夜确认心意",
    "role_list": [
        {"role_name": "苏晚", "role_desc": "年轻女职员，白衬衫"},
    ],
    "storyboard_list": [
        {
            "id": 7,
            "scene": "办公室",
            "roles": ["苏晚"],
            "action": "苏晚合上文件夹",
            "dialogue": "下班吧。",
            "emotion": "克制",
            "camera": "缓慢推近",
            "duration": 8,
        }
    ],
}


class ScriptImportTests(unittest.TestCase):
    def test_parse_script_json_preserves_table_fields(self):
        rows, meta = bc.parse_script_json(json.dumps(SCRIPT_JSON, ensure_ascii=False))

        self.assertEqual(len(rows), 1)
        script = meta["script"]
        self.assertEqual(script["title"], "雨夜加班")
        self.assertEqual(script["logline"], "两人在雨夜确认心意")
        self.assertEqual(script["role_list"][0]["role_name"], "苏晚")
        self.assertEqual(
            script["storyboard_list"][0],
            {
                "id": 7,
                "scene": "办公室",
                "roles": ["苏晚"],
                "action": "苏晚合上文件夹",
                "dialogue": "下班吧。",
                "emotion": "克制",
                "camera": "缓慢推近",
                "duration": 8,
            },
        )

    def test_import_script_payload_returns_script_and_tasks(self):
        payload = bc.import_script_payload(json.dumps(SCRIPT_JSON, ensure_ascii=False))

        self.assertIn("script", payload)
        self.assertIn("tasks", payload)
        self.assertEqual(payload["script"]["storyboard_list"][0]["scene"], "办公室")
        self.assertEqual(payload["tasks"][0]["duration"], 8)
        self.assertTrue(payload["tasks"][0]["prompt"])

    def test_import_script_payload_normalizes_segment_aliases(self):
        payload = bc.import_script_payload(json.dumps({
            "name": "别名格式",
            "characters": [{"name": "林深", "description": "男上司"}],
            "segments": [{
                "index": 3,
                "location": "走廊",
                "characters": ["林深"],
                "motion": "抬头",
                "line": "等等。",
                "mood": "急切",
                "camera_move": "固定中景",
                "seconds": 6,
            }],
        }, ensure_ascii=False))

        scene = payload["script"]["storyboard_list"][0]
        self.assertEqual(payload["script"]["title"], "别名格式")
        self.assertEqual(payload["script"]["role_list"][0]["role_name"], "林深")
        self.assertEqual(scene["scene"], "走廊")
        self.assertEqual(scene["roles"], ["林深"])
        self.assertEqual(scene["action"], "抬头")
        self.assertEqual(scene["dialogue"], "等等。")
        self.assertEqual(scene["emotion"], "急切")
        self.assertEqual(scene["camera"], "固定中景")
        self.assertEqual(scene["duration"], 6)


if __name__ == "__main__":
    unittest.main()
