import sys
import unittest
from pathlib import Path


CONSOLE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSOLE_DIR))

from environment_verifier import ComfyUIWorkflowVerifier


def model_values(graph, input_name):
    return [
        node.get("inputs", {}).get(input_name)
        for node in graph.values()
        if input_name in node.get("inputs", {})
    ]


class RecordingClient:
    def __init__(self, variants=False):
        self.variants = variants
        self.preflight_graphs = []
        self.object_info_calls = 0

    def preflight(self, graph):
        self.preflight_graphs.append(graph)
        if not self.variants:
            return {"ok": True, "missing_nodes": [], "missing_models": [], "warnings": []}
        wanted_unet = "minimax_h3_fl2va_pruned_fp8_scaled.safetensors"
        wanted_clip = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"
        ok = wanted_unet in model_values(graph, "unet_name") and wanted_clip in model_values(graph, "clip_name")
        return {
            "ok": ok,
            "missing_nodes": [],
            "missing_models": [] if ok else ["configured H3 variants"],
            "warnings": [],
        }

    def object_info(self):
        self.object_info_calls += 1
        return {
            "UNETLoader": {"input": {"required": {"unet_name": [[
                "minimax_h3_fl2va_pruned_fp8_scaled.safetensors"
            ]]}}},
            "CLIPLoader": {"input": {"required": {"clip_name": [[
                "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"
            ]]}}},
        }


class ComfyUIWorkflowVerifierTests(unittest.TestCase):
    def test_all_deployment_services_run_real_comfyui_preflight(self):
        client = RecordingClient()
        verifier = ComfyUIWorkflowVerifier(
            "http://127.0.0.1:6006",
            client_factory=lambda server: client,
        )

        for service in ("sdxl", "t2v", "i2v", "r2v"):
            with self.subTest(service=service):
                result = verifier(service, {})
                self.assertTrue(result["ok"])

        self.assertEqual(len(client.preflight_graphs), 4)
        self.assertTrue(all(graph for graph in client.preflight_graphs))

    def test_r2v_retries_preflight_with_advertised_compatible_h3_variants(self):
        client = RecordingClient(variants=True)
        verifier = ComfyUIWorkflowVerifier(
            "http://127.0.0.1:6006",
            client_factory=lambda server: client,
        )

        result = verifier("r2v", {})

        self.assertTrue(result["ok"])
        self.assertEqual(client.object_info_calls, 1)
        self.assertEqual(len(client.preflight_graphs), 2)
        final_graph = client.preflight_graphs[-1]
        self.assertIn("minimax_h3_fl2va_pruned_fp8_scaled.safetensors", model_values(final_graph, "unet_name"))
        self.assertIn("qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors", model_values(final_graph, "clip_name"))
        self.assertEqual(result["compatible_models"]["unet_name"], "minimax_h3_fl2va_pruned_fp8_scaled.safetensors")
        self.assertEqual(result["compatible_models"]["clip_name"], "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors")


if __name__ == "__main__":
    unittest.main()
