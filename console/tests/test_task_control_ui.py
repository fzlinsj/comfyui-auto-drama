import re
import unittest
from pathlib import Path


INDEX = Path(__file__).resolve().parents[1] / "index.html"


class TaskControlUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = INDEX.read_text(encoding="utf-8")

    def test_required_task_control_ids_exist(self):
        required = [
            "taskServerSummary", "taskStatusFilter", "taskControlList",
            "btnCancelBatch", "taskDetailModalBg", "taskFailureDetail",
            "taskRetryMp", "taskRetrySteps", "taskRetryDuration",
            "taskRetryChain", "taskRetryPredecessor", "btnTaskRetrySubmit",
        ]
        for item in required:
            self.assertIn(f'id="{item}"', self.source)

    def test_required_task_control_functions_exist(self):
        required = [
            "loadTaskControl", "renderTaskControl", "openTaskAttempt",
            "preflightTaskAttempt", "retryTaskAttempt", "cancelTaskAttempt",
            "cancelCurrentBatch", "resolveBlockedChain",
        ]
        for item in required:
            self.assertRegex(self.source, rf"function\s+{item}\s*\(")

    def test_confirmation_and_predecessor_history_are_handled(self):
        self.assertIn("d.confirmation_required", self.source)
        self.assertRegex(self.source, r"group\.history\s*\|\|\s*\[\]")

    def test_task_control_user_text_is_chinese(self):
        required_text = [
            "任务控制中心",
            "查看每个分段的尝试记录、失败详情、重试设置、取消操作和链式依赖。",
            "全部状态",
            "刷新任务控制中心",
            "取消当前批次",
            "详情",
            "预检",
            "提交",
            "重新生成本段",
            "运行预检",
            "解析链式依赖",
            "关闭",
            "创建重试任务",
        ]
        for text in required_text:
            self.assertIn(text, self.source)

    def test_task_control_handles_non_json_responses(self):
        self.assertIn("response.text()", self.source)
        self.assertIn("JSON.parse", self.source)
        self.assertIn("任务控制接口未找到，请重启控制台服务", self.source)


if __name__ == "__main__":
    unittest.main()
