"""Manual real-model integration for complete quotes and dense extraction."""
import os
import unittest

from becoming.agent import Agent
from becoming.long_memory import LongMemory
from becoming.memory import SQLiteConversationStore
from becoming.models import OpenAICompatibleModel


class LiveMemorySafety(unittest.TestCase):
    def test_explicit_dense_and_qualified_memory(self):
        store = SQLiteConversationStore(":memory:")
        self.addCleanup(store.close)
        model = OpenAICompatibleModel(os.environ["BECOMING_BASE_URL"],
                                      os.environ["BECOMING_API_KEY"], os.environ["BECOMING_MODEL"])
        memory = LongMemory(store, model, semantic=True)
        agent = Agent(model, store, history_turns=0, long_memory=memory)
        quotes = ["我住在虚构的白石镇", "我每周二休息", "我不会开车",
                  "我长期学习陶艺", "我不喜欢拥挤的场所"]
        agent.reply("请逐条记录以下五条虚构长期记忆：" + "。".join(quotes) + "。")
        self.assertFalse(agent.last_memory_event.errors)
        self.assertGreaterEqual(len(agent.last_memory_event.written_ids), 5)
        actual = memory.list_active()
        for quote in quotes:
            self.assertTrue(any(quote in item.quote for item in actual), quote)
