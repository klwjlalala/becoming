"""Single-user local transcript storage. No inferred user profile."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol
from .models import Message


class ConversationStore(Protocol):
    def recent(self, limit: int) -> list[Message]: ...
    def append_turn(self, user: str, assistant: str) -> None: ...


class SQLiteConversationStore:
    def __init__(self, path: str | Path = "data/conversations.sqlite3"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def recent(self, limit: int = 12) -> list[Message]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        rows = self.connection.execute(
            "SELECT user_text, assistant_text FROM turns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        messages: list[Message] = []
        for user, assistant in reversed(rows):
            messages.extend([{"role": "user", "content": user},
                             {"role": "assistant", "content": assistant}])
        return messages

    def append_turn(self, user: str, assistant: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO turns (user_text, assistant_text) VALUES (?, ?)",
                (user, assistant),
            )

    def clear(self) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM turns")

    def close(self) -> None:
        self.connection.close()
