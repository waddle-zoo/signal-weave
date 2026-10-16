"""The diagnostic cannot enable discovery inference or broaden its endpoint."""

from argparse import Namespace

import pytest

from evaluations.superset_source_readiness_probe import run, validate_proposal


@pytest.mark.parametrize("value", [None, [], {}, {"selected_sources": []},
    {"selected_sources": [{"ref": "superset|chart:1"}], "retrieval_mode": "expand"},
    {"selected_sources": [{"ref": "superset|chart:1"}], "investigation_mode": "bounded"}])
def test_requires_fixed_source_proposal(value):
    with pytest.raises(ValueError):
        validate_proposal(value)


def test_keeps_explicit_proposal_without_mutation():
    proposal = {"selected_sources": [{"ref": "superset|chart:1"}], "decision_guidance": "Owner policy"}
    assert validate_proposal(proposal) is proposal


async def test_remote_source_rejected_before_binary_or_home_access(tmp_path):
    args = Namespace(superset_url="https://superset.example", binary="missing", output=str(tmp_path / "new"))
    with pytest.raises(ValueError, match="loopback"):
        await run(args)
    assert not (tmp_path / "new").exists()
