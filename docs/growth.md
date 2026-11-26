# 第五阶段：个人成长与行动辅助 V1

## 用户价值与边界

从自我理解、方向判断进入可选择的行动、体验反馈和调整。目标是用户认可的方向，不是 AI 对人格的评估；行动可以是小尝试；复盘记录用户确认的经历与感受。允许暂停、跳过和删除，不用任务完成率定义成长。不含提醒、打卡、后台自主执行或完整产品 UI。

## 实现

独立 growth_store.py（SQLite）、growth_agent.py（组合现有 Agent）、growth_cli.py（显式启用）。原有 Agent/Model/CLI、长期记忆实现与提示词不改。使用现有文本模型协议：普通回复正常生成；模型通过 GROWTH_TOOL 换行 + JSON 对象发出最多一个工具请求；严格校验名称/参数；查询执行后把实际数据传回模型生成回应，并附真实数据。无原生 function calling 或多工具循环；后续若确有需求再升级。普通轮次一次模型请求，查询最多两次（不计可选长期记忆）；无后台请求。

七个工具：list_goals、get_goal（分页30条）；create_goal、create_action、record_reflection、update_item、delete_item。目标 active/paused/completed，行动 pending/done/skipped，复盘可改文字。删除目标级联删除行动与复盘，预览包含受影响记录 ID/版本；不自动生成目标或行动。

所有变更均只生成本地预览及一次性 token，用户必须输入 /confirm token；/cancel 或下一轮普通消息取消，退出/重启不保留。模型文本永远不能触发确认。确认重新校验预览，在 SQLite 写事务中检查版本并原子提交；成功/失败直接由代码输出。确认不进入模型对话历史，后续应查询实际记录，不能依据先前提案判断已写入。工具事件区分 proposed/read/committed/rejected/failed。无认证、多用户、跨进程审批或数据库加密。

成长数据库与对话数据库独立；/clear 仅清对话，删除成长记录通过确认后的删除工具；SQLite 删除不保证物理擦除。查询结果会发送给模型服务并作为对话文本持久化，删除成长记录不会清除历史对话或长期记忆中的副本。独立 CLI 提供数据隔离，实际发布前必须完善统一删除、用户界面、隐私说明和跨模块回归。PR #1 尚未合并；可选 --long-memory 仅在合并后可用，未声称已联合测试。

## 运行

    python -m becoming.growth_cli
    python -m becoming.growth_cli --db :memory: --growth-db :memory:

使用 BECOMING_BASE_URL、BECOMING_API_KEY、BECOMING_MODEL；默认本地数据文件在 data/。只有显式启动 growth_cli 才启用工具，原 CLI 保持兼容。建议用独立测试数据库。模型可能错误提议工具，审批机制保护持久化，不保证语义质量或模型回复安全。

## 验收

    python -m unittest discover -s tests -v
    python -m unittest discover -s tests -p live_growth.py -v
    python -m evaluation.growth
    python -m evaluation.growth --live --case growth-action-001 --approve-synthetic

离线覆盖实际七工具、持久化、分页、参数校验、拒绝/取消/重复/重启、并发状态变化、模型失败、对话存储失败、结果返回及不允许二次调用。真实显式功能用例逐项通过模型调用、用户确认、结果及数据库验证，不以回答中的工具名为依据。自然场景不指定工具；记录实际事件及最终状态，人工评价是否选择正确工具、是否过度记录和是否帮助成长。评测仅虚构数据；--approve-synthetic 是测试端主动批准全部合法提案以暴露错误提案，不是线上行为。真实模型测试默认不执行，不宣称效果通过。

本 PR 基于第四阶段分支；待前序 PR 合并后调整目标分支。长期记忆组合、正常产品入口、完整端到端服务属于下一阶段。


## 第六阶段集成说明

第五阶段独立 CLI 保留兼容；统一入口已在后续集成分支中提供：`python -m becoming --growth --long-memory --comprehensive-memory`。GrowthAgent 现在可以组合现有长期记忆对象，所有能力共享同一对话历史；成长数据仍位于独立 SQLite 文件。

待确认 nonce 只附加在本地 CLI 返回文本，不进入模型上下文和对话存储。确认、取消及被新消息作废的提案会写入对话记录，且不将 nonce 持久化。查询结果由模型根据真实工具结果自然总结；真实结构化结果保留在工具事件中，不默认把原始 JSON 拼进回答。

`/clear-growth` 需二次确认并级联删除成长数据库中的目标、行动和复盘；不会删除对话、长期记忆中的副本或外部服务副本。该原型尚无跨库原子事务、账户隔离、加密或物理安全擦除。
