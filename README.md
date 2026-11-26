# Becoming

一个帮助用户认识自己、探索人生意义、成为自己想成为的人的 AI 伙伴。

当前版本是核心智能体研究原型，不是完整产品。先建立最小可运行闭环，不预先确定长期记忆、认知或自主调度算法。

## 快速启动

需要 Python 3.11+，运行时仅依赖标准库。

```bash
git clone https://github.com/klwjlalala/becoming.git
cd becoming
python -m becoming --demo
python -m unittest discover -s tests -v
```

Demo 为固定的模拟模型，不具有真实 AI 理解能力，也不会发送网络请求。Demo 默认保存在 data/demo.sqlite3，真实模式默认保存在 data/conversations.sqlite3；可用 --db :memory: 不落盘，或 --db <path> 选择文件。/exit 退出，/clear 清除当前数据库中的对话记录（逻辑删除，不保证物理擦除）。

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
- 效果评测：`python -m evaluation`，离线列出用例；真实模型调用须显式 `--live --case <ID>`，自然场景评估需求理解、能力选择、解决效果。
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
