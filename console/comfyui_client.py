"""Small, testable HTTP client for the ComfyUI API."""

import hashlib
import json
import mimetypes
import os
import urllib.parse
import urllib.request
import uuid
from urllib.error import HTTPError


class UrllibTransport:
    def __init__(self, server):
        self.server = server.rstrip("/")

    def _request(self, path, data=None, method=None, headers=None, timeout=30):
        url = self.server + path
        request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ComfyUI HTTP {exc.code} {exc.reason}: {detail[:4000]}") from exc

    def get_json(self, path, timeout=15):
        return json.loads(self._request(path, timeout=timeout).decode("utf-8"))

    def post_json(self, path, payload, timeout=30):
        return json.loads(self._request(
            path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "batch-console"},
            timeout=timeout,
        ).decode("utf-8"))

    def upload_image(self, path, local_path, filename, timeout=120):
        with open(local_path, "rb") as handle:
            raw = handle.read()
        boundary = "----CodexBatch" + uuid.uuid4().hex
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts = [
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
            ).encode("utf-8"),
            raw,
            b"\r\n",
        ]
        for name, value in (("type", "input"), ("overwrite", "true")):
            parts.extend([
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
            ])
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return json.loads(self._request(
            path,
            data=b"".join(parts),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "batch-console"},
            timeout=timeout,
        ).decode("utf-8"))

    def download(self, path, destination, timeout=120):
        data = self._request(path, timeout=timeout)
        with open(destination, "wb") as handle:
            handle.write(data)
        return destination


class ComfyUIClient:
    MODEL_INPUTS = {
        "ckpt_name", "unet_name", "clip_name", "vae_name", "lora_name",
        "ipadapter_file", "clip_vision", "clip_vision_name", "control_net_name",
    }
    CLIP_VISION_BY_PRESET = {
        "PLUS": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
        "PLUS_FACE": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
        "FULL_FACE": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
        "VIT_H": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
    }

    def __init__(self, server, transport=None):
        self.server = str(server or "").rstrip("/")
        self.transport = transport or UrllibTransport(self.server)

    def profile(self):
        stats = self.transport.get_json("/system_stats") or {}
        queue = self.queue()
        system = stats.get("system") or {}
        devices = stats.get("devices") or []
        device = devices[0] if devices else {}
        return {
            "server": self.server,
            "comfyui_version": system.get("comfyui_version") or stats.get("comfyui_version") or "",
            "gpu_name": device.get("name") or device.get("type") or "",
            "vram_total": device.get("vram_total"),
            "vram_free": device.get("vram_free"),
            "queue_running": len(queue.get("queue_running") or []),
            "queue_pending": len(queue.get("queue_pending") or []),
        }

    def queue(self):
        return self.transport.get_json("/queue") or {}

    def history(self, prompt_id=None):
        path = "/history" if prompt_id is None else "/history/" + urllib.parse.quote(str(prompt_id), safe="")
        return self.transport.get_json(path) or {}

    def object_info(self):
        return self.transport.get_json("/object_info") or {}

    def checkpoint_models(self):
        objects = self.object_info()
        required = (((objects.get("CheckpointLoaderSimple") or {}).get("input") or {}).get("required") or {})
        choices = required.get("ckpt_name") or []
        if isinstance(choices, (list, tuple)) and choices and isinstance(choices[0], (list, tuple)):
            choices = choices[0]
        if not isinstance(choices, (list, tuple)):
            return []
        return sorted({str(name).strip() for name in choices if str(name).strip()}, key=str.casefold)

    def preflight(self, graph):
        available = self.object_info()
        missing_nodes = set()
        missing_models = set()
        missing_inputs = set()
        explicit_clip_vision = {
            str((node.get("inputs") or {}).get("clip_name") or (node.get("inputs") or {}).get("clip_vision") or "").strip()
            for node in (graph or {}).values()
            if str(node.get("class_type") or "") == "CLIPVisionLoader"
        }
        for node in (graph or {}).values():
            class_type = str(node.get("class_type") or "")
            if class_type not in available:
                missing_nodes.add(class_type)
                continue
            required = ((available.get(class_type) or {}).get("input") or {}).get("required") or {}
            inputs = node.get("inputs") or {}
            for name in required:
                if name not in inputs:
                    missing_inputs.add(f"{class_type}.{name}")
            for name in self.MODEL_INPUTS:
                if name not in inputs or name not in required:
                    continue
                value = inputs[name]
                options = required[name]
                if isinstance(options, (list, tuple)) and options and isinstance(options[0], (list, tuple)):
                    options = options[0]
                if isinstance(options, (list, tuple)) and value not in options:
                    missing_models.add(str(value))
            if class_type == "IPAdapterUnifiedLoader":
                preset = str(inputs.get("preset") or "").strip().upper().replace(" ", "_")
                expected = self.CLIP_VISION_BY_PRESET.get(preset)
                if expected:
                    if explicit_clip_vision:
                        continue
                    vision = available.get("CLIPVisionLoader") or {}
                    vision_required = ((vision.get("input") or {}).get("required") or {})
                    vision_spec = vision_required.get("clip_name") or vision_required.get("clip_vision")
                    if not vision_spec:
                        missing_models.add(expected)
                        continue
                    options = vision_spec[0] if isinstance(vision_spec, (list, tuple)) and vision_spec and isinstance(vision_spec[0], (list, tuple)) else vision_spec
                    if not isinstance(options, (list, tuple)) or expected not in options:
                        missing_models.add(expected)
        missing_nodes.discard("")
        return {
            "ok": not missing_nodes and not missing_models and not missing_inputs,
            "missing_nodes": sorted(missing_nodes),
            "missing_models": sorted(missing_models),
            "missing_inputs": sorted(missing_inputs),
            "warnings": [],
        }

    def submit(self, graph, client_id="batch_console"):
        return self.transport.post_json("/prompt", {"prompt": graph, "client_id": client_id}, timeout=60)

    def interrupt(self):
        return self.transport.post_json("/interrupt", {}, timeout=30)

    def delete_pending(self, prompt_id):
        return self.transport.post_json("/queue", {"delete": [str(prompt_id)]}, timeout=30)

    def upload_image(self, local_path, filename=None):
        filename = filename or os.path.basename(local_path)
        if hasattr(self.transport, "upload_image"):
            return self.transport.upload_image("/upload/image", local_path, filename)
        raise RuntimeError("ComfyUI transport does not support image uploads")

    def download_output(self, output_meta, destination):
        query = urllib.parse.urlencode({
            "filename": output_meta.get("filename", ""),
            "subfolder": output_meta.get("subfolder", ""),
            "type": output_meta.get("type", "output"),
        })
        if hasattr(self.transport, "download"):
            return self.transport.download("/view?" + query, destination)
        raise RuntimeError("ComfyUI transport does not support downloads")

    def server_fingerprint(self):
        stats = self.transport.get_json("/system_stats") or {}
        objects = self.object_info()
        system = stats.get("system") or {}
        devices = stats.get("devices") or []
        device = devices[0] if devices else {}
        nodes = {}
        for name in sorted(objects):
            info = objects.get(name) or {}
            required = ((info.get("input") or {}).get("required") or {})
            model_options = {}
            for input_name in sorted(self.MODEL_INPUTS.intersection(required)):
                options = required[input_name]
                model_options[input_name] = options
            nodes[name] = {"present": True, "models": model_options}
        payload = {
            "server": self.server.lower(),
            "version": system.get("comfyui_version") or stats.get("comfyui_version") or "",
            "gpu": device.get("name") or device.get("type") or "",
            "nodes": nodes,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
