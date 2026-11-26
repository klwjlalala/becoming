"""Minimal synchronous agent. The conversation store and model are injected."""
from .models import Message, Model, ModelError
from .memory import ConversationStore
from .prompts import SYSTEM_PROMPT
from .long_memory import LongMemory, MemoryEvent
import sqlite3


class Agent:
    def __init__(self, model: Model, store: ConversationStore, history_turns: int = 12,
                 long_memory: LongMemory | None = None):
        if history_turns < 0:
            raise ValueError("history_turns must be non-negative")
        self.model = model
        self.store = store
        self.history_turns = history_turns
        if long_memory is not None and long_memory.store is not store:
            raise ValueError("Memory and agent must share the transcript store")
        self.long_memory = long_memory
        self.last_memory_event = MemoryEvent()

    def reply(self, text: str) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Input cannot be empty")
        self.last_memory_event = MemoryEvent()
        memories = []
        errors = []
        if self.long_memory is not None:
            try:
                memories = self.long_memory.retrieve(text)
            except (ModelError, sqlite3.Error, ValueError):
                errors.append("retrieve_failed")
        system = SYSTEM_PROMPT
        if memories:
            system += "\n" + self.long_memory.context(memories)
        messages: list[Message] = [
            {"role": "system", "content": system},
            *self.store.recent(self.history_turns),
            {"role": "user", "content": text},
        ]
        reply = self.model.complete(messages)
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("Model returned no text")
        reply = reply.strip()
        # Store completed turns atomically; failed requests do not create orphan turns.
        turn_id = self.store.append_turn(text, reply)
        written = ()
        if self.long_memory is not None:
            try:
                written = self.long_memory.extract(turn_id, text)
            except (ModelError, sqlite3.Error, ValueError):
                errors.append("extract_failed")
        self.last_memory_event = MemoryEvent(
            tuple(m.id for m in memories), written, tuple(errors),
            self.long_memory.last_search if self.long_memory is not None else None)
        return reply
