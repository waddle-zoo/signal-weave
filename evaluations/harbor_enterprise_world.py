"""Thin local company-world transport for Harbor research journeys.

The coordinator owns source cutoffs, native setup, policy, and callback behavior.
This module only forwards MCP tools, retains a bounded trace, and lets
caller-supplied CompanyPerson instances exchange natural messages and files.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import time
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from evaluations.codex_workspace import validate_workspace
from evaluations.company_people import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_CONTEXT_CHARS,
    CompanyPerson,
)
from evaluations.harbor_workflow_actor import WorkspaceSourceActor, _tool_spec

DEFAULT_TOOL_CALLS, MAX_TOOL_CALLS = 256, 512
DEFAULT_MESSAGES, MAX_MESSAGES = 64, 128
DEFAULT_PERSON_REPLIES, MAX_PERSON_REPLIES = 96, 128
DEFAULT_SECONDS, MAX_SECONDS = 7_200, 14_400
MAX_CALL_SECONDS = 240
MAX_TEXT_CHARS = 8_000
MAX_CARD_SNAPSHOT_BYTES = MAX_ATTACHMENT_BYTES
_STATE_VERSION = 1
_CALLBACK_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _tool(name: str, description: str, properties: dict, required=()) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


def _text(maximum: int = MAX_TEXT_CHARS) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _workspace_file(workspace: Path, reference: str) -> Path:
    """Apply Northstar's workspace-relative, symlink-free evidence contract."""
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("Use a relative file path inside the current workspace")
    relative = PurePosixPath(reference)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Workspace file references must stay inside the current workspace")
    candidate, cursor = Path(workspace).joinpath(*relative.parts), Path(workspace)
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Workspace file references cannot use symlinks")
    path = candidate.resolve(strict=True)
    if not path.is_relative_to(Path(workspace).resolve(strict=True)) or not path.is_file():
        raise ValueError("Workspace evidence must be an ordinary file within the current workspace")
    if path.stat().st_size > 16_000_000:
        raise ValueError("A single simulated inbox attachment is limited to 16 MB")
    return path


def _copy_workspace_evidence(workspace: Path, destination: Path, references: list[str]) -> list[dict]:
    """Copy exact workspace bytes into a private simulated inbox and verify hashes."""
    if len(references) > 20:
        raise ValueError("At most 20 workspace evidence files can be attached")
    if not references:
        return []
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    destination.chmod(0o700)
    copied = []
    for index, reference in enumerate(references):
        source = _workspace_file(workspace, reference)
        target = destination / f"{index + 1}-{source.name}"
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        copy_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if source_hash != copy_hash:
            raise ValueError("Workspace evidence copy failed SHA-256 verification")
        copied.append({"original_workspace_path": reference, "recipient_path": str(target),
                       "filename": source.name, "bytes": target.stat().st_size, "sha256": copy_hash})
    return copied


def _awaitable(value):
    return value if hasattr(value, "__await__") else _immediate(value)


async def _immediate(value):
    return value


class HarborWorld:
    """A bounded people/inbox layer around caller-owned Harbor and native MCPs."""

    def __init__(self, source, workspace, inbox_root, people: Mapping[str, CompanyPerson],
                 owner_key: str, audit, native=None, *, advance_callback=None,
                 register_query_callback=None, confirm_snapshot_callback=None,
                 observation_context_callback=None,
                 callback_tools: Mapping[str, Mapping[str, Any]] | None = None,
                 state: Mapping[str, Any] | None = None,
                 max_tool_calls: int = DEFAULT_TOOL_CALLS,
                 max_messages: int = DEFAULT_MESSAGES,
                 max_person_replies: int = DEFAULT_PERSON_REPLIES,
                 max_seconds: int = DEFAULT_SECONDS):
        self.source, self.native, self.audit = source, native, audit
        self.workspace = validate_workspace(workspace)
        root = Path(inbox_root).expanduser().absolute()
        info = root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or root.resolve(strict=True) != root
                or info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise ValueError("inbox_root must be an existing private, owned, non-symlink directory")
        if (not isinstance(people, Mapping) or not people or not isinstance(owner_key, str)
                or owner_key not in people or not callable(getattr(audit, "emit", None))
                or not callable(getattr(audit, "redact", None))):
            raise ValueError("people, owner_key, and an audit recorder are required")
        if (type(max_tool_calls) is not int or not 1 <= max_tool_calls <= MAX_TOOL_CALLS
                or type(max_messages) is not int or not 1 <= max_messages <= MAX_MESSAGES
                or type(max_person_replies) is not int or not 1 <= max_person_replies <= MAX_PERSON_REPLIES
                or type(max_seconds) is not int or not 1 <= max_seconds <= MAX_SECONDS):
            raise ValueError("world budgets must be finite and within their hard limits")

        self.inbox_root, self.owner_key = root, owner_key
        self.people = dict(people)
        self.advance_callback = self._optional_callback(advance_callback, "advance_callback")
        self.register_query_callback = self._optional_callback(register_query_callback, "register_query_callback")
        self.confirm_snapshot_callback = self._optional_callback(
            confirm_snapshot_callback, "confirm_snapshot_callback")
        self.observation_context_callback = self._optional_callback(
            observation_context_callback, "observation_context_callback")
        self.callback_tools = self._callbacks(callback_tools or {})
        self.max_tool_calls, self.max_messages = max_tool_calls, max_messages
        self.max_person_replies, self.max_seconds = max_person_replies, max_seconds
        self.started = time.monotonic()
        self.workspace_actor: WorkspaceSourceActor | None = None

        self._validate_people()
        self.state = self._load_state(state)
        self._restore_people()

    @staticmethod
    def _optional_callback(callback, name):
        if callback is not None and not callable(callback):
            raise ValueError(f"{name} must be callable when supplied")
        return callback

    @staticmethod
    def _callbacks(callbacks):
        if not isinstance(callbacks, Mapping):
            raise ValueError("callback_tools must map names to callback definitions")
        reserved = {"ask_owner", "confirm_snapshot", "send_message", "read_inbox",
                    "finish_day", "register_query"}
        checked = {}
        for name, definition in callbacks.items():
            if (not isinstance(name, str) or not _CALLBACK_NAME.fullmatch(name)
                    or name in reserved or not isinstance(definition, Mapping)):
                raise ValueError("callback tool definitions need a unique safe name and object value")
            callback, description, parameters = (
                definition.get("callback"), definition.get("description"), definition.get("parameters"))
            if (not callable(callback) or not isinstance(description, str)
                    or not isinstance(parameters, Mapping) or parameters.get("type") != "object"):
                raise ValueError("callback tools require callback, description, and object parameters")
            checked[name] = {"callback": callback, "description": description,
                             "parameters": deepcopy(dict(parameters))}
        return checked

    def _validate_people(self):
        inboxes = set()
        for key, person in self.people.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(person, CompanyPerson):
                raise ValueError("people must map stable nonblank keys to CompanyPerson instances")
            inbox = person.session.inbox
            info = inbox.lstat()
            resolved = inbox.resolve(strict=True)
            if (not stat.S_ISDIR(info.st_mode) or resolved != inbox or info.st_uid != os.geteuid()
                    or not resolved.is_relative_to(self.inbox_root) or resolved == self.inbox_root):
                raise ValueError("each person needs a distinct existing owned inbox beneath inbox_root")
            if resolved in inboxes:
                raise ValueError("people cannot share an inbox directory")
            inboxes.add(resolved)

    def _context_fingerprints(self):
        return {
            key: hashlib.sha256(json.dumps({"role_context": person.context,
                                            "model": person.model, "effort": person.effort},
                                           ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
            for key, person in self.people.items()
        }

    def _empty_state(self):
        return {
            "version": _STATE_VERSION,
            "inbox_root": str(self.inbox_root),
            "context_fingerprints": self._context_fingerprints(),
            "messages": [],
            "conversations": {key: [] for key in self.people},
            "person_replies": [],
            "feedback_reads": [],
            "operations": [],
            "tool_events": [],
            "read_message_ids": [],
            "day_summaries": [],
            "person_states": {},
            "elapsed_seconds": 0.0,
        }

    def _load_state(self, state):
        if state is None:
            return self._empty_state()
        if not isinstance(state, Mapping):
            raise ValueError("state must be a prior HarborWorld.snapshot() result")
        loaded = _json_copy(dict(state))
        empty = self._empty_state()
        if (loaded.get("version") != _STATE_VERSION
                or loaded.get("inbox_root") != str(self.inbox_root)
                or loaded.get("context_fingerprints") != empty["context_fingerprints"]):
            raise ValueError("saved world state belongs to a different inbox or person context")
        for key, default in empty.items():
            if key not in loaded:
                loaded[key] = default
        for key in ("messages", "person_replies", "feedback_reads", "operations", "tool_events",
                    "read_message_ids", "day_summaries"):
            if not isinstance(loaded[key], list):
                raise ValueError(f"saved world {key} must be a list")
        if (not isinstance(loaded["conversations"], dict)
                or set(loaded["conversations"]) != set(self.people)
                or not isinstance(loaded["person_states"], dict)
                or not isinstance(loaded["elapsed_seconds"], (int, float))
                or loaded["elapsed_seconds"] < 0):
            raise ValueError("saved world conversation or budget state is invalid")
        return loaded

    def _restore_people(self):
        for key, person in self.people.items():
            saved = self.state["person_states"].get(key)
            if saved is None:
                self.state["person_states"][key] = self._person_state(person)
                continue
            counters = (saved.get("reply_calls"), saved.get("tool_calls"), saved.get("elapsed_seconds"))
            if (type(counters[0]) is not int or type(counters[1]) is not int
                    or not isinstance(counters[2], (int, float))
                    or not 0 <= counters[0] <= person.max_reply_calls
                    or not 0 <= counters[1] <= person.max_tool_calls
                    or not 0 <= counters[2] <= person.max_seconds
                    or type(saved.get("stopped")) is not bool
                    or not isinstance(saved.get("records"), list)
                    or not isinstance(saved.get("reads"), list)
                    or not isinstance(saved.get("deliveries"), list)):
                raise ValueError("saved CompanyPerson budgets or ledgers are invalid")
            for item in saved.get("deliveries", []):
                name = item["attachment"]
                known = person.session.manifest.get(name)
                if known is None:
                    delivered = person.deliver_attachments([name])[0]
                    if delivered != item:
                        raise ValueError("saved delivered attachment no longer matches its exact bytes")
                elif known != (item["bytes"], item["sha256"]):
                    raise ValueError("person inbox attachment differs from saved delivery")
            expected_names = {item["attachment"] for item in saved["deliveries"]}
            if set(person.session.manifest) != expected_names:
                raise ValueError("person inbox contains files outside the saved delivery ledger")
            if (person.reply_calls > saved["reply_calls"] or person.tool_calls > saved["tool_calls"]
                    or person.elapsed_seconds > saved["elapsed_seconds"]
                    or person.stopped and not saved["stopped"]
                    or len(person.records) > len(saved["records"])
                    or len(person.session.reads) > len(saved["reads"])
                    or len(person.attachment_delivery_ledger) > len(saved["deliveries"])):
                raise ValueError("CompanyPerson is ahead of the supplied world snapshot")
            person.reply_calls = saved["reply_calls"]
            person.tool_calls = saved["tool_calls"]
            person.elapsed_seconds = saved["elapsed_seconds"]
            person.stopped = bool(saved["stopped"])
            person.records[:] = deepcopy(saved["records"])
            person.session.reads[:] = deepcopy(saved["reads"])
            person.attachment_delivery_ledger[:] = deepcopy(saved["deliveries"])

    @staticmethod
    def _person_state(person):
        return {
            "reply_calls": person.reply_calls,
            "tool_calls": person.tool_calls,
            "elapsed_seconds": person.elapsed_seconds,
            "stopped": person.stopped,
            "records": deepcopy(person.records),
            "reads": deepcopy(person.session.reads),
            "deliveries": deepcopy(person.attachment_delivery_ledger),
        }

    def snapshot(self) -> dict:
        """Return only the transport ledger needed to resume this arm's people."""
        result = deepcopy(self.state)
        result["person_states"] = {
            key: self._person_state(person) for key, person in self.people.items()
        }
        result["elapsed_seconds"] = self._elapsed()
        return _json_copy(result)

    def _elapsed(self):
        return self.state["elapsed_seconds"] + (time.monotonic() - self.started)

    def _emit(self, kind: str, **fields):
        self.audit.emit(kind, actor_kind="harbor_enterprise_world", **fields)

    def _local_tools(self) -> list[dict]:
        tools = [
            _tool("ask_owner", "Ask the configured fictional owner a natural business question.",
                  {"question": _text()}, ["question"]),
            _tool("send_message", "Send a natural message and exact workspace evidence to one local simulated inbox.",
                  {"to": {"type": "string", "enum": sorted(self.people)},
                   "body": _text(),
                   "workspace_files": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
                   "source_refs": {"type": "array", "maxItems": 20, "items": {"type": "string"}}},
                  ["to", "body", "workspace_files", "source_refs"]),
            _tool("read_inbox", "Read pending messages through the named recipient's own simulated-person context.",
                  {"to": {"type": "string", "enum": sorted(self.people)}}, ["to"]),
        ]
        if self.confirm_snapshot_callback:
            tools.append(_tool(
                "confirm_snapshot",
                "Show the exact saved native card returned by the caller's reader to the owner and retain the natural reply; this never approves or changes native status.",
                {"card_id": _text(256), "question": _text()}, ["card_id", "question"]))
        if self.register_query_callback:
            tools.append(_tool(
                "register_query",
                "Pass one analyst-authored MCPResource JSON proposal for a fixed export_query resource to the caller's registration callback; this is not the connection transport manifest.",
                {"manifest_file": {**_text(1024),
                                   "description": "Workspace-relative path to exactly one MCPResource JSON proposal."}},
                ["manifest_file"]))
        if self.advance_callback:
            tools.append(_tool("finish_day", "Ask the coordinator to advance its caller-owned source state.", {}, []))
        tools.extend({"name": name, "description": item["description"],
                      "parameters": deepcopy(item["parameters"])}
                     for name, item in self.callback_tools.items())
        return tools

    async def _ask_person(self, key: str, incoming_kind: str, message: str) -> dict:
        if len(self.state["person_replies"]) >= self.max_person_replies:
            raise ValueError("simulated-person reply budget exhausted")
        conversation = self.state["conversations"][key]
        conversation.append({"speaker": "analyst", "text": message})
        person = self.people[key]
        try:
            result = await person.reply(incoming_kind=incoming_kind, incoming_message=message,
                                        prior_conversation=conversation[:-1])
        finally:
            self.state["person_states"][key] = self._person_state(person)
        if result.get("final_message"):
            conversation.append({"speaker": "person", "text": result["final_message"]})
        record = {"person_key": key, **deepcopy(result)}
        self.state["person_replies"].append(record)
        self.state["person_states"][key] = self._person_state(person)
        self._emit("company_person.reply", person_key=key, status=result["status"],
                   error=result["error"], reply=result["final_message"],
                   usage_status=result["usage_status"], usage=result["usage"],
                   tool_calls=result["tool_calls"], seconds=result["seconds"],
                   attachment_reads=result["attachment_reads"], person_record=deepcopy(record))
        return {"status": record["status"], "person_key": key,
                "final_message": record["final_message"], "error": record["error"],
                "attachment_reads": deepcopy(record["attachment_reads"])}

    async def _confirm_snapshot(self, args):
        question = args.get("question")
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_CONTEXT_CHARS:
            raise ValueError(f"confirm_snapshot question must be non-empty text up to {MAX_CONTEXT_CHARS} characters")

        card = await _awaitable(self.confirm_snapshot_callback(args["card_id"]))
        if not isinstance(card, Mapping):
            raise ValueError("saved native card snapshot must be a JSON object")
        try:
            snapshot = _json_copy(dict(card))
            encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, sort_keys=True)
            encoded_bytes = encoded.encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise ValueError("saved native card snapshot must be a finite UTF-8 JSON object") from error
        if len(encoded_bytes) > MAX_CARD_SNAPSHOT_BYTES:
            raise ValueError(
                f"saved native card snapshot exceeds the {MAX_CARD_SNAPSHOT_BYTES}-byte review limit"
            )

        snapshot_sha256 = hashlib.sha256(encoded_bytes).hexdigest()
        inline_message = f"{question}\n\nExact saved native card returned by the caller:\n{encoded}"
        delivery = None
        if len(inline_message) <= MAX_CONTEXT_CHARS:
            message = inline_message
            review_mode = "inline"
        else:
            attachment_name = f"native-card-snapshot-{snapshot_sha256}.json"
            message = (
                f"{question}\n\nThe exact saved native card snapshot is delivered as "
                f"{attachment_name} ({len(encoded_bytes)} UTF-8 bytes; SHA-256 "
                f"{snapshot_sha256}). Please use read_delivered_attachment to inspect this exact "
                "JSON file before stating whether you consent. This review does not approve or "
                "change native status."
            )
            if len(message) > MAX_CONTEXT_CHARS:
                raise ValueError(
                    "confirm_snapshot question leaves no room for bounded exact-snapshot review instructions"
                )
            delivery = self._deliver_snapshot_attachment(
                self.people[self.owner_key], attachment_name, encoded_bytes, snapshot_sha256
            )
            review_mode = "attachment"

        reply = await self._ask_person(self.owner_key, "owner_question", message)
        attachment_reads = deepcopy(reply["attachment_reads"])
        event = {
            "card_id": args["card_id"],
            "displayed_native_card": snapshot,
            "snapshot_sha256": snapshot_sha256,
            "snapshot_bytes": len(encoded_bytes),
            "snapshot_review_mode": review_mode,
            "snapshot_attachment": delivery,
            "reply": reply,
            "attachment_reads": attachment_reads,
        }
        self.state["operations"].append({"tool": "confirm_snapshot", **event})
        self._emit(
            "owner_snapshot_review",
            card_id=args["card_id"],
            snapshot_sha256=snapshot_sha256,
            snapshot_bytes=len(encoded_bytes),
            review_mode=review_mode,
            attachment=delivery,
            attachment_reads=attachment_reads,
            reply_status=reply["status"],
        )
        return event

    @staticmethod
    def _deliver_snapshot_attachment(person: CompanyPerson, name: str, content: bytes,
                                     sha256: str) -> dict:
        """Deliver a write-once, hash-addressed snapshot through CompanyPerson's ledger."""
        inbox = person.session.inbox
        target = inbox / name
        expected = {"attachment": name, "bytes": len(content), "sha256": sha256}

        if name in person.session.manifest:
            try:
                existing = person.session._read_bytes(name)
            except (OSError, ValueError) as error:
                raise ValueError("previously delivered card snapshot is no longer readable") from error
            if existing != content:
                raise ValueError("previously delivered card snapshot differs from its content hash")
            recorded = next((item for item in person.attachment_delivery_ledger
                             if item.get("attachment") == name), None)
            if recorded != expected:
                raise ValueError("previously delivered card snapshot ledger does not match its bytes")
            return deepcopy(recorded)

        if len(person.session.manifest) >= MAX_ATTACHMENTS:
            raise ValueError("owner attachment delivery limit prevents exact card snapshot review")

        try:
            with target.open("xb") as stream:
                stream.write(content)
                os.fchmod(stream.fileno(), 0o400)
        except FileExistsError:
            try:
                existing = person.session._read_bytes(name, initial=True)
            except (OSError, ValueError) as error:
                raise ValueError("existing card snapshot path is not a safe regular file") from error
            if existing != content:
                raise ValueError("existing card snapshot path contains different bytes") from None

        deliveries = person.deliver_attachments([name])
        if len(deliveries) != 1 or deliveries[0] != expected:
            raise ValueError("CompanyPerson delivery ledger did not retain the exact card snapshot")
        return deepcopy(deliveries[0])

    async def _send_message(self, args):
        if len(self.state["messages"]) >= self.max_messages:
            raise ValueError("simulated message budget exhausted")
        recipient = self.people[args["to"]]
        files, refs = args["workspace_files"], args["source_refs"]
        if (not isinstance(args["body"], str) or not args["body"].strip()
                or len(args["body"]) > MAX_TEXT_CHARS
                or not isinstance(files, list) or not isinstance(refs, list)
                or len(files) > 20 or len(refs) > 20
                or any(not isinstance(item, str) or len(item) > 2048 for item in refs)):
            raise ValueError("message body and evidence references must be bounded")
        for ref in files:
            path = _workspace_file(self.workspace, ref)
            if path.stat().st_size > MAX_ATTACHMENT_BYTES:
                raise ValueError("recipient attachments must fit the CompanyPerson read limit")
        if len(recipient.session.manifest) + len(files) > MAX_ATTACHMENTS:
            raise ValueError("recipient cumulative attachment limit would be exceeded")

        observation_context = None
        if self.observation_context_callback is not None:
            observed = await _awaitable(self.observation_context_callback())
            if not isinstance(observed, Mapping):
                raise ValueError("observation_context_callback must return a JSON object")
            observation_context = _json_copy(dict(observed))

        message_id = f"message-{len(self.state['messages']) + 1:06d}"
        copied = _copy_workspace_evidence(self.workspace, recipient.session.inbox / message_id, files)
        relative = [str(Path(item["recipient_path"]).relative_to(recipient.session.inbox)) for item in copied]
        deliveries = recipient.deliver_attachments(relative) if relative else []
        if deliveries != [
                {"attachment": rel, "bytes": item["bytes"], "sha256": item["sha256"]}
                for rel, item in zip(relative, copied, strict=True)]:
            raise ValueError("recipient attachment delivery hash differed from copied workspace evidence")
        message = {
            "id": message_id, "to": args["to"], "body": args["body"],
            "source_refs": list(refs), "attachments": copied,
            "attachment_deliveries": deliveries,
            "observation_context": observation_context,
        }
        self.state["messages"].append(message)
        return {"delivered": True, "message_id": message_id, "destination": f"simulation://{args['to']}",
                "source_refs": list(refs), "attachments": copied}

    async def _read_inbox(self, args):
        key = args["to"]
        pending = [message for message in self.state["messages"]
                   if message["to"] == key and message["id"] not in self.state["read_message_ids"]]
        replies = []
        for message in pending:
            # Mark before inference so a timeout or unknown-usage failure is never silently retried.
            self.state["read_message_ids"].append(message["id"])
            result = await self._ask_person(key, "delivered_message", message["body"])
            feedback = {"reply_to": message["id"], "from": key, "reply": result}
            self.state["feedback_reads"].append(feedback)
            replies.append(feedback)
        # Source cutoff/day provenance is retained in the private world trace,
        # not surfaced as an extra clue to the analyst/person conversation.
        visible_messages = [
            {key: value for key, value in message.items() if key != "observation_context"}
            for message in pending
        ]
        return {"messages": visible_messages, "replies": replies}

    async def _register_query(self, args):
        path = _workspace_file(self.workspace, args["manifest_file"])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = await _awaitable(self.register_query_callback(path))
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        event = {"manifest_file": args["manifest_file"], "sha256_before": before,
                 "sha256_after": after, "result": result, "unchanged": before == after}
        self.state["operations"].append({"tool": "register_query", **event})
        if before != after:
            raise ValueError("native registration callback changed the agent-authored manifest")
        return event

    async def _finish_day(self):
        message_count, read_count = len(self.state["messages"]), len(self.state["feedback_reads"])
        previous_message_count = (self.state["day_summaries"][-1]["message_count"]
                                  if self.state["day_summaries"] else 0)
        pending_ids = [message["id"] for message in self.state["messages"][previous_message_count:]
                       if message["id"] not in self.state["read_message_ids"]]
        result = await _awaitable(self.advance_callback())
        sent_since_advance = message_count - previous_message_count
        summary = {
            "advance_index": len(self.state["day_summaries"]),
            "messages_since_prior_advance": sent_since_advance,
            "feedback_reads_since_prior_advance": read_count - self.state["day_summaries"][-1]["read_count"]
            if self.state["day_summaries"] else read_count,
            "unread_message_ids": pending_ids,
            "omissions": (["no_message_delivered"] if sent_since_advance == 0 else [])
                         + (["message_feedback_not_read"] if pending_ids else []),
            "message_count": message_count,
            "read_count": read_count,
            "coordinator_result": result,
        }
        self.state["day_summaries"].append(summary)
        return result

    async def _dispatch(self, name: str, args: dict, base):
        if name == "ask_owner":
            if set(args) != {"question"} or not isinstance(args["question"], str) or not args["question"].strip():
                raise ValueError("ask_owner requires one natural-language question")
            return await self._ask_person(self.owner_key, "owner_question", args["question"])
        if name == "confirm_snapshot":
            if set(args) != {"card_id", "question"}:
                raise ValueError("confirm_snapshot requires card_id and question")
            return await self._confirm_snapshot(args)
        if name == "send_message":
            if set(args) != {"to", "body", "workspace_files", "source_refs"} or args["to"] not in self.people:
                raise ValueError("send_message requires a configured person and bounded message fields")
            return await self._send_message(args)
        if name == "read_inbox":
            if set(args) != {"to"} or args["to"] not in self.people:
                raise ValueError("read_inbox requires one configured recipient key")
            return await self._read_inbox(args)
        if name == "register_query":
            if set(args) != {"manifest_file"} or not isinstance(args["manifest_file"], str):
                raise ValueError("register_query requires one workspace-relative manifest file")
            return await self._register_query(args)
        if name == "finish_day":
            if args:
                raise ValueError("finish_day accepts no arguments")
            return await self._finish_day()
        if name in self.callback_tools:
            definition = self.callback_tools[name]
            result = await _awaitable(definition["callback"](deepcopy(args)))
            operation = {"tool": name, "arguments": deepcopy(args), "result": result}
            self.state["operations"].append(operation)
            return result
        return await base.call(name, args)

    async def call(self, name: str, args: dict, base):
        if not isinstance(args, dict):
            raise ValueError("tool arguments must be an object")
        if len(self.state["tool_events"]) >= self.max_tool_calls:
            self._emit("tool.budget_exhausted", name=name, budget="tool_calls")
            raise ValueError("Harbor world tool-call budget exhausted")
        elapsed = self._elapsed()
        if elapsed >= self.max_seconds:
            self._emit("tool.budget_exhausted", name=name, budget="seconds")
            raise ValueError("Harbor world time budget exhausted")
        self.state["tool_events"].append({"name": name, "arguments": deepcopy(args), "status": "running"})
        event = self.state["tool_events"][-1]
        started = time.monotonic()
        try:
            async with asyncio.timeout(min(MAX_CALL_SECONDS, self.max_seconds - elapsed)):
                result = await self._dispatch(name, args, base)
            event.update(status="complete")
            self._emit("tool.complete", name=name, arguments=args)
            return result
        except BaseException as exc:
            event.update(status="failed", error_type=type(exc).__name__)
            self._emit("tool.failed", name=name, error_type=type(exc).__name__)
            raise
        finally:
            duration = time.monotonic() - started
            event["seconds"] = duration


class HarborEnterpriseBridge:
    """Keep WorkspaceSourceActor's saved-response transport and add world tools."""

    def __init__(self, world: HarborWorld):
        self.world = world
        # Source tool discovery is async, so the actor is initialized lazily by specs().
        self.base: WorkspaceSourceActor | None = None
        self.lock = asyncio.Lock()
        self.phase, self.setup_complete, self.submission = "whole_journey", False, None
        self.treatment = world.native is not None
        self.mcp_instructions = getattr(world.native, "instructions", None)

    async def _ensure_base(self):
        if self.base is None:
            tools = await self.world.source.list_tools()
            source_tools = {_tool_spec(tool)["name"] for tool in tools}
            self.base = WorkspaceSourceActor(
                self.world.source, self.world.audit, self.world.workspace,
                source_tools=source_tools, native=self.world.native)
            self.world.workspace_actor = self.base
        return self.base

    async def specs(self) -> list[dict]:
        base = await self._ensure_base()
        specs = [*await base.specs(), *self.world._local_tools()]
        names = [item["name"] for item in specs]
        if len(names) != len(set(names)):
            raise ValueError("source, native, and Harbor world tool names must be unique")
        return specs

    async def call(self, name: str, arguments: dict):
        async with self.lock:
            base = await self._ensure_base()
            return await self.world.call(name, arguments, base)
