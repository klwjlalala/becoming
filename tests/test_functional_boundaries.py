"""Deterministic functional tests. All model calls are mocked."""
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.models import ModelError, OpenAICompatibleModel
from becoming.prompts import SYSTEM_PROMPT


class AgentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)
        self.model = Mock()
        self.model.complete.return_value = "answer"

    def test_first_turn_exact_context_and_normalization(self):
        self.model.complete.return_value = "  你好  "
        self.assertEqual(Agent(self.model, self.store).reply("  测试  "), "你好")
        self.model.complete.assert_called_once_with([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "测试"},
        ])
        self.assertEqual(self.store.recent(), [
            {"role": "user", "content": "测试"},
            {"role": "assistant", "content": "你好"},
        ])

    def test_blank_input_never_calls_model(self):
        for value in ("", " ", "\n\t", "\u3000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Agent(self.model, self.store).reply(value)
        self.model.complete.assert_not_called()
        self.assertEqual(self.store.recent(), [])

    def test_zero_history(self):
        self.store.append_turn("old", "old reply")
        Agent(self.model, self.store, history_turns=0).reply("new")
        self.assertEqual(len(self.model.complete.call_args.args[0]), 2)
        self.assertEqual(len(self.store.recent()), 4)

    def test_negative_history_rejected(self):
        with self.assertRaises(ValueError):
            Agent(self.model, self.store, history_turns=-1)
        self.model.complete.assert_not_called()

    def test_default_history_window_is_twelve_turns(self):
        for i in range(15):
            self.store.append_turn(f"u{i}", f"a{i}")
        Agent(self.model, self.store).reply("new")
        messages = self.model.complete.call_args.args[0]
        self.assertEqual(len(messages), 26)
        self.assertEqual(messages[1]["content"], "u3")
        self.assertEqual(messages[-2]["content"], "a14")
        self.assertEqual(messages[-1]["content"], "new")

    def test_invalid_model_reply_does_not_persist(self):
        self.store.append_turn("old", "reply")
        before = self.store.recent()
        for value in ("", " ", None, 123, []):
            with self.subTest(value=value):
                self.model.complete.return_value = value
                with self.assertRaises(ModelError):
                    Agent(self.model, self.store).reply("failed turn")
                self.assertEqual(self.store.recent(), before)

    def test_recovers_after_model_failure(self):
        self.model.complete.side_effect = [ModelError("failure"), "success"]
        agent = Agent(self.model, self.store)
        with self.assertRaises(ModelError):
            agent.reply("failed")
        self.assertEqual(agent.reply("retry"), "success")
        self.assertEqual([m["content"] for m in self.store.recent()], ["retry", "success"])

    def test_storage_write_failure_not_reported_as_success(self):
        with patch.object(self.store, "append_turn", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                Agent(self.model, self.store).reply("hello")
        self.assertEqual(self.store.recent(), [])

    def test_storage_read_failure_never_calls_model(self):
        with patch.object(self.store, "recent", side_effect=sqlite3.OperationalError("read failed")):
            with self.assertRaises(sqlite3.OperationalError):
                Agent(self.model, self.store).reply("hello")
        self.model.complete.assert_not_called()


class StorageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)

    def test_empty_and_zero_limit(self):
        self.assertEqual(self.store.recent(), [])
        self.store.append_turn("a", "b")
        self.assertEqual(self.store.recent(0), [])

    def test_negative_limit(self):
        with self.assertRaises(ValueError):
            self.store.recent(-1)

    def test_unicode_and_sql_like_text_roundtrip(self):
        text = "中文🌱\n'); DROP TABLE turns; --"
        self.store.append_turn(text, "回复")
        self.assertEqual(self.store.recent()[0]["content"], text)
        self.store.append_turn("next", "next reply")
        self.assertEqual(len(self.store.recent()), 4)

    def test_recent_order_and_limit(self):
        for i in range(4):
            self.store.append_turn(f"u{i}", f"a{i}")
        self.assertEqual([m["content"] for m in self.store.recent(2)],
                         ["u2", "a2", "u3", "a3"])

    def test_failed_insert_is_atomic(self):
        self.store.append_turn("existing", "reply")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_turn("invalid", None)
        self.assertEqual(len(self.store.recent()), 2)
        self.store.append_turn("valid", "reply")
        self.assertEqual(len(self.store.recent()), 4)

    def test_clear_is_idempotent_and_persistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "history.db"
            store = SQLiteConversationStore(path)
            try:
                store.append_turn("old", "reply")
                store.clear()
                store.clear()
            finally:
                store.close()
            reopened = SQLiteConversationStore(path)
            try:
                self.assertEqual(reopened.recent(), [])
                reopened.append_turn("new", "reply")
                self.assertEqual(len(reopened.recent()), 2)
            finally:
                reopened.close()

    def test_two_database_files_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = SQLiteConversationStore(Path(tmp) / "a.db")
            b = SQLiteConversationStore(Path(tmp) / "b.db")
            try:
                a.append_turn("a", "reply")
                self.assertEqual(b.recent(), [])
                b.append_turn("b", "reply")
                self.assertEqual(a.recent()[0]["content"], "a")
            finally:
                a.close()
                b.close()


class ModelBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.model = OpenAICompatibleModel("https://example.test/v1/", "fake-test-key", "test", timeout=3)

    @patch("becoming.models.build_opener")
    def test_request_contract(self, opener):
        send = opener.return_value.open
        send.return_value = io.BytesIO(json.dumps({"choices": [{"message": {"content": "  好  "}}]},
                                                  ensure_ascii=False).encode())
        messages = [{"role": "user", "content": "中文"}]
        self.assertEqual(self.model.complete(messages), "好")
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-test-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"model": "test", "messages": messages})
        self.assertEqual(send.call_args.kwargs["timeout"], 3)

    @patch("becoming.models.build_opener")
    def test_http_errors_are_safe_and_not_retried(self, opener):
        send = opener.return_value.open
        for status in (400, 401, 403, 404, 429, 500, 503):
            with self.subTest(status=status):
                send.reset_mock()
                send.side_effect = HTTPError(self.model.url, status, "secret fake-test-key", {}, None)
                with self.assertRaisesRegex(ModelError, f"HTTP {status}") as caught:
                    self.model.complete([])
                self.assertNotIn("fake-test-key", str(caught.exception))
                send.assert_called_once()

    @patch("becoming.models.build_opener")
    def test_network_and_timeout_errors(self, opener):
        send = opener.return_value.open
        for failure in (URLError("private detail"), TimeoutError(), OSError("private detail")):
            with self.subTest(failure=type(failure).__name__):
                send.side_effect = failure
                with self.assertRaisesRegex(ModelError, "Model connection failed"):
                    self.model.complete([])

    @patch("becoming.models.build_opener")
    def test_malformed_payloads(self, opener):
        send = opener.return_value.open
        for raw in (b"not json", b"{}", b"null", b'{"choices":[]}', b'{"choices":[{}]}'):
            with self.subTest(raw=raw):
                send.return_value = io.BytesIO(raw)
                with self.assertRaisesRegex(ModelError, "Invalid model response"):
                    self.model.complete([])

    @patch("becoming.models.build_opener")
    def test_invalid_content_types(self, opener):
        send = opener.return_value.open
        for value in (None, "", "  ", 12, [], {}):
            with self.subTest(value=value):
                send.return_value = io.BytesIO(json.dumps({"choices": [{"message": {"content": value}}]}).encode())
                with self.assertRaisesRegex(ModelError, "Model returned no text"):
                    self.model.complete([])

    def test_invalid_configuration(self):
        for url, key, model in (
            ("https://", "fake", "test"),
            ("https://user:pass@example.test/v1", "fake", "test"),
            ("https://example.test/v1?q=1", "fake", "test"),
            ("https://example.test/v1#x", "fake", "test"),
            ("http://example.test/v1", "fake", "test"),
            ("https://example.test/v1", "", "test"),
            ("https://example.test/v1", "fake", ""),
        ):
            with self.subTest(url=url, key=bool(key), model=bool(model)), self.assertRaises(ValueError):
                OpenAICompatibleModel(url, key, model)

    def test_local_http_allowed(self):
        for host in ("localhost", "127.0.0.1", "[::1]"):
            with self.subTest(host=host):
                self.assertEqual(OpenAICompatibleModel(f"http://{host}:8080/v1", "fake", "test").url,
                                 f"http://{host}:8080/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
