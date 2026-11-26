"""Manual live-model integration test for explicit personal-understanding updates."""
import os
import unittest

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.models import OpenAICompatibleModel
from becoming.personal_understanding import PersonalUnderstanding


class LivePersonalUnderstandingTest(unittest.TestCase):
    def setUp(self):
        required = ("BECOMING_BASE_URL", "BECOMING_API_KEY", "BECOMING_MODEL")
        if not all(os.environ.get(key) for key in required):
            self.skipTest("BECOMING_BASE_URL/API_KEY/MODEL are required for live tests")
        self.model = OpenAICompatibleModel(
            os.environ["BECOMING_BASE_URL"],
            os.environ["BECOMING_API_KEY"],
            os.environ["BECOMING_MODEL"],
        )
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)
        self.understanding = PersonalUnderstanding(self.store, self.model)
        self.agent = Agent(
            self.model, self.store, history_turns=0,
            personal_understanding=self.understanding,
        )

    def test_explicit_update_revision_and_natural_recall(self):
        first = (
            "请更新你对我的理解：我目前把创业视为自己最重要的人生目标。"
            "这是本次虚构测试设定，不代表真实个人资料。"
        )
        self.agent.reply(first)
        self.assertFalse(
            self.agent.last_understanding_event.errors,
            self.agent.last_understanding_event.errors,
        )
        self.assertTrue(self.agent.last_understanding_event.written_claim_ids)
        first_claims = self.understanding.list_claims()
        self.assertTrue(first_claims)

        correction = (
            "更正一下：创业并不是我的人生目标；我真正希望的是有选择权，"
            "创业只是一个可选方式。这仍然只是虚构测试设定。"
        )
        self.agent.reply(correction)
        self.assertFalse(
            self.agent.last_understanding_event.errors,
            self.agent.last_understanding_event.errors,
        )
        self.assertTrue(self.agent.last_understanding_event.written_claim_ids)
        histories = [self.understanding.get_claim_history(claim.id) for claim in first_claims]
        self.assertTrue(any(len(history) >= 2 for history in histories),
                        "explicit correction should revise the existing claim")

        answer = self.agent.reply("结合之前聊过的内容，我真正想要什么样的生活？")
        self.assertTrue(self.agent.last_understanding_event.retrieved_claim_ids)
        self.assertTrue(any(word in answer for word in ("选择", "创业", "人生目标")))

        # Verify the data actually persisted in the test database and every active
        # claim version still has a source-backed evidence row.
        for claim in self.understanding.list_claims():
            history = self.understanding.get_claim_history(claim.id)
            current = [item for item in history if item["version"] == claim.version]
            self.assertEqual(len(current), 1)
            self.assertTrue(current[0]["evidence"])
            for item in current[0]["evidence"]:
                source = self.store.connection.execute(
                    "SELECT user_text FROM turns WHERE id=?", (item["source_turn_id"],)
                ).fetchone()
                self.assertIsNotNone(source)
                self.assertIn(item["quote"], source[0])


if __name__ == "__main__":
    unittest.main()
