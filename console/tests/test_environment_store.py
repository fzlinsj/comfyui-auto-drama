import sys
import tempfile
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from task_store import TaskStore


class EnvironmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(str(Path(self.temp_dir.name) / "environment.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_store_round_trip_does_not_have_credential_columns(self):
        columns = self.store.table_columns("environment_targets")
        self.assertNotIn("password", columns)
        self.assertNotIn("private_key", columns)

    def test_environment_target_scan_plan_and_steps_round_trip(self):
        target_id = self.store.create_environment_target(
            platform="autodl", host="gpu.example", username="root", port=18078,
            credential_ref="session-1", fingerprint="SHA256:abc"
        )
        scan_id = self.store.save_environment_scan(
            target_id, {"has_gpu": False, "environment_kind": "clean_system"}
        )
        plan_id = self.store.save_deployment_plan(
            target_id, scan_id, "minimax-h3-sdxl", "1.0.0", {"status": "ready"}
        )
        self.store.upsert_deployment_step(plan_id, "scan", "succeeded", {"message": "ok"})
        job = self.store.get_environment_job(plan_id)
        self.assertEqual(job["target"]["platform"], "autodl")
        self.assertEqual(job["scan"]["summary"]["environment_kind"], "clean_system")
        self.assertEqual(job["plan"]["estimate"]["status"], "ready")
        self.assertEqual(job["steps"][0]["step_name"], "scan")

    def test_environment_scan_and_plan_can_be_loaded_individually(self):
        target_id = self.store.create_environment_target("autodl", "gpu.example")
        scan_id = self.store.save_environment_scan(target_id, {"has_gpu": True})
        plan_id = self.store.save_deployment_plan(target_id, scan_id, "minimax-h3-sdxl", "1.0.0", {"status": "ready"})
        scan = self.store.get_environment_scan(scan_id)
        plan = self.store.get_deployment_plan(plan_id)
        self.assertEqual(scan["summary"]["has_gpu"], True)
        self.assertEqual(plan["recipe_version"], "1.0.0")

    def test_find_target_and_update_fingerprint_round_trip(self):
        target_id = self.store.create_environment_target(
            "autodl", "gpu.example", username="root", port=18078,
            fingerprint="SHA256:old", credential_ref="session-1",
        )
        target = self.store.find_environment_target("autodl", "gpu.example", "root", 18078)
        self.assertEqual(target["target_id"], target_id)
        self.store.update_environment_target_fingerprint(target_id, "SHA256:new")
        refreshed = self.store.find_environment_target("autodl", "gpu.example", "root", 18078)
        self.assertEqual(refreshed["fingerprint"], "SHA256:new")


if __name__ == "__main__":
    unittest.main()
