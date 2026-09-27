import unittest
from pathlib import Path


HTML = Path(__file__).resolve().parents[1] / "index.html"


class RealisticDramaPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HTML.read_text(encoding="utf-8")

    def test_role_type_classifier_includes_real_animals(self):
        self.assertIn("function inferRoleType", self.source)
        self.assertIn("公鸡", self.source)
        self.assertIn("animal", self.source)

    def test_role_prompt_has_separate_animal_template(self):
        self.assertIn("真实动物摄影", self.source)
        self.assertIn("不得出现人脸或人体", self.source)

    def test_role_prompt_removes_ambiguous_gender_fallback(self):
        self.assertNotIn("根据名字与描述判断性别", self.source)
        self.assertNotIn("gender according to the description", self.source)

    def test_story_prompt_does_not_require_human_limbs_for_animals(self):
        self.assertIn("动物保持真实物种", self.source)
        self.assertNotIn("每人四肢完整各两只手", self.source)


if __name__ == "__main__":
    unittest.main()
