import unittest

from becoming.models import ModelError
from becoming.prompts import BASE_SYSTEM_PROMPT, SYSTEM_PROMPT
from evaluation.live_quality import (
    BaselinePolicyModel, BudgetedModel, CASES, proposal_matches,
    redact_confirmation, validate_cases,
)


class FakeModel:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def complete(self, messages):
        self.calls.append([dict(message) for message in messages])
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class LiveQualityFixtureTests(unittest.TestCase):
    def test_case_catalog_is_complete_and_valid(self):
        self.assertTrue(validate_cases())
        self.assertEqual(len(CASES), 6)
        self.assertIn("memory-lifecycle", CASES)
        self.assertIn("immediate-safety", CASES)

    def test_growth_harness_only_approves_expected_tool_and_ids(self):
        self.assertTrue(proposal_matches(
            "create_goal", {"tool": "create_goal", "args": {"text": "恢复阅读习惯"}}))
        self.assertTrue(proposal_matches(
            "create_action", {"tool": "create_action",
                              "args": {"goal_id": 7, "text": "睡前读十分钟"}},
            goal_id=7))
        self.assertTrue(proposal_matches(
            "update_item", {"tool": "update_item",
                            "args": {"id": 9, "status": "done"}},
            action_id=9))
        self.assertTrue(proposal_matches(
            "record_reflection", {"tool": "record_reflection",
                                  "args": {"goal_id": 7, "text": "读完后更放松"}},
            goal_id=7))
        self.assertFalse(proposal_matches(
            "create_action", {"tool": "create_action",
                              "args": {"goal_id": 8, "text": "睡前读十分钟"}},
            goal_id=7))
        self.assertFalse(proposal_matches(
            "update_item", {"tool": "delete_item", "args": {"id": 9}},
            action_id=9))
        self.assertFalse(proposal_matches(
            "record_reflection", {"tool": "record_reflection",
                                  "args": {"goal_id": 99, "text": "放松"}},
            goal_id=7))
        self.assertFalse(proposal_matches(
            "create_goal", {"tool": "create_goal", "args": {"text": 42}}))

    def test_budgeted_model_counts_calls_and_stops_at_limit(self):
        wrapped = BudgetedModel(FakeModel("one", "two"), max_calls=2)
        self.assertEqual(wrapped.complete([]), "one")
        self.assertEqual(wrapped.complete([]), "two")
        with self.assertRaises(ModelError):
            wrapped.complete([])
        self.assertEqual(wrapped.calls, 2)
        self.assertEqual(len(wrapped.events), 2)

    def test_budgeted_model_records_failure_without_retry(self):
        wrapped = BudgetedModel(FakeModel(ModelError("HTTP 429")), max_calls=2)
        with self.assertRaises(ModelError):
            wrapped.complete([])
        self.assertEqual(wrapped.calls, 1)
        self.assertEqual(wrapped.events[0]["status"], "error")

    def test_baseline_removes_only_companion_policies_and_keeps_suffix(self):
        suffix = "\nMEMORY_CONTEXT: retained"
        source = [{"role": "system", "content": SYSTEM_PROMPT + suffix},
                  {"role": "user", "content": "hello"}]
        fake = FakeModel("ok")
        self.assertEqual(BaselinePolicyModel(fake).complete(source), "ok")
        system = fake.calls[0][0]["content"]
        self.assertTrue(system.startswith(BASE_SYSTEM_PROMPT))
        self.assertNotIn("自我理解与探索", system)
        self.assertNotIn("迷茫时的分析与引导", system)
        self.assertTrue(system.endswith(suffix))

    def test_confirmation_nonce_is_redacted_from_report(self):
        self.assertEqual(redact_confirmation("请 /confirm a1b2c3d4"),
                         "请 /confirm <redacted>")


if __name__ == "__main__":
    unittest.main()
