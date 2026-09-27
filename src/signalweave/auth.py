from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from mcp.server.auth.provider import AccessToken
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .models import PrincipalContext


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


def _claim(payload: dict[str, Any], path: str) -> Any:
    """Read a simple dotted claim path without allowing arbitrary expressions."""

    value: Any = payload
    for part in path.split("."):
        if not part or not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _validate_oidc_url(name: str, value: str) -> None:
    """Validate configured or discovered OIDC URLs before making a request."""

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        # ``urlsplit().hostname`` alone does not validate malformed ports.
        # Force parsing before OIDC discovery or JWKS retrieval.
        _validated_port = parsed.port
    except ValueError as error:
        raise RuntimeError(f"{name} must be a valid URL") from error
    insecure_allowed = os.getenv("SIGNALWEAVE_ALLOW_INSECURE_OIDC") == "1"
    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    local_http_allowed = (
        parsed.scheme == "http" and insecure_allowed and hostname in loopback_hosts
    )
    if parsed.scheme != "https" and not local_http_allowed:
        if parsed.scheme == "http" and insecure_allowed and hostname not in loopback_hosts:
            raise RuntimeError(
                f"{name} may use http only on a loopback host for an isolated local test"
            )
        raise RuntimeError(
            f"{name} must use https; set SIGNALWEAVE_ALLOW_INSECURE_OIDC=1 "
            "only for an isolated local test"
        )
    if (
        not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(f"{name} must be a URL without credentials, query, or fragment")


@dataclass(frozen=True)
class OIDCSettings:
    """Small, deployment-owned configuration for signed OIDC access tokens."""

    issuer_url: str
    audience: str
    jwks_url: str | None = None
    tenant_claim: str = "tenant_id"
    principal_claim: str = "sub"
    scope_claim: str = "scope"
    jwks_ttl_seconds: int = 300
    algorithms: tuple[str, ...] = ("RS256",)

    @classmethod
    def from_env(cls) -> OIDCSettings:
        # Preserve the issuer exactly for JWT validation. OIDC issuers may
        # legitimately end in '/', while discovery URLs need a normalized join.
        issuer = os.getenv("SIGNALWEAVE_OIDC_ISSUER_URL", "").strip()
        audience = os.getenv("SIGNALWEAVE_OIDC_AUDIENCE", "").strip()
        if not issuer or not audience:
            raise RuntimeError(
                "OIDC mode requires SIGNALWEAVE_OIDC_ISSUER_URL and "
                "SIGNALWEAVE_OIDC_AUDIENCE"
            )
        _validate_oidc_url("OIDC issuer", issuer)
        jwks_url = (os.getenv("SIGNALWEAVE_OIDC_JWKS_URL") or "").strip() or None
        if jwks_url:
            _validate_oidc_url("OIDC JWKS URL", jwks_url)
        algorithms = tuple(
            item.strip()
            for item in os.getenv("SIGNALWEAVE_OIDC_ALGORITHMS", "RS256").split(",")
            if item.strip()
        )
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
        if not algorithms or any(item not in allowed for item in algorithms):
            raise RuntimeError(
                "SIGNALWEAVE_OIDC_ALGORITHMS must contain only approved asymmetric algorithms"
            )
        try:
            ttl = int(os.getenv("SIGNALWEAVE_OIDC_JWKS_TTL_SECONDS", "300"))
        except ValueError as error:
            raise RuntimeError("SIGNALWEAVE_OIDC_JWKS_TTL_SECONDS must be an integer") from error
        if not 30 <= ttl <= 86400:
            raise RuntimeError("SIGNALWEAVE_OIDC_JWKS_TTL_SECONDS must be between 30 and 86400")
        claim_paths = {
            "SIGNALWEAVE_OIDC_TENANT_CLAIM": os.getenv(
                "SIGNALWEAVE_OIDC_TENANT_CLAIM", "tenant_id"
            ),
            "SIGNALWEAVE_OIDC_PRINCIPAL_CLAIM": os.getenv(
                "SIGNALWEAVE_OIDC_PRINCIPAL_CLAIM", "sub"
            ),
            "SIGNALWEAVE_OIDC_SCOPE_CLAIM": os.getenv(
                "SIGNALWEAVE_OIDC_SCOPE_CLAIM", "scope"
            ),
        }
        for name, claim_path in claim_paths.items():
            if not claim_path.strip() or any(not part.strip() for part in claim_path.split(".")):
                raise RuntimeError(f"{name} must be a non-empty dotted claim path")
        return cls(
            issuer_url=issuer,
            audience=audience,
            jwks_url=jwks_url,
            tenant_claim=claim_paths["SIGNALWEAVE_OIDC_TENANT_CLAIM"],
            principal_claim=claim_paths["SIGNALWEAVE_OIDC_PRINCIPAL_CLAIM"],
            scope_claim=claim_paths["SIGNALWEAVE_OIDC_SCOPE_CLAIM"],
            jwks_ttl_seconds=ttl,
            algorithms=algorithms,
        )


class OIDCJWTVerifier:
    """Validate signed OIDC JWTs for MCP's native bearer-auth stack.

    This verifier deliberately does not infer tenant identity from email, issuer,
    or audience. A deployment must configure an explicit tenant claim, and the
    MCP principal resolver rejects tokens that do not carry it.
    """

    def __init__(
        self,
        settings: OIDCSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._http = http_client or httpx.AsyncClient(timeout=5.0)
        self._jwks_uri = settings.jwks_url
        self._keys: dict[str, Any] = {}
        self._jwks_expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _load_keys(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._keys and now < self._jwks_expires_at:
            return self._keys
        async with self._lock:
            now = time.monotonic()
            if not force and self._keys and now < self._jwks_expires_at:
                return self._keys
            _validate_oidc_url("OIDC issuer", self.settings.issuer_url)
            if not self._jwks_uri:
                response = await self._http.get(
                    f"{self.settings.issuer_url.rstrip('/')}/.well-known/openid-configuration"
                )
                response.raise_for_status()
                metadata = response.json()
                if not isinstance(metadata, dict):
                    raise RuntimeError("OIDC discovery response was not a JSON object")
                discovered_jwks_uri = metadata.get("jwks_uri")
                if not isinstance(discovered_jwks_uri, str) or not discovered_jwks_uri.strip():
                    raise RuntimeError("OIDC discovery did not provide jwks_uri")
                self._jwks_uri = discovered_jwks_uri.strip()
                _validate_oidc_url("OIDC discovery jwks_uri", self._jwks_uri)
            else:
                _validate_oidc_url("OIDC JWKS URL", self._jwks_uri)
            if not isinstance(self._jwks_uri, str) or not self._jwks_uri:
                raise RuntimeError("OIDC discovery did not provide jwks_uri")
            response = await self._http.get(self._jwks_uri)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("OIDC JWKS response was not a JSON object")
            raw_keys = payload.get("keys")
            if not isinstance(raw_keys, list) or not raw_keys:
                raise RuntimeError("OIDC JWKS response did not contain keys")
            keys: dict[str, Any] = {}
            for raw_key in raw_keys:
                if not isinstance(raw_key, dict) or not raw_key.get("kid"):
                    continue
                algorithm = raw_key.get("alg") or {
                    "RSA": "RS256",
                    "EC": "ES256",
                }.get(str(raw_key.get("kty")))
                if algorithm not in self.settings.algorithms:
                    continue
                keys[str(raw_key["kid"])] = jwt.algorithms.get_default_algorithms()[algorithm].from_jwk(
                    json.dumps(raw_key)
                )
            if not keys:
                raise RuntimeError("OIDC JWKS contained no approved signing keys")
            self._keys = keys
            self._jwks_expires_at = time.monotonic() + self.settings.jwks_ttl_seconds
            return keys

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if algorithm not in self.settings.algorithms or not kid:
                return None
            keys = await self._load_keys()
            key = keys.get(str(kid))
            if key is None:
                keys = await self._load_keys(force=True)
                key = keys.get(str(kid))
            if key is None:
                return None
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self.settings.algorithms),
                audience=self.settings.audience,
                issuer=self.settings.issuer_url,
                options={"require": ["exp", "iss", "sub"]},
            )
            if not isinstance(claims, dict):
                return None
            scopes = _claim(claims, self.settings.scope_claim)
            if isinstance(scopes, str):
                scope_values = scopes.split()
            elif isinstance(scopes, list):
                scope_values = [str(scope) for scope in scopes]
            else:
                scope_values = []
            audience = claims.get("aud")
            resource = (
                audience
                if isinstance(audience, str)
                else self.settings.audience
                if self.settings.audience in (audience or [])
                else None
            )
            principal = _claim(claims, self.settings.principal_claim)
            if not isinstance(principal, str) or not principal.strip():
                return None
            return AccessToken(
                token=token,
                client_id=str(claims.get("azp") or claims.get("client_id") or principal),
                scopes=scope_values,
                expires_at=int(claims["exp"]),
                resource=resource,
                subject=principal,
                claims=claims,
            )
        except (
            httpx.HTTPError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
            jwt.InvalidTokenError,
        ):
            return None


def principal_from_access_token(
    access_token: AccessToken | None,
    *,
    tenant_claim: str = "tenant_id",
    authorization_source: str = "oidc",
    required_scopes: Iterable[str] = (),
) -> PrincipalContext:
    """Convert a verified MCP token into the tenant-scoped SignalWeave principal."""

    if access_token is None:
        raise RuntimeError("the MCP request has no authenticated access token")
    missing_scopes = set(required_scopes) - set(access_token.scopes)
    if missing_scopes:
        raise RuntimeError(
            "authenticated token is missing required scopes: "
            + ", ".join(sorted(missing_scopes))
        )
    claims = access_token.claims or {}
    tenant = _claim(claims, tenant_claim)
    if not isinstance(tenant, str) or not tenant.strip():
        raise RuntimeError(f"authenticated token is missing required tenant claim: {tenant_claim}")
    subject = access_token.subject or access_token.client_id
    return PrincipalContext(
        principal_id=subject,
        tenant_id=tenant,
        scopes=list(access_token.scopes),
        authorization_source=authorization_source,
    )
