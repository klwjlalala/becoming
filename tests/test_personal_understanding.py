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


def reinforce_proposal(claim_id, quote, version=1, operation="REINFORCE", relation="support",
                       content="用户重视自主安排时间。", dimension="values"):
    return json.dumps({
        "evidence": [{
            "ref": "e1", "turn_index": 0, "quote": quote,
            "kind": "correction" if operation == "REJECT" else "direct_statement",
            "event_time": None,
        }],
        "operations": [{
            "operation": operation, "claim_ref": None, "claim_id": claim_id,
            "expected_version": version, "content": content,
            "dimension": dimension, "basis": "explicit_statement", "scope": {},
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

    def test_refine_can_retain_selected_prior_evidence(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        original_evidence_id = engine.get_claim_history(claim.id)[0]["evidence"][0]["id"]
        new_quote = "和能聊到一块的人交流会让我很有精神。"
        model.outputs.append(json.dumps({
            "evidence": [{
                "ref": "e1", "turn_index": 0, "quote": new_quote,
                "kind": "self_interpretation", "event_time": None,
            }],
            "operations": [{
                "operation": "REFINE", "claim_ref": None, "claim_id": claim.id,
                "expected_version": 1,
                "content": "用户重视自主安排时间，也喜欢与有共同兴趣的人深入交流。",
                "dimension": "patterns", "basis": "self_interpretation",
                "scope": {"context": "工作选择与社交"},
                "temporal_scope": "ongoing",
                "evidence": [{"ref": "e1", "relation": "qualifies"}],
                "prior_evidence": [{
                    "evidence_id": original_evidence_id, "relation": "qualifies"
                }],
                "reason": "保留仍然适用的旧证据，并加入新的情境限定。",
            }],
            "confirmation": None,
        }, ensure_ascii=False))
        turn_id = self.store.append_turn(new_quote, "明白。")
        engine._enqueue(turn_id, "normal")
        event = engine.process_pending()
        self.assertFalse(event.errors)
        history = engine.get_claim_history(claim.id)
        current_evidence = history[-1]["evidence"]
        self.assertEqual(
            {item["quote"] for item in current_evidence},
            {"我更在意能自己安排时间。", new_quote},
        )
        self.assertEqual({item["relation"] for item in current_evidence}, {"qualifies"})

    def test_prior_evidence_reference_must_belong_to_target_claim(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        quote = "和能聊到一块的人交流会让我很有精神。"
        model.outputs.append(json.dumps({
            "evidence": [{
                "ref": "e1", "turn_index": 0, "quote": quote,
                "kind": "self_interpretation", "event_time": None,
            }],
            "operations": [{
                "operation": "REFINE", "claim_ref": None, "claim_id": claim.id,
                "expected_version": 1,
                "content": "用户重视自主安排时间，也喜欢与有共同兴趣的人深入交流。",
                "dimension": "patterns", "basis": "self_interpretation",
                "scope": {}, "temporal_scope": "ongoing",
                "evidence": [{"ref": "e1", "relation": "qualifies"}],
                "prior_evidence": [{"evidence_id": 999999, "relation": "support"}],
                "reason": "invalid evidence reference",
            }],
            "confirmation": None,
        }, ensure_ascii=False))
        turn_id = self.store.append_turn(quote, "明白。")
        engine._enqueue(turn_id, "normal")
        event = engine.process_pending()
        self.assertEqual(event.errors, ("update_failed",))
        self.assertEqual(engine.list_claims()[0].version, 1)
        self.assertEqual(len(engine.get_claim_history(claim.id)), 1)

    def test_high_support_claim_does_not_match_unrelated_query(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE understanding_claim_versions SET support_level='high' WHERE id=?",
                (claim.version_id,),
            )
        result = engine.retrieve("顺便问一下，Python 的生成器和迭代器有什么区别？")
        self.assertEqual(result, [])
        self.assertEqual(engine.last_search["selected_ids"], [])

    def test_meaning_query_prioritizes_event_level_experience(self):
        mountain_quote = "上个月我一个人爬到山顶，看着下面城市里的人来来往往，突然很感动。"
        mountain_proposal = json.dumps({
            "evidence": [{
                "ref": "e1", "turn_index": 0, "quote": mountain_quote,
                "kind": "experience", "event_time": "上个月",
            }],
            "operations": [{
                "operation": "CREATE", "claim_ref": "c1", "claim_id": None,
                "expected_version": None,
                "content": "用户曾在山顶观察城市人流时感到强烈感动。",
                "dimension": "values", "basis": "explicit_statement",
                "scope": {"context": "独自登山并观看城市"},
                "temporal_scope": "一次个人经历；具体日期以来源记录为准",
                "evidence": [{"ref": "e1", "relation": "support"}],
                "reason": "保留具有情感意义的事件级经历，不推断稳定人格。",
            }],
            "confirmation": None,
        }, ensure_ascii=False)
        engine, model = self.make_engine(mountain_proposal, create_proposal())
        mountain_turn = self.store.append_turn(mountain_quote, "那一刻很特别。")
        engine._enqueue(mountain_turn, "normal")
        engine.process_pending()
        mountain_claim = next(
            claim for claim in engine.list_claims() if "山顶" in claim.content
        )

        generic_turn = self.store.append_turn("我更在意能自己安排时间。", "明白。")
        engine._enqueue(generic_turn, "normal")
        engine.process_pending()
        results = engine.retrieve("结合我们之前聊过的内容，你觉得我真正想要的生活是什么？")
        self.assertGreaterEqual(len(results), 2)
        self.assertEqual(results[0].id, mountain_claim.id)

    def test_listen_only_turn_skips_personal_understanding_retrieval(self):
        engine, model = self.make_engine(create_proposal())
        self.create_claim(engine, model)
        result = engine.retrieve("我最近有点迷茫，先别给我方案，我只是想说说。")
        self.assertEqual(result, [])
        self.assertEqual(engine.last_search["suppression_reason"], "listen_only")

    def test_third_party_vent_skips_personal_understanding_retrieval(self):
        engine, model = self.make_engine(create_proposal())
        self.create_claim(engine, model)
        result = engine.retrieve("我朋友最近说他想辞职创业，我只是听他吐槽。")
        self.assertEqual(result, [])
        self.assertEqual(engine.last_search["suppression_reason"], "third_party_only")

    def test_transient_mood_skips_personal_understanding_retrieval(self):
        engine, model = self.make_engine(create_proposal())
        self.create_claim(engine, model)
        result = engine.retrieve("今天有点烦，什么都不想做，明天应该就好了。")
        self.assertEqual(result, [])
        self.assertEqual(engine.last_search["suppression_reason"], "transient_mood")

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
        engine, model = self.make_engine(create_proposal(
            quote="我想把创业当成人生目标。",
            content="用户把创业视为人生目标。",
            dimension="motivation",
        ))
        claim = self.create_claim(engine, model, quote="我想把创业当成人生目标。")
        model.outputs.append(reinforce_proposal(
            claim.id, "你理解错了，我并不把创业当成我的人生目标。",
            operation="REJECT", relation="counter",
            content="用户把创业视为人生目标。", dimension="motivation",
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


    def test_sensitive_claim_content_is_rejected_even_when_quote_is_not_sensitive(self):
        proposal = json.loads(create_proposal(quote="我最近心情很低落。"))
        proposal["operations"][0]["content"] = "用户可能患有抑郁症。"
        engine, model = self.make_engine(json.dumps(proposal, ensure_ascii=False))
        turn_id = self.store.append_turn("我最近心情很低落。", "我听到了。")
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

    def test_fabricated_confirmation_question_is_ignored_without_blocking_claim(self):
        raw = json.loads(create_proposal())
        raw["confirmation"] = {
            "claim_id": None, "claim_ref": "c1", "expected_version": 1,
            "turn_index": 0, "question": "你确定吗？",
        }
        engine, model = self.make_engine(json.dumps(raw, ensure_ascii=False))
        turn_id = self.store.append_turn("我更在意能自己安排时间。", "收到。")
        engine._enqueue(turn_id, "normal")
        event = engine.process_pending()
        self.assertFalse(event.errors)
        self.assertEqual(len(engine.list_claims()), 1)
        self.assertEqual(engine.pending_confirmations(), [])

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


    def test_confirmation_expires_if_an_intervening_turn_was_skipped(self):
        raw = json.loads(create_proposal())
        raw["confirmation"] = {
            "claim_id": None, "claim_ref": "c1", "expected_version": 1,
            "turn_index": 0, "question": "你觉得这个理解准确吗？",
        }
        engine, model = self.make_engine(json.dumps(raw, ensure_ascii=False))
        first = self.store.append_turn(
            "更正一下：我更在意能自己安排时间。",
            "你觉得这个理解准确吗？",
        )
        engine._enqueue(first, "immediate")
        engine.process_pending()
        # Simulate a host-side control turn which does not pass through Agent.reply.
        self.store.append_turn("我先处理一下其他事情。", "好的。")
        answer_turn = self.store.append_turn("是的", "收到。")
        self.assertEqual(engine.resolve_pending_confirmation("是的", answer_turn), ())
        status = self.store.connection.execute(
            "SELECT status FROM understanding_pending_confirmations").fetchone()[0]
        self.assertEqual(status, "expired")
        claim, = engine.list_claims()
        self.assertEqual(claim.user_validation, "unconfirmed")

    def test_high_support_requires_evidence_across_time(self):
        engine, model = self.make_engine(create_proposal())
        first = self.store.append_turn("我更在意能自己安排时间。", "明白。")
        self.store.connection.execute(
            "UPDATE turns SET created_at='2024-01-01 09:00:00' WHERE id=?", (first,))
        engine._enqueue(first, "normal")
        engine.process_pending()
        claim, = engine.list_claims()

        second_quote = "如果必须选，我还是更看重自主安排时间。"
        second = self.store.append_turn(second_quote, "理解。")
        self.store.connection.execute(
            "UPDATE turns SET created_at='2024-01-02 09:00:00' WHERE id=?", (second,))
        model.outputs.append(reinforce_proposal(claim.id, second_quote, version=1))
        engine._enqueue(second, "normal")
        engine.process_pending()
        self.assertEqual(engine.list_claims()[0].support_level, "medium")

        third_quote = "即使有更高头衔，我仍然更希望自己安排时间。"
        third = self.store.append_turn(third_quote, "知道了。")
        self.store.connection.execute(
            "UPDATE turns SET created_at='2024-02-01 09:00:00' WHERE id=?", (third,))
        model.outputs.append(reinforce_proposal(claim.id, third_quote, version=2))
        engine._enqueue(third, "normal")
        engine.process_pending()
        self.assertEqual(engine.list_claims()[0].support_level, "high")


    def test_confirmation_classifier_does_not_match_ambiguous_substrings(self):
        engine, model = self.make_engine()
        self.assertIsNone(engine._confirmation_kind("对不起，我刚才没听清。"))
        self.assertIsNone(engine._confirmation_kind("我对这个问题还有疑问。"))
        self.assertEqual(engine._confirmation_kind("对，我认可这个理解。"), "confirmed")
        self.assertEqual(engine._confirmation_kind("不是，我的意思不同。"), "rejected")


    def test_urgent_trigger_distinguishes_personal_correction_from_code_edit(self):
        self.assertFalse(PersonalUnderstanding.is_urgent("更正一下这段 Python 代码。"))
        self.assertTrue(PersonalUnderstanding.is_urgent("更正一下：我更在意自主安排时间。"))
        self.assertTrue(PersonalUnderstanding.is_urgent("请更新你对我的理解：我不再把创业当成人生目标。"))


    def test_deleting_new_evidence_restores_previous_supported_version(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        quote = "和熟悉的人围绕共同兴趣交流，我会觉得很自在。"
        model.outputs.append(json.dumps({
            "evidence": [{
                "ref": "e1", "turn_index": 0, "quote": quote,
                "kind": "self_interpretation", "event_time": None,
            }],
            "operations": [{
                "operation": "REFINE", "claim_ref": None, "claim_id": claim.id,
                "expected_version": 1,
                "content": "用户重视自主安排时间，也偏好围绕共同兴趣进行深入交流。",
                "dimension": "patterns", "basis": "self_interpretation",
                "scope": {"social_context": "熟悉的人、共同兴趣"},
                "temporal_scope": "ongoing",
                "evidence": [{"ref": "e1", "relation": "qualifies"}],
                "reason": "新证据补充了适用情境。",
            }],
            "confirmation": None,
        }, ensure_ascii=False))
        newer_turn = self.store.append_turn(quote, "明白。")
        engine._enqueue(newer_turn, "normal")
        engine.process_pending()
        self.assertEqual(engine.list_claims()[0].version, 2)
        with self.store.connection:
            self.store.connection.execute("DELETE FROM turns WHERE id=?", (newer_turn,))
        restored, = engine.list_claims()
        self.assertEqual(restored.id, claim.id)
        self.assertEqual(restored.version, 1)
        self.assertEqual(restored.status, "active")
        self.assertEqual(len(engine.get_claim_history(claim.id)), 1)


    def test_deleting_reinforcement_evidence_recalculates_support_level(self):
        engine, model = self.make_engine(create_proposal())
        claim = self.create_claim(engine, model)
        quote = "如果必须选，我还是更看重自主安排时间。"
        model.outputs.append(reinforce_proposal(claim.id, quote))
        second = self.store.append_turn(quote, "理解。")
        self.store.connection.execute(
            "UPDATE turns SET created_at='2024-02-01 09:00:00' WHERE id=?", (second,))
        engine._enqueue(second, "normal")
        engine.process_pending()
        self.assertEqual(engine.list_claims()[0].support_level, "medium")
        with self.store.connection:
            self.store.connection.execute("DELETE FROM turns WHERE id=?", (second,))
        restored, = engine.list_claims()
        self.assertEqual(restored.version, 2)
        self.assertEqual(restored.support_level, "low")
        self.assertEqual(restored.status, "active")
        self.assertEqual(engine.list_revisions(claim.id)[-1]["operation"], "CREATE")


    def test_running_jobs_are_recovered_after_reopening_engine(self):
        model = ScriptedModel(create_proposal())
        engine = PersonalUnderstanding(self.store, model)
        turn_id = self.store.append_turn("我更在意能自己安排时间。", "明白。")
        engine._enqueue(turn_id, "normal")
        self.store.connection.execute(
            "UPDATE understanding_jobs SET status='running' WHERE source_turn_id=?", (turn_id,))
        recovered = PersonalUnderstanding(self.store, model)
        event = recovered.process_pending()
        self.assertFalse(event.errors)
        self.assertEqual(len(recovered.list_claims()), 1)
        status = self.store.connection.execute(
            "SELECT status FROM understanding_jobs WHERE source_turn_id=?", (turn_id,)
        ).fetchone()[0]
        self.assertEqual(status, "done")


    def test_event_time_must_be_explicit_and_evidence_refs_unique(self):
        invalid_time = json.loads(create_proposal())
        invalid_time["evidence"][0]["event_time"] = "2020-01-01"
        duplicate_ref = json.loads(create_proposal())
        duplicate_ref["operations"][0]["evidence"].append(
            {"ref": "e1", "relation": "qualifies"}
        )
        for proposal in (invalid_time, duplicate_ref):
            engine, model = self.make_engine(json.dumps(proposal, ensure_ascii=False))
            turn_id = self.store.append_turn("我更在意能自己安排时间。", "收到。")
            engine._enqueue(turn_id, "normal")
            event = engine.process_pending()
            self.assertEqual(event.errors, ("update_failed",))
            self.assertEqual(engine.list_claims(), [])


    def test_reflective_retrieval_includes_goals_and_real_world_constraints(self):
        engine, model = self.make_engine()
        scenarios = [
            ("我重视拥有选择权。", "用户重视拥有选择权。", "values"),
            ("我未来一年想把 AI 知识学扎实。", "用户未来一年的目标是扎实学习 AI。", "goals"),
            ("家里的固定支出让我需要稳定现金流。", "用户需要稳定现金流以覆盖固定支出。", "constraints"),
            ("我以前的想法现在发生了变化。", "用户明确意识到自己对某项认识发生了变化。", "cognition"),
            ("我喜欢围绕共同兴趣深入交流。", "用户偏好围绕共同兴趣进行深入交流。", "patterns"),
            ("我希望能选择自己愿意承担的约束。", "用户将自由理解为选择愿意承担的约束。", "self_concept"),
        ]
        for quote, claim_text, dimension in scenarios:
            model.outputs.append(create_proposal(
                quote=quote, content=claim_text, dimension=dimension,
            ))
            turn_id = self.store.append_turn(quote, "明白。")
            engine._enqueue(turn_id, "normal")
            event = engine.process_pending()
            self.assertFalse(event.errors)
        selected = engine.retrieve(
            "结合之前聊过的内容，我真正想要的生活有哪些取舍和变化？"
        )
        dimensions = {claim.dimension for claim in selected}
        self.assertIn("goals", dimensions)
        self.assertIn("constraints", dimensions)
        self.assertIn("values", dimensions)
        self.assertLessEqual(len(selected), 7)

    def test_store_mismatch_and_invalid_limits(self):
        other = SQLiteConversationStore(":memory:")
        self.addCleanup(other.close)
        engine = PersonalUnderstanding(other, ScriptedModel())
        with self.assertRaises(ValueError):
            Agent(ScriptedModel(), self.store, personal_understanding=engine)
        with self.assertRaises(ValueError):
            engine.retrieve("test", 8)
        with self.assertRaises(ValueError):
            engine.process_pending(limit=6)

    def test_delayed_confirmation_is_reconciled_without_cross_conversation_expiry(self):
        question_a = "你觉得我这样理解准确吗？"
        question_b = "你也这样认为吗？"
        proposal_a = json.loads(create_proposal())
        proposal_a["confirmation"] = {
            "claim_id": None, "claim_ref": "c1", "expected_version": 1,
            "turn_index": 0, "question": question_a,
        }
        proposal_b = json.loads(create_proposal(
            quote="我喜欢和朋友深入交流。",
            content="用户偏好与朋友围绕共同兴趣深入交流。",
            dimension="patterns",
        ))
        proposal_b["confirmation"] = {
            "claim_id": None, "claim_ref": "c1", "expected_version": 1,
            "turn_index": 0, "question": question_b,
        }
        model = ScriptedModel(
            json.dumps(proposal_a, ensure_ascii=False),
            json.dumps(proposal_b, ensure_ascii=False),
        )
        engine = PersonalUnderstanding(self.store, model)

        turn_a = self.store.append_turn(
            "我更在意能自己安排时间。", question_a
        )
        engine.observe_turn(
            turn_a, "我更在意能自己安排时间。", question_a, process=False
        )

        other = self.store.create_conversation("另一个会话")
        other_store = self.store.for_conversation(other["id"])
        turn_b = other_store.append_turn("我喜欢和朋友深入交流。", question_b)
        engine.observe_turn(
            turn_b, "我喜欢和朋友深入交流。", question_b, process=False
        )
        answer_b = "先说说别的事。"
        next_b = other_store.append_turn(answer_b, "好的。")

        answer_a = "是的，我认可这个理解。"
        next_a = self.store.append_turn(answer_a, "谢谢。")
        # The answer can arrive before the understanding model finishes.
        self.assertEqual(engine.resolve_pending_confirmation(answer_a, next_a), ())
        self.assertEqual(engine.resolve_pending_confirmation(answer_b, next_b), ())

        first = engine.process_pending(limit=1)
        second = engine.process_pending(limit=1)
        self.assertFalse(first.errors)
        self.assertFalse(second.errors)

        # A later turn in conversation B must not expire A's pending confirmation.
        self.assertEqual(engine.resolve_pending_confirmation(answer_b, next_b), ())
        pending_before_reconciliation = engine.pending_confirmations()
        self.assertEqual(len(pending_before_reconciliation), 1)
        self.assertEqual(pending_before_reconciliation[0]["source_turn_id"], turn_a)

        resolved = engine.resolve_deferred_confirmations()
        self.assertEqual(len(resolved), 1)
        claims = engine.list_claims()
        confirmed = next(item for item in claims if item.user_validation == "confirmed")
        self.assertEqual(confirmed.content, "用户重视自主安排时间。")
        self.assertEqual(engine.pending_confirmations(), [])
        other_status = self.store.connection.execute(
            "SELECT status FROM understanding_pending_confirmations WHERE source_turn_id=?",
            (turn_b,),
        ).fetchone()[0]
        self.assertEqual(other_status, "expired")

        other_store.close()

    def test_read_manager_does_not_requeue_a_live_worker_job(self):
        model = ScriptedModel()
        engine = PersonalUnderstanding(self.store, model)
        turn_id = self.store.append_turn("我更在意能自己安排时间。", "明白。")
        engine._enqueue(turn_id, "normal")
        self.store.connection.execute(
            "UPDATE understanding_jobs SET status='running' WHERE source_turn_id=?",
            (turn_id,),
        )
        self.store.connection.commit()

        PersonalUnderstanding(
            self.store, model, recover_running_jobs=False
        )
        status = self.store.connection.execute(
            "SELECT status FROM understanding_jobs WHERE source_turn_id=?",
            (turn_id,),
        ).fetchone()[0]
        self.assertEqual(status, "running")

    def test_claim_list_offset_pagination_is_stable(self):
        model = ScriptedModel(
            create_proposal("我更在意能自己安排时间。", claim_ref="c1"),
            create_proposal("我希望有稳定的收入。", claim_ref="c2",
                            content="用户希望拥有稳定收入。", dimension="constraints"),
            create_proposal("我喜欢研究新的技术。", claim_ref="c3",
                            content="用户喜欢研究新技术。", dimension="patterns"),
        )
        engine = PersonalUnderstanding(self.store, model)
        for quote in (
            "我更在意能自己安排时间。",
            "我希望有稳定的收入。",
            "我喜欢研究新的技术。",
        ):
            turn_id = self.store.append_turn(quote, "明白。")
            engine._enqueue(turn_id, "normal")
            event = engine.process_pending()
            self.assertFalse(event.errors)

        full = engine.list_claims(limit=200)
        first = engine.list_claims(limit=1, offset=0)
        second = engine.list_claims(limit=1, offset=1)
        third = engine.list_claims(limit=1, offset=2)
        self.assertEqual(
            [item.id for item in first + second + third],
            [item.id for item in full],
        )
        with self.assertRaises(ValueError):
            engine.list_claims(limit=1, offset=-1)


if __name__ == "__main__":
    unittest.main()
