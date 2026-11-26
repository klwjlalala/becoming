import unittest

from becoming.agent import Agent
from becoming.guidance import GUIDANCE_PROMPT
from becoming.memory import SQLiteConversationStore
from becoming.models import ModelError
from becoming.prompts import EXPLORATION_SYSTEM_PROMPT, SYSTEM_PROMPT
from evaluation.guidance import CASES, WithoutGuidanceModel, evaluate


class RecordingModel:
    def __init__(self):
        self.calls = []

    def complete(self, messages):
        self.calls.append([dict(m) for m in messages])
        return "模拟回复"


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.model = RecordingModel()
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)

    def test_guidance_policy_is_applied_once(self):
        answer = Agent(self.model, self.store).reply("我不知道该怎么办")
        self.assertEqual(answer, "模拟回复")
        self.assertEqual(len(self.model.calls), 1)
        content = self.model.calls[0][0]["content"]
        self.assertEqual(content.count(GUIDANCE_PROMPT), 1)
        self.assertTrue(content.startswith(EXPLORATION_SYSTEM_PROMPT))
        self.assertEqual(content, SYSTEM_PROMPT)

    def test_current_constraints_and_corrections_reach_model(self):
        agent = Agent(self.model, self.store)
        for user in ("我想辞职", "存款只够三个月", "其实我暂时不想辞职"):
            agent.reply(user)
        self.assertEqual([m["content"] for m in self.model.calls[-1] if m["role"] == "user"],
                         ["我想辞职", "存款只够三个月", "其实我暂时不想辞职"])
        self.assertEqual(len(self.model.calls), 3)
        self.assertEqual(len(self.store.recent()), 6)

    def test_baseline_preserves_exploration_memory_and_inputs(self):
        messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n历史证据"},
                    {"role": "user", "content": "我很迷茫"}]
        WithoutGuidanceModel(self.model).complete(messages)
        self.assertEqual(self.model.calls[0][0]["content"],
                         EXPLORATION_SYSTEM_PROMPT + "\n历史证据")
        self.assertEqual(self.model.calls[0][1], messages[1])
        self.assertEqual(messages[0]["content"], SYSTEM_PROMPT + "\n历史证据")

    def test_baseline_leaves_unrelated_model_prompts_untouched(self):
        messages = [{"role": "system", "content": "独立记忆提取策略"},
                    {"role": "user", "content": "提取"}]
        WithoutGuidanceModel(self.model).complete(messages)
        self.assertEqual(self.model.calls[0], messages)

    def test_failure_does_not_persist(self):
        class Failing:
            def complete(self, messages):
                raise ModelError("failed")
        with self.assertRaises(ModelError):
            Agent(Failing(), self.store).reply("我很迷茫")
        self.assertEqual(self.store.recent(), [])

    def test_comparison_uses_independent_histories_and_hidden_criteria(self):
        case = CASES["guide-002"]
        report = evaluate(self.model, case, compare=True)
        n = len(case["turns"])
        self.assertEqual(len(self.model.calls), 2 * n)
        self.assertEqual(len(report["guidance"]), n)
        self.assertEqual(len(report["baseline"]), n)
        self.assertEqual(len(self.model.calls[0]), 2)
        self.assertEqual(len(self.model.calls[n]), 2)
        self.assertIn(GUIDANCE_PROMPT, self.model.calls[0][0]["content"])
        self.assertNotIn(GUIDANCE_PROMPT, self.model.calls[n][0]["content"])
        for call in self.model.calls:
            for criterion in case["criteria"]:
                self.assertNotIn(criterion, str(call))
        self.assertEqual(report["status"], "manual review required")

    def test_cases_have_unique_ids_and_usable_content(self):
        self.assertGreaterEqual(len(CASES), 10)
        for key, case in CASES.items():
            self.assertTrue(key.startswith("guide-"))
            for field in ("turns", "criteria"):
                self.assertTrue(case[field])
                self.assertTrue(all(isinstance(s, str) and s.strip() for s in case[field]))


if __name__ == "__main__":
    unittest.main()
