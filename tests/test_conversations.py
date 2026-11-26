import sqlite3
import tempfile
import unittest
from pathlib import Path

from becoming.memory import SQLiteConversationStore


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "conversations.sqlite3"
        self.store = SQLiteConversationStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_recent_history_is_scoped_to_conversation(self):
        first = self.store.append_turn("第一条私聊", "第一条回复")
        other = self.store.create_conversation("另一个主题")
        second_store = self.store.for_conversation(other["id"])
        self.addCleanup(second_store.close)

        second_store.append_turn("第二个会话的内容", "第二个会话的回复")
        self.assertEqual(
            self.store.recent(10),
            [
                {"role": "user", "content": "第一条私聊"},
                {"role": "assistant", "content": "第一条回复"},
            ],
        )
        self.assertEqual(
            second_store.recent(10),
            [
                {"role": "user", "content": "第二个会话的内容"},
                {"role": "assistant", "content": "第二个会话的回复"},
            ],
        )
        self.assertNotEqual(first, second_store.list_messages()[0]["id"])

    def test_conversation_metadata_crud_and_pagination(self):
        conversation = self.store.create_conversation("测试会话")
        scoped = self.store.for_conversation(conversation["id"])
        self.addCleanup(scoped.close)
        scoped.append_turn("one", "reply one")
        scoped.append_turn("two", "reply two")

        renamed = self.store.rename_conversation(conversation["id"], "已重命名")
        self.assertEqual(renamed["title"], "已重命名")
        self.assertEqual(renamed["message_count"], 2)
        self.assertEqual([x["user"] for x in scoped.list_messages(limit=1)], ["two"])
        self.assertEqual(len(scoped.list_messages(limit=1, before_id=2)), 1)

        archived = self.store.archive_conversation(conversation["id"])
        self.assertIsNotNone(archived["archived_at"])
        self.assertNotIn(conversation["id"], [x["id"] for x in self.store.list_conversations()])
        self.store.archive_conversation(conversation["id"], archived=False)
        self.assertIn(conversation["id"], [x["id"] for x in self.store.list_conversations()])

    def test_delete_conversation_removes_only_its_turns(self):
        other = self.store.create_conversation("保留")
        scoped = self.store.for_conversation(other["id"])
        self.addCleanup(scoped.close)
        self.store.append_turn("default 保留", "ok")
        scoped.append_turn("待删除", "ok")

        result = self.store.delete_conversation(other["id"])
        self.assertEqual(result["deleted_turns"], 1)
        self.assertEqual([x["user"] for x in self.store.list_messages()], ["default 保留"])
        self.assertIsNone(self.store.get_conversation(other["id"]))

    def test_existing_cli_database_migrates_into_default_conversation(self):
        self.store.close()
        with sqlite3.connect(self.path) as connection:
            connection.execute("""
                CREATE TABLE turns (
                    id INTEGER PRIMARY KEY,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute(
                "INSERT INTO turns(user_text, assistant_text) VALUES(?, ?)",
                ("旧 CLI 消息", "旧 CLI 回复"),
            )

        migrated = SQLiteConversationStore(self.path)
        self.addCleanup(migrated.close)
        self.assertEqual(
            migrated.recent(10),
            [
                {"role": "user", "content": "旧 CLI 消息"},
                {"role": "assistant", "content": "旧 CLI 回复"},
            ],
        )
        self.assertEqual(migrated.list_conversations()[0]["id"], "default")
        self.assertEqual(migrated.list_messages()[0]["user"], "旧 CLI 消息")


if __name__ == "__main__":
    unittest.main()
