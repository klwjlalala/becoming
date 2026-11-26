import json
import unittest

from becoming.growth_agent import GrowthAgent, PREFIX
from becoming.growth_store import GrowthStore
from becoming.long_memory import LongMemory
from becoming.memory import SQLiteConversationStore
from becoming.personal_understanding import PersonalUnderstanding


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
    def test_all_three_context_modules_run_together(self):
        quote = "我希望能自由安排时间。"
        understanding_proposal = json.dumps({
            "evidence": [{
                "ref": "e1", "turn_index": 0, "quote": quote,
                "kind": "direct_statement", "event_time": None,
            }],
            "operations": [{
                "operation": "CREATE", "claim_ref": "c1", "claim_id": None,
                "expected_version": None,
                "content": "用户希望能自由安排时间。",
                "dimension": "values", "basis": "explicit_statement",
                "scope": {}, "temporal_scope": "ongoing",
                "evidence": [{"ref": "e1", "relation": "support"}],
                "reason": "用户直接表达了对自主时间的偏好。",
            }],
            "confirmation": None,
        }, ensure_ascii=False)
        no_change = json.dumps({
            "evidence": [], "operations": [], "confirmation": None,
        }, ensure_ascii=False)
        model = ScriptedModel(
            understanding_proposal,
            "从你之前的表达看，自主安排时间确实是你在意的生活条件。",
            "[]",  # Long-memory extraction after the first reply.
            tool("create_goal", text="每周安排一次自由探索"),
            "[]",  # Long-memory extraction after the growth proposal.
            no_change,  # Flush the two ordinary understanding jobs.
        )
        transcript = SQLiteConversationStore(":memory:")
        growth = GrowthStore(":memory:")
        self.addCleanup(transcript.close)
        self.addCleanup(growth.close)

        source_turn = transcript.append_turn(quote, "明白。")
        memory = LongMemory(transcript, model)
        self.assertEqual(
            len(memory.write(source_turn, [("autonomy", "subjective", quote)])), 1
        )
        understanding = PersonalUnderstanding(transcript, model)
        understanding._enqueue(source_turn, "normal")
        seeded = understanding.process_pending()
        self.assertFalse(seeded.errors)
        self.assertEqual(len(understanding.list_claims()), 1)

        agent = GrowthAgent(
            model, transcript, growth, long_memory=memory,
            personal_understanding=understanding,
        )
        answer = agent.reply(
            "结合之前聊过的内容，我希望能自由安排时间。"
            "你觉得这说明我真正想要什么样的生活？"
        )
        self.assertIn("自主安排时间", answer)
        self.assertTrue(agent.last_memory_event.retrieved_ids)
        self.assertTrue(agent.last_understanding_event.retrieved_claim_ids)
        # Both memory layers are included in the same actual model request.
        system_context = model.calls[1][0]["content"]
        self.assertIn(quote, system_context)
        self.assertIn("用户希望能自由安排时间", system_context)

        proposal = agent.reply("请帮我创建一个成长目标：每周安排一次自由探索。")
        self.assertIn("尚未保存", proposal)
        self.assertEqual(agent.last_event["status"], "proposed")
        token = agent.adapter.pending[0]
        committed = agent.reply("/confirm " + token)
        self.assertIn("已保存变更", committed)
        self.assertEqual(agent.last_event["status"], "committed")
        goals = growth.read("list_goals", {})["items"]
        self.assertEqual(len(goals), 1)
        self.assertEqual(goals[0]["text"], "每周安排一次自由探索")

        flushed = agent.flush_personal_understanding()
        self.assertFalse(flushed.errors)
        self.assertEqual(len(flushed.processed_job_ids), 2)
        self.assertEqual(len(model.responses), 0)


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
