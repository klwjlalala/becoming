"""Paired synthetic service scenarios, no model calls unless explicitly requested."""
import argparse
import os

from becoming.agent import Agent
from becoming.long_memory import LongMemory
from becoming.memory_search import ComprehensiveMemory
from becoming.memory import SQLiteConversationStore
from becoming.models import OpenAICompatibleModel

# Date is the UTC date of the user statement, not necessarily the event.
CASES = {
    "growth-001": {
        "title": "职业变化与长期价值观",
        "records": [
            ("2023-02-01", "职业", "fact", "我在广告公司做设计。", False),
            ("2023-03-10", "价值观", "subjective", "我很重视自由安排时间。", False),
            ("2024-02-01", "经历", "experience", "去年做独立项目时，收入不稳定让我很焦虑。", False),
            ("2025-03-01", "职业", "fact", "我现在在学校做设计，已经离开广告公司。", True),
        ],
        "query": "我最近又想换工作，你能结合这几年的变化，帮我看看我到底在追求什么、又该注意什么吗？",
        "criteria": ["区分两次职业陈述和当前状态", "结合自由时间和收入约束",
                     "提出可验证的探索方向，不替用户决定，不把推测当事实"],
    },
    "growth-002": {
        "title": "限定时间范围的兴趣回顾",
        "records": [
            ("2023-06-01", "运动", "subjective", "我喜欢攀岩。", False),
            ("2024-04-01", "创作", "subjective", "我做木雕时觉得很专注。", False),
            ("2024-11-01", "环境", "subjective", "独自去海边散步让我很放松。", False),
            ("2025-01-01", "阅读", "subjective", "我最近喜欢读历史书。", False),
        ],
        "query": "回顾我2024年和你说过的兴趣与放松方式，你觉得我可以从哪里重新找回生活的乐趣？",
        "criteria": ["检索2024年两条相关证据", "不混入2023或2025年的记录",
                     "不武断断言用户现在仍有相同兴趣"],
    },
    "growth-003": {
        "title": "普通技术问题不滥用私人历史",
        "records": [
            ("2024-03-01", "职业", "fact", "我的工作是维修家用电器。", False),
            ("2025-05-01", "爱好", "subjective", "我喜欢安静地读书。", False),
        ],
        "query": "解释一下冰箱的工作原理。",
        "criteria": ["正常解释技术原理", "不引用无关个人信息"],
    },
}


def seed(store, memory, case):
    slots = {}
    for day, key, category, quote, revise in case["records"]:
        turn = store.append_turn(quote, "收到")
        with store.connection:
            store.connection.execute("UPDATE turns SET created_at=? WHERE id=?", (day, turn))
        mid, = memory.write(turn, [(key, category, quote, slots[key] if revise else None)])
        slots[key] = mid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--case", choices=CASES)
    args = p.parse_args()
    if not args.live:
        if args.case:
            p.error("--case requires --live")
        for key, case in CASES.items():
            print(key, case["title"])
        print("Synthetic fixtures only; no model evaluation performed.")
        return 0
    if not args.case:
        p.error("--live requires --case")
    model = OpenAICompatibleModel(os.environ["BECOMING_BASE_URL"], os.environ["BECOMING_API_KEY"],
                                  os.environ["BECOMING_MODEL"])
    case = CASES[args.case]
    for label in ("no-memory", "v1.1", "comprehensive"):
        store = SQLiteConversationStore(":memory:")
        try:
            memory = (ComprehensiveMemory(store, model) if label == "comprehensive"
                      else LongMemory(store, model, semantic=True))
            seed(store, memory, case)
            agent = Agent(model, store, history_turns=0,
                          long_memory=None if label == "no-memory" else memory)
            print(label, agent.reply(case["query"]))
            print("Evidence:", agent.last_memory_event)
        finally:
            store.close()
    print("Manual criteria:", *case["criteria"], sep="\n- ")
    print("Awaiting manual review; no quality verdict.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
