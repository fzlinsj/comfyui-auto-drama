# 云端环境智能部署器实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在控制台中实现面向 AutoDL 和晨羽智云的 SSH 环境扫描、方案规划、无卡准备、有卡验证和可恢复部署流程，并让 MiniMax H3 + SDXL 环境状态可被用户独立测试和审阅。

**Architecture:** 保留 `batch_console.py` 作为 HTTP 入口，将 SSH 会话、只读扫描、recipe 清单、空间估算、下载、部署状态机和验证器拆成独立模块。所有远程动作由版本化 recipe 生成，凭据只在当前进程会话中存在；SQLite 保存目标、扫描、计划、步骤和 manifest，不保存密码或私钥。

**Tech Stack:** Python 3.10+、标准库 `sqlite3`/`subprocess`/`hashlib`/`urllib`/`threading`、现有 `TaskStore`、现有 `ComfyUIClient`、HTTP 单页设置界面、`unittest`。

---

## 文件地图

- Create: `console/environment_models.py` - 环境状态、错误码、扫描结果、计划和步骤的数据结构与脱敏函数。
- Create: `console/environment_ssh.py` - SSH 命令解析、主机指纹、会话内凭据和受限远程命令执行。
- Create: `console/environment_scanner.py` - 只读远端扫描和 AutoDL/晨羽平台识别。
- Create: `console/environment_recipes.py` - recipe JSON 加载、首版 `minimax-h3-sdxl` 清单和步骤校验。
- Create: `console/environment_planner.py` - 环境差异、空间估算、复用/隔离决策和下载源选择。
- Create: `console/environment_deployer.py` - 可恢复的部署步骤、下载校验、无卡/有卡资源门控和验证编排。
- Create: `console/environment_manager.py` - 扫描、计划、部署和 manifest 的统一门面。
- Create: `console/tests/test_environment_models.py`
- Create: `console/tests/test_environment_store.py`
- Create: `console/tests/test_environment_ssh.py`
- Create: `console/tests/test_environment_scanner.py`
- Create: `console/tests/test_environment_recipes.py`
- Create: `console/tests/test_environment_planner.py`
- Create: `console/tests/test_environment_deployer.py`
- Create: `recipes/minimax-h3-sdxl.json` - 首版结构化方案清单，引用仓库内工作流和模型资源。
- Modify: `console/task_store.py` - 增加环境实体表和 CRUD/状态迁移。
- Modify: `console/batch_console.py` - 注册环境管理器、API 路由、后台任务生命周期和错误映射。
- Create: `console/tests/test_environment_api.py`
- Create: `console/tests/test_environment_ui.py`
- Modify: `console/index.html` - 设置页中的连接、扫描、计划、执行、验证和环境清单视图。
- Modify: `console/CHANGELOG.md` - 每个实现阶段顶部新增中文记录，包含验证命令和影响说明。
- Modify: `console/README.md`, `CONFIG.md` - 用户操作、无卡/有卡切换、空间要求和凭据说明。

### Task 1: 建立领域模型和 SQLite 持久化

**Files:**
- Create: `console/environment_models.py`
- Modify: `console/task_store.py`
- Create: `console/tests/test_environment_models.py`
- Create: `console/tests/test_environment_store.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 写失败测试，固定状态和脱敏契约**

```python
def test_gpu_free_prepare_is_not_available(self):
    self.assertEqual(environment_status_after_prepare(has_gpu=False), "prepared_waiting_gpu")
    self.assertNotEqual(environment_status_after_prepare(has_gpu=False), "available")

def test_secret_redaction_removes_password_and_token(self):
    value = redact_environment_data("ssh root@host -p 22 password=abc token=xyz")
    self.assertNotIn("abc", value)
    self.assertNotIn("xyz", value)

def test_store_round_trip_does_not_have_credential_columns(self):
    columns = self.store.table_columns("environment_targets")
    self.assertNotIn("password", columns)
    self.assertNotIn("private_key", columns)
```

- [ ] **Step 2: 运行失败测试**

运行：`python -m unittest console.tests.test_environment_models console.tests.test_environment_store -v`

预期：因模块、表和状态函数尚不存在而失败。

- [ ] **Step 3: 实现最小领域模型和表结构**

`environment_models.py` 定义以下常量和函数：

```python
import re

ENVIRONMENT_STATUSES = {
    "disconnected", "scanned", "plan_ready", "deploying",
    "prepared_waiting_gpu", "verifying", "available", "blocked", "failed",
}
ERROR_CODES = {
    "E-SSH-AUTH", "E-SSH-FINGERPRINT", "E-PERMISSION", "E-DISK", "E-PYTHON",
    "E-CUDA", "E-NODE", "E-DOWNLOAD", "E-CHECKSUM", "E-WORKFLOW",
    "E-GPU-REQUIRED", "E-VERIFY",
}

def environment_status_after_prepare(has_gpu):
    return "verifying" if has_gpu else "prepared_waiting_gpu"

def redact_environment_data(value, secrets=()):
    # 同时过滤显式凭据和常见 token/password 参数，供日志、DB 和 API 共用。
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "***")
    return re.sub(
        r"(?i)(password|token|api[_-]?key|private[_-]?key)(\\s*[=:]\\s*)[^\\s,;]+",
        r"\\1\\2***",
        text,
    )
```

在 `TaskStore.initialize()` 中追加 `environment_targets`、`environment_scans`、`deployment_plans`、`deployment_steps`、`environment_manifests` 表及索引；凭据字段只允许 `credential_ref`，不允许明文。增加 `create_environment_target`、`save_environment_scan`、`save_deployment_plan`、`upsert_deployment_step`、`save_environment_manifest`、`get_environment_job` 方法，JSON 字段统一用现有 `_json/_unjson`。

- [ ] **Step 4: 运行测试并检查迁移幂等性**

运行：`python -m unittest console.tests.test_environment_models console.tests.test_environment_store -v`

预期：PASS；同一个临时 DB 初始化两次不产生重复表或重复索引，状态只能从允许的前置状态迁移。

- [ ] **Step 5: 提交本任务**

```powershell
git add console/environment_models.py console/task_store.py console/tests/test_environment_models.py console/tests/test_environment_store.py console/CHANGELOG.md
git commit -m "feat: add environment domain persistence"
```

### Task 2: 实现 SSH 解析、指纹确认和模拟会话

**Files:**
- Create: `console/environment_ssh.py`
- Create: `console/tests/test_environment_ssh.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 写失败测试**

```python
def test_parse_ssh_command(self):
    info = parse_ssh_command("ssh -p 18078 root@connect.example.com")
    self.assertEqual(info.host, "connect.example.com")
    self.assertEqual(info.port, 18078)
    self.assertEqual(info.username, "root")

def test_changed_fingerprint_is_blocked(self):
    session = FakeSSHSession(fingerprint="SHA256:new")
    with self.assertRaises(EnvironmentError) as ctx:
        session.verify_fingerprint("SHA256:old", confirmed=False)
    self.assertEqual(ctx.exception.code, "E-SSH-FINGERPRINT")

def test_command_builder_never_accepts_arbitrary_shell(self):
    command = build_recipe_command("disk_probe", {"path": "/data"})
    self.assertNotIn("password", command)
    with self.assertRaises(ValueError):
        build_recipe_command("arbitrary", {"shell": "rm -rf /"})
```

- [ ] **Step 2: 运行测试确认失败**

运行：`python -m unittest console.tests.test_environment_ssh -v`

预期：解析器、指纹会话和受限命令表尚未定义。

- [ ] **Step 3: 实现安全会话接口**

实现 `SSHConnectionInfo`、`parse_ssh_command`、`SSHSession`、`FakeSSHSession` 和 `build_recipe_command`。使用本机 `ssh`/`scp` 或可注入传输适配器；私钥/密码只放在 `SSHSession` 实例内存，不写入异常、日志和命令参数。首次连接返回指纹，只有 `confirm_fingerprint()` 后才允许执行 recipe 命令；错误统一映射为 `E-SSH-AUTH`、`E-SSH-FINGERPRINT` 或 `E-PERMISSION`。命令只能来自固定 probe/install/verify 操作名及白名单参数。

- [ ] **Step 4: 验证模拟 SSH、脱敏和清理**

运行：`python -m unittest console.tests.test_environment_ssh -v`

预期：PASS；失败临时目录只保留脱敏日志，凭据不出现在日志字符串或返回字典中。

- [ ] **Step 5: 提交本任务**

```powershell
git add console/environment_ssh.py console/tests/test_environment_ssh.py console/CHANGELOG.md
git commit -m "feat: add safe environment ssh sessions"
```

### Task 3: 实现只读扫描和 recipe 清单

**Files:**
- Create: `console/environment_scanner.py`
- Create: `console/environment_recipes.py`
- Create: `recipes/minimax-h3-sdxl.json`
- Create: `console/tests/test_environment_scanner.py`
- Create: `console/tests/test_environment_recipes.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 写失败测试**

```python
def test_scan_is_read_only(self):
    result = EnvironmentScanner(FakeSSHSession(scan_fixture)).scan()
    self.assertEqual(result.gpu.name, "NVIDIA GeForce RTX 3090")
    self.assertEqual(self.session.install_commands, [])

def test_scan_detects_clean_comfyui_and_bundle(self):
    self.assertEqual(classify_environment({"python": True, "comfyui": False}), "clean_system")
    self.assertEqual(classify_environment({"python": True, "comfyui": True, "bundle": False}), "pure_comfyui")
    self.assertEqual(classify_environment({"comfyui": True, "bundle": True}), "integrated_bundle")

def test_recipe_contains_all_four_verification_modes(self):
    recipe = load_recipe("minimax-h3-sdxl")
    self.assertEqual(recipe["version"], "1.0.0")
    self.assertEqual({item["service"] for item in recipe["checks"]}, {"sdxl", "t2v", "i2v", "r2v"})
```

- [ ] **Step 2: 运行失败测试**

运行：`python -m unittest console.tests.test_environment_scanner console.tests.test_environment_recipes -v`

预期：扫描器、recipe 加载器和清单文件尚未存在。

- [ ] **Step 3: 实现固定 probe 的只读扫描器**

扫描命令只收集系统、GPU/CUDA、磁盘、内存、Python、ComfyUI 版本、节点、模型、监听端口和进程状态；每项保存原始值前经过 `redact_environment_data`。用平台标签判断 AutoDL/晨羽智云，不能执行安装、下载、重启或修改文件。扫描输出包含 `host_fingerprint`、`has_gpu`、`environment_kind` 和 `raw_summary`。

- [ ] **Step 4: 创建首版 recipe 清单和严格校验**

`recipes/minimax-h3-sdxl.json` 必须声明 `platforms: ["autodl", "chenyu"]`、ComfyUI `0.31.0`、Python `>=3.10`、24GB VRAM、80GB 空间，并引用：

```json
{
  "workflows": [
    "workflows/minimax_h3_t2v_turbo.json",
    "workflows/video_minimax_h3_i2v_uncensored_enhancer.json",
    "workflows/video_minimax_h3_r2v.json",
    "workflows/sdxl_image_api_template.json"
  ],
  "checks": [
    {"service": "sdxl", "resource_mode": "gpu_required"},
    {"service": "t2v", "resource_mode": "gpu_required"},
    {"service": "i2v", "resource_mode": "gpu_required"},
    {"service": "r2v", "resource_mode": "gpu_required"}
  ]
}
```

模型和节点项必须带 `filename`、`target_dir`、`size_bytes`、`sha256`、`primary_url`、`fallback_urls`、`shareable`；不把访问令牌写进 URL。加载器拒绝未知 `resource_mode`、绝对路径和缺失校验字段。

- [ ] **Step 5: 运行测试并提交**

运行：`python -m unittest console.tests.test_environment_scanner console.tests.test_environment_recipes -v; python -m json.tool recipes/minimax-h3-sdxl.json > $null`

预期：PASS，JSON 校验无输出错误。

```powershell
git add console/environment_scanner.py console/environment_recipes.py recipes/minimax-h3-sdxl.json console/tests/test_environment_scanner.py console/tests/test_environment_recipes.py console/CHANGELOG.md
git commit -m "feat: add environment scanner and deployment recipe"
```

### Task 4: 实现计划生成、空间估算和下载器

**Files:**
- Create: `console/environment_planner.py`
- Create: `console/environment_downloader.py`
- Create: `console/tests/test_environment_planner.py`
- Create: `console/tests/test_environment_downloader.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 写失败测试**

```python
def test_disk_estimate_includes_fifteen_percent_reserve(self):
    estimate = estimate_required_space([{"size_bytes": 1000}], temp_bytes=200, extract_bytes=300)
    self.assertEqual(estimate.required_bytes, 1725)

def test_insufficient_disk_blocks_plan_before_download(self):
    scan = {"disk": {"free_bytes": 100}}
    plan = build_plan(scan=scan, recipe=small_recipe)
    self.assertEqual(plan.status, "blocked")
    self.assertEqual(plan.error.code, "E-DISK")

def test_checksum_failure_never_promotes_part_file(self):
    with self.assertRaises(EnvironmentError) as ctx:
        finalize_download("model.safetensors.part", "model.safetensors", sha256="bad")
    self.assertEqual(ctx.exception.code, "E-CHECKSUM")
```

- [ ] **Step 2: 运行失败测试**

运行：`python -m unittest console.tests.test_environment_planner console.tests.test_environment_downloader -v`

预期：计划和下载器尚未定义。

- [ ] **Step 3: 实现复用/隔离决策与空间估算**

计划器比较扫描快照与 recipe：兼容现有 ComfyUI 时选择 `reuse`，程序/Python/节点版本冲突时选择 `isolated`，共享模型目录通过 `extra_model_paths.yaml` 接入。空间计算为模型本体 + 临时下载 + 解压空间，再乘 1.15；不足时返回 `blocked`，不创建下载任务。计划记录 recipe 版本、差异、风险、预计下载和预计剩余空间。

- [ ] **Step 4: 实现断点下载、备用源和校验**

下载器按 `aria2c -> Hugging Face -> ModelScope -> wget/curl` 探测；每次写入 `.part`，支持 HTTP Range、重试和取消。完成后先检查大小再 SHA256，成功后原子改名；失败源切换并保留脱敏错误。已通过校验的目标直接复用，不能重复下载。

- [ ] **Step 5: 运行测试并提交**

运行：`python -m unittest console.tests.test_environment_planner console.tests.test_environment_downloader -v`

预期：PASS；覆盖断点恢复、源切换、校验失败、磁盘不足和已存在文件复用。

```powershell
git add console/environment_planner.py console/environment_downloader.py console/tests/test_environment_planner.py console/tests/test_environment_downloader.py console/CHANGELOG.md
git commit -m "feat: add deployment planning and resumable downloads"
```

### Task 5: 实现部署执行器和无卡/有卡状态机

**Files:**
- Create: `console/environment_deployer.py`
- Create: `console/tests/test_environment_deployer.py`
- Modify: `console/task_store.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 写失败测试**

```python
def test_cpu_only_steps_finish_without_gpu(self):
    job = self.deployer.run(plan, has_gpu=False)
    self.assertEqual(job.status, "prepared_waiting_gpu")
    self.assertEqual(job.completed_steps[-1], "manifest")

def test_gpu_required_step_is_deferred_without_gpu(self):
    job = self.deployer.run(plan, has_gpu=False)
    self.assertEqual(job.deferred_steps, ["verify_sdxl", "verify_t2v", "verify_i2v", "verify_r2v"])

def test_gpu_validation_requires_all_four_outputs(self):
    result = self.deployer.finalize_verification({"sdxl": True, "t2v": True, "i2v": True, "r2v": False})
    self.assertEqual(result.status, "failed")
    self.assertNotEqual(result.status, "available")

def test_retry_skips_verified_download(self):
    self.deployer.retry_step("download_models")
    self.assertEqual(self.downloader.download_calls, [])
```

- [ ] **Step 2: 运行失败测试**

运行：`python -m unittest console.tests.test_environment_deployer -v`

预期：执行器和资源门控尚未定义。

- [ ] **Step 3: 实现可恢复步骤执行器**

按 `scan -> prepare_dirs -> create_venv -> install_comfyui -> install_nodes -> download_models -> configure_shared_models -> copy_workflows -> manifest -> verify_*` 执行。每步开始/完成/失败写入 `deployment_steps`，记录进度、脱敏消息、重试次数和时间。无卡只执行 `cpu_only`/可选步骤并结束为 `prepared_waiting_gpu`；有卡重新扫描后继续 `gpu_required` 步骤，只有 SDXL/T2V/I2V/R2V 全部成功且输出文件可播放/可打开才转 `available`。

- [ ] **Step 4: 实现冲突隔离、取消和单步重试**

兼容环境复用原程序但不覆盖其启动脚本；冲突时在远端 `<data-disk>/toonflow/environments/minimax-h3-sdxl-v1/` 建独立环境，模型通过共享目录和配置接入。取消只停止当前可中断步骤并保留已完成文件；重试仅允许 `failed`/`interrupted` 步骤，已校验文件直接跳过。

- [ ] **Step 5: 运行执行器测试并提交**

运行：`python -m unittest console.tests.test_environment_deployer -v`

预期：PASS；无卡状态不会显示可用，失败步骤可单独重试，四类验证互相独立。

```powershell
git add console/environment_deployer.py console/task_store.py console/tests/test_environment_deployer.py console/CHANGELOG.md
git commit -m "feat: add resumable gpu-aware environment deployment"
```

### Task 6: 接入后端 API 和后台任务

**Files:**
- Modify: `console/batch_console.py`
- Create: `console/environment_manager.py`
- Create: `console/tests/test_environment_api.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 写失败 API 测试**

```python
def test_scan_route_is_read_only(self):
    response = self.post_json("/api/environments/scan", {"platform": "autodl", "ssh_command": "ssh root@host"})
    self.assertEqual(response.status, 200)
    self.assertEqual(self.fake_session.install_calls, [])

def test_deploy_requires_plan_version_and_confirmation(self):
    response = self.post_json("/api/environments/deploy", {"plan_id": "p1", "confirm": False})
    self.assertEqual(response.status, 400)
    self.assertEqual(response.json["error_code"], "E-CONFIRMATION-REQUIRED")

def test_job_payload_is_redacted(self):
    response = self.get_json("/api/environments/jobs/j1")
    self.assertNotIn("private_key", response.text)
    self.assertNotIn("password", response.text)
```

- [ ] **Step 2: 运行失败测试**

运行：`python -m unittest console.tests.test_environment_api -v`

预期：新路由尚未注册而失败。

- [ ] **Step 3: 实现环境管理门面并注册路由**

在 `environment_manager.py` 实现 `EnvironmentManager`，其公开方法为 `scan_target()`、`make_plan()`、`start_deploy()`、`get_job()`、`retry_step()`、`cancel_job()`、`list_recipes()`、`get_manifest()`；它只编排 TaskStore、SSH、scanner、planner 和 deployer，不暴露任意 shell。然后在 `batch_console.py` 初始化门面并实现：

```text
POST /api/environments/scan
POST /api/environments/plan
POST /api/environments/deploy
GET  /api/environments/jobs/{id}
POST /api/environments/jobs/{id}/retry
POST /api/environments/jobs/{id}/cancel
GET  /api/environments/recipes
GET  /api/environments/manifest/{target_id}
```

`scan` 只读；`plan` 必须引用扫描快照和 recipe 版本；`deploy` 必须同时提交 `plan_id`、`recipe_version` 和 `confirm: true`；`retry` 仅接受失败/中断步骤；所有响应只返回脱敏消息、状态和下一步建议。后台线程使用已有服务生命周期，进程重启后从 SQLite 恢复未完成步骤。

- [ ] **Step 4: 运行后端回归测试**

运行：`python -m unittest console.tests.test_environment_api console.tests.test_task_store console.tests.test_service_diagnostics -v; python -m py_compile console/batch_console.py console/environment_*.py`

预期：PASS；既有任务控制和诊断路由行为不变。

- [ ] **Step 5: 提交本任务**

```powershell
git add console/batch_console.py console/tests/test_environment_api.py console/CHANGELOG.md
git commit -m "feat: expose cloud environment management api"
```

### Task 7: 设置页增加环境管理工作流

**Files:**
- Modify: `console/index.html`
- Create: `console/tests/test_environment_ui.py`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 写失败 UI 契约测试**

```python
REQUIRED_IDS = [
    "environmentPanel", "environmentPlatform", "environmentSshCommand",
    "environmentCredentialMode", "btnEnvironmentScan", "environmentScanSummary",
    "environmentRecipe", "environmentPlanSummary", "btnEnvironmentDeploy",
    "environmentJobSteps", "btnEnvironmentRetry", "btnEnvironmentCancel",
    "environmentVerificationResults", "environmentManifest",
]
REQUIRED_FUNCTIONS = [
    "scanEnvironment", "loadEnvironmentPlan", "deployEnvironment",
    "pollEnvironmentJob", "retryEnvironmentStep", "cancelEnvironmentJob",
    "renderEnvironmentVerification",
]
```

运行：`python -m unittest console.tests.test_environment_ui -v`，预期因 DOM/函数不存在而失败。

- [ ] **Step 2: 添加设置页分区和条件显示**

在现有设置抽屉中加入：连接信息、只读扫描结果、recipe 资源要求、计划确认、执行进度、四项验证结果和 manifest。密码/私钥字段使用 `type=password`，页面只显示“本次会话已提供”，不回填明文。无卡状态显示“准备完成，等待 GPU”，四个真实验证按钮置灰并标注“需要 GPU”。

- [ ] **Step 3: 接入 API、轮询和用户确认**

`scanEnvironment()` 只调用 `/scan`；计划页展示复用/隔离、下载大小、剩余空间、重启影响和风险；`deployEnvironment()` 在用户确认后才提交；执行页每 2 秒轮询 `/jobs/{id}`，支持暂停可中断步骤、单步重试和取消；开卡后提供“重新扫描并验证”，不重复下载已校验文件。

- [ ] **Step 4: 浏览器和源代码验证**

运行：`python -m unittest console.tests.test_environment_ui -v; python -m unittest discover -s console/tests -p 'test_*.py' -v`

启动 `python console/start_daemons.py`，访问 `http://127.0.0.1:8890`，在桌面和 390px 宽度检查设置页不横向溢出；使用 Fake API 验证扫描不会触发安装，计划未确认不能部署，失败步骤不会显示为旋转中。

- [ ] **Step 5: 提交本任务**

```powershell
git add console/index.html console/tests/test_environment_ui.py console/CHANGELOG.md
git commit -m "feat: add cloud environment settings workflow"
```

### Task 8: 文档、模拟验收和真实 GPU 验证

**Files:**
- Modify: `console/README.md`
- Modify: `CONFIG.md`
- Create: `docs/testing/cloud-environment-acceptance.md`
- Modify: `console/CHANGELOG.md`

- [ ] **Step 1: 编写用户操作和安全说明**

说明 AutoDL/晨羽智云开机后填写 SSH 命令、指纹确认、扫描、生成计划、确认无卡部署、开 GPU、重新扫描、依次验证 SDXL/T2V/I2V/R2V；说明 24GB 显存和至少 80GB 可用空间建议；说明密码只存在当前进程，停止控制台会清除会话凭据；说明无卡准备不等于可生成。

- [ ] **Step 2: 建立验收矩阵并运行模拟测试**

矩阵至少覆盖：三种远端环境分类、已有模型复用、节点/Python 冲突隔离、断点下载、磁盘不足、SSH 指纹变化、凭据脱敏、无卡终态、开卡复验、四项独立验证、单步重试、取消、进程重启恢复和 API 计划确认。

运行：

```powershell
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/*.py workflows/*.py
Get-ChildItem recipes -Filter *.json | ForEach-Object { python -m json.tool $_.FullName > $null }
git diff --check
```

- [ ] **Step 3: 仅在用户明确确认且 GPU 已开时做真实验证**

逐项运行 SDXL、T2V、I2V、R2V，记录服务器指纹、recipe 版本、prompt ID、耗时、输出路径和预览结果；不提供“一键全部真实生成”按钮，不重复下载已通过 SHA256 的模型。真实部署和生成会产生云端流量、磁盘和 GPU 费用，执行前在界面再次提示。

- [ ] **Step 4: 最终检查并提交**

确认 `console/CHANGELOG.md` 顶部包含本功能记录，记录测试命令、无卡/有卡状态语义、远程副作用和回滚方式。运行完整回归后提交：

```powershell
python -m unittest discover -s console/tests -p 'test_*.py' -v
python -m py_compile console/*.py workflows/*.py
git diff --check
git add console/README.md CONFIG.md docs/testing/cloud-environment-acceptance.md console/CHANGELOG.md
git commit -m "docs: add cloud environment deployment acceptance guide"
```

## 自查结果

- 规格中的 AutoDL/晨羽、三类环境识别、扫描/计划/执行分离、无卡 `prepared_waiting_gpu`、有卡四项验证、模型复用/隔离、下载源/断点/校验/15% 余量、SSH 指纹与凭据脱敏、SQLite 实体、API、设置页和验收矩阵均有对应任务。
- 计划未把自动购买/释放实例、任意远程 shell、任意工作流映射器或原整合包删除列入首版实现。
- 所有失败测试先于实现；每个代码任务都有精确文件、接口、命令和预期结果。
- 真实云端扫描/部署/生成必须在用户开机并确认可能产生费用后执行；本计划本身不连接远端、不下载模型。
