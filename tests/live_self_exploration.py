"""Explicit live integration, one model call; quality remains manually reviewed."""
import os
import unittest

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.models import OpenAICompatibleModel
from becoming.self_exploration import SELF_EXPLORATION_PROMPT


class LiveExplorationTest(unittest.TestCase):
    def test_explicit_exploration_request(self):
        delegate = OpenAICompatibleModel(os.environ.get("BECOMING_BASE_URL", ""),
                                         os.environ.get("BECOMING_API_KEY", ""),
                                         os.environ.get("BECOMING_MODEL", ""))
        calls = []

        class ObservedModel:
            def complete(self, messages):
                calls.append(list(messages))
                return delegate.complete(messages)

        store = SQLiteConversationStore(":memory:")
        self.addCleanup(store.close)
        user = "虚构测试：我想探索自己为何如此重视创作自由。请先问一个具体问题，不要给结论。"
        answer = Agent(ObservedModel(), store).reply(user)
        self.assertEqual(len(calls), 1)
        self.assertIn(SELF_EXPLORATION_PROMPT, calls[0][0]["content"])
        self.assertTrue(answer.strip())
        self.assertEqual([m["content"] for m in store.recent()], [user, answer])
        print("Explicit exploration response (manual quality review):", answer)
