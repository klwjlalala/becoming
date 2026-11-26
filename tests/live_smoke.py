"""Opt-in live model smoke test; excluded from default test_*.py discovery.

Run from the repository root:
    python -m unittest discover -s tests -p live_smoke.py -v

Uses synthetic data, three model calls on success, and a temporary SQLite file.
Credentials are read from environment variables and never printed.
"""
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.models import OpenAICompatibleModel


class LiveModelSmokeTest(unittest.TestCase):
    def test_live_conversation_and_restart(self):
        required = ("BECOMING_BASE_URL", "BECOMING_API_KEY", "BECOMING_MODEL")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            self.fail("Missing environment variables: " + ", ".join(missing))

        model = OpenAICompatibleModel(
            os.environ["BECOMING_BASE_URL"],
            os.environ["BECOMING_API_KEY"],
            os.environ["BECOMING_MODEL"],
        )
        marker = "BE-" + uuid.uuid4().hex[:12]

        def ask(agent, label, prompt):
            start = time.monotonic()
            answer = agent.reply(prompt)
            elapsed = time.monotonic() - start
            print(f"{label}: {elapsed:.2f}s, {len(answer)} characters", flush=True)
            self.assertTrue(answer.strip())
            return answer

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.sqlite3"
            store = SQLiteConversationStore(path)
            try:
                agent = Agent(model, store)
                ask(agent, "Initial model response",
                    f"这是虚构测试数据，我的测试代号是 {marker}。请简短回复已了解。")
                answer = ask(agent, "Multi-turn context", "我的测试代号是什么？请只回复代号。")
                self.assertIn(marker, answer)
                self.assertEqual(len(store.recent()), 4)
            finally:
                store.close()

            reopened = SQLiteConversationStore(path)
            try:
                agent = Agent(model, reopened)
                answer = ask(agent, "Reopened agent and database",
                             "请再次告诉我最初提供的测试代号。")
                self.assertIn(marker, answer)
                self.assertEqual(len(reopened.recent()), 6)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
