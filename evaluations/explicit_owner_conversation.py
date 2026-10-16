"""Research-only owner reply and complete native-operation logging.

The fictional owner sees the saved artifact and explicitly permits its review
transition. This does not validate its semantics or simulate a real person's UX.
No card, policy, reason, scope map or approval API arguments are supplied here.
"""

import copy


class ExplicitOwnerMixin:
    async def call(self, name, args):
        result = await super().call(name, args)
        if name != "request_owner_approval":
            return result
        artifact = self.owner_requests[-1]["saved_artifact"]
        kind = args["kind"]
        if kind == "card":
            answer = (
                "Yes. I approve this saved card's policy and its displayed selected source scopes "
                "for evaluation. You may approve this saved version, then run one delivery-disabled "
                "check after setup. Do not schedule anything or send a message."
            )
            version = artifact["version"]
        elif kind == "context":
            answer = (
                "Yes. I approve this saved definition and its displayed audience and review date. "
                "This does not approve a card, schedule a run or authorize sending messages."
            )
            version = None
        else:
            answer = (
                "Yes. I approve these saved notes as the reusable brief for one later check. "
                "Do not schedule anything or send a message."
            )
            version = None
        response = {**result, "answer": answer,
                    "confirmation_target": {"kind": kind, "id": args["id"], "card_version": version,
                                            "artifact_digest": self.approvals[kind, args["id"]]},
                    "semantic_review": "Still required separately; this scripted yes is not expert validation."}
        self.owner_requests[-1]["owner_reply"] = copy.deepcopy(response)
        return response


class AuditedNative:
    """Record parent/helper MCP operations as well as model tool forwarding."""

    def __init__(self, native, audit):
        self.native, self.audit = native, audit

    def __getattr__(self, name):
        return getattr(self.native, name)

    async def call_tool(self, name, arguments):
        self.audit.emit("native.operation.start", name=name, arguments=arguments)
        try:
            result = await self.native.call_tool(name, arguments)
        except Exception as error:
            self.audit.emit("native.operation.error", name=name, error_type=type(error).__name__)
            raise
        self.audit.emit("native.operation.result", name=name, result=result[1])
        return result
