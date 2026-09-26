"""Restricted SSH boundary for environment scanning and recipe execution."""

import contextlib
import dataclasses
import base64
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

from environment_models import EnvironmentError, redact_environment_data


@dataclasses.dataclass(frozen=True)
class SSHConnectionInfo:
    host: str
    username: str = "root"
    port: int = 22
    identity_file: str = ""


def fingerprint_from_keyscan(output):
    """Return the OpenSSH SHA256 fingerprint for the first host key line."""
    for line in str(output or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3 or not parts[1] or not parts[2]:
            continue
        if not (parts[1].startswith(("ssh-", "ecdsa-", "sk-"))):
            continue
        try:
            key_data = parts[2]
            key_data += "=" * (-len(key_data) % 4)
            blob = base64.b64decode(key_data, validate=True)
        except (ValueError, TypeError):
            continue
        digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
        return f"SHA256:{digest}"
    raise EnvironmentError("无法从 SSH 主机获取公钥指纹", "E-SSH-FINGERPRINT")


def parse_ssh_command(command):
    """Parse the supported subset of an ssh command without executing it."""
    try:
        tokens = shlex.split(str(command or ""), posix=True)
    except ValueError as exc:
        raise EnvironmentError(f"SSH 命令无法解析：{exc}", "E-SSH-AUTH") from exc
    if not tokens or os.path.basename(tokens[0]).lower() != "ssh":
        raise EnvironmentError("请输入 ssh 连接命令", "E-SSH-AUTH")
    host_token = None
    port = 22
    identity_file = ""
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-p", "--port"}:
            index += 1
            if index >= len(tokens) or not tokens[index].isdigit():
                raise EnvironmentError("SSH 端口无效", "E-SSH-AUTH")
            port = int(tokens[index])
            if not 1 <= port <= 65535:
                raise EnvironmentError("SSH 端口超出范围", "E-SSH-AUTH")
        elif token in {"-i", "--identity-file"}:
            index += 1
            if index >= len(tokens) or not tokens[index] or any(c in tokens[index] for c in "\r\n"):
                raise EnvironmentError("SSH 私钥路径无效", "E-SSH-AUTH")
            identity_file = tokens[index]
        elif token.startswith("-"):
            raise EnvironmentError(f"不支持的 SSH 参数：{token}", "E-SSH-AUTH")
        elif host_token is None:
            host_token = token
        else:
            raise EnvironmentError("SSH 命令只能包含一个目标主机", "E-SSH-AUTH")
        index += 1
    if not host_token:
        raise EnvironmentError("SSH 命令缺少目标主机", "E-SSH-AUTH")
    if "@" in host_token:
        username, host = host_token.split("@", 1)
    else:
        username, host = "root", host_token
    if not username or not host or not re.fullmatch(r"[A-Za-z0-9_.:-]+", username) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", host):
        raise EnvironmentError("SSH 用户名或主机格式无效", "E-SSH-AUTH")
    return SSHConnectionInfo(host=host, username=username, port=port, identity_file=identity_file)


_RECIPE_TEMPLATES = {
    "system_probe": "uname -a && id && python3 --version 2>&1 || true",
    "gpu_probe": "command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true",
    "disk_probe": "df -P -- {path}",
    "python_probe": "python3 -c 'import sys; print(sys.version)'",
    "comfy_probe": "test -d {path} && find {path} -maxdepth 2 -type f -name 'main.py' -print -quit",
    "model_probe": "",
    "download_file": "",
    "clone_node": "",
}

_COMPATIBLE_KEX_ALGORITHMS = "curve25519-sha256,ecdh-sha2-nistp256,diffie-hellman-group14-sha256"


@contextlib.contextmanager
def _password_askpass_environment(password):
    """Create a short-lived askpass bridge without putting the password in argv."""
    root = tempfile.mkdtemp(prefix="toonflow-askpass-")
    helper_path = os.path.join(root, "askpass.py")
    helper_source = (
        "import os, sys\n"
        "sys.stdout.write(os.environ.get('TOONFLOW_SSH_ASKPASS_SECRET', ''))\n"
    )
    with open(helper_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(helper_source)
    askpass_path = helper_path
    if os.name == "nt":
        askpass_path = os.path.join(root, "askpass.cmd")
        python_path = str(sys.executable).replace('"', '""')
        helper_for_cmd = helper_path.replace('"', '""')
        with open(askpass_path, "w", encoding="utf-8", newline="\r\n") as handle:
            handle.write(f'@"{python_path}" "{helper_for_cmd}" %*\r\n')
    else:
        os.chmod(helper_path, 0o700)
    child_env = os.environ.copy()
    child_env.update({
        "SSH_ASKPASS": askpass_path,
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": "toonflow",
        "TOONFLOW_SSH_ASKPASS_SECRET": str(password or ""),
    })
    try:
        yield child_env
    finally:
        child_env.pop("TOONFLOW_SSH_ASKPASS_SECRET", None)
        child_env.pop("SSH_ASKPASS", None)
        child_env.pop("SSH_ASKPASS_REQUIRE", None)
        child_env.pop("DISPLAY", None)
        shutil.rmtree(root, ignore_errors=True)


def _safe_remote_path(value):
    path = str(value or "")
    if not path or any(char in path for char in "\r\n;|&`$()\x00"):
        raise ValueError("unsafe remote path")
    return shlex.quote(path)


def _safe_remote_url(value):
    url = str(value or "")
    parsed = urlparse(url)
    lowered = url.lower()
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("url must be a credential-free http(s) URL")
    if any(token in lowered for token in ("token=", "api_key=", "apikey=", "access_token=", "password=")):
        raise ValueError("url must not contain credentials")
    return shlex.quote(url)


def build_recipe_command(recipe_name, params):
    """Build one known read-only or recipe operation; arbitrary shell is rejected."""
    if recipe_name not in _RECIPE_TEMPLATES:
        raise ValueError(f"unknown recipe command: {recipe_name}")
    params = dict(params or {})
    template = _RECIPE_TEMPLATES[recipe_name]
    if recipe_name == "download_file":
        if set(params) != {"url", "target", "sha256", "size_bytes"}:
            raise ValueError("url, target, sha256 and size_bytes are the only accepted parameters")
        digest = str(params.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest == "0" * 64:
            raise ValueError("sha256 must be a non-zero SHA256 digest")
        try:
            size_bytes = int(params.get("size_bytes"))
        except (TypeError, ValueError) as exc:
            raise ValueError("size_bytes must be a non-negative integer") from exc
        if size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        url = _safe_remote_url(params["url"])
        target = _safe_remote_path(params["target"])
        rendered = (
            "set -eu; "
            f"target={target}; part=\"$target.part\"; "
            "mkdir -p -- \"$(dirname -- \"$target\")\"; "
            "if command -v curl >/dev/null 2>&1; then "
            f"if [ -s \"$part\" ]; then curl -fL --connect-timeout 20 --speed-time 60 --speed-limit 1024 --retry 2 -C - -o \"$part\" {url} || curl -fL --connect-timeout 20 --speed-time 60 --speed-limit 1024 --retry 2 -o \"$part\" {url}; "
            f"else curl -fL --connect-timeout 20 --speed-time 60 --speed-limit 1024 --retry 2 -o \"$part\" {url}; fi; "
            "elif command -v wget >/dev/null 2>&1; then "
            f"wget --timeout=20 --tries=3 -c -O \"$part\" {url}; "
            "else echo 'curl or wget is required' >&2; exit 127; fi; "
            "test -f \"$part\"; "
            f"if [ {size_bytes} -gt 0 ]; then test \"$(wc -c < \"$part\")\" -eq {size_bytes}; fi; "
            f"test \"$(sha256sum -- \"$part\" | awk '{{print $1}}')\" = {digest}; "
            "mv -f -- \"$part\" \"$target\""
        )
    elif recipe_name == "clone_node":
        if set(params) != {"url", "target"}:
            raise ValueError("url and target are the only accepted parameters")
        url = _safe_remote_url(params["url"])
        target = _safe_remote_path(params["target"])
        rendered = (
            "set -eu; "
            f"target={target}; mkdir -p -- \"$(dirname -- \"$target\")\"; "
            "if [ -d \"$target/.git\" ]; then "
            f"git -C \"$target\" remote set-url origin {url}; "
            "git -c http.connectTimeout=20 -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=60 -C \"$target\" fetch --depth 1 origin; "
            "git -C \"$target\" reset --hard FETCH_HEAD; "
            "elif [ -d \"$target\" ] && [ -z \"$(find \"$target\" -mindepth 1 -maxdepth 1 -print -quit)\" ]; then "
            "rmdir -- \"$target\"; "
            "fi; "
            "if [ -e \"$target\" ]; then "
            "echo 'target exists and is not a git repository' >&2; exit 2; "
            "else "
            f"git clone -c http.connectTimeout=20 -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=60 --depth 1 {url} \"$target\"; fi"
        )
    elif recipe_name == "model_probe":
        if set(params) != {"comfy_path", "data_path"}:
            raise ValueError("comfy_path and data_path are the only accepted parameters")
        comfy_path = _safe_remote_path(params["comfy_path"])
        data_path = _safe_remote_path(params["data_path"])
        # This is deliberately a fixed read-only inventory command.  It only
        # reports files and immediate custom-node entries under the configured
        # ComfyUI/data roots; no user supplied shell fragment is interpolated.
        rendered = (
            "for root in "
            f"{comfy_path}/models {comfy_path}/ComfyUI/models "
            f"{data_path}/models {data_path}/ComfyUI/models; do "
            "[ -d \"$root\" ] && find -L \"$root\" -type f -printf 'model\\t%p\\t%s\\n'; "
            "done; "
            # Some cloud images mount the model directory outside the four
            # conventional roots above.  Search only directories named
            # ``models`` below the configured roots, never the whole data disk.
            "for base in "
            f"{comfy_path} {data_path}; do "
            "[ -d \"$base\" ] && find -L \"$base\" -type f "
            "-path '*/models/*' -printf 'model\\t%p\\t%s\\n'; "
            "done; "
            "for root in "
            f"{comfy_path}/custom_nodes {comfy_path}/ComfyUI/custom_nodes "
            f"{data_path}/custom_nodes {data_path}/ComfyUI/custom_nodes; do "
            "[ -d \"$root\" ] && find \"$root\" -mindepth 1 -maxdepth 1 "
            "-printf 'node\\t%f\\t%y\\t%p\\n'; "
            "done; true"
        )
    elif "{path}" in template:
        if set(params) != {"path"}:
            raise ValueError("path is the only accepted parameter")
        rendered = template.format(path=_safe_remote_path(params["path"]))
    elif params:
        raise ValueError("recipe command does not accept parameters")
    else:
        rendered = template
    if any(value in rendered.lower() for value in ("password", "private_key", "api_key")):
        raise ValueError("credential text is not allowed in recipe commands")
    return rendered


class SSHSession:
    """A session that only executes commands generated by ``build_recipe_command``."""

    def __init__(self, connection, credential=None, runner=None):
        self.connection = connection if isinstance(connection, SSHConnectionInfo) else parse_ssh_command(connection)
        self.credential = credential or {}
        self.runner = runner or subprocess.run
        self.fingerprint_confirmed = False
        self.install_commands = []
        self._observed_host_keys = ""

    def observe_fingerprint(self, timeout=10):
        fd, known_hosts_path = tempfile.mkstemp(prefix="toonflow-known-hosts-", suffix=".known_hosts")
        os.close(fd)
        args = [
            "ssh", "-p", str(self.connection.port),
            "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "PreferredAuthentications=none",
            "-o", "NumberOfPasswordPrompts=0",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "HashKnownHosts=no",
            "-o", f"UserKnownHostsFile={known_hosts_path}",
            "-o", f"GlobalKnownHostsFile={os.devnull}",
            "-o", f"KexAlgorithms={_COMPATIBLE_KEX_ALGORITHMS}",
            f"{self.connection.username}@{self.connection.host}", "exit",
        ]
        try:
            result = self.runner(args, capture_output=True, text=True, timeout=timeout, check=False)
        except OSError as exc:
            raise EnvironmentError(f"无法调用 ssh：{redact_environment_data(exc)}", "E-SSH-AUTH") from exc
        finally:
            try:
                with open(known_hosts_path, "r", encoding="utf-8") as handle:
                    observed_keys = handle.read()
            except OSError:
                observed_keys = ""
            try:
                os.unlink(known_hosts_path)
            except OSError:
                pass
        if observed_keys:
            try:
                fingerprint = fingerprint_from_keyscan(observed_keys)
            except EnvironmentError:
                fingerprint = ""
            if fingerprint:
                self._observed_host_keys = observed_keys
                return fingerprint
        raise EnvironmentError(
            f"SSH 主机指纹获取失败：{redact_environment_data(result.stderr or result.stdout)}",
            "E-SSH-FINGERPRINT",
        )

    def verify_fingerprint(self, observed, confirmed=False):
        expected = str(self.credential.get("fingerprint") or "")
        observed = str(observed or "")
        if expected and observed and expected != observed and not confirmed:
            raise EnvironmentError("SSH 主机指纹发生变化，请重新确认", "E-SSH-FINGERPRINT")
        if expected and observed != expected and confirmed:
            self.credential["fingerprint"] = observed
        self.fingerprint_confirmed = bool(confirmed or not expected or observed == expected)
        return self.fingerprint_confirmed

    def _temporary_identity_file(self):
        private_key = str(self.credential.get("private_key") or "")
        if not private_key or self.connection.identity_file:
            return None
        fd, path = tempfile.mkstemp(prefix="toonflow-ssh-", suffix=".key")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(private_key)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return path
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

    def run_recipe(self, recipe_name, params=None, timeout=60):
        if not self.fingerprint_confirmed:
            raise EnvironmentError("请先确认 SSH 主机指纹", "E-SSH-FINGERPRINT")
        remote_command = build_recipe_command(recipe_name, params or {})
        args = ["ssh", "-p", str(self.connection.port)]
        identity_path = self.connection.identity_file or self._temporary_identity_file()
        password = str(self.credential.get("password") or "") if not identity_path else ""
        known_hosts_path = None
        if self._observed_host_keys:
            fd, known_hosts_path = tempfile.mkstemp(prefix="toonflow-known-hosts-", suffix=".known_hosts")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(self._observed_host_keys)
            except Exception:
                try:
                    os.unlink(known_hosts_path)
                except OSError:
                    pass
                raise
        try:
            if identity_path:
                args.extend(["-i", identity_path])
            if known_hosts_path:
                args.extend([
                    "-o", "StrictHostKeyChecking=yes",
                    "-o", f"UserKnownHostsFile={known_hosts_path}",
                    "-o", f"GlobalKnownHostsFile={os.devnull}",
                ])
            args.extend(["-o", f"KexAlgorithms={_COMPATIBLE_KEX_ALGORITHMS}"])
            if password:
                args.extend([
                    "-o", "BatchMode=no",
                    "-o", "PasswordAuthentication=yes",
                    "-o", "KbdInteractiveAuthentication=no",
                    "-o", "PreferredAuthentications=password",
                    "-o", "NumberOfPasswordPrompts=1",
                ])
            else:
                args.extend(["-o", "BatchMode=yes"])
            args.extend([f"{self.connection.username}@{self.connection.host}", remote_command])
            try:
                if password:
                    with _password_askpass_environment(password) as child_env:
                        result = self.runner(
                            args, capture_output=True, text=True, timeout=timeout,
                            check=False, env=dict(child_env),
                        )
                else:
                    result = self.runner(args, capture_output=True, text=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise EnvironmentError(
                    f"SSH 请求超时：{redact_environment_data(exc, secrets=[password])}",
                    "E-SSH-AUTH",
                ) from exc
            except OSError as exc:
                raise EnvironmentError(
                    f"SSH 执行失败：{redact_environment_data(exc, secrets=[password])}",
                    "E-SSH-AUTH",
                ) from exc
            if result.returncode != 0:
                code = "E-SSH-AUTH" if password else "E-PERMISSION"
                raise EnvironmentError(
                    f"远端探针执行失败：{redact_environment_data(result.stderr or result.stdout, secrets=[password])}",
                    code,
                )
            return result.stdout
        finally:
            if identity_path and not self.connection.identity_file and not self.credential.get("private_key") is None:
                try:
                    os.unlink(identity_path)
                except OSError:
                    pass
            if known_hosts_path:
                try:
                    os.unlink(known_hosts_path)
                except OSError:
                    pass


class FakeSSHSession:
    """Deterministic session for unit tests and dry-run planning."""

    def __init__(self, fixture=None, fingerprint="SHA256:test"):
        self.fixture = fixture if fixture is not None else {}
        self.fingerprint = fingerprint
        self.fingerprint_confirmed = False
        self.install_commands = []
        self.commands = []

    def verify_fingerprint(self, expected=None, confirmed=False):
        if expected and expected != self.fingerprint and not confirmed:
            raise EnvironmentError("SSH 主机指纹发生变化，请重新确认", "E-SSH-FINGERPRINT")
        self.fingerprint_confirmed = True
        return True

    def observe_fingerprint(self, timeout=10):
        return self.fingerprint

    def run_recipe(self, recipe_name, params=None, timeout=60):
        build_recipe_command(recipe_name, params or {})
        self.commands.append(recipe_name)
        if isinstance(self.fixture, dict) and recipe_name in self.fixture:
            value = self.fixture[recipe_name]
        else:
            value = self.fixture
        return value
