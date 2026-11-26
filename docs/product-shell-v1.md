# 产品化 V1：API First 后端服务基线

状态：产品化设计基线；本阶段不开发任何 Web/Electron 页面  
依赖：PR #1–#7 的核心 Agent、长期记忆、自我探索/引导、成长服务和动态个人理解  
目标：先把现有研究原型封装为完整、可独立运行、可通过 HTTP 调用和自动化联调的后端服务；接口稳定后再开发 Electron 桌面端。

## 1. 决策：API First，不做 Web First

当前不需要为了联调先开发 Web UI。Web 页面会增加一套暂时没有产品价值的客户端代码，不能替代对 Agent、数据、工具和会话服务本身的验证。

采用以下路径：

1. Python 核心能力保留，增加稳定的 HTTP API 服务层。
2. GitHub Actions 启动真实 API 进程，通过 HTTP 请求跑端到端测试。
3. 本地开发可通过 OpenAPI/Swagger 文档或 curl/Postman 调用接口；Swagger 仅作为开发调试工具，不作为产品页面。
4. API、会话、数据管理、错误处理、真实模型联调稳定后，再开发 Electron + Vue 3 桌面端。
5. Electron Main 作为本地客户端，调用同一套后端 API；不重写 Agent，也不另做一套业务逻辑。

后端服务先以本机单用户模式运行，默认只绑定 loopback（127.0.0.1），不直接开放公网。GitHub Actions 中的服务只在 runner 内部启动，用测试数据库和虚构数据。

## 2. 产品目标与核心原则

Becoming 首先是一个长期、自然、可信赖的 AI 伙伴，帮助用户理解自己、梳理困惑，在迷茫时提供有依据的分析和建议。

产品优先级：

1. 自然交流和长期关系连续性。
2. 逐渐形成、能够修正的个人理解。
3. 用户明确需要时提供成长目标、行动和复盘工具。
4. 记忆与成长数据的透明管理和用户控制。

不以任务完成率、人格评分、连续打卡、画像完整度或 AI 主动干预次数衡量产品价值。

## 3. 后端 V1 API 范围

统一前缀：`/api/v1`。所有接口使用 JSON；错误响应有稳定的错误码、用户可读消息和 request_id。模型原始异常、密钥和内部堆栈不返回给客户端。

### 3.1 服务与模型配置

- `GET /health`：服务存活状态、API 版本、数据库状态。
- `GET /capabilities`：当前启用的模块和可用功能。
- `GET /model/config`：返回服务商、Base URL、模型名称和是否已配置；绝不返回 API Key。
- `PUT /model/config`：更新当前进程运行时模型配置；密钥只保存在进程内存，不写入数据库、普通配置文件或日志。
- `POST /model/test`：对指定模型配置发起最小真实请求，区分配置、鉴权、网络和模型响应错误。

当前 API 进程不负责永久保存 API Key。后续 Electron Main 使用操作系统安全存储保存密钥，并在启动本地 Python 服务时注入运行时配置；重启后由 Electron 重新注入。独立开发/CI 环境可通过环境变量注入。未来若需要独立 Web 客户端，必须另行设计身份认证和密钥托管，不能直接开放当前本地单用户服务。

### 3.2 会话与对话

- `GET /conversations`：分页列出会话。
- `POST /conversations`：创建会话。
- `GET /conversations/{id}`：会话元数据。
- `PATCH /conversations/{id}`：重命名、归档。
- `DELETE /conversations/{id}`：删除会话及其来源证据。
- `GET /conversations/{id}/messages`：分页读取消息。
- `POST /conversations/{id}/messages`：发送一条用户消息，返回 assistant 回复和结构化执行事件。
- `POST /conversations/{id}/cancel`：取消当前请求（仅在底层模型请求支持可靠取消后开放；V1 不承诺假取消）。

会话近期历史按 conversation_id 隔离；长期记忆与个人理解是用户级资料，可以跨会话使用，但必须根据当前请求的相关性检索。删除一个会话时，其来源记忆、证据及失去来源的理解必须级联清理；其他会话和其他来源仍有效的记忆保留。

### 3.3 成长工具

- `GET /growth/goals`：分页读取目标。
- `GET /growth/goals/{id}`：读取目标、行动和复盘。
- `POST /growth/changes`：对创建/更新/删除请求生成真实数据库预览，不写入。
- `POST /growth/changes/{id}/confirm`：确认一次性预览并提交。
- `POST /growth/changes/{id}/cancel`：取消预览。

聊天中模型提出的成长工具调用仍必须经过现有 GrowthStore 校验、预览和明确确认；API 返回结构化 preview/confirmation_required 字段，不依赖 UI 从自然语言中解析 nonce。普通聊天、愿望表达和建议讨论不自动创建成长记录。

### 3.4 记忆与个人理解管理

- `GET /memories`：查看活跃长期记忆、来源和时间。
- `DELETE /memories/{key}`：删除指定记忆槽位并阻止自动重写。
- `POST /memories/{key}/allow`：恢复未来写入（不恢复已删除内容）。
- `GET /understanding/claims`：查看当前个人理解命题及证据摘要。
- `GET /understanding/claims/{id}`：查看单个命题和版本历史。
- 用户纠正/拒绝理解优先通过自然对话完成；管理 API 可提供显式拒绝/删除操作，但不得绕过现有证据、版本和审计规则。

主聊天响应不播报每次理解更新；用户主动检查时才展示原话、来源、当前理解、适用范围和版本历史。模型推断不能覆盖用户自己的最终解释权。

### 3.5 数据导出与清除

- `GET /data/export`：导出对话、长期记忆、个人理解和成长记录。
- `POST /data/clear`：预览全部本地数据清除范围。
- `POST /data/clear/confirm`：二次确认后清除两个数据库中的业务数据。

删除界面必须说明逻辑删除、备份/WAL 文件和模型服务副本的边界。不得声称可远程删除第三方模型服务保留的数据。

## 4. 服务架构

建议使用 FastAPI + Uvicorn。理由：现有 Python 核心可直接复用，接口契约清晰，OpenAPI 文档自动生成，既能被 Electron 调用，也方便 GitHub Actions 通过 HTTP 做端到端测试。

分层：

- API 层：Pydantic 请求/响应模型、路由、错误映射、request_id；不承载业务规则。
- Application/Service 层：会话生命周期、Agent 装配、成长确认、记忆管理、导出/删除。
- Domain/Core 层：复用现有 Agent、GrowthAgent、LongMemory、PersonalUnderstanding、GrowthStore 和 Model 接口。
- Persistence 层：SQLite 会话/对话/记忆数据库与成长数据库；统一 schema migration。
- Model Adapter：继续复用 OpenAI-compatible 模型适配器；API 层不直接拼模型提示词。

建议目录：

```
becoming/
  api.py                 # FastAPI app factory / lifespan
  api_models.py          # Pydantic DTO
  api_errors.py          # 稳定错误码映射
  services/
    runtime.py           # 应用运行时、配置、生命周期
    conversations.py     # 会话与 Agent 装配
    data_management.py   # 导出、清除
  ...                    # 现有 Agent/Memory/Growth 核心模块
```

API 层必须薄；不为了每个端点复制一套业务逻辑。

## 5. 会话与 Agent 生命周期

当前 SQLite turns 表没有 conversation_id，CLI 只有一条连续历史。产品化前必须新增 conversations 表和迁移。

- 旧数据库迁移时，把既有 turns 归入一个默认会话，保证 CLI 旧数据可继续读取。
- 每条 turn 归属一个 conversation_id；近期历史只读取当前会话。
- 长期记忆和个人理解仍是用户级数据，跨会话检索，但来源仍指向原始 turn。
- 删除会话时先删除该会话 turns，再依靠外键/显式清理删除来源记忆、证据、命题和更新任务；若某个理解仍有其他有效来源，不得误删。
- 每个会话的待确认成长提案必须隔离；确认码一次性、过期或新消息到达时失效。
- API 服务按会话串行处理同一会话的写操作；不同会话可逐步并行。V1 不承诺同一会话并发消息的顺序语义，服务应通过冲突响应避免静默乱序。

## 6. 回复与记忆更新

当前 Agent.reply() 在主回复保存后同步执行长期记忆提取和个人理解更新。对于日常产品，这可能使回复被后置分析拖慢。

目标行为：

1. 优先生成并持久化主回复。
2. 返回主回复和当前可观测状态。
3. 记忆提取/个人理解更新进入持久化后台队列。
4. 后台任务有状态、重试上限、失败记录和进程重启恢复。
5. 后台更新不得修改已经返回给用户的 assistant 回复；失败不能丢失主回复。
6. 重要纠正是否需要同步确认，必须保留现有产品约束，不能为了提速而丢失用户明确修订。

该机制不要求建设复杂消息队列；第一版可使用 SQLite job table + 单进程 worker。只有实际负载证明不足时才引入 Redis/Celery 等外部基础设施。

## 7. GitHub 联调与测试策略

每个 PR 的 GitHub Actions 执行：

1. 安装 Python 依赖并运行原有 168 项离线功能回归。
2. 启动 FastAPI/Uvicorn 本地服务，使用临时 SQLite 数据库和 Demo/Scripted Model。
3. 使用真实 HTTP 客户端请求 health、model config、conversation CRUD、chat、growth preview/confirm、memory/understanding 管理、导出/清除等接口。
4. 检查响应 schema、错误码、数据库最终状态、跨会话隔离和删除级联。
5. 单独的手动工作流使用 GitHub Secrets 配置真实模型，执行少量虚构数据的真实 HTTP 端到端测试；默认 CI 不消耗真实模型额度。

必须区分：
- 直接调用测试：验证业务方法。
- HTTP API 集成测试：验证路由、序列化、状态码和服务装配。
- 真实模型端到端测试：验证真实模型通过 API 运行完整流程。
- 效果测试：评估模型是否理解用户、是否在正确场景使用工具及长期理解是否有帮助。

GitHub Actions 只启动 runner 内部的服务，不把测试 API 暴露公网。测试用虚构数据和临时数据库，不使用真实用户数据。

## 8. 安全与运行边界

- 默认仅监听 127.0.0.1；不绑定 0.0.0.0，不开放公网。
- 本地单用户 V1 暂不实现账号系统；如果部署远程服务，必须先补身份认证、授权、速率限制和密钥管理。
- API Key 只存在于进程内存或运行时环境，不能进入数据库、日志、异常响应、导出或 Git。
- 限制请求体大小、消息长度、分页大小；对所有路径参数、ID、枚举和状态进行服务端校验。
- 不允许客户端传入任意文件路径、SQL、模型 system prompt 或内部数据库连接参数。
- CORS 默认关闭；Electron 通过 Main 访问 loopback API。后续如有浏览器客户端需求再显式配置可信 origin。
- SQLite 未加密、逻辑删除和模型服务数据留存等限制必须在产品隐私说明中明确。

## 9. 实施顺序

1. **服务基础**：FastAPI app factory、配置注入、健康检查、错误模型、服务生命周期、CI HTTP smoke test。
2. **会话层**：SQLite migration、会话 CRUD、近期历史隔离、旧 CLI 兼容。
3. **对话 API**：Agent/GrowthAgent 装配、消息发送、结构化工具事件、成长确认/取消。
4. **个人数据 API**：长期记忆、个人理解、成长查询、来源查看。
5. **数据治理**：导出、全量清除、会话删除级联和恢复验证。
6. **后台更新**：持久化记忆任务队列，回复与后置更新解耦。
7. **真实模型联调**：GitHub Actions 手动工作流 + 虚构测试数据，人工检查报告。
8. 上述接口稳定后才进入 Electron + Vue 3 UI；不先做 Web 前端。

## 10. V1 验收标准

- 后端可通过单一命令启动并提供 OpenAPI schema。
- GitHub Actions 能启动实际 HTTP 服务并调用接口，不依赖 UI。
- 新建多个会话，消息历史严格隔离；长期记忆/个人理解按相关性跨会话使用。
- Agent、GrowthAgent、记忆模块复用现有核心，不复制业务规则。
- 成长变更必须经过预览与确认；API 能结构化返回确认状态。
- 删除会话后，相关来源证据不再召回；其他会话数据保留。
- API Key 不出现在响应、日志、数据库、导出或 Git。
- 服务异常、模型失败、SQLite 错误均有稳定错误响应，不返回内部堆栈。
- 原有 CLI 和 168 项测试继续通过。
- 完成至少一轮真实模型通过 HTTP API 的虚构数据端到端联调。
- API 验收通过后再开发 Electron 客户端。

## 11. 暂缓项

不开发 Web UI、不开发 Electron UI、不实现云同步/多用户/远程部署、不引入 Redis/Celery、不建设复杂微服务、不做流式传输（除非真实交互需要）、不新增向量检索/人格算法，除非真实 API 评测发现明确阻塞。
