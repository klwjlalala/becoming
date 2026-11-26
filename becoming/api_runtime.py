"""Application runtime shared by the HTTP API routes."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from .growth_agent import GrowthAgent
from .growth_store import GrowthStore
from .long_memory import LongMemory
from .memory import SQLiteConversationStore
from .models import DemoModel, Model, OpenAICompatibleModel
from .personal_understanding import PersonalUnderstanding


class ModelNotConfigured(RuntimeError):
    pass


class AppRuntime:
    """Single-user API runtime.

    The SQLite connection and Agent instances are serialized by the HTTP
    boundary. This is intentionally a single-user desktop backend for V1,
    not a multi-tenant or public network service.
    """

    def __init__(
        self,
        *,
        db_path: str | Path = "data/conversations.sqlite3",
        growth_db_path: str | Path = "data/growth.sqlite3",
        model: Model | None = None,
        model_config: dict[str, str] | None = None,
        enable_long_memory: bool = True,
        enable_personal_understanding: bool = True,
    ):
        if str(db_path) != ":memory:" and str(growth_db_path) != ":memory:":
            if Path(db_path).resolve() == Path(growth_db_path).resolve():
                raise ValueError("Conversation and growth databases must be separate")

        self.lock = threading.RLock()
        self.store = SQLiteConversationStore(db_path)
        try:
            self.growth = GrowthStore(growth_db_path)
        except BaseException:
            self.store.close()
            raise

        self.model_config = dict(model_config or {})
        self.model: Model | None = model
        self.demo = isinstance(model, DemoModel)
        self.enable_long_memory = enable_long_memory
        self.enable_personal_understanding = enable_personal_understanding
        self.agents: dict[str, GrowthAgent] = {}
        self.pending_growth_changes: dict[str, dict] = {}
        self.pending_data_clears: set[str] = set()

    @classmethod
    def from_env(cls) -> "AppRuntime":
        db_path = os.environ.get(
            "BECOMING_API_DB",
            os.environ.get("BECOMING_DB", "data/conversations.sqlite3"),
        )
        growth_db_path = os.environ.get(
            "BECOMING_API_GROWTH_DB",
            os.environ.get("BECOMING_GROWTH_DB", "data/growth.sqlite3"),
        )
        demo = os.environ.get("BECOMING_DEMO", "").casefold() in {"1", "true", "yes"}
        base_url = os.environ.get("BECOMING_BASE_URL", "https://api.openai.com/v1")
        api_key = os.environ.get("BECOMING_API_KEY", "")
        model_name = os.environ.get("BECOMING_MODEL", "")
        config = {"base_url": base_url, "api_key": api_key, "model": model_name}
        model: Model | None
        if demo:
            model = DemoModel()
        elif api_key and model_name:
            model = OpenAICompatibleModel(base_url, api_key, model_name)
        else:
            model = None
        return cls(
            db_path=db_path,
            growth_db_path=growth_db_path,
            model=model,
            model_config=config,
            enable_long_memory=os.environ.get("BECOMING_ENABLE_LONG_MEMORY", "1") != "0",
            enable_personal_understanding=os.environ.get(
                "BECOMING_ENABLE_PERSONAL_UNDERSTANDING", "1"
            ) != "0",
        )

    def model_config_view(self) -> dict[str, Any]:
        return {
            "configured": self.model is not None,
            "demo": self.demo,
            "base_url": self.model_config.get("base_url"),
            "model": self.model_config.get("model"),
            "api_key_configured": self.demo or bool(self.model_config.get("api_key")),
            "api_key": None,
            "persistence": "process_memory_only",
        }

    def configure_model(self, *, base_url: str, api_key: str, model: str) -> dict:
        # Construct first so invalid config never replaces a working model.
        replacement = OpenAICompatibleModel(base_url, api_key, model)
        self.model = replacement
        self.model_config = {
            "base_url": base_url.rstrip("/"),
            "api_key": api_key,
            "model": model,
        }
        self.demo = False
        # Existing agents capture the previous model adapter. Drop them so
        # future requests consistently use the newly configured model.
        self.agents.clear()
        return self.model_config_view()

    def test_model(self, *, base_url: str, api_key: str, model: str) -> None:
        candidate = OpenAICompatibleModel(base_url, api_key, model, timeout=20)
        response = candidate.complete([
            {"role": "system", "content": "Reply with exactly OK."},
            {"role": "user", "content": "Connection test. Reply with exactly OK."},
        ])
        if not response.strip():
            raise ValueError("Model returned an empty response")

    def require_model(self) -> Model:
        if self.model is None:
            raise ModelNotConfigured("Model is not configured")
        return self.model

    def get_agent(self, conversation_id: str) -> GrowthAgent:
        existing = self.agents.get(conversation_id)
        if existing is not None:
            return existing
        model = self.require_model()
        scoped = self.store.for_conversation(conversation_id)
        memory = LongMemory(scoped, model) if self.enable_long_memory else None
        understanding = (
            PersonalUnderstanding(scoped, model)
            if self.enable_personal_understanding else None
        )
        agent = GrowthAgent(
            model,
            scoped,
            self.growth,
            long_memory=memory,
            personal_understanding=understanding,
        )
        self.agents[conversation_id] = agent
        return agent

    def memory_manager(self) -> LongMemory:
        scoped = self.store.for_conversation("default")
        return LongMemory(scoped, self.model or DemoModel())

    def understanding_manager(self) -> PersonalUnderstanding:
        scoped = self.store.for_conversation("default")
        return PersonalUnderstanding(scoped, self.model or DemoModel())

    def close(self) -> None:
        with self.lock:
            self.agents.clear()
            self.growth.close()
            self.store.close()
