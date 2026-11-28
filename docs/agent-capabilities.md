# 通用 Agent 能力扩展

本模块不定义某一种固定 Agent 角色。角色、任务流程和交付要求由用户在会话中提供；运行时负责保留指令、发现工具、执行能力并渲染结构化结果。

## 会话级自定义指令

- 首轮消息包含明确角色标题（例如 `Role:`、`角色设定：`）及多项任务约束时，会自动固定为本次会话指令。
- 固定指令独立存储，不受最近 12 轮聊天历史窗口影响。
- 使用 `/set-instructions\n...` 替换当前会话指令。
- 使用 `/clear-instructions` 清除当前会话指令。
- 原始提示词仍保留在聊天记录中，但不会在每轮上下文里重复注入；对应的助手回复仍保留。
- 自定义指令始终受系统安全、隐私和更高优先级规则约束。

## 原生工具调用

模型通过 OpenAI-compatible Chat Completions 的 `tools` / `tool_calls` 协议调用工具，不再依赖模型在普通文本中伪造工具 JSON。

`agent-runtime/capabilities/registry.mjs` 提供：

- 工具注册：名称、说明、JSON Schema、类别、关键词和执行处理器。
- 参数校验：类型、必填项、额外字段、枚举、长度和数值范围。
- 动态发现：模型先调用 `discover_capabilities`，再按需激活匹配能力。
- 执行限制：限制单轮工具调用轮数和总调用次数。
- 结果回传：工具结果作为 `tool` 消息交回模型，模型再组织最终答复。

## 已接入能力

| 能力 | 用途 | 条件 |
|---|---|---|
| `chart_create` | 柱状图、折线图、饼图 | 本地可用 |
| `image_generate` | 生成场景图、插画等图片 | 需要配置图像模型 |
| 成长记录工具 | 查询、创建、修改和删除成长记录 | 写入操作仍需用户确认 |

成长记录工具沿用现有的确认机制：工具只生成预览，只有用户确认后才真正写入。

## 多模态内容块

每轮消息可以携带 `content_blocks`，与文本一起保存到本地 SQLite：

- `chart`：由前端 SVG 渲染。
- `image`：通过本地资产 ID 展示，不直接加载模型返回的任意远程 URL。
- `document`：预留本地文件资产展示入口。

聊天正文使用安全的 DOM 节点构建 Markdown，不使用模型输出的原始 HTML。

## 图像模型配置

Python 网关读取以下环境变量：

| 变量 | 必需 | 说明 |
|---|---|---|
| `BECOMING_IMAGE_MODEL` | 是 | 图像生成模型名称 |
| `BECOMING_IMAGE_BASE_URL` | 否 | 图像服务 OpenAI-compatible API 地址；默认复用 `BECOMING_BASE_URL` |
| `BECOMING_IMAGE_API_KEY` | 否 | 图像服务密钥；默认复用 `BECOMING_API_KEY` |
| `BECOMING_ASSET_DIR` | 否 | 生成图片的本地存储目录；默认使用数据库路径加 `.assets` |

图像服务需要兼容 `POST /images/generations`，并返回 `data[0].b64_json`。目前接受 PNG、JPEG、WebP，单张图片最大 15 MB。未配置图像模型时，工具会返回明确的未配置错误，不会伪造图片。

配置好图像模型后，可以在 GitHub Actions 的 **Node agent native tool-call probe** 工作流中手动勾选 `probe_image`，执行一次真实出图测试并下载测试图片。该步骤默认关闭，避免在普通 CI 中产生图像生成费用。

## 当前边界

- 原生工具调用已通过当前配置模型的真实调用验证。
- 动态发现和本地图表工具有确定性测试及真实模型联调。
- 图片生成链路已接入可选 OpenAI-compatible provider；仍需配置实际图像模型并完成真实图片生成验证。
- 图表与图片块已进入持久化和前端渲染链路；文档生成、联网搜索等能力后续通过注册新工具扩展，不修改 Agent 的角色或主循环。
