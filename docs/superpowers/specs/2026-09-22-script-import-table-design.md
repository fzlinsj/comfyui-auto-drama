# 剧本 JSON 导入表格字段保留设计

## 问题

`/api/import_script` 当前只返回用于提交生成的 `tasks`。这些任务行不包含
`scene`、`roles`、`action`、`dialogue`、`emotion`、`camera` 等剧本字段，前端
收到响应后用空字段重建 `storyboard_list`，导致导入提示成功且段数正确，但脚本表格
的内容全部为空。

## 方案

保留现有 `tasks` 响应，新增一个标准化 `script` 响应对象。标准化脚本包含标题、角色
表和每个分镜的通用字段；支持现有解析器接受的 `storyboard_list`、`storyboards`、
`segments`、`scenes`、`shots`、`tasks` 容器以及字段别名。前端导入剧本 JSON 时优先
使用 `d.script` 渲染表格；Prompt 块和旧任务导入继续沿用原有空白脚本行为。

## 兼容与错误处理

- `tasks` 的结构和生成提交链路保持不变。
- 标准化脚本只复制用户输入的剧本字段，不改写提示词内容。
- 无法解析或没有分镜时仍返回现有错误响应。
- 角色表兼容 `role_list`、`roles`、`characters`、`role_definitions`。

## 验证

- 解析包含 `storyboard_list` 的 JSON，确认返回脚本保留场景、角色、动作、对白、
  情绪、运镜和时长。
- 解析使用 `segments`/`location`/`characters` 别名的 JSON，确认字段被标准化。
- 确认 `/api/import_script` 同时返回 `script` 与 `tasks`。
- 运行 Python 编译检查和项目测试。
