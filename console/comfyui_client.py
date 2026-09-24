"""Small, testable HTTP client for the ComfyUI API."""

import hashlib
import json
import mimetypes
import os
import urllib.parse
import urllib.request
import uuid


class UrllibTransport:
    def __init__(self, server):
        self.server = server.rstrip("/")

    def _request(self, path, data=None, method=None, headers=None, timeout=30):
        url = self.server + path
        request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
            return response.read()

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
    MODEL_INPUTS = {"ckpt_name", "unet_name", "clip_name", "vae_name", "lora_name"}

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

    def preflight(self, graph):
        available = self.object_info()
        missing_nodes = set()
        missing_models = set()
        for node in (graph or {}).values():
            class_type = str(node.get("class_type") or "")
            if class_type not in available:
                missing_nodes.add(class_type)
                continue
            required = ((available.get(class_type) or {}).get("input") or {}).get("required") or {}
            for name in self.MODEL_INPUTS:
                if name not in (node.get("inputs") or {}) or name not in required:
                    continue
                value = node["inputs"][name]
                options = required[name]
                if isinstance(options, (list, tuple)) and options and isinstance(options[0], (list, tuple)):
                    options = options[0]
                if isinstance(options, (list, tuple)) and value not in options:
                    missing_models.add(str(value))
        missing_nodes.discard("")
        return {
            "ok": not missing_nodes and not missing_models,
            "missing_nodes": sorted(missing_nodes),
            "missing_models": sorted(missing_models),
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
