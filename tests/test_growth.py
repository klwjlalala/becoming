import json
import tempfile
import unittest
from pathlib import Path

from becoming.growth_agent import GrowthAgent, PREFIX, POLICY
from becoming.growth_store import GrowthStore
from becoming.memory import SQLiteConversationStore
from becoming.models import ModelError


def call(tool, **args):
    return PREFIX + json.dumps({"tool": tool, "args": args}, ensure_ascii=False)


class Scripted:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append([dict(m) for m in messages])
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.store = GrowthStore(":memory:")
        self.history = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)
        self.addCleanup(self.history.close)

    def create(self, tool, **args):
        return self.store.apply(self.store.prepare(tool, args))["record"]

    def confirm(self, agent):
        return agent.reply("/confirm " + agent.adapter.pending[0])

    def test_all_mutation_tools_through_agent_and_actual_storage(self):
        model = Scripted(call("create_goal", text="创作"),
                         call("create_action", goal_id=1, text="写一段故事"),
                         call("record_reflection", goal_id=1, text="写作很放松"),
                         call("update_item", id=2, status="done"),
                         call("update_item", id=1, status="paused"),
                         call("delete_item", id=3))
        agent = GrowthAgent(model, self.history, self.store)
        for i in range(6):
            response = agent.reply("明确请求 " + str(i))
            self.assertIn("尚未保存", response)
            self.assertEqual(agent.last_event["status"], "proposed")
            self.confirm(agent)
            self.assertEqual(agent.last_event["status"], "committed")
        result = self.store.read("get_goal", {"goal_id": 1})
        self.assertEqual(result["goal"]["status"], "paused")
        self.assertEqual([(x["kind"], x["status"]) for x in result["items"]], [("action", "done")])
        self.assertEqual(len(model.calls), 6)

    def test_preview_no_write_and_exact_one_shot_confirmation(self):
        agent = GrowthAgent(Scripted(call("create_goal", text="阅读")), self.history, self.store)
        agent.reply("帮我记录")
        token = agent.adapter.pending[0]
        self.assertEqual(self.store.read("list_goals", {})["items"], [])
        self.assertIn("没有匹配", agent.reply("/confirm wrong"))
        self.confirm(agent)
        self.assertIn("没有匹配", agent.reply("/confirm " + token))
        self.assertEqual(len(self.store.read("list_goals", {})["items"]), 1)

    def test_cancel_new_message_restart_and_plain_language_never_commit(self):
        model = Scripted(call("create_goal", text="A"), "好的", call("create_goal", text="B"),
                         call("create_goal", text="C"))
        agent = GrowthAgent(model, self.history, self.store)
        agent.reply("记录A")
        token = agent.adapter.pending[0]
        agent.reply("确认")
        self.assertIn("没有匹配", agent.reply("/confirm " + token))
        agent.reply("记录B")
        agent.reply("/cancel")
        agent.reply("记录C")
        other = GrowthAgent(Scripted(), self.history, self.store)
        self.assertIn("没有匹配", other.reply("/confirm " + agent.adapter.pending[0]))
        self.assertEqual(self.store.read("list_goals", {})["items"], [])

    def test_tool_marker_after_preamble_is_executed(self):
        raw = json.dumps({"tool": "list_goals", "args": {}}, ensure_ascii=False)
        model = Scripted("我先检查一下现有记录。\nGROWTH_TOOL\n" + raw,
                         "目前还没有成长目标。")
        agent = GrowthAgent(model, self.history, self.store)
        answer = agent.reply("帮我查看目标")
        self.assertEqual(agent.last_event["status"], "read")
        self.assertEqual(agent.last_event["result"]["items"], [])
        self.assertEqual(answer, "目前还没有成长目标。")

    def test_tool_marker_with_inline_json_is_executed(self):
        raw = json.dumps({"tool": "list_goals", "args": {}}, ensure_ascii=False)
        model = Scripted("我来查询。 GROWTH_TOOL " + raw, "目前还没有成长目标。")
        agent = GrowthAgent(model, self.history, self.store)
        self.assertEqual(agent.reply("查看目标"), "目前还没有成长目标。")
        self.assertEqual(agent.last_event["status"], "read")

    def test_model_preview_text_is_revalidated_against_database(self):
        goal = self.create("create_goal", text="阅读")
        action = self.create("create_action", goal_id=goal["id"], text="睡前读十分钟")
        payload = json.dumps({
            "tool": "update_item",
            "args": {"id": action["id"], "status": "done"},
            "parent": {"id": 999, "kind": "goal", "text": "伪造父目标"},
        }, ensure_ascii=False)
        model = Scripted("尚未保存。请核对以下变更：\n" + payload)
        agent = GrowthAgent(model, self.history, self.store)
        answer = agent.reply("把刚才的行动标记为完成")
        self.assertEqual(agent.last_event["status"], "proposed")
        preview = agent.adapter.pending[1]
        self.assertEqual(preview["before"]["id"], action["id"])
        self.assertNotEqual(preview["before"].get("text"), "伪造父目标")
        self.assertIn("/confirm ", answer)
        agent.reply("/confirm " + agent.adapter.pending[0])
        self.assertEqual(agent.last_event["status"], "committed")
        self.assertEqual(self.store.read("get_goal", {"goal_id": goal["id"]})["items"][0]["status"], "done")

    def test_read_tools_return_actual_results_and_followup(self):
        self.create("create_goal", text="真实标记")
        model = Scripted(call("list_goals"), "你的目标如下", call("get_goal", goal_id=1), "详情")
        agent = GrowthAgent(model, self.history, self.store)
        for text in ("列出目标", "看详情"):
            answer = agent.reply(text)
            self.assertEqual(answer, "你的目标如下" if text == "列出目标" else "详情")
            self.assertEqual(agent.last_event["status"], "read")
            self.assertIn("真实标记", json.dumps(agent.last_event["result"], ensure_ascii=False))
            self.assertIn("真实标记", model.calls[-1][-1]["content"])
        self.assertEqual(len(model.calls), 4)

    def test_read_followup_cannot_chain_mutation(self):
        model = Scripted(call("list_goals"), call("create_goal", text="不允许"))
        agent = GrowthAgent(model, self.history, self.store)
        self.assertIn("未能完成解读", agent.reply("查询"))
        self.assertTrue(agent.last_event["followup_failed"])
        self.assertIsNone(agent.adapter.pending)
        self.assertEqual(self.store.read("list_goals", {})["items"], [])

    def test_normal_conversation_single_call_no_storage_mutation(self):
        model = Scripted("听起来你只是想休息。")
        agent = GrowthAgent(model, self.history, self.store)
        self.assertEqual(agent.reply("今天好累"), "听起来你只是想休息。")
        self.assertEqual(len(model.calls), 1)
        self.assertIn(POLICY, model.calls[0][0]["content"])
        self.assertIsNone(agent.last_event)
        self.assertEqual(self.store.read("list_goals", {})["items"], [])

    def test_invalid_envelopes_and_parameters_fail_closed(self):
        invalid = [PREFIX + "{", PREFIX + '{"tool":"list_goals","tool":"delete_item","args":{}}',
                   call("unknown"), call("create_goal", text=" "), call("create_goal", text="x", extra=True),
                   call("create_action", goal_id=True, text="x"), call("delete_item", id=999),
                   call("get_goal", goal_id=1.5), call("update_item", id=1)]
        agent = GrowthAgent(Scripted(*invalid), self.history, self.store)
        for _ in invalid:
            agent.reply("测试")
            self.assertEqual(agent.last_event["status"], "rejected")
            self.assertIsNone(agent.adapter.pending)
        self.assertEqual(self.store.read("list_goals", {})["items"], [])

    def test_parent_kind_status_and_stale_write(self):
        goal = self.create("create_goal", text="g")
        action = self.create("create_action", goal_id=goal["id"], text="a")
        with self.assertRaises(ValueError):
            self.store.prepare("create_action", {"goal_id": action["id"], "text": "x"})
        with self.assertRaises(ValueError):
            self.store.prepare("update_item", {"id": goal["id"], "status": "done"})
        agent = GrowthAgent(Scripted(call("update_item", id=goal["id"], status="paused")),
                            self.history, self.store)
        agent.reply("暂停")
        self.store.apply(self.store.prepare("update_item", {"id": goal["id"], "text": "changed"}))
        self.confirm(agent)
        self.assertEqual(agent.last_event["status"], "failed")
        self.assertEqual(self.store.read("get_goal", {"goal_id": goal["id"]})["goal"]["status"], "active")

    def test_delete_cascade_and_stale_child_change(self):
        goal = self.create("create_goal", text="g")
        child = self.create("record_reflection", goal_id=goal["id"], text="first")
        pending = self.store.prepare("delete_item", {"id": goal["id"]})
        self.store.apply(self.store.prepare("update_item", {"id": child["id"], "text": "second"}))
        with self.assertRaises(ValueError):
            self.store.apply(pending)
        result = self.store.apply(self.store.prepare("delete_item", {"id": goal["id"]}))
        self.assertEqual(result["deleted_children"], 1)
        self.assertEqual(self.store.read("list_goals", {})["items"], [])
        with self.assertRaises(ValueError):
            self.store.prepare("delete_item", {"id": child["id"]})

    def test_persistence_pagination_and_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "growth.sqlite"
            s = GrowthStore(path)
            for i in range(31):
                s.apply(s.prepare("create_goal", {"text": str(i)}))
            s.close()
            s = GrowthStore(path)
            self.addCleanup(s.close)
            page = s.read("list_goals", {})
            self.assertEqual(len(page["items"]), 30)
            self.assertEqual(page["next_offset"], 30)
            self.assertEqual(len(s.read("list_goals", {"offset": 30})["items"]), 1)
            self.assertEqual(self.store.read("list_goals", {})["items"], [])

    def test_transcript_failure_invalidates_proposal(self):
        class BrokenTranscript:
            def recent(self, limit):
                return []
            def append_turn(self, user, assistant):
                raise RuntimeError("disk failure")
        agent = GrowthAgent(Scripted(call("create_goal", text="g")), BrokenTranscript(), self.store)
        with self.assertRaises(RuntimeError):
            agent.reply("记录")
        self.assertIsNone(agent.adapter.pending)
        self.assertEqual(self.store.read("list_goals", {})["items"], [])

    def test_confirmation_and_cancellation_are_recorded_without_nonce_leak(self):
        model = Scripted(call("create_goal", text="长期阅读"))
        agent = GrowthAgent(model, self.history, self.store)
        preview = agent.reply("帮我记录长期阅读目标")
        token = agent.adapter.pending[0]
        self.assertIn("/confirm " + token, preview)
        transcript = self.history.recent()
        self.assertNotIn(token, json.dumps(transcript, ensure_ascii=False))
        agent.reply("/confirm " + token)
        transcript = self.history.recent()
        self.assertIn("我确认了刚才展示的成长记录变更。",
                      [m["content"] for m in transcript if m["role"] == "user"])
        self.assertNotIn(token, json.dumps(transcript, ensure_ascii=False))
        self.assertEqual(agent.last_event["status"], "committed")

    def test_cancel_and_new_message_log_cancellation(self):
        model = Scripted(call("create_goal", text="A"), call("create_goal", text="B"), "普通回复")
        agent = GrowthAgent(model, self.history, self.store)
        agent.reply("记录A")
        agent.reply("/cancel")
        self.assertEqual(agent.last_event["status"], "cancelled")
        self.assertIn("我取消了刚才尚未确认的成长记录变更。",
                      [m["content"] for m in self.history.recent() if m["role"] == "user"])
        agent.reply("记录B")
        agent.reply("换个话题")
        self.assertEqual(agent.last_event, None)
        self.assertEqual(len(self.store.read("list_goals", {})["items"]), 0)

    def test_growth_store_clear_cascades_all_children(self):
        goal = self.create("create_goal", text="g")
        self.create("create_action", goal_id=goal["id"], text="a")
        self.create("record_reflection", goal_id=goal["id"], text="r")
        self.assertEqual(self.store.clear(), {"goal": 1, "action": 1, "reflection": 1})
        self.assertEqual(self.store.read("list_goals", {})["items"], [])

    def test_model_failure_and_recovery(self):
        agent = GrowthAgent(Scripted(call("create_goal", text="g"), ModelError("failed"), "恢复"),
                            self.history, self.store)
        agent.reply("记录")
        with self.assertRaises(ModelError):
            agent.reply("新消息")
        self.assertIsNone(agent.adapter.pending)
        self.assertEqual(agent.reply("再试"), "恢复")
