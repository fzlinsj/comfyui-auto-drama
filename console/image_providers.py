"""Image provider selection with explicit, single-provider execution."""

import base64
import json
import os
import re
import time
import urllib.request


DEFAULTS = {
    "active_provider": "boogu",
    "boogu": {"url": "http://127.0.0.1:8081"},
    "agnes": {
        "base_url": "https://apihub.agnes-ai.com/v1",
        "api_key": "",
        "model": "agnes-image-2.5-flash",
    },
    "openai": {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-image-1"},
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com", "api_key": "", "model": "wanx-v1"},
    "comfyui": {
        "server": "inherit",
        "checkpoint": "sd_xl_base_1.0.safetensors",
        "steps": 20,
        "cfg": 7.0,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
    },
}


def _merged(base, extra):
    result = dict(base or {})
    result.update(extra or {})
    return result


def normalize_image_provider(config=None):
    """Normalize both the current provider layout and legacy local/cloud fields."""
    config = dict(config or {})
    normalized = {name: dict(value) if isinstance(value, dict) else value for name, value in DEFAULTS.items()}
    for name in ("boogu", "agnes", "openai", "dashscope", "comfyui"):
        normalized[name] = _merged(DEFAULTS[name], config.get(name) if isinstance(config.get(name), dict) else {})

    active = str(config.get("active_provider") or "").strip().lower()
    if not active:
        legacy_provider = str(config.get("provider") or "local").strip().lower()
        legacy_type = str(config.get("provider_type") or "openai").strip().lower()
        active = "boogu" if legacy_provider == "local" else legacy_type
        local = config.get("local") if isinstance(config.get("local"), dict) else {}
        cloud = config.get("cloud") if isinstance(config.get("cloud"), dict) else {}
        if local:
            normalized["boogu"] = _merged(normalized["boogu"], local)
        if cloud and active in {"agnes", "openai", "dashscope"}:
            legacy_cloud = dict(cloud)
            if "base_url" not in legacy_cloud and legacy_cloud.get("url"):
                legacy_cloud["base_url"] = legacy_cloud["url"]
            normalized[active] = _merged(normalized[active], legacy_cloud)
    if active not in {"boogu", "agnes", "openai", "dashscope", "comfyui"}:
        raise ValueError(f"不支持的生图供应商：{active}")
    normalized["active_provider"] = active
    return normalized


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _v1(url):
    value = str(url or "").rstrip("/")
    return value if value.endswith("/v1") else value + "/v1"


def _headers(api_key=""):
    headers = {"Content-Type": "application/json", "User-Agent": "batch-console"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _size_ratio(size):
    value = str(size or "").strip().upper()
    match = re.match(r"^(\d+)\s*[Xx]\s*(\d+)$", value)
    if not match:
        return "2K", "1:1"
    width, height = int(match.group(1)), int(match.group(2))
    if width == height:
        ratio = "1:1"
    elif width / max(1, height) >= 1.5:
        ratio = "16:9"
    elif width > height:
        ratio = "4:3"
    else:
        ratio = "3:4"
    return "2K", ratio


def _read_image_item(item, timeout):
    encoded = item.get("b64_json") or item.get("b64")
    if encoded:
        return base64.b64decode(encoded)
    url = item.get("url") or item.get("image_url")
    if not url:
        raise RuntimeError("供应商响应中没有图片 URL 或 base64 数据")
    with _opener().open(url, timeout=timeout) as response:
        return response.read()


def _save_result(raw, request, provider):
    output_dir = str(request.get("output_dir") or "")
    filename = os.path.basename(str(request.get("filename") or "image.png"))
    if not output_dir:
        raise ValueError("生图请求缺少 output_dir")
    os.makedirs(output_dir, exist_ok=True)
    destination = os.path.join(output_dir, filename)
    temporary = destination + ".part"
    with open(temporary, "wb") as handle:
        handle.write(raw)
    os.replace(temporary, destination)
    return {"filename": filename, "path": destination, "provider": provider}


def _post_json(url, payload, api_key, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(api_key),
    )
    with _opener().open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _generate_openai(request):
    cfg = request["provider_config"]
    payload = {
        "model": cfg.get("model") or "gpt-image-1",
        "prompt": request.get("prompt") or "",
        "n": 1,
        "size": request.get("size") or "768x1024",
        "response_format": "b64_json",
    }
    data = _post_json(_v1(cfg.get("base_url")) + "/images/generations", payload, cfg.get("api_key"), request.get("timeout", 300))
    raw = _read_image_item((data.get("data") or [{}])[0], request.get("timeout", 300))
    return _save_result(raw, request, "openai")


def _generate_agnes(request):
    cfg = request["provider_config"]
    quality, ratio = _size_ratio(request.get("size") or "768x1024")
    payload = {
        "model": cfg.get("model") or "agnes-image-2.5-flash",
        "prompt": request.get("prompt") or "",
        "size": quality,
        "ratio": ratio,
        "return_base64": True,
    }
    data = _post_json(_v1(cfg.get("base_url")) + "/images/generations", payload, cfg.get("api_key"), request.get("timeout", 300))
    raw = _read_image_item((data.get("data") or [{}])[0], request.get("timeout", 300))
    return _save_result(raw, request, "agnes")


def _generate_boogu(request):
    cfg = request["provider_config"]
    payload = {"model": cfg.get("model") or "boogu-image", "prompt": request.get("prompt") or "", "size": request.get("size") or "768x1024"}
    data = _post_json(_v1(cfg.get("url")) + "/images/generations", payload, cfg.get("api_key"), request.get("timeout", 300))
    raw = _read_image_item((data.get("data") or [{}])[0], request.get("timeout", 300))
    return _save_result(raw, request, "boogu")


def _generate_dashscope(request):
    cfg = request["provider_config"]
    root = str(cfg.get("base_url") or "").rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    payload = {
        "model": cfg.get("model") or "wanx-v1",
        "input": {"prompt": request.get("prompt") or ""},
        "parameters": {"size": request.get("size") or "768x1024", "n": 1},
    }
    task = _post_json(root + "/api/v1/services/aigc/multimodal-generation/generation", payload, cfg.get("api_key"), request.get("timeout", 300))
    task_id = (task.get("output") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("DashScope 未返回任务 ID")
    deadline = time.time() + min(int(request.get("timeout", 300)), 300)
    while time.time() < deadline:
        time.sleep(3)
        query = urllib.request.Request(root + f"/api/v1/tasks/{task_id}", headers=_headers(cfg.get("api_key")))
        with _opener().open(query, timeout=30) as response:
            status = json.loads(response.read().decode("utf-8"))
        output = status.get("output") or {}
        if output.get("task_status") == "SUCCEEDED":
            raw = _read_image_item((output.get("results") or [{}])[0], request.get("timeout", 300))
            return _save_result(raw, request, "dashscope")
        if output.get("task_status") in {"FAILED", "CANCELED"}:
            raise RuntimeError(f"DashScope 生图失败：{output}")
    raise TimeoutError("DashScope 生图任务超时")


def _comfyui_requires_async(_request):
    raise RuntimeError("ComfyUI 生图必须通过异步图片任务提交")


DEFAULT_ADAPTERS = {
    "agnes": _generate_agnes,
    "boogu": _generate_boogu,
    "openai": _generate_openai,
    "dashscope": _generate_dashscope,
    "comfyui": _comfyui_requires_async,
}


def generate_image(provider_name, request, adapters=None):
    """Call exactly one selected provider. Failures are returned to the caller unchanged."""
    provider_name = str(provider_name or "").strip().lower()
    registry = adapters or DEFAULT_ADAPTERS
    adapter = registry.get(provider_name)
    if not adapter:
        raise ValueError(f"不支持的生图供应商：{provider_name}")
    payload = dict(request or {})
    if "provider_config" not in payload:
        normalized = normalize_image_provider(payload.get("config") or {})
        payload["provider_config"] = normalized[provider_name]
    return adapter(payload)
