"""Read-only remote environment inspection for deployment planning."""

from __future__ import annotations

import dataclasses
import os
import re
from typing import Any

try:
    from .environment_models import redact_environment_data
except ImportError:
    from environment_models import redact_environment_data


@dataclasses.dataclass(frozen=True)
class GPUInfo:
    name: str = ""
    memory_bytes: int = 0
    cuda: str = ""
    driver: str = ""


@dataclasses.dataclass(frozen=True)
class EnvironmentScan:
    platform: str
    host_fingerprint: str
    has_gpu: bool
    environment_kind: str
    gpu: GPUInfo
    disk: dict[str, Any]
    python: dict[str, Any]
    comfyui: dict[str, Any]
    system: dict[str, Any]
    raw_summary: dict[str, Any]

    def to_dict(self):
        return dataclasses.asdict(self)


def classify_environment(observed):
    """Classify a machine without making assumptions about its provider."""
    observed = observed or {}
    has_comfy = bool(observed.get("comfyui") or observed.get("comfyui_present"))
    bundle = bool(observed.get("bundle") or observed.get("integrated_bundle"))
    if has_comfy and bundle:
        return "integrated_bundle"
    if has_comfy:
        return "pure_comfyui"
    return "clean_system"


def _number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _memory_bytes(value):
    """Parse the units used by nvidia-smi while keeping numeric fixtures working."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().replace(",", "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(b|kib|mib|gib|tib)?", text, re.IGNORECASE)
    if not match:
        return 0
    amount = float(match.group(1))
    multiplier = {
        "b": 1,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }.get((match.group(2) or "b").lower(), 1)
    return int(amount * multiplier)


def _parse_system_output(value):
    text = str(value or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = {"raw": text}
    for line in lines:
        if re.match(r"^(Linux|Darwin|FreeBSD|Windows)\b", line, re.IGNORECASE):
            result["uname"] = line
            tokens = line.split()
            if len(tokens) > 1:
                result["hostname"] = tokens[1]
            break
    for line in lines:
        if line.startswith("uid="):
            result["identity"] = line
            break
    return result


def _parse_gpu_output(value):
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    for line in lines:
        parts = [part.strip() for part in line.split(",", 2)]
        if len(parts) < 2 or not parts[0]:
            continue
        result = {"name": parts[0], "memory_bytes": _memory_bytes(parts[1]), "present": True}
        if len(parts) > 2:
            result["driver"] = parts[2]
        return result
    return {}


def _parse_disk_output(value, path):
    for line in str(value or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("filesystem"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        total_blocks = _number(parts[1])
        free_blocks = _number(parts[3])
        if total_blocks or free_blocks:
            return {
                "path": str(path or ""),
                "total_bytes": total_blocks * 1024,
                "free_bytes": free_blocks * 1024,
            }
    return {"path": str(path or ""), "total_bytes": 0, "free_bytes": 0}


def _parse_python_output(value):
    text = str(value or "")
    match = re.search(r"\bPython\s+([0-9]+(?:\.[0-9]+)+(?:[-+._A-Za-z0-9]*)?)", text, re.IGNORECASE)
    if not match:
        match = re.search(r"^\s*([0-9]+(?:\.[0-9]+)+(?:[-+._A-Za-z0-9]*)?)\b", text)
    return {"version": match.group(1)} if match else {}


def _parse_comfy_output(value, path):
    for line in str(value or "").splitlines():
        line = line.strip()
        if line:
            return {"path": str(path or line), "entrypoint": line, "present": True}
    return {"path": str(path or ""), "present": False}


def _normalise_path(value):
    return os.path.normpath(str(value or "")).replace("\\", "/").rstrip("/")


def _model_target_and_filename(full_path, roots):
    full_path = _normalise_path(full_path)
    for root in roots:
        root = _normalise_path(root)
        prefix = root + "/"
        if full_path.startswith(prefix):
            relative = full_path[len(prefix):]
            parts = relative.split("/")
            if len(parts) >= 2:
                return "models/" + "/".join(parts[:-1]), parts[-1]
    # Shared model mounts may not be descendants of the configured ComfyUI
    # root.  Preserve the ComfyUI-relative directory beginning at ``models``.
    parts = full_path.split("/")
    try:
        marker = next(index for index, part in enumerate(parts) if part.lower() == "models")
    except StopIteration:
        return "", os.path.basename(full_path)
    if marker + 1 >= len(parts):
        return "", os.path.basename(full_path)
    return "models/" + "/".join(parts[marker + 1:-1]), parts[-1]


def _parse_model_output(value, comfy_path, data_path):
    """Parse the tab-separated, read-only model/node inventory probe."""
    if isinstance(value, dict):
        return value
    roots = [
        _normalise_path(os.path.join(comfy_path, "models")),
        _normalise_path(os.path.join(comfy_path, "ComfyUI", "models")),
        _normalise_path(os.path.join(data_path, "models")),
        _normalise_path(os.path.join(data_path, "ComfyUI", "models")),
    ]
    models = []
    nodes = []
    seen_models = set()
    seen_nodes = set()
    for raw_line in str(value or "").splitlines():
        parts = raw_line.strip().split("\t")
        if not parts or not parts[0]:
            continue
        if parts[0] == "model" and len(parts) >= 3:
            target_dir, filename = _model_target_and_filename(parts[1], roots)
            if not target_dir or not filename:
                continue
            model_key = (target_dir, filename, _normalise_path(parts[1]))
            if model_key in seen_models:
                continue
            seen_models.add(model_key)
            models.append({
                "filename": filename,
                "target_dir": target_dir,
                "size_bytes": _number(parts[2]),
                "path": _normalise_path(parts[1]),
            })
        elif parts[0] == "node" and len(parts) >= 4:
            node_key = (parts[1], _normalise_path(parts[3]))
            if node_key in seen_nodes:
                continue
            seen_nodes.add(node_key)
            nodes.append({
                "filename": parts[1],
                "target_dir": "custom_nodes",
                "size_bytes": 0,
                "path": _normalise_path(parts[3]),
                "entry_type": parts[2],
            })
    return {"models": models, "nodes": nodes}


def _platform_label(value):
    text = str(value or "").lower()
    if any(token in text for token in ("autodl", "auto-dl", "autodl.com")):
        return "autodl"
    if any(token in text for token in ("晨羽", "chenyu", "seetacloud", "nmb2")):
        return "chenyu"
    return "unknown"


def _safe_summary(value):
    if isinstance(value, dict):
        return {str(key): _safe_summary(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_summary(item) for item in value]
    return redact_environment_data(value)


class EnvironmentScanner:
    """Run the fixed read-only probes exposed by :mod:`environment_ssh`."""

    def __init__(self, session, data_path="/root/autodl-tmp", comfy_path="/root/ComfyUI", host_fingerprint="", platform_hint=""):
        self.session = session
        self.data_path = data_path
        self.comfy_path = comfy_path
        self.host_fingerprint = str(host_fingerprint or "")
        self.platform_hint = str(platform_hint or "")

    def scan(self):
        system = self._probe("system_probe")
        gpu_raw = self._probe("gpu_probe")
        disk = self._probe("disk_probe", {"path": self.data_path})
        python = self._probe("python_probe")
        comfy = self._probe("comfy_probe", {"path": self.comfy_path})
        inventory = self._probe("model_probe", {"comfy_path": self.comfy_path, "data_path": self.data_path})
        if isinstance(inventory, dict) and ("models" in inventory or "nodes" in inventory):
            comfy = dict(comfy or {})
            comfy["models"] = inventory.get("models") or comfy.get("models") or []
            comfy["nodes"] = inventory.get("nodes") or comfy.get("nodes") or []

        gpu = GPUInfo(
            name=str(gpu_raw.get("name") or gpu_raw.get("gpu_name") or ""),
            memory_bytes=_number(gpu_raw.get("memory_bytes") or gpu_raw.get("memory_total_bytes")),
            cuda=str(gpu_raw.get("cuda") or gpu_raw.get("cuda_version") or ""),
            driver=str(gpu_raw.get("driver") or gpu_raw.get("driver_version") or ""),
        )
        has_gpu = bool(gpu.name or gpu.memory_bytes or gpu_raw.get("present"))
        platform = _platform_label(system.get("platform") or system.get("provider") or system.get("hostname"))
        if platform == "unknown" and self.platform_hint:
            platform = _platform_label(self.platform_hint)
        kind = classify_environment({
            "python": bool(python.get("version") or python.get("executable")),
            "comfyui": bool(comfy.get("present") or comfy.get("version") or comfy.get("path")),
            "bundle": bool(comfy.get("bundle") or comfy.get("integrated_bundle")),
        })
        fingerprint = self.host_fingerprint or str(system.get("host_fingerprint") or system.get("fingerprint") or "")
        raw_summary = _safe_summary({
            "system": system,
            "gpu": gpu_raw,
            "disk": disk,
            "python": python,
            "comfyui": comfy,
        })
        return EnvironmentScan(
            platform=platform,
            host_fingerprint=fingerprint,
            has_gpu=has_gpu,
            environment_kind=kind,
            gpu=gpu,
            disk=disk if isinstance(disk, dict) else {},
            python=python if isinstance(python, dict) else {},
            comfyui=comfy if isinstance(comfy, dict) else {},
            system=system if isinstance(system, dict) else {},
            raw_summary=raw_summary,
        )

    def _probe(self, name, params=None):
        value = self.session.run_recipe(name, params or {})
        if isinstance(value, dict):
            return value
        if name == "system_probe":
            return _parse_system_output(value)
        if name == "gpu_probe":
            return _parse_gpu_output(value)
        if name == "disk_probe":
            return _parse_disk_output(value, (params or {}).get("path"))
        if name == "python_probe":
            return _parse_python_output(value)
        if name == "comfy_probe":
            return _parse_comfy_output(value, (params or {}).get("path"))
        if name == "model_probe":
            return _parse_model_output(
                value,
                (params or {}).get("comfy_path"),
                (params or {}).get("data_path"),
            )
        return {"raw": redact_environment_data(value)}
