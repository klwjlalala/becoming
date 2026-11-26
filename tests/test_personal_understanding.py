import json
import unittest

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.personal_understanding import PersonalUnderstanding, parse_proposal
from becoming.models import ModelError


class ScriptedModel:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, messages):
        self.calls.append([dict(message) for message in messages])
        if not self.outputs:
            raise AssertionError("unexpected model call")
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def create_proposal(quote="我更在意能自己安排时间。", assistant="明白。", **overrides):
    operation = {
        "operation": "CREATE", "claim_ref": "c1", "claim_id": None,
        "expected_version": None, "content": "用户重视自主安排时间。",
        "dimension": "values", "basis": "explicit_statement", "scope": {},
        "temporal_scope": "ongoing",
        "evidence": [{"ref": "e1", "relation": "support"}],
        "reason": "用户直接表达了稳定偏好。",
    }
    operation.update(overrides)
    return json.dumps({
        "evidence": [{
            "ref": "e1", "turn_index": 0, "quote": quote,
            "kind": "direct_statement", "event_time": None,
        }],
        "operations": [operation],
        "confirmation": None,
    }, ensure_ascii=False)


def reinforce_proposal(claim_id, quote, version=1, operation="REINFORCE", relation="support"):
    return json.dumps({
        "evidence": [{
            "ref": "e1", "turn_index": 0, "quote": quote,
            "kind": "correction" if operation == "REJECT" else "direct_statement",
            "event_time": None,
        }],
        "operations": [{
            "operation": operation, "claim_ref": None, "claim_id": claim_id,
            "expected_version": version, "content": "用户重视自主安排时间。",
            "dimension": "values", "basis": "explicit_statement", "scope": {},
            "temporal_scope": "ongoing",
            "evidence": [{"ref": "e1", "relation": relation}],
            "reason": "新增证据使当前理解需要更新。",
        }],
        "confirmation": None,
    }, ensure_ascii=False)


class PersonalUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)

    def make_engine(self, *responses):
        model = ScriptedModel(*responses)
        engine = PersonalUnderstanding(self.store, model)
        return engine, model

    def add_turn(self, engine, user, assistant="明白。"):
        turn_id = self.store.append_turn(user, assistant)
        return turn_id, engine.observe_turn(turn_id, user, assistant)

    def create_claim(self, engine, model, quote="我更在意能自己安排时间。"):
        turn_id = self.store.append_turn(quote, "明白。")
        engine._enqueue(turn_id, "normal")
        event = engine.process_pending()
        self.assertFalse(event.errors)
        claims = engine.list_claims()
        self.assertEqual(len(claims), 1)
        return claims[0]

    def test_create_claim_keeps_exact_source_and_revision(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        self.assertEqual(claim.content, "用户重视自主安排时间。")
        self.assertEqual(claim.version, 1)
        self.assertEqual(claim.support_level, "low")
        history = engine.get_claim_history(claim.id)
        self.assertEqual(history[0]["evidence"][0]["quote"], "我更在意能自己安排时间。")
        self.assertEqual(engine.list_revisions(claim.id)[0]["operation"], "CREATE")
        self.assertEqual(len(model.calls), 1)

    def test_reinforce_adds_independent_evidence_and_increases_support(self):
        first = create_proposal()
        engine, model = self.make_engine(first)
        claim = self.create_claim(engine, model)
        model.outputs.append(reinforce_proposal(
            claim.id, "如果必须选，我还是更看重自主安排时间。"
        ))
        turn_id = self.store.append_turn(
            "如果必须选，我还是更看重自主安排时间。", "理解。"
        )
        engine._enqueue(turn_id, "normal")
        event = engine.process_pending()
        updated, = engine.list_claims()
        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.support_level, "medium")
        self.assertEqual(len(engine.get_claim_history(claim.id)), 2)
        self.assertEqual(engine.list_revisions(claim.id)[-1]["operation"], "REINFORCE")
        self.assertEqual(event.written_claim_ids, (claim.id,))

    def test_refine_versions_claim_without_overwriting_history(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        model.outputs.append(json.dumps({
            "evidence": [{
                "ref": "e1", "turn_index": 0,
                "quote": "和能聊到一块的人交流会让我很有精神。",
                "kind": "self_interpretation", "event_time": None,
            }],
            "operations": [{
                "operation": "REFINE", "claim_ref": None, "claim_id": claim.id,
                "expected_version": 1,
                "content": "用户并非排斥所有社交；共同兴趣和深入交流可能使其感到愉快。",
                "dimension": "patterns", "basis": "self_interpretation",
                "scope": {"social_context": "共同兴趣、深入交流"},
                "temporal_scope": "ongoing",
                "evidence": [{"ref": "e1", "relation": "qualifies"}],
                "reason": "新证据为早期笼统表述增加情境限定。",
            }],
            "confirmation": None,
        }, ensure_ascii=False))
        quote = "和能聊到一块的人交流会让我很有精神。"
        turn_id = self.store.append_turn(quote, "明白。")
        engine._enqueue(turn_id, "normal")
        engine.process_pending()
        history = engine.get_claim_history(claim.id)
        self.assertEqual([x["status"] for x in history], ["superseded", "active"])
        self.assertEqual(history[0]["content"], "用户重视自主安排时间。")
        self.assertIn("共同兴趣", history[1]["content"])

    def test_dispute_retains_both_support_and_counter_evidence(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        model.outputs.append(reinforce_proposal(
            claim.id, "在大型酒会上我还是会觉得社交很消耗。",
            operation="DISPUTE", relation="counter",
        ))
        quote = "在大型酒会上我还是会觉得社交很消耗。"
        turn_id = self.store.append_turn(quote, "这可能是场景差异。")
        engine._enqueue(turn_id, "normal")
        engine.process_pending()
        updated, = engine.list_claims()
        self.assertEqual(updated.status, "disputed")
        evidence = engine.get_claim_history(claim.id)[-1]["evidence"]
        self.assertIn("support", {x["relation"] for x in evidence})
        self.assertIn("counter", {x["relation"] for x in evidence})
        self.assertEqual(updated.support_level, "low")

    def test_explicit_rejection_removes_claim_from_current_retrieval(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        model.outputs.append(reinforce_proposal(
            claim.id, "你理解错了，我并不把创业当成我的人生目标。",
            operation="REJECT", relation="counter",
        ))
        quote = "你理解错了，我并不把创业当成我的人生目标。"
        turn_id = self.store.append_turn(quote, "我会修正。")
        engine._enqueue(turn_id, "immediate")
        event = engine.process_pending()
        self.assertFalse(event.errors)
        self.assertEqual(engine.list_claims(), [])
        history = engine.get_claim_history(claim.id)
        self.assertEqual(history[-1]["status"], "rejected")
        self.assertEqual(engine.list_revisions(claim.id)[-1]["operation"], "REJECT")

    def test_fabricated_quote_or_claim_id_fails_closed(self):
        for raw in (
            create_proposal(quote="我是一名医生。"),
            json.dumps({
                "evidence": [{"ref":"e1","turn_index":0,"quote":"我更在意能自己安排时间。",
                              "kind":"direct_statement","event_time":None}],
                "operations": [{
                    "operation":"REINFORCE","claim_ref":None,"claim_id":"invented",
                    "expected_version":1,"content":"不存在","dimension":"values",
                    "basis":"explicit_statement","scope":{},"temporal_scope":"ongoing",
                    "evidence":[{"ref":"e1","relation":"support"}],"reason":"invalid",
                }],
                "confirmation":None,
            }, ensure_ascii=False),
        ):
            engine, model = self.make_engine(raw)
            turn_id = self.store.append_turn("我更在意能自己安排时间。", "明白。")
            engine._enqueue(turn_id, "normal")
            event = engine.process_pending()
            self.assertEqual(event.errors, ("update_failed",))
            self.assertEqual(engine.list_claims(), [])
            self.assertEqual(self.store.connection.execute(
                "SELECT COUNT(*) FROM understanding_evidence").fetchone()[0], 0)

    def test_confirmation_only_when_question_was_actually_asked(self):
        raw = json.loads(create_proposal())
        raw["confirmation"] = {
            "claim_id": None, "claim_ref": "c1", "expected_version": 1,
            "turn_index": 0, "question": "你觉得这个理解准确吗？",
        }
        engine, model = self.make_engine(json.dumps(raw, ensure_ascii=False))
        turn_id = self.store.append_turn(
            "更正一下：我更在意能自己安排时间。",
            "我猜这对你很重要。你觉得这个理解准确吗？",
        )
        engine._enqueue(turn_id, "immediate")
        event = engine.process_pending()
        self.assertFalse(event.errors)
        pending, = engine.pending_confirmations()
        self.assertEqual(pending["question"], "你觉得这个理解准确吗？")

        answer_turn = self.store.append_turn("是的", "好的。")
        confirmed = engine.resolve_pending_confirmation("是的", answer_turn)
        self.assertEqual(confirmed, (pending["claim_id"],))
        claim, = engine.list_claims()
        self.assertEqual(claim.user_validation, "confirmed")
        self.assertEqual(claim.version, 2)
        self.assertEqual(engine.list_revisions(claim.id)[-1]["operation"], "CONFIRM")
        self.assertEqual(engine.pending_confirmations(), [])

    def test_fabricated_confirmation_question_rejects_batch(self):
        raw = json.loads(create_proposal())
        raw["confirmation"] = {
            "claim_id": None, "claim_ref": "c1", "expected_version": 1,
            "turn_index": 0, "question": "你确定吗？",
        }
        engine, model = self.make_engine(json.dumps(raw, ensure_ascii=False))
        turn_id = self.store.append_turn("我更在意能自己安排时间。", "收到。")
        engine._enqueue(turn_id, "normal")
        event = engine.process_pending()
        self.assertEqual(event.errors, ("update_failed",))
        self.assertEqual(engine.list_claims(), [])

    def test_ambiguous_confirmation_expires_without_guessing(self):
        raw = json.loads(create_proposal())
        raw["confirmation"] = {
            "claim_id": None, "claim_ref": "c1", "expected_version": 1,
            "turn_index": 0, "question": "你觉得这个理解准确吗？",
        }
        engine, model = self.make_engine(json.dumps(raw, ensure_ascii=False))
        turn_id = self.store.append_turn(
            "更正一下：我更在意能自己安排时间。",
            "你觉得这个理解准确吗？",
        )
        engine._enqueue(turn_id, "immediate")
        engine.process_pending()
        self.store.append_turn("顺便问一下，Python 生成器是什么？", "解释。")
        engine.resolve_pending_confirmation("顺便问一下，Python 生成器是什么？", 2)
        status = self.store.connection.execute(
            "SELECT status FROM understanding_pending_confirmations").fetchone()[0]
        self.assertEqual(status, "expired")
        claim, = engine.list_claims()
        self.assertEqual(claim.user_validation, "unconfirmed")

    def test_reflective_retrieval_and_irrelevant_query_filter(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        selected = engine.retrieve("结合之前聊过的内容，我真正想要什么样的生活？")
        self.assertEqual([item.id for item in selected], [claim.id])
        self.assertIn("自主安排时间", engine.context(selected))
        self.assertEqual(engine.retrieve("Python 生成器和迭代器有什么区别？"), [])
        self.assertEqual(engine.last_search["selected_ids"], [])

    def test_five_normal_turns_are_processed_in_one_batch(self):
        raw = create_proposal()
        engine, model = self.make_engine(raw)
        for i in range(5):
            user = f"第{i+1}轮：我更在意能自己安排时间。"
            quote = "我更在意能自己安排时间。"
            turn_id = self.store.append_turn(user, "收到。")
            engine.observe_turn(turn_id, user, "收到。")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(engine.list_claims()), 1)
        self.assertEqual(self.store.connection.execute(
            "SELECT COUNT(*) FROM understanding_jobs WHERE status='done'").fetchone()[0], 5)

    def test_failed_jobs_have_finite_retries(self):
        engine, model = self.make_engine("not json", "still not json", "also invalid")
        turn_id = self.store.append_turn("我更在意能自己安排时间。", "收到。")
        engine._enqueue(turn_id, "normal")
        self.assertEqual(engine.process_pending().errors, ("update_failed",))
        result = engine.flush()
        self.assertEqual(result.errors, ("update_failed", "update_failed"))
        attempts, status = self.store.connection.execute(
            "SELECT attempts,status FROM understanding_jobs").fetchone()
        self.assertEqual(attempts, 3)
        self.assertEqual(status, "failed")

    def test_clear_cascades_evidence_claims_jobs_and_confirmations(self):
        raw = json.loads(create_proposal())
        raw["confirmation"] = {
            "claim_id": None, "claim_ref": "c1", "expected_version": 1,
            "turn_index": 0, "question": "你觉得这个理解准确吗？",
        }
        engine, model = self.make_engine(json.dumps(raw, ensure_ascii=False))
        turn_id = self.store.append_turn(
            "更正一下：我更在意能自己安排时间。",
            "你觉得这个理解准确吗？",
        )
        engine._enqueue(turn_id, "immediate")
        engine.process_pending()
        self.assertTrue(engine.list_claims())
        self.store.clear()
        for table in (
            "understanding_evidence", "understanding_claims", "understanding_claim_versions",
            "understanding_revisions", "understanding_pending_confirmations", "understanding_jobs",
        ):
            self.assertEqual(self.store.connection.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

    def test_agent_optional_integration_and_disabled_path(self):
        plain_model = ScriptedModel("普通回复。")
        Agent(plain_model, self.store).reply("你好")
        self.assertEqual(len(plain_model.calls), 1)

        model = ScriptedModel("我会修正这个理解。", create_proposal(
            quote="我更在意能自己安排时间。"
        ))
        engine = PersonalUnderstanding(self.store, model)
        agent = Agent(model, self.store, personal_understanding=engine)
        agent.reply("更正一下：我更在意能自己安排时间。")
        self.assertTrue(agent.last_understanding_event.written_claim_ids)
        self.assertEqual(len(engine.list_claims()), 1)

    def test_agent_retrieval_injects_claims_without_extra_model_call(self):
        create_model = ScriptedModel(create_proposal())
        engine = PersonalUnderstanding(self.store, create_model)
        claim = self.create_claim(engine, create_model)
        model = ScriptedModel("我记得你更看重自主安排时间。")
        agent = Agent(model, self.store, history_turns=0, personal_understanding=engine)
        agent.reply("结合之前聊过的内容，我真正想要什么？")
        self.assertEqual(len(model.calls), 1)
        self.assertIn(claim.content, model.calls[0][0]["content"])
        self.assertEqual(agent.last_understanding_event.retrieved_claim_ids, (claim.id,))

    def test_store_mismatch_and_invalid_limits(self):
        other = SQLiteConversationStore(":memory:")
        self.addCleanup(other.close)
        engine = PersonalUnderstanding(other, ScriptedModel())
        with self.assertRaises(ValueError):
            Agent(ScriptedModel(), self.store, personal_understanding=engine)
        with self.assertRaises(ValueError):
            engine.retrieve("test", 6)
        with self.assertRaises(ValueError):
            engine.process_pending(limit=6)


if __name__ == "__main__":
    unittest.main()
