# 第六阶段：完整产品服务闭环 V1

## 目标

将长期记忆、自我理解、迷茫引导、成长目标、行动和复盘放在同一个持续对话服务中，验证同一个用户上下文能否跨越多轮交流，形成“理解—判断—尝试—反馈—重新理解”的闭环。产品核心仍是朋友式的长期 AI 伙伴；工具只在用户明确需要时介入。

## 单一运行入口

    python -m becoming --growth --long-memory --comprehensive-memory --personal-understanding

兼容现有环境变量 BECOMING_BASE_URL、BECOMING_API_KEY、BECOMING_MODEL。对话及长期记忆使用 data/conversations.sqlite3；成长目标、行动和复盘使用 data/growth.sqlite3。可分别通过 --db、--growth-db 指定，禁止两个文件指向同一路径。旧 growth_cli 保留兼容，但统一入口优先。

普通对话沿用原 Agent；启用 --growth 后由 GrowthAgent 组合成长工具与可选长期记忆、动态个人理解。长期记忆与个人理解共享对话数据库但使用独立数据表：前者保存用户明确表达的原始事实/经历，后者形成有证据、可修订的理解命题。两者的提取/检索均使用原始模型适配器，不经过成长工具协议；个人理解默认关闭，需显式添加 --personal-understanding。成长变更需要本地一次性确认；nonce 只附加在 CLI 返回文本，不进入模型上下文或对话历史。确认、取消及被新消息作废的提案会形成普通对话事件，便于后续理解上下文。

查询工具把实际数据库结果传回模型，由模型自然总结。成功时不再把原始 JSON 强行拼接到回复；实际结构化结果保留在工具事件。读取失败时如实降级。

## 数据与删除边界

对话与长期记忆共享数据库；删除对话会级联删除来源记忆，但保留 blocked_memory_keys。成长记录使用独立数据库：
- /clear：清除对话和关联长期记忆，成长记录保留。
- /clear-growth：生成一次性确认码；/confirm-growth-clear <token> 清除全部成长目标、行动和复盘。
- /forget <key>：删除对应记忆槽位的所有版本并阻止该槽位再次写入。

清除成长数据不会删除对话/长期记忆中曾出现的副本；清除对话也不会删除成长记录。查询结果可能作为对话内容发送到模型服务并保存在对话历史中。SQLite 删除是逻辑删除，不保证安全物理擦除；WAL、备份、模型服务副本不在当前实现控制范围。当前为单用户本地原型，无账户、多用户权限、加密或正式数据治理，不适合直接公开上线。

## 评测

离线功能回归：

    python -m unittest discover -s tests -v
    python -m evaluation.service_loop

真实模型集成（显式执行，使用虚构数据）：

    python -m unittest discover -s tests -p live_service_loop.py -v
    python -m evaluation.service_loop --live --case service-001 --approve-proposals
    python -m evaluation.service_loop --live --case service-002

service-001 覆盖明确记忆、跨轮召回、成长目标、行动、完成、复盘及再次总结。评测端的 --approve-proposals 只在虚构测试中显式批准模型提案，不代表产品自动批准。service-002 检查倾诉和普通技术请求不会误触发成长写入。报告记录模型实际工具事件、记忆事件及最终数据库状态，所有效果结论仍需人工审阅。

离线测试使用脚本模型验证真实代码路径；tests/test_service_loop.py 覆盖长期记忆、动态个人理解和成长工具同时启用的组合路径，tests/test_cli.py 覆盖统一入口的全部可选模块启动。真实模型用例不由 CI 自动执行，不自动消耗额度。一次成功的工具调用不代表长期理解质量已经通过。

## 本阶段明确不做

前端 UI、移动端、提醒推送、打卡机制、后台自主行动、心理诊断、永久人格画像、多用户账户、云同步及自动清理。下一步应先用真实模型验证整段闭环，再决定是否需要产品界面和更复杂的服务层。
