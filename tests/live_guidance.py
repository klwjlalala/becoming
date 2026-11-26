"""Explicit live policy integration test; does not assert subjective quality."""
import os
import unittest

from becoming.agent import Agent
from becoming.guidance import GUIDANCE_PROMPT
from becoming.memory import SQLiteConversationStore
from becoming.models import OpenAICompatibleModel


class LiveGuidanceTest(unittest.TestCase):
    def test_explicit_guidance_request(self):
        delegate = OpenAICompatibleModel(os.environ.get("BECOMING_BASE_URL", ""),
                                         os.environ.get("BECOMING_API_KEY", ""),
                                         os.environ.get("BECOMING_MODEL", ""))
        calls = []

        class Observed:
            def complete(self, messages):
                calls.append(list(messages))
                return delegate.complete(messages)

        store = SQLiteConversationStore(":memory:")
        self.addCleanup(store.close)
        user = "虚构测试：我在两个工作机会间犹豫，请帮我分析取舍，不替我决定。"
        reply = Agent(Observed(), store).reply(user)
        self.assertEqual(len(calls), 1)
        self.assertIn(GUIDANCE_PROMPT, calls[0][0]["content"])
        self.assertTrue(reply.strip())
        self.assertEqual([m["content"] for m in store.recent()], [user, reply])
        print("Explicit guidance response (manual quality review):", reply)
