"""Versioned HTTP API for the local Becoming companion service."""
from __future__ import annotations

import os
import re
import secrets
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .api_runtime import AppRuntime, ModelNotConfigured
from .growth_store import READ_TOOLS
from .models import ModelError


API_VERSION = "1"


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


class ModelConfigInput(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=200)


class ConversationCreateInput(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=120)


class ConversationUpdateInput(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class ConfirmationInput(BaseModel):
    token: str = Field(min_length=8, max_length=128)


class GrowthChangeInput(BaseModel):
    tool: str = Field(min_length=1, max_length=40)
    args: dict[str, Any]


def _plain(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def create_app(runtime: AppRuntime | None = None) -> FastAPI:
    app = FastAPI(
        title="Becoming API",
        description="Local-first, single-user AI companion backend. No UI is included.",
        version=API_VERSION,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.runtime = runtime or AppRuntime.from_env()
    app.state.owns_runtime = runtime is None

    @app.on_event("shutdown")
    def shutdown_runtime():
        if app.state.owns_runtime:
            app.state.runtime.close()

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Do not echo request bodies: they may contain credentials or private text.
        fields = [str(".".join(str(x) for x in item.get("loc", ()))) for item in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "请求参数不符合接口要求。",
                    "fields": fields,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "服务暂时无法完成请求。",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    def runtime_for(request: Request) -> AppRuntime:
        return request.app.state.runtime

    def require_conversation(rt: AppRuntime, conversation_id: str):
        conversation = rt.store.get_conversation(conversation_id)
        if conversation is None:
            raise APIError(404, "conversation_not_found", "对话不存在。")
        if conversation["archived_at"] is not None:
            raise APIError(409, "conversation_archived", "该对话已归档，不能继续发送消息。")
        return conversation

    def get_agent(rt: AppRuntime, conversation_id: str):
        try:
            return rt.get_agent(conversation_id)
        except ModelNotConfigured:
            raise APIError(503, "model_not_configured", "请先配置并测试模型连接。") from None
        except ValueError:
            raise APIError(404, "conversation_not_found", "对话不存在。") from None

    @app.get("/api/v1/health")
    def health(request: Request):
        rt = runtime_for(request)
        with rt.lock:
            rt.store.connection.execute("SELECT 1").fetchone()
            rt.growth.connection.execute("SELECT 1").fetchone()
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "model_configured": rt.model is not None,
            "database": "ok",
        }

    @app.get("/api/v1/capabilities")
    def capabilities(request: Request):
        rt = runtime_for(request)
        return {
            "conversation_management": True,
            "chat": True,
            "growth_tools": True,
            "long_memory": rt.enable_long_memory,
            "personal_understanding": rt.enable_personal_understanding,
            "data_export": True,
            "data_clear": True,
            "streaming": False,
            "multi_user": False,
        }

    @app.get("/api/v1/model/config")
    def get_model_config(request: Request):
        return runtime_for(request).model_config_view()

    @app.put("/api/v1/model/config")
    def put_model_config(payload: ModelConfigInput, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            try:
                result = rt.configure_model(
                    base_url=payload.base_url,
                    api_key=payload.api_key,
                    model=payload.model,
                )
            except ValueError as exc:
                raise APIError(422, "invalid_model_config", str(exc)) from None
        return result

    @app.post("/api/v1/model/test")
    def test_model(payload: ModelConfigInput, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            try:
                rt.test_model(
                    base_url=payload.base_url,
                    api_key=payload.api_key,
                    model=payload.model,
                )
            except ModelError as exc:
                raise APIError(502, "model_connection_failed", str(exc)) from None
            except ValueError as exc:
                raise APIError(422, "invalid_model_config", str(exc)) from None
        return {"success": True, "model": payload.model}

    @app.get("/api/v1/conversations")
    def list_conversations(
        request: Request,
        include_archived: bool = False,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        rt = runtime_for(request)
        with rt.lock:
            items = rt.store.list_conversations(include_archived=include_archived)
        return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}

    @app.post("/api/v1/conversations", status_code=201)
    def create_conversation(payload: ConversationCreateInput, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            try:
                item = rt.store.create_conversation(payload.title)
            except ValueError as exc:
                raise APIError(422, "invalid_conversation", str(exc)) from None
        return item

    @app.get("/api/v1/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            item = rt.store.get_conversation(conversation_id)
        if item is None:
            raise APIError(404, "conversation_not_found", "对话不存在。")
        return item

    @app.patch("/api/v1/conversations/{conversation_id}")
    def update_conversation(
        conversation_id: str, payload: ConversationUpdateInput, request: Request
    ):
        rt = runtime_for(request)
        changes = payload.dict(exclude_unset=True)
        if not changes:
            raise APIError(422, "empty_update", "至少需要提供一个修改字段。")
        with rt.lock:
            try:
                if "title" in changes and changes["title"] is not None:
                    rt.store.rename_conversation(conversation_id, changes["title"])
                if "archived" in changes and changes["archived"] is not None:
                    rt.store.archive_conversation(conversation_id, changes["archived"])
                item = rt.store.get_conversation(conversation_id)
            except ValueError as exc:
                raise APIError(404, "conversation_not_found", "对话不存在。") from None
        return item

    @app.delete("/api/v1/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            try:
                result = rt.store.delete_conversation(conversation_id)
            except ValueError:
                raise APIError(404, "conversation_not_found", "对话不存在。") from None
            rt.agents.pop(conversation_id, None)
        return {"success": True, **result}

    @app.get("/api/v1/conversations/{conversation_id}/messages")
    def list_messages(
        conversation_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        before_id: int | None = Query(default=None, ge=1),
    ):
        rt = runtime_for(request)
        with rt.lock:
            if rt.store.get_conversation(conversation_id) is None:
                raise APIError(404, "conversation_not_found", "对话不存在。")
            scoped = rt.store.for_conversation(conversation_id)
            items = scoped.list_messages(limit=limit, before_id=before_id)
        return {"items": items, "limit": limit, "before_id": before_id}

    @app.post("/api/v1/conversations/{conversation_id}/messages")
    def send_message(conversation_id: str, payload: MessageInput, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            require_conversation(rt, conversation_id)
            agent = get_agent(rt, conversation_id)
            try:
                answer = agent.reply(payload.content)
            except ModelError as exc:
                raise APIError(502, "model_request_failed", str(exc)) from None
            except ValueError as exc:
                raise APIError(422, "invalid_message", str(exc)) from None

            pending = agent.adapter.pending
            confirmation = None
            if pending is not None:
                token, preview = pending
                confirmation = {"token": token, "preview": preview}
                answer = re.sub(
                    r"\n确认请输入 /confirm [0-9a-f]+；取消请输入 /cancel。$",
                    "",
                    answer,
                )
            scoped = rt.store.for_conversation(conversation_id)
            last = scoped.list_messages(limit=1)
            return {
                "reply": answer,
                "message_id": last[-1]["id"] if last else None,
                "growth_event": _plain(agent.last_event),
                "confirmation_required": confirmation is not None,
                "confirmation": confirmation,
                "memory_event": _plain(agent.last_memory_event),
                "understanding_event": _plain(agent.last_understanding_event),
            }

    @app.post("/api/v1/conversations/{conversation_id}/confirm")
    def confirm_growth(conversation_id: str, payload: ConfirmationInput, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            require_conversation(rt, conversation_id)
            agent = get_agent(rt, conversation_id)
            try:
                answer = agent.reply("/confirm " + payload.token)
            except (ValueError, ModelError):
                raise APIError(409, "confirmation_failed", "该确认请求无法完成。") from None
            return {"reply": answer, "growth_event": _plain(agent.last_event)}

    @app.post("/api/v1/conversations/{conversation_id}/cancel")
    def cancel_growth(conversation_id: str, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            require_conversation(rt, conversation_id)
            agent = get_agent(rt, conversation_id)
            answer = agent.reply("/cancel")
            return {"reply": answer, "growth_event": _plain(agent.last_event)}

    @app.get("/api/v1/growth/goals")
    def list_growth_goals(
        request: Request,
        offset: int = Query(default=0, ge=0),
    ):
        rt = runtime_for(request)
        with rt.lock:
            result = rt.growth.read("list_goals", {"offset": offset})
        return result

    @app.get("/api/v1/growth/goals/{goal_id}")
    def get_growth_goal(goal_id: int, request: Request, offset: int = Query(default=0, ge=0)):
        rt = runtime_for(request)
        with rt.lock:
            try:
                return rt.growth.read("get_goal", {"goal_id": goal_id, "offset": offset})
            except ValueError:
                raise APIError(404, "growth_goal_not_found", "成长目标不存在。") from None

    @app.post("/api/v1/growth/changes", status_code=201)
    def preview_growth_change(payload: GrowthChangeInput, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            try:
                preview = rt.growth.prepare(payload.tool, payload.args)
            except ValueError as exc:
                raise APIError(422, "invalid_growth_change", str(exc)) from None
            token = secrets.token_urlsafe(24)
            rt.pending_growth_changes[token] = preview
        return {"confirmation_required": True, "token": token, "preview": preview}

    @app.post("/api/v1/growth/changes/{token}/confirm")
    def confirm_growth_change(token: str, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            preview = rt.pending_growth_changes.pop(token, None)
            if preview is None:
                raise APIError(409, "confirmation_expired", "确认请求不存在、已使用或已失效。")
            try:
                result = rt.growth.apply(preview)
            except ValueError:
                raise APIError(409, "growth_change_conflict", "数据已变化，请重新生成预览。") from None
        return {"success": True, "result": result}

    @app.post("/api/v1/growth/changes/{token}/cancel")
    def cancel_growth_change(token: str, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            existed = rt.pending_growth_changes.pop(token, None) is not None
        return {"success": True, "cancelled": existed}

    @app.get("/api/v1/memories")
    def list_memories(request: Request):
        rt = runtime_for(request)
        with rt.lock:
            items = rt.memory_manager().list_active()
        return {"items": [_plain(item) for item in items]}

    @app.delete("/api/v1/memories/{key}")
    def forget_memory(key: str, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            try:
                deleted = rt.memory_manager().forget(key)
            except ValueError:
                raise APIError(422, "invalid_memory_key", "记忆槽位名称无效。") from None
        return {"success": True, "deleted_versions": deleted, "blocked_key": key}

    @app.post("/api/v1/memories/{key}/allow")
    def allow_memory(key: str, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            try:
                allowed = rt.memory_manager().allow(key)
            except ValueError:
                raise APIError(422, "invalid_memory_key", "记忆槽位名称无效。") from None
        return {"success": True, "allowed": allowed, "key": key}

    @app.get("/api/v1/understanding/claims")
    def list_understanding_claims(request: Request, limit: int = Query(default=100, ge=1, le=200)):
        rt = runtime_for(request)
        with rt.lock:
            claims = rt.understanding_manager().list_claims(limit=limit)
        return {"items": [_plain(item) for item in claims]}

    @app.get("/api/v1/understanding/claims/{claim_id}")
    def get_understanding_claim(claim_id: str, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            manager = rt.understanding_manager()
            claims = {item.id: item for item in manager.list_claims(limit=200)}
            claim = claims.get(claim_id)
            if claim is None:
                raise APIError(404, "claim_not_found", "个人理解记录不存在。")
            history = manager.get_claim_history(claim_id)
        return {"claim": _plain(claim), "history": history}

    @app.get("/api/v1/data/export")
    def export_data(request: Request):
        rt = runtime_for(request)
        with rt.lock:
            memories = rt.memory_manager().list_active()
            manager = rt.understanding_manager()
            claims = manager.list_claims(limit=200)
            growth_rows = rt.growth.connection.execute(
                "SELECT id, kind, goal_id, text, status, version, created_at, updated_at "
                "FROM growth_items ORDER BY id"
            ).fetchall()
            growth = [dict(row) for row in growth_rows]
            return {
                "format_version": 1,
                "conversations": rt.store.list_conversations(include_archived=True),
                "turns": rt.store.all_turns(),
                "long_memories": [_plain(item) for item in memories],
                "personal_understanding": [
                    {"claim": _plain(item), "history": manager.get_claim_history(item.id)}
                    for item in claims
                ],
                "growth_items": growth,
            }

    @app.post("/api/v1/data/clear")
    def preview_data_clear(request: Request):
        rt = runtime_for(request)
        with rt.lock:
            token = secrets.token_urlsafe(24)
            rt.pending_data_clears.add(token)
            return {
                "confirmation_required": True,
                "token": token,
                "scope": [
                    "所有对话及其来源长期记忆和个人理解",
                    "成长目标、行动和复盘",
                    "记忆槽位的阻止写入设置",
                ],
                "note": "不会删除 SQLite 备份/WAL 文件，也不能删除模型服务端副本。",
            }

    @app.post("/api/v1/data/clear/confirm")
    def confirm_data_clear(payload: ConfirmationInput, request: Request):
        rt = runtime_for(request)
        with rt.lock:
            if payload.token not in rt.pending_data_clears:
                raise APIError(409, "confirmation_expired", "清除确认请求不存在或已失效。")
            rt.pending_data_clears.remove(payload.token)
            with rt.store.connection:
                turn_count = rt.store.connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
                rt.store.connection.execute("DELETE FROM turns")
                rt.store.connection.execute(
                    "DELETE FROM conversations WHERE id <> 'default'"
                )
                rt.store.connection.execute(
                    "UPDATE conversations SET title='默认对话', archived_at=NULL, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id='default'"
                )
                tables = {
                    row[0] for row in rt.store.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "blocked_memory_keys" in tables:
                    rt.store.connection.execute("DELETE FROM blocked_memory_keys")
            growth_counts = rt.growth.clear()
            rt.agents.clear()
            rt.pending_growth_changes.clear()
            rt.pending_data_clears.clear()
        return {
            "success": True,
            "deleted_turns": turn_count,
            "growth": growth_counts,
            "note": "已清除本地业务记录；备份/WAL 文件及模型服务端副本不在此操作范围内。",
        }

    return app


app = create_app()


def run() -> None:
    import uvicorn

    host = os.environ.get("BECOMING_API_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Becoming API V1 may only bind to loopback addresses.")
    port = int(os.environ.get("BECOMING_API_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level="info")
