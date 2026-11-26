"""Manual, real-model explicit capability test. Uses synthetic data only."""
import os
import unittest
import uuid
from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.long_memory import LongMemory
from becoming.models import OpenAICompatibleModel


class LiveMemoryTest(unittest.TestCase):
    def test_explicit_remember_retrieve_update(self):
        model = OpenAICompatibleModel(os.environ["BECOMING_BASE_URL"],
                                      os.environ["BECOMING_API_KEY"],
                                      os.environ["BECOMING_MODEL"])
        store = SQLiteConversationStore(":memory:")
        self.addCleanup(store.close)
        memory = LongMemory(store, model)
        agent = Agent(model, store, history_turns=0, long_memory=memory)
        marker = "BE-" + uuid.uuid4().hex[:8]
        agent.reply(f"请将这条虚构信息保存为长期事实记忆，key 使用 test_code：我的测试代号是 {marker}。")
        self.assertFalse(agent.last_memory_event.errors)
        items = [m for m in memory.list_active() if marker in m.quote]
        self.assertTrue(items)
        self.assertIn(items[0].id, agent.last_memory_event.written_ids)
        answer = agent.reply("请检索长期记忆，我的测试代号是什么？只回复代号。")
        self.assertIn(marker, answer)
        self.assertIn(items[0].id, agent.last_memory_event.retrieved_ids)
        # Explicitly target the actual slot to exercise model-driven revision.
        key = items[0].key
        new = marker + "-NEW"
        agent.reply(f"请更新长期记忆槽位 {key}，替换旧代号：我的测试代号是 {new}。")
        self.assertFalse(agent.last_memory_event.errors)
        active = [m for m in memory.list_active() if m.key == key]
        self.assertEqual(len(active), 1)
        self.assertIn(new, active[0].quote)
        self.assertIn(active[0].id, agent.last_memory_event.written_ids)
        self.assertGreaterEqual(memory.forget(key), 2)
        self.assertFalse(any(m.key == key for m in memory.list_active()))
