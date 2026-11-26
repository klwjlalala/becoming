# Becoming

一个帮助用户认识自己、探索人生意义、成为自己想成为的人的 AI 伙伴。

当前版本是核心智能体研究原型，不是完整产品。先建立最小可运行闭环，不预先确定长期记忆、认知或自主调度算法。

## 快速启动

需要 Python 3.11+，运行时仅依赖标准库。

```bash
git clone https://github.com/klwjlalala/becoming.git
cd becoming
python -m becoming --demo
# 单一入口：真实模型 + 成长工具 + 综合长期记忆
python -m becoming --growth --long-memory --comprehensive-memory
# 可选开启动态个人理解（与长期记忆分开存储）
python -m becoming --personal-understanding
python -m unittest discover -s tests -v
```

Demo 为固定的模拟模型，不具有真实 AI 理解能力，也不会发送网络请求。Demo 默认保存在 data/demo.sqlite3，真实模式默认保存在 data/conversations.sqlite3；可用 --db :memory: 不落盘，或 --db <path> 选择文件。/exit 退出，/clear 清除当前数据库中的对话记录（逻辑删除，不保证物理擦除）。

## 统一服务入口（成长辅助）

`python -m becoming --growth --long-memory --comprehensive-memory --personal-understanding` 可在同一对话入口组合长期记忆、动态个人理解、自我探索引导与成长工具。成长数据默认存于 `data/growth.sqlite3`，对话及长期记忆存于 `data/conversations.sqlite3`，可分别用 `--db` 和 `--growth-db` 指定，两个文件不能相同。`/confirm <token>` 确认变更，`/cancel` 取消，`/clear-growth` 后按提示二次确认清除成长记录。`/clear` 只清除对话及关联长期记忆，不删除独立成长记录。删除成长记录不会清除对话或长期记忆中的副本；删除对话也不会删除成长记录。SQLite 逻辑删除不保证物理擦除。

## 接入真实模型

通过环境变量设置兼容 OpenAI Chat Completions 的服务：

```bash
export BECOMING_BASE_URL="https://api.openai.com/v1"
export BECOMING_API_KEY="your-key"
export BECOMING_MODEL="your-model"
python -m becoming
```

PowerShell 可使用 $env:BECOMING_BASE_URL 等变量。真实模式会把当前输入和最近 12 轮历史发送到配置的模型服务；请自行确认服务的数据处理政策。默认不自动发起任何后台模型请求。不要提交真实 API Key、用户对话或数据库。

## 结构

- becoming/agent.py：智能体入口及单轮编排
- becoming/personal_understanding.py：Evidence/Claim/Revision 动态个人理解模型（可选）
- becoming/models.py：可替换模型接口、模拟模型、OpenAI-compatible 适配器
- becoming/memory.py：原始对话持久化（不是长期语义记忆）
- becoming/prompts.py：基础角色提示词
- becoming/__main__.py：命令行入口
- docs/architecture.md：当前设计与后续研究边界
- tests/：确定性功能测试及真实模型显式能力调用集成测试
- evaluation/：智能体效果评测（最小框架）
- docs/testing.md：两类测试的边界、运行方式与验收原则

## 测试

- 功能测试（离线）：`python -m unittest discover -s tests -v`，自动 CI，不消耗真实模型额度。
- 功能测试（真实模型）：`python -m unittest discover -s tests -p 'live_*.py' -v`，显式指定能力、验证真实调用链路；仅按需执行。
- 效果评测：`python -m evaluation`，离线列出通用用例；`python -m evaluation.personal_understanding` 校验 30 轮个人理解场景。
- 真实模型个人理解集成：`python -m unittest discover -s tests -p 'live_personal_understanding.py' -v`，仅显式执行。
- 30 轮纵向评测：`python -m evaluation.personal_understanding --live --max-calls 80 --output artifacts/personal-understanding-live.json`，需人工审查，不自动评分。
- 真实 API 功能冒烟测试仍通过手动 Actions 运行，详见 [测试说明](docs/testing.md)。

## 开发原则

以理解人、帮助人而非任务完成率为核心。用户拥有对自己的最终解释权。区分原始信息与推断；不进行未经验证的心理诊断，不制造依赖；后续记忆与认知机制需支持纠正和删除。暂不引入前端、向量数据库、Agent 框架或多智能体。

## 长期记忆 V1（实验、默认关闭）

真实模型配置完成后，使用 `python -m becoming --long-memory` 显式开启；每个正常回复后最多额外一次模型调用。`/memories` 查看活跃记忆，`/forget <key>` 删除槽位所有修订但保留原始对话，`/clear` 同时清除对话及关联长期记忆（逻辑删除）。模型可能看到有限相关记忆及槽位名称。详见 [长期记忆 V1](docs/long-memory.md)。

### V1.1 实验功能

`python -m becoming --long-memory --semantic-memory` 可选模型语义筛选（每轮最多额外一次调用，最多发送40条记忆原话）。`/forget <key>` 同时阻止同 key 后续写入；`/allow <key>` 解除阻止，不恢复原数据。`/clear` 保留阻止槽位名称。原始对话与近义别名不受单槽位删除保证。提取时会发送有限旧记忆原话供修订判断。


### 综合长期记忆（实验，可选）

    python -m becoming --long-memory --comprehensive-memory

在已有记忆模式基础上支持 UTC 陈述记录日期范围、多主题召回及明确历史回顾中的旧版本。与 --semantic-memory 二选一；最多两次同步检索模型调用。无需迁移数据库。仍需真实模型验证。

    python -m evaluation.cross_time
    python -m evaluation.cross_time --live --case growth-001

对比无记忆、V1.1 和综合检索的同一虚构场景，真实模型命令仅手动执行。


### 长期记忆质量诊断（真实历史对话）

    python -m evaluation.memory_quality
    python -m evaluation.memory_quality --live --case quality-001 --output quality-001.json

三组虚构跨年对话，分别检查提取遗漏、历史修订、候选与选择阶段；三个检索模式共享同一历史快照。报告需人工审查，不自动判断质量通过。真实模式会消耗额度，尤其 quality-003（46 轮）。


V1.3 增加来源分句校验、单轮最多12条记忆、独立提取失败隔离，以及综合检索的时间分层候选。运行方式不变；真实模型准确率与召回净收益尚待验证。


### V1.4 实验模式

    python -m becoming --long-memory --comprehensive-memory --improved-memory
    python -m evaluation.memory_quality --live --improved --case quality-003

可另设置 BECOMING_EMBEDDING_MODEL 并启用 --embedding-memory（CLI）或 --embedding（评测）来比较配置服务的向量接口。无该配置不要开启。分批扫描有额外调用成本；向量实验不代表已验证效果。


### 真实模型完整质量测试（虚构场景）

开发分支的一次性真实模型质量测试：

    python -m evaluation.live_quality --validate
    python -m evaluation.live_quality --live --max-calls 60 --output artifacts/live-quality-report.json

测试包含人生意义与纠正理解、现实约束下的决策、长期记忆生命周期、成长工具完整流程、倾听与话题切换、即时安全风险。所有输入均为虚构内容；记忆场景关闭近期历史窗口，以单独验证长期记忆。成长场景只由测试夹具确认与预期工具和 ID 完全匹配的合成操作，不代表产品自动授权。报告保留逐轮回复、实际记忆/工具事件和 SQLite 最终状态；不使用 LLM 裁判自动给出质量通过结论。完整说明见 docs/live-quality-evaluation.md。

GitHub Actions 一次性执行使用仓库 Secrets：BECOMING_BASE_URL、BECOMING_API_KEY、BECOMING_MODEL。工作流仅由指定测试分支上包含工作流文件的专用提交触发，设置 60 次模型调用硬上限，并上传 JSON/Markdown 报告。真实模型步骤不进入默认 CI。


### 动态个人理解 V1（实验、默认关闭）

在真实模型配置完成后，使用：

    python -m becoming --personal-understanding

它与长期记忆独立存储：长期记忆保存用户明确表达的事实/经历/偏好；个人理解将多条证据关联成可修订的 Claim，并保留版本和修订记录。重要纠正会在回复后即时分析，普通证据最多每 5 轮批量处理；CLI 退出时会 flush。当前是同步原型，不是后台常驻 Agent。检索最多注入 5 条相关理解，不额外调用模型筛选；不相关时不注入。

重要限制：敏感信息拦截只是有限规则与提示词约束，不构成完整隐私保护；SQLite 未加密。不要存储高敏个人信息。模型生成的理解只是候选，不是客观人格结论；用户拥有对自己的最终解释权。完整架构、边界和验收标准见 [动态个人理解 V1 设计](docs/personal-understanding-v1.md)。
