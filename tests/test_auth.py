from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from semantic_monitor.auth import BearerTokenMiddleware


async def ok(request):
    return JSONResponse({"ok": True})


def make_app():
    app = Starlette(routes=[Route("/healthz", ok), Route("/private", ok)])
    app.add_middleware(BearerTokenMiddleware, token="local-test-token")
    return app


def test_bearer_token_protects_http_surface_but_keeps_health_public():
    with TestClient(make_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/private").status_code == 401
        response = client.get(
            "/private", headers={"authorization": "Bearer local-test-token"}
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
