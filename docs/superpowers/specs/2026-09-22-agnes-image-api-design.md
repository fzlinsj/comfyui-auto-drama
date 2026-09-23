# Agnes 生图 API 适配设计

## 问题

项目当前把 Agnes 当作通用 OpenAI 生图接口调用，发送 `response_format: b64_json`
和像素尺寸 `768x1024`，但 Agnes 的可用请求使用 `size: 2K`、`ratio` 以及
`extra_body.response_format: url`。请求可能产生计费，但响应格式或参数不被正确处理，
导致图片没有落盘。

## 方案

新增 Agnes 专用适配器，发送 Agnes 要求的请求体，并兼容 URL 与 b64 返回。输入的
像素尺寸映射为 Agnes 比例：`768x1024` → `3:4`、正方形 → `1:1`、宽屏 → `16:9`，
质量默认使用 `2K`。当 base_url 包含 `agnes-ai.com` 且 provider_type 仍为 `openai`
时自动选择 Agnes 适配器；设置界面同时增加显式 Agnes 选项。

## 兼容与错误处理

- 现有 OpenAI 和 DashScope 适配器请求不变。
- Agnes 返回 URL 时由服务端下载到素材目录，返回 b64 时继续支持解码落盘。
- HTTP 错误、响应缺少图片内容时保留原有 `/api/asset_gen` 错误响应链路。

## 验证

- 单测检查 Agnes 请求体的模型、prompt、size、ratio 和 `extra_body`。
- 单测模拟 URL 响应，确认图片被下载并保存。
- 运行全量 Python 单测和编译检查。
