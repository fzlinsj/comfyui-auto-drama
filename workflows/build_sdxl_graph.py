"""Build the built-in standard-node SDXL ComfyUI API graph."""

import copy
import json
import os
import random


TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdxl_image_api_template.json")


def _node(graph, class_type):
    matches = [node for node in graph.values() if node.get("class_type") == class_type]
    if len(matches) != 1:
        raise ValueError(f"SDXL 模板中的 {class_type} 节点数量必须为 1")
    return matches[0]


def build_sdxl_graph(request=None):
    request = request or {}
    with open(TEMPLATE, "r", encoding="utf-8") as handle:
        graph = json.load(handle)
    graph = copy.deepcopy(graph)
    checkpoint = _node(graph, "CheckpointLoaderSimple")["inputs"]
    positive_nodes = [node for node in graph.values() if node.get("class_type") == "CLIPTextEncode"]
    if len(positive_nodes) != 2:
        raise ValueError("SDXL 模板必须包含正向和负向两个 CLIPTextEncode 节点")
    latent = _node(graph, "EmptyLatentImage")["inputs"]
    sampler = _node(graph, "KSampler")["inputs"]
    save = _node(graph, "SaveImage")["inputs"]

    checkpoint["ckpt_name"] = str(request.get("checkpoint") or "sd_xl_base_1.0.safetensors")
    positive_nodes[0]["inputs"]["text"] = str(request.get("prompt") or "")
    positive_nodes[1]["inputs"]["text"] = str(
        request.get("negative_prompt") or "text, watermark, logo, low quality, blurry"
    )
    latent["width"] = max(64, int(request.get("width") or 768))
    latent["height"] = max(64, int(request.get("height") or 1024))
    latent["batch_size"] = 1
    sampler["seed"] = int(request.get("seed") if request.get("seed") is not None else random.randrange(0, 2**63))
    sampler["steps"] = max(1, int(request.get("steps") or 20))
    sampler["cfg"] = float(request.get("cfg") or 7.0)
    sampler["sampler_name"] = str(request.get("sampler") or "dpmpp_2m")
    sampler["scheduler"] = str(request.get("scheduler") or "karras")
    sampler["denoise"] = float(request.get("denoise") or 1.0)
    save["filename_prefix"] = str(request.get("filename_prefix") or "assets/sdxl")
    return graph


def _input_spec(object_info, class_type):
    info = (object_info or {}).get(class_type) or {}
    inputs = info.get("input") or {}
    return inputs.get("required") or {}, inputs.get("optional") or {}


def _choices(spec):
    if isinstance(spec, (list, tuple)) and spec:
        values = spec[0]
        if isinstance(values, (list, tuple)):
            return [str(value) for value in values]
    return []


def _pick_preset(requested, choices):
    requested = str(requested or "").strip()
    if requested and (not choices or requested in choices):
        return requested
    if requested and choices:
        wanted = requested.replace("_", " ").lower()
        for choice in choices:
            normalized = choice.replace("_", " ").lower()
            if all(token in normalized for token in wanted.split()):
                return choice
        for choice in choices:
            if "plus" in choice.lower() and "face" in wanted:
                return choice
    return choices[0] if choices else requested or "PLUS_FACE"


def _set_if_required(inputs, required, name, value):
    if name in required:
        inputs[name] = value


def build_sdxl_identity_graph(request=None, object_info=None):
    """Build the SDXL graph with an IPAdapter identity anchor.

    The graph is assembled from the server's ``/object_info`` response because
    IPAdapter Plus node names and input sets differ between installations.
    A missing identity node is an explicit configuration error; silently
    falling back to text-only generation would produce unrelated characters.
    """
    request = dict(request or {})
    object_info = object_info or {}
    graph = build_sdxl_graph(request)
    unified = "IPAdapterUnifiedLoader" in object_info
    adapter_name = next(
        (name for name in ("IPAdapterAdvanced", "IPAdapter") if name in object_info),
        None,
    )
    model_loader = "IPAdapterModelLoader" in object_info
    if not adapter_name or not (unified or model_loader):
        available_identity_nodes = [
            name for name in object_info
            if "ipadapter" in str(name).lower() or name == "LoadImage"
        ]
        detected = ", ".join(sorted(available_identity_nodes)) or "无"
        raise RuntimeError(
            "未找到 IPAdapter Plus 身份节点；已检测到："
            f"{detected}。请安装/启用 IPAdapter Plus 后重启 ComfyUI"
        )

    next_id = max((int(key) for key in graph if str(key).isdigit()), default=0) + 1
    load_id, loader_id, adapter_id = (str(next_id), str(next_id + 1), str(next_id + 2))
    load_required, _ = _input_spec(object_info, "LoadImage")
    if "LoadImage" not in object_info or "image" not in load_required:
        raise RuntimeError("ComfyUI 缺少 LoadImage 节点，无法读取身份参考图")
    graph[load_id] = {"class_type": "LoadImage", "inputs": {"image": str(request["reference_image"])}}

    checkpoint_id = next(
        (str(node_id) for node_id, node in graph.items() if node.get("class_type") == "CheckpointLoaderSimple"),
        "1",
    )
    if unified:
        required, optional = _input_spec(object_info, "IPAdapterUnifiedLoader")
        loader_inputs = {"model": [checkpoint_id, 0]}
        _set_if_required(loader_inputs, required, "model", [checkpoint_id, 0])
        preset = _pick_preset(request.get("ipadapter_preset") or "PLUS_FACE", _choices(required.get("preset")))
        _set_if_required(loader_inputs, required, "preset", preset)
        if "preset" not in required and "preset" in optional:
            loader_inputs["preset"] = preset
        graph[loader_id] = {"class_type": "IPAdapterUnifiedLoader", "inputs": loader_inputs}
        model_ref = [loader_id, 0]
        ipadapter_ref = [loader_id, 1]
    else:
        required, optional = _input_spec(object_info, "IPAdapterModelLoader")
        model_inputs = {}
        model_choices = _choices(required.get("ipadapter_file"))
        model_name = str(request.get("ipadapter_model") or "").strip() or (model_choices[0] if model_choices else "")
        _set_if_required(model_inputs, required, "ipadapter_file", model_name)
        graph[loader_id] = {"class_type": "IPAdapterModelLoader", "inputs": model_inputs}
        model_ref = [checkpoint_id, 0]
        ipadapter_ref = [loader_id, 0]

    required, optional = _input_spec(object_info, adapter_name)
    adapter_inputs = {
        "model": model_ref,
        "ipadapter": ipadapter_ref,
        "image": [load_id, 0],
    }
    defaults = {
        "weight": float(request.get("ipadapter_weight") or 0.85),
        "weight_type": "standard",
        "combine_embeds": "concat",
        "start_at": 0.0,
        "end_at": 1.0,
        "embeds_scaling": "V only",
    }
    for name, value in defaults.items():
        _set_if_required(adapter_inputs, required, name, value)
        if name in optional:
            adapter_inputs.setdefault(name, value)
    graph[adapter_id] = {"class_type": adapter_name, "inputs": adapter_inputs}
    sampler = _node(graph, "KSampler")["inputs"]
    sampler["model"] = [adapter_id, 0]
    return graph


if __name__ == "__main__":
    print(json.dumps(build_sdxl_graph(), ensure_ascii=False, indent=2))
