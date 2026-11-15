"""HTTP/SSE adapter for the independent Cyber assistant."""

import json
import asyncio
import re
import secrets
import logging
import time
from uuid import UUID
from contextlib import aclosing

import anyio
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse
from starlette.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from backend.assistant_config import AssistantSettings, get_assistant_settings
from backend.config import get_settings
from backend.models.assistant import AssistantTurnRequest, AssistantFeedbackRequest, AssistantRenameRequest
from backend.services.assistant_loop import Turn, model_client, run_turn
from backend.services.assistant_mcp import CatalogMcp
from backend.services.assistant_store import (
    ConversationNotFound, QuestionLimitReached, SavedTurn, get_assistant_store,
)
from backend.services.assistant_provider import quota_reset, safe_provider_message

router = APIRouter(prefix="/assistant", tags=["assistant"])
COOKIE_NAME = "pwc_assistant_visitor"
logger = logging.getLogger(__name__)


def visitor_cookie(request: Request) -> str:
    cookie = request.cookies.get(COOKIE_NAME, "")
    if cookie and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        expected = get_settings().public_site_url
        if not expected:
            # Match the existing nginx header trust in auth._origin_from_request;
            # keep the request Host and accept only an HTTP(S) forwarded scheme.
            proto = request.headers.get("x-forwarded-proto", "")
            scheme = proto if proto in {"http", "https"} else request.url.scheme
            expected = str(request.base_url.replace(scheme=scheme)).rstrip("/")
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
    began = time.monotonic()
    finalized = False
    async def record(step):
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(store.record_step, saved, len(turn.steps) - 1, step)
    async def provider_limit(error):
        # Persist the cooldown even if the browser disconnects at this point.
        with anyio.CancelScope(shield=True):
            reset = await quota_reset(error, settings)
            return await run_in_threadpool(store.record_provider_limit,
                safe_provider_message(error, settings.api_key.get_secret_value()), reset)
    try:
        yield sse({"type": "meta", **saved.metadata()})
        async with model_client(settings) as client, httpx.AsyncClient() as http:
            events = run_turn(client, CatalogMcp(http, settings.mcp_url), settings.model, saved.history, turn,
                              on_step=record, on_provider_limit=provider_limit)
            async with aclosing(events):
                async for event in events:
                    if event["type"] in {"done", "error"}:
                        # Commit before announcing completion: the browser may
                        # close the SSE connection as soon as it sees this event.
                        with anyio.CancelScope(shield=True):
                            await run_in_threadpool(store.finish, saved, turn)
                        finalized = True
                        event = {**event, **saved.metadata()}
                    yield sse(event)
    except (asyncio.CancelledError, GeneratorExit):
        if not finalized:
            turn.status = "cancelled"
        raise
    finally:
        if turn.status == "running":
            turn.status = "failed"
        # Disconnect cancellation must not interrupt the short save transaction.
        if not finalized:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(store.finish, saved, turn)
        logger.info("assistant_run id=%s status=%s model_steps=%d tool_steps=%d duration_ms=%d",
                    saved.run_id, turn.status,
                    sum(s["kind"] == "model" for s in turn.steps),
                    sum(s["kind"] == "tool" for s in turn.steps),
                    round((time.monotonic() - began) * 1000))


@router.post("/turn")
async def post_turn(payload: AssistantTurnRequest, settings=Depends(require_assistant),
                    visitor=Depends(visitor_cookie), store=Depends(get_assistant_store)):
    status = await run_in_threadpool(store.provider_status)
    if not status["available"]:
        raise HTTPException(503, status)
    try:
        saved = await run_in_threadpool(store.begin, visitor,
                                       str(payload.conversation_id) if payload.conversation_id else None,
                                       payload.question, model=settings.model, surface=payload.surface,
                                       site_path=payload.site_path,
                                       analytics_session_id=str(payload.analytics_session_id)
                                       if settings.store_analytics_session and payload.analytics_session_id else None)
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


@router.get("/status")
def status(store=Depends(get_assistant_store)):
    settings = get_assistant_settings()
    if not settings.enabled:
        result = {"available": False, "code": "disabled", "reason": "The assistant is switched off.", "retry_at": None}
    elif not settings.api_key.get_secret_value():
        raise HTTPException(503, "The assistant is not configured yet.")
    else:
        result = store.provider_status()
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/runs/{run_id}/feedback")
def feedback(run_id: UUID, payload: AssistantFeedbackRequest, settings=Depends(require_assistant),
             visitor=Depends(visitor_cookie), store=Depends(get_assistant_store)):
    try:
        store.feedback(visitor, str(run_id), payload.rating, payload.note)
    except ConversationNotFound:
        raise HTTPException(404, "Answer not found.") from None
    return {"saved": True}


def private_response(value, visitor, settings):
    response = JSONResponse(value, headers={"Cache-Control": "no-store"})
    set_visitor_cookie(response, visitor, settings)
    return response


@router.get("/conversations")
def conversations(settings=Depends(require_assistant), visitor=Depends(visitor_cookie), store=Depends(get_assistant_store)):
    return private_response(store.list_conversations(visitor), visitor, settings)


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: UUID, settings=Depends(require_assistant),
                 visitor=Depends(visitor_cookie), store=Depends(get_assistant_store)):
    try:
        result = store.get_conversation(visitor, str(conversation_id))
    except ConversationNotFound:
        raise HTTPException(404, "Chat not found.") from None
    return private_response(result, visitor, settings)


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: UUID, payload: AssistantRenameRequest, settings=Depends(require_assistant),
                        visitor=Depends(visitor_cookie), store=Depends(get_assistant_store)):
    try:
        result = store.rename(visitor, str(conversation_id), payload.title)
    except ConversationNotFound:
        raise HTTPException(404, "Chat not found.") from None
    return private_response(result, visitor, settings)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, settings=Depends(require_assistant),
                        visitor=Depends(visitor_cookie), store=Depends(get_assistant_store)):
    try:
        store.delete_conversation(visitor, str(conversation_id))
    except ConversationNotFound:
        raise HTTPException(404, "Chat not found.") from None
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
