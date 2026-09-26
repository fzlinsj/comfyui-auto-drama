"""Versioned, validated deployment recipes."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_RESOURCE_MODES = {"cpu_only", "gpu_required", "optional"}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _recipe_dir():
    return Path(__file__).resolve().parents[1] / "recipes"


_MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pth", ".pt", ".bin")
_LOADER_DIRECTORIES = {
    "CheckpointLoaderSimple": "models/checkpoints",
    "UNETLoader": "models/diffusion_models",
    "VAELoader": "models/vae",
    "CLIPLoader": "models/text_encoders",
    "DualCLIPLoader": "models/text_encoders",
    "LoraLoader": "models/loras",
    "LoraLoaderModelOnly": "models/loras",
    "MiniMaxH3TurboLoRA": "models/loras",
    "MiniMaxH3GenerationTailLoader": "models/text_encoders",
    "ControlNetLoader": "models/controlnet",
    "UpscaleModelLoader": "models/upscale_models",
}


def _normalise_model_name(value):
    value = str(value or "").replace("\\", "/").strip()
    if not value.lower().endswith(_MODEL_SUFFIXES):
        return ""
    # ComfyUI combo boxes may return a relative subdirectory.  The directory
    # is tracked separately so matching remains stable across platforms.
    name = value.rsplit("/", 1)[-1]
    if not name or name in {".", ".."} or ".." in name:
        return ""
    return name


def extract_workflow_resources(workflow_path):
    """Extract model files referenced by either ComfyUI workflow format.

    ComfyUI ships both editor workflows (``nodes``/``widgets_values``) and
    API prompt graphs (``class_type``/``inputs``).  The editor format may
    additionally carry machine-readable ``properties.models`` metadata, so
    that metadata is preferred for the target directory and download URL.
    """
    path = Path(workflow_path)
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    resources = {}

    def add(value, target_dir="", url=""):
        filename = _normalise_model_name(value)
        if not filename:
            return
        target_dir = str(target_dir or "").replace("\\", "/").strip("/")
        if target_dir and not target_dir.startswith("models/"):
            target_dir = f"models/{target_dir}"
        key = (target_dir, filename)
        item = resources.setdefault(key, {
            "filename": filename,
            "target_dir": target_dir,
            "primary_url": "",
        })
        if url and not item["primary_url"]:
            item["primary_url"] = str(url)

    def walk(value):
        if isinstance(value, dict):
            inspect_node(value)
            models = value.get("models")
            if isinstance(models, list):
                for model in models:
                    if isinstance(model, dict):
                        add(model.get("name"), model.get("directory"), model.get("url"))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    def inspect_node(node):
        if not isinstance(node, dict):
            return
        node_type = str(node.get("type") or node.get("class_type") or "")
        directory = _LOADER_DIRECTORIES.get(node_type)
        if not directory:
            return
        values = node.get("widgets_values")
        if values is None:
            inputs = node.get("inputs") or {}
            values = list(inputs.values()) if isinstance(inputs, dict) else []
        if isinstance(values, dict):
            values = values.values()
        if not isinstance(values, (list, tuple)):
            values = [values]
        for value in values:
            if isinstance(value, str):
                add(value, directory)

    if isinstance(document, dict) and isinstance(document.get("nodes"), list):
        for node in document["nodes"]:
            inspect_node(node)
    elif isinstance(document, dict):
        for node in document.values():
            inspect_node(node)
    walk(document)
    return list(resources.values())


def extract_workflow_model_refs(workflow_path):
    """Return stable ``(target_dir, filename)`` keys for workflow models."""
    return {
        (item["target_dir"], item["filename"])
        for item in extract_workflow_resources(workflow_path)
    }


def _check_relative(path, field):
    value = str(path or "")
    candidate = Path(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{field} must be a relative path")


def _check_url(url, field):
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError(f"{field} must be a credential-free http(s) URL")
    lowered = str(url).lower()
    if any(token in lowered for token in ("token=", "api_key=", "apikey=", "access_token=")):
        raise ValueError(f"{field} must not contain credentials")


def _validate_resource(resource, kind):
    required = {"filename", "target_dir", "size_bytes", "sha256", "primary_url", "fallback_urls", "shareable"}
    missing = required - set(resource)
    if missing:
        raise ValueError(f"{kind} resource missing fields: {sorted(missing)}")
    _check_relative(resource["filename"], f"{kind}.filename")
    _check_relative(resource["target_dir"], f"{kind}.target_dir")
    if not isinstance(resource["size_bytes"], int) or resource["size_bytes"] < 0:
        raise ValueError(f"{kind}.size_bytes must be a non-negative integer")
    if not isinstance(resource["fallback_urls"], list):
        raise ValueError(f"{kind}.fallback_urls must be a list")
    if not isinstance(resource["shareable"], bool):
        raise ValueError(f"{kind}.shareable must be boolean")
    managed = resource.get("managed", True)
    if not isinstance(managed, bool):
        raise ValueError(f"{kind}.managed must be boolean")
    if managed:
        if not _SHA256.fullmatch(str(resource["sha256"])):
            raise ValueError(f"{kind}.sha256 must be a SHA256 hex digest")
        _check_url(resource["primary_url"], f"{kind}.primary_url")
        for index, url in enumerate(resource["fallback_urls"]):
            _check_url(url, f"{kind}.fallback_urls[{index}]")
    else:
        if resource["primary_url"] or resource["fallback_urls"]:
            raise ValueError(f"{kind} unmanaged resource must not declare download URLs")
        if str(resource["sha256"]) not in {"", "0" * 64}:
            raise ValueError(f"{kind} unmanaged resource must not declare a checksum")


def validate_recipe(recipe):
    if not isinstance(recipe, dict):
        raise ValueError("recipe must be an object")
    for field in ("id", "version", "platforms", "requirements", "workflows", "models", "nodes", "checks"):
        if field not in recipe:
            raise ValueError(f"recipe missing field: {field}")
    if not recipe["platforms"] or not isinstance(recipe["platforms"], list):
        raise ValueError("recipe.platforms must be a non-empty list")
    requirements = recipe["requirements"]
    if not isinstance(requirements, dict) or requirements.get("min_comfyui") is None or requirements.get("min_python") is None:
        raise ValueError("recipe requirements are incomplete")
    if int(requirements.get("min_vram_bytes", 0)) <= 0 or int(requirements.get("min_disk_bytes", 0)) <= 0:
        raise ValueError("recipe hardware requirements are incomplete")
    if not isinstance(recipe["workflows"], list) or not recipe["workflows"]:
        raise ValueError("recipe.workflows must be a non-empty list")
    for workflow in recipe["workflows"]:
        _check_relative(workflow, "workflow")
    for resource in recipe["models"]:
        _validate_resource(resource, "model")
    for resource in recipe["nodes"]:
        _validate_resource(resource, "node")
    if not isinstance(recipe["checks"], list) or not recipe["checks"]:
        raise ValueError("recipe.checks must be a non-empty list")
    for check in recipe["checks"]:
        if set(check) - {"service", "resource_mode", "workflow", "output_kind"}:
            raise ValueError("recipe check contains unknown fields")
        if not check.get("service") or check.get("resource_mode") not in ALLOWED_RESOURCE_MODES:
            raise ValueError("recipe check has an invalid resource mode")
    return recipe


def load_recipe(recipe_id):
    """Load and strictly validate one recipe by its stable id."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", str(recipe_id or "")):
        raise ValueError("invalid recipe id")
    path = _recipe_dir() / f"{recipe_id}.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        recipe = json.load(handle)
    return validate_recipe(recipe)
