from __future__ import annotations

import json

import pytest

from scripts.live_card_check import run


@pytest.mark.asyncio
async def test_live_card_check_rejects_unapproved_card(tmp_path):
    path = tmp_path / "card.json"
    path.write_text(
        json.dumps(
            {
                "id": "card-1",
                "title": "Growth",
                "what_to_watch": "Growth movement",
                "why_watch": "Help the growth team",
                "sources": [
                    {
                        "key": "dashboard",
                        "adapter": "preset__workspace",
                        "resource": "dashboard:1",
                        "label": "Growth dashboard",
                    }
                ],
                "status": "draft",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="status='approved'"):
        await run(path)
