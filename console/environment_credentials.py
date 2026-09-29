"""Secure local storage for cloud-environment SSH passwords."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import stat
import uuid


class CredentialStoreError(RuntimeError):
    """A safe, non-secret credential persistence failure."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class _WindowsDpapiProtector:
    CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def __init__(self):
        if os.name != "nt":
            raise CredentialStoreError("当前系统不支持 Windows DPAPI")
        self.crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        self.crypt32.CryptProtectData.restype = wintypes.BOOL
        self.crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self.kernel32.LocalFree.restype = wintypes.HLOCAL

    @staticmethod
    def _input_blob(value):
        raw = bytes(value)
        buffer = (ctypes.c_byte * len(raw)).from_buffer_copy(raw)
        blob = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return buffer, blob

    def protect(self, value):
        input_buffer, input_blob = self._input_blob(value)
        output_blob = _DataBlob()
        ok = self.crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        if not ok:
            raise CredentialStoreError("Windows 无法加密 SSH 密码") from ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self.kernel32.LocalFree(output_blob.pbData)
            del input_buffer

    def unprotect(self, value):
        input_buffer, input_blob = self._input_blob(value)
        output_blob = _DataBlob()
        ok = self.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        if not ok:
            raise CredentialStoreError("已保存的 SSH 密码无法解密") from ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self.kernel32.LocalFree(output_blob.pbData)
            del input_buffer


def _default_store_path():
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        return Path(local_app_data) / "ComfyUIAutoDrama" / "environment_credentials.json"
    return Path.home() / ".comfyui-auto-drama" / "environment_credentials.json"


class EnvironmentCredentialStore:
    """Persist only DPAPI ciphertext, addressed by an opaque reference."""

    def __init__(self, path=None, protector=None, supported=None):
        self.path = Path(path) if path else _default_store_path()
        self._supported = os.name == "nt" if supported is None else bool(supported)
        self.protector = protector or (_WindowsDpapiProtector() if self._supported else None)

    @property
    def supported(self):
        return bool(self._supported and self.protector)

    @staticmethod
    def _empty_payload():
        return {"version": 1, "credentials": {}}

    def _read_payload(self):
        if not self.path.exists():
            return self._empty_payload()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return self._empty_payload()
        if payload.get("version") != 1 or not isinstance(payload.get("credentials"), dict):
            return self._empty_payload()
        return {"version": 1, "credentials": dict(payload["credentials"])}

    def _write_payload(self, payload):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def save(self, password, credential_ref=None):
        if not self.supported:
            raise CredentialStoreError("当前系统不支持安全保存 SSH 密码")
        ref = str(credential_ref or uuid.uuid4().hex)
        payload = self._read_payload()
        ciphertext = self.protector.protect(str(password).encode("utf-8"))
        payload["credentials"][ref] = base64.b64encode(ciphertext).decode("ascii")
        self._write_payload(payload)
        return ref

    def load(self, credential_ref):
        if not self.supported or not credential_ref:
            return None
        encoded = self._read_payload()["credentials"].get(str(credential_ref))
        if not encoded:
            return None
        try:
            ciphertext = base64.b64decode(str(encoded), validate=True)
            return self.protector.unprotect(ciphertext).decode("utf-8")
        except CredentialStoreError:
            raise
        except Exception as exc:
            raise CredentialStoreError("已保存的 SSH 密码无法解密") from exc

    def delete(self, credential_ref):
        if not credential_ref:
            return False
        payload = self._read_payload()
        removed = payload["credentials"].pop(str(credential_ref), None) is not None
        if removed:
            self._write_payload(payload)
        return removed
