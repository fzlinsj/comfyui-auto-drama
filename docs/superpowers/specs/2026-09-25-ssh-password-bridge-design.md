# SSH 密码自动认证设计

## 目标

云端环境扫描只要求用户填写 SSH 登录命令和密码。系统自动完成主机指纹观察、认证和只读环境探针，不要求用户准备 SSH 私钥、公钥或 SSH Agent。

本设计只解决 SSH 认证与扫描入口，不改变远程部署配方、模型下载和 GPU 验证的未完成状态。

## 用户流程

1. 用户填写 SSH 登录命令和密码，点击“扫描远端环境”。
2. 首次请求只做 SSH 握手，获取主机公钥指纹并自动填入指纹字段；不执行远端命令。
3. 用户核对指纹并勾选确认，再次点击扫描。
4. 后端使用本次会话中的密码完成认证，执行固定的只读探针。
5. 扫描成功后用户可以生成部署计划；实际部署仍需单独确认并受当前配方能力限制。

## 方案与边界

### SSH 传输

继续调用系统 OpenSSH，保持项目标准库优先，不新增 Paramiko、sshpass 或其他第三方依赖。私钥和 SSH Agent 路径保持现有兼容行为。

### 密码桥接

当会话提供密码且没有私钥文件时：

- 生成随机名称的一次性 `SSH_ASKPASS` helper。
- helper 只输出当前会话密码，不接受命令行参数，不写入日志。
- 调用 SSH 时设置 `SSH_ASKPASS`、`SSH_ASKPASS_REQUIRE=force` 和必要的无交互环境标记，限制认证方式为密码，最多尝试一次。
- SSH 子进程结束后，在 `finally` 中删除 helper 并清理相关环境变量。
- 密码不出现在 SSH 参数、异常文本、日志、SQLite 或 API 响应中。

helper 的具体实现由平台适配器负责：Windows 使用临时可执行脚本或等效 helper；其他平台使用当前 Python 运行时可执行的临时 helper。若系统 OpenSSH 不支持强制 askpass，返回可操作的 `E-SSH-AUTH`，不执行远端探针。

### 主机信任

沿用现有流程：首次观察使用临时 `known_hosts` 和兼容 KEX；认证探针只使用刚刚观察到的公钥，并强制 `StrictHostKeyChecking=yes`。指纹不匹配或服务器主机键变化时，拒绝执行探针。

## 错误处理

- `E-SSH-FINGERPRINT`：无法观察指纹、指纹字段不匹配或主机键发生变化。
- `E-SSH-AUTH`：密码错误、OpenSSH/askpass 不可用、SSH 命令启动失败或认证未完成。
- `E-PERMISSION`：认证成功但固定只读探针被远端拒绝或执行失败。

错误消息必须脱敏，不包含密码、helper 路径中的敏感信息或完整 SSH 命令凭据。

## 测试设计

新增测试覆盖：

- 密码会话构造的 SSH 参数包含 askpass 环境所需配置，不包含密码文本。
- helper 创建后传给子进程，并在成功、失败、超时和异常路径全部清理。
- 密码错误映射为 `E-SSH-AUTH`，不会执行后续 recipe 命令。
- 已有私钥和 SSH Agent 会话继续走原路径，不创建密码 helper。
- 指纹确认、主机键信任和密码脱敏回归测试。

验证命令：

```powershell
python -m unittest discover -s console/tests -p "test_*.py" -v
$paths = @(Get-ChildItem console -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile $paths
git diff --check
```

## 非目标

- 不保存密码或自动修改用户的 `authorized_keys`。
- 不把密码写入项目配置、SQLite、前端本地存储或日志。
- 不在本轮实现远程 ComfyUI 安装、模型下载校验或 GPU 生成验证。
