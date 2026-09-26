# 更新日志（CHANGELOG）

> 本控制台**每次更新**（代码、规则、界面、工作流任一改动）都必须在此记录一条。
> 规则见文末「更新说明怎么写」，做不到的更新不算完成。

---

## 2026-09-26 - v0.13.63 - 修复 Git 镜像失败后的目录阻塞
### 本次更新内容

- GitHub 节点的首个镜像克隆失败后，自动清理留下的空目录，让后续镜像可以继续尝试。
- 已存在节点仓库会先切换 `origin` 到当前回退地址再 fetch，避免一直重试失效的旧地址。

### 验证方式

- `python -m unittest console.tests.test_environment_ssh console.tests.test_environment_downloader -v`
- `python -m unittest discover -s console/tests -p "test_*.py"`
- `python -m py_compile console/environment_ssh.py`
- `git diff --check`

### 影响与注意事项

- 仅清理目标节点目录下的空目录；非空且不是 Git 仓库的目录仍会拒绝覆盖。
- 需要重试“下载模型”步骤，旧的失败状态不会自动重新执行。

## 2026-09-26 - v0.13.62 - 国内下载源优先并扩展 GitHub 回退
### 本次更新内容

- Hugging Face 下载优先使用 `hf-mirror.com`，官方地址作为最后回退，避免云服务器先在不可达的官方源上长时间等待。
- GitHub 节点增加 `ghfast.top`、`gh-proxy.com`、`ghproxy.net` 三个候选代理，官方 GitHub 最后尝试。
- 保留断点续传、大小和 SHA256 校验；镜像返回错误内容时不会覆盖正式模型文件。

### 验证方式

- `python -m unittest console.tests.test_environment_downloader -v`
- `python -m unittest discover -s console/tests -p "test_*.py"`
- `python -m py_compile console/environment_downloader.py`
- `git diff --check`

### 影响与注意事项

- 需要重启控制台后重新生成部署计划并重试“下载模型”步骤；旧任务不会自动改变已记录的下载源。
- 代理站点均为无凭据公开地址，最终文件仍必须通过 recipe 中的 SHA256 校验。

## 2026-09-25 - v0.13.61 - 持久化 SSH 命令并增加 GitHub 国内回退
### 本次更新内容

- SSH 登录命令同时保存到项目配置的非敏感字段，解决使用不同本机地址或浏览器存储隔离时无法回填的问题。
- SSH 密码、私钥和 API Key 不会写入该字段；页面仍只自动回填 SSH 命令。
- GitHub 节点克隆增加国内代理回退，并为 Git 连接增加超时和低速检测。

### 验证方式

- `python -m unittest console.tests.test_environment_api_routes console.tests.test_environment_ui console.tests.test_environment_downloader -v`
- `python -m unittest discover -s console/tests -p "test_*.py"`
- `python -m py_compile console/batch_console.py console/environment_downloader.py console/environment_ssh.py`
- `git diff --check`

### 影响与注意事项

- SSH 命令会写入项目根目录 `config.json`，仅包含连接命令，不包含密码。
- GitHub 直连失败时才尝试代理地址；节点内容仍由 Git 克隆结果确认。

## 2026-09-25 - v0.13.60 - 统一增加 Hugging Face 国内镜像回退
### 本次更新内容

- 下载器现在会自动识别 `huggingface.co` 地址并追加对应的 `hf-mirror.com` 地址，配方无需逐项手工填写镜像。
- 官方源、配方显式回退源和自动镜像源会去重并按顺序尝试；所有来源仍执行原有大小与 SHA256 校验。

### 验证方式

- `python -m unittest console.tests.test_environment_downloader -v`
- `python -m unittest discover -s console/tests -p "test_*.py"`
- `git diff --check`

### 影响与注意事项

- 当前自动镜像仅针对 Hugging Face 文件下载；GitHub 节点不自动使用不稳定代理，失败时会保留原始错误来源。

## 2026-09-25 - v0.13.59 - 增加 Hugging Face 镜像回退与连接超时
### 本次更新内容

- 为公开 Hugging Face 模型增加 `hf-mirror.com` 回退地址；主站连接失败时自动切换。
- 远端 `curl`/`wget` 增加连接超时和重试参数，避免网络不可达时长时间卡在下载步骤。

### 验证方式

- `python -m unittest console.tests.test_environment_ssh console.tests.test_environment_downloader -v`
- `python -m unittest discover -s console/tests -p "test_*.py"`
- `git diff --check`

### 影响与注意事项

- 镜像只作为公开模型的备用来源，文件仍必须通过配方 SHA256 校验后才会落盘。
- 如果云服务器同时无法访问 Hugging Face 镜像和 GitHub，任务会显示具体失败来源。

## 2026-09-25 - v0.13.58 - 记住 SSH 登录命令但不保存密码
### 本次更新内容

- 环境部署设置会将最近使用的 SSH 登录命令保存到当前浏览器的 `localStorage`，下次打开页面自动回填。
- SSH 密码、私钥和其他凭据仍只用于当前操作，不写入浏览器、本地配置或数据库。

### 验证方式

- `python -m unittest console.tests.test_environment_ui -v`
- `python -m unittest discover -s console/tests -p "test_*.py"`
- `git diff --check`

### 影响与注意事项

- 清除浏览器站点数据会同时清除已记住的 SSH 命令；密码字段始终保持不记忆。

## 2026-09-25 - v0.13.57 - 将部署下载迁移到远端 SSH 主机
### 本次更新内容

- 模型下载改为在扫描到的远端数据盘执行，使用断点续传、文件大小和 SHA256 校验后再替换正式文件。
- ComfyUI 节点资源改为通过受限的 Git 克隆 recipe 安装到远端 `custom_nodes`，不再把 Git URL 当作普通文件下载。
- 部署失败消息保留下载源和远端错误摘要，便于直接使用“重试步骤”定位问题；无 GPU 时仍可完成 CPU 准备阶段。

### 验证方式

- `python -m unittest console.tests.test_environment_ssh console.tests.test_environment_downloader console.tests.test_environment_deployer -v`
- `python -m unittest discover -s console/tests -p "test_*.py"`
- `python -m py_compile console/environment_ssh.py console/environment_downloader.py console/environment_deployer.py console/environment_manager.py`
- `git diff --check`

### 影响与注意事项

- 部署必须使用当前扫描建立的 SSH 会话；会话失效时会明确提示重新扫描，不会退回本机下载。
- 下载和克隆需要远端系统具备 `curl` 或 `wget`、`sha256sum`、`git`；GPU 不参与环境准备阶段。

## 2026-09-25 - v0.13.53 - 修复环境资源探测误报并避免增强模型阻塞部署
### 本次更新内容

- 远端模型探针跟随 ComfyUI 模型软链接，并在配置的 ComfyUI/数据盘路径下递归发现 `models` 目录，兼容共享模型挂载；重复路径会去重。
- 没有公开下载源的增强模型改为风险提示，不再把基础环境部署整体标记为“需要人工提供”并阻塞按钮。
- 计划页在 `blocked` 时明确说明尚未创建部署任务，解释“重试步骤/取消任务”为什么不可用，避免把计划阻塞误认为按钮故障。
### 验证方式

- `python -m unittest console.tests.test_environment_scanner console.tests.test_environment_planner console.tests.test_environment_ui -v`
- `python -m py_compile console/environment_ssh.py console/environment_scanner.py console/environment_planner.py`
- `git diff --check`
### 影响与注意事项

- 修改后需重启控制台并重新扫描远端环境；旧扫描快照不会自动补充模型清单。
- 有官方来源的模型仍会按实际缺失文件和磁盘空间检查；磁盘不足时继续阻塞，避免启动后必然失败。
- 私有增强模型缺失时基础部署可以继续，但对应增强工作流的最终验证仍会提示缺少该资源。

## 2026-09-25 - v0.13.54 - 复用整合包中的同名模型，避免重复下载导致磁盘阻塞
### 本次更新内容

- 发现远端已有同名模型时，即使整合包文件大小与 recipe 清单不同，也优先复用现有文件，并将差异保留为风险提示。
- 避免因为量化/缩放版本的清单大小差异，把已有模型错误加入下载清单，导致 22 GB 数据盘被错误判定为无法部署。
### 验证方式

- `python -m unittest console.tests.test_environment_planner console.tests.test_environment_scanner console.tests.test_environment_ui -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- `git diff --check`
### 影响与注意事项

- 同名文件会在部署后的工作流验证中继续检查；如果实际版本不兼容，验证步骤会失败并允许单独重试。
- 配方中完全缺失且有可靠下载源的模型仍会进入下载清单，并按可用空间阻塞部署。

## 2026-09-25 - v0.13.55 - 识别 MiniMax H3 量化与安全变体
### 本次更新内容

- 计划器识别 MiniMax H3 的 `fp8_scaled`、`heretic`、Turbo LoRA 和 generation-tail 变体，并在同一模型目录下复用已安装变体。
- 计划结果显示实际采用的远端文件名，保留“未找到配方同名文件/已复用兼容变体”的风险提示，避免把几十 GB 的已安装权重重复加入下载清单。
### 验证方式

- `python -m unittest console.tests.test_environment_planner -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- `git diff --check`
### 影响与注意事项

- 变体匹配仅限 MiniMax H3 已知模型族、同一 ComfyUI `target_dir`，不会用任意文件冒充模型。
- 变体最终是否能被当前 ComfyUI 节点接受，仍由部署后的 SDXL/T2V/I2V/R2V 验证确认。

## 2026-09-25 - v0.13.56 - 实时显示环境部署进度
### 本次更新内容

- 部署器增加逐步骤进度回调，完成扫描、目录准备、模型下载或验证步骤后立即更新任务状态。
- 页面显示当前“执行中”步骤，不再在长时间下载期间把所有步骤都显示为“待执行”。
- 部署线程异常或步骤失败会即时进入任务结果，用户可以看到失败步骤并使用重试/取消控制。
### 验证方式

- `python -m unittest console.tests.test_environment_deployer console.tests.test_environment_ui -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- `python -m py_compile console/environment_deployer.py console/environment_manager.py`
- `git diff --check`
### 影响与注意事项

- 需要重启控制台并刷新页面后生效；部署中的已有旧任务不会补发历史进度。
- 进度回调只更新 SQLite/内存状态，不会改变远端部署步骤的执行顺序。

## 2026-09-25 - v0.13.52 - 修复远端模型探针误报 SSH 认证失败
### 本次更新内容

- 修复远端模型/节点探针在可选目录不存在时返回非零退出码，导致已有扫描输出被误判为 `E-SSH-AUTH` 的问题。
- 探针仍只读取配置的 ComfyUI 与数据盘目录；目录不存在时按空目录处理并正常完成扫描。
### 验证方式

- `python -m unittest console.tests.test_environment_ssh -v`
- `python -m unittest discover -s console/tests -p "test_*.py"`
- `python -m py_compile console/environment_ssh.py`
- `git diff --check`
### 影响与注意事项

- 需要重启控制台服务后重新点击“扫描远端环境”；不会改变 SSH 密码、指纹或远端文件。

## 2026-09-25 - v0.13.51 - 完善远端模型复用与部署资源校验
### 本次更新内容

- 修正 MiniMax H3 文本编码器官方下载地址，指向官方仓库的 `text_encoders` 目录。
- 工作流模型引用提取覆盖 MiniMax H3 生成尾模型，并纳入部署配方资源校验。
- 远端扫描发现已安装且匹配的模型/节点时直接复用；人工提供资源未找到时阻塞部署并返回 `E-RESOURCE`，避免生成中途才暴露缺失模型。
- 配方补充官方模型大小与 SHA256；没有可靠下载来源的人工资源明确标记为不可自动管理。
### 验证方式

- `python -m unittest discover -s console/tests -p "test_*.py"`
- `python -c "import pathlib,py_compile; [py_compile.compile(str(path), doraise=True) for path in pathlib.Path('console').glob('environment_*.py')]"`
- `python -m json.tool recipes/minimax-h3-sdxl.json > $null`
- `git diff --check`
### 影响与注意事项

- 部署计划会按扫描到的文件名、目标目录和大小判断复用；大小不一致的模型会保留风险并重新纳入下载。
- 人工资源仍需用户预先放入对应 ComfyUI 模型目录，系统不会尝试从未知来源下载。
### 失败码 / 错误提示变化

- 新增 `E-RESOURCE`：配方声明的人工资源未在远端扫描结果中找到时返回该错误，并列出缺失文件名。

---

## 2026-09-25 - v0.13.50 - 复用远端已安装模型并显示实际下载清单
### 本次更新内容

- 后端：新增只读 `model_probe`，扫描配置的 ComfyUI / 数据盘模型目录和 `custom_nodes`，记录文件名、目标目录、大小及路径。
- 计划器：按资源类型、目标目录和文件名匹配远端清单；大小一致的模型和已存在节点直接复用，大小不一致的模型标记风险并重新纳入下载。
- 前端：扫描结果显示已发现模型/节点，部署计划显示复用资源和实际需要下载的资源，避免把已安装模型重复计入磁盘需求。
### 验证方式

- `python -m unittest console.tests.test_environment_ui console.tests.test_environment_ssh console.tests.test_environment_scanner console.tests.test_environment_planner console.tests.test_environment_api`：37 项通过。
- `model_probe` 仅接受 `comfy_path` 和 `data_path`，不接受任意 shell 参数；扫描命令只读，不安装、不下载、不启动服务。
### 影响与注意事项

- 需要重启控制台服务后重新执行“扫描远端环境”，旧扫描记录不会自动补充模型清单。
- 配方中模型大小仍需准确；远端文件大小不匹配时会显示风险并按需重新下载。
### 失败码 / 错误提示变化

- 无新增错误码；磁盘不足仍使用 `E-DISK`，模型大小不匹配显示在计划风险中。

---

## 2026-09-25 - v0.13.49 - 修复远端环境扫描结果为空
### 本次更新内容

- 修复真实 SSH 探针返回普通文本时未被解析，导致平台、GPU、磁盘、Python 和 ComfyUI 全部显示未检测到的问题。
- 增加对 `uname`、`nvidia-smi`、`df`、Python 版本和 ComfyUI 入口路径输出的兼容解析。
- 兼容 `python3 -c 'import sys; print(sys.version)'` 返回的纯版本字符串格式。
- 使用设置页选择的云平台作为主机名无法识别时的后备值，避免 AutoDL 等连接域名显示为 `unknown`。
- 保留测试夹具使用结构化字典的兼容性，避免影响已有部署规划逻辑。

### 验证方式

- 新增普通 SSH 文本输出回归测试。
- 新增 Python `sys.version` 输出回归测试。
- 新增平台选择后备值回归测试。
- 全量控制台测试、Python 编译、配方 JSON 校验和 `git diff --check`。

### 影响与注意事项

- 需要重启控制台服务后重新点击“扫描远端环境”。
- 扫描仍为只读探针，不会安装依赖、下载模型或启动 ComfyUI。

---

## 2026-09-25 - v0.13.48 - SSH 密码自动认证与一键环境扫描
### 本次更新内容

- 用户只需输入 SSH 命令和密码即可完成首次环境扫描。
- 通过临时 `SSH_ASKPASS` helper 完成认证，密码不写入命令行、日志、配置或 SQLite。
- 首次主机指纹由后台记录，后续变化默认阻止，并提供页面内“重新建立信任”按钮。
- 保留私钥和 SSH Agent 兼容方式；本次未实现远程安装、模型下载和 GPU 生成。

### 验证方式

- 定向 SSH、环境存储、环境 API 和环境设置页测试。
- 全量控制台测试、Python 编译、配方 JSON 校验和 `git diff --check`。

### 影响与注意事项

- 首次扫描不再要求用户输入或确认主机指纹；指纹变化时需在页面确认当前实例后重新建立信任。
- 密码只存在本次扫描的进程内存和子进程环境，扫描结束后立即清理临时 helper。

---

## 2026-09-25 - v0.13.47 - 兼容 AutoDL SSH 主机指纹协商
### 本次更新内容

- 修复 Windows 自带 `ssh-keyscan` 与晨羽智云/AutoDL SSH 服务端 KEX 协商失败导致无法获取指纹的问题。
- 指纹观察改为一次不执行远端命令的 SSH 握手，显式使用兼容 KEX，并从临时 `known_hosts` 计算主机指纹。
- 远端探针只信任刚才用户确认过的主机公钥；临时 `known_hosts` 和私钥文件在命令结束后清理。

### 验证方式

- `python -m unittest console.tests.test_environment_ssh console.tests.test_environment_api console.tests.test_environment_api_routes console.tests.test_environment_deployer console.tests.test_environment_scanner console.tests.test_environment_planner console.tests.test_environment_recipes console.tests.test_environment_store console.tests.test_environment_ui -v`（40 项通过）
- `python` 调用项目 `SSHSession.observe_fingerprint` 连接 `connect.nmb2.seetacloud.com:18078`，成功得到 `SHA256:liZ36vNCsNcNdXeWs4f+g5ZIhPM/ZihP834vxs8Ulqc`
- 兼容握手实测成功写入 ED25519 主机公钥；未提供认证时的 `Permission denied` 属于预期，不执行任何远端探针。

### 影响与注意事项

- 设置页首次扫描流程不变：获取指纹后核对并勾选，再次扫描执行环境探针。
- 本次只修复 SSH 主机指纹协商；真实远端安装、模型下载和 GPU 验证仍未接入，暂不要点击“确认并开始部署”。
- `E-SSH-FINGERPRINT` 现在仅表示无法观察或解析主机公钥；认证失败仍返回 `E-SSH-AUTH` 或 `E-PERMISSION`。

---

## 2026-09-25 - v0.13.46 - SSH 主机指纹首次连接确认
### 本次更新内容

- SSH 扫描首次连接自动调用 `ssh-keyscan` 获取真实主机公钥指纹；首个请求只返回指纹，不执行远端探针。
- 设置页收到 `E-SSH-FINGERPRINT` 后自动填入指纹并提示用户核对，用户勾选确认后再次点击扫描才会执行环境探针。
- 私钥内容仅在单次 SSH 命令期间写入权限为 600 的临时文件，命令结束立即清理；密码-only 登录明确返回可操作的认证错误。

### 验证方式

- `python -m unittest discover -s console/tests -p "test_*.py" -v`（126 项通过）
- `python -m py_compile`（`console/*.py` 与 `workflows/*.py` 全部通过）
- `python -m json.tool`（`recipes/*.json` 通过）
- `git diff --check`

### 影响与注意事项

- 现有配置和 SQLite 数据结构不变；首次扫描会多一次只读的主机指纹获取请求。
- 当前控制台不能安全地通过非交互 SSH 传递密码；请使用 SSH 私钥或已配置的 SSH Agent。密码-only 会在确认指纹后以 `E-SSH-AUTH` 明确拒绝，不会执行远端探针。
- 本轮仍未执行真实 AutoDL/晨羽智云部署、模型下载或 GPU 验证；recipe 的真实远端安装适配器和资源摘要仍需后续接入。

---

## 2026-09-25 - v0.13.45 - 云端环境部署控制与重试状态同步
### 本次更新内容

- 设置页补齐环境部署控制事件：扫描、生成计划、开始部署、重试步骤、取消任务、凭据模式切换和配方加载均连接到后端接口。
- 修复 `prepared_waiting_gpu` 状态下错误禁用重试按钮的问题；重试下拉框现在只展示失败步骤和等待 GPU 验证的步骤。
- 修复手动重试后的任务状态同步：GPU 延迟验证成功会更新已完成/失败/延期步骤和任务状态，失败重试会保留失败状态并通过任务查询接口返回。

### 验证方式

- `python -m unittest discover -s console/tests -p "test_*.py" -v`（120 项通过）
- `python -m py_compile console\*.py workflows\*.py`
- `python -m json.tool recipes\minimax-h3-sdxl.json`
- `node --check`（以 UTF-8 提取的 `console/index.html` 内嵌脚本）
- `git diff --check`

### 影响与注意事项

- 现有 SQLite 数据结构和启动方式不变；新增控制仅影响环境部署任务的前端操作与状态展示。
- 当前仍未接入真实 AutoDL/晨羽智云远端安装命令、真实模型下载、工作流复制或真实 GPU 验证；这些步骤仍以可恢复的显式步骤和注入式验证器提供接口，不能据此宣称远端环境已完成部署。
- SSH 密码、私钥和 API Key 仍只保存在当前 SSH 会话内存，不写入 SQLite、配置、日志或 manifest。

---

## 2026-09-25 - v0.13.44 - 云端环境管理 API 与部署状态机
### 本次更新内容

- 增加可恢复环境部署状态机：无 GPU 时完成 CPU/文件准备并停在 `prepared_waiting_gpu`，开卡后独立执行 SDXL、T2V、I2V、R2V 四项验证，全部通过才标记 `available`。
- 增加部署步骤记录、取消、失败步骤重试和已校验模型跳过逻辑；部署 manifest 写入 SQLite，便于进程重启后查看。
- 增加环境管理 API：扫描、计划、部署确认、任务查询、单步重试、取消、recipe 列表和 manifest 查询。
- 所有远端凭据只存在当前 SSH 会话内存，API/日志响应使用脱敏内容；部署接口必须携带匹配的 recipe 版本和 `confirm: true`。

### 验证方式

- `python -m unittest console.tests.test_environment_deployer console.tests.test_environment_api console.tests.test_environment_api_routes -v`
- `python -m py_compile console/batch_console.py console/environment_*.py`

### 影响与注意事项

- API 路由加载后需重启控制台服务；扫描不会触发安装或下载，部署确认后才会产生远端磁盘/流量/GPU 费用。
- 首版安装步骤保留为显式可恢复步骤，recipe 适配器接入前不会覆盖已有 ComfyUI 启动脚本。

## 2026-09-25 - v0.13.42 - 云端环境计划与可恢复下载
### 本次更新内容

- 增加环境计划器，按模型本体、临时下载、解压空间并预留 15% 余量，空间不足时直接返回 `E-DISK`，不创建下载任务。
- 根据现有 ComfyUI/Python 版本自动选择复用或独立环境，并输出差异、风险、下载清单和预计剩余空间。
- 增加 `.part` 断点下载、备用源切换、大小与 SHA256 校验、已验证文件复用和取消检查；校验失败不会提升临时文件。

### 验证方式

- `python -m unittest console.tests.test_environment_planner console.tests.test_environment_downloader -v`

### 影响与注意事项

- 下载目标必须提供真实的 64 位 SHA256；recipe 中的占位摘要不会被下载器视为已验证。
- 下载器可注入传输函数，便于后端任务和离线测试复用；默认实现使用 HTTP Range 续传。

## 2026-09-25 - v0.13.41 - 云端环境只读扫描与 MiniMax H3/SDXL 配方
### 本次更新内容

- 增加 AutoDL/晨羽智云环境的只读扫描器，收集 GPU、CUDA、磁盘、Python、ComfyUI、节点、模型、端口和进程摘要，并区分纯净系统、纯 ComfyUI 与整合包。
- 增加 `minimax-h3-sdxl` 1.0.0 配方，声明 MiniMax H3 视频、SDXL 生图的工作流、四类 GPU 验证项、资源校验字段和 15% 余量所需的硬件门槛。
- recipe 加载器拒绝绝对路径、缺少 SHA256/大小/备用源字段、非法资源模式及 URL 中的访问凭据。

### 验证方式

- `python -m unittest console.tests.test_environment_scanner console.tests.test_environment_recipes -v`
- `python -m json.tool recipes/minimax-h3-sdxl.json > $null`

### 影响与注意事项

- 扫描阶段只执行固定 probe，不安装、下载、重启或修改远端文件。
- 配方中的零值 SHA256 表示供应商尚未提供可核对摘要；实际部署前下载器会拒绝将其视为已验证文件，需替换为官方摘要。

## 2026-09-24 - v0.13.40 - 文生图测试需求输入与结果预览
### 本次更新内容

- 文生图诊断增加“测试生成需求”输入框，真实测试会把用户输入原样传给当前选择的 Agnes/OpenAI/Boogu 或 ComfyUI 生图流程。
- 生成成功后在设置卡片内显示最新图片预览，并提供原图打开链接、提供商、模型、耗时、文件名和实际需求信息。
- 新一次生成失败时保留上一张成功预览，同时在状态区显示本次失败原因，避免结果被清空。
- ComfyUI SDXL 诊断工作流支持自定义提示词；云端图片适配器不再使用写死的测试提示词。
- 修复输出目录中的 PNG/JPEG/WebP/GIF 被 `/media/` 错误按视频类型返回的问题，确保本地 ComfyUI 诊断图可以在浏览器预览。

### 验证方式

- `python -m unittest console.tests.test_service_diagnostics console.tests.test_settings_diagnostics_ui console.tests.test_task_control_api -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- 浏览器模拟自定义提示词提交、图片加载、结果元数据及失败后保留旧预览。
- `node --check`（提取后的前端脚本）
- `python -m py_compile console/batch_console.py console/service_diagnostics.py`
- `git diff --check`

### 影响与注意事项

- “检查当前生图接口”仍不会生成图片或产生生图费用；只有确认“真实生图测试”后才会提交生成。
- 云端预览使用供应商返回的图片 URL；ComfyUI 预览使用已下载到输出目录的本地文件。
- 更新后需重启控制台后端以加载自定义提示词参数和本地图片 MIME 类型修复，浏览器再执行 `Ctrl+F5`。

## 2026-09-24 - v0.13.39 - 生图诊断入口去重与结果定位修复
### 本次更新内容

- ComfyUI 服务器区域删除重复的“测试生图”和旧“连接测试”，统一保留一个“检查连接”入口；视频工作流测试保持独立。
- 文生图卡片作为唯一的生图诊断入口，“检查当前生图接口”只检查配置与连接，“真实生图测试”按当前选择的提供商实际生成图片。
- 每个诊断按钮显式绑定结果提示区，修复 `needs_real_test` 覆盖“真实生图测试”按钮，以及两个 R2V 入口结果显示串位的问题。
- 将常见诊断状态码转换为中文显示，不再直接展示 `needs_real_test` 等内部状态值。

### 验证方式

- `python -m unittest console.tests.test_settings_diagnostics_ui -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- 浏览器模拟免费检查与真实生图测试，确认按钮文字不变且结果进入 `diagImage`。
- `node --check`（提取后的前端脚本）
- `python -m py_compile console/batch_console.py console/service_diagnostics.py`
- `git diff --check`

### 影响与注意事项

- ComfyUI 生图后端及 `comfyui_image` 诊断能力未删除；选择“ComfyUI 工作流”后，文生图卡片的真实测试仍会提交 SDXL 工作流。
- 本次只收敛重复界面入口并修复结果显示位置，不修改已保存的模型配置。

## 2026-09-24 - v0.13.38 - 设置抽屉宽度与模型字段布局优化
### 本次更新内容

- 设置抽屉扩大到桌面端最多 `720px`，增加内容区留白、层次和可读性。
- 语言模型和图片模型的云端配置统一为“接口地址 → API Key → 模型”，接口地址与 API Key 在桌面端并排，模型单独占一行。
- 窄屏自动切换为单列，同时保留接口地址、API Key、模型的填写顺序。
- 修复 ComfyUI 服务器地址标签未闭合导致后续诊断区域结构异常的问题。
- 修复文生图卡片被提前闭合导致 R2V 及底部设置脱离滚动区的问题，所有设置项现在统一对齐并随内容区整体滚动。

### 验证方式

- `python -m unittest console.tests.test_settings_diagnostics_ui -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- `node --check`（提取后的前端脚本）
- `python -m py_compile console/batch_console.py console/service_diagnostics.py`
- `git diff --check`

### 影响与注意事项

- 仅调整设置页的布局和标签结构，原有配置字段 ID、保存逻辑及接口地址不变。
- 更新页面后如仍显示旧布局，请在浏览器执行 `Ctrl+F5` 强制刷新。

## 2026-09-24 - v0.13.37 - Windows 启动脚本清理旧控制台
### 本次更新内容

- `scripts/start_windows.bat` 启动前只清理占用 `8890` 控制台端口的旧进程，避免更新代码后浏览器仍连接旧版后端。

### 验证方式

- `python -m unittest console.tests.test_windows_launcher -v`
- `git diff --check`

### 影响与注意事项

- 启动脚本不会结束 ComfyUI `6006` 或其他端口的服务，只处理控制台 `8890`。
- 已打开的旧控制台窗口再次启动时，会自动替换为当前代码版本。

## 2026-09-24 - v0.13.36 - LLM 检查详情与交互对话
### 本次更新内容

- “免费检查 LLM”明确检查 `GET /models`，结果显示实际端点、提供商格式、当前模型和上游错误原因；HTTP 错误正文会脱敏 API Key 后返回。
- “真实对话测试”改为设置页内置一问一答面板，支持多轮历史、当前未保存表单配置即时生效、发送中禁用按钮和错误提示。
- 新增 `/api/llm/chat` 交互接口，要求明确确认可能产生费用，并校验消息内容与历史长度，避免确认后窗口直接消失。

### 验证方式

- `python -m unittest console.tests.test_service_diagnostics console.tests.test_settings_diagnostics_ui console.tests.test_task_control_api -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- `python -m py_compile console/batch_console.py console/service_diagnostics.py`
- `node --check`（提取后的前端脚本）
- `git diff --check`

### 影响与注意事项

- 免费检查只访问模型列表，不发送对话或生图请求；真实对话仍可能产生 LLM 费用。
- 代码更新后需重启 `console/start_daemons.py`，浏览器使用 `Ctrl+F5` 加载新的聊天接口和页面。

## 2026-09-24 - v0.13.35 - 诊断接口未重启提示
### 本次更新内容

- 设置页真实诊断遇到 HTTP 404 时，明确提示“控制台后端未加载诊断接口，请重启控制台服务”，不再只显示 `not found`。
- 保留真实上游错误内容，便于区分后端未更新与云端接口/模型本身的问题。

### 验证方式

- `python -m unittest console.tests.test_settings_diagnostics_ui -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- `node --check`（提取后的前端脚本）
- `git diff --check`

### 影响与注意事项

- 本次截图对应的是旧后端进程返回 404；必须重启 `console/start_daemons.py` 后，`/api/diagnostics/real` 才会生效。

## 2026-09-24 - v0.13.34 - 设置项按提供商条件显示
### 本次更新内容

- 生图设置按本地、云端、ComfyUI 分组显示，只展示当前提供商需要的参数。
- 云端接口格式仅在云端模式显示，模型下拉按 OpenAI/Agnes 提供商过滤；ComfyUI 模式显示 SDXL 检查点配置。
- 语言模型设置同步按本地/云端显示，修复“云端接口格式”标签在窄抽屉中被挤成竖排的问题。
- 兼容旧配置：检测到“云端 + ComfyUI 格式”时自动迁移为 ComfyUI 生图模式。

### 验证方式

- `python -m unittest console.tests.test_settings_diagnostics_ui -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- `node --check`（提取后的前端脚本）
- `git diff --check`

### 影响与注意事项

- 保存配置时仍保留旧版 `provider/provider_type` 字段，现有后端配置兼容不受影响。
- 选择 ComfyUI 生图时，检查点留空会使用后端默认的 `sd_xl_base_1.0.safetensors`。

## 2026-09-24 - v0.13.33 - 真实诊断结果轮询修复
### 本次更新内容

- 设置页真实测试提交后持续轮询 `/api/diagnostics/run`，显示执行中、成功输出路径或失败摘要。
- ComfyUI 生图、T2V、I2V、R2V 诊断分别写入对应结果区域，避免提交后界面停留在“已提交”。

### 验证方式

- `python -m unittest console.tests.test_settings_diagnostics_ui -v`
- `python -m unittest discover -s console/tests -p "test_*.py" -v`
- `python -m py_compile console/batch_console.py console/service_diagnostics.py`
- `git diff --check`

### 影响与注意事项

- 真实测试仍可能消耗 Agnes 费用或 ComfyUI GPU；结果会在任务完成后显示具体输出或失败原因。
- 修改前端后需重启 `console/start_daemons.py` 以加载新页面。

## 2026-09-24 - v0.13.32 - 生图提供商选择与诊断布局
### 本次更新内容

- ComfyUI 诊断按钮按连接、生图、视频分组并统一显示执行结果。
- 生图配置支持 OpenAI、Agnes、Boogu 和 ComfyUI 提供商选择；云端模型提供常用预设和自定义模型。
- 真实诊断提交后轮询最终状态并显示输出验证结果。
### 验证方式

- `python -m unittest console.tests.test_settings_diagnostics_ui console.tests.test_service_diagnostics -v`
- `python -m py_compile console/batch_console.py console/service_diagnostics.py`
- `git diff --check`
### 影响与注意事项

- 真实生图/视频测试仍可能产生云端费用或占用 GPU。
- 旧版 `image_gen.local/cloud/provider_type` 配置保持兼容。


## 2026-09-24 - v0.13.31 - 配置区服务诊断

### 本次更新内容

- 服务诊断从第 7 步移入设置抽屉，分别紧贴 ComfyUI、LLM、生图和 R2V 配置。
- 测试请求读取当前表单值，即使尚未保存也能验证；生图测试根据当前本地/云端供应商选择适配器。
- 诊断错误改为先读取原始响应，再解析 JSON，服务端返回 HTML 或纯文本时显示可读错误。

### 验证方式

- `python -m unittest console.tests.test_settings_diagnostics_ui console.tests.test_service_diagnostics -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile console/batch_console.py console/service_diagnostics.py`
- `git diff --check`

### 影响与注意事项

- 第 7 步不再显示诊断卡片；打开右上角“设置”即可测试配置。
- 真实生图/视频测试仍可能产生费用或占用 GPU，点击后会再次确认。

## 2026-09-24 - v0.13.30 - 服务诊断与单项真实测试

### 本次更新内容

- 新增 `/api/diagnostics/quick` 免费连通性检查、`/api/diagnostics/real` 单项真实测试和 `/api/diagnostics/run` 结果轮询接口。
- 控制台新增服务诊断面板，可分别测试 Agnes 生图、LLM、ComfyUI 生图及 T2V/I2V/R2V，真实测试必须明确确认费用或 GPU 使用。
- 诊断结果写入 `console.db`，服务重启后仍可查询，失败信息沿用失败码并脱敏 API Key。

### 验证方式

- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile console/batch_console.py console/service_diagnostics.py`
- `git diff --check`

### 影响与注意事项

- 免费检查不会提交生图或视频任务；真实测试可能消耗 Agnes 费用或 ComfyUI GPU，需在界面勾选确认。
- 修改后需重启 `console/start_daemons.py` 才能加载新的后端路由。

## 2026-09-24 - v0.13.29 - 链式重试自动恢复前置末帧

### 本次更新内容

- **末帧持久化**：链式生成完成后，将抽取的末帧保存到配置的素材目录，不再只依赖临时文件。
- **失败重试恢复**：旧批量提交和任务控制中心的“重新生成本段”都会在提交前检查链式首帧；素材缺失时自动从已成功的前置视频重新抽取、保存并上传。
- **明确阻塞原因**：找不到前置尝试或前置视频/末帧无法恢复时，预检记录 `F-CHAIN-PREDECESSOR-MISSING` 或 `F-CHAIN-FRAME-MISSING`，不再进入无限等待。
- **可再次预检**：`preflight_failed` 任务修复服务器、输出或素材后，可以直接再次运行预检，不需要删除重建记录。

### 验证方式

- `python -m unittest console.tests.test_task_service console.tests.test_chain_resume console.tests.test_task_control_chain -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile console/batch_console.py console/task_service.py console/task_store.py console/chain_daemon.py`
- `git diff --check`

### 影响与注意事项

- 仅影响链式任务的末帧保存、重试预检和提交前素材准备；普通 T2V/I2V/R2V 参数不变。
- 代码更新后需重启 `console/start_daemons.py`。现有失败任务可在任务控制中心创建重试，选择已成功的前置段，运行预检通过后再提交。

## 2026-09-24 - v0.13.28 - 任务控制中心中文化与接口错误提示修复

### 本次更新内容

- **界面中文化**：任务控制中心的标题、状态、按钮、详情弹窗、重试参数、链式依赖、确认提示和失败提示统一改为中文；任务 ID、Prompt ID、GPU 型号、文件名和节点名等技术标识保持原文。
- **响应解析保护**：任务控制中心先读取响应文本，再尝试解析 JSON；接口返回纯文本 404 或非 JSON 错误时显示明确的中文提示，不再出现 `Unexpected token`。
- **后端错误格式统一**：未匹配的 GET/POST 路由统一返回 JSON 错误对象，便于前端和其他客户端稳定处理。

### 验证方式

- `python -m unittest console.tests.test_task_control_ui console.tests.test_task_control_api -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile console/batch_console.py console/task_service.py console/task_store.py console/chain_daemon.py`
- `git diff --check`

### 影响与注意事项

- 仅影响任务控制中心的显示文案与错误处理，不改变任务提交、重试、取消和链式依赖的业务流程。
- 代码更新后需重启 `console/start_daemons.py`，让运行中的控制台进程加载新的路由和页面代码。

## 2026-09-24 - v0.13.27 - 任务控制中心支持远端离线降级

### 本次更新内容

- **离线任务控制**：任务控制中心先读取本地规范化任务记录；ComfyUI 服务器离线时仍返回任务列表，并在服务器摘要中明确显示离线原因。
- **预检恢复**：允许 `preflight_failed` 尝试在服务器或工作流修复后重新预检并恢复为 `ready`，不需要手工删除旧记录。
- **项目隔离**：任务控制中心按当前项目名过滤规范化尝试，避免不同项目的分段混入同一列表。

### 验证方式

- `python -m unittest console.tests.test_task_service.TaskServiceTests.test_failed_preflight_can_be_run_again_after_server_is_fixed console.tests.test_task_control_api -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile console/task_service.py console/task_store.py console/batch_console.py console/chain_daemon.py`
- `git diff --check`

### 影响与注意事项

- 服务器离线只会阻止预检、提交和刷新等远端操作，不会隐藏本地任务历史；不会自动提交、重试或切换供应商。

## 2026-09-24 - v0.13.26 - 增加可控任务生命周期与链式刷新
### 本次更新内容

- **单段控制 API**：新增任务预检、单段提交、单段重试、取消/中断、批次取消和链式来源选择接口；重试创建独立子尝试，不覆盖失败父记录。
- **失效检测**：只有在队列和历史查询均成功且连续两次找不到 prompt 时才标记 `stale`，连接失败不会误判。
- **链式守护进程**：改为每 20 秒刷新规范化任务状态，不再自动替换前置视频或偷偷提交下一段。

### 验证方式

- `python -m unittest console.tests.test_task_service console.tests.test_chain_resume -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile console/task_service.py console/batch_console.py console/chain_daemon.py`
- `git diff --check`

### 影响与注意事项

- 旧 `/api/status`、`/api/submit`、`/api/regenerate` 保留；新控制接口返回规范化尝试记录。
- 正在运行的任务取消必须二次确认；失败、取消、失效任务不会自动重试、降画质或切换供应商。

## 2026-09-24 - v0.13.25 - 增加规范化任务尝试存储与旧任务迁移
### 本次更新内容

- **任务尝试表**：新增分段、尝试和诊断运行表，支持明确状态转换、父子重试关系、输出和失败信息持久化。
- **兼容迁移**：控制台启动时幂等读取旧 `state.tasks`，保留完整原始任务字典并映射为成功、失败、阻塞、排队或待提交状态。

### 验证方式

- `python -m unittest console.tests.test_task_store -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile console/task_store.py console/batch_console.py`
- `git diff --check`

### 影响与注意事项

- 不删除、不重建现有 `console.db`，原 `state` 键值表和项目快照继续由旧 API 管理。
- 迁移以 `legacy_task_id` 保证幂等，不会重复创建历史尝试；本阶段尚未改变旧任务提交和轮询逻辑。

## 2026-09-24 - v0.13.24 - 抽离 ComfyUI 客户端与结构化错误解析
### 本次更新内容

- **统一 ComfyUI 请求**：新增可测试的客户端，封装队列、历史、系统能力、工作流预检、取消、上传和下载接口，并让旧 HTTP 包装函数保持兼容。
- **结构化失败信息**：新增显存不足、节点缺失、模型缺失和工作流校验失败等稳定错误码，同时对 Bearer/API Key 做脱敏。

### 验证方式

- `python -m unittest console.tests.test_comfyui_client console.tests.test_failure_diagnostics -v`
- `python -m py_compile console/comfyui_client.py console/failure_diagnostics.py console/batch_console.py`
- `git diff --check`

### 影响与注意事项

- 现有 `/api` 接口签名和任务提交逻辑保持不变；本次只替换底层请求实现。
- 诊断模块不会记录或返回明文 API Key；远端 ComfyUI 离线时不会自动启动或提交任务。

## 2026-09-24 - v0.13.23 - 修复链式重生成卡在等待上一段
### 本次更新内容

- **链式重生成**：允许重生成任务复用已经完成并标记过 `chain_done` 的前置视频；此前该标记会错误阻止重生成任务继续提交。
- **旧记录兼容**：对已经写入数据库但没有新标记的版本任务，通过原任务名与 `_v2`/`_v3` 版本关系识别为链式重生成。
- **显式标记**：后续 `/api/regenerate` 创建链式等待任务时写入 `chain_retry`，避免与普通批次链式任务混淆。
- **回归测试**：新增等待任务复用已完成前置任务的测试。

### 验证方式

- `python -m unittest console.tests.test_chain_resume -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile console/batch_console.py console/start_daemons.py console/chain_daemon.py`
- `git diff --check`

### 影响与注意事项

- 不改变普通批次链式任务的防重复行为；只允许明确的重生成版本继续使用已完成前置视频。
- 已卡住的 `最后两分钟_04_v4_v2` 已使用第 3 段本地视频提交到当前 ComfyUI，当前任务由 ComfyUI 继续生成。
- 不会自动提交其他分段，也不会改变分辨率或步数。


## 2026-09-24 - v0.13.22 - 重生成后自动显示任务状态
### 本次更新内容

- **重生成流程**：`/api/regenerate` 成功返回后，前端自动切换到第 7 步“提交生成”，并重置状态分页，立即显示刚创建的新版本任务。
- **轮询保持**：继续使用现有状态轮询，不改变重生成参数、链式衔接或整批提交行为。
- **回归测试**：新增前端源码回归测试，确保成功重生成包含状态页导航和分页重置。

### 验证方式

- `python -m unittest console.tests.test_regenerate_ui -v`
- `python -m py_compile console/batch_console.py console/start_daemons.py console/chain_daemon.py`
- `git diff --check`

### 影响与注意事项

- 仅影响点击“重新生成”后的界面展示；任务仍按原接口提交到当前配置的 ComfyUI 服务器。
- 第 7 步会显示所有任务，最新重生成版本按现有状态排序置顶。


## 2026-09-24 - v0.13.21 - 允许失败任务重新生成
### 本次更新内容

- **提交生成页**：`F-LOST` 等失败任务现在显示“重新生成”按钮，复用现有的重新生成接口；已完成任务的行为保持不变。
- **接口兼容**：修复重新生成接口仍按旧版返回值解包导致连接被关闭、前端显示 `Failed to fetch` 的问题。

### 验证方式

- `python -m py_compile console/batch_console.py`
- `git diff --check`
- 检查失败任务卡片的状态渲染条件包含 `error`。

### 影响与注意事项

- 重新生成会创建新的任务版本并实际占用 ComfyUI/GPU；链式重新生成仍需上一段已有视频，首段不应开启链式衔接。


## 2026-09-23 - v0.13.20 - 适配 AutoDL MiniMax H3 镜像模型文件名

### 本次更新内容

- **T2V/I2V/R2V Turbo LoRA**：统一改用 AutoDL 镜像已安装的 `minimax_h3_turbo_v4_step600_ema_pruned_comfyui.safetensors`。
- **I2V 文本编码器**：改用镜像已安装的 H3 Heretic NVFP4 编码器 `qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors`。
- **回归测试**：新增三种任务模式的 API 工作流构建检查，并确认 R2V 官方 Ref2VA UNet/CLIP 配置保持不变。

### 验证方式

- `python -m unittest console.tests.test_autodl_model_compat -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile workflows/build_api_graphs.py console/batch_console.py console/start_daemons.py console/chain_daemon.py`
- 使用 JSON 解析器验证 T2V 与 I2V 模板；`git diff --check`

### 影响与注意事项

- T2V、I2V、R2V 将选择 AutoDL 镜像中已存在的 H3 权重文件名，不修改服务器文件或额外下载模型。
- 其他 ComfyUI 环境若没有这些权重，需要恢复为该环境实际安装的模型文件名。
- 修改后需重启本地控制台后台服务，再提交低分辨率预览任务；本次未提交生成任务。

### 失败码 / 错误提示变化

- 不新增失败码；避免因 LoRA/CLIP 文件名不在 ComfyUI 可用模型列表中导致工作流校验失败。

## 2026-09-23 - v0.13.19 - 修复 Windows 提交任务时工作流 JSON 编码错误

### 本次更新内容

- **工作流读取**：`workflows/build_api_graphs.py` 的 T2V、I2V、R2V 工作流 JSON 统一显式使用 UTF-8 读取，避免 Windows 默认 GBK 解码中文工作流失败。
- **回归测试**：新增工作流编码测试，模拟 Windows 默认编码并覆盖三种任务模式。

### 验证方式

- `python -m unittest console.tests.test_workflow_encoding -v`
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`
- `python -m py_compile workflows/build_api_graphs.py console/batch_console.py console/start_daemons.py console/chain_daemon.py`
- `git diff --check`

### 影响与注意事项

- 仅影响工作流 JSON 的读取编码，不改变任务图结构或任务参数。
- 修改后需重启控制台后台服务，再重新提交任务。

### 失败码/错误提示变化

- 修复提交任务时 `构建任务 ... 失败：'gbk' codec can't decode ...` 的编码错误。

## 2026-09-22 · v0.13.18 — 修复云端生图成功后素材目录不存在导致落盘失败

### 本次更新内容

- **存储初始化**：服务加载配置后自动创建 `storage.asset_dirs` 中的素材目录；每次云端/本地图片落盘前再次确保目录存在。
- **根因修复**：Agnes 已返回并计费后，原代码直接写入不存在的 `素材/`，触发 `No such file or directory`，导致前端看不到图片；现在目录会在写入前创建。
- **错误提示**：`/api/asset_gen` 不再把所有供应商错误标记为“Boogu 生图失败”，统一显示“生图失败”。
- **测试**：新增“素材目录不存在时自动创建”的回归测试。

### 验证方式

- `python -m unittest discover -s console/tests -p 'test_*.py' -v`：7 个测试全部通过。
- `python -m py_compile console/batch_console.py console/start_daemons.py console/chain_daemon.py`：编译检查通过。
- 项目根目录下已确认存在 `素材/` 与 `出镜素材/`。

### 影响与注意事项

- 不修改已有资产；缺失目录只会被创建。
- 已扣费但落盘失败的历史 Agnes 响应未被保存到本地，无法由控制台恢复，需要重新生成。
- 新代码需重启控制台后台服务后生效。

### 失败码 / 错误提示变化

- 不新增失败码；修复 `No such file or directory: ...\\素材\\*.png` 错误。

## 2026-09-22 · v0.13.17 — 修正 Agnes 文生图响应与错误回退

### 本次更新内容

- **请求格式**：参考已验证的 Agnes 适配器，纯文生图改用 `return_base64: true`；仍发送 `size` 与 `ratio`，并兼容 `b64_json`/URL 响应。
- **错误链路**：Agnes 云端请求失败时不再回退本地 Boogu，保留 Agnes 原始异常，避免把已扣费的云端请求误报为本地“未返回图片数据”。
- **测试**：新增 Agnes 云端错误不回退、请求体和 URL 下载回归测试。

### 验证方式

- `python -m unittest console.tests.test_agnes_image -v`：3 个测试全部通过。
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`：全部回归测试通过。
- `python -m py_compile console/batch_console.py console/start_daemons.py console/chain_daemon.py`：编译检查通过。

### 影响与注意事项

- Agnes 失败不会再触发本地 Boogu 请求，不会产生第二次生图调用。
- OpenAI、DashScope 和本地 Boogu 的原有回退逻辑不变。
- 已经扣费但未返回图片的请求需要在 Agnes 后台按请求记录查询，代码无法撤销供应商侧扣费。

### 失败码 / 错误提示变化

- Agnes 请求失败时，前端将显示 Agnes 的 HTTP/响应错误，不再显示误导性的 Boogu 错误。

## 2026-09-22 · v0.13.16 — 适配 Agnes Image API 生图请求格式

### 本次更新内容

- **后端**：新增 Agnes 生图适配器，按官方格式发送 `size`、`ratio` 和 `extra_body.response_format=url`，并支持 URL/b64 图片响应落盘。
- **兼容选择**：设置中新增 Agnes 接口格式；即使旧配置仍写 `openai`，只要 base_url 是 `apihub.agnes-ai.com` 也会自动识别为 Agnes。
- **前端**：保留现有云端地址、模型和 API Key 配置方式，仅增加协议选项。

### 验证方式

- `python -m unittest console.tests.test_agnes_image -v`：2 个 Agnes 适配测试通过。
- `python -m unittest discover -s console/tests -p 'test_*.py' -v`：全部回归测试通过。
- `python -m py_compile console/batch_console.py console/start_daemons.py console/chain_daemon.py`：编译检查通过。

### 影响与注意事项

- Agnes 请求默认使用 `2K`；控制台当前资产图尺寸 `768x1024` 映射为 `3:4`，宽屏输入映射为 `16:9`。
- OpenAI 兼容和 DashScope 生图请求不变。
- 生图仍会执行现有图片质检；质检失败会按原逻辑重试并返回问题列表。

### 失败码 / 错误提示变化

- Agnes 无 URL/b64 图片内容时返回“Agnes 生图返回无图片 URL 或 b64 数据”。
- 其他 HTTP 错误继续沿用 `/api/asset_gen` 的“Boogu 生图失败：...”包装。

## 2026-09-22 · v0.13.15 — 修复剧本 JSON 导入后分镜表格字段为空

### 本次更新内容

- **后端**：`/api/import_script` 在保留生成用 `tasks` 的同时，新增标准化 `script`，保留标题、角色表以及每段的场景、角色、动作、对白、情绪、运镜和时长。
- **兼容格式**：标准化逻辑继续支持 `storyboard_list`、`segments` 等分镜容器及 `location`、`characters` 等字段别名；现有 Prompt 块导入和任务提交结构不变。
- **测试**：新增剧本导入回归测试，覆盖标准 Novel-Director 字段和 ArcReel 风格别名字段。

### 验证方式

- `python -m unittest discover -s console/tests -p 'test_*.py' -v`：3 个测试全部通过。
- `python -m py_compile console/batch_console.py console/start_daemons.py console/chain_daemon.py`：编译检查通过。
- 通过导入接口响应检查 `script` 与 `tasks` 同时存在，前端已有 `d.script` 分支负责渲染表格。

### 影响与注意事项

- 已有项目数据和生成任务不受影响；只影响剧本 JSON 导入响应和脚本表格显示。
- 导入格式错误或没有分镜时仍返回原有错误提示。
- 无新增或修改失败码。

## 2026-08-16 · v0.13.14 — 开源补 GitHub Issue/PR 模板

### 本次更新内容

- 新增 `.github/ISSUE_TEMPLATE/`：Bug 反馈、功能建议、模板选择配置
- 新增 `.github/PULL_REQUEST_TEMPLATE.md`：PR 提交说明模板

### 影响与注意事项

- 纯仓库元数据；推送 GitHub 后 Issues / PR 页面自动生效

---

## 2026-08-16 · v0.13.5 — 四视图正面槽兼容老项目锚点图

### 本次更新内容

- 老项目兼容：正面锚点图生成于四视图功能上线前、未登记 `roleViews.front` 时，
  加载项目自动补登记；角色卡片四视图的「正面」槽位显示已有锚点图
- 角色卡片渲染兜底：正面槽优先显示 `roleViews.front`，没有则显示主锚点图

### 影响与注意事项

- 纯前端兼容逻辑；刷新页面即生效，无需重启服务

---

## 2026-08-16 · v0.13.13 — 文字提示词与生图提示词一致性（年代/场景基调统一）

### 本次更新内容

- **年代/场景基调从剧本推断**：新增 `projectEraZh()`，按剧本 type/logline/场景自动判断
  「现代中国城市」还是「1980年代中国乡村」，替换所有生图提示词里写死的"1980年代中国乡村"：
  - 角色锚点图 / 四视图 / 场景图 / 分镜图 全部跟随剧本设定
  - 现代题材不再误加"无现代物品"约束
- **分镜图提示词引用场景描述**：分镜图现在优先使用资产状态表的场景描述
  （与文字提示词同一来源），并加约束"背景元素必须与场景描述一致，
  门窗/设备/位置不得凭空增加或替换"——解决分镜图出现停车牌/手机/门等无关元素
- 规则文件同步：剧本生成与分镜生图规则改为"跟随用户题材"，不再默认套乡村模板
- 修复当前项目 7 个场景描述的"1980年代中国乡村"前缀 → "现代中国城市"
- 代码层新增镜头编号规范化：LLM 输出开头误写 [Shot 2]/[Shot 3] 时自动重排为 [Shot 1] 起
  （只处理画面描述字段，不动 I2V 首帧对齐头里的 [Shot 1] 引用）

### 影响与注意事项

- 纯前端/规则改动；**已生成的旧分镜图、场景图仍是用旧提示词画的**，
  需要重新生成才生效（分镜卡片「重新生成」或「⚡ 一键生成」先删旧图）
- 需重启控制台服务生效

---

## 2026-08-16 · v0.13.12 — 修复重启 ComfyUI 后已完成任务被误标 F-LOST

### 本次更新内容

- 根因：ComfyUI 重启会清空内存里的 history，控制台查不到已提交的 pid，
  把**已经完成并下载到本地**的任务也误标成 F-LOST（"远程队列中消失"）
- 修复：只要任务记录有本地产物（output_file / downloaded），一律按「完成」处理，
  即使远程 history 已被重启清空；丢失/超时标记只针对确实没有产物的任务
- 历史丢失时状态卡仍显示视频（从任务记录恢复输出列表），不影响播放/合成
- 一次性修复：把当前 10 条被误标的记录恢复为「完成」

### 影响与注意事项

- 以后重启远程 ComfyUI 不再出现"已完成任务变失败"；真丢失（没出片）仍会正常标 F-LOST
- 需重启控制台服务生效

---

## 2026-08-16 · v0.13.11 — README 增加系统架构图

### 本次更新内容

- README 新增「系统架构」章节（Mermaid 流程图，GitHub 直接渲染）：
  控制台流水线、本地服务（LLM/文生图/质检）、远程 ComfyUI（H3 工作流/权重/加速）、
  数据与配置四层关系

### 影响与注意事项

- 纯文档改动；README 在 GitHub 上自动渲染架构图

---

## 2026-08-16 · v0.13.10 — 开源准备清理（相对路径 / 改名 / 密钥防护 / README）

### 本次更新内容

- 消除代码与文档里的绝对路径：
  - `workflows/make_assets.py` 字体路径改为跨平台查找（`H3_FONT` 环境变量 > 项目内字体 > macOS/Windows 系统字体）
  - `console/README.md` 启动命令改为相对路径
- 工作流文件改名：`video_minimax_h3_r2v (1).json` → `video_minimax_h3_r2v.json`（去掉空格/括号）
- `.gitignore` 增加 `config*.bak` / `*.bak`（防止含 API Key 的配置备份被误提交）
- README 更新：R2V 六段式自动包装、角色四视图、ref2va 权重要求与缺失回退说明、CLIP 开源默认

### 影响与注意事项

- 本机 `config.json.bak` 含真实 api_key，已加入 gitignore 不会提交；建议确认后自行删除
- 纯文档/脚本路径调整，不影响运行逻辑；控制台服务无需重启（下次启动自动生效）

---

## 2026-08-16 · v0.13.9 — 修复视频播放只播几秒：/media 支持 HTTP Range 分段

### 本次更新内容

- `/media` 接口支持 **HTTP Range 请求**（206 Partial Content）：
  - 之前不管浏览器要哪段都一次性返回整个文件，播放器只能播开头几秒（约 5 秒就停）
  - 现在支持 `bytes=start-end` / `bytes=start-` / `bytes=-N` 分段，视频可完整播放、可拖动进度条
- 图片仍走整文件返回（无需分段）

### 影响与注意事项

- 生成的视频文件本身一直是完整 12.25s（294 帧 @24fps），问题只在播放服务；
  刷新页面后重新播放即可看到完整时长
- 需重启控制台服务生效

---

## 2026-08-16 · v0.13.8 — 任务版本化 ID：链条严格接新前段 + 生成中任务禁止删除

### 本次更新内容

- **版本化任务 ID**：重提的每段 ID 和名称都带 `_vN`（如 `task_1_最后两分钟_01_v3`），
  新旧版本完全可区分，不再共用同一 ID
- **链条严格接新前段**：链式提交时，本批第 N 段明确引用"本批第 N-1 段的新版本"，
  不再按状态列表位置猜上一段——解决"重复提交后链条接到旧版本/断链"的问题
- **生成中任务禁止删除（后端双保险）**：删除接口先查远程队列，任务还在
  生成/排队（running/pending）时返回"任务正在生成/排队中，不能删除"；
  前端删除按钮本来就对进行中任务隐藏
- 同一段的任意版本还在远程跑时，重提会被拦截（防误双击产生多版本）；
  全部结束后可再提，版本号继续接序号

### 影响与注意事项

- 已提交的旧记录 ID 不变（向后兼容），新提交从 `_v2` 起带版本化 ID
- 需重启控制台服务生效

---

## 2026-08-16 · v0.13.7 — 任务删除改为移除记录：失败/丢失任务也能删掉

### 本次更新内容

- 「🗑️ 删除」现在**删除任务记录本身**（有视频文件一并删除），不再只清视频文件：
  - 失败 / 丢失（F-LOST）等没有视频的任务也能删除并从状态列表消失（原来会 404 删不掉）
  - 完成的任务删除后记录一并移除
- 删除按钮对所有非进行中任务显示（原来失败且无输出的任务连删除按钮都没有）
- 确认文案改为「确定删除这个任务吗？关联的视频文件会一并删除，任务记录不可恢复」

### 影响与注意事项

- 进行中（排队/生成/等待）任务不显示删除按钮，避免误删导致远程任务无人跟踪
- 需重启控制台服务生效

---

## 2026-08-16 · v0.13.6 — 支持多次提交：完成/失败/丢失可重提，版本号自动接序号

### 本次更新内容

- 去重逻辑改为**只有上一版还在远程生成/排队（running/pending）时才拦截**；
  已完成 / 失败 / 丢失（F-LOST）的旧任务可直接再次提交，不再弹"已提交过，跳过"
- 二次提交的每段命名保持原顺序，版本号从已有最大序号往后接：
  `最后两分钟_01` → 重提为 `最后两分钟_01_v2` → 再提 `_v3`（按已有记录自动计算）
- 同 ID 的"等待中但从未提交成功"死链占位在重提时自动清理，不挡路、不重复生成
- 远程队列查不到时保守处理：所有旧任务视为活跃，避免误重提

### 影响与注意事项

- 旧记录保留作版本历史（视频文件不删除）；不想要的可点卡片 🗑️ 删除或「清空历史任务」
- 需重启控制台服务生效

---

## V2 升级计划（待办，2026-08-16 确认）

- **故事板升级为"一镜一张"**：每段按实际镜头数（[Shot N]）生成 N 张分镜图，
  提交时在 `subject_definitions` 分别声明 `<Picture N> is a storyboard reference for [Shot N]`；
  当前保持"一段一张"，前端资产存储/一键生成/预览/参考图顺序届时同步改造

---

## 2026-08-16 · v0.13.4 — 一键生成补齐角色四视图 + 断点续跑

### 本次更新内容

- 「⚡ 一键生成全部参考图」现在会补齐角色四视图（正/脸/侧/背）：
  - 新增开关「角色四视图（正/脸/侧/背）」，默认勾选；取消则只生成正面锚点
  - 只生成缺失的图（断点续跑），已存在的不重复生成
  - 进度条按实际待生成张数统计，每张立即保存
- 修复四视图质检解析：带 `_side/_back/_face` 后缀的图按角色名取性别/服装做质检
  （之前性别会变成「未知」，质检条件错误）

### 影响与注意事项

- 一键生成数量会明显增加（2 个角色 × 4 视图 + 场景 + 分镜 ≈ 25 张，约 5-10 分钟）；
  只想快速出正面锚点时可取消四视图开关

---

## 2026-08-16 · v0.13.3 — LLM 连接支持 oMLX（8001）+ 设置标签通用化

### 本次更新内容

- 本地 LLM 可配置 oMLX（如 `http://127.0.0.1:8001`），token 复用本地服务 key；
  设置抽屉 Token 标签改为「本地 LLM API Token（LM Studio / oMLX）」
- 扩写仍不自动重载任何模型服务（v0.13.2 起行为不变）

### 影响与注意事项

- config.json `llm.local.url` 指向哪个本地服务就用哪个；oMLX 8bit 未审查模型
  （Qwen3.6-35B-A3B）实测扩写约 2 分钟/段，比 LM Studio 快

---

## 2026-08-16 · v0.13.2 — 移除 LM Studio 自动重载（防止连环 lms load 拖垮本机）

### 本次更新内容

- 删除扩写重试循环里的 `_ensure_llm_loaded`（自动 `lms load`）逻辑及函数：
  **系统不再以任何方式操作/重载 LM Studio 模型**
- 原因：LLM 调用鉴权失败（401）时旧逻辑每失败一次就 `lms load` 一次，
  10 段 × 3 次重试会连环重载，导致本机内存占满、疑似崩溃

### 影响与注意事项

- LLM 调用失败时只重试 + 回退规则扩写，不再尝试拉起模型
- 若 LM Studio 开了 API token，需要在设置抽屉「LM Studio API Token」填对，
  否则扩写会走规则回退（能用但效果差）

---

## 2026-08-16 · v0.13.1 — R2V 文本编码器开源默认改官方权重

### 本次更新内容

- `models.r2v.clip` 开源默认/示例改为官方 `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`
  （远端 ComfyUI 自带，开箱即用）；个人本地配置保留未审查版 qwen（config.json 不提交 git）
- CONFIG.md 新增 `models` 与 `console.max_ref_images` 说明，并提示未审查模型名不要写进开源示例

### 影响与注意事项

- 本机 config.json 未改动，仍用未审查 CLIP；开源用户复制 config.example.json 即为官方模型

---

## 2026-08-16 · v0.13.0 — R2V 改官方 Ref2VA：六段式 + 独立权重 + 角色四视图

### 本次更新内容

- **R2V 提示词改官方六段式**（提交时自动包装）：
  `subject_definitions / summary / retention_analysis / detailed_description /
  overall_soundscape / non_diegetic_music`
  - 角色/场景自动生成 `<Subject N>` 定义，映射到 `<Picture N>`（图片编号 = 提交连接顺序）
  - 分镜图声明为故事板参考（weak_reference），**不再当首帧**
  - 链帧若出现在 R2V 中声明为 keyframe completion（第 0.00 秒首帧）
- **R2V 使用独立 Ref2VA 权重**：`models.r2v.unet` 默认
  `minimax_h3_ref2va_pruned_int8_convrot.safetensors`，CLIP 默认无审查模型
  - config.json / 设置抽屉均可配置（models.r2v.unet / clip）
  - 提交时自动检测服务器上是否加载该权重；缺失则回退 FL2VA 并在界面提示
- **参考图提交顺序修正**：本段出场角色多视图（正→脸→侧→背）→ 场景图 → 分镜图 → 手动补充，
  上限 8 张（官方上限 9）
- **角色四视图资产**：角色卡片新增 正面/脸部/侧面/背面 四个视图槽 + 「🧩 四视图」一键补齐；
  资产状态表参考图列显示四视图缩略图；四视图全部绑定同一 `<Subject N>`
- 侧面/背面/脸部特写有独立质检规则（侧/背面不强制正脸）
- 链式段保持 I2V（上段末帧 → 本段首帧），不受本次 R2V 改造影响

### 影响与注意事项

- 服务器需加载 `minimax_h3_ref2va_pruned_int8_convrot.safetensors`（重启 ComfyUI 刷新模型列表）；
  未加载前提交 R2V 会提示并回退 FL2VA
- 需重启本控制台服务（batch_console.py / chain_daemon.py）后生效
- 参考图每多一张都会拖慢采样，四视图建议只给主角配齐

---

## 2026-08-15 · v0.11.12 — 重新生成"永久保存"选项（补充说明提示）

### 本次更新内容

- 重新生成弹窗的「同时更新到项目提示词库」复选框下方新增**行为说明提示**：
  - 勾选 = 永久保存（写回项目，第 4/6 步与后续合成都用新版）
  - 不勾选 = 只对这一次生成生效（项目提示词库保持不变）

### 影响与注意事项

- 纯界面文案改动，行为与 v0.11.12 一致

---

## 2026-08-16 · v0.12.10 — 链式衔接改 I2V（画面真正连续）+ 提交默认勾选链式

### 本次更新内容

- **链式衔接改为 I2V**：上段末帧作为本段**首帧图**（image 槽），画面从上一帧直接发展——R2V 多参考下 H3 不保证从链帧开始，段间会跳变
  - `advance_chain` 统一用 `build_i2v` + 链帧首帧
  - 提示词注入"首帧延续上一段末帧场景/人物/光线，整段单一场景不切换"
  - 去掉链式参考中的分镜图（分镜场景与上段末帧可能冲突，导致段内换场景）
- **提交默认勾选链式**：多段剧本加载/提交时自动勾选「🔗 链式衔接」，每段独立场景可手动取消

### 影响与注意事项

- 第 1-9 段为旧 R2V 链式生成；第 10 段起用 I2V 链式
- 场景切换段（如机房→屋顶）用链帧过渡更自然，分镜图在非链式单段提交时仍生效

---

## 2026-08-16 · v0.12.9 — 环境一键检查脚本 + 各平台安装命令文档

### 本次更新内容

- 新增 `scripts/check_env.py`：一键检查 Python / ffmpeg / config.json / 远程 ComfyUI / 语言模型 / 文生图 / 视觉质检，逐项 ✅/❌ + 修复建议（401 鉴权视为服务在线）
- README 新增「一键环境检查 + 各平台安装命令」（macOS / Windows / Linux）
- CONFIG.md 提示配好后先跑环境检查

### 验证方式

- 本地实测：Python / ffmpeg / ComfyUI / LLM / Boogu / 视觉全部 ✅

---

## 2026-08-16 · v0.12.8 — 修复链式推进 400 真正根因（waiting 任务参考图未上传）

### 本次更新内容

- **根因**：链式等待任务（chain_waiting）从未提交过，其参考图（锚点/场景/分镜）**从未上传到远程 ComfyUI**；daemon 推进时只上传了上段末帧，POST /prompt 因参考图缺失返回 400，后续段一直"等待上段"
- 修复：`advance_chain` 推进前，把该段所有本地参考图（角色/场景/分镜 + 链帧）全部上传到远程
- 验证：日志"最后两分钟_02 → 最后两分钟_03 已提交（e3660b2f…）"，task_3 开始生成

### 影响与注意事项

- 此前的 400 双 daemon 竞争只是加剧因素，参考图未上传才是根因；现在两条都修了

---

## 2026-08-16 · v0.12.7 — 分镜图提到 Picture 1（首帧对齐 + 构图基准）

### 本次更新内容

- **问题**：分镜图在参考图第 4 位（Picture 4），H3 多参考下对末尾图构图作用弱，视频不按分镜场景做
- 修复：`effectiveRefs` 把分镜图放第一位（Picture 1）
  - enhance 的"0.00 秒完全参照 <Picture 1>"现在指向分镜图（首帧对齐）
  - "严格参照 <Picture N>（分镜图）"引用同步生效
  - 角色/场景图仍在参考中保身份与环境
- 第 1 段 v3 已用新顺序提交验证

### 影响与注意事项

- 所有段提交自动生效（前端 effectiveRefs 新顺序）

---

## 2026-08-16 · v0.12.6 — 修复"床"误注入 + 分镜图构图引用

### 本次更新内容

- **问题1（视频出现床）**：`enhance_prompt` 的写死"1980s 乡村场景库"在灾难片上误注入卧室描述（含雕花木床架/台灯），所有段提交时都被注入
  - 修复：场景锚点兜底 `ENABLE_SCENE_ANCHOR = False` 默认关闭（AI 扩写已写环境，不再需要兜底）
- **问题2（视频没按分镜图做）**：分镜图在参考图里但提示词未引用，H3 忽略其构图作用
  - 修复：参考图含 `分镜_*` 时，提示词注入"本镜构图/机位/景别/人物站位严格参照 <Picture N>（分镜图）"
- 已批量更新最后两分钟 10 段的提示词（无床 + 分镜引用）；第 1 段已重新提交 v2

### 验证方式

- enhance 后无"乡村卧室/雕花木床架"，含"分镜图"引用 ✅

### 影响与注意事项

- task_1/task_2 旧含床版本作废，需重新生成（task_3-10 会用干净提示词自动推进）

---

## 2026-08-16 · v0.12.5 — 修复链式推进 400（重复 daemon 竞争）+ 防重复启动

### 本次更新内容

- **问题**：运行了两个 chain_daemon 实例，同时抢着推进链式任务，互相干扰导致"提交下一段失败 400"，第 2 段及以后一直"等待上段"
- 修复：
  - 清理为单实例 daemon
  - `start_daemons.py` 启动前自动杀掉同名旧进程（防重复守护）
- 当前链：第 2 段已手动提交（生成中），完成后单实例 daemon 自动推进 3-10 段

### 验证方式

- 重复启动测试：旧进程被杀，web + daemon 各 1 个

### 影响与注意事项

- 以后统一用 `python3 start_daemons.py` 启动/重启，不会叠加进程

---

## 2026-08-16 · v0.12.4 — 一键生成资产：每张立即保存 + 进度条

### 本次更新内容

- 「⚡ 一键生成全部参考图」改为**每生成一张立即保存**（中途刷新不丢），不再等全部完成才保存
- 新增生成进度条：`已生成 N/总 张 · 当前项（角色/场景/分镜）`，逐张推进
- 单张生成（角色/场景/分镜按钮）此前已是每张保存

### 验证方式

- `node --check` 通过；页面 200

---

## 2026-08-16 · v0.12.3 — 修复"一键生成"分镜图崩溃（函数名残留 bug）

### 本次更新内容

- 问题：`genAllAssets` 分镜循环调用 `storyPrompt(i)`，但该函数已改名 `defaultStoryPrompt` → ReferenceError → 一键生成在分镜阶段中断，分镜图一张不出
- 修复：改用 `defaultStoryPrompt(i)`

### 影响与注意事项

- 角色/场景图已生成的会跳过，重新点「一键生成全部参考图」会补全分镜图

---

## 2026-08-16 · v0.12.2 — 修复视觉质检失效（模型名配置错误导致假放行）

### 本次更新内容

- **问题**：config.json `vision.model` 配置为 `qwen-vl-max`（云端通义模型名），但本地视觉服务（oMLX）无此模型 → 质检请求 404 → 代码"保守放行"全部通过（假质检）
- **修复**：vision 配置改用本地多模态模型 `Qwen3.6-35B-A3B-4bit`（从 ~/.codex/vision/.env 读取）
- **修正**：苏芮锚点图 v1 生成成了男性（质检假放行没拦住），重新生成 v2 并确认女性特征
- **全量重新质检**：角色 2 张 + 场景 7 张全部真实质检通过

### 验证方式

- 视觉复核：苏芮 v2 = 女性、林川 = 男性 ✅
- 9 张资产真实质检全部通过 ✅

### 影响与注意事项

- 此前所有"质检通过"记录不可信（假放行），本项目已全部重检；历史项目建议也重新质检

---

## 2026-08-16 · v0.12.1 — 项目卡片提示词进度 + 第 4 步进度条/剩余时间

### 本次更新内容

- 项目卡片新增「提示词 N/M 段」进度显示（与"已出片"并列），扩写期间实时刷新
- 第 4 步新增**进度条**：显示 `第 X/M 段 · 场景 · 已完成 N 段 · 预计剩余约 Y 分钟`（按已用耗时推算每段平均时长）
- 新增 `_is_full_prompt`：完整扩写判定统一（>600 字 + 三段式齐全），供断点续跑与进度显示共用

### 验证方式

- 麦田告白：提示词 1/5（段 1 完整、2-5 旧规则版不计）✅
- 最后两分钟：提示词 3/10 实时更新 ✅
- `node --check` / `py_compile` 通过

---

## 2026-08-16 · v0.12.0 — 扩写断点续跑 + 每段实时保存 + 模型自动恢复

### 本次更新内容

- `start_expand_job` 改造：
  - **断点续跑**：已完整扩写的段（>800 字且三段式完整）自动跳过，只跑缺失段
  - **每段完成立即保存**到项目 prompt_tasks（断点不丢、前端实时可见）
  - **模型自动恢复**：LM Studio 不可用时自动 `lms load` 重载，不再因崩溃中断浪费
  - 失败自动重试 3 次后再回退规则
- 前端第 4 步：扩写进行中时实时拉取已保存段并渲染卡片（每完成一段页面立即多一段）
- 修复：此前脚本"全部完成才保存"导致中断丢进度、重复浪费算力的问题

### 影响与注意事项

- 已完整段判定：长度 >800 且含 `overall_soundscape`/`non_diegetic_music`；需要重扩的段可先清空其 prompt 再跑

---

## 2026-08-15 · v0.11.19 — 状态卡片真分页

### 本次更新内容

- 第 7 步状态卡片由"默认显示+展开全部"改为**真分页**：每页 12 个任务，上一页/下一页 + "第 X-Y / N 个任务"
- 进行中任务按排序自然排在最前页；轮询刷新时页码自动收敛（不越界）

### 验证方式

- `node --check` 通过；页面 200

---

## 2026-08-15 · v0.11.18 — 合成历史分页 + 二次/多次合并

### 本次更新内容

- **合成历史分页**：每页 9 个 + 上一页/下一页（含"第 X-Y / N 个"），不再"加载更多"
- **二次/多次合并**：
  - 每个合成历史视频卡片加「合并」勾选，跨页选择保留
  - 新增 `POST /api/assemble_selected`：把选中的合成视频按勾选顺序拼接（`合成_{项目}_合并_{时间戳}.mp4`）
  - 批次结果（1-50、51-100…）勾选合并成完整片；合并产物**可再次勾选参与下一轮合并**（支持三次/多次合并）
- 合成/生图产物统一保存到 `素材/` 目录（原误存出镜素材）

### 验证方式

- 实测合并 2 个合成视频 → `合成_麦田告白_合并_1786803382.mp4`，出现在历史列表
- 非法文件名（evil.mp4）→ 明确拒绝
- `node --check` / `py_compile` 通过

### 影响与注意事项

- 合并按勾选顺序拼接（合成历史为时间倒序，勾选时注意顺序）

---

## 2026-08-15 · v0.11.17 — 段范围联动版本选择 + 选择器分页 + 文件名带段号

### 本次更新内容

- **范围联动**：合成段范围（起/止）变化时，版本选择器只显示范围内的段；点「选择版本」也按当前范围加载
- **选择器分页**：范围内段数 >15 时分页显示（上一页/下一页 + "第 X-Y / N 段"），跨页选择会保留
- **合成文件名带段范围**：`合成_{项目}_{起-止}_{时间戳}.mp4`（如 `合成_麦田告白_3-4_xxx.mp4`），几百段分批合成后能一眼区分批次
- 合成校验随范围变化：范围内多版本段未选择会提示具体段名

### 验证方式

- 实测合成 3-4 段 → 文件名 `合成_麦田告白_3-4_1786803073.mp4`
- `node --check` / `py_compile` 通过

### 影响与注意事项

- 合成历史删除白名单兼容带范围命名（仍以 `合成_` 开头）

---

## 2026-08-15 · v0.11.16 — 合成支持段范围/进度/失败跳过（几百段可控）

### 本次更新内容

- **段范围选择**：合成区新增"从第 X 段 到 第 Y 段"输入（默认全部），几百段可分批发起合成
- **合成进度**：实时显示处理中 N/M 段 + 进度条（后端 job 增加 done/total）
- **失败跳过**：单段转码失败不再中断整批，记录跳过段，完成后提示"跳过 N 段（名单）"
- 范围校验：起止段越界/无效时明确报错（如"段范围无效：1-10（共 5 段）"）

### 验证方式

- 合法范围 [1,2]：合成完成 2/2、无跳过
- 非法范围 [1,10]（共 5 段）：异步报错"段范围无效"
- `node --check` / `py_compile` 通过

### 影响与注意事项

- 几百段建议分批合成（如每批 20-50 段），最后再合成批次结果

---

## 2026-08-15 · v0.11.15 — 视频多时性能优化（懒加载 + 折叠 + 分页）

### 本次更新内容

- 所有视频标签（状态卡片/合成历史/合成结果）改为 `preload="none"`：**点击播放才加载**，不再预载元数据
- 状态卡片：默认只显示进行中任务 + 最近 8-12 个，历史版本折叠在「显示全部 N 个任务」按钮后
- 合成历史：默认显示最近 6 个，支持「加载更多」
- 素材图片下拉保持原样（图片本身轻量）

### 验证方式

- `node --check` 通过；页面 200

### 影响与注意事项

- 视频点击播放时首帧加载略慢（可接受），页面滚动/打开不再卡顿

---

## 2026-08-15 · v0.11.14 — 重新生成支持链式衔接（除第一段自动勾选）

### 本次更新内容

- 重新生成弹窗新增「🔗 链式衔接」选项：
  - **除第一段外自动勾选**（根据任务名匹配剧本段序号判断；第一段禁用）
  - 勾选后本段等待上一段**最新视频**完成，自动抽末帧接本段首帧
- 后端：
  - `advance_chain` 改为按 `chain_prev` 找上一段（不再依赖任务列表相邻），支持重生成指定上一段
  - `submit_tasks` 支持任务自带 `chain_prev/chain_waiting`
  - `regenerate` 勾选链式时自动找上一段最新任务；上一段无视频则明确报错
- 移除"重新生成不参与链式"的旧提示，替换为链式行为说明

### 验证方式

- 段匹配测试：第 1 段不勾、第 2/5 段自动勾并正确找到上一段最新任务
- `node --check` / `py_compile` 通过

### 影响与注意事项

- 原第 7 步整链提交逻辑不受影响（相邻链式仍正常）

---

## 2026-08-15 · v0.11.13 — 链式衔接：多段默认勾选 + 中间段必接提示

### 本次更新内容

- 第 7 步「🔗 链式衔接」：
  - **多段剧本（>1 段）默认勾选**（未显式设置过 chain_mode 时自动勾上），中间段必须承接上一段末帧
  - 新增醒目提示："连续剧情中间段必须承接上一段末帧，否则人物/场景会跳变；每段独立场景可取消"

### 影响与注意事项

- 单段项目不受影响；独立场景短剧可手动取消勾选
- 链式推进依赖 chain_daemon（已常驻运行）

---

## 2026-08-15 · v0.11.12 — 重新生成"永久保存"选项

### 本次更新内容

- 重新生成弹窗新增复选框「💾 同时更新到项目提示词库」
  - 不勾选：修改只对这一次生效（新任务用新提示词，项目第 4 步提示词库不变）
  - 勾选：`/api/regenerate` 把新提示词写回项目 `prompt_tasks` 对应段（带 `_vN` 后缀的任务名也能匹配回原始段），并刷新 `prompt_updated_at`

### 验证方式

- 段名匹配测试：`借半块橡皮_01_v6` → 匹配回 `借半块橡皮_01` ✅
- `node --check` / `py_compile` 通过

### 影响与注意事项

- 永久保存后，第 4/6 步看到的提示词即新版；下次合成/重跑基于新提示词

---

## 2026-08-15 · v0.11.11 — 重新生成可配置（提示词/质量/步数/分辨率）

### 本次更新内容

- 新增 `GET /api/task`：返回任务完整详情（prompt/images/mode/mp/quality/steps 等）
- `POST /api/regenerate` 支持覆盖参数：`prompt` / `quality` / `steps` / `mp`
- 前端「🔄 重新生成」改为打开**配置弹窗**：
  - 提示词可编辑（textarea，预填原任务提示词）
  - 质量档（预览/成片）、步数（4-50）、分辨率（0.4/1.0/1.5）可选，默认沿用原任务
  - 显示参考图；注明"单段重跑，不参与链式衔接"

### 重新生成的规则（回答用户）

- 提示词：可修改（默认沿用原任务）
- 参考图/时长/模式：沿用原任务（不可改）
- 质量/步数/分辨率：可选，默认沿用原任务
- 链式衔接：重新生成为单段重跑，不自动链式（整链用第 7 步链式提交）
- 新版本自动加 `_vN` 后缀，原版本保留

### 验证方式

- `/api/task` 返回完整字段；`node --check` / `py_compile` 通过

---

## 2026-08-15 · v0.11.10 — 修复删除/重新生成确认框（内嵌浏览器兼容）

### 本次更新内容

- 问题：原生 `confirm()` 在部分内嵌浏览器环境被拦截，导致删除/重新生成无确认框、操作不执行
- 修复：新增页面内通用确认弹窗（`confirmModalBg`），删除视频、删除合成、重新生成全部改为自定义确认
- 确认弹窗支持：确定 / 取消 / 点击遮罩关闭

### 验证方式

- `node --check` / `py_compile` 通过；页面含确认弹窗结构
- 删除接口真实链路测试：临时合成文件删除成功

### 影响与注意事项

- 所有破坏性操作均经过确认弹窗

---

## 2026-08-15 · v0.11.9 — 任务「重新生成」按钮

### 本次更新内容

- 新增 `POST /api/regenerate`：用原任务的提示词/参考图/参数/质量档直接重新提交（新任务 id + 名称自动加 `_vN` 后缀，不覆盖原版本）
- 状态卡片已完成任务新增「🔄 重新生成」按钮（与删除并列），提交后自动轮询状态

### 验证方式

- 不存在任务 id → 404 明确报错
- `node --check` / `py_compile` 通过

### 影响与注意事项

- 重新生成 = 一次新的正常提交（走主备模型/加速逻辑），原视频保留在历史中

---

## 2026-08-15 · v0.11.8 — 生成视频 / 合成视频可删除

### 本次更新内容

- 新增 `POST /api/delete_video`：删除任务生成视频（本地文件 + 重置下载标记），状态卡片加「🗑️ 删除」按钮（带确认弹窗）
- 新增 `POST /api/delete_assembled`：删除合成视频（素材目录 `合成_*.mp4`），合成历史卡片加「🗑️ 删除」按钮
- 安全校验：合成删除仅允许 `合成_*.mp4` 白名单文件名；任务删除仅限已下载任务

### 验证方式

- 非法文件名（`evil.mp4`）→ 400 拒绝
- 临时 `合成_临时测试.mp4` 创建后删除成功，文件确认不存在
- `node --check` / `py_compile` 通过

### 影响与注意事项

- 删除为不可恢复操作（确认弹窗提示）；生成视频可重新生成
- 删除某段唯一视频后，该段进度会回到"未出片"（有其它版本则不受影响）

---

## 2026-08-15 · v0.11.7 — 合成历史（可反复合成，全部保留）

### 本次更新内容

- 新增 `GET /api/assemble_history`：扫描素材目录 `合成_*.mp4`，按时间倒序返回（文件名/时间/大小）
- 第 7 步合成区新增「📼 合成历史」：所有已合成视频可播放、下载；合成完成后自动刷新
- 支持反复合成：每次生成新文件（时间戳命名），历史全部保留

### 验证方式

- 当前已有 1 条历史（`合成_麦田告白_*.mp4`，21.1MB）正确返回
- `node --check` / `py_compile` 通过

### 影响与注意事项

- 合成文件存素材目录（gitignore 排除，不入仓库）

---

## 2026-08-15 · v0.11.6 — 合成交互调整（先选版本后合成）

### 本次更新内容

- 「🎞️ 选择版本」按钮移到「一键合成」**前面**（先选后合）
- 点「一键合成」时校验：
  - 存在多版本段且未选择 → 提示"请先选择版本"并自动展开选择器，阻止合成
  - 某段无视频 → 明确提示该段名，阻止合成
  - 多版本已选择 → 正常合成（带 selection）
- 版本选择器中无视频段显示红色"无视频"，不提供可选项

### 验证方式

- `node --check` / `py_compile` 通过；页面 200

### 影响与注意事项

- 单版本项目行为不变（无需选择，直接合成）

---

## 2026-08-15 · v0.11.5 — 合成版本手动选择

### 本次更新内容

- 新增 `GET /api/assemble_versions`：返回项目每段的可用视频版本列表（文件名/提交时间/步数等）
- `assemble_project_video` 支持 `selection`（{段名: 视频文件名}）手动指定版本；未指定默认取同名最新
- 第 7 步合成区新增「🎞️ 选择版本」：多版本段显示下拉选择器（默认最新），单版本段提示"无需选择直接合成"
- 合成按钮自动带上已选版本

### 验证方式

- 当前项目：第 1 段 6 个版本可选，2-5 段单版本
- `py_compile` / `node --check` 通过

### 影响与注意事项

- 不选版本 = 与之前一致（取每段最新）；指定错误文件名会明确报错

---

## 2026-08-15 · v0.11.4 — 合成逻辑修正：按剧本段序取最新版本

### 本次更新内容

- 问题：一键合成会把**所有**已下载任务（含多个第 1 段测试版 v3/v4/v5/v6）按提交顺序全拼，产出重复乱序
- 修复 `assemble_project_video`：
  - 按项目 `prompt_tasks` 的段顺序合成
  - 每段取"同名任务中最新提交且已下载"的一版（任务名带 `_v2/_v6` 后缀也能匹配）
  - 某段无视频时明确报错提示，不再静默跳过
  - 无剧本时回退旧行为（按提交顺序拼接）

### 验证方式

- 当前项目选择结果：第 1 段 v6（`_00007_` 碎花裙版）、2-5 段各自最新（`_00002_`）

### 影响与注意事项

- 合成默认用最新版本；如需指定某历史版本出片，可后续加"版本选择"

---

## 2026-08-15 · v0.11.3 — 进度显示修正（档位 1-7，消除 6/7 歧义）

### 本次更新内容

- 问题：后端进度用 0-6 索引（0=仅创建 … 6=已出片），前端直接显示 `progress/7`，导致已完成的最后一档显示成 `6/7`，看起来像还有一档未完成
- 修复：显示改为 `当前第 (progress+1)/7 档`，进度条同步；已出片显示 `7/7`

### 影响与注意事项

- 纯显示层改动；后端 progress 数值与状态机不变

---

## 2026-08-15 · v0.11.2 — 进度语义修正：完整跑过一次即算完成

### 本次更新内容

- 用户明确语义：**只要完整跑过一次就算完成；二次重跑是独立版本，不回退项目进度**
- 修正段级出片判定：每段同名任务中**任一任务**有完整视频（downloaded/output_file）即算该段完成
- 重跑/二次生成不改变项目进度（版本记录在 `generation_log`）
- 当前项目恢复显示：`进度 6/7 · 已出片 · 已出片 5/5 段`

### 影响与注意事项

- `prompt_updated_at` 仍记录（供版本对比），但不再阻塞进度

---

## 2026-08-15 · v0.11.1 — 项目进度判定修正（段级出片）

### 本次更新内容

- 问题：`已出片`判定过宽松——只要有任务下载过视频就置 6/7，调试中的项目也显示"已出片"
- 修复：
  - 项目保存 `prompt_tasks` 时记录 `prompt_updated_at`
  - `已出片`（6/7）= 每段 prompt_tasks 的"同名最新任务"提交时间**晚于提示词最后更新**且已下载，全部满足才算
  - 项目卡片新增段级明细：`已出片 N/M 段`
- 当前项目刷新后显示：`进度 5/7 · 已提交任务 · 已出片 0/5 段`（提示词刚更新，尚未按当前提示词出片）

### 影响与注意事项

- 时间戳判定比指纹更稳定（任务 prompt 经过 enhance 增强，与原始 prompt 指纹不同）
- 2-5 段提示词仍为旧版（蓝布衫、无 S1/S2），需重新扩写后重跑才能计入已出片

---

## 2026-08-15 · v0.11.0 — 云端 API 适配器机制（openai / claude / dashscope）

### 本次更新内容

- 新增**适配器注册表**：`_LLM_ADAPTERS`（openai / claude / dashscope）与 `_IMG_ADAPTERS`（openai / dashscope），config `provider_type` 选择，扩展新服务只需加一个适配器
- **Claude 适配器**：转 Anthropic Messages API（`/v1/messages`，system 提取、`x-api-key` + `anthropic-version` 头）
- **通义适配器**：千问走 DashScope 原生 text-generation（同步）；万相走 multimodal-generation（`X-DashScope-Async` 异步任务 + 自动轮询）
- 新增 `_strip_v1`：DashScope 原生 API 需要不带 `/v1` 的根地址（自动去重）
- 设置抽屉新增「云端接口格式」下拉（LLM 三选一、文生图二选一），保存进 config.json

### 验证方式

- 适配器单测（mock + 真实本地 echo 服务器）：claude 请求头/body 转换正确、dashscope URL 无双 `/v1`
- `py_compile` / `node --check` / config JSON 校验通过

### 影响与注意事项

- 默认 `provider_type: openai`，现有配置不受影响
- 主备降级逻辑不变：适配器按 provider_type 各自转换，主失败切备用

---

## 2026-08-15 · v0.10.4 — 修复 AI 检测不可用（OpenAI 兼容 URL 缺失 /v1）

### 本次更新内容

- 问题：配置化改造后 LLM/生图请求拼的是 `url + /models`，而 OpenAI 兼容服务实际路径是 `url + /v1/models`（LM Studio / Boogu），导致 200 空响应，前端显示"模型不可用"
- 修复：新增 `_v1(url)` 规范化——URL 未带 `/v1` 自动补全，已带 `/v1`（如云端 base_url）不重复；应用于 LLM `/models`、`/chat/completions`、文生图 `/images/generations`、Boogu 检测
- 验证：LM Studio `qwen3.6-27b-abliterated-mlx` 检测 available=True；Boogu `boogu-image` 在线

### 影响与注意事项

- 配置里 URL 填主机地址即可（自动补 `/v1`），云端填 `https://api.xxx.com/v1` 也能识别

---

## 2026-08-15 · v0.10.3 — Windows 跨平台兼容

### 本次更新内容

- `start_daemons.py` 跨平台：macOS/Linux 用 setsid，**Windows 用 `CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS`** 后台常驻
- 新增 `scripts/start_windows.bat`：Windows 前台启动控制台
- ffmpeg concat 列表路径跨平台：Windows 下反斜杠转正斜杠（`os.sep` 兼容），合成/转码在 Windows 正常
- README 新增「Windows 部署」章节：依赖安装（winget ffmpeg）、LM Studio/云端 LLM、**生图用云端**（Boogu MLX 仅 Apple Silicon）、启动方式
- `deploy_boogu.sh` 非 macOS 平台明确提示改云端生图

### 验证方式

- `py_compile` 全部脚本通过；`start_daemons.py` Windows 分支语法合法
- macOS 下服务重启正常，页面 200

### 影响与注意事项

- Windows 本地无法跑 Boogu MLX，生图必须 `image_gen.provider: cloud`
- ComfyUI / LM Studio / 云端 API 均跨平台

---

## 2026-08-15 · v0.10.2 — 修复配置化导致的服务器地址丢失

### 本次更新内容

- 问题：新建 `config.json` 时默认服务器为 `127.0.0.1:8188`，前端 `/api/config` 加载后覆盖了用户实际使用的远程服务器地址
- 修复：
  - `config.json` 恢复为实际远程服务器（`192.168.1.23:8188`）
  - `/api/config` 返回时**用户运行时保存的服务器（console.db state.server）优先于配置文件**，防止配置化把已连通地址改丢
- 确认 `console.db` 中 LM Studio token / 角色图 / 场景图等运行时配置未受迁移影响

### 验证方式

- `/api/config` 返回 `192.168.1.23:8188`；远程 ComfyUI 在线（0.31.0）
- `/api/llm_check` 正常（token 仍从 console.db 读取）

### 影响与注意事项

- 配置文件只作为"默认值"，运行时用户设置（state）优先

---

## 2026-08-15 · v0.10.1 — Boogu 部署脚本 + 云端生图切换 + 移除 TTS

### 本次更新内容

- 新增 `scripts/deploy_boogu.sh`：Boogu-Image 本地生图一键部署（装依赖 / 克隆 boogu-image-mlx 管线 / 下载模型 / 启动指引），Apple Silicon / MLX
- 新增 `scripts/boogu_server.py`：参数化 OpenAI 兼容生图服务（`BOOGU_PKG/BOOGU_MODEL/BOOGU_QWEN/BOOGU_PORT` 环境变量，无绝对路径）
- README / CONFIG.md 补充：Boogu 本地部署步骤 + 云端模型切换示例（LLM 与文生图 provider 切换、OpenAI 兼容要求、主端点失败自动降级）
- 移除与项目无关的 Qwen3-TTS 配置（`config.tts`），声音方案已完全依赖 H3 官方 (S1)/(S2) 说话人 ID

### 验证方式

- `bash -n deploy_boogu.sh` / `py_compile boogu_server.py` 通过
- `_image_gen_endpoints` provider 切换验证：cloud→(cloud, local)，local→(local, cloud)
- 服务重启后 `/api/config` 无 tts 字段

### 影响与注意事项

- 非 Apple Silicon 平台建议直接使用云端生图（config `image_gen.provider: cloud`）

---

## 2026-08-15 · v0.10.0 — 开源化重构（全配置化 + 目录归拢 + 云端模型）

### 本次更新内容

- **全配置化**：新增项目根 `config.json`（模板 `config.example.json`，说明见 `CONFIG.md`）：
  ComfyUI 服务器/工作流目录、存储路径、语言模型（本地 + 云端 OpenAI 兼容 API）、
  文生图（本地 + 云端）、视觉质检、TTS、控制台端口
- **云端模型支持**：`llm` / `image_gen` 配置 `provider: local|cloud`，主端点失败自动降级备用；
  设置抽屉新增"本地/云端模型"切换 + 云端 Key 填写（保存写 config.json，自动备份旧文件）
- **去绝对路径**：`make_cta_layer.py` / `make_subtitles.py` 改为相对路径 + 环境变量覆盖
- **目录归拢**：`console/`（原 batch_console）、`workflows/`、`scripts/`、`examples/`；
  个人内容（口播稿、技能整理、素材、录屏、生成记录等）移入 `_private/` 并 gitignore
- **开源文档**：README、CONFIG.md、LICENSE（MIT）、requirements.txt、示例演示剧本
- **git 初始化**：首次提交完成，`.gitignore` 覆盖配置密钥/运行时数据/素材/个人内容

### 验证方式

- `python3 -m py_compile` + `node --check` 通过
- 新路径下服务启动正常，`/api/config` 返回配置，`build_graphs` 从 workflows/ 加载模板成功
- `git status` 确认无 console.db / 素材 / token / 个人文档

### 影响与注意事项

- 启动路径变为 `cd console && python3 start_daemons.py`；`config.json` 不入 git（含 Key 风险）

---

## 2026-08-15 · v0.9.1 — 记录倒序 + 资产表批准状态说明

### 本次更新内容

- `GET /api/records` 返回**倒序**（最新记录在最上方），第 8 步记录表不再旧的在上
- 资产状态表"批准"字段语义明确：自动质检为机器初筛，"批准"勾选为人工终审（合格资产才允许用于生成）；未生成参考图的场景显示未批准属正常
- 资产状态表**场景描述自动预填**：从剧本分镜的动作/氛围提取，未填写的场景不再空白
- 新增 `/api/asset_reverify` + 第 5 步「🩺 补质检（已有图）」按钮：给旧项目已有参考图一键补跑质检，结果写入资产表
- 项目进度判定调整：**有参考图即算资产完成**（质检记录作为附加质量信息，不再阻塞老项目进度）
- 质检发现：林夏锚点图（`锚点_林夏_1a000bdf54c.png`）服装与设定不符（蓝底大花短袖，非小白花碎花连衣裙+彼得潘领+浅绿开衫），需重新生成锚点图

## 2026-08-15 · v0.9.2 — 声音角色锁定（方案 A）

### 本次更新内容

- 诊断：成片档第 1 段音频基频检测显示两个角色音色相同（林夏 117Hz / 陈默 125Hz，均男声），且每段开头 0-0.2s 有低频短促杂音（疑似 H3 起始语气词/残响）
- `rules/h3_expand.md` 对白锁补充**声音角色锁定**：说话者必须写清音色（林夏=年轻女性清澈嗓音、陈默=低沉男声），音色明显不同；台词前无吸气/语气词/杂音/残响
- `enhance_prompt` 新增 9b 兜底：提示词缺音色锁定时自动注入"女性角色年轻女声、男性角色低沉男声，音色明显不同，无语气词无杂音"

### 验证方式

- 以 4 步 / 480p 最低质量重跑第 1 段，出片后 whisper 转写 + 基频检测验证：
  - 林夏台词基频 ≥165Hz（女声）
  - 开头 0-0.2s 无高能量杂音

### 影响与注意事项

- 方案 A 为提示词级修复（零成本）；若音色仍不分，升级方案 B（Ref2VA 音频参考锁音色）

## 2026-08-15 · v0.9.3 — H3 官方说话人 ID 锁音色（方案 C，纯提示词）

### 本次更新内容

- 根因确认：H3 区分说话人音色靠官方稳定 ID `(S1)`/`(S2)`，不是中文名；之前提示词写"陈默低声说：…林夏垂眸压声：…"，H3 不识别为不同说话人，整段统一音色
- `rules/h3_expand.md`：对白必须带 `(S1)`/`(S2)`（按剧本角色表固定分配、全片一致），禁止只写中文名
- `enhance_prompt` 新增 `_assign_speaker_ids`：自动把 `<d>` 前的说话者中文名转成 `名字（Sx）` 格式（角色顺序取任务 roles → 资产状态表 → 出现顺序；已带 ID 幂等跳过）
- 不使用任何外部音频/参考音频，完全依靠 H3 自身能力

### 验证方式

- 单测：中文名 →（Sx）转换、幂等、动作括号保留，全部通过
- 4 步 / 480p 重跑第 1 段，出片后 whisper + YIN 基频验证：林夏（S1）≥165Hz 女声、陈默（S2）<165Hz 男声

## 2026-08-15 · v0.9.4 — 提交步数新增 6 / 8 档（加速成片）

### 本次更新内容

- 第 7 步步数选择新增 `6（加速成片）` 和 `8（加速成片）` 两档
- 加速机制自动覆盖：`build_r2v` 中步数 ≤8 自动插入 TurboLoRA + SageAttention（6/8 步与 4 步预览同一加速链路）

### 验证方式

- 前端下拉选项已更新；后端 `use_turbo = steps <= 8` 逻辑已确认覆盖 6/8

### 影响与注意事项

- 6/8 步为"加速成片"折中档：比 4 步质量高、比 20 步成片快约 2-3 倍

## 2026-08-15 · v0.9.5 — 修复"爆炸"误生成（拟音词治理）+ 提示词库被旧数据覆盖

### 本次更新内容

- 问题定位：H3 音画联动把提示词里的"啪"（橡皮断裂拟音）理解成爆破/拍击，生成爆炸音效与爆炸画面（8.5-9s 高能量非语音段）
- `rules/h3_expand.md`：拟音禁用强爆破词（啪/砰/轰/炸/爆），小物件断裂改"细微的闷响/轻轻的脆响"，画面描述加"无爆炸、无火光、无烟雾、无碎片飞溅、无闪光"
- 发现并修复：项目库 `prompt_tasks` 曾被页面 autosave 的旧内存数据覆盖（蓝布衫旧版 + `<d>` 内带角色名），已用新规范重写第 1 段（碎花裙 + S1/S2 + 无爆炸负向）

### 验证方式

- 6 步 / 480p 重跑第 1 段，出片后检查：8-9.5s 无高能量爆炸音、画面无爆炸火光

### 影响与注意事项

- 其余 4 段提示词仍为旧版（蓝布衫），建议重新扩写（新规则含 S1/S2 与拟音治理）

## 2026-08-15 · v0.9.6 — 锚点图引用修复 + 同名任务自动加后缀

### 本次更新内容

- 问题定位：`prompt_tasks` 各段 `images` 仍引用旧林夏锚点图（`锚点_林夏_1a000bdf54c.png`，蓝底大花），提示词文字虽为碎花裙但 H3 看图为主 → 衣服回退
- 修复：全部 5 段 `images` 中旧林夏锚点图替换为新图 `锚点_林夏_new.png`
- `submit_tasks` 同名任务自动加后缀序号（`_v2`/`_v3`…），状态列表不再同名混淆

### 验证方式

- 6 步 / 480p 用新锚点图重跑第 1 段，出片后视觉质检林夏服装（碎花裙）
- 任务名显示为 `借半块橡皮_01_v6`

## 2026-08-15 · v0.9.7 — 合成时自动裁剪开头起始音节

### 本次更新内容

- 确认 H3 每段开头 0.02-0.15s 带固定"起始音节"（短促人声，whisper 识别为"到/拜拜"等，基频约 190Hz），提示词约束无效
- 新增 `detect_lead_noise_sec`：检测开头短促高能量段（>1500、<0.3s）+ 后续长低能量间隙（<800、≥0.2s），返回裁剪秒数
- `assemble_project_video` 合成时对每段自动音画同步裁剪（trim 滤镜），旧 i2v 视频（无前置音节）自动跳过

### 验证方式

- 7 个版本检测：H3 各版 0.12-0.16s，旧 i2v 0s ✅
- 裁剪后 20ms 粒度验证：开头峰值从 9500 降至 400-700（静音）✅

### 影响与注意事项

- 只影响"一键合成完整视频"；单段下载预览仍保留原始开头

### 验证方式

- `curl /api/records` 首条为最新记录
- 重启 `start_daemons.py` 后页面刷新生效

### 影响与注意事项

- 无数据迁移；旧记录顺序不影响

---

## 2026-08-15 · v0.9.0 — 提示词工程化改造（参考 Higgsfield《Hell Grind》方法论）

### 本次更新内容

**P0 · 提示词生成规则（第 4 步）**

- 重写 `rules/h3_expand.md`：把七层提示词架构压缩进 H3 三段式
  - 精确人数正向锁（"画面中恰好 N 名角色，各出现一次"）
  - 资产状态一字不差引用（服装/发型/身份来自资产状态表，禁止自行改写）
  - 参考图 inherit/exclude（只继承身份/发型/服装，排除原图姿势/构图/背景/光线）
  - camera 三件套（起点构图 + 一个主运动 + 终点构图），链式段写"承接上段末帧"
  - 对白锁（`<d>` 内只放纯对白、发声时间窗、静默尾拍、未说话者嘴静止、对白不视觉化）
  - must_hold / changes_here / must_not_appear 三栏约束
- 更新 `rules/story_prompt.md`（分镜图）与 `rules/asset_prompt.md`（生图修改）：
  角色服装/发型必须与资产状态表一字不差，参考图写继承/排除
- 后端 `enhance_prompt` 新增：
  - 对白标签自动拆分：老格式 `<d>[Chinese] 陈默：“用我的。”…</d>` 自动转成
    `陈默：<d>[Chinese]用我的。</d>`（角色名/动作移到标签外，杜绝念角色名）
  - 参考范围声明、对白锁定句、链式连续性注入（放到声音字段之后，修复被字段替换吞掉的问题）
- 扩写流程（`start_expand_job` / `llm_expand_one`）自动注入：
  - 【资产状态表】作为硬事实（一字不差）
  - 上一段提示词作为链式 continuity 上下文

**P1 · 资产层（第 5 步）**

- 新增**资产状态表**（角色/场景）：身份不变量、发型、服装、参考图、批准状态
  - 存在项目数据（`asset_state`），前端第 5 步可编辑，自动保存
  - 扩写与生图质检都从该表取服装/发型描述
- 自动质检升级（`verify_asset`）：
  - 角色：性别 + 发型/服装与设定一字不差 + 无多余肢体 + 面部清晰
  - 场景：与场景描述一致 + 无人 + 无现代物品
  - 修复隐藏 bug：前端原来传 `kind='锚点/场景/分镜'`，后端质检分支接不到，
    现改为正确传 `role/scene/story`，质检真正生效

**P2 · 流程与记录**

- 新增**失败码体系**：
  - `F-SUBMIT-API` / `F-SUBMIT-RESP` / `F-DUP-SUBMIT` / `F-LOST` / `F-TIMEOUT`
  - 状态卡片显示失败码，第 8 步新增 `rules/failure_codes.md` 诊断速查表
  - 规则：先定位责任层，每轮只改一个变量，两批无改善回上层
- 新增**生成记录**：每次提交 = 一个版本批次（模式/时长/MP/质量/步数/提示词指纹），第 8 步可对比
- 项目进度改为**状态机判定**：
  - 资产档必须有质检通过记录才算完成（之前文件存在就算，判定不准确）
  - 进度条 7 档显示（仅创建→剧本→改写→提示词→资产→提交→出片）

**界面**

- 第 5 步新增资产状态表编辑区
- 第 8 步新增生成记录表 + 失败码速查面板
- 状态卡片：生成中的任务置顶 + 加载动画（spinner），不再白屏

### 验证方式

- 单段扩写实测：碎花裙保留 ✅、人数锁 ✅、纯对白 ✅、承接上段 ✅、尾帧 ✅
- 对白拆分器单测：5 种输入格式全部正确转换、新格式不被误伤 ✅
- `/api/projects` 状态机、`/api/project` 资产表存取、`/api/enhance` 全链路 ✅

### 影响与注意事项

- 规则文件热更新需通过「设置 → 编辑 AI 规则」保存（写文件 + 更新内存），或重启服务
- 已存在的 5 段提示词是旧规则生成，想升级到最新标准需重新跑第 4 步扩写
- LM Studio 模型长生成时曾崩溃一次，已用 `lms load qwen3.6-27b-abliterated-mlx` 恢复

---

## 更新说明怎么写（规则）

**什么时候算一次更新**：任何代码 / 规则文件 / 界面 / 工作流改动，凡影响系统行为，都必须写。

**每次更新至少包含 5 项**：

1. **日期与版本号**：`YYYY-MM-DD · vX.Y.Z — 一句话标题`
2. **本次更新内容**：按模块列出（后端 / 前端 / 规则 / 工作流），写清"改了什么、为什么"
3. **验证方式**：每个改动对应的验证动作与结果（跑过什么命令、通过什么检查）
4. **影响与注意事项**：已有数据是否受影响、是否需要重新生成、服务如何重启
5. **失败码 / 错误提示变化**（如有）：新增或修改的错误提示要在此说明

**版本号规则**：

- 新增功能或破坏性改动 → `+0.1.0`
- Bug 修复 / 小改进 → `+0.0.1`
- 界面文案、文档、注释 → 不升版本，但日期仍要记录

**提交前自检**：

- [ ] CHANGELOG 已更新（顶部新增一条）
- [ ] 改动可复现（写了验证命令或操作步骤）
- [ ] 已有数据兼容性已说明
