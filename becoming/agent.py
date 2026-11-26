"""Minimal synchronous agent. The conversation store and model are injected."""
from .models import Message, Model, ModelError
from .memory import ConversationStore
from .prompts import SYSTEM_PROMPT


class Agent:
    def __init__(self, model: Model, store: ConversationStore, history_turns: int = 12):
        if history_turns < 0:
            raise ValueError("history_turns must be non-negative")
        self.model = model
        self.store = store
        self.history_turns = history_turns

    def reply(self, text: str) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Input cannot be empty")
        messages: list[Message] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.store.recent(self.history_turns),
            {"role": "user", "content": text},
        ]
        reply = self.model.complete(messages)
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("Model returned no text")
        reply = reply.strip()
        # Store completed turns atomically; failed requests do not create orphan turns.
        self.store.append_turn(text, reply)
        return reply
