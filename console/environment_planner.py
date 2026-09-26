"""Turn an environment scan and recipe into a safe deployment plan."""

from __future__ import annotations

import dataclasses
import math
import re

try:
    from .environment_models import EnvironmentError
except ImportError:
    from environment_models import EnvironmentError


@dataclasses.dataclass(frozen=True)
class SpaceEstimate:
    content_bytes: int
    temporary_bytes: int
    extract_bytes: int
    required_bytes: int


@dataclasses.dataclass
class DeploymentPlan:
    status: str
    mode: str
    estimate: SpaceEstimate
    download_tasks: list[dict]
    differences: list[str]
    risks: list[str]
    remaining_bytes: int
    error: EnvironmentError | None = None
    reused_resources: list[dict] = dataclasses.field(default_factory=list)

    def to_dict(self):
        return {
            "status": self.status,
            "mode": self.mode,
            "estimate": dataclasses.asdict(self.estimate),
            "download_tasks": self.download_tasks,
            "differences": self.differences,
            "risks": self.risks,
            "remaining_bytes": self.remaining_bytes,
            "error": {"code": self.error.code, "message": str(self.error)} if self.error else None,
            "reused_resources": self.reused_resources,
        }


def estimate_required_space(resources, temp_bytes=0, extract_bytes=0):
    content = sum(max(int(item.get("size_bytes", 0)), 0) for item in resources or [])
    temporary = max(int(temp_bytes or 0), 0)
    extract = max(int(extract_bytes or 0), 0)
    required = math.ceil((content + temporary + extract) * 1.15)
    return SpaceEstimate(content, temporary, extract, required)


def _version(value):
    numbers = re.findall(r"\d+", str(value or ""))
    return tuple(int(number) for number in numbers[:3]) or (0,)


def _python_compatible(actual, requirement):
    match = re.search(r"(\d+(?:\.\d+)*)", str(requirement or ""))
    return _version(actual) >= _version(match.group(1) if match else requirement)


def _as_dict(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value or {}


def _resource_key(resource):
    resource_kind = str(resource.get("resource_kind") or "")
    target_dir = str(resource.get("target_dir") or "").strip("/\\")
    if resource_kind == "node" and not target_dir:
        target_dir = "custom_nodes"
    return (
        resource_kind,
        target_dir,
        str(resource.get("filename") or ""),
    )


def _inventory(scan):
    comfy = scan.get("comfyui") or {}
    models = [dict(item, resource_kind="model") for item in (comfy.get("models") or []) if isinstance(item, dict)]
    nodes = [dict(item, resource_kind="node") for item in (comfy.get("nodes") or []) if isinstance(item, dict)]
    return {_resource_key(item): item for item in models + nodes}


def _compatible_variant(expected, inventory):
    """Find a known ComfyUI weight variant for an absent recipe filename.

    Vendor images commonly ship FP8/quantized or safety-filtered variants under
    a different filename. Matching is deliberately limited to MiniMax H3 model
    families and the same target directory; arbitrary same-size files are never
    accepted.
    """
    if expected.get("resource_kind") != "model":
        return None
    name = str(expected.get("filename") or "").lower()
    target_dir = str(expected.get("target_dir") or "").strip("/\\")
    family = ""
    if "minimax_h3_fl2va_" in name:
        family = "minimax_h3_fl2va_"
    elif "minimax_h3_ref2va_" in name:
        family = "minimax_h3_ref2va_"
    elif name.startswith("minimax_h3_turbo_v4_step600_ema"):
        family = "minimax_h3_turbo_v4_step600_ema"
    elif name.startswith("qwen3vl_32b_h3_generation_tail"):
        family = "qwen3vl_32b_h3_generation_tail"
    elif "qwen3vl_32b_h3_ultra_uncensored_heretic" in name:
        family = "qwen3vl_32b_"
    if not family:
        return None
    candidates = []
    for key, found in inventory.items():
        if key[0] != "model" or key[1] != target_dir:
            continue
        found_name = str(found.get("filename") or "")
        lowered = found_name.lower()
        if family == "qwen3vl_32b_":
            if "qwen3vl_32b" not in lowered or "heretic" not in lowered or "minimax_h3" not in lowered:
                continue
        elif not lowered.startswith(family):
            continue
        candidates.append(found)
    return sorted(candidates, key=lambda item: (0 if str(item.get("filename")).lower() == name else 1, str(item.get("filename"))))[0] if candidates else None


def build_plan(scan, recipe):
    scan = _as_dict(scan)
    recipe = recipe or {}
    models = list(recipe.get("models") or [])
    nodes = list(recipe.get("nodes") or [])
    inventory = _inventory(scan)
    pending = []
    reused_resources = []
    risks = []
    manual_missing = []
    for resource_kind, resources in (("model", models), ("node", nodes)):
        for resource in resources:
            expected = dict(resource, resource_kind=resource_kind)
            managed = bool(expected.get("managed", True))
            found = inventory.get(_resource_key(expected)) or _compatible_variant(expected, inventory)
            if found is None:
                if managed:
                    pending.append(expected)
                else:
                    manual_missing.append(expected)
                    risks.append(
                        f"{resource_kind} {expected.get('filename', '')} 未发现公开下载源，"
                        "已标记为增强资源；基础部署继续，使用该工作流前需补齐它"
                    )
                continue
            expected_size = max(int(expected.get("size_bytes", 0) or 0), 0)
            actual_size = max(int(found.get("size_bytes", 0) or 0), 0)
            # A scan can find an exact filename in a vendor image whose size
            # differs from the recipe manifest (quantized/scaled variants are
            # common). Re-downloading the same filename would overwrite a
            # usable installed asset and can exceed the disk budget. Reuse it
            # and surface the discrepancy for the post-deployment workflow
            # verification instead.
            reused_resources.append({
                "filename": found.get("filename") or expected.get("filename", ""),
                "target_dir": expected.get("target_dir", ""),
                "resource_kind": resource_kind,
                "size_bytes": actual_size,
                "path": found.get("path", ""),
            })
            if found.get("filename") != expected.get("filename"):
                risks.append(
                    f"{resource_kind} {expected.get('filename', '')} 未找到同名文件，"
                    f"已复用兼容变体 {found.get('filename', '')}"
                )
            if resource_kind == "model" and expected_size != actual_size:
                risks.append(
                    f"{resource_kind} {expected.get('filename', '')} 大小与配方不同，"
                    f"已复用远端文件：远端 {actual_size}，配方 {expected_size}"
                )
    all_resources = pending
    estimate = estimate_required_space(
        all_resources,
        temp_bytes=int(recipe.get("temporary_bytes", 0) or 0),
        extract_bytes=int(recipe.get("extract_bytes", sum(item.get("size_bytes", 0) for item in pending if item.get("resource_kind") == "node") or 0)),
    )
    disk = scan.get("disk") or {}
    free_bytes = int(disk.get("free_bytes", 0) or 0)
    comfy = scan.get("comfyui") or {}
    python = scan.get("python") or {}
    requirements = recipe.get("requirements") or {}
    compatible_comfy = bool(comfy.get("present") or comfy.get("version")) and _version(comfy.get("version")) >= _version(requirements.get("min_comfyui"))
    compatible_python = _python_compatible(python.get("version"), requirements.get("min_python", ">=3.10"))
    mode = "reuse" if compatible_comfy and compatible_python else "isolated"
    differences = []
    if not compatible_comfy:
        differences.append("ComfyUI 版本缺失或低于配方要求")
    if not compatible_python:
        differences.append("Python 版本缺失或低于配方要求")
    if mode == "isolated":
        risks.append("将使用独立目录，现有 ComfyUI 启动脚本不会被覆盖")
    if free_bytes < estimate.required_bytes:
        error = EnvironmentError(
            f"磁盘空间不足，需要 {estimate.required_bytes} 字节，剩余 {free_bytes} 字节",
            "E-DISK",
            {"required_bytes": estimate.required_bytes, "free_bytes": free_bytes},
        )
        return DeploymentPlan("blocked", mode, estimate, [], differences, risks, free_bytes, error, reused_resources)
    return DeploymentPlan("plan_ready", mode, estimate, pending, differences, risks, free_bytes - estimate.required_bytes, None, reused_resources)
