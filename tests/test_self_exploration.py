import unittest

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.models import ModelError
from becoming.prompts import BASE_SYSTEM_PROMPT, SYSTEM_PROMPT
from becoming.self_exploration import SELF_EXPLORATION_PROMPT
from evaluation.self_exploration import BaselineModel, CASES, run_case


class RecordingModel:
    def __init__(self):
        self.calls = []

    def complete(self, messages):
        self.calls.append([dict(m) for m in messages])
        return "模拟回复"


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)
        self.model = RecordingModel()
        self.agent = Agent(self.model, self.store)

    def test_policy_is_additive_and_applied_to_agent(self):
        self.assertEqual(SYSTEM_PROMPT, BASE_SYSTEM_PROMPT + "\n" + SELF_EXPLORATION_PROMPT)
        self.agent.reply("我想认识自己")
        self.assertTrue(self.model.calls[0][0]["content"].startswith(SYSTEM_PROMPT))
        self.assertEqual(len(self.model.calls), 1)

    def test_multiturn_preserves_actual_user_correction(self):
        for message in ("我不喜欢聚会", "不是讨厌别人", "先不分析了"):
            self.agent.reply(message)
        self.assertEqual(len(self.model.calls), 3)
        self.assertEqual([m["content"] for m in self.model.calls[-1] if m["role"] == "user"],
                         ["我不喜欢聚会", "不是讨厌别人", "先不分析了"])
        self.assertEqual(len(self.store.recent()), 6)

    def test_no_extra_storage_on_failure(self):
        class Broken:
            def complete(self, messages):
                raise ModelError("failed")
        with self.assertRaises(ModelError):
            Agent(Broken(), self.store).reply("我想理解自己")
        self.assertEqual(self.store.recent(), [])

    def test_baseline_removes_only_policy_and_retains_context(self):
        messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n历史证据"},
                    {"role": "user", "content": "你好"}]
        BaselineModel(self.model).complete(messages)
        self.assertEqual(self.model.calls[0][0]["content"], BASE_SYSTEM_PROMPT + "\n历史证据")
        self.assertTrue(messages[0]["content"].startswith(SYSTEM_PROMPT))
        self.assertEqual(self.model.calls[0][1], messages[1])

    def test_paired_runner_uses_separate_histories_and_no_criteria(self):
        case = CASES["explore-003"]
        first = run_case(self.model, case)
        second = run_case(self.model, case, baseline=True)
        n = len(case["turns"])
        self.assertEqual(len(first), n)
        self.assertEqual(len(second), n)
        self.assertEqual(len(self.model.calls), 2 * n)
        self.assertEqual(len(self.model.calls[0]), 2)
        self.assertEqual(len(self.model.calls[n]), 2)
        for call in self.model.calls:
            for criterion in case["criteria"]:
                self.assertNotIn(criterion, str(call))

    def test_case_definitions(self):
        self.assertGreaterEqual(len(CASES), 8)
        for case in CASES.values():
            for field in ("turns", "criteria"):
                self.assertTrue(case[field])
                self.assertTrue(all(isinstance(x, str) and x.strip() for x in case[field]))


if __name__ == "__main__":
    unittest.main()
