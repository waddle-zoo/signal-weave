from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


def format_evidence_bundle(result: Mapping[str, Any]) -> str:
    """Render SignalWeave's structured result without asking an LLM to rewrite it."""

    lines = [
        f"*{str(result.get('summary') or 'SignalWeave investigation')}*",
        f"Outcome: `{result.get('outcome', 'unknown')}`",
    ]
    if result.get("confidence") is not None:
        lines.append(f"Confidence: `{float(result['confidence']):.2f}`")
    rationale = str(result.get("rationale") or "").strip()
    if rationale:
        lines.extend(["", f"_{rationale}_"])

    findings = result.get("evidence_findings") or []
    if findings:
        lines.extend(["", "*Evidence roles*"])
        for finding in findings:
            if not isinstance(finding, Mapping):
                continue
            probability = finding.get("probability")
            score = f" ({float(probability):.2f})" if probability is not None else ""
            lines.append(
                f"• `{finding.get('role', 'unknown')}` {finding.get('subject_label') or finding.get('metric')}{score}"
            )

    evidence = result.get("evidence") or []
    if evidence:
        lines.extend(["", "*Evidence*"])
        for item in evidence[:20]:
            if not isinstance(item, Mapping):
                continue
            statement = str(item.get("statement") or "").strip()
            source = str(item.get("source_key") or "unknown")
            url = str(item.get("source_url") or "").strip()
            suffix = f" <{url}|source>" if url else ""
            if statement:
                lines.append(f"• `{source}` — {statement}{suffix}")

    observations = result.get("observations") or []
    changed = [item for item in observations if isinstance(item, Mapping) and item.get("change_pct") is not None]
    if changed:
        lines.extend(["", "*Key movements*"])
        for item in changed[:20]:
            lines.append(
                f"• {item.get('subject_label') or item.get('metric')}: {float(item['change_pct']):+.1f}%"
            )

    context = result.get("context") or {}
    facts = context.get("facts", []) if isinstance(context, Mapping) else []
    if facts:
        lines.extend(["", "*Diagnostic context*"])
        for fact in facts[:20]:
            if isinstance(fact, Mapping) and fact.get("statement"):
                source_url = str(fact.get("source_url") or "").strip()
                suffix = f" <{source_url}|source>" if source_url else ""
                lines.append(f"• {fact['statement']}{suffix}")

    warnings = result.get("warnings") or []
    if context.get("warnings") if isinstance(context, Mapping) else False:
        warnings = [*warnings, *context["warnings"]]
    if warnings:
        lines.extend(["", "*Warnings*"])
        lines.extend(f"• {warning}" for warning in warnings[:10])
    return "\n".join(lines)


class DeliveryAdapter(Protocol):
    async def deliver(
        self, result: Mapping[str, Any], *, card_id: str, run_id: str
    ) -> Sequence[Mapping[str, Any]]: ...


class StdoutDeliveryAdapter:
    """Safe local sink for demos and tests."""

    async def deliver(
        self, result: Mapping[str, Any], *, card_id: str, run_id: str
    ) -> Sequence[Mapping[str, Any]]:
        print(format_evidence_bundle(result))
        return [{"status": "printed", "card_id": card_id, "run_id": run_id}]


class SlackTransport(Protocol):
    async def list_channels(self) -> Sequence[Mapping[str, Any]]: ...

    async def list_members(self, channel_id: str) -> Sequence[str]: ...

    async def create_channel(self, name: str) -> Mapping[str, Any]: ...

    async def invite(self, channel_id: str, user_ids: Sequence[str]) -> Mapping[str, Any]: ...

    async def post_message(self, channel_id: str, text: str) -> Mapping[str, Any]: ...


class SlackWebApi:
    """Minimal Slack Web API transport; policy remains in SlackDeliveryAdapter."""

    def __init__(self, token: str, *, base_url: str = "https://slack.com/api", timeout: float = 30.0) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _call(self, method: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/{method}",
                headers={"Authorization": f"Bearer {self.token}"},
                json=dict(payload),
            )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Slack {method} failed: {body.get('error', 'unknown_error')}")
        return body

    async def list_channels(self) -> Sequence[Mapping[str, Any]]:
        body = await self._call("conversations.list", {"exclude_archived": True, "limit": 1000})
        return body.get("channels", [])

    async def list_members(self, channel_id: str) -> Sequence[str]:
        body = await self._call("conversations.members", {"channel": channel_id, "limit": 1000})
        return body.get("members", [])

    async def create_channel(self, name: str) -> Mapping[str, Any]:
        body = await self._call("conversations.create", {"name": name})
        return body["channel"]

    async def invite(self, channel_id: str, user_ids: Sequence[str]) -> Mapping[str, Any]:
        return await self._call(
            "conversations.invite", {"channel": channel_id, "users": ",".join(user_ids)}
        )

    async def post_message(self, channel_id: str, text: str) -> Mapping[str, Any]:
        return await self._call("chat.postMessage", {"channel": channel_id, "text": text})


@dataclass(frozen=True)
class SlackRoute:
    channel_name: str
    member_ids: tuple[str, ...] = ()


def _channel_slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return value[:70] or "investigation"


class SlackDeliveryAdapter:
    """Create/reuse one channel and post a structured SignalWeave bundle.

    Channel creation and invitations are explicit opt-ins.  Posting to an
    existing channel can be enabled independently.  The adapter uses one stable
    channel name per route so retries do not create a new channel each time.
    """

    def __init__(
        self,
        transport: SlackTransport,
        *,
        route: SlackRoute | None = None,
        allow_channel_create: bool = False,
        allow_invites: bool = False,
    ) -> None:
        self.transport = transport
        self.route = route
        self.allow_channel_create = allow_channel_create
        self.allow_invites = allow_invites

    async def deliver(
        self, result: Mapping[str, Any], *, card_id: str, run_id: str
    ) -> Sequence[Mapping[str, Any]]:
        method_keys = [
            str(method.get("key"))
            for method in result.get("delivery_methods", [])
            if isinstance(method, Mapping) and method.get("key")
        ]
        channel_name = self.route.channel_name if self.route else f"signalweave-{_channel_slug(card_id)}"
        members = self.route.member_ids if self.route else ()
        channels = await self.transport.list_channels()
        channel = next(
            (item for item in channels if str(item.get("name", "")) == channel_name), None
        )
        created = False
        if channel is None:
            if members and not self.allow_invites:
                raise RuntimeError(
                    "Slack member invitations are disabled; refusing to create a channel "
                    "that cannot receive its configured members"
                )
            if not self.allow_channel_create:
                raise RuntimeError(
                    f"Slack channel {channel_name!r} does not exist and channel creation is disabled"
                )
            channel = await self.transport.create_channel(channel_name)
            created = True
        channel_id = str(channel.get("id") or "")
        if not channel_id:
            raise RuntimeError("Slack channel response did not contain an id")
        invited = False
        if members:
            existing_members = set(await self.transport.list_members(channel_id))
            missing_members = tuple(member for member in members if member not in existing_members)
            if missing_members and not self.allow_invites:
                raise RuntimeError("Slack member invitations are disabled for this agent")
            if missing_members:
                await self.transport.invite(channel_id, missing_members)
                invited = True
        message = format_evidence_bundle(result)
        message = f"*SignalWeave evidence bundle* · run `{run_id}`\n{message}"
        posted = await self.transport.post_message(channel_id, message)
        return [
            {
                "status": "posted",
                "channel_id": channel_id,
                "channel_name": channel_name,
                "created": created,
                "invited": invited,
                "method_keys": method_keys,
                "message_ts": posted.get("ts"),
            }
        ]
