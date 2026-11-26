# Becoming HTTP API V1

当前 API 是本地单用户后端服务，不包含 Web UI。最终 Electron 桌面端将通过同一套 HTTP API 调用业务能力。

## 启动

安装项目及 API 依赖：

    python -m pip install -e .

使用离线模拟模型启动：

    BECOMING_DEMO=1 becoming-api

Windows PowerShell：

    $env:BECOMING_DEMO="1"
    becoming-api

默认地址为 http://127.0.0.1:8765。Swagger/OpenAPI 仅用于开发联调：

- OpenAPI UI: http://127.0.0.1:8765/docs
- Schema: http://127.0.0.1:8765/openapi.json
- Health: http://127.0.0.1:8765/api/v1/health

服务默认只绑定 loopback；不要通过设置 BECOMING_API_HOST 为 0.0.0.0 将当前单用户服务暴露到局域网或公网。

## 真实模型配置

可以在启动时设置：

    BECOMING_BASE_URL=https://api.openai.com/v1
    BECOMING_API_KEY=...
    BECOMING_MODEL=...

也可以调用 PUT /api/v1/model/config 在当前进程内配置，或先调用 POST /api/v1/model/test 测试连接。

API 不提供读取密钥的接口。运行时通过 HTTP 配置的 API Key 只保存在当前 Python 进程内存；进程重启后需要重新注入。该 API 当前不负责永久保存密钥。后续 Electron Main 应使用操作系统安全存储保存密钥，并在启动本地 Python 服务时注入。

不要将真实密钥放进 URL、日志、Git、导出数据或对话消息。

## API 路由

所有 JSON API 使用前缀 /api/v1。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | /health | 服务及数据库健康状态 |
| GET | /capabilities | 当前启用的能力 |
| GET | /background/status | 后台 worker 状态及任务计数 |
| GET | /background/jobs | 查询后台任务状态 |
| GET/PUT | /model/config | 查看安全配置摘要 / 更新运行时模型 |
| POST | /model/test | 测试模型连接 |
| GET/POST | /conversations | 列出 / 创建会话 |
| GET/PATCH/DELETE | /conversations/{id} | 查看、重命名/归档、删除会话 |
| GET/POST | /conversations/{id}/messages | 读取消息 / 发送消息 |
| POST | /conversations/{id}/confirm | 确认聊天中待保存的成长变更 |
| POST | /conversations/{id}/cancel | 取消聊天中的待确认变更 |
| GET | /growth/goals | 查看成长目标 |
| GET | /growth/goals/{id} | 查看目标、行动和复盘 |
| POST | /growth/changes | 生成成长变更预览 |
| POST | /growth/changes/{token}/confirm | 确认预览并提交 |
| POST | /growth/changes/{token}/cancel | 取消预览 |
| GET | /memories | 查看长期记忆 |
| DELETE | /memories/{key} | 删除记忆槽位并阻止重新写入 |
| POST | /memories/{key}/allow | 允许未来重新写入该槽位 |
| GET | /understanding/claims | 查看动态个人理解 |
| GET | /understanding/claims/{id} | 查看命题及版本历史 |
| GET | /data/export | 导出当前本地业务数据 |
| POST | /data/clear | 生成全量清除预览 |
| POST | /data/clear/confirm | 二次确认清除 |

## 后台任务

HTTP API 模式下，消息回复完成后，长期记忆提取和动态个人理解更新不在请求线程中执行。服务在写入对话轮次的同一个 SQLite 事务中创建对应任务，避免出现“对话已保存但任务没有入队”的窗口。

- worker 使用独立 SQLite 连接，不持有 API runtime 锁执行模型调用；持久化数据库使用 WAL 和 busy timeout。
- `long_memory.extract` 按来源轮次生成唯一任务，并用 `long_memory_extraction_receipts` 防止重启后重复提取或重复写入。
- `personal_understanding.process` 复用既有 `understanding_jobs` 批处理队列；命题写入与内部任务完成状态在同一事务提交，避免崩溃后重复应用同一修订。
- 任务有 `pending/running/done/failed/cancelled` 状态，最多尝试 3 次；临时失败采用延迟重试，进程启动时将中断的 `running` 任务恢复为 `pending`。
- 用户确认个人理解的回复如果先于后台提取到达，worker 会在创建确认问题后检查同一会话的下一轮消息并补做确认；不同会话的待确认状态互不影响。
- 删除来源对话或清除全部数据时，外键级联删除尚存的来源任务。

查询：

    GET /api/v1/background/status
    GET /api/v1/background/jobs?limit=50
    GET /api/v1/background/jobs?source_turn_id=123

任务状态只表示本地处理结果，不代表模型对用户的理解一定正确。`failed` 任务需要在客户端提示用户后台整理未完成；不能把 `pending/running` 描述成已经保存。显式要求记住的信息在任务完成前，助手会说明仍在后台整理。

当前 worker 是单进程单 worker，不支持多进程竞争消费；模型调用仍是同步请求，但与主聊天请求解耦。CLI 入口保留原来的同步/批处理行为；此后台 worker 只由 HTTP API 服务生命周期管理。

### 对话请求

POST /api/v1/conversations/{id}/messages

    {
      "content": "最近我在考虑自己真正想要的生活是什么。"
    }

响应包括：

- reply：自然语言回复。
- message_id：持久化的对话轮次 ID。
- growth_event：成长工具的真实执行事件。
- confirmation_required / confirmation：如果模型提出了成长变更，返回真实数据库预览及一次性确认 token。
- memory_event / understanding_event：长期记忆与个人理解的结构化处理摘要。

客户端必须以 confirmation_required 和 confirmation 为准，不解析自然语言中的确认码，也不能仅凭模型回复判断数据已保存。

确认请求：

    POST /api/v1/conversations/{id}/confirm
    {"token": "从上一步响应中取得的一次性 token"}

### 直接管理成长数据

创建成长目标先预览：

    POST /api/v1/growth/changes
    {"tool": "create_goal", "args": {"text": "每周自由探索一次"}}

服务返回 token 和 preview；只有调用对应 confirm 路由后才写入数据库。确认 token 有效期为 10 分钟；重复确认、失效 token 或数据版本冲突都会被拒绝。

## 会话与记忆边界

- 每个会话的近期历史按 conversation_id 隔离。
- 长期记忆和动态个人理解属于本地用户级资料，可跨会话按相关性检索。
- 删除单个会话会删除该会话的 turns，并通过来源关系清理其记忆/证据；其他会话保留。
- 成长目标、行动和复盘独立于对话会话。
- 清除全部数据需要两步确认，会清除所有 turns、来源记忆/个人理解、成长记录及阻止写入槽位。
- SQLite 逻辑删除不等于物理安全擦除；备份/WAL 文件及模型服务端副本不在 API 清除范围内。

旧版 CLI 数据库会在首次打开时迁移到名为 default 的兼容会话，原有数据不会被丢弃。default 会话删除操作会清空内容并保留兼容容器。

## 错误响应

错误统一为：

    {
      "error": {
        "code": "model_not_configured",
        "message": "请先配置并测试模型连接。",
        "request_id": "..."
      }
    }

客户端应按 code 处理状态；不应依赖 message 文案。请求验证失败不回显请求 body，防止把模型密钥或私人内容写入错误响应。请求体大小上限为 64 KiB，客户端 request ID 会经过格式校验。

## GitHub Actions 联调

默认 Functional tests 工作流会：

1. 安装 FastAPI/Uvicorn。
2. 运行原有确定性功能测试。
3. 启动独立的 loopback API 进程，使用临时 SQLite 文件和 DemoModel。
4. 启动持久化后台 worker，并通过 Python 标准库 HTTP 客户端执行健康检查、会话隔离、聊天、成长预览/确认、后台任务状态、数据导出和全量清除。

该流程在 GitHub runner 内部完成，不需要公网部署或 UI。真实模型 API 测试使用独立手动工作流 `API live HTTP smoke (manual)`（`.github/workflows/api-live-smoke.yml`）、仓库 Secrets 和虚构测试数据；该用例只进行模型连接测试与一次真实对话请求，默认 CI 不消耗真实模型额度。

当前服务为单用户、本地服务；主聊天模型调用仍同步，记忆整理任务在后台执行。它尚未提供账号认证、多租户隔离、远程部署安全、token streaming 或可取消的底层模型请求。不要把它作为公网服务部署。
