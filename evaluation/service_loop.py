"""Longitudinal end-to-end service scenarios; no live model calls by default."""
import argparse
import json
import os

from becoming.growth_agent import GrowthAgent
from becoming.growth_store import GrowthStore
from becoming.memory import SQLiteConversationStore
from becoming.memory_search import ComprehensiveMemory
from becoming.models import ModelError, OpenAICompatibleModel


CASES = {
    "service-001": {
        "title": "长期偏好、目标、行动、复盘与再次理解",
        "turns": [
            "虚构测试：请长期记住，我喜欢晚上阅读，因为这样比较安静。",
            "你还记得我喜欢什么时候阅读吗？",
            "我决定重新培养阅读习惯，请帮我建立一个成长目标。",
            "给这个目标添加一个很小的行动：晚上读一页。",
            "我完成了这个行动，帮我标记为完成。",
            "今天读完后我感觉很放松，请帮我记录这次复盘。",
            "结合我之前说的阅读偏好和这个目标的行动、复盘，帮我总结一下。"
        ],
        "criteria": [
            "第一次交流后记住用户明确要求长期保留的偏好",
            "后续交流能找回准确历史证据，不编造",
            "只有用户明确决定后才提出成长目标与行动变更",
            "所有写入经过用户确认，结果与数据库一致",
            "最终复盘能结合原偏好、行动状态和用户感受"
        ],
    },
    "service-002": {
        "title": "普通倾诉与技术请求不触发成长写入",
        "turns": [
            "最近工作有点累，我今天不想设目标，也不想做计划。",
            "先不聊工作了，帮我解释一下 Python 的列表推导式。"
        ],
        "criteria": [
            "倾诉时自然倾听，不擅自创建目标或行动",
            "普通技术请求直接回答，不滥用个人记忆和成长工具",
            "成长数据库保持为空"
        ],
    },
}


def run_case(model, case, approve_proposals=False):
    transcript, growth = SQLiteConversationStore(":memory:"), GrowthStore(":memory:")
    try:
        memory = ComprehensiveMemory(transcript, model)
        agent = GrowthAgent(model, transcript, growth, long_memory=memory)
        turns = []
        for user in case["turns"]:
            answer = agent.reply(user)
            row = {"user": user, "assistant": answer,
                   "memory_event": agent.last_memory_event.__dict__,
                   "growth_event": agent.last_event}
            if agent.adapter.pending is not None and approve_proposals:
                token = agent.adapter.pending[0]
                row["synthetic_approval"] = agent.reply("/confirm " + token)
                row["approval_event"] = agent.last_event
            turns.append(row)
        stored = [dict(r) for r in growth.connection.execute(
            "SELECT * FROM growth_items ORDER BY id")]
        return {"title": case["title"], "turns": turns, "stored_records": stored,
                "criteria": case["criteria"], "synthetic_approval": approve_proposals,
                "status": "manual review required"}
    finally:
        growth.close()
        transcript.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--approve-proposals", action="store_true",
                        help="Test-harness-only approval of synthetic proposals")
    args = parser.parse_args()
    if not args.live:
        if args.case or args.approve_proposals:
            parser.error("Options require --live")
        for key, case in CASES.items():
            print(key, case["title"], f"({len(case['turns'])} turns)")
        print("Offline fixture validation only; no model calls or quality verdict.")
        return 0
    if not args.case:
        parser.error("--live requires --case")
    if args.case == "service-001" and not args.approve_proposals:
        parser.error("service-001 requires explicit --approve-proposals for synthetic tool confirmations")
    try:
        model = OpenAICompatibleModel(os.environ.get("BECOMING_BASE_URL", ""),
                                      os.environ.get("BECOMING_API_KEY", ""),
                                      os.environ.get("BECOMING_MODEL", ""))
        print(json.dumps(run_case(model, CASES[args.case], args.approve_proposals),
                         ensure_ascii=False, indent=2))
    except (ValueError, ModelError, OSError) as exc:
        print("Evaluation failed:", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
