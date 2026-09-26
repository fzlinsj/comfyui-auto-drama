import sys
import tempfile
import time
import unittest
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from service_diagnostics import ServiceDiagnostics, _HttpAdapter
from task_store import TaskStore


class FakeComfy:
    def __init__(self):
        self.submit_calls = []
        self.history_calls = []

    def profile(self):
        return {"gpu_name": "NVIDIA GeForce RTX 3090", "comfyui_version": "0.3"}

    def queue(self):
        return {"queue_running": [], "queue_pending": []}

    def object_info(self):
        return {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["test.safetensors"]]}}}}

    def preflight(self, graph):
        return {"ok": True, "missing_nodes": [], "missing_models": [], "warnings": []}

    def submit(self, graph, client_id="diagnostics"):
        self.submit_calls.append((graph, client_id))
        return {"prompt_id": "diagnostic-prompt"}

    def history(self, prompt_id=None):
        self.history_calls.append(prompt_id)
        return {prompt_id: {"status": {"completed": True}, "outputs": {"7": {"images": [{"filename": "diagnostic.png", "subfolder": "", "type": "output"}]}}}}

    def download_output(self, output_meta, destination):
        Path(destination).write_bytes(b"diagnostic image")
        return destination

    def upload_image(self, local_path, filename=None):
        self.uploaded_image = (Path(local_path).read_bytes(), filename)
        return {"name": filename or "diagnostic.png", "subfolder": "", "type": "input"}


class FakeImage:
    def __init__(self):
        self.generate_calls = []

    def quick_check(self):
        return {"status": "needs_real_test", "summary": "需要真实测试"}

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return {"filename": "diagnostic.png", "validated": True}


class FakeLLM:
    def __init__(self):
        self.chat_calls = []

    def quick_check(self):
        return {"status": "needs_real_test", "summary": "需要真实测试"}

    def chat(self, **kwargs):
        self.chat_calls.append(kwargs)
        return {"ok": True, "service": "llm"}


class ServiceDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(str(Path(self.temp_dir.name) / "diagnostics.db"))
        self.comfy = FakeComfy()
        self.image = FakeImage()
        self.llm = FakeLLM()
        self.diagnostics = ServiceDiagnostics(
            store=self.store,
            config={"comfyui": {"server": "http://comfy"}},
            adapters={"comfyui": self.comfy, "agnes": self.image, "llm": self.llm},
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_quick_check_never_calls_generation(self):
        results = self.diagnostics.quick_check_all()
        self.assertEqual(self.image.generate_calls, [])
        self.assertEqual(self.comfy.submit_calls, [])
        self.assertEqual(results["comfyui_t2v"]["level"], "quick")

    def test_provider_without_free_probe_requires_real_test(self):
        result = self.diagnostics.quick_check_service("agnes")
        self.assertEqual(result["status"], "needs_real_test")

    def test_http_adapter_supports_interactive_messages(self):
        adapter = _HttpAdapter("https://example.test/v1", model="deepseek-chat")
        captured = {}

        def fake_request(path, payload=None, timeout=30):
            captured["path"] = path
            captured["payload"] = payload
            return {"choices": [{"message": {"content": "你好，我是测试助手"}}]}

        adapter._request = fake_request
        result = adapter.chat(
            messages=[{"role": "user", "content": "你好"}],
            interactive=True,
        )
        self.assertEqual(captured["path"], "/chat/completions")
        self.assertEqual(captured["payload"]["messages"][0]["content"], "你好")
        self.assertEqual(result["response"], "你好，我是测试助手")

    def test_http_image_adapter_uses_custom_diagnostic_prompt(self):
        adapter = _HttpAdapter("https://example.test/v1", model="agnes-image-2.5-flash")
        captured = {}

        def fake_request(path, payload=None, timeout=30):
            captured["path"] = path
            captured["payload"] = payload
            return {"data": [{"url": "https://example.test/result.png"}]}

        adapter._request = fake_request
        result = adapter.generate(parameters={"prompt": "雨夜霓虹街道，一辆红色跑车"})

        self.assertEqual(captured["path"], "/images/generations")
        self.assertEqual(captured["payload"]["prompt"], "雨夜霓虹街道，一辆红色跑车")
        self.assertEqual(result["url"], "https://example.test/result.png")

    def test_http_adapter_quick_check_exposes_safe_failure_details(self):
        adapter = _HttpAdapter("https://example.test/v1", api_key="secret-token", model="deepseek-chat")
        adapter._request = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("401 secret-token"))
        result = adapter.quick_check()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["details"]["check"], "GET /models")
        self.assertIn("401", result["details"]["error"])
        self.assertNotIn("secret-token", result["details"]["error"])

    def test_local_image_configuration_installs_boogu_adapter(self):
        diagnostics = ServiceDiagnostics(
            store=self.store,
            config={"image_gen": {"provider": "local", "local": {"url": "http://127.0.0.1:8081"}}},
            adapters={"comfyui": self.comfy},
        )
        self.assertEqual(diagnostics.adapters["boogu"].endpoint, "http://127.0.0.1:8081")

    def test_comfyui_image_provider_uses_comfyui_workflow(self):
        diagnostics = ServiceDiagnostics(
            store=self.store,
            config={"comfyui": {"server": "http://comfy"}, "image_gen": {"provider": "comfyui"}},
            adapters={"comfyui": self.comfy},
            output_dir=self.temp_dir.name,
        )
        self.assertIs(diagnostics.adapters["image"], diagnostics.adapters["comfyui_image"])

    def test_real_test_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirm_cost"):
            self.diagnostics.start_real_test("agnes", confirm_cost=False)

    def test_t2v_success_does_not_mark_i2v_or_r2v_available(self):
        self.diagnostics.finish_real_test("comfyui_t2v", output={"filename": "t2v.mp4"})
        summary = self.diagnostics.summary()
        self.assertEqual(summary["comfyui_t2v"]["status"], "available")
        self.assertNotEqual(summary["comfyui_i2v"]["status"], "available")
        self.assertNotEqual(summary["comfyui_r2v"]["status"], "available")

    def test_async_real_test_is_persisted_and_can_be_polled(self):
        result = self.diagnostics.start_real_test("llm", confirm_cost=True)
        self.assertIn("run_id", result)
        for _ in range(20):
            current = self.diagnostics.poll(result["run_id"])
            if current["status"] != "running":
                break
            time.sleep(0.01)
        self.assertEqual(current["status"], "succeeded")
        self.assertEqual(current["result"], {"ok": True, "service": "llm"})

    def test_comfyui_image_real_test_submits_and_downloads_a_validated_workflow(self):
        diagnostics = ServiceDiagnostics(
            store=self.store,
            config={"comfyui": {"server": "http://comfy"}},
            adapters={"comfyui": self.comfy},
            output_dir=self.temp_dir.name,
        )
        run = diagnostics.start_real_test(
            "comfyui_image",
            confirm_gpu=True,
            parameters={"prompt": "电影感雪山日出，金色云海"},
        )
        for _ in range(100):
            result = diagnostics.poll(run["run_id"])
            if result["status"] != "running":
                break
            time.sleep(0.01)
        self.assertEqual(result["status"], "succeeded")
        graph, client_id = self.comfy.submit_calls[0]
        self.assertEqual(client_id, "diagnostics")
        self.assertTrue(graph)
        self.assertTrue(all("class_type" in node and "inputs" in node for node in graph.values()))
        self.assertNotIn("diagnostic_service", graph)
        encoded_text = [node["inputs"].get("text") for node in graph.values() if node["class_type"] == "CLIPTextEncode"]
        self.assertIn("电影感雪山日出，金色云海", encoded_text)
        self.assertEqual(self.comfy.history_calls, ["diagnostic-prompt"])
        self.assertTrue(Path(result["result"]["filename"]).is_file())

    def test_i2v_and_r2v_real_tests_upload_a_generated_reference_image(self):
        for service in ("comfyui_i2v", "comfyui_r2v"):
            with self.subTest(service=service):
                self.comfy.submit_calls.clear()
                self.comfy.history_calls.clear()
                diagnostics = ServiceDiagnostics(
                    store=self.store,
                    config={"comfyui": {"server": "http://comfy"}},
                    adapters={"comfyui": self.comfy},
                    output_dir=self.temp_dir.name,
                )
                run = diagnostics.start_real_test(service, confirm_gpu=True)
                for _ in range(100):
                    result = diagnostics.poll(run["run_id"])
                    if result["status"] != "running":
                        break
                    time.sleep(0.01)
                self.assertEqual(result["status"], "succeeded", result.get("failure"))
                graph, _ = self.comfy.submit_calls[0]
                load_images = [node["inputs"]["image"] for node in graph.values() if node["class_type"] == "LoadImage"]
                self.assertTrue(load_images)
                self.assertIn(self.comfy.uploaded_image[1], load_images)

    def test_failure_details_are_redacted(self):
        diagnostics = ServiceDiagnostics(
            store=self.store,
            config={"llm": {"cloud": {"api_key": "secret-token"}}},
        )
        diagnostics.finish_real_test(
            "llm", failure={"code": "F-X", "raw_error": "api_key=secret-token"}
        )
        failure = diagnostics.summary()["llm"]["failure"]
        self.assertNotIn("secret-token", str(failure))


if __name__ == "__main__":
    unittest.main()
