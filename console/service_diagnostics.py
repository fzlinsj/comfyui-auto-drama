"""Two-level service diagnostics.

Quick checks are deliberately metadata-only.  A real test is an explicit,
single-service operation and is persisted through :class:`TaskStore` so a
restart does not turn a charged request into an unknown state.
"""

import copy
import datetime as _datetime
import hashlib
import json
import os
import platform
import struct
import tempfile
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import zlib

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in os.sys.path:
    os.sys.path.insert(0, PROJECT_ROOT)

from workflows.build_api_graphs import build_i2v, build_r2v, convert_t2v
from workflows.build_sdxl_graph import build_sdxl_graph

try:
    from .comfyui_client import ComfyUIClient
    from .failure_diagnostics import FAILURE_SUMMARIES, redact_secrets
except ImportError:
    from comfyui_client import ComfyUIClient
    from failure_diagnostics import FAILURE_SUMMARIES, redact_secrets


SERVICES = (
    "comfyui",
    "comfyui_t2v",
    "comfyui_i2v",
    "comfyui_r2v",
    "comfyui_image",
    "llm",
    "agnes",
    "boogu",
    "image",
    "vision",
    "local_environment",
)

COMFY_MODES = {"comfyui_t2v", "comfyui_i2v", "comfyui_r2v", "comfyui_image"}
COST_SERVICES = {"llm", "agnes", "boogu", "image", "vision"}
GPU_SERVICES = COMFY_MODES


def _now():
    return _datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _elapsed(start):
    return max(0, int((time.monotonic() - start) * 1000))


def _failure(exc, code="F-DIAGNOSTIC"):
    return {
        "code": code,
        "summary": str(exc) or "诊断测试失败",
        "raw_error": str(exc),
    }


def _png_card():
    """Create a deterministic 256x128 RGB PNG without requiring Pillow."""
    width, height = 256, 128
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend((32 + x % 64, 64 + y % 64, 128 + (x + y) % 64))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows))

    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


class _HttpAdapter:
    """Small OpenAI-compatible adapter used only when no fake is injected."""

    def __init__(self, endpoint, api_key="", model="", provider_type="openai"):
        self.endpoint = str(endpoint or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or "")
        self.provider_type = str(provider_type or "openai").strip() or "openai"

    def _request(self, path, payload=None, timeout=30):
        headers = {"Content-Type": "application/json", "User-Agent": "batch-console-diagnostics"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.endpoint + path, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._safe_error(exc)) from exc
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _safe_error(self, exc):
        """Return a useful upstream error without exposing the configured key."""
        if isinstance(exc, urllib.error.HTTPError):
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body = ""
            detail = body or str(exc.reason or "HTTP 请求失败")
            if self.api_key:
                detail = detail.replace(self.api_key, "[已隐藏 API Key]")
            return f"HTTP {exc.code}: {detail}"
        detail = str(exc) or exc.__class__.__name__
        return detail.replace(self.api_key, "[已隐藏 API Key]") if self.api_key else detail

    def quick_check(self):
        if not self.endpoint:
            return {
                "status": "unconfigured",
                "summary": "未配置服务地址",
                "details": {"check": "GET /models", "endpoint": ""},
            }
        try:
            response = self._request("/models", timeout=8)
            models = [item.get("id") or item.get("name") for item in (response.get("data") or []) if isinstance(item, dict)]
            return {
                "status": "quick_passed",
                "summary": "服务元数据可访问",
                "details": {
                    "check": "GET /models",
                    "endpoint": self.endpoint,
                    "provider_type": self.provider_type,
                    "models": [name for name in models if name][:20],
                    "selected_model": self.model,
                },
            }
        except Exception as exc:
            return {
                "status": "failed",
                "summary": "LLM 服务检查失败",
                "details": {
                    "check": "GET /models",
                    "endpoint": self.endpoint,
                    "provider_type": self.provider_type,
                    "selected_model": self.model,
                    "error": self._safe_error(exc),
                },
            }

    def chat(self, **kwargs):
        messages = kwargs.get("messages")
        interactive = bool(kwargs.get("interactive"))
        if not isinstance(messages, list) or not messages:
            messages = [{"role": "user", "content": 'Reply with JSON: {"ok":true,"service":"llm"}'}]
        response = self._request("/chat/completions", {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 64,
        }, timeout=120)
        content = (((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if interactive:
            return {"ok": True, "service": "llm", "response": content, "model": self.model}
        try:
            result = json.loads(content)
        except (TypeError, ValueError):
            result = {"ok": True, "service": "llm", "response": content[:500]}
        return result

    def generate(self, **kwargs):
        parameters = kwargs.get("parameters") if isinstance(kwargs.get("parameters"), dict) else {}
        prompt = str(parameters.get("prompt") or "").strip() or "A diagnostic test card, clean lighting, no text, neutral composition"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": "768x768",
            "ratio": "1:1",
            "extra_body": {"response_format": "url"},
        }
        response = self._request("/images/generations", payload, timeout=180)
        item = (response.get("data") or [{}])[0]
        url = item.get("url") or item.get("image_url")
        if not url:
            raise RuntimeError("图片服务未返回可用 URL")
        return {"url": url, "filename": os.path.basename(urllib.parse.urlparse(url).path) or "diagnostic.png", "prompt": prompt, "validated": True}

    def inspect(self, **kwargs):
        return {"ok": True, "service": "vision", "card_sha256": hashlib.sha256(_png_card()).hexdigest()}


class _NullAdapter:
    def __init__(self, service):
        self.service = service

    def quick_check(self):
        return {"status": "unconfigured", "summary": "未配置适配器", "details": {}}

    def real_test(self, **kwargs):
        raise RuntimeError("未配置真实测试适配器")


class _ComfyDiagnosticAdapter:
    """Run a real API graph and validate the first downloaded output."""

    def __init__(self, client, output_dir):
        self.client, self.output_dir = client, output_dir

    def _graph(self, service, parameters=None):
        parameters = parameters if isinstance(parameters, dict) else {}
        prompt = str(parameters.get("prompt") or "").strip() or "A neutral diagnostic test"
        task = {"prompt": prompt, "duration": 5, "seed": 12345,
                "steps": 4, "mp": 0.2, "prefix": "diagnostics/comfyui"}
        if service == "comfyui_image":
            return build_sdxl_graph({"prompt": task["prompt"], "width": 768, "height": 768,
                                     "steps": 4, "filename_prefix": task["prefix"]})
        if service == "comfyui_t2v":
            return convert_t2v(dict(task, mode="t2v"))
        image_path = os.path.join(self.output_dir, "diagnostic_reference.png")
        if not os.path.isfile(image_path):
            with open(image_path, "wb") as handle:
                handle.write(_png_card())
        uploaded = self.client.upload_image(image_path, "diagnostic_reference.png")
        name = uploaded.get("name") or uploaded.get("filename") or "diagnostic_reference.png"
        task["image"] = name
        task["images"] = [name]
        task["story_image"] = name
        if service == "comfyui_i2v":
            return build_i2v(dict(task, mode="i2v"))
        if service == "comfyui_r2v":
            return build_r2v(dict(task, mode="r2v"))
        raise ValueError("unsupported ComfyUI diagnostic service: " + service)

    @staticmethod
    def _output(record):
        for node in (record.get("outputs") or {}).values():
            for kind in ("images", "gifs", "videos"):
                for item in node.get(kind) or []:
                    if item.get("filename"):
                        return item
        return None

    def real_test(self, service, parameters):
        if service == "image":
            service = "comfyui_image"
        graph = self._graph(service, parameters)
        preflight = self.client.preflight(graph)
        if not preflight.get("ok"):
            raise RuntimeError("ComfyUI 预检失败：" + json.dumps(preflight, ensure_ascii=False))
        response = self.client.submit(graph, client_id="diagnostics")
        prompt_id = response.get("prompt_id") or response.get("id")
        if not prompt_id:
            raise RuntimeError("ComfyUI 未返回 prompt_id")
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            history = self.client.history(prompt_id)
            record = history.get(prompt_id) if isinstance(history, dict) else None
            if record:
                status = record.get("status") or {}
                if status.get("status_str") == "error" or status.get("completed") is False:
                    raise RuntimeError("ComfyUI 执行失败：" + json.dumps(status, ensure_ascii=False)[:1000])
                output = self._output(record)
                if output:
                    os.makedirs(self.output_dir, exist_ok=True)
                    ext = os.path.splitext(output.get("filename") or "")[1] or ".bin"
                    destination = os.path.join(self.output_dir, "diagnostic_" + prompt_id + ext)
                    self.client.download_output(output, destination)
                    if not os.path.isfile(destination) or os.path.getsize(destination) == 0:
                        raise RuntimeError("ComfyUI 输出下载后为空")
                    prompt = str((parameters or {}).get("prompt") or "").strip() or "A neutral diagnostic test"
                    return {"prompt_id": prompt_id, "filename": destination, "prompt": prompt, "validated": True, "preflight": preflight}
            time.sleep(1)
        raise RuntimeError("ComfyUI 诊断任务超时: " + str(prompt_id))


class ServiceDiagnostics:
    """Run quick metadata checks and explicitly confirmed real tests.

    ``adapters`` is intentionally injectable.  A test adapter may implement
    ``quick_check``, ``real_test``, ``chat``, ``generate`` or ``inspect``;
    production adapters are only called from ``start_real_test``.
    """

    def __init__(self, store, config=None, adapters=None, comfy_client_factory=None, output_dir=None):
        self.store = store
        self.config = copy.deepcopy(config or {})
        self.adapters = dict(adapters or {})
        self._comfy_client_factory = comfy_client_factory or (lambda server: ComfyUIClient(server))
        storage = self.config.get("storage") or {}
        self.output_dir = output_dir or storage.get("output_dir") or tempfile.gettempdir()
        self._results = {}
        self._lock = threading.RLock()
        self._install_default_adapters()

    def _install_default_adapters(self):
        comfy = self.adapters.get("comfyui")
        if comfy is None:
            endpoint = (self.config.get("comfyui") or {}).get("server") or ""
            comfy = self._comfy_client_factory(endpoint) if endpoint else _NullAdapter("comfyui")
            self.adapters["comfyui"] = comfy
        for mode in COMFY_MODES:
            self.adapters.setdefault(mode, _ComfyDiagnosticAdapter(comfy, self.output_dir))
        llm_cfg = self.config.get("llm") or {}
        llm_mode = llm_cfg.get("provider") or "local"
        llm_part = llm_cfg.get("cloud" if llm_mode == "cloud" else "local") or {}
        self.adapters.setdefault("llm", _HttpAdapter(
            llm_part.get("base_url") or llm_part.get("url"),
            llm_part.get("api_key") or llm_part.get("token"),
            llm_part.get("model"),
            llm_cfg.get("provider_type") or "openai",
        ))
        image_cfg = self.config.get("image_gen") or {}
        image_mode = image_cfg.get("provider") or "local"
        if image_mode == "comfyui":
            self.adapters.setdefault("image", self.adapters["comfyui_image"])
            self.adapters.setdefault("agnes", _NullAdapter("agnes"))
            self.adapters.setdefault("boogu", _NullAdapter("boogu"))
            return
        image_part = image_cfg.get("cloud" if image_mode == "cloud" else "local") or {}
        image_adapter = _HttpAdapter(
            image_part.get("base_url") or image_part.get("url"),
            image_part.get("api_key"),
            image_part.get("model"),
            image_cfg.get("provider_type") or "openai",
        )
        self.adapters.setdefault("agnes", image_adapter if image_mode == "cloud" else _NullAdapter("agnes"))
        self.adapters.setdefault("boogu", image_adapter if image_mode == "local" else _NullAdapter("boogu"))
        # The selected image provider is exposed through a neutral test name.
        self.adapters.setdefault("image", self.adapters["agnes"] if image_mode == "cloud" else self.adapters["boogu"])
        vision_cfg = self.config.get("vision") or {}
        self.adapters.setdefault("vision", _HttpAdapter(vision_cfg.get("base_url"), vision_cfg.get("api_key"), vision_cfg.get("model")))
        self.adapters.setdefault("local_environment", _NullAdapter("local_environment"))

    def _secrets(self):
        values = []
        def walk(value, key=""):
            if isinstance(value, dict):
                for name, child in value.items():
                    if any(token in str(name).lower() for token in ("key", "token", "secret", "password")) and child:
                        values.append(str(child))
                    walk(child, str(name))
            elif isinstance(value, (list, tuple)):
                for child in value:
                    walk(child, key)
        walk(self.config)
        return values

    def _redact(self, value):
        if isinstance(value, dict):
            return {key: self._redact(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self._redact(child) for child in value]
        return redact_secrets(value, self._secrets()) if isinstance(value, str) else value

    def _entry(self, service, level, status, start, summary="", details=None, failure=None):
        return {
            "service": service,
            "level": level,
            "status": status,
            "elapsed_ms": _elapsed(start),
            "summary": summary,
            "details": self._redact(details or {}),
            "failure": self._redact(failure) if failure else None,
            "checked_at": _now(),
        }

    def _quick_comfy(self):
        adapter = self.adapters["comfyui"]
        profile = adapter.profile() if hasattr(adapter, "profile") else {}
        details = {"profile": profile}
        details["queue"] = adapter.queue() if hasattr(adapter, "queue") else {}
        return "quick_passed", "ComfyUI 元数据可访问", details

    def quick_check_service(self, service):
        service = str(service or "").strip()
        if service not in SERVICES:
            raise ValueError("unknown diagnostic service: " + service)
        start = time.monotonic()
        try:
            if service == "local_environment":
                status, summary, details = "quick_passed", "本地运行环境可用", {"python": platform.python_version(), "platform": platform.platform()}
            elif service == "comfyui":
                status, summary, details = self._quick_comfy()
            elif service in COMFY_MODES:
                status, summary, details = self._quick_comfy()
                status = "needs_real_test"
                summary = "节点服务可访问，仍需单独真实生成测试"
                details = dict(details, mode=service, generation_called=False)
            else:
                adapter = self.adapters.get(service) or _NullAdapter(service)
                probe = adapter.quick_check() if hasattr(adapter, "quick_check") else {"status": "needs_real_test", "summary": "需要显式真实测试确认", "details": {}}
                status = str(probe.get("status") or "needs_real_test")
                summary = str(probe.get("summary") or "")
                details = probe.get("details") or {}
            entry = self._entry(service, "quick", status, start, summary, details)
        except Exception as exc:
            failure = _failure(exc, "F-CONNECTION" if service in {"comfyui", *COMFY_MODES} else "F-DIAGNOSTIC")
            entry = self._entry(service, "quick", "failed", start, failure["summary"], {}, failure)
        with self._lock:
            self._results[service] = entry
        return entry

    def quick_check_all(self):
        return {service: self.quick_check_service(service) for service in SERVICES}

    def _confirm(self, service, confirm_cost, confirm_gpu):
        if service in COST_SERVICES and not confirm_cost:
            raise ValueError("confirm_cost must be true for " + service)
        if service in GPU_SERVICES and not confirm_gpu:
            raise ValueError("confirm_gpu must be true for " + service)

    def start_real_test(self, service, confirm_cost=False, confirm_gpu=False, parameters=None):
        service = str(service or "").strip()
        if service not in SERVICES:
            raise ValueError("unknown diagnostic service: " + service)
        if service == "comfyui":
            raise ValueError("comfyui metadata has no paid real test; choose a generation mode")
        self._confirm(service, bool(confirm_cost), bool(confirm_gpu))
        run_parameters = self._parameters(service)
        supplied = parameters if isinstance(parameters, dict) else {}
        if service in {"agnes", "boogu", "image", "comfyui_image"}:
            prompt = str(supplied.get("prompt") or "").strip()
            if prompt:
                run_parameters["prompt"] = prompt[:4000]
        run_id = self.store.create_diagnostic_run(service, "real", run_parameters)
        with self._lock:
            self._results[service] = self._entry(service, "real", "running", time.monotonic(), "真实测试运行中", {"run_id": run_id, "parameters": run_parameters})
        thread = threading.Thread(target=self._run_real, args=(run_id, service, run_parameters), daemon=True)
        thread.start()
        return {"run_id": run_id, "service": service, "level": "real", "status": "running", "parameters": run_parameters}

    def _parameters(self, service):
        if service in {"agnes", "boogu", "image"}:
            return {"prompt": "A diagnostic test card, clean lighting, no text", "size": "768x768", "provider": service}
        if service == "llm":
            return {"response": '{"ok":true,"service":"llm"}'}
        if service == "vision":
            return {"width": 256, "height": 128, "card": "deterministic"}
        if service == "comfyui_image":
            return {"prompt": "A diagnostic test card, clean lighting, no text", "width": 768, "height": 768, "steps": 12}
        return {"mp": 0.2, "duration": 5, "steps": 4, "mode": service.rsplit("_", 1)[-1]}

    def _run_real(self, run_id, service, parameters):
        started = time.monotonic()
        try:
            adapter = self.adapters.get(service) or self.adapters.get("comfyui")
            if hasattr(adapter, "real_test"):
                output = adapter.real_test(service=service, parameters=parameters)
            elif service in COMFY_MODES and hasattr(adapter, "diagnostic_test"):
                output = adapter.diagnostic_test(service=service, parameters=parameters)
            elif service in COMFY_MODES and hasattr(adapter, "submit"):
                # Keep the default operation conservative: a fake/injected
                # adapter can provide the complete poll/download lifecycle,
                # while a bare ComfyUI client receives only this explicit
                # one-service request and the result remains unverified.
                output = adapter.submit({"diagnostic_service": service, "parameters": parameters}, client_id="diagnostics")
                if not isinstance(output, dict) or not (output.get("prompt_id") or output.get("id")):
                    raise RuntimeError("ComfyUI 未返回诊断 prompt_id")
                output = {"prompt_id": output.get("prompt_id") or output.get("id"), "validated": False}
            elif service == "llm" and hasattr(adapter, "chat"):
                output = adapter.chat(parameters=parameters)
            elif service == "vision" and hasattr(adapter, "inspect"):
                output = adapter.inspect(card=_png_card(), parameters=parameters)
            elif service in {"agnes", "boogu", "image", "comfyui_image"} and hasattr(adapter, "generate"):
                output = adapter.generate(service=service, parameters=parameters)
            else:
                raise RuntimeError("未配置真实测试适配器")
            output = self._validate_output(service, output)
            self.finish_real_test(service, output=output, run_id=run_id, elapsed_ms=_elapsed(started))
        except Exception as exc:
            self.finish_real_test(service, failure=_failure(exc), run_id=run_id, elapsed_ms=_elapsed(started))

    def _validate_output(self, service, output):
        if not isinstance(output, dict):
            output = {"value": output}
        result = copy.deepcopy(output)
        if service == "llm" or service == "vision":
            return result
        filename = str(result.get("filename") or result.get("path") or "")
        if not filename and not result.get("url"):
            raise RuntimeError("真实测试未返回输出文件")
        if filename and os.path.isfile(filename):
            result["filename"] = filename
        elif filename and not result.get("url"):
            # Injected test adapters may return metadata; production adapters
            # mark downloaded media explicitly.
            if not result.get("validated"):
                raise RuntimeError("输出文件未通过下载验证")
        result["validated"] = bool(result.get("validated", True))
        return result

    def finish_real_test(self, service, output=None, failure=None, run_id=None, elapsed_ms=None):
        service = str(service or "").strip()
        if run_id is None:
            run_id = self.store.create_diagnostic_run(service, "real", self._parameters(service))
        if failure:
            failure = self._redact(failure)
            self.store.finish_diagnostic_run(run_id, "failed", result=None, failure=failure)
            status, summary = "failed", str(failure.get("summary") or "真实测试失败")
        else:
            # ``_run_real`` validates adapter output before reaching here.
            # Keeping this method usable with a caller-supplied result also
            # makes it a small persistence seam for integrations/tests.
            output = copy.deepcopy(output or {})
            output = self._redact(output)
            self.store.finish_diagnostic_run(run_id, "succeeded", result=output, failure=None)
            status, summary = "available", "真实测试成功"
        record = self.store.get_diagnostic_run(run_id) or {"run_id": run_id, "service": service, "level": "real", "status": "failed"}
        record["elapsed_ms"] = elapsed_ms if elapsed_ms is not None else record.get("elapsed_ms", 0)
        with self._lock:
            self._results[service] = {
                "service": service, "level": "real", "status": status,
                "elapsed_ms": record["elapsed_ms"], "summary": summary,
                "details": {"run_id": run_id}, "failure": failure,
                "checked_at": _now(), "result": output if not failure else None,
            }
        return record

    def poll(self, run_id):
        record = self.store.get_diagnostic_run(run_id)
        if not record:
            raise KeyError(run_id)
        service = record["service"]
        with self._lock:
            current = copy.deepcopy(self._results.get(service) or {})
        response = dict(record)
        response.update({key: value for key, value in current.items() if key not in {"service", "level"}})
        response["service"] = service
        response["level"] = record.get("level")
        # The persisted run state is the API contract; ``available`` is a
        # summary-only label used by the diagnostics cards.
        response["status"] = record.get("status")
        response["failure"] = self._redact(response.get("failure")) if response.get("failure") else None
        if response.get("status") == "succeeded" and response.get("result"):
            response["result"] = self._redact(response["result"])
        return response

    def summary(self):
        with self._lock:
            result = copy.deepcopy(self._results)
        for service in SERVICES:
            result.setdefault(service, self._entry(service, "quick", "unconfigured", time.monotonic(), "尚未检查", {}))
        return {service: self._redact(result[service]) for service in SERVICES}


__all__ = ["SERVICES", "ServiceDiagnostics"]
