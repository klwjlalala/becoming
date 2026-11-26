import json
import unittest

from becoming.agent import Agent
from becoming.long_memory import LongMemory, complete_quote
from becoming.memory import SQLiteConversationStore
from becoming.memory_search import ComprehensiveMemory, SearchPlan
from test_long_memory import ScriptedModel


class MemorySafetyTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)

    def test_source_boundaries(self):
        for quote, source in [
            ("喜欢吵闹", "我不喜欢吵闹"),
            ("我想辞职", "如果经济有保障，我想辞职"),
            ("我喜欢游泳", "我喜欢游泳，但只在夏天"),
            ("我喜欢蹦极", "朋友说：我喜欢蹦极"),
            ("I like running", "If I had time, I like running"),
            ("我喜欢画画", "我喜欢画画很久了"),
            ("我喜欢跑步", "我喜欢跑步。假设我喜欢跑步"),
        ]:
            with self.subTest(quote=quote, source=source):
                self.assertFalse(complete_quote(quote, source))
        for quote, source in [
            ("我不喜欢吵闹", "我不喜欢吵闹，我喜欢木雕"),
            ("如果经济有保障，我想辞职", "如果经济有保障，我想辞职。"),
            ("我喜欢游泳，但只在夏天", "我喜欢游泳，但只在夏天。"),
            ("我是木工", "请记住：我是木工"),
        ]:
            self.assertTrue(complete_quote(quote, source))

    def test_legacy_bad_quote_not_retrieved_or_sent(self):
        memory = ComprehensiveMemory(self.store, ScriptedModel())
        turn = self.store.append_turn("我不喜欢吵闹，我喜欢木雕", "好")
        with self.store.connection:
            self.store.connection.execute("INSERT INTO long_memories(key,category,quote,source_turn_id) VALUES(?,?,?,?)",
                                          ("noise", "subjective", "喜欢吵闹", turn))
        good, = memory.write(turn, [("hobby", "subjective", "我喜欢木雕")])
        self.assertEqual([m.id for m in memory.list_active()], [good])
        self.assertEqual([m.id for m in memory.search(SearchPlan(("吵闹",), include_history=True))], [good])
        self.assertEqual(memory.forget("noise"), 1)

    def test_partial_extraction_reports_rejected_items(self):
        data = [
            {"key":"noise","category":"subjective","quote":"喜欢吵闹"},
            {"key":"hobby","category":"subjective","quote":"我喜欢木雕"},
            {"key":"other","category":"fact","quote":"编造的内容"},
        ]
        model = ScriptedModel("好", json.dumps(data))
        memory = LongMemory(self.store, model)
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        agent.reply("我不喜欢吵闹，我喜欢木雕")
        item, = memory.list_active()
        self.assertEqual(item.quote, "我喜欢木雕")
        self.assertEqual(agent.last_memory_event.written_ids, (item.id,))
        self.assertEqual(agent.last_memory_event.errors, ("extract_partial",))
        self.assertEqual(memory.last_extract_rejected, 2)

    def test_conflicting_revision_does_not_discard_independent_fact(self):
        model = ScriptedModel("好", json.dumps([
            {"key":"job","category":"fact","quote":"我是工程师"},
            {"key":"hobby","category":"subjective","quote":"我喜欢游泳"}
        ]))
        memory = LongMemory(self.store, model)
        turn = self.store.append_turn("我是木工", "好")
        old, = memory.write(turn, [("job", "fact", "我是木工")])
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        agent.reply("我是工程师，我喜欢游泳")
        self.assertEqual({m.quote for m in memory.list_active()}, {"我是木工", "我喜欢游泳"})
        self.assertNotIn(old, agent.last_memory_event.written_ids)
        self.assertEqual(agent.last_memory_event.errors, ("extract_partial",))

    def test_duplicate_keys_do_not_select_arbitrary_winner(self):
        data = [{"key":"same","category":"fact","quote":q} for q in ("甲信息", "乙信息")]
        model = ScriptedModel("好", json.dumps(data))
        memory = LongMemory(self.store, model)
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        agent.reply("甲信息，乙信息")
        self.assertEqual(memory.list_active(), [])
        self.assertEqual(agent.last_memory_event.errors, ("extract_failed",))

    def test_forgotten_sibling_not_injected_with_retained_quote(self):
        memory = LongMemory(self.store, ScriptedModel())
        turn = self.store.append_turn("我住在白石镇，我喜欢木雕", "好")
        memory.write(turn, [("town", "fact", "我住在白石镇"),
                            ("hobby", "subjective", "我喜欢木雕")])
        memory.forget("town")
        context = memory.context(memory.retrieve("木雕"))
        self.assertIn("我喜欢木雕", context)
        self.assertNotIn("白石镇", context)
