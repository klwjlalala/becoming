"""Explicit real-model tool integration, isolated synthetic databases."""
import os
import unittest

from becoming.growth_agent import GrowthAgent
from becoming.growth_store import GrowthStore
from becoming.memory import SQLiteConversationStore
from becoming.models import OpenAICompatibleModel


class LiveGrowthTests(unittest.TestCase):
    def test_explicit_all_tools(self):
        model = OpenAICompatibleModel(os.environ.get("BECOMING_BASE_URL", ""),
                                      os.environ.get("BECOMING_API_KEY", ""),
                                      os.environ.get("BECOMING_MODEL", ""))
        transcript, growth = SQLiteConversationStore(":memory:"), GrowthStore(":memory:")
        self.addCleanup(transcript.close)
        self.addCleanup(growth.close)
        agent = GrowthAgent(model, transcript, growth)

        def mutate(tool, prompt):
            agent.reply(prompt)
            self.assertIsNotNone(agent.last_event, "Model did not use a tool")
            self.assertEqual(agent.last_event["tool"], tool)
            self.assertEqual(agent.last_event["status"], "proposed")
            token = agent.adapter.pending[0]
            agent.reply("/confirm " + token)
            self.assertEqual(agent.last_event["status"], "committed")
            return agent.last_event["result"]

        goal = mutate("create_goal", "明确调用 create_goal，text 为虚构目标：读书。")["record"]
        gid = goal["id"]
        self.assertEqual(goal["text"], "虚构目标：读书")
        action = mutate("create_action", f"明确调用 create_action，goal_id={gid}，text=读一页。")["record"]
        reflection = mutate("record_reflection",
                            f"明确调用 record_reflection，goal_id={gid}，text=感觉平静。")["record"]
        updated = mutate("update_item", f"明确调用 update_item，id={action['id']}，status=done。")["record"]
        self.assertEqual(updated["status"], "done")
        for tool, prompt in (("list_goals", "明确调用 list_goals 列出目标。"),
                             ("get_goal", f"明确调用 get_goal，goal_id={gid}。")):
            agent.reply(prompt)
            self.assertIsNotNone(agent.last_event)
            self.assertEqual(agent.last_event["tool"], tool)
            self.assertEqual(agent.last_event["status"], "read")
            self.assertFalse(agent.last_event.get("followup_failed"))
            self.assertIn("result", agent.last_event)
        mutate("delete_item", f"明确调用 delete_item，id={reflection['id']}。")
        self.assertEqual(len(growth.read("get_goal", {"goal_id": gid})["items"]), 1)
