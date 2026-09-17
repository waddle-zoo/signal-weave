from __future__ import annotations

import hmac
from collections.abc import Iterable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerTokenMiddleware:
    """Protect the HTTP surface with one optional deployment-owned token.

    The health endpoint can remain public for container orchestration. Identity,
    rotation, and secret distribution belong to the deployment environment; this
    middleware is a small defense-in-depth boundary for a self-hosted service.
    """

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        exempt_paths: Iterable[str] = ("/healthz",),
    ) -> None:
        self.app = app
        self.token = token
        self.exempt_paths = frozenset(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        authorization = next(
            (value for key, value in scope.get("headers", []) if key.lower() == b"authorization"),
            b"",
        ).decode("latin-1")
        expected = f"Bearer {self.token}"
        if not hmac.compare_digest(authorization, expected):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
