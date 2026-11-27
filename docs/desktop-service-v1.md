# 桌面端服务接入 V1（无 UI）

本分支基于 API First V1 冻结候选版本，不改变智能体、长期记忆或个人理解算法。真实模型 HTTP smoke 仍是独立验收门槛，不以离线测试替代。

## 运行边界

Electron Main 将复用 desktop/main/becoming-service.mjs；目前它是可脱离 Electron 运行的 Node.js 22 模块，尚未加入 BrowserWindow、preload、Renderer 或安装包。

- 调用 start({ demo: true }) 可启动离线演示；默认无模型配置，或者显式传入 modelConfig（base_url、api_key、model）。仅子进程环境注入，不从父进程继承 BECOMING_* 配置。
- dataDir 由未来 Electron Main 提供，例如 app.getPath('userData') 下的业务子目录。SQLite 文件独立于项目工作目录。
- Python 子进程先绑定 127.0.0.1 的系统分配端口，再通过标准输出发送端口握手。Node 使用进程专属随机令牌探测 /health 与 API 版本。
- 桌面模式所有 HTTP 路径均要求 Authorization Bearer，令牌仅在 Main 与子进程中使用。独立开发 API 未设置 BECOMING_SERVICE_TOKEN 时保留原有行为，不可作为公网服务。
- start/stop 支持重复调用；关闭 stdin 触发服务退出，超时才终止子进程。退出后重新 start 恢复原数据目录。不自动重放有副作用的请求。
- request(method, path, body) 固定访问本机 /api/v1，拒绝路径越界及重定向；错误包含 code、status、requestId，不回显请求内容。
- 不将任意 HTTP 请求代理、服务令牌、模型密钥或原始进程日志暴露给 Renderer。未来 preload/IPC 必须使用明确允许的业务操作。
- 此令牌不是操作系统级隔离，不能防御同一用户权限下的恶意进程。系统密钥存储、安装包、单实例桌面应用、真正 Electron 生命周期、强制退出时的实际数据恢复和流式输出尚未验收。

## 本地联调（Node.js 22 + Python 3.11）

    python -m pip install -e .
    node --test desktop/test/becoming-service.test.mjs

CI 在 Linux/Windows 启动真实 Python 子进程，验证鉴权、错误、会话/成长写入和重启恢复；使用 DemoModel 或无模型配置，不调用外部模型。

## API 契约冻结候选

docs/api-v1-routes.json 固定 V1 已有路由与 HTTP 方法，tests/test_api_contract.py 验证实际 OpenAPI 的路由和关键输入字段。允许兼容新增字段与接口；不删除或重命名已有字段/方法、不改变既有语义，破坏性变更进入新版本。响应字段尚未全部使用显式 Pydantic response_model，因此路由检查不是完整响应 Schema 冻结；关键响应由现有 HTTP 测试和桌面集成测试保护。真实模型验证通过后再正式验收。
