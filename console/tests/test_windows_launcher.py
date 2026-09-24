import unittest
from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[2] / "scripts" / "start_windows.bat"


class WindowsLauncherTests(unittest.TestCase):
    def test_launcher_clears_only_the_console_port_before_starting(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("Get-NetTCPConnection", source)
        self.assertIn(":8890", source)
        self.assertIn("Stop-Process -Id", source)
        self.assertIn("python batch_console.py 8890", source)


if __name__ == "__main__":
    unittest.main()
