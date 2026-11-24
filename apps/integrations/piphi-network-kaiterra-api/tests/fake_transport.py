from __future__ import annotations

from collections import deque

import httpx


class ScriptedTransport(httpx.AsyncBaseTransport):
    """Deterministic provider simulator; it never opens a network socket."""

    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = deque(responses)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected simulated Kaiterra request")
        result = self.responses.popleft()
        if isinstance(result, Exception):
            raise result
        result.request = request
        return result
