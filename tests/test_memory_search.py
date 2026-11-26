import json
import unittest
from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.memory_search import ComprehensiveMemory, SearchPlan
from becoming.models import ModelError
from test_long_memory import ScriptedModel


def plan(topics=("职业",), start=None, end=None, include_history=False):
    return json.dumps(dict(topics=topics, start=start, end=end, include_history=include_history),
                      ensure_ascii=False)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)
        self.memory = ComprehensiveMemory(self.store, ScriptedModel())

    def add(self, key, quote, day, replaces=None, category="fact"):
        turn = self.store.append_turn(quote, "收到")
        with self.store.connection:
            self.store.connection.execute("UPDATE turns SET created_at=? WHERE id=?",
                                          (day + " 12:00:00", turn))
        mid, = self.memory.write(turn, [(key, category, quote, replaces)])
        return mid

    def test_inclusive_dates_and_revision_scope(self):
        old = self.add("职业", "我是木工", "2024-01-01")
        new = self.add("职业", "现在我是工程师", "2025-01-01", old)
        self.assertEqual(self.memory.search(SearchPlan(("职业",), "2024-01-01", "2024-01-01")), [])
        item, = self.memory.search(SearchPlan(("职业",), "2024-01-01", "2024-01-01", True))
        self.assertEqual(item.id, old)
        self.assertFalse(item.active)
        self.assertEqual(item.recorded_at, "2024-01-01 12:00:00")
        self.assertEqual([m.id for m in self.memory.search(SearchPlan(("职业",)))], [new])
        self.assertEqual({m.id for m in self.memory.search(SearchPlan(("职业",), include_history=True))},
                         {old, new})

    def test_date_only_and_empty(self):
        mid = self.add("爱好", "我喜欢摄影", "2024-03-01")
        self.assertEqual(self.memory.search(SearchPlan(())), [])
        self.assertEqual(self.memory.search(SearchPlan((), "2024-03-02")), [])
        self.assertEqual([m.id for m in self.memory.search(SearchPlan((), end="2024-03-01"))], [mid])

    def test_multi_topic_pool_does_not_starve_older_topic(self):
        old = self.add("自由", "我希望自主支配时间", "2020-01-01")
        for i in range(45):
            self.add(f"工作{i}", f"工作项目{i}", "2025-01-01")
        pool = self.memory.search(SearchPlan(("工作", "自由")))
        self.assertEqual(len(pool), 40)
        self.assertIn(old, [m.id for m in pool])
        self.assertEqual(len({m.id for m in pool}), len(pool))

    def test_agent_combines_dated_evidence(self):
        old = self.add("职业", "我是木工", "2024-01-01")
        new = self.add("职业", "现在我是工程师", "2025-01-01", old)
        hobby = self.add("爱好", "我喜欢摄影", "2024-06-01")
        model = ScriptedModel(plan(("职业", "爱好"), "2024-01-01", "2025-01-01", True),
                              json.dumps([old, new, hobby]), "综合回答", "[]")
        memory = ComprehensiveMemory(self.store, model)
        agent = Agent(model, self.store, history_turns=0, long_memory=memory)
        self.assertEqual(agent.reply("回顾这两年的职业和爱好记录"), "综合回答")
        event = agent.last_memory_event
        self.assertEqual(event.retrieved_ids, (old, new, hobby))
        self.assertEqual(set(event.search["candidate_ids"]), {old, new, hobby})
        self.assertEqual(event.search["plan"]["start"], "2024-01-01")
        context = model.calls[2][0]["content"]
        self.assertIn('"active": false', context)
        self.assertIn("2024-01-01 12:00:00", context)
        self.assertIn("我喜欢摄影", context)

    def test_invalid_plan_and_out_of_scope_selection_fail_closed(self):
        self.add("职业", "我是木工", "2024-01-01")
        other = self.add("爱好", "我喜欢摄影", "2025-01-01")
        for responses in [
            ("{}",), (plan(start="2025-01-01", end="2024-01-01"),),
            (plan(start="2024-01-01", end="2024-12-31"), json.dumps([other])),
            (ModelError("quota"),)
        ]:
            with self.subTest(responses=responses):
                model = ScriptedModel(*responses, "正常回复", "[]")
                agent = Agent(model, self.store, history_turns=0,
                              long_memory=ComprehensiveMemory(self.store, model))
                self.assertEqual(agent.reply("回顾职业"), "正常回复")
                self.assertEqual(agent.last_memory_event.errors, ("retrieve_failed",))
                self.assertEqual(agent.last_memory_event.retrieved_ids, ())
                self.assertNotIn("我是木工", model.calls[-2][0]["content"])

    def test_no_memory_or_no_intent_or_forgotten(self):
        self.assertEqual(self.memory.retrieve("问题"), [])
        self.add("职业", "我是木工", "2024-01-01")
        model = ScriptedModel(plan(()))
        memory = ComprehensiveMemory(self.store, model)
        self.assertEqual(memory.retrieve("冰箱原理"), [])
        self.assertEqual(len(model.calls), 1)
        memory.forget("职业")
        self.assertEqual(memory.search(SearchPlan(("职业",), include_history=True)), [])
        self.assertEqual(memory.retrieve("职业"), [])

    def test_plan_validation(self):
        for raw in (plan(start="20240101"), plan(start="2024-02-30"),
                    plan(topics=["a"] * 5), plan(include_history=1), plan(topics=[""])):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                SearchPlan.parse(raw)
        with self.assertRaises(ValueError):
            self.memory.search(SearchPlan(("职业",)), 41)

    def test_evaluation_fixtures_seed_without_model_calls(self):
        from evaluation.cross_time import CASES, seed
        for case in CASES.values():
            store = SQLiteConversationStore(":memory:")
            try:
                memory = ComprehensiveMemory(store, ScriptedModel())
                seed(store, memory, case)
                self.assertEqual(store.connection.execute("SELECT count(*) FROM long_memories").fetchone()[0],
                                 len(case["records"]))
            finally:
                store.close()
