"""Single-user local transcript storage with isolated conversations."""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Protocol

from .models import Message


class ConversationStore(Protocol):
    def recent(self, limit: int) -> list[Message]: ...
    def append_turn(self, user: str, assistant: str) -> int: ...
    def update_assistant(self, turn_id: int, assistant: str) -> None: ...


class SQLiteConversationStore:
    """A conversation-scoped view over a SQLite transcript database.

    Multiple scoped stores may share one connection. User-level memory tables
    continue to use that same connection and can therefore span conversations,
    while Agent.recent() is always restricted to this store's conversation_id.
    """

    def __init__(
        self,
        path: str | Path = "data/conversations.sqlite3",
        *,
        conversation_id: str = "default",
        connection: sqlite3.Connection | None = None,
    ):
        self._owns_connection = connection is None
        if connection is None:
            if str(path) != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.connection = connection
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=10000")
        if connection is not None and str(path) != ":memory:" and self._owns_connection:
            self.connection.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()
        self.conversation_id = conversation_id
        if self.get_conversation(conversation_id) is None:
            raise ValueError("Unknown conversation")

    def _ensure_schema(self) -> None:
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    archived_at TEXT
                )
            """)
            self.connection.execute("""
                INSERT OR IGNORE INTO conversations(id, title)
                VALUES('default', '默认对话')
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    conversation_id TEXT NOT NULL
                        REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            columns = {
                row[1] for row in self.connection.execute("PRAGMA table_info(turns)")
            }
            if "conversation_id" not in columns:
                # Existing CLI databases are migrated in place. A nullable
                # column is required by SQLite's ALTER TABLE FK rules; all
                # existing and future application writes receive an ID.
                self.connection.execute("""
                    ALTER TABLE turns ADD COLUMN conversation_id TEXT
                    REFERENCES conversations(id) ON DELETE CASCADE
                """)
            self.connection.execute("""
                UPDATE turns SET conversation_id='default'
                WHERE conversation_id IS NULL OR conversation_id=''
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS turns_by_conversation
                ON turns(conversation_id, id)
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS background_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK(kind IN (
                        'long_memory.extract', 'personal_understanding.process'
                    )),
                    source_turn_id INTEGER NOT NULL
                        REFERENCES turns(id) ON DELETE CASCADE,
                    priority INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','running','done','failed','cancelled')),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    available_at REAL NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(kind, source_turn_id)
                )
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS background_jobs_ready
                ON background_jobs(status, available_at, priority DESC, id)
            """)

    @classmethod
    def _from_connection(cls, connection: sqlite3.Connection, conversation_id: str):
        return cls(":memory:", conversation_id=conversation_id, connection=connection)

    def for_conversation(self, conversation_id: str) -> "SQLiteConversationStore":
        return self._from_connection(self.connection, conversation_id)

    def create_conversation(self, title: str = "新对话") -> dict:
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120:
            raise ValueError("Conversation title must contain 1–120 characters")
        conversation_id = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO conversations(id, title) VALUES(?, ?)",
                (conversation_id, title.strip()),
            )
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> dict | None:
        row = self.connection.execute("""
            SELECT c.id, c.title, c.created_at, c.updated_at, c.archived_at,
                   COUNT(t.id) AS message_count, MAX(t.created_at) AS last_message_at
            FROM conversations c
            LEFT JOIN turns t ON t.conversation_id=c.id
            WHERE c.id=?
            GROUP BY c.id
        """, (conversation_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "title": row[1], "created_at": row[2],
            "updated_at": row[3], "archived_at": row[4],
            "message_count": row[5], "last_message_at": row[6],
        }

    def list_conversations(self, *, include_archived: bool = False) -> list[dict]:
        query = """
            SELECT c.id, c.title, c.created_at, c.updated_at, c.archived_at,
                   COUNT(t.id) AS message_count, MAX(t.created_at) AS last_message_at
            FROM conversations c
            LEFT JOIN turns t ON t.conversation_id=c.id
        """
        if not include_archived:
            query += " WHERE c.archived_at IS NULL"
        query += " GROUP BY c.id ORDER BY COALESCE(MAX(t.created_at), c.updated_at) DESC, c.id"
        rows = self.connection.execute(query).fetchall()
        return [{
            "id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3],
            "archived_at": r[4], "message_count": r[5], "last_message_at": r[6],
        } for r in rows]

    def rename_conversation(self, conversation_id: str, title: str) -> dict:
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120:
            raise ValueError("Conversation title must contain 1–120 characters")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE conversations SET title=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (title.strip(), conversation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Unknown conversation")
        return self.get_conversation(conversation_id)

    def archive_conversation(self, conversation_id: str, archived: bool = True) -> dict:
        with self.connection:
            if archived:
                cursor = self.connection.execute(
                    "UPDATE conversations SET archived_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (conversation_id,),
                )
            else:
                cursor = self.connection.execute(
                    "UPDATE conversations SET archived_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (conversation_id,),
                )
            if cursor.rowcount != 1:
                raise ValueError("Unknown conversation")
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> dict:
        if self.get_conversation(conversation_id) is None:
            raise ValueError("Unknown conversation")
        # Explicit turn deletion also handles databases created before the
        # conversation_id FK migration was added. The legacy default container
        # remains as a compatibility anchor for existing CLI installations.
        with self.connection:
            count = self.connection.execute(
                "SELECT COUNT(*) FROM turns WHERE conversation_id=?", (conversation_id,)
            ).fetchone()[0]
            # API receipts contain cached reply data, which may include facts
            # from other conversations. Invalidate them in the same transaction.
            if self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_message_requests'"
            ).fetchone():
                self.connection.execute(
                    "DELETE FROM api_message_requests WHERE conversation_id=?", (conversation_id,)
                )
                self.connection.execute("UPDATE api_message_requests SET response_json=NULL")
            self.connection.execute(
                "DELETE FROM turns WHERE conversation_id=?", (conversation_id,)
            )
            if conversation_id == "default":
                self.connection.execute(
                    """UPDATE conversations
                       SET title='默认对话', archived_at=NULL, updated_at=CURRENT_TIMESTAMP
                       WHERE id='default'"""
                )
                preserved_default = True
            else:
                self.connection.execute(
                    "DELETE FROM conversations WHERE id=?", (conversation_id,)
                )
                preserved_default = False
        return {
            "conversation_id": conversation_id,
            "deleted_turns": count,
            "preserved_default": preserved_default,
        }

    def list_messages(self, *, limit: int = 50, before_id: int | None = None) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("Message limit must be between 1 and 200")
        if before_id is not None and (type(before_id) is not int or before_id < 1):
            raise ValueError("Invalid before_id")
        if before_id is None:
            rows = self.connection.execute("""
                SELECT id, user_text, assistant_text, created_at
                FROM turns WHERE conversation_id=?
                ORDER BY id DESC LIMIT ?
            """, (self.conversation_id, limit)).fetchall()
        else:
            rows = self.connection.execute("""
                SELECT id, user_text, assistant_text, created_at
                FROM turns WHERE conversation_id=? AND id<?
                ORDER BY id DESC LIMIT ?
            """, (self.conversation_id, before_id, limit)).fetchall()
        return [{
            "id": r[0], "user": r[1], "assistant": r[2], "created_at": r[3]
        } for r in reversed(rows)]

    def all_turns(self) -> list[dict]:
        rows = self.connection.execute("""
            SELECT id, conversation_id, user_text, assistant_text, created_at
            FROM turns ORDER BY id
        """).fetchall()
        return [{
            "id": r[0], "conversation_id": r[1], "user": r[2],
            "assistant": r[3], "created_at": r[4],
        } for r in rows]

    def recent(self, limit: int = 12) -> list[Message]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        rows = self.connection.execute(
            """SELECT user_text, assistant_text FROM turns
               WHERE conversation_id=? ORDER BY id DESC LIMIT ?""",
            (self.conversation_id, limit),
        ).fetchall()
        messages: list[Message] = []
        for user, assistant in reversed(rows):
            messages.extend([
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ])
        return messages

    def append_turn(
        self, user: str, assistant: str, *,
        background_jobs: tuple[tuple[str, int], ...] = (),
    ) -> int:
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO turns (user_text, assistant_text, conversation_id)
                   VALUES (?, ?, ?)""",
                (user, assistant, self.conversation_id),
            )
            turn_id = cursor.lastrowid
            self.connection.execute(
                "UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (self.conversation_id,),
            )
            for kind, priority in background_jobs:
                self.connection.execute("""
                    INSERT OR IGNORE INTO background_jobs
                    (kind, source_turn_id, priority)
                    VALUES (?, ?, ?)
                """, (kind, turn_id, priority))
            return turn_id

    def list_background_jobs(
        self, *, limit: int = 50, status: str | None = None,
        source_turn_id: int | None = None,
    ) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("Background job limit must be between 1 and 200")
        if status is not None and status not in {
            "pending", "running", "done", "failed", "cancelled"
        }:
            raise ValueError("Invalid background job status")
        clauses, params = [], []
        if status is not None:
            clauses.append("j.status=?")
            params.append(status)
        if source_turn_id is not None:
            if type(source_turn_id) is not int or source_turn_id < 1:
                raise ValueError("Invalid source turn ID")
            clauses.append("j.source_turn_id=?")
            params.append(source_turn_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.connection.execute(
            """
            SELECT j.id,j.kind,j.source_turn_id,t.conversation_id,j.priority,
                   j.status,j.attempts,j.available_at,j.started_at,j.finished_at,
                   j.last_error,j.created_at,j.updated_at
            FROM background_jobs j
            JOIN turns t ON t.id=j.source_turn_id
            """ + where + " ORDER BY j.id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        fields = (
            "id", "kind", "source_turn_id", "conversation_id", "priority",
            "status", "attempts", "available_at", "started_at", "finished_at",
            "last_error", "created_at", "updated_at",
        )
        return [dict(zip(fields, row)) for row in rows]

    def background_job_counts(self) -> dict[str, dict[str, int]]:
        rows = self.connection.execute("""
            SELECT kind,status,COUNT(*) FROM background_jobs GROUP BY kind,status
        """).fetchall()
        result: dict[str, dict[str, int]] = {}
        for kind, status, count in rows:
            result.setdefault(kind, {})[status] = count
        return result

    def update_assistant(self, turn_id: int, assistant: str) -> None:
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE turns SET assistant_text=?
                   WHERE id=? AND conversation_id=?""",
                (assistant, turn_id, self.conversation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Unknown conversation turn")

    def clear(self) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM turns WHERE conversation_id=?", (self.conversation_id,)
            )

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()
