# 真实模型自动化测试

## 一次性配置

在仓库 Settings → Secrets and variables → Actions → New repository secret 中建立三个 Repository secrets：

| Name | Value |
| --- | --- |
| BECOMING_BASE_URL | 兼容 Chat Completions 的接口根地址（包含 /v1） |
| BECOMING_API_KEY | 专用、可撤销的测试密钥 |
| BECOMING_MODEL | 服务商提供的模型 ID |

不要将真实密钥放入代码、提交、Issue 或 workflow_dispatch 输入。公开仓库的 Actions 日志可能公开可见。

## 执行

1. 打开仓库 Actions 页面，选择 Live model smoke test。
2. 点击 Run workflow，选择 main，然后再次点击 Run workflow。
3. 查看 Offline regression tests 与 Live model conversation and restart 两个 job。

仅手动触发，不在 push、PR 或定时事件中调用真实模型。离线测试失败时不启动真实模型 job；真实模型 job 仅允许 main 分支执行。每次成功运行发出三次模型请求，使用虚构随机代号及临时 SQLite 数据库，不上传对话产物。日志记录耗时、回复长度与测试结果，不主动输出凭据。工作流串行运行，设有超时。

## 排查

- Missing environment variables：检查三个 Repository secrets 的名称和配置。
- Model connection failed：检查 GitHub-hosted runner 到服务端的网络、防火墙、端口和 TLS 证书；不关闭证书验证。
- HTTP 401/403：检查密钥、访问权限。
- HTTP 404：检查接口路径及模型 ID。
- HTTP 429：检查服务额度与频率限制。
- 回忆代号断言失败：检查模型是否正确理解历史上下文。

本测试验证基础对话、近期上下文及数据库重开后的恢复能力，不代表已经具备长期记忆、认知能力或人格评测。暂不记录 Token 账单。

本地也可运行：python -m unittest discover -s tests -p live_smoke.py -v（先通过环境变量提供配置）。
