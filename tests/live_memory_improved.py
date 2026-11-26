"""Manual real-model explicit capability integration (synthetic data)."""
import os
import unittest
from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.memory_improved import ImprovedMemory
from becoming.models import OpenAICompatibleModel


class LiveImprovedMemory(unittest.TestCase):
    def test_supplement_keeps_independent_constraint(self):
        store = SQLiteConversationStore(":memory:")
        self.addCleanup(store.close)
        model = OpenAICompatibleModel(os.environ["BECOMING_BASE_URL"],os.environ["BECOMING_API_KEY"],os.environ["BECOMING_MODEL"])
        memory = ImprovedMemory(store,model)
        agent = Agent(model,store,history_turns=0,long_memory=memory)
        agent.reply("请记住：我不喜欢拥挤嘈杂的场所。")
        ids = agent.last_memory_event.written_ids
        self.assertTrue(ids)
        agent.reply("请补充记忆：我不是完全排斥社交，只是不喜欢很吵的环境。")
        self.assertTrue(agent.last_memory_event.written_ids)
        self.assertTrue(set(ids) <= {m.id for m in memory.list_active()})
        self.assertTrue(any("不是完全排斥社交" in m.quote for m in memory.list_active()))
