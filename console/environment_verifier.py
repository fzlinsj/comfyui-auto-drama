"""ComfyUI workflow verification used by the environment deployment gate."""

from __future__ import annotations

try:
    from .comfyui_client import ComfyUIClient
except ImportError:
    from comfyui_client import ComfyUIClient

from workflows.build_api_graphs import build_i2v, build_r2v, convert_t2v
from workflows.build_sdxl_graph import build_sdxl_graph


MODEL_INPUTS = {"ckpt_name", "unet_name", "clip_name", "vae_name", "lora_name"}


def _model_options(available, class_type, input_name):
    required = (((available.get(class_type) or {}).get("input") or {}).get("required") or {})
    options = required.get(input_name) or []
    if isinstance(options, (list, tuple)) and options and isinstance(options[0], (list, tuple)):
        options = options[0]
    return [str(item) for item in options] if isinstance(options, (list, tuple)) else []


def _compatibility_rank(expected, candidate):
    expected = str(expected or "").lower()
    candidate = str(candidate or "").lower()
    if expected == candidate:
        return 0
    if "minimax_h3_ref2va_" in expected:
        if "minimax_h3_ref2va_" in candidate:
            return 1
        if "minimax_h3_fl2va_" in candidate:
            return 2
        return None
    if "minimax_h3_fl2va_" in expected:
        return 1 if "minimax_h3_fl2va_" in candidate else None
    if expected.startswith("minimax_h3_turbo_v4_step600_ema"):
        return 1 if candidate.startswith("minimax_h3_turbo_v4_step600_ema") else None
    if "qwen3vl_32b" in expected:
        if "qwen3vl_32b" not in candidate:
            return None
        return 1 if "minimax_h3" in candidate or "heretic" in candidate else 2
    if expected.startswith("sd_xl_base_1.0"):
        return 1 if candidate.startswith("sd_xl_base_1.0") else None
    return None


def _compatible_model(expected, options):
    ranked = []
    for option in options:
        rank = _compatibility_rank(expected, option)
        if rank is not None:
            ranked.append((rank, option.lower(), option))
    return min(ranked)[2] if ranked else None


def _apply_compatible_models(graph, available):
    replacements = {}
    for node in (graph or {}).values():
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs") or {}
        for input_name in MODEL_INPUTS.intersection(inputs):
            expected = str(inputs.get(input_name) or "")
            options = _model_options(available, class_type, input_name)
            if not options or expected in options:
                continue
            replacement = _compatible_model(expected, options)
            if replacement:
                inputs[input_name] = replacement
                replacements[input_name] = replacement
    return replacements


class ComfyUIWorkflowVerifier:
    """Build production workflow graphs and preflight them against ComfyUI."""

    def __init__(self, server, client_factory=None):
        self.server = str(server or "").rstrip("/")
        self.client_factory = client_factory or (lambda endpoint: ComfyUIClient(endpoint))

    @staticmethod
    def _graph(service):
        task = {
            "prompt": "A neutral environment verification test",
            "duration": 2,
            "seed": 12345,
            "steps": 4,
            "mp": 0.2,
            "prefix": "diagnostics/environment",
            "image": "diagnostic_reference.png",
            "images": ["diagnostic_reference.png"],
            "story_image": "diagnostic_reference.png",
        }
        if service == "sdxl":
            return build_sdxl_graph({
                "prompt": task["prompt"],
                "width": 768,
                "height": 768,
                "steps": 4,
                "filename_prefix": task["prefix"],
            })
        if service == "t2v":
            return convert_t2v(dict(task, mode="t2v"))
        if service == "i2v":
            return build_i2v(dict(task, mode="i2v"))
        if service == "r2v":
            return build_r2v(dict(task, mode="r2v"))
        raise ValueError("unsupported environment verification service: " + str(service))

    def __call__(self, service, plan):
        del plan
        client = self.client_factory(self.server)
        graph = self._graph(service)
        result = dict(client.preflight(graph) or {})
        replacements = {}
        if not result.get("ok"):
            replacements = _apply_compatible_models(graph, client.object_info() or {})
            if replacements:
                result = dict(client.preflight(graph) or {})
        result["service"] = service
        if replacements:
            result["compatible_models"] = replacements
            warnings = list(result.get("warnings") or [])
            warnings.append("已使用 ComfyUI 已加载的兼容 H3 模型变体进行验证")
            result["warnings"] = warnings
        return result
