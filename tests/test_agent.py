import tempfile
import unittest
from pathlib import Path
from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.models import ModelError, DemoModel


class RecordingModel:
    def __init__(self):
        self.messages = []

    def complete(self, messages):
        self.messages = list(messages)
        return "reply"


class FailingModel:
    def complete(self, messages):
        raise ModelError("failure")


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)
        self.model = RecordingModel()
        self.agent = Agent(self.model, self.store, history_turns=1)

    def test_turn_and_context_order(self):
        self.assertEqual(self.agent.reply("first"), "reply")
        self.agent.reply("second")
        self.agent.reply("third")
        self.assertEqual([m["role"] for m in self.model.messages],
                         ["system", "user", "assistant", "user"])
        self.assertEqual([m["content"] for m in self.model.messages[1:]],
                         ["second", "reply", "third"])

    def test_blank_input(self):
        with self.assertRaises(ValueError):
            self.agent.reply("  ")
        self.assertEqual(self.store.recent(), [])

    def test_failure_does_not_store_turn(self):
        with self.assertRaises(ModelError):
            Agent(FailingModel(), self.store).reply("hello")
        self.assertEqual(self.store.recent(), [])

    def test_clear(self):
        self.agent.reply("hello")
        self.store.clear()
        self.assertEqual(self.store.recent(), [])

    def test_persistence_across_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.sqlite3"
            store = SQLiteConversationStore(path)
            Agent(DemoModel(), store).reply("hello")
            store.close()
            reopened = SQLiteConversationStore(path)
            try:
                self.assertEqual(reopened.recent()[0]["content"], "hello")
                self.assertEqual(len(reopened.recent()), 2)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
