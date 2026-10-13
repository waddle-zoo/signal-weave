"""Local Sign in with ChatGPT OAuth for the open-source Responses API path.

This intentionally does not read or reuse Codex CLI credentials. Users grant
SignalWeave its own scoped access in the system browser, and tokens remain in
the owner-only SignalWeave home.
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import http.server
import json
import os
import re
import secrets
import time
import urllib.parse
import uuid
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import jwt

from .local_setup import (
    SetupError,
    _private_directory,
    _private_path,
    _publish_secret,
    _read_private,
    resolve_home,
)

AUTH_FILE = "chatgpt-auth.json"
HOST_FILE = "chatgpt-host.json"
AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
ISSUER = "https://auth.openai.com"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
CALLBACK_PATH = "/auth/callback"
_DIAGNOSTIC_TOKEN = re.compile(r"[A-Za-z0-9_.:/-]{1,120}\Z")
_UNUSABLE_REFRESH_CODES = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}


def _safe_diagnostic(value: Any) -> str | None:
    if isinstance(value, str) and _DIAGNOSTIC_TOKEN.fullmatch(value):
        return value
    return None


def _oauth_error_details(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = _safe_diagnostic(error.get("code") or error.get("error"))
    else:
        code = _safe_diagnostic(error)
    request_id = _safe_diagnostic(
        response.headers.get("openai-request-id") or response.headers.get("x-request-id")
    )
    return code, request_id


def _oauth_failure_summary(response: httpx.Response) -> str:
    code, request_id = _oauth_error_details(response)
    details = [f"HTTP {response.status_code}"]
    if code:
        details.append(f"code={code}")
    if request_id:
        details.append(f"request_id={request_id}")
    return "; ".join(details)


def _mark_reauth_required(path: Path, record: dict[str, Any]) -> None:
    for field in ("access_token", "refresh_token", "expires_at"):
        record.pop(field, None)
    record["reauth_required"] = True
    _write_private_json(path, record)


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    _publish_secret(path, encoded)


def _auth_path(home: str | Path | None = None) -> tuple[Path, Path]:
    root = resolve_home(home)
    _private_directory(root)
    _private_directory(root / "state")
    return root, root / AUTH_FILE


def _read_auth(home: str | Path | None = None) -> dict[str, Any] | None:
    _, path = _auth_path(home)
    if not path.exists() and not path.is_symlink():
        return None
    _private_path(path)
    try:
        value = json.loads(_read_private(path))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SetupError(
            "ChatGPT sign-in state is invalid; run `signalweave auth login` again"
        ) from None
    required = {"client_id", "subject", "ext_agent_host_id", "scopes"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise SetupError("ChatGPT sign-in state is incomplete; run `signalweave auth login` again")
    reauth_required = value.get("reauth_required", False)
    token_fields = {"access_token", "refresh_token", "expires_at"}
    if not isinstance(reauth_required, bool) or (
        (reauth_required and token_fields.intersection(value))
        or (not reauth_required and not token_fields.issubset(value))
    ):
        raise SetupError("ChatGPT sign-in state is invalid; reauthorization is required")
    if (
        not isinstance(value["scopes"], list)
        or not all(isinstance(item, str) for item in value["scopes"])
        or not all(
            isinstance(value[name], str) and value[name]
            for name in ("client_id", "subject", "ext_agent_host_id")
        )
        or (
            not reauth_required
            and (
                not all(
                    isinstance(value[name], str) and value[name]
                    for name in ("access_token", "refresh_token")
                )
                or type(value["expires_at"]) is not int
            )
        )
        or (
            "token_type" in value
            and (not isinstance(value["token_type"], str) or value["token_type"].lower() != "bearer")
        )
        or (
            "id_token" in value
            and (not isinstance(value["id_token"], str) or not value["id_token"])
        )
        or ("email" in value and not isinstance(value["email"], str))
    ):
        raise SetupError("ChatGPT sign-in state is invalid; run `signalweave auth login` again")
    return value


def auth_status(home: str | Path | None = None) -> dict[str, Any]:
    """Return secret-free state for CLI and UI status."""
    try:
        value = _read_auth(home)
    except SetupError:
        return {"status": "invalid", "account": None, "plan_usage": "unknown"}
    if value is None:
        return {"status": "not_connected", "account": None, "plan_usage": "not_enabled"}
    if value.get("reauth_required"):
        return {
            "status": "reauth_required",
            "account": value.get("email"),
            "plan_usage": "reauthorization_required",
        }
    scopes = set(value["scopes"])
    enabled = "chatgpt.tokens.use.direct" in scopes and "resource.invoke" in scopes
    return {
        "status": "connected" if enabled else "permission_missing",
        "account": value.get("email"),
        "plan_usage": "enabled" if enabled else "not_enabled",
        "expires_at": value.get("expires_at"),
    }


def _host_id(home: str | Path | None = None) -> str:
    root = resolve_home(home)
    _private_directory(root)
    path = root / HOST_FILE
    if path.exists() or path.is_symlink():
        _private_path(path)
        try:
            value = json.loads(_read_private(path))
            host_id = value.get("ext_agent_host_id") if isinstance(value, dict) else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            host_id = None
        if isinstance(host_id, str) and host_id.startswith("urn:uuid:"):
            return host_id
        raise SetupError(
            "SignalWeave ChatGPT host identifier is invalid; inspect the local auth files"
        )
    host_id = f"urn:uuid:{uuid.uuid4()}"
    _write_private_json(path, {"ext_agent_host_id": host_id})
    return host_id


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _authorization_url(
    *,
    client_id: str,
    host_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    verifier: str,
    initial_registration: bool,
    existing: dict[str, Any] | None = None,
) -> str:
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "ext_agent_host_id": host_id,
    }
    if initial_registration:
        params["agent_name_hint"] = "SignalWeave"
    elif existing:
        if existing.get("id_token"):
            params["id_token_hint"] = existing["id_token"]
        if existing.get("email"):
            params["login_hint"] = existing["email"]
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _fallback_authorization_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    params = [
        (name, value)
        for name, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if name != "id_token_hint"
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(params), parsed.fragment)
    )


def _validate_id_token(token: str, *, client_id: str, nonce: str) -> dict[str, Any]:
    try:
        key = jwt.PyJWKClient(JWKS_URL, timeout=10).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256", "ES256"],
            audience=client_id,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
            leeway=30,
        )
    except Exception:
        raise SetupError("ChatGPT identity token could not be verified; sign in again") from None
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SetupError("ChatGPT sign-in nonce did not match; sign in again")
    return claims


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            self.server.oauth_result = {"_invalid_callback": True}  # type: ignore[attr-defined]
        else:
            self.server.oauth_result = {
                key: values[0] for key, values in query.items()
            }  # type: ignore[attr-defined]
        body = (
            b"<!doctype html><title>SignalWeave sign-in</title>"
            b"<p>SignalWeave sign-in returned to your computer. You can close this window.</p>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


def login(
    home: str | Path | None = None,
    *,
    timeout_seconds: int = 300,
    open_browser: Callable[[str], bool] = webbrowser.open,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Run the documented loopback PKCE flow and persist a verified profile."""
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        raise SetupError("ChatGPT sign-in timeout must be a positive number of seconds")
    root, auth_path = _auth_path(home)
    existing = _read_auth(root)
    client_id = existing.get("client_id") if existing else "dynamic_agent_client"
    initial = existing is None
    host_id = _host_id(root)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    callback = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    callback.timeout = 1
    redirect_uri = f"http://127.0.0.1:{callback.server_port}{CALLBACK_PATH}"
    authorization_url = _authorization_url(
        client_id=client_id,
        host_id=host_id,
        redirect_uri=redirect_uri,
        state=state,
        nonce=nonce,
        verifier=verifier,
        initial_registration=initial,
        existing=existing,
    )
    print(
        "Opening OpenAI sign-in in your browser. Approve SignalWeave’s requested ChatGPT-plan access."
    )
    try:
        try:
            browser_opened = open_browser(authorization_url)
        except Exception:
            browser_opened = False
        if not browser_opened:
            print("If the browser did not open, copy this sign-in URL into your browser:")
            print(_fallback_authorization_url(authorization_url))
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and not hasattr(callback, "oauth_result"):
            callback.handle_request()
    finally:
        callback.server_close()
    result = getattr(callback, "oauth_result", None)
    if isinstance(result, dict) and result.get("_invalid_callback"):
        raise SetupError("ChatGPT sign-in callback contained duplicate parameters")
    if not isinstance(result, dict):
        raise SetupError("ChatGPT sign-in timed out; run `signalweave auth login` to try again")
    if not secrets.compare_digest(str(result.get("state", "")), state):
        raise SetupError("ChatGPT sign-in state did not match; run `signalweave auth login` again")
    if result.get("error"):
        raise SetupError("ChatGPT sign-in was cancelled or not authorized")
    code = result.get("code")
    returned_client_id = result.get("client_id")
    if not code:
        raise SetupError("ChatGPT sign-in returned no authorization code")
    if initial:
        if not returned_client_id or returned_client_id == "dynamic_agent_client":
            raise SetupError("ChatGPT did not issue a SignalWeave client ID; sign in again")
        client_id = returned_client_id
    elif returned_client_id and returned_client_id != client_id:
        raise SetupError(
            "ChatGPT returned a different account registration; existing credentials were preserved"
        )

    try:
        with httpx.Client(timeout=20, transport=transport) as client:
            response = client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                    "resource": RESOURCE,
                },
            )
    except httpx.HTTPError:
        raise SetupError(
            "ChatGPT token exchange could not reach OpenAI; check your network and try again"
        ) from None
    if response.status_code != 200:
        raise SetupError(
            "ChatGPT token exchange failed ("
            f"{_oauth_failure_summary(response)}); sign in again"
        )
    try:
        tokens = response.json()
        if not isinstance(tokens, dict):
            raise ValueError("token response is not an object")
        token_type = tokens.get("token_type")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise ValueError("token type is not bearer")
        scope_value = tokens.get("scope")
        if not isinstance(scope_value, str):
            raise ValueError("granted scope is missing")
        granted_scopes = scope_value.split()
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise ValueError("identity token is missing")
        claims = _validate_id_token(id_token, client_id=client_id, nonce=nonce)
        if not {"chatgpt.tokens.use.direct", "resource.invoke", "openid"}.issubset(granted_scopes):
            raise SetupError(
                "Sign-in succeeded but ChatGPT-plan permission was not granted. "
                "Run `signalweave auth login` and approve the requested usage permission."
            )
        if not all(isinstance(tokens.get(name), str) and tokens[name] for name in ("access_token", "refresh_token")):
            raise ValueError("token fields missing")
        expires_in = tokens.get("expires_in")
        if type(expires_in) is not int or expires_in <= 0:
            raise ValueError("token expiry is invalid")
        previous = existing or {}
        if previous and previous.get("subject") != claims["sub"]:
            raise SetupError(
                "The selected ChatGPT account changed; existing credentials were preserved"
            )
        record = {
            "issuer": ISSUER,
            "subject": claims["sub"],
            "email": claims.get("email"),
            "client_id": client_id,
            "ext_agent_host_id": host_id,
            "id_token": id_token,
            "token_type": "Bearer",
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_at": int(time.time()) + expires_in,
            "scopes": granted_scopes,
            "saved_at": int(time.time()),
        }
    except SetupError:
        raise
    except Exception:
        raise SetupError(
            "ChatGPT token response was incomplete or invalid; sign in again"
        ) from None
    _write_private_json(auth_path, record)
    return auth_status(root)


def logout(home: str | Path | None = None) -> bool:
    """Remove local credentials. Remote access can be revoked in ChatGPT settings."""
    _, path = _auth_path(home)
    if path.exists() or path.is_symlink():
        _private_path(path)
        path.unlink()
        return True
    return False


def _get_access_token_sync(
    home: str | Path | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Refresh under a process-wide file lock to protect rotating tokens."""
    root, path = _auth_path(home)
    lock_path = root / ".chatgpt-auth.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        _private_path(lock_path)
        fcntl.flock(fd, fcntl.LOCK_EX)
        record = _read_auth(home)
        if record is None:
            raise SetupError("ChatGPT is not connected; run `signalweave auth login`")
        if record.get("reauth_required"):
            raise SetupError("ChatGPT sign-in expired; run `signalweave auth login`")
        if not {"chatgpt.tokens.use.direct", "resource.invoke"}.issubset(set(record["scopes"])):
            raise SetupError("ChatGPT-plan access is not enabled; run `signalweave auth login`")
        if int(record["expires_at"]) > int(time.time()) + 90:
            return str(record["access_token"])
        refresh_token = str(record["refresh_token"])
        client_id = str(record["client_id"])
        try:
            with httpx.Client(timeout=20, transport=transport) as client:
                response = client.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": client_id,
                        "refresh_token": refresh_token,
                        "resource": RESOURCE,
                    },
                )
        except httpx.HTTPError:
            raise SetupError(
                "ChatGPT session refresh could not reach OpenAI; check network or sign in again"
            ) from None
        if response.status_code != 200:
            code, request_id = _oauth_error_details(response)
            if code in _UNUSABLE_REFRESH_CODES:
                _mark_reauth_required(path, record)
                details = [f"code={code}"]
                if request_id:
                    details.append(f"request_id={request_id}")
                raise SetupError(
                    "ChatGPT refresh token is no longer valid ("
                    + "; ".join(details)
                    + "); run `signalweave auth login`"
                )
            raise SetupError(
                f"ChatGPT session refresh failed ({_oauth_failure_summary(response)}); "
                "credentials were preserved; retry or run `signalweave auth login`"
            )
        try:
            tokens = response.json()
            if not isinstance(tokens, dict):
                raise ValueError("token response is not an object")
            token_type = tokens.get("token_type")
            if not isinstance(token_type, str) or token_type.lower() != "bearer":
                raise ValueError("token type is not bearer")
            scope_value = tokens.get("scope", " ".join(record["scopes"]))
            if not isinstance(scope_value, str):
                raise ValueError("scope is invalid")
            new_scopes = scope_value.split()
            if not {"chatgpt.tokens.use.direct", "resource.invoke"}.issubset(new_scopes):
                raise ValueError("required permissions missing")
            if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
                raise ValueError("access token missing")
            if not isinstance(tokens.get("refresh_token"), str) or not tokens["refresh_token"]:
                raise ValueError("rotated refresh token missing")
            expires_in = tokens.get("expires_in")
            if type(expires_in) is not int or expires_in <= 0:
                raise ValueError("token expiry is invalid")
            record.update(
                {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "token_type": "Bearer",
                    "expires_at": int(time.time()) + expires_in,
                    "scopes": new_scopes,
                    "saved_at": int(time.time()),
                }
            )
        except Exception:
            _mark_reauth_required(path, record)
            raise SetupError(
                "ChatGPT refresh may have rotated credentials but returned an invalid token set; "
                "reauthorize with `signalweave auth login`"
            ) from None
        _write_private_json(path, record)
        return str(record["access_token"])
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


async def get_access_token(
    home: str | Path | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Return a valid OAuth token without blocking the MCP event loop."""
    return await asyncio.to_thread(_get_access_token_sync, home, transport=transport)


__all__ = ["auth_status", "get_access_token", "login", "logout"]
