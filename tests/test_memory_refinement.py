import json
import tempfile
import unittest
from pathlib import Path

from becoming.agent import Agent
from becoming.long_memory import LongMemory
from becoming.memory import SQLiteConversationStore
from becoming.models import ModelError
from test_long_memory import ScriptedModel, candidate


class MemoryRefinementTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)

    def add(self, memory, key="职业", category="fact", quote="我是木工"):
        turn = self.store.append_turn(quote, "收到")
        mid, = memory.write(turn, [(key, category, quote)])
        return mid

    def test_collision_and_stale_revision_are_rejected_atomically(self):
        memory = LongMemory(self.store, ScriptedModel())
        old = self.add(memory)
        turn = self.store.append_turn("我是工程师，我喜欢游泳", "收到")
        for replacement in (None, old + 1):
            with self.assertRaises(ValueError):
                memory.write(turn, [("运动", "subjective", "我喜欢游泳", None),
                                    ("职业", "fact", "我是工程师", replacement)])
            self.assertEqual([m.id for m in memory.list_active()], [old])
        new, = memory.write(turn, [("职业", "fact", "我是工程师", old)])
        self.assertNotEqual(old, new)
        with self.assertRaises(ValueError):
            memory.write(turn, [("职业", "fact", "我是木工", old)])

    def test_model_revision_uses_old_evidence(self):
        model = ScriptedModel("ok", json.dumps([{"key":"职业","category":"fact",
                              "quote":"我现在是工程师","replaces":1}], ensure_ascii=False))
        memory = LongMemory(self.store, model)
        old = self.add(memory)
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        agent.reply("我现在是工程师")
        item, = memory.list_active()
        self.assertNotEqual(item.id, old)
        hints = json.loads(model.calls[-1][1]["content"])["existing_slots"]
        self.assertEqual(hints[0]["id"], old)
        self.assertEqual(hints[0]["quote"], "我是木工")
        self.assertEqual(agent.last_memory_event.written_ids, (item.id,))

    def test_exact_duplicate_across_slots(self):
        memory = LongMemory(self.store, ScriptedModel())
        self.add(memory)
        turn = self.store.append_turn("我是木工", "好")
        self.assertEqual(memory.write(turn, [("工作", "fact", "我是木工")]), ())
        self.assertEqual(len(memory.list_active()), 1)

    def test_block_persists_and_allow_does_not_restore(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.sqlite3"
            store = SQLiteConversationStore(path)
            memory = LongMemory(store, ScriptedModel())
            turn = store.append_turn("我是木工", "好")
            memory.write(turn, [("职业", "fact", "我是木工")])
            self.assertEqual(memory.forget("职业"), 1)
            store.close()
            store = SQLiteConversationStore(path)
            try:
                memory = LongMemory(store, ScriptedModel())
                self.assertEqual(memory.blocked_keys(), ["职业"])
                self.assertEqual(memory.write(turn, [("职业", "fact", "我是木工")]), ())
                self.assertEqual(memory.list_active(), [])
                self.assertTrue(memory.allow("职业"))
                self.assertEqual(memory.list_active(), [])
                self.assertFalse(memory.allow("职业"))
                self.assertTrue(memory.write(turn, [("职业", "fact", "我是木工")]))
            finally:
                store.close()

    def test_blocked_model_write_is_not_recreated(self):
        model = ScriptedModel("好", candidate())
        memory = LongMemory(self.store, model)
        memory.forget("职业")
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        agent.reply("我是木工")
        self.assertEqual(agent.last_memory_event.written_ids, ())
        self.assertEqual(memory.list_active(), [])
        self.assertIn("职业", json.loads(model.calls[-1][1]["content"])["blocked_keys"])

    def test_obvious_credential_skips_extraction_and_direct_write(self):
        model = ScriptedModel("请勿分享密钥")
        memory = LongMemory(self.store, model)
        agent = Agent(model, self.store, long_memory=memory)
        agent.reply("我的 API key: synthetic-secret")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(memory.write(1, [("信息", "fact", "synthetic-secret")]), ())
        self.assertEqual(memory.list_active(), [])

    def test_semantic_recall_without_word_overlap(self):
        model = ScriptedModel("[1]", "可以去山里走走", "[]")
        memory = LongMemory(self.store, model, semantic=True)
        mid = self.add(memory, "爱好", "subjective", "我喜欢徒步")
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        self.assertEqual(agent.reply("放假怎么安排？"), "可以去山里走走")
        self.assertIn("我喜欢徒步", model.calls[1][0]["content"])
        self.assertEqual(agent.last_memory_event.retrieved_ids, (mid,))
        self.assertEqual(len(model.calls), 3)

    def test_semantic_empty_selection_no_injection(self):
        model = ScriptedModel("[]", "回答", "[]")
        memory = LongMemory(self.store, model, semantic=True)
        self.add(memory)
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        agent.reply("工作原理是什么？")
        self.assertNotIn("我是木工", model.calls[1][0]["content"])
        self.assertEqual(agent.last_memory_event.retrieved_ids, ())

    def test_invalid_semantic_selection_fails_closed(self):
        for invalid in ("[999]", "[true]", "[1,1]", "{}", ModelError("network")):
            with self.subTest(invalid=invalid):
                model = ScriptedModel(invalid, "回答", "[]")
                memory = LongMemory(self.store, model, semantic=True)
                if not memory.list_active():
                    self.add(memory)
                agent = Agent(model, self.store, history_turns=0, long_memory=memory)
                self.assertEqual(agent.reply("我的职业是什么？"), "回答")
                self.assertEqual(agent.last_memory_event.errors, ("retrieve_failed",))
                self.assertEqual(agent.last_memory_event.retrieved_ids, ())
                self.assertNotIn("我是木工", model.calls[1][0]["content"])

    def test_category_alone_does_not_recall(self):
        memory = LongMemory(self.store, ScriptedModel())
        self.add(memory)
        self.assertEqual(memory.retrieve("工作原理是什么？"), [])

    def test_semantic_pool_bounded(self):
        model = ScriptedModel("[]")
        memory = LongMemory(self.store, model, semantic=True)
        for i in range(45):
            self.add(memory, f"槽位{i}", "fact", f"独立数据{i}")
        self.assertEqual(memory.retrieve("无关问题"), [])
        self.assertEqual(len(json.loads(model.calls[0][1]["content"])["candidates"]), 40)
