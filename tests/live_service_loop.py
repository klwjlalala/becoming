"""Explicit end-to-end memory + growth-tool integration using synthetic user data."""
import os
import unittest

from becoming.growth_agent import GrowthAgent
from becoming.growth_store import GrowthStore
from becoming.long_memory import LongMemory
from becoming.memory import SQLiteConversationStore
from becoming.models import OpenAICompatibleModel


class LiveServiceLoopTests(unittest.TestCase):
    def test_memory_then_confirmed_growth_tool(self):
        model = OpenAICompatibleModel(os.environ.get("BECOMING_BASE_URL", ""),
                                      os.environ.get("BECOMING_API_KEY", ""),
                                      os.environ.get("BECOMING_MODEL", ""))
        transcript, growth = SQLiteConversationStore(":memory:"), GrowthStore(":memory:")
        self.addCleanup(transcript.close)
        self.addCleanup(growth.close)
        memory = LongMemory(transcript, model)
        agent = GrowthAgent(model, transcript, growth, long_memory=memory)

        agent.reply("虚构测试：请长期记住，我喜欢晚上阅读。")
        self.assertTrue(agent.last_memory_event.written_ids,
                        "Explicit memory request was not stored; inspect model extraction")
        agent.reply("你还记得我喜欢什么时候阅读吗？")
        self.assertTrue(agent.last_memory_event.retrieved_ids,
                        "Previously stored preference was not retrieved")

        proposal = agent.reply("请明确调用 create_goal，text 为虚构目标：重新培养阅读习惯。")
        self.assertEqual(agent.last_event["status"], "proposed", proposal)
        token = agent.adapter.pending[0]
        confirmation = agent.reply("/confirm " + token)
        self.assertEqual(agent.last_event["status"], "committed", confirmation)

        agent.reply("请明确调用 list_goals 列出我的成长目标。")
        self.assertEqual(agent.last_event["status"], "read")
        self.assertTrue(agent.last_event["result"]["items"])
        print("Live integrated memory/growth event:", agent.last_memory_event, agent.last_event)
