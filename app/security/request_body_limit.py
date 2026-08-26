"""ASGI request-body size enforcement.

This middleware counts the bytes actually received from the server. It therefore
covers chunked requests and requests with missing or misleading Content-Length
headers, which a header-only guard cannot safely enforce.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


class RequestBodyLimitMiddleware:
    """Buffer and replay HTTP request bodies up to a fixed byte limit."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max(0, int(max_body_bytes))

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") != "http" or self.max_body_bytes <= 0:
            await self.app(scope, receive, send)
            return

        messages: list[ASGIMessage] = []
        received_bytes = 0

        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return

            messages.append(message)
            if message.get("type") != "http.request":
                continue

            received_bytes += len(message.get("body", b""))
            if received_bytes > self.max_body_bytes:
                body = b'{"detail":"Request body too large."}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("ascii")),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

            if not message.get("more_body", False):
                break

        pending = iter(messages)

        async def replay_receive() -> ASGIMessage:
            try:
                return next(pending)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)
