"""Domain values shared by the cloud environment manager."""

import re


ENVIRONMENT_STATUSES = {
    "disconnected", "scanned", "plan_ready", "deploying",
    "prepared_waiting_gpu", "verifying", "available", "blocked", "failed",
}

ERROR_CODES = {
    "E-SSH-AUTH", "E-SSH-FINGERPRINT", "E-PERMISSION", "E-DISK", "E-PYTHON",
    "E-CUDA", "E-NODE", "E-DOWNLOAD", "E-CHECKSUM", "E-RESOURCE", "E-WORKFLOW",
    "E-GPU-REQUIRED", "E-VERIFY",
}


class EnvironmentError(RuntimeError):
    """An expected environment operation failure with a stable public code."""

    def __init__(self, message, code="E-VERIFY", details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def environment_status_after_prepare(has_gpu):
    return "verifying" if has_gpu else "prepared_waiting_gpu"


_SECRET_RE = re.compile(
    r"(?i)(password|token|api[_-]?key|private[_-]?key)"
    r"(\s*[=:]\s*|\s+)([^\s,;]+)"
)


def redact_environment_data(value, secrets=()):
    """Redact explicit credentials and common key/value secrets for logs/DB/API."""
    text = str(value)
    for secret in secrets or ():
        if secret:
            text = text.replace(str(secret), "***")
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", text)


def public_error(error):
    if isinstance(error, EnvironmentError):
        return {"code": error.code, "message": str(error), "details": error.details}
    return {"code": "E-VERIFY", "message": str(error), "details": {}}
