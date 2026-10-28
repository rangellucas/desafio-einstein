"""Cancelamento da consulta e propriedade dos recursos de uma resposta SSE."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import AsyncExitStack
from typing import Any, TypeVar

from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.requests import ClientDisconnect
from starlette.types import Message, Receive, Scope, Send

from app.schemas import ErrorDetail

T = TypeVar("T")
logger = logging.getLogger(__name__)


async def close_after_failure(resources: AsyncExitStack) -> None:
    """Preserva o erro principal; ExitStack libera a vaga mesmo se close falhar."""
    try:
        await resources.aclose()
    except Exception:
        logger.warning("query_cleanup_failed")


def sse_event(name: str, payload: BaseModel) -> str:
    # JSON escapa quebras de linha/aspas sem permitir injeção de campos SSE.
    return f"event: {name}\ndata: {payload.model_dump_json()}\n\n"


async def run_connected(request: Request, operation: Coroutine[Any, Any, T]) -> T:
    """Depois da leitura do corpo, há um único leitor de http.disconnect por fase."""
    async def disconnected() -> None:
        while (await request.receive())["type"] != "http.disconnect":
            pass

    work = asyncio.create_task(operation)
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((work, watcher), return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            watcher.result()
            raise ClientDisconnect()
        return work.result()
    finally:
        # Cancelar e aguardar evita tarefas órfãs e geração após a desconexão.
        for task in (work, watcher):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, watcher, return_exceptions=True)


class QueryStreamingResponse(StreamingResponse):
    """StreamingResponse com fechamento garantido, inclusive durante send e ASGI 2.4.

    A classe é necessária porque o stream foi aberto antes dos cabeçalhos e o
    gerador pode nem começar a ser iterado. BackgroundTask não cobre toda falha.
    """

    media_type = "text/event-stream"

    def __init__(
        self, content: AsyncGenerator[str, None], resources: AsyncExitStack, deadline: float,
        error_detail: Callable[[Exception], ErrorDetail],
    ) -> None:
        super().__init__(content, media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })
        self.resources = resources
        self.events = content
        self.deadline = deadline
        self.error_detail = error_detail

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = False
        terminal_sent = False

        async def tracked_send(message: Message) -> None:
            nonlocal started, terminal_sent
            try:
                await send(message)
            except OSError:
                raise ClientDisconnect() from None
            if message["type"] == "http.response.start":
                started = True
            if message["type"] == "http.response.body" and message.get("body", b"").startswith(b"event: done\n"):
                terminal_sent = True

        async def deliver() -> None:
            try:
                # Mesmo prazo absoluto usado na recuperação: não reinicia no SSE.
                # Abrange também backpressure enquanto send aguarda o consumidor.
                async with asyncio.timeout_at(self.deadline):
                    await self.stream_response(tracked_send)
            except ClientDisconnect:
                raise
            except Exception as error:
                if not started:
                    raise
                await close_after_failure(self.resources)
                if not terminal_sent:
                    data = sse_event("error", self.error_detail(error)).encode()
                    await send({"type": "http.response.body", "body": data, "more_body": True})
                await send({"type": "http.response.body", "body": b"", "more_body": False})

        try:
            await run_connected(Request(scope, receive), deliver())
        except (ClientDisconnect, OSError):
            # O consumidor já saiu; não há conexão para receber evento terminal.
            logger.info("query_disconnected request_id=%s route=%s", scope.get("state", {}).get("request_id"), scope.get("path"))
        finally:
            try:
                await self.events.aclose()
            finally:
                await close_after_failure(self.resources)
