import re
import unittest
from pathlib import Path


class RegenerateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parents[1] / "index.html").read_text(encoding="utf-8")

    def test_successful_regeneration_opens_status_page_from_first_page(self):
        body = self.source.split("async function regenSubmit()", 1)[1]
        body = body.split("async function deleteAssembled", 1)[0]
        self.assertRegex(body, r"statusPage\s*=\s*0")
        self.assertRegex(body, r"goStep\(7\)")


if __name__ == "__main__":
    unittest.main()
