"""HTTP/SSE adapter for the independent Cyber assistant."""

import json
import asyncio
import re
import secrets
from contextlib import aclosing

import anyio
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.assistant_config import AssistantSettings, get_assistant_settings
from backend.config import get_settings
from backend.models.assistant import AssistantTurnRequest
from backend.services.assistant_loop import Turn, model_client, run_turn
from backend.services.assistant_mcp import CatalogMcp
from backend.services.assistant_store import (
    ConversationNotFound, QuestionLimitReached, SavedTurn, get_assistant_store,
)

router = APIRouter(prefix="/assistant", tags=["assistant"])
COOKIE_NAME = "pwc_assistant_visitor"


def visitor_cookie(request: Request) -> str:
    cookie = request.cookies.get(COOKIE_NAME, "")
    if cookie and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        expected = get_settings().public_site_url or str(request.base_url).rstrip("/")
        if origin != expected or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Please send this request from the catalog page.")
    return cookie if re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie) else secrets.token_urlsafe(32)


def set_visitor_cookie(response, visitor, settings):
    response.set_cookie(COOKIE_NAME, visitor, httponly=True, samesite="lax",
                        secure=get_settings().environment not in {"development", "local", "test"},
                        max_age=settings.retention_days * 86400, path="/api/v1/assistant")


def require_assistant() -> AssistantSettings:
    settings = get_assistant_settings()
    if not settings.enabled:
        raise HTTPException(503, "The assistant is switched off.")
    if not settings.api_key.get_secret_value():
        raise HTTPException(503, "The assistant is not configured yet.")
    return settings


def sse(event: dict) -> str:
    kind = event["type"]
    return f"event: {kind}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


class AssistantStreamResponse(StreamingResponse):
    """Listen for disconnect even while a model is silent (ASGI 2.4 included)."""

    async def __call__(self, scope, receive, send):
        async with anyio.create_task_group() as group:
            async def stream():
                try:
                    await self.stream_response(send)
                except OSError:
                    pass  # ASGI server reports a disconnected socket.
                finally:
                    with anyio.CancelScope(shield=True):
                        await self.body_iterator.aclose()
                    group.cancel_scope.cancel()

            async def disconnected():
                await self.listen_for_disconnect(receive)
                group.cancel_scope.cancel()

            group.start_soon(stream)
            group.start_soon(disconnected)
        if self.background:
            await self.background()


async def turn_events(payload: AssistantTurnRequest, settings: AssistantSettings, saved: SavedTurn, store):
    turn = Turn()
    try:
        yield sse({"type": "meta", **saved.metadata()})
        async with model_client(settings) as client, httpx.AsyncClient() as http:
            events = run_turn(client, CatalogMcp(http, settings.mcp_url), settings.model, saved.history, turn)
            async with aclosing(events):
                async for event in events:
                    if event["type"] in {"done", "error"}:
                        event = {**event, **saved.metadata()}
                    yield sse(event)
    except (asyncio.CancelledError, GeneratorExit):
        turn.status = "cancelled"
        raise
    finally:
        if turn.status == "running":
            turn.status = "failed"
        # Disconnect cancellation must not interrupt the short save transaction.
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(store.finish, saved, turn)


@router.post("/turn")
async def post_turn(payload: AssistantTurnRequest, settings=Depends(require_assistant),
                    visitor=Depends(visitor_cookie), store=Depends(get_assistant_store)):
    try:
        saved = await run_in_threadpool(store.begin, visitor,
                                       str(payload.conversation_id) if payload.conversation_id else None,
                                       payload.question)
    except ConversationNotFound:
        raise HTTPException(404, "Chat not found.") from None
    except QuestionLimitReached:
        raise HTTPException(409, {"code": "question_limit", "message": "This chat has reached 10 questions. Start a new chat.",
                                  "question_count": 10, "question_limit": 10}) from None
    response = AssistantStreamResponse(
        turn_events(payload, settings, saved, store), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
    set_visitor_cookie(response, visitor, settings)
    return response
