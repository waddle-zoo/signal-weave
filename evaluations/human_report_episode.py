"""Evaluation-only human readout sink; no product policy or delivery behavior."""

import json

from jsonschema import validate

from evaluations.domain_context_onboarding_trial import RecurringEpisode


class HumanReportEpisode(RecurringEpisode):
    """Record the message a person would read, not a second metric registry."""

    def submission_schema(self):
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "outcome": {"type": "string", "enum": ["ignore", "notify", "investigate", "insufficient_data"]},
                "recipients": {"type": "array", "maxItems": 20,
                               "items": {"type": "string", "enum": [item["key"] for item in self.public["destinations"]]},
                               "description": "Policy-triggered alert/review routes only. Ignore has none; routine report audience belongs in summary."},
                "summary": {"type": "string", "minLength": 1, "maxLength": 12000,
                            "description": "The concise human-facing message, including material facts, limits, next step and inline source references. Workflow receipts support workflow facts only."},
            },
            "required": ["outcome", "recipients", "summary"],
        }

    async def specs(self):
        tools = [item for item in await super().specs() if item["name"] != "submit_analysis"]
        tools.append({
            "type": "function", "name": "record_report", "strict": False,
            "description": "Record the message a human should read and its proposed policy routes. No message is sent. Stop after success.",
            "parameters": self.submission_schema(),
        })
        return tools

    async def call(self, name, args):
        if name == "submit_analysis":
            raise ValueError("Use record_report for this human-readout episode")
        if name != "record_report":
            return await super().call(name, args)
        if self.submission is not None:
            raise ValueError("report already recorded; stop now")
        json.dumps(args, allow_nan=False)
        validate(args, self.submission_schema())
        if not args["summary"].strip():
            raise ValueError("include the human-facing message")
        if args["outcome"] == "ignore" and args["recipients"]:
            raise ValueError("ignore has no policy-triggered recipients; put a routine audience in summary")
        if len(set(args["recipients"])) != len(args["recipients"]):
            raise ValueError("do not duplicate policy recipients")
        # Copy, do not normalize or infer citations/numbers from the prose.
        self.submission = json.loads(json.dumps(args, allow_nan=False))
        return {"recorded": True, "delivery_enabled": False}
