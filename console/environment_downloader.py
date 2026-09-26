"""Resumable, checksum-first downloads used by environment deployment."""

from __future__ import annotations

import dataclasses
import hashlib
import os
import posixpath
import urllib.request
from urllib.parse import urlsplit, urlunsplit

try:
    from .environment_models import EnvironmentError, redact_environment_data
except ImportError:
    from environment_models import EnvironmentError, redact_environment_data


@dataclasses.dataclass(frozen=True)
class DownloadResult:
    status: str
    target: str
    source: str = ""
    bytes_written: int = 0


def _digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _expected_matches(path, expected, size_bytes=0):
    if not os.path.isfile(path):
        return False
    if size_bytes and os.path.getsize(path) != int(size_bytes):
        return False
    return bool(expected) and _digest(path).lower() == str(expected).lower()


def finalize_download(part_path, target_path, sha256, expected_size=None):
    part_path = os.fspath(part_path)
    target_path = os.fspath(target_path)
    if not os.path.isfile(part_path):
        raise EnvironmentError("下载临时文件不存在", "E-DOWNLOAD")
    if expected_size is not None and os.path.getsize(part_path) != int(expected_size):
        raise EnvironmentError("下载文件大小校验失败", "E-CHECKSUM")
    expected = str(sha256 or "").lower()
    if len(expected) != 64 or expected == "0" * 64 or _digest(part_path).lower() != expected:
        raise EnvironmentError("下载文件 SHA256 校验失败", "E-CHECKSUM")
    os.replace(part_path, target_path)
    return target_path


def build_download_sources(resource):
    """Return domestic mirrors first, then configured and official sources."""
    resource = dict(resource or {})
    sources = []
    primary = str(resource.get("primary_url") or "").strip()
    try:
        parsed = urlsplit(primary)
    except ValueError:
        parsed = None

    def add(url):
        url = str(url or "").strip()
        if url and url not in sources:
            sources.append(url)

    mirrors = []
    if parsed and parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "huggingface.co":
        mirrors.append(urlunsplit(("https", "hf-mirror.com", parsed.path, parsed.query, parsed.fragment)))
    elif parsed and parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "github.com":
        mirrors.extend([
            f"https://ghfast.top/{primary}",
            f"https://gh-proxy.com/{primary}",
            f"https://ghproxy.net/{primary}",
        ])
    if mirrors:
        for url in mirrors:
            add(url)
        for url in list(resource.get("fallback_urls") or []):
            add(url)
        add(primary)
    else:
        add(primary)
        for url in list(resource.get("fallback_urls") or []):
            add(url)
    return sources


class ResumableDownloader:
    def __init__(self, fetcher=None, max_attempts=2):
        self.fetcher = fetcher or self._fetch_http
        self.max_attempts = max(1, int(max_attempts))

    def download(self, resource, cancel=None):
        target = os.fspath(resource.get("filename") or "")
        if not target:
            raise EnvironmentError("下载目标缺失", "E-DOWNLOAD")
        expected = resource.get("sha256")
        expected_size = resource.get("size_bytes")
        if _expected_matches(target, expected, expected_size):
            return DownloadResult("reused", target, bytes_written=os.path.getsize(target))
        parent = os.path.dirname(os.path.abspath(target))
        os.makedirs(parent, exist_ok=True)
        part = target + ".part"
        urls = build_download_sources(resource)
        errors = []
        for url in [item for item in urls if item]:
            for _attempt in range(self.max_attempts):
                if cancel and cancel():
                    raise EnvironmentError("下载已取消", "E-DOWNLOAD")
                offset = os.path.getsize(part) if os.path.isfile(part) else 0
                try:
                    self.fetcher(url, part, offset)
                    finalize_download(part, target, expected, expected_size)
                    return DownloadResult("downloaded", target, url, os.path.getsize(target))
                except EnvironmentError as exc:
                    errors.append(f"{url}: {exc.code}")
                    if exc.code == "E-CHECKSUM":
                        continue
                except Exception as exc:
                    errors.append(f"{url}: {redact_environment_data(exc)}")
        raise EnvironmentError("所有下载源均失败", "E-DOWNLOAD", {"sources": errors})

    @staticmethod
    def _fetch_http(url, path, offset):
        request = urllib.request.Request(url)
        if offset:
            request.add_header("Range", f"bytes={offset}-")
        with urllib.request.urlopen(request, timeout=60) as response:
            mode = "ab" if offset and response.status == 206 else "wb"
            with open(path, mode) as handle:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    handle.write(block)


class RemoteDownloader:
    """Execute managed downloads on the scanned Linux host over SSH recipes."""

    def __init__(self, session, data_path, comfy_path):
        self.session = session
        self.data_path = str(data_path or "").rstrip("/")
        self.comfy_path = str(comfy_path or "").rstrip("/")

    @staticmethod
    def _join(root, *parts):
        if not root.startswith("/"):
            raise EnvironmentError("远端根目录必须是绝对路径", "E-DOWNLOAD")
        clean = []
        for part in parts:
            value = str(part or "").replace("\\", "/").strip("/")
            if not value or any(piece in {"", ".", ".."} for piece in value.split("/")):
                raise EnvironmentError("远端资源路径无效", "E-DOWNLOAD")
            clean.append(value)
        return posixpath.join(root, *clean)

    def download(self, resource, cancel=None):
        resource = dict(resource or {})
        kind = str(resource.get("resource_kind") or "model")
        filename = str(resource.get("filename") or "")
        target_dir = str(resource.get("target_dir") or ("custom_nodes" if kind == "node" else ""))
        if not filename or not resource.get("primary_url"):
            raise EnvironmentError("远端资源缺少文件名或下载地址", "E-DOWNLOAD")
        root = self.comfy_path if kind == "node" else self.data_path
        target = self._join(root, target_dir, filename)
        urls = build_download_sources(resource)
        errors = []
        for url in [item for item in urls if item]:
            if cancel and cancel():
                raise EnvironmentError("下载已取消", "E-DOWNLOAD")
            try:
                if kind == "node":
                    self.session.run_recipe(
                        "clone_node", {"url": url, "target": target}, timeout=3600
                    )
                elif kind == "model":
                    self.session.run_recipe(
                        "download_file",
                        {
                            "url": url,
                            "target": target,
                            "sha256": resource.get("sha256"),
                            "size_bytes": int(resource.get("size_bytes") or 0),
                        },
                        timeout=max(7200, min(86400, int((int(resource.get("size_bytes") or 0) / 1024 / 1024) * 2 + 900))),
                    )
                else:
                    raise EnvironmentError(f"未知资源类型: {kind}", "E-DOWNLOAD")
                return DownloadResult("downloaded", target, str(url), int(resource.get("size_bytes") or 0))
            except EnvironmentError as exc:
                errors.append(f"{url}: {redact_environment_data(exc)}")
            except Exception as exc:
                errors.append(f"{url}: {redact_environment_data(exc)}")
        raise EnvironmentError("所有远端下载源均失败", "E-DOWNLOAD", {"sources": errors})
