"""Provider-neutral failure classification and safe diagnostic formatting."""

import re


FAILURE_SUMMARIES = {
    "F-OOM": "GPU 显存不足",
    "F-MODEL-MISSING": "工作流引用的模型不存在",
    "F-NODE-MISSING": "工作流依赖节点不存在",
    "F-WORKFLOW-INVALID": "ComfyUI 工作流校验失败",
    "F-ASSET-MISSING": "参考素材不存在或不可读取",
    "F-CONNECTION": "无法连接服务",
    "F-AUTH": "接口鉴权失败",
    "F-SERVER-STALE": "任务不属于当前服务器或已被远端清除",
    "F-CANCELLED": "任务已由用户取消",
    "F-PROVIDER-RESPONSE": "供应商返回格式异常",
    "F-CHAIN-PREDECESSOR-MISSING": "链式前置段不存在或尚未成功",
    "F-CHAIN-FRAME-MISSING": "链式前置段末帧无法恢复",
}


def _execution_error(entry):
    status = entry.get("status") or {}
    for item in status.get("messages") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] == "execution_error":
            return item[1] or {}
    return {}


def parse_comfyui_failure(entry):
    """Return a stable, UI-safe description of a ComfyUI history failure."""
    error = _execution_error(entry or {})
    exception_type = str(error.get("exception_type") or "")
    message = str(error.get("exception_message") or "")
    combined = f"{exception_type} {message}".lower()
    if "outofmemory" in combined or "out of memory" in combined or "allocation on device" in combined:
        code = "F-OOM"
    elif any(marker in combined for marker in ("node not found", "unknown node", "class type", "does not exist")):
        code = "F-NODE-MISSING"
    elif "not in list" in combined or "model" in combined and "missing" in combined:
        code = "F-MODEL-MISSING"
    else:
        code = "F-WORKFLOW-INVALID"
    return {
        "code": code,
        "summary": FAILURE_SUMMARIES[code],
        "node_id": str(error.get("node_id") or ""),
        "node_type": str(error.get("node_type") or ""),
        "exception_type": exception_type,
        "raw_error": message,
    }


def redact_secrets(value, secrets=()):
    """Redact bearer/API key values before a diagnostic leaves the server."""
    text = str(value or "")
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1***", text)
    text = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1***", text)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "***")
    return text
