from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .agent import SignalWeaveGateway


class McpSignalWeaveGateway(SignalWeaveGateway):
    """Streamable-HTTP MCP client for a deployed SignalWeave instance."""

    def __init__(self, url: str, *, bearer_token: str | None = None, timeout: float = 90.0) -> None:
        self.url = url
        self.bearer_token = bearer_token
        self.timeout = timeout

    async def evaluate(
        self,
        card_id: str,
        *,
        idempotency_key: str,
        context: Any = None,
        parent_receipt_id: str | None = None,
        workflow_step_key: str | None = None,
    ) -> Mapping[str, Any]:
        # These imports are intentionally lazy so the example's deterministic
        # unit tests do not need to open a network connection or initialize MCP.
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        headers = {}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        timeout = httpx2.Timeout(self.timeout, read=self.timeout)
        async with create_mcp_http_client(headers=headers, timeout=timeout) as http_client:
            async with streamable_http_client(self.url, http_client=http_client) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "evaluate_insight_card",
                        {
                            "card_id": card_id,
                            "idempotency_key": idempotency_key,
                            "actor": "investigation-agent",
                            "context": (
                                context.model_dump(mode="json")
                                if context is not None and hasattr(context, "model_dump")
                                else context
                            ),
                            "parent_receipt_id": parent_receipt_id,
                            "workflow_step_key": workflow_step_key,
                        },
                    )
        if getattr(result, "isError", False):
            raise RuntimeError(_tool_text(result))
        return _tool_payload(result)


def _tool_text(result: Any) -> str:
    content = getattr(result, "content", []) or []
    text = [str(item.text) for item in content if getattr(item, "text", None)]
    return "\n".join(text) or "SignalWeave MCP tool returned an error"


def _tool_payload(result: Any) -> Mapping[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, Mapping):
        return structured
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        import json

        payload = json.loads(text)
        if isinstance(payload, Mapping):
            return payload
    raise ValueError("SignalWeave MCP result did not contain a JSON object")
