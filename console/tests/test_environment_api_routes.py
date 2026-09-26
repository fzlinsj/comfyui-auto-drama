import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

import batch_console


class EnvironmentApiRouteTests(unittest.TestCase):
    def test_environment_routes_are_registered(self):
        source = Path(batch_console.__file__).read_text(encoding="utf-8")
        for route in (
            "/api/environments/scan",
            "/api/environments/plan",
            "/api/environments/deploy",
            "/api/environments/jobs/",
            "/api/environments/recipes",
            "/api/environments/manifest/",
            "/api/environment/ssh-command",
        ):
            self.assertIn(route, source)

    def test_deploy_route_requires_confirmation_error_code(self):
        source = Path(batch_console.__file__).read_text(encoding="utf-8")
        route = source.split('if path == "/api/environments/deploy":', 1)[1].split('if path.startswith("/api/environments/jobs/")', 1)[0]
        self.assertIn('bool(body.get("confirm"))', route)
        self.assertIn("error_code", route)

    def test_environment_api_never_returns_credentials(self):
        source = Path(batch_console.__file__).read_text(encoding="utf-8")
        self.assertIn("get_environment_manager", source)
        self.assertIn("redact_payload", Path(CONSOLE_DIR / "environment_manager.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
