"""Manual explicit real-model retrieval integration, synthetic dated evidence."""
import os
import unittest
from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.memory_search import ComprehensiveMemory
from becoming.models import OpenAICompatibleModel


class LiveMemorySearch(unittest.TestCase):
    def test_explicit_dated_multi_topic_retrieval(self):
        store = SQLiteConversationStore(":memory:")
        self.addCleanup(store.close)
        model = OpenAICompatibleModel(os.environ["BECOMING_BASE_URL"],
                                      os.environ["BECOMING_API_KEY"], os.environ["BECOMING_MODEL"])
        memory = ComprehensiveMemory(store, model)
        ids = []
        for key, quote, day in [("职业", "我在青桐工坊修理钟表。", "2024-01-10"),
                                ("爱好", "我喜欢制作纸质星图。", "2024-08-15"),
                                ("住处", "我住在白石镇。", "2025-03-01")]:
            turn = store.append_turn(quote, "收到")
            with store.connection:
                store.connection.execute("UPDATE turns SET created_at=? WHERE id=?", (day, turn))
            mid, = memory.write(turn, [(key, "fact", quote)])
            ids.append(mid)
        agent = Agent(model, store, history_turns=0, long_memory=memory)
        answer = agent.reply("请检索2024-01-01至2024-12-31 UTC 的长期记忆记录，综合职业和爱好两主题，复述具体内容。")
        event = agent.last_memory_event
        self.assertFalse(event.errors)
        self.assertEqual(set(event.retrieved_ids), set(ids[:2]))
        self.assertNotIn(ids[2], event.search["candidate_ids"])
        self.assertEqual(event.search["plan"]["start"], "2024-01-01")
        self.assertEqual(event.search["plan"]["end"], "2024-12-31")
        self.assertIn("钟表", answer)
        self.assertIn("星图", answer)
