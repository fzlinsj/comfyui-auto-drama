import unittest
from pathlib import Path


INDEX = Path(__file__).resolve().parents[1] / "index.html"


class EnvironmentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = INDEX.read_text(encoding="utf-8")

    def test_environment_settings_panel_contains_required_controls(self):
        for element_id in (
            "environmentPanel", "environmentPlatform", "environmentSshCommand",
            "environmentPassword", "btnEnvironmentScan", "btnEnvironmentRetrust", "environmentScanSummary",
            "environmentRecipe", "environmentPlanSummary", "btnEnvironmentDeploy",
            "environmentJobSteps", "btnEnvironmentRetry", "btnEnvironmentCancel",
            "environmentVerificationResults", "environmentManifest",
        ):
            self.assertIn(f'id="{element_id}"', self.source)

    def test_environment_settings_panel_contains_workflow_functions(self):
        for function_name in (
            "scanEnvironment", "loadEnvironmentPlan", "deployEnvironment",
            "pollEnvironmentJob", "retryEnvironmentStep", "cancelEnvironmentJob",
            "renderEnvironmentVerification",
        ):
            self.assertIn(f"function {function_name}", self.source)

    def test_environment_scan_only_exposes_command_and_password(self):
        self.assertIn('type="password"', self.source)
        self.assertIn('id="environmentPassword"', self.source)
        self.assertNotIn('id="environmentFingerprint"', self.source)
        self.assertNotIn('id="environmentConfirmFingerprint"', self.source)
        self.assertNotIn('id="environmentPrivateKey"', self.source)

    def test_environment_remembers_only_ssh_command(self):
        self.assertIn("toonflow.environment.sshCommand", self.source)
        self.assertIn("loadSavedEnvironmentSshCommand", self.source)
        self.assertIn("saveEnvironmentSshCommand", self.source)
        self.assertIn("persistEnvironmentSshCommand", self.source)
        self.assertIn("/api/environment/ssh-command", self.source)
        self.assertIn("localStorage.setItem", self.source)
        self.assertNotIn("localStorage.setItem('toonflow.environment.password'", self.source)
        self.assertNotIn("localStorage.setItem('toonflow.environment.privateKey'", self.source)

    def test_environment_controls_are_bound_and_recipe_loading_starts(self):
        for binding in (
            "$('btnEnvironmentScan').addEventListener('click', scanEnvironment)",
            "$('btnEnvironmentRetrust').addEventListener('click', retrustEnvironment)",
            "$('btnEnvironmentPlan').addEventListener('click', loadEnvironmentPlan)",
            "$('btnEnvironmentDeploy').addEventListener('click', deployEnvironment)",
            "$('btnEnvironmentRetry').addEventListener('click', retryEnvironmentStep)",
            "$('btnEnvironmentCancel').addEventListener('click', cancelEnvironmentJob)",
            "loadEnvironmentRecipes();",
        ):
            self.assertIn(binding, self.source)

    def test_prepared_without_gpu_keeps_retry_available_for_deferred_verification(self):
        self.assertIn("deferred.size", self.source)
        self.assertIn("terminal && !failed.size && !deferred.size", self.source)

    def test_retry_selector_is_limited_to_failed_or_deferred_steps(self):
        self.assertIn("retryableSteps", self.source)
        self.assertIn("failed.has(step) || deferred.has(step)", self.source)

    def test_environment_retrust_button_is_bound(self):
        self.assertIn("async function retrustEnvironment()", self.source)
        self.assertIn("scanEnvironment(true)", self.source)

    def test_environment_ui_exposes_installed_resource_reuse(self):
        self.assertIn("installedModels", self.source)
        self.assertIn("installedNodes", self.source)
        self.assertIn("reused_resources", self.source)
        self.assertIn("需要下载：", self.source)

    def test_environment_ui_explains_blocked_plan_controls(self):
        self.assertIn("当前没有创建部署任务", self.source)
        self.assertIn("重试步骤/取消任务", self.source)

    def test_environment_ui_renders_active_deployment_step(self):
        self.assertIn("active_step", self.source)
        self.assertIn("执行中", self.source)


if __name__ == "__main__":
    unittest.main()
