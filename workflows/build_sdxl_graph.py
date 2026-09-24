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


if __name__ == "__main__":
    print(json.dumps(build_sdxl_graph(), ensure_ascii=False, indent=2))
