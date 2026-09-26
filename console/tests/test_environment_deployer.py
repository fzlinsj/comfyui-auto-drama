import sys
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_deployer import EnvironmentDeployer
from environment_models import EnvironmentError


class FakeDownloader:
    def __init__(self):
        self.download_calls = []

    def download(self, resource, cancel=None):
        self.download_calls.append(resource["filename"])
        return type("DownloadResult", (), {"status": "downloaded", "target": resource["filename"]})()


class EnvironmentDeployerTests(unittest.TestCase):
    def setUp(self):
        self.downloader = FakeDownloader()
        self.deployer = EnvironmentDeployer(downloader=self.downloader)
        self.plan = {
            "plan_id": "p1",
            "download_tasks": [{"filename": "models/a.safetensors", "sha256": "a" * 64, "size_bytes": 1}],
            "status": "plan_ready",
        }

    def test_cpu_only_steps_finish_without_gpu(self):
        job = self.deployer.run(self.plan, has_gpu=False)
        self.assertEqual(job.status, "prepared_waiting_gpu")
        self.assertEqual(job.completed_steps[-1], "manifest")

    def test_gpu_required_step_is_deferred_without_gpu(self):
        job = self.deployer.run(self.plan, has_gpu=False)
        self.assertEqual(job.deferred_steps, ["verify_sdxl", "verify_t2v", "verify_i2v", "verify_r2v"])

    def test_gpu_validation_requires_all_four_outputs(self):
        result = self.deployer.finalize_verification({"sdxl": True, "t2v": True, "i2v": True, "r2v": False})
        self.assertEqual(result.status, "failed")
        self.assertNotEqual(result.status, "available")

    def test_retry_skips_verified_download(self):
        first = self.deployer.run(self.plan, has_gpu=False)
        self.assertEqual(self.downloader.download_calls, ["models/a.safetensors"])
        self.deployer.retry_step("download_models")
        self.assertEqual(self.downloader.download_calls, ["models/a.safetensors"])
        self.assertIn("download_models", first.completed_steps)

    def test_retry_deferred_gpu_step_updates_job_progress(self):
        deployer = EnvironmentDeployer(downloader=self.downloader, verifier=lambda service, plan: True)
        first = deployer.run(self.plan, has_gpu=False)
        self.assertIn("verify_sdxl", first.deferred_steps)

        retried = deployer.retry_step("verify_sdxl")

        self.assertIn("verify_sdxl", retried.completed_steps)
        self.assertNotIn("verify_sdxl", retried.deferred_steps)
        self.assertEqual(retried.status, "verifying")

    def test_progress_callback_publishes_each_completed_step(self):
        snapshots = []
        deployer = EnvironmentDeployer(
            downloader=self.downloader,
            progress_callback=lambda job: snapshots.append(job.to_dict()),
        )
        deployer.run(self.plan, has_gpu=False)
        completed_counts = [len(item["completed_steps"]) for item in snapshots]
        self.assertIn(1, completed_counts)
        self.assertTrue(any("scan" in item["completed_steps"] for item in snapshots))
        self.assertEqual(snapshots[-1]["status"], "prepared_waiting_gpu")

    def test_progress_snapshot_identifies_active_step(self):
        snapshots = []
        deployer = EnvironmentDeployer(
            downloader=self.downloader,
            progress_callback=lambda job: snapshots.append(job.to_dict()),
        )
        deployer.run(self.plan, has_gpu=False)
        self.assertTrue(any(item.get("active_step") == "download_models" for item in snapshots))

    def test_download_failure_keeps_source_details_in_job_messages(self):
        class FailingDownloader:
            def download(self, resource, cancel=None):
                raise EnvironmentError(
                    "所有下载源均失败", "E-DOWNLOAD", {"sources": ["https://example.invalid: timeout"]}
                )

        deployer = EnvironmentDeployer(downloader=FailingDownloader())
        job = deployer.run(self.plan, has_gpu=False)
        self.assertEqual(job.status, "failed")
        self.assertTrue(any("example.invalid" in message for message in job.messages))


if __name__ == "__main__":
    unittest.main()
