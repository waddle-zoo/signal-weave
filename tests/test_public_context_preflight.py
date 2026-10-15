"""Offline fault checks for the public walkthrough, not native/provider proof."""

from contextlib import asynccontextmanager

import pytest

from evaluations import public_context_preflight as trial
from signalweave.knowledge_models import KnowledgeContent
from tests.test_public_context_setup import FakeNative


@pytest.mark.parametrize("fault", [None, "old-revision", "draft-context", "routed", "wrong-source", "no-values", "no-provenance",
                                   "secondary-error", "secondary-missing", "packet-errors", "wrong-card", "wrong-result-card", "wrong-version", "unchanged-context"])
async def test_public_runner_keeps_zero_budget_and_rejects_false_green_packets(tmp_path, monkeypatch, fault):
    class Native(FakeNative):
        content = None

        async def call_tool(self, name, args):
            if name == "onboard_insight_card":
                self.selected = args["selected_sources"]
            if name == "save_domain_context":
                self.content = KnowledgeContent.model_validate(args["content"]).model_dump(mode="json")
                if self.context:
                    if fault == "unchanged-context":
                        return None, dict(self.context)
                    self.context = {**self.context, "revision": 3, "status": "draft"}
                    return None, dict(self.context)
            if name == "retrieve_domain_context":
                return None, {"entries": [{**self.context, "content": self.content,
                    "revision": 1 if fault == "old-revision" else 2,
                    "status": "draft" if fault == "draft-context" else "reviewed"}]}
            if name == "evaluate_insight_card":
                sources = {}
                for anchor in self.selected:
                    adapter, resource = anchor["ref"].split("|", 1)
                    if fault == "secondary-missing" and anchor["key"] == "posting-policy":
                        continue
                    sources[anchor["key"]] = {
                        "adapter": adapter, "resource": "another-resource" if fault == "wrong-source" else resource,
                        "error": "fixture source failed" if fault == "secondary-error" and anchor["key"] == "posting-policy" else None,
                        "evidence": [{"values": {} if fault == "no-values" else {"current": 1},
                                      "provenance": [] if fault == "no-provenance" else [anchor["ref"]]}],
                    }
                return None, {"result": {
                    "card_id": "different-result-card" if fault == "wrong-result-card" else args["card_id"],
                    "outcome": None, "delivery_methods": [{"key": "unexpected"}] if fault == "routed" else [],
                    "judgment": {"reason": "context_review_required"},
                    "judgment_state": {"source_errors": ["fixture failure"] if fault == "packet-errors" else []},
                    "source_by_key": sources,
                }, "receipt": {"delivery_enabled": False,
                               "card_id": "different-card" if fault == "wrong-card" else args["card_id"],
                               "card_version": 99 if fault == "wrong-version" else self.cards[args["card_id"]]["version"]}}
            return await super().call_tool(name, args)

    native = Native()

    @asynccontextmanager
    async def fake_context(binary, key, public, adapter, audit, root, *, request_budget):
        assert request_budget.limit == 0
        assert key.read_text() == "synthetic-public-preflight-no-provider-requests"
        assert not {"private", "labels", "periods"} & public.keys()
        assert adapter.period_context["as_of"] != adapter.period_context["captured_at"]
        assert root.is_dir()
        yield native, "offline synthetic skill"

    monkeypatch.setattr(trial, "verify_binary", lambda binary: {"scope": "offline stub only"})
    monkeypatch.setattr(trial, "native_context", fake_context)
    report = await trial.run(tmp_path / "not-executed", tmp_path / "exclusive-output")
    assert report["provider_attempts"] == 0
    assert len(report["setup"]["cards"]) == 2
    assert report.get("completed", False) is (fault is None)
    assert ("failure" in report) is (fault is not None)
    assert (tmp_path / "exclusive-output" / "report.json").is_file()
    assert not list((tmp_path / "exclusive-output").glob("public-context-*"))


async def test_public_runner_refuses_to_overwrite_previous_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "verify_binary", lambda binary: {})
    output = tmp_path / "existing-attempt"
    output.mkdir()
    marker = output / "report.json"
    marker.write_text("original partial result")
    with pytest.raises(FileExistsError):
        await trial.run(tmp_path / "unused", output)
    assert marker.read_text() == "original partial result"
