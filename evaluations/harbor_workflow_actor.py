"""Bounded research-only actor bridge for Harbor workflow sessions.

The caller owns the native runner, source snapshots, and final-reply transport.
This module only exposes the phase-appropriate tools and retains local evidence
of tool calls and shadow briefs; it does not send messages or decide outcomes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from copy import deepcopy

from evaluations.declared_owner_reference import declared_owner_reference

ONBOARDING_NATIVE_TOOLS = frozenset({
    "get_signalweave_guide",
    "list_insight_cards",
    "search_catalog",
    "inspect_resource",
    "onboard_insight_card",
    "get_insight_card",
    "revise_insight_card",
    "review_insight_card",
})
RECURRING_NATIVE_TOOLS = frozenset({
    "get_signalweave_guide",
    "list_insight_cards",
    "get_insight_card",
    "evaluate_insight_card",
    "get_decision_receipt",
})
SOURCE_QUERY_TOOLS = frozenset({"query_readonly", "export_query"})


def _tool_spec(tool) -> dict:
    """Copy the InstalledServer/MCP tool contract into transport form."""
    if isinstance(tool, Mapping):
        name = tool.get("name")
        description = tool.get("description")
        schema = tool.get("inputSchema", tool.get("parameters"))
    else:
        name = getattr(tool, "name", None)
        description = getattr(tool, "description", None)
        schema = getattr(tool, "inputSchema", getattr(tool, "parameters", None))
    if not isinstance(name, str) or not name or not isinstance(schema, Mapping):
        raise ValueError("MCP tool is missing its name or input schema")
    return {
        "name": name,
        "description": description or "",
        "parameters": deepcopy(dict(schema)),
    }


def _function_spec(name: str, description: str, properties: dict, required=()) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


class HarborWorkflowActor:
    """Expose shared source reads and a small phase-specific native surface."""

    def __init__(self, source, audit, owner, *, native=None, phase="onboarding",
                 notes="", card_id=None, observation_cutoffs=(), advance=None):
        if phase not in {"onboarding", "recurring", "monitoring"}:
            raise ValueError("phase must be onboarding, recurring, or monitoring")
        if not isinstance(notes, str):
            raise ValueError("notes must be a string")
        self.source = source
        self.audit = audit
        self.owner = deepcopy(owner)
        self.native = native
        self.treatment = bool(native)
        self.phase = phase
        self.setup_complete = False
        self.submission = None
        self.notes = notes
        self.card_id = card_id
        self.observation_cutoffs = tuple(observation_cutoffs)
        self.advance = advance
        self.briefs: list[dict] = []
        self.native_calls: list[dict] = []
        self.queries: list[dict] = []
        # Ordinary tool errors are logged per call and remain recoverable.
        # Fatal session failure means source activation left the active clock ambiguous.
        self.failed = False
        self._advance_failed = False
        self._current_cutoff = (
            self.observation_cutoffs[0] if self.observation_cutoffs else None
        )

    @property
    def _recurring(self) -> bool:
        return self.phase in {"recurring", "monitoring"}

    def _emit(self, kind: str, **payload) -> None:
        self.audit.emit(kind, phase=self.phase, **payload)

    def _owner_declarations(self) -> dict:
        if not isinstance(self.owner, Mapping):
            raise ValueError("Owner context must be a mapping of prior declarations")
        declarations = self.owner.get("declarations")
        if not isinstance(declarations, Mapping):
            declarations = {
                key: value for key, value in self.owner.items()
                if key not in {"recipient_keys", "destinations"}
            }
        else:
            declarations = {
                key: value for key, value in declarations.items()
                if key not in {"recipient_keys", "destinations"}
            }
        # The reference helper deliberately accepts exact statement strings.
        # Preserve structured fictional context as deterministic JSON text.
        return {
            key: value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            for key, value in declarations.items()
        }

    def _recipient_keys(self) -> list[str]:
        if not isinstance(self.owner, Mapping):
            raise ValueError("Owner recipient_keys must be supplied as nonblank strings")
        configured = self.owner.get("recipient_keys", ())
        if not isinstance(configured, (list, tuple, set, frozenset)) or any(
            not isinstance(key, str) or not key.strip() for key in configured
        ):
            raise ValueError("Owner recipient_keys must be supplied as nonblank strings")
        return sorted(configured) if isinstance(configured, (set, frozenset)) else list(configured)

    async def specs(self) -> list[dict]:
        source_specs = [_tool_spec(tool) for tool in await self.source.list_tools()]
        result = list(source_specs)
        result.extend([
            _function_spec(
                "ask_owner",
                "Read prior fictional owner context for a free-form question. This is reference material, not approval.",
                {"question": {"type": "string", "minLength": 1, "maxLength": 2000}},
                ("question",),
            ),
            _function_spec(
                "save_working_notes",
                "Save reusable working notes for this analyst session; saving notes is not approval.",
                {"notes": {"type": "string", "maxLength": 16000}},
                ("notes",),
            ),
        ])
        if self._recurring:
            recipient_item = {"type": "string", "minLength": 1}
            recipient_keys = self._recipient_keys()
            if recipient_keys:
                recipient_item["enum"] = recipient_keys
            result.append(_function_spec(
                "save_brief",
                "Save the actual human-readable brief as a local shadow draft. No message is sent.",
                {
                    "body": {"type": "string", "minLength": 1, "maxLength": 6000},
                    "recipients": {
                        "type": "array", "maxItems": 20,
                        "items": recipient_item,
                    },
                    "evidence_refs": {
                        "type": "array", "minItems": 1, "maxItems": 20,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                ("body", "recipients", "evidence_refs"),
            ))

        if self.native is not None:
            visible = RECURRING_NATIVE_TOOLS if self._recurring else ONBOARDING_NATIVE_TOOLS
            result.extend(
                spec for spec in (_tool_spec(tool) for tool in await self.native.list_tools())
                if spec["name"] in visible
            )

        names = [spec["name"] for spec in result]
        if len(names) != len(set(names)):
            raise ValueError("Source, actor, and native tool names must be distinct")
        return result

    async def _source_names(self) -> set[str]:
        return {spec["name"] for spec in
                (_tool_spec(tool) for tool in await self.source.list_tools())}

    async def _call_source(self, name: str, arguments: dict):
        recorded_arguments = deepcopy(arguments)
        try:
            _, result = await self.source.call_tool(name, arguments)
        except (Exception, asyncio.CancelledError) as error:
            entry = {
                "name": name,
                "arguments": recorded_arguments,
                "result": None,
                "error": {"type": type(error).__name__, "message": str(error)[:2000]},
            }
            if name in SOURCE_QUERY_TOOLS:
                self.queries.append(deepcopy(entry))
            self._emit("actor.source_call_failed", **entry)
            raise

        entry = {
            "name": name,
            "arguments": recorded_arguments,
            "result": deepcopy(result),
        }
        if name in SOURCE_QUERY_TOOLS:
            self.queries.append(deepcopy(entry))
        self._emit("actor.source_call", **entry)
        return result

    async def _call_native(self, name: str, arguments: dict):
        recorded_arguments = deepcopy(arguments)
        observation_cutoff = self._current_cutoff
        try:
            _, result = await self.native.call_tool(name, arguments)
        except (Exception, asyncio.CancelledError) as error:
            entry = {
                "name": name,
                "observation_cutoff": observation_cutoff,
                "arguments": recorded_arguments,
                "result": None,
                "error": {"type": type(error).__name__, "message": str(error)[:2000]},
            }
            self.native_calls.append(deepcopy(entry))
            self._emit("actor.native_call_failed", **entry)
            raise

        entry = {
            "name": name,
            "observation_cutoff": observation_cutoff,
            "arguments": recorded_arguments,
            "result": deepcopy(result),
        }
        self.native_calls.append(deepcopy(entry))
        self._emit("actor.native_call", **entry)
        return result

    def _validate_brief(self, arguments: dict) -> tuple[str, list[str], list[str]]:
        if not isinstance(arguments, Mapping):
            raise ValueError("save_brief arguments must be an object")
        body = arguments.get("body")
        recipients = arguments.get("recipients")
        evidence_refs = arguments.get("evidence_refs")
        if not isinstance(body, str) or not body.strip() or len(body) > 6000:
            raise ValueError("body must be nonblank and at most 6000 characters")
        if not isinstance(recipients, list) or len(recipients) > 20:
            raise ValueError("recipients must be a list of at most 20 recipient keys")
        if any(not isinstance(key, str) or not key.strip() for key in recipients):
            raise ValueError("recipient keys must be nonblank exact strings")
        configured = self._recipient_keys()
        unknown = [key for key in recipients if key not in configured]
        if unknown:
            raise ValueError("Unknown recipient key")
        if (not isinstance(evidence_refs, list) or not evidence_refs
                or len(evidence_refs) > 20):
            raise ValueError("evidence_refs must contain 1 to 20 exact source references")
        if any(not isinstance(ref, str) or not ref.strip() for ref in evidence_refs):
            raise ValueError("evidence references must be nonblank exact strings")
        return body, list(recipients), list(evidence_refs)

    async def _save_brief(self, arguments: dict) -> dict:
        if self.failed:
            raise ValueError("Actor session failed; stop without completing the request")
        if self._advance_failed:
            raise ValueError("Snapshot advancement failed; stop without another check")
        body, recipients, evidence_refs = self._validate_brief(arguments)
        if self._current_cutoff is None:
            raise ValueError("A source cutoff is required before saving a recurring brief")
        index = len(self.briefs)
        if index >= len(self.observation_cutoffs):
            raise ValueError("No requested observation remains for this brief")
        has_next = index + 1 < len(self.observation_cutoffs)
        if has_next and self.advance is None:
            raise ValueError("An advance callback is required between observations")

        brief = {
            "body": body,
            "recipients": recipients,
            "evidence_refs": evidence_refs,
            "observation_cutoff": deepcopy(self._current_cutoff),
            "delivery": "local_shadow_draft",
            "sent": False,
        }
        if self.card_id is not None:
            brief["card_id"] = self.card_id
        self.briefs.append(brief)
        self._emit("actor.brief_saved", index=index, brief=deepcopy(brief))

        response = {
            "saved": True,
            "brief": deepcopy(brief),
            "delivery": "local_shadow_draft",
            "sent": False,
        }
        if not has_next:
            response["request_complete"] = True
            return response

        next_index = index + 1
        try:
            await self.advance(next_index)
        except (Exception, asyncio.CancelledError) as error:
            self.failed = True
            self._advance_failed = True
            self._emit(
                "actor.advance_failed",
                after_brief_index=index,
                requested_observation_index=next_index,
                completed_brief=deepcopy(brief),
                partial_activation_possible=True,
                error={"type": type(error).__name__, "message": str(error)[:2000]},
            )
            raise RuntimeError(
                "Brief was saved, but the next source snapshot did not activate successfully"
            ) from error

        next_cutoff = self.observation_cutoffs[next_index]
        self._current_cutoff = deepcopy(next_cutoff)
        self._emit(
            "actor.snapshot_advanced",
            observation_index=next_index,
            source_cutoff=deepcopy(next_cutoff),
        )
        response["continue_request"] = True
        response["next_source_cutoff"] = deepcopy(next_cutoff)
        return response

    async def call(self, name: str, arguments: dict):
        if self.failed:
            raise ValueError("Actor session failed; stop without completing the request")
        if self.submission is not None:
            raise ValueError("Actor request already submitted")

        if name == "ask_owner":
            return declared_owner_reference(
                self._owner_declarations(), arguments.get("question")
                if isinstance(arguments, Mapping) else None,
            )
        if name == "save_working_notes":
            if not isinstance(arguments, Mapping):
                raise ValueError("save_working_notes arguments must be an object")
            notes = arguments.get("notes")
            if not isinstance(notes, str) or len(notes) > 16000:
                raise ValueError("notes must be a string of at most 16000 characters")
            self.notes = notes
            return {"saved": True, "approved": False}
        if name == "save_brief" and self._recurring:
            return await self._save_brief(arguments)

        source_names = await self._source_names()
        if name in source_names:
            return await self._call_source(name, arguments)
        visible_native = RECURRING_NATIVE_TOOLS if self._recurring else ONBOARDING_NATIVE_TOOLS
        if self.native is not None and name in visible_native:
            native_names = {
                spec["name"] for spec in
                (_tool_spec(tool) for tool in await self.native.list_tools())
            }
            if name in native_names:
                return await self._call_native(name, arguments)
        raise ValueError("tool not available")
