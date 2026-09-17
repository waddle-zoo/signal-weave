import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from semantic_monitor.auth import BearerTokenMiddleware


async def ok(request):
    return JSONResponse({"ok": True})


def make_app():
    app = Starlette(routes=[Route("/healthz", ok), Route("/private", ok)])
    app.add_middleware(BearerTokenMiddleware, token="local-test-token")
    return app


@pytest.mark.asyncio
async def test_bearer_token_protects_http_surface_but_keeps_health_public():
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/private")).status_code == 401
        response = await client.get(
            "/private", headers={"authorization": "Bearer local-test-token"}
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
