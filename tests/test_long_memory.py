import tempfile
import unittest
from pathlib import Path

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.long_memory import LongMemory, parse_candidates
from becoming.models import ModelError
import json


def candidate(key="职业", quote="我是木工", category="fact"):
    return json.dumps([{"key": key, "category": category, "quote": quote}], ensure_ascii=False)


class ScriptedModel:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def complete(self, messages):
        self.calls.append(list(messages))
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        return value


class LongMemoryTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)

    def test_end_to_end_recall_without_recent_history(self):
        model = ScriptedModel("收到", candidate(), "你是木工", "[]")
        memory = LongMemory(self.store, model)
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        agent.reply("请记住：我是木工")
        item, = memory.list_active()
        self.assertEqual(agent.last_memory_event.written_ids, (item.id,))
        self.assertEqual(item.source_turn_id, 1)
        self.assertEqual(agent.reply("我的职业是什么？"), "你是木工")
        self.assertIn("我是木工", model.calls[2][0]["content"])
        self.assertEqual(len(model.calls[2]), 2)
        self.assertEqual(agent.last_memory_event.retrieved_ids, (item.id,))
        self.assertEqual(len(memory.list_active()), 1)

    def test_update_duplicate_and_forget_all_versions(self):
        memory = LongMemory(self.store, ScriptedModel())
        t1 = self.store.append_turn("我是木工", "好")
        t2 = self.store.append_turn("我是工程师", "好")
        a, = memory.write(t1, [("职业", "fact", "我是木工")])
        self.assertEqual(memory.write(t1, [("职业", "fact", "我是木工")]), ())
        b, = memory.write(t2, [("职业", "fact", "我是工程师")])
        self.assertNotEqual(a, b)
        self.assertEqual([m.quote for m in memory.retrieve("职业")], ["我是工程师"])
        self.assertEqual(memory.forget("职业"), 2)
        self.assertEqual(memory.retrieve("职业"), [])
        self.assertEqual(len(self.store.recent()), 4)

    def test_irrelevant_not_injected(self):
        model = ScriptedModel("天气不确定", "[]")
        memory = LongMemory(self.store, model)
        t = self.store.append_turn("我是木工", "好")
        memory.write(t, [("职业", "fact", "我是木工")])
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        agent.reply("今天下雨吗？")
        self.assertNotIn("我是木工", model.calls[0][0]["content"])
        self.assertEqual(agent.last_memory_event.retrieved_ids, ())

    def test_validation_rejects_fabricated_or_bad_batch(self):
        for raw in ("not json", "{}", candidate(quote="我是医生"),
                    candidate(category="inference"), candidate(key="bad key")):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_candidates(raw, "我是木工")
        t = self.store.append_turn("我是木工", "好")
        memory = LongMemory(self.store, ScriptedModel())
        with self.assertRaises(ValueError):
            memory.write(t, [("职业", "fact", "我是木工"), ("城市", "fact", "北京")])
        self.assertEqual(memory.list_active(), [])
        with self.assertRaises(ValueError):
            memory.write(999, [("职业", "fact", "我是木工")])

    def test_extraction_failure_keeps_completed_reply(self):
        for error in (ModelError("quota"), "invalid JSON"):
            with self.subTest(error=error):
                model = ScriptedModel("收到", error)
                memory = LongMemory(self.store, model)
                agent = Agent(model, self.store, long_memory=memory)
                self.assertEqual(agent.reply("我是木工"), "收到")
                self.assertEqual(agent.last_memory_event.errors, ("extract_failed",))
                self.assertEqual(memory.list_active(), [])
        self.assertEqual(len(self.store.recent()), 4)

    def test_failed_reply_does_not_extract(self):
        model = ScriptedModel(ModelError("failed"))
        memory = LongMemory(self.store, model)
        with self.assertRaises(ModelError):
            Agent(model, self.store, long_memory=memory).reply("我是木工")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(self.store.recent(), [])
        self.assertEqual(memory.list_active(), [])

    def test_persistence_clear_even_without_memory_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            store = SQLiteConversationStore(path)
            memory = LongMemory(store, ScriptedModel())
            t = store.append_turn("我是木工", "好")
            memory.write(t, [("职业", "fact", "我是木工")])
            store.close()
            store = SQLiteConversationStore(path)
            self.assertEqual(len(LongMemory(store, ScriptedModel()).list_active()), 1)
            store.close()
            store = SQLiteConversationStore(path)
            store.clear()
            self.assertEqual(LongMemory(store, ScriptedModel()).list_active(), [])
            store.close()

    def test_memory_disabled_no_extra_calls(self):
        model = ScriptedModel("ok")
        Agent(model, self.store).reply("我是木工")
        self.assertEqual(len(model.calls), 1)

    def test_mismatched_store_and_limit(self):
        other = SQLiteConversationStore(":memory:")
        self.addCleanup(other.close)
        memory = LongMemory(other, ScriptedModel())
        with self.assertRaises(ValueError):
            Agent(ScriptedModel(), self.store, long_memory=memory)
        with self.assertRaises(ValueError):
            memory.retrieve("职业", 11)
