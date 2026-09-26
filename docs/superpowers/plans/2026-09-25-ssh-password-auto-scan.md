# SSH 密码自动扫描实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户只填写 SSH 命令和密码，点击一次即可完成安全的主机信任、SSH 认证和远端环境扫描；主机身份变化时通过页面按钮重新建立信任，不要求用户手敲命令。

**Architecture:** 保留系统 OpenSSH 和现有只读 recipe 探针。`SSHSession` 增加一次性 `SSH_ASKPASS` 密码桥接，密码只在当前进程和子进程环境中存在；`EnvironmentManager` 按平台、主机、端口和用户名复用目标并在后台保存主机指纹，首次成功连接自动建立信任，后续变化默认阻止，重新信任必须再次通过密码认证。前端隐藏指纹和密钥细节，扫描接口仍保持单一入口。

**Tech Stack:** Python 3 标准库、Windows OpenSSH 9.5+/系统 OpenSSH、SQLite、现有原生 HTML/JavaScript、`unittest`。

---

### Task 1: 为密码认证建立可测试的 askpass 边界

**Files:**
- Modify: `console/tests/test_environment_ssh.py`
- Modify: `console/environment_ssh.py`

- [ ] **Step 1: 写密码 askpass 的失败测试**

在 `EnvironmentSSHTests` 增加以下测试行为：使用注入的 `runner(args, **kwargs)` 模拟首次握手写入临时主机公钥，再模拟 recipe 成功；断言 recipe 调用的 `kwargs["env"]` 含 `SSH_ASKPASS_REQUIRE=force`、`SSH_ASKPASS` 路径和一次性秘密环境变量，`args` 不含明文密码；在 runner 返回后确认 helper 路径不存在。

```python
def test_password_session_uses_askpass_and_cleans_helper(self):
    calls = []

    def runner(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        if args[-1] == "exit":
            known_hosts = next(
                item.split("=", 1)[1]
                for item in args if item.startswith("UserKnownHostsFile=")
            )
            Path(known_hosts).write_text("host ssh-ed25519 dGVzdA==\n", encoding="utf-8")
            return type("Result", (), {"returncode": 255, "stdout": "", "stderr": "Permission denied"})()
        env = calls[-1][1]["env"]
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
        self.assertIn("SSH_ASKPASS", env)
        self.assertEqual(env["TOONFLOW_SSH_ASKPASS_SECRET"], "secret")
        self.assertNotIn("secret", " ".join(args))
        self.assertTrue(Path(env["SSH_ASKPASS"]).exists())
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    session = SSHSession(
        SSHConnectionInfo("host"),
        credential={"password": "secret"},
        runner=runner,
    )
    observed = session.observe_fingerprint()
    session.verify_fingerprint(observed, confirmed=True)
    self.assertEqual(session.run_recipe("system_probe"), "ok")
    helper = calls[-1][1]["env"]["SSH_ASKPASS"]
    self.assertFalse(Path(helper).exists())
```

- [ ] **Step 2: 写失败、超时和私钥绕过测试**

增加三个断言：runner 返回非零时异常代码为 `E-SSH-AUTH` 且异常文本不包含密码；runner 抛出 `TimeoutExpired` 后 helper 仍被删除；提供 `private_key` 时不创建 `SSH_ASKPASS` 环境且仍使用临时 `-i` 文件。

- [ ] **Step 3: 运行 SSH 测试确认新测试失败**

运行：

```powershell
python -m unittest console.tests.test_environment_ssh -v
```

预期：新增测试失败，现有密码-only 测试仍显示当前“不能安全传递密码”的旧行为。

- [ ] **Step 4: 实现跨平台一次性 askpass helper**

在 `console/environment_ssh.py` 增加一个只负责临时资源生命周期的上下文管理器，接口固定为：

```python
@contextlib.contextmanager
def _password_askpass_environment(password):
    """Yield a child environment and remove all helper resources on exit."""
```

实现要求：

- 使用 `tempfile.mkdtemp(prefix="toonflow-askpass-")` 创建目录。
- 写入不包含密码的 Python helper，helper 只执行 `sys.stdout.write(os.environ.get("TOONFLOW_SSH_ASKPASS_SECRET", ""))`。
- Windows 额外写入 `.cmd` wrapper，调用当前 `sys.executable` 和 helper 路径；非 Windows 直接写入带 shebang 的可执行 helper。
- 通过 `env = os.environ.copy()` 设置 `SSH_ASKPASS`、`SSH_ASKPASS_REQUIRE=force`、`DISPLAY=toonflow`、`TOONFLOW_SSH_ASKPASS_SECRET=password`。
- `finally` 使用 `shutil.rmtree(..., ignore_errors=True)` 清理目录，并从子进程环境副本中移除秘密键。
- helper 路径、密码和异常输出不写日志；清理失败只能变成内部调试信息，不能把密码带入异常。

在 `SSHSession.run_recipe()` 的密码分支使用该上下文，并将 SSH 参数改为：

```python
args.extend([
    "-o", "BatchMode=no",
    "-o", "PasswordAuthentication=yes",
    "-o", "KbdInteractiveAuthentication=no",
    "-o", "PreferredAuthentications=password",
    "-o", "NumberOfPasswordPrompts=1",
])
```

密码错误和启动异常调用 `redact_environment_data(message, secrets=[password])` 后再包装为 `E-SSH-AUTH`。

- [ ] **Step 5: 运行 SSH 测试确认通过**

运行：

```powershell
python -m unittest console.tests.test_environment_ssh -v
```

预期：所有 SSH 测试通过，密码不出现在参数、异常和残留临时文件中。

- [ ] **Step 6: 提交认证边界变更**

```powershell
git add console/environment_ssh.py console/tests/test_environment_ssh.py
git commit -m "feat: support ephemeral ssh password authentication"
```

### Task 2: 保存后台主机信任并改造一次请求扫描

**Files:**
- Modify: `console/task_store.py`
- Modify: `console/environment_manager.py`
- Modify: `console/tests/test_environment_store.py`
- Modify: `console/tests/test_environment_api.py`
- Modify: `console/tests/test_environment_api_routes.py`

- [ ] **Step 1: 写目标复用和自动信任的失败测试**

在 `test_environment_store.py` 增加 `find_environment_target()` 和 `update_environment_target_fingerprint()` 的 round-trip 测试；在 `test_environment_api.py` 替换旧的二次确认测试，固定以下行为：

```python
def test_first_scan_authenticates_without_fingerprint_payload(self):
    result = self.manager.scan_target({
        "platform": "autodl",
        "ssh_command": "ssh root@host",
        "password": "secret",
    })
    self.assertEqual(result["scan"]["gpu"]["name"], "RTX 3090")
    self.assertNotIn("host_fingerprint", result["scan"])
    target = self.store.get_environment_job(result["scan_id"])
    self.assertEqual(target["target"]["fingerprint"], "SHA256:test")
```

再增加：同一目标同指纹可直接扫描；不同指纹且没有 `retrust` 时返回 `E-SSH-FINGERPRINT`、`details["can_retrust"] is True`，且 `session.commands` 为空；`retrust=True` 且扫描成功后更新指纹；重信任扫描认证失败时保留旧指纹。

- [ ] **Step 2: 运行 API/store 测试确认失败**

运行：

```powershell
python -m unittest console.tests.test_environment_store console.tests.test_environment_api console.tests.test_environment_api_routes -v
```

预期：新测试因缺少目标查询、指纹更新和一次请求扫描逻辑而失败；旧的 `confirm_fingerprint` 测试应被替换，不保留旧契约。

- [ ] **Step 3: 增加目标查询和指纹更新方法**

在 `TaskStore` 增加：

```python
def find_environment_target(self, platform, host, username, port):
    """Return the newest matching target without exposing credentials."""

def update_environment_target_fingerprint(self, target_id, fingerprint, status="scanned"):
    """Replace only the pinned host key and status after a successful scan."""
```

查询使用 `platform`, `host`, `username`, `port` 精确匹配并按 `updated_at DESC` 取一条；更新只写 `fingerprint`, `status`, `updated_at`，不新增密码或私钥字段。

- [ ] **Step 4: 改造 EnvironmentManager.scan_target()**

按以下顺序实现：

1. 解析 SSH 命令并构造带 `password`/`private_key` 的会话。
2. 调用 `observe_fingerprint()`。
3. 用规范化连接信息查询已有目标。
4. 已有指纹不一致且 `retrust` 为假时，抛出 `EnvironmentError("服务器身份已变化，请点击重新建立信任", "E-SSH-FINGERPRINT", {"target_id": target_id, "can_retrust": True})`，不得调用 `EnvironmentScanner.scan()`。
5. 首次连接、指纹一致或 `retrust=True` 时调用 `session.verify_fingerprint(observed, confirmed=True)`，然后执行固定只读扫描。
6. 扫描成功后首次连接调用 `create_environment_target()`；已有目标调用 `update_environment_target_fingerprint()`（仅在 `retrust=True` 或指纹相同的成功扫描后更新）。
7. 保存完整内部扫描快照用于规划，但返回给 API 的 `scan` 字典删除 `host_fingerprint`。
8. `credential_ref` 继续只保存随机 session 引用，密码和私钥不进入 store。

`retrust=True` 只由页面的“重新建立信任”按钮提交；密码认证或探针失败时不得更新旧指纹。

- [ ] **Step 5: 运行 API/store 测试确认通过**

运行：

```powershell
python -m unittest console.tests.test_environment_store console.tests.test_environment_api console.tests.test_environment_api_routes -v
```

预期：首次扫描不需要 `fingerprint`/`confirm_fingerprint`，响应不暴露指纹；目标复用、变化阻止和重信任更新测试全部通过。

- [ ] **Step 6: 提交扫描信任变更**

```powershell
git add console/task_store.py console/environment_manager.py console/tests/test_environment_store.py console/tests/test_environment_api.py console/tests/test_environment_api_routes.py
git commit -m "feat: automate environment host trust during scan"
```

### Task 3: 简化设置页为一次点击扫描并加入重信任按钮

**Files:**
- Modify: `console/index.html`
- Modify: `console/tests/test_environment_ui.py`

- [ ] **Step 1: 写前端契约失败测试**

更新 UI 测试固定以下契约：

```python
def test_environment_scan_only_exposes_command_and_password(self):
    self.assertIn('id="environmentSshCommand"', self.source)
    self.assertIn('id="environmentPassword"', self.source)
    self.assertNotIn('id="environmentFingerprint"', self.source)
    self.assertNotIn('id="environmentConfirmFingerprint"', self.source)
    self.assertNotIn('id="environmentPrivateKey"', self.source)

def test_environment_retrust_button_is_bound(self):
    self.assertIn('id="btnEnvironmentRetrust"', self.source)
    self.assertIn("async function retrustEnvironment()", self.source)
    self.assertIn("$('btnEnvironmentRetrust').addEventListener('click', retrustEnvironment)", self.source)
```

同时删除旧测试中对 `confirm_fingerprint` 和首次指纹挑战文案的断言。

- [ ] **Step 2: 运行 UI 测试确认失败**

运行：

```powershell
python -m unittest console.tests.test_environment_ui -v
```

预期：新契约失败，因为当前设置页仍显示凭据方式、私钥、指纹输入和确认复选框。

- [ ] **Step 3: 修改环境面板和扫描 payload**

在 `console/index.html`：

- 删除“凭据方式”选择、私钥 textarea、指纹输入框和确认复选框。
- 保留云平台、部署配方、SSH 命令、SSH 密码、数据盘路径和 ComfyUI 路径。
- 在扫描按钮旁增加默认隐藏的 `btnEnvironmentRetrust`，文本为“重新建立信任”。
- `environmentScanPayload(retrust=false)` 只返回 `ssh_command`、`password`、平台和路径，并加入 `retrust` 布尔值；不再发送 `fingerprint` 或 `confirm_fingerprint`。
- `scanEnvironment()` 一次请求完成首次扫描，成功后隐藏重信任按钮。
- 当响应为 `E-SSH-FINGERPRINT` 且 `details.can_retrust` 为真时，只显示“服务器身份发生变化，请确认实例后重新建立信任”，显示按钮，不展示指纹值。
- `retrustEnvironment()` 调用 `scanEnvironment(true)`；成功后回到普通扫描完成状态，失败时保留旧扫描结果和按钮。
- 删除 `environmentCredentialToggle()`、其初始化绑定以及旧的自动填充指纹逻辑。

实现的核心请求结构固定为：

```javascript
function environmentScanPayload(retrust = false) {
  return {
    platform: $('environmentPlatform').value,
    ssh_command: $('environmentSshCommand').value.trim(),
    data_path: $('environmentDataPath').value.trim(),
    comfy_path: $('environmentComfyPath').value.trim(),
    password: $('environmentPassword').value,
    retrust: Boolean(retrust),
  };
}
```

- [ ] **Step 4: 运行 UI 测试确认通过**

运行：

```powershell
python -m unittest console.tests.test_environment_ui -v
```

预期：页面只暴露 SSH 命令和密码，首次扫描没有二次点击逻辑，主机变化只出现重信任按钮。

- [ ] **Step 5: 提交设置页变更**

```powershell
git add console/index.html console/tests/test_environment_ui.py
git commit -m "feat: simplify environment scan to one click"
```

### Task 4: 记录更新说明并完成全量验证

**Files:**
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 在 CHANGELOG 顶部增加版本记录**

新增 `v0.13.48 - SSH 密码自动认证与一次点击环境扫描`，明确记录：

- 用户只需 SSH 命令和密码。
- 系统通过临时 askpass 完成认证，密码不落盘。
- 首次主机指纹后台记录，后续变化默认阻止；重信任不要求手敲命令。
- 本次不实现远端实际安装、模型下载校验和 GPU 生成。
- 验证命令和测试数量。

- [ ] **Step 2: 运行完整验证**

运行：

```powershell
python -m unittest discover -s console/tests -p "test_*.py" -v
$paths = @(Get-ChildItem console -Filter *.py | ForEach-Object { $_.FullName }) + @(Get-ChildItem workflows -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile $paths
Get-ChildItem recipes -Filter *.json | ForEach-Object { python -m json.tool $_.FullName > $null }
git diff --check
```

预期：所有单元测试通过，Python 编译和配方 JSON 校验退出码为 0，`git diff --check` 无错误。

- [ ] **Step 3: 检查敏感信息和工作区**

运行：

```powershell
rg -n "password|private_key|TOONFLOW_SSH_ASKPASS_SECRET" console --glob "*.log" --glob "*.err.log" --glob "*.json"
git status --short
```

预期：运行日志、配置和 JSON 中没有用户密码或私钥内容；只显示本轮预期代码、测试、文档和 changelog 改动，不清理其他用户修改。

- [ ] **Step 4: 提交验证和文档变更**

```powershell
git add console/CHANGELOG.md
git commit -m "docs: document automatic ssh scan security flow"
```

## 风险与验收

- Windows OpenSSH 必须支持 `SSH_ASKPASS_REQUIRE=force`；不支持时返回 `E-SSH-AUTH`，不退回明文密码或命令行密码。
- 首次主机信任无法仅靠 SSH 命令和密码完成带外证明，因此采用自动记录加后续严格校验；主机变化不静默放行。
- 密码认证只在当前扫描请求和子进程环境存在，扫描完成后 helper 与秘密环境变量被清理。
- 验收标准：用户填写两个字段后一次点击能完成首次扫描；错误密码不会创建或更新目标；主机变化不执行探针；重信任只需按钮且必须认证成功；现有私钥/Agent 后端兼容不回归。
