# 云端环境智能部署器设计

## 1. 背景与目标

当前项目依赖远程 ComfyUI、MiniMax H3 视频工作流和 SDXL 生图工作流。不同云平台的镜像、目录、Python、CUDA、自定义节点和模型状态差异很大，手工搭建容易出现“文件存在但工作流不能运行”的情况。

本功能为控制台增加清单驱动的云端环境管理能力，首版优先支持 AutoDL 和晨羽智云，目标是：

- 通过 SSH 识别干净系统、纯 ComfyUI 和整合包。
- 在执行前生成可审阅的安装计划、空间估算和风险提示。
- 优先复用兼容环境和已有模型；冲突时隔离安装，不破坏原整合包。
- 支持无卡模式完成环境准备，开卡后再完成真实验证。
- 让 MiniMax H3 视频和 SDXL 生图成为首个可部署、可验证的方案。
- 为后续二次元、写实、国风等模型方案提供扩展入口。

本设计只描述架构和行为，不在本阶段实现代码。

## 2. 范围

### 2.1 首版包含

- AutoDL、晨羽智云平台标签和平台差异适配。
- SSH 连接、主机指纹确认和会话内凭据。
- 只读扫描：系统、GPU、CUDA、磁盘、内存、Python、ComfyUI、节点、模型、端口和运行状态。
- 方案清单：MiniMax H3 视频 + SDXL 生图。
- 安装计划、空间估算、下载源选择、断点续传和校验。
- 现有环境复用、隔离环境、共享模型目录和软链接。
- 无卡部署、等待有卡、重新扫描和有卡真实验证。
- 进度持久化、断线续装、单步重试、取消和错误诊断。
- 设置页中的环境列表、计划确认页、执行进度页和验证结果页。

### 2.2 首版不包含

- 自动购买或释放云实例。
- 任意远程命令执行器。
- 自动修改或删除用户原整合包。
- 第一版自定义任意 ComfyUI 工作流映射器。
- 同时维护多台云服务器的自动负载均衡。

后续可通过 AutoDL/晨羽智云平台 API 增加自动开卡、关卡和端口发现，但不作为 SSH 部署的前置条件。

## 3. 核心原则

1. **先扫描，再计划，最后执行。** SSH 连接不会自动安装或覆盖远端内容。
2. **优先复用，冲突隔离。** 兼容时复用原环境；版本冲突时创建 ToonFlow 管理环境。
3. **模型共享，环境隔离。** 大模型放在共享目录，多个 ComfyUI 通过软链接接入。
4. **无卡可准备，有卡才验证。** 无卡阶段不宣称“环境可用”。
5. **每一步可恢复。** 下载、安装、启动和验证状态持久化，断线后从未完成步骤继续。
6. **用户确认高风险动作。** 下载、安装、重启和真实生成都显示影响后再执行。
7. **不泄露凭据。** 密码和私钥口令不写入日志、数据库、页面或接口响应。
8. **版本可追踪。** 方案、节点、模型、工作流和验证结果都记录版本与校验值。

## 4. 用户流程

```text
选择云平台和部署方案
        |
输入 SSH 命令、密码或私钥
        |
主机指纹确认
        |
只读扫描
        |
生成安装计划和空间估算
        |
用户确认
        |
无卡部署 / 有卡部署
        |
环境准备完成，等待有卡验证
        |
有卡重新扫描
        |
GPU 预检和真实生成测试
        |
环境可用
```

用户可在计划页选择“只做无卡准备”或“部署后立即验证”。在没有 GPU 时，所有真实生成按钮显示为“需要 GPU”，不会尝试使用 CPU 假装验证通过。

## 5. 两阶段资源模型

每个方案步骤声明 `resource_mode`：

```text
cpu_only       只需要 CPU、磁盘和网络
gpu_optional   有 GPU 时增强检查，无 GPU 也可继续
gpu_required   必须开卡后执行
```

### 5.1 无卡阶段

允许执行：

- 检测系统、Python、磁盘、内存、网络和权限。
- 创建 ToonFlow 管理目录和虚拟环境。
- 安装或更新 ComfyUI 及固定版本节点。
- 下载模型、工作流和依赖文件。
- 校验文件大小和 SHA256。
- 创建共享模型目录、软链接和 ComfyUI 配置。
- 检查工作流 JSON、节点类型、模型引用和目录结构。
- 执行不依赖 CUDA 的 Python 导入检查。
- 生成启动脚本、环境清单和待验证项目。

无卡阶段的终态为 `prepared_waiting_gpu`，含义是“环境已准备，尚未证明可以生成”。

### 5.2 有卡阶段

用户在云平台切换到 GPU 实例后，点击“重新扫描并验证”：

- 重新确认主机指纹、实例状态和 SSH 连接。
- 检测 GPU、CUDA、显存和 ComfyUI 进程。
- 复用无卡阶段已校验的文件，不重新下载。
- 补充 GPU 阶段依赖并启动或重启 ComfyUI。
- 执行 `/system_stats`、`/object_info` 和工作流预检。
- 分别执行 SDXL、MiniMax H3 T2V、I2V、R2V 最小真实测试。
- 保存输出文件、耗时、显存、提示词、工作流版本和错误信息。

只有四类测试都按方案要求通过，环境状态才变为 `available`。单项成功不能替代其他模式的验证。

## 6. 方案清单

方案清单是版本化的结构化文件，不把安装逻辑硬编码在页面或路由中。首版方案 ID 为 `minimax-h3-sdxl`。

每个方案至少包含：

```json
{
  "id": "minimax-h3-sdxl",
  "version": "1.0.0",
  "platforms": ["autodl", "chenyu"],
  "comfyui": {"min_version": "0.31.0"},
  "requirements": {
    "gpu_vram_gb": 24,
    "disk_free_gb": 80,
    "python": ">=3.10"
  },
  "packages": [],
  "custom_nodes": [],
  "models": [],
  "workflows": [],
  "checks": [],
  "steps": []
}
```

模型项包含文件名、目标目录、文件大小、SHA256、主下载源、备用下载源和是否可共享。节点项包含仓库、固定版本、安装命令类型和重启要求。检查项包含资源模式、输入、预计耗时和成功条件。

首版方案至少引用：

- MiniMax H3 T2V、I2V、R2V 所需的 UNET、CLIP、VAE、LoRA 和节点。
- SDXL `sd_xl_base_1.0.safetensors` 及标准节点工作流。
- 项目内置的 T2V、I2V、R2V、SDXL API 工作流。

## 7. 远端目录策略

默认管理目录由方案和远端数据盘探测结果决定，不在代码中写死绝对路径。推荐结构如下：

```text
<data-disk>/toonflow/
├── environments/
│   └── minimax-h3-sdxl-v1/
├── models/
│   ├── checkpoints/
│   ├── diffusion_models/
│   ├── text_encoders/
│   ├── vae/
│   └── loras/
├── downloads/
├── manifests/
└── logs/
```

扫描到兼容的现有 ComfyUI 时，计划可以选择复用其程序目录，同时把共享模型目录加入 `extra_model_paths.yaml`。扫描到程序或节点冲突时，在 `environments/` 创建独立环境；旧目录只读检查，不自动删除或覆盖。

## 8. 下载与空间估算

下载器按远端可用能力选择：

1. `aria2c` 多线程断点下载。
2. Hugging Face 镜像或官方源。
3. ModelScope。
4. `wget`/`curl` 普通续传。

每个文件下载前执行：

- 检查目标文件是否已经通过校验。
- 检查临时文件、剩余磁盘和写权限。
- 计算模型本体、临时文件、解压空间和 15% 安全余量。
- 选择可用下载源并记录源地址（日志中不含凭据）。

下载结束后校验大小和 SHA256，失败源自动切换；校验失败的临时文件不能被当作已安装文件。下载任务支持暂停、断线重连、单文件重试和整个计划继续。

空间不足时计划状态为 `blocked_disk`，不得开始下载，并显示至少还需要的空间和可释放的临时文件。

## 9. SSH 与远程执行安全

- 支持 SSH 命令解析出的主机、端口、用户名、密码、私钥和私钥口令。
- 密码和私钥口令仅保存在本次控制台进程内存。
- 可选使用 Windows 凭据管理器保存凭据引用，不保存明文到 SQLite。
- 首次连接显示主机指纹，用户确认后才继续；不关闭主机密钥校验。
- 远程命令由方案步骤生成，前端只能选择步骤和参数，不能直接提交任意 shell 字符串。
- 不把密码、私钥、API Key、Bearer Token 放进命令行参数、URL、任务响应或普通日志。
- 远端临时脚本使用唯一目录，完成后清理；失败时保留脱敏日志和步骤状态。
- 默认不修改原整合包的启动脚本、工作流和模型文件。

首版 SSH 适配器优先支持 Windows 可稳定使用的密码和私钥连接方式；若本机缺少所需适配器，页面应明确提示安装前置组件，而不是把密码拼进 `ssh` 命令行。

## 10. 本地数据模型

本地 SQLite 增加以下逻辑实体：

```text
environment_targets
  id, platform, host, port, username, display_name, host_fingerprint

environment_scans
  id, target_id, scan_time, gpu, cuda, disk, python, comfyui, raw_summary

deployment_plans
  id, target_id, recipe_id, recipe_version, status, estimate_json

deployment_steps
  id, plan_id, step_key, status, progress, message, retry_count,
  started_at, finished_at

environment_manifests
  id, target_id, recipe_id, installed_json, verified_json, generated_at
```

凭据不进入上述实体。扫描原始输出必须在入库前脱敏；详细日志按任务目录保存，并使用统一脱敏器。

## 11. 本地接口

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

接口约定：

- `/scan` 只读，不安装、不下载、不重启。
- `/plan` 根据扫描快照和方案版本生成差异、空间估算和风险。
- `/deploy` 必须携带计划版本和明确确认字段。
- `/jobs/{id}` 返回步骤进度、脱敏消息和下一步建议。
- `/retry` 只能重试失败或中断步骤，已校验文件不重复下载。
- `/cancel` 停止当前可中断步骤并保留状态，不删除已完成环境。
- `/manifest` 返回已安装版本、文件校验和验证结果，不返回凭据。

## 12. 状态和错误模型

环境状态：

```text
disconnected
scanned
plan_ready
deploying
prepared_waiting_gpu
verifying
available
blocked
failed
```

标准错误码至少包括：

| 错误码 | 含义 | 页面动作 |
|---|---|---|
| `E-SSH-AUTH` | SSH 鉴权失败 | 修改凭据后重试 |
| `E-SSH-FINGERPRINT` | 主机指纹变化 | 停止并人工确认 |
| `E-PERMISSION` | 目录或 sudo 权限不足 | 选择可写目录或账号 |
| `E-DISK` | 磁盘空间不足 | 清理或扩容后重试 |
| `E-PYTHON` | Python 版本不匹配 | 隔离创建虚拟环境 |
| `E-CUDA` | CUDA/GPU 不满足方案 | 开卡或更换方案 |
| `E-NODE` | 节点安装或版本冲突 | 单步重试或隔离环境 |
| `E-DOWNLOAD` | 下载源或网络失败 | 切换源并续传 |
| `E-CHECKSUM` | 文件校验失败 | 删除临时文件重下 |
| `E-WORKFLOW` | 工作流节点/模型不满足 | 查看缺失项 |
| `E-GPU-REQUIRED` | 当前为无卡模式 | 开卡后重新验证 |
| `E-VERIFY` | 真实生成失败 | 查看输出和节点错误 |

## 13. 设置页交互

设置中新增“云端环境”区域，分为：

1. **连接信息**：平台、别名、SSH 命令、密码/私钥、主机指纹。
2. **环境扫描**：只读扫描按钮和硬件、磁盘、ComfyUI 摘要。
3. **方案选择**：方案版本、资源要求、预计下载和预计剩余空间。
4. **计划确认**：复用、安装、隔离、下载、重启和风险列表。
5. **执行进度**：步骤列表、速度、剩余时间、暂停、重试、取消。
6. **验证结果**：SDXL、T2V、I2V、R2V 独立结果和输出预览。
7. **环境清单**：已安装节点、模型、工作流版本和最后验证时间。

页面必须明确显示“无卡准备完成”与“有卡验证通过”的区别。真实测试按钮在无卡状态置灰，并说明不会因为无卡而误报成功。

## 14. 验收标准

首版验收至少包括：

1. AutoDL 和晨羽智云能完成 SSH 扫描。
2. 干净系统、纯 ComfyUI、整合包都能生成不同计划。
3. 已有且校验通过的模型不会重复下载。
4. 节点或 Python 冲突时不破坏原整合包。
5. 下载中断后可断点续传。
6. 磁盘不足时执行前阻止部署。
7. 无卡模式可完成目录、依赖、节点、模型和工作流准备。
8. 无卡模式不会把环境标记为可生成。
9. 开卡后重新扫描能复用无卡阶段成果。
10. SDXL、T2V、I2V、R2V 分别完成真实验证。
11. 任意失败步骤可单独重试，成功文件不重复下载。
12. 日志、数据库、页面和接口响应中无明文密码或密钥。
13. 所有代码、规则、界面和工作流改动都更新 `console/CHANGELOG.md`。
14. 测试覆盖扫描、计划计算、空间估算、下载恢复、脱敏、状态机和模拟 SSH。

## 15. 后续扩展

- AutoDL/晨羽智云 API：自动开卡、等待实例、重新连接、验证后释放。
- 更多漫剧方案：二次元、写实、国风，以及不同显存档位的模型组合。
- 自定义 ComfyUI API 工作流导入和依赖分析。
- 多服务器环境列表和一键切换默认生成服务器。
- 方案导出、迁移和 Docker/镜像构建。
