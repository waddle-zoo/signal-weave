"""Fresh public-MCP fixture setup; scripted owner, not agent onboarding evidence.

No SQLite import, archived approvals, provider judgments or private labels. The
caller supplies the exact source scope and fictional owner's reviewed policy.
All mutations go through the same agent-profile tools available to real users.
"""

from copy import deepcopy
from datetime import timedelta


def retail_setup_spec(public, clock):
    """Two distinct reporting briefs using one published synthetic definition."""
    primary = next(item for item in public["catalog"] if item["contract"].get("roles") == ["primary"])
    corroboration = next(item for item in public["catalog"] if item["contract"].get("roles") == ["corroborates"])
    metric = primary["contract"]["metric_names"][0]
    source = {"key": "sales", "adapter": primary["adapter"], "resource": primary["resource"],
              "label": primary["title"]}
    context = {
        "domain": "commerce", "title": "Net sales reporting definition",
        "body": public["glossary"][metric], "kind": "definition", "sources": [source],
        "provenance": ["Published synthetic scenario's fictional owner and glossary; not customer sign-off"],
        "review_after": (clock + timedelta(days=30)).isoformat(),
    }
    common = {
        "why_watch": public["brief"],
        "decision_guidance": public["owner_answers"]["materiality"],
        "comparison_windows": ["previous_period"],
        "selected_sources": [
            {"ref": primary["adapter"] + "|" + primary["resource"], "key": "sales",
             "required": True, "required_comparison_keys": [metric]},
            {"ref": corroboration["adapter"] + "|" + corroboration["resource"],
             "key": "posting-policy", "required": True},
        ],
        "delivery_methods": [{"outcome": "notify", **public["destinations"][0]},
                             {"outcome": "insufficient_data", **public["destinations"][1]}],
        "watch_for": [], "questions": [],
    }
    briefs = [
        {"title": "Weekly commerce briefing", "what_to_watch": "Explain net sales movement for the commerce lead."},
        {"title": "Channel contribution investigation", "what_to_watch": "Explain which channels contributed to net sales movement; do not infer causes from accounting contributions."},
    ]
    return {"context": context, "cards": [{**deepcopy(common), **brief} for brief in briefs]}


async def create_public_context_setup(native, spec):
    """Exercise actual save → review → bind → card approval with scripted consent.

    Never evaluate, infer, schedule or send. Errors propagate without retries;
    the caller must preserve its native trace, including partial setup writes.
    This helper is an evaluation caller, not a production onboarding shortcut.
    """
    if len(spec["cards"]) != 2 or any(not draft.get("selected_sources") for draft in spec["cards"]):
        raise ValueError("This public two-brief fixture requires explicit selected source scopes")
    reason = "Scripted fictional owner confirms this published fixture's exact scope and policy; no delivery or scheduling."
    _, saved = await native.call_tool("save_domain_context", {"content": deepcopy(spec["context"])})
    _, reviewed = await native.call_tool("review_domain_context", {
        "entry_id": saved["id"], "expected_revision": saved["revision"],
        "action": "approve", "reason": reason,
    })
    cards = []
    for draft in spec["cards"]:
        _, created = await native.call_tool("onboard_insight_card", deepcopy(draft))
        card_id = created["card"]["id"]
        if any(card["id"] == card_id for card in cards):
            raise RuntimeError("Distinct business briefs must not overwrite one another")
        await native.call_tool("bind_insight_context", {
            "card_id": card_id, "expected_card_version": created["card"]["version"],
            "pins": [{"entry_id": reviewed["id"], "revision": reviewed["revision"], "required_for_action": True}],
            "reason": reason,
        })
        _, review = await native.call_tool("review_insight_card", {"card_id": card_id})
        approval = review["approval_handoff"]["arguments_after_owner_confirmation"]
        await native.call_tool("approve_insight_card", {**approval, "source_selection_reason": reason})
        _, card = await native.call_tool("get_insight_card", {"card_id": card_id, "response_mode": "full"})
        pins = card.get("context_bindings", [])
        if (card["status"] != "approved" or len(pins) != 1
                or pins[0]["entry_id"] != reviewed["id"]
                or pins[0]["revision"] != reviewed["revision"]
                or pins[0]["required_for_action"] is not True):
            raise RuntimeError("Public MCP setup did not persist the reviewed dependency")
        cards.append(card)
    return {"context": reviewed, "cards": cards,
            "approval_scope": "scripted fictional owner, not agent-led or real human onboarding"}
