# Electron Main V1

本轮只做桌面基础设施和临时模型配置调试入口，不把临时 HTML 当作产品 UI；正式 Vue3 交互设计下一阶段进行。复用 PR #10 的 Node/Python 服务与既有 API，未修改智能体算法。

## 运行
在项目根目录安装 Python 3.11+ 依赖：`python -m pip install -e .`。
进入 desktop，Node.js 24 下运行 `npm install`、`npm start`。若默认 python 命令不是正确解释器，可在启动 Electron 前设置 BECOMING_PYTHON。暂未打包 Python 或安装器。
Electron 45.5.0 固定版本；当前尚无提交的 npm lockfile，发布前必须补锁定依赖。

## 边界
- Electron Main 单实例，管理 Python 进程、退出及数据目录。
- Renderer 只通过 contextBridge 的显式业务方法调用受控 IPC；校验窗口和主 frame，禁用 Node、启用 sandbox、context isolation，限制导航与权限。
- 本地页面 CSP 禁止网络；不暴露通用 HTTP、服务令牌或已保存密钥。用户输入的新密钥会经过受控 IPC，Main 负责测试连接、应用与可选持久化。
- 模型配置使用 safeStorage 加密整个配置文件；Linux 只允许已识别的系统密钥库，拒绝 basic_text 回退。不可用时仅允许会话配置。测试连接先于配置变更；如果保存失败，明确报告会话配置已应用但未保存。之前保存的配置不会被无意覆盖；取消保存不等于删除旧配置，modelForgetSaved 可显式删除持久化配置，当前会话仍有效。
- 禁止远程明文 HTTP 模型端点及 URL 内嵌凭据；允许 HTTPS 和 loopback HTTP。旧配置不向其他 URL 自动复用密钥。
- 数据清除由 Main 原生对话框确认；普通成长操作继续由后端预览确认。导出 IPC 返回数据对象，正式保存文件交互后续实现。
- 测试使用虚构数据；Node 单测的 fakeStorage 只验证调用/拒绝回退/文件流程，不证明 OS 加密。真实 Electron smoke 验证 renderer/preload/IPC/本地 Python 路径，不验证外部模型或真实系统密钥库持久化。
- SQLite 未加密、真实模型 HTTP smoke、系统密钥库跨平台验收、应用打包、正式 Vue3 UI 仍未完成。
