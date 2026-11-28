# AI 好友 Web 页面 V1

## 本轮范围

本轮在 `feat/ai-friend-web-v1` 上完成 AI 好友主页面，不改写 Node Agent 的记忆、个人理解、成长工具业务逻辑，也不迁移旧 Python 数据库。

- 单一长期会话：Web 不展示会话切换或新建会话入口，始终使用 `default`。
- 左侧主导航固定；桌面端约 232px，窄屏收纳为底部导航。
- 顶部只保留页面身份、连接状态和历史搜索。
- 聊天内容居中，最大宽度约 900px；不设置永久右侧栏。
- 首次欢迎、长历史分页、关键词/日期搜索、消息复制、流式回复、停止、失败重试。
- 示例对话仅在用户主动点击后展示，明确标记为虚构内容，不写入数据库。
- 深浅主题切换保存在当前浏览器本地。

“我的行动”和“关于我”只在导航中预留位置，本轮不实现其业务页面。示例任务、观察和人生记录卡片不代表真实数据，也不会产生业务写入。

## API 增量

### `POST /api/chat/stream`

请求：

```json
{
  "text": "用户消息",
  "request_id": "客户端生成的 UUID"
}
```

响应为 Server-Sent Events：

- `event: token`：`data: {"text":"..." }`
- `event: done`：`data: {"turn":{...}}`
- `event: error`：`data: {"message":"..."}`

客户端断开连接时会中止本轮模型请求；Agent 仅在完整回复成功后保存对话轮次。请求 ID 由本地 SQLite 建立幂等映射，客户端重试不会重复写入已完成轮次。

### `GET /api/history`

默认返回长期会话最近 80 轮及分页游标。传入 `before` 可读取更早记录；传入 `around` 可读取指定消息附近的历史，用于搜索结果定位。

### `GET /api/search?q=关键词&from=YYYY-MM-DD&to=YYYY-MM-DD`

在当前长期会话中执行本地关键词与日期范围检索，不调用模型、不执行语义搜索。

### `GET /api/requests/{request_id}`

查询客户端请求是否已成功保存，用于处理连接在提交后中断的边界情况。

### Python 模型网关

新增 `POST /v1/llm/stream`，只负责将 OpenAI-compatible Chat Completions SSE 数据流转发给 Node。模型配置仍由 Python 网关读取环境变量；Node 仍是 Agent 和本地数据的唯一所有者。

## 本地启动

终端 1：

```bash
python -m pip install -e . httpx
export BECOMING_BASE_URL="https://api.openai.com/v1"
export BECOMING_API_KEY="your-provider-key"
export BECOMING_MODEL="your-model"
python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

终端 2：

```bash
npm --prefix agent-runtime start
```

浏览器访问 `http://127.0.0.1:4310`。真实模型请求会消耗配置服务的额度；没有配置模型时，页面仍可打开并查看静态示例，但发送消息会失败。

## 测试

```bash
npm --prefix agent-runtime test
npm --prefix agent-runtime run test:effects
python -m unittest server.test_gateway -v
python server/smoke_local.py
```

新增离线测试覆盖流式分片、取消不落盘、请求 ID 幂等、历史分页、指定消息附近导航、关键词检索及 Python SSE 转发。真实模型测试仍须显式手动执行，不纳入默认 CI。

## 已知边界

- 本地单用户运行时；没有账号、多租户或公网部署能力。
- 任务管理、自我认识、人生记录的正式业务页面与数据模型尚未在本轮实现。
- 历史搜索为本地关键词/日期检索，不是语义搜索。
- 流式体验依赖配置的上游模型兼容 SSE；不支持流式的上游会明确失败，不伪装为真实 token streaming。
- 页面示例卡片只用于体验布局，不会写入任务、个人认识或人生记录。
