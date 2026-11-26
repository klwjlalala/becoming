"""Model boundary; no agent or persistence logic belongs here."""
from __future__ import annotations

import json
from typing import Protocol, TypedDict, Literal, Sequence
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class Model(Protocol):
    def complete(self, messages: Sequence[Message]) -> str: ...


class ModelError(RuntimeError):
    pass


class DemoModel:
    def complete(self, messages: Sequence[Message]) -> str:
        return "【模拟模型】对话链路运行正常；配置真实模型后即可进行自然交流。"


class OpenAICompatibleModel:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Use HTTPS, or HTTP on loopback for local models")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid model base URL")
        if not api_key or not model:
            raise ValueError("API key and model are required")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, messages: Sequence[Message]) -> str:
        request = Request(
            self.url,
            data=json.dumps({"model": self.model, "messages": list(messages)},
                            ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.api_key,
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
            reply = payload["choices"][0]["message"]["content"]
        except HTTPError as exc:
            raise ModelError(f"Model request failed (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError):
            raise ModelError("Model connection failed") from None
        except (ValueError, TypeError, KeyError, IndexError):
            raise ModelError("Invalid model response") from None
        if not isinstance(reply, str) or not reply.strip():
            raise ModelError("Model returned no text")
        return reply.strip()
