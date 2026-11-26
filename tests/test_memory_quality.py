import json
import unittest
from becoming.long_memory import LongMemory, MAX_ITEMS
from becoming.memory_search import ComprehensiveMemory, SearchPlan
from evaluation.memory_quality import DatedStore, all_records, audit, probe_audit, run_case
from evaluation.quality_cases import CASES, Case, Evidence, Turn, validate_cases
from test_long_memory import ScriptedModel


class QualityDiagnosticsTests(unittest.TestCase):
    def test_case_contracts_and_stress_size(self):
        self.assertEqual(len(validate_cases()), 3)
        self.assertGreater(len(CASES["quality-003"].history), 40)
        self.assertGreater(len(CASES["quality-003"].history[0].evidence), 3)
        self.assertLessEqual(len(CASES["quality-003"].history[0].evidence), MAX_ITEMS)

    def test_audit_distinguishes_missing_span_wrong_state_and_noise(self):
        case = Case("test", (
            Turn("2024-01-01", "我不喜欢吵闹，我喜欢木雕", (
                Evidence("negative", "我不喜欢吵闹"), Evidence("hobby", "我喜欢木雕"))),
            Turn("2024-02-01", "今天下雨", no_write=True),
        ), "2025-01-01", "我的喜好？", ("negative", "hobby"), ())
        store = DatedStore(":memory:")
        self.addCleanup(store.close)
        memory = LongMemory(store, ScriptedModel())
        store.day = "2024-01-01"
        t1 = store.append_turn(case.history[0].text, "好")
        # Literal substring validity does not preserve polarity.
        # Simulate pre-upgrade database corruption; current writes reject this.
        with store.connection:
            store.connection.execute("INSERT INTO long_memories(key,category,quote,source_turn_id) VALUES(?,?,?,?)",
                                     ("noise", "subjective", "喜欢吵闹", t1))
        memory.write(t1, [("hobby", "subjective", "我喜欢木雕")])
        store.connection.execute("UPDATE long_memories SET active=0 WHERE key='hobby'")
        store.day = "2024-02-01"
        t2 = store.append_turn("今天下雨", "好")
        memory.write(t2, [("weather", "fact", "今天下雨")])
        results, noise = audit(case, [{"turn_id": t1}, {"turn_id": t2}], all_records(store))
        self.assertEqual(results["negative"]["matched_ids"], [])
        self.assertEqual(results["hobby"]["state_check"], "mismatch")
        self.assertEqual(noise[0]["turn_id"], t2)

    def test_pipeline_traces_and_isolated_comparison(self):
        case = Case("test", (Turn("2024-01-01", "我喜欢木雕",
                                  (Evidence("hobby", "我喜欢木雕"),)),),
                    "2025-01-01", "假日做什么？", ("hobby",), ("manual only",))
        extract = json.dumps([{"key":"hobby","category":"subjective","quote":"我喜欢木雕"}])
        search = json.dumps({"topics":["木雕"],"start":None,"end":None,"include_history":False})
        model = ScriptedModel("历史回复", extract, "普通回复", "[1]", "旧版回复", "[]",
                              search, "[1]", "新版回复", "[]")
        report = run_case(case, model)
        self.assertEqual(report["model_calls"], 10)
        self.assertEqual(report["exact_span_matched"], 1)
        self.assertEqual(report["records"][0]["recorded_at_utc"], "2024-01-01 12:00:00")
        self.assertEqual(report["probes"]["v1.3"]["diagnostics"]["hobby"], "selected")
        self.assertEqual(report["probes"]["v1.1"]["diagnostics"]["hobby"], "selected")
        self.assertEqual(report["probes"]["no-memory"]["event"]["retrieved_ids"], ())
        self.assertEqual(report["verdict"], "awaiting_manual_review")
        for call in model.calls:
            self.assertNotIn("manual only", str(call))
        self.assertEqual(len(report["records"]), 1)

    def test_temporal_reserve_recalls_old_zero_overlap_candidate(self):
        # Regression for the previously excluded oldest record.
        store = DatedStore(":memory:")
        self.addCleanup(store.close)
        memory = ComprehensiveMemory(store, ScriptedModel())
        store.day = "2023-01-01"
        turn = store.append_turn("我无法承担失去收入的风险", "好")
        old, = memory.write(turn, [("收入", "subjective", "我无法承担失去收入的风险")])
        store.day = "2024-01-01"
        for i in range(45):
            quote = f"收藏编号{i}"
            turn = store.append_turn(quote, "好")
            memory.write(turn, [(f"book{i}", "fact", quote)])
        pool = memory.search(SearchPlan(("财务稳定",)))
        self.assertEqual(len(pool), 40)
        self.assertIn(old, [m.id for m in pool])
        self.assertIn(old, [m.id for m in memory.search(SearchPlan(("收入",)))])

    def test_dense_batch_preserves_five_independent_evidence_items(self):
        store = DatedStore(":memory:")
        self.addCleanup(store.close)
        memory = LongMemory(store, ScriptedModel())
        quotes = ["甲信息", "乙信息", "丙信息", "丁信息", "戊信息"]
        turn = store.append_turn("，".join(quotes), "好")
        ids = memory.write(turn, [(f"slot{i}", "fact", x) for i, x in enumerate(quotes)])
        self.assertEqual(len(ids), 5)
        self.assertEqual({m.quote for m in memory.list_active()}, set(quotes))
        with self.assertRaises(ValueError):
            memory.write(turn, [("slot", "fact", quotes[0])] * (MAX_ITEMS + 1))
        self.assertEqual(len(memory.list_active()), 5)
