"""HTTP/SSE adapter for the independent Cyber assistant."""

import json
from contextlib import aclosing

import anyio
import httpx
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from backend.assistant_config import AssistantSettings, get_assistant_settings
from backend.models.assistant import AssistantTurnRequest
from backend.services.assistant_loop import Turn, model_client, run_turn
from backend.services.assistant_mcp import CatalogMcp

router = APIRouter(prefix="/assistant", tags=["assistant"])


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
                    group.cancel_scope.cancel()

            async def disconnected():
                await self.listen_for_disconnect(receive)
                group.cancel_scope.cancel()

            group.start_soon(stream)
            group.start_soon(disconnected)
        if self.background:
            await self.background()


async def turn_events(payload: AssistantTurnRequest, settings: AssistantSettings):
    turn = Turn()
    async with model_client(settings) as client, httpx.AsyncClient() as http:
        events = run_turn(client, CatalogMcp(http, settings.mcp_url), settings.model,
                          [{"role": "user", "content": payload.question}], turn)
        async with aclosing(events):
            async for event in events:
                yield sse(event)


@router.post("/turn")
async def post_turn(payload: AssistantTurnRequest, settings=Depends(require_assistant)):
    return AssistantStreamResponse(
        turn_events(payload, settings), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
