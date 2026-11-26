import json
import unittest

from becoming.growth_agent import GrowthAgent, PREFIX
from becoming.growth_store import GrowthStore
from becoming.long_memory import LongMemory
from becoming.memory import SQLiteConversationStore


def tool(name, **args):
    return PREFIX + json.dumps({"tool": name, "args": args}, ensure_ascii=False)


class ScriptedModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append([dict(m) for m in messages])
        response = self.responses.pop(0)
        return response


class IntegratedServiceLoopTests(unittest.TestCase):
    def test_memory_conversation_goal_action_reflection_and_recall(self):
        model = ScriptedModel(
            "阅读似乎是你喜欢的一种安静体验。",
            json.dumps([{"key": "reading_time", "category": "subjective",
                         "quote": "我喜欢晚上阅读。", "replaces": None}], ensure_ascii=False),
            "你之前提到喜欢晚上阅读。",
            "[]",
            tool("create_goal", text="重新培养阅读习惯"), "[]",
            tool("create_action", goal_id=1, text="晚上读一页"), "[]",
            tool("update_item", id=2, status="done"), "[]",
            tool("record_reflection", goal_id=1, text="读完后感觉很放松"), "[]",
            tool("get_goal", goal_id=1),
            "目标是重新培养阅读习惯；行动已完成，并记录了读后感受。",
            "[]",
        )
        transcript = SQLiteConversationStore(":memory:")
        growth = GrowthStore(":memory:")
        self.addCleanup(transcript.close)
        self.addCleanup(growth.close)
        memory = LongMemory(transcript, model)
        agent = GrowthAgent(model, transcript, growth, long_memory=memory)

        agent.reply("我喜欢晚上阅读。")
        self.assertEqual(len(agent.last_memory_event.written_ids), 1)

        answer = agent.reply("你还记得我喜欢什么时候阅读吗？")
        self.assertEqual(answer, "你之前提到喜欢晚上阅读。")
        self.assertTrue(agent.last_memory_event.retrieved_ids)
        self.assertIn("我喜欢晚上阅读。", model.calls[2][0]["content"])

        confirmations = []
        for prompt in (
            "我决定重新培养阅读习惯，请帮我建立一个成长目标。",
            "给这个目标添加一个很小的行动：晚上读一页。",
            "我完成了这个行动，帮我标记为完成。",
            "今天读完后我感觉很放松，请帮我记录这次复盘。",
        ):
            response = agent.reply(prompt)
            self.assertIn("尚未保存", response)
            self.assertEqual(agent.last_event["status"], "proposed")
            token = agent.adapter.pending[0]
            self.assertIn("/confirm " + token, response)
            confirmations.append(token)
            agent.reply("/confirm " + token)
            self.assertEqual(agent.last_event["status"], "committed")

        answer = agent.reply("帮我查看这个目标的完整进展。")
        self.assertEqual(answer, "目标是重新培养阅读习惯；行动已完成，并记录了读后感受。")
        self.assertEqual(agent.last_event["status"], "read")
        result = agent.last_event["result"]
        self.assertEqual(result["goal"]["text"], "重新培养阅读习惯")
        self.assertEqual([(x["kind"], x["status"]) for x in result["items"]],
                         [("action", "done"), ("reflection", "recorded")])
        self.assertEqual(len(model.responses), 0)

        history = json.dumps(transcript.recent(100), ensure_ascii=False)
        for token in confirmations:
            self.assertNotIn(token, history)
        self.assertEqual(len(model.calls), 15)
        self.assertEqual(len(growth.read("list_goals", {})["items"]), 1)


if __name__ == "__main__":
    unittest.main()
