"""Minimal synchronous agent. The conversation store and model are injected."""
from .models import Message, Model, ModelError
from .memory import ConversationStore
from .prompts import SYSTEM_PROMPT
from .long_memory import LongMemory, MemoryEvent
import sqlite3


_MEMORY_UPDATE_CUES = (
    "请记住", "记住：", "记住:", "帮我记", "记下", "我想更正一下",
    "更正一下我的", "更新我的偏好", "更新你对我的理解",
    "请更新我的记忆", "remember this", "please remember", "update my memory",
)


def _is_explicit_memory_update(text: str) -> bool:
    lowered = text.casefold()
    return any(cue.casefold() in lowered for cue in _MEMORY_UPDATE_CUES)


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
                if self.long_memory.last_extract_rejected:
                    errors.append("extract_partial")
            except (ModelError, sqlite3.Error, ValueError):
                errors.append("extract_failed")
        if self.long_memory is not None and "extract_failed" in errors and _is_explicit_memory_update(text):
            reply += "\n\n不过，这次长期记忆没有成功保存或更新；我不想让你误以为已经记住。"
            try:
                self.store.update_assistant(turn_id, reply)
            except (AttributeError, sqlite3.Error):
                errors.append("transcript_update_failed")
        self.last_memory_event = MemoryEvent(
            tuple(m.id for m in memories), written, tuple(errors),
            self.long_memory.last_search if self.long_memory is not None else None)
        return reply
