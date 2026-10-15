"""Fresh post-onboarding periods built with the approved first-report engine.

Only the p05--p08 input rows live here. Source contracts, tenant identity,
policies, destinations, snapshot construction, and oracle math remain the
approved implementation in ``first_report_cases``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from evaluations.first_report_cases import _COMPANIES, _build_run, _public_company

_COMPANY_IDS = ("northstar-cart", "harbor-help", "redwood-fulfillment")


def _fresh_periods() -> dict[str, list[dict[str, Any]]]:
    """Return only new p05--p08 rows; no original period is reused."""
    return {
        "northstar-cart": [
            {"id": "p05", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"web": [400, 520], "marketplace": [120, 115], "store": [80, 80]}, "alternate": {"web": [430, 510], "marketplace": [140, 125], "store": [90, 95]}},
            {"id": "p06", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"web": [400, 470], "marketplace": [120, 55], "store": [80, 80]}, "alternate": {"web": [420, 495], "marketplace": [135, 90], "store": [90, 100]}},
            {"id": "p07", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"web": [300, 390], "marketplace": [140, 50], "store": [100, 100]}, "alternate": {"web": [330, 410], "marketplace": [160, 80], "store": [110, 110]}},
            {"id": "p08", "role": "fresh", "coverage": "partial", "semantic_status": "aligned", "primary": {"web": [500, 530], "marketplace": [140, 145]}, "alternate": {"web": [520, 550], "marketplace": [155, 165], "store": [90, 100]}},
        ],
        "harbor-help": [
            {"id": "p05", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": [("enterprise", 8, 80, 9, 90), ("self_serve", 12, 120, 12, 120)], "alternate": [("enterprise", 10, 80, 12, 90), ("self_serve", 15, 120, 17, 120)]},
            {"id": "p06", "role": "fresh", "coverage": "partial", "semantic_status": "aligned", "primary": [("enterprise", 12, 120, 15, 100), ("self_serve", 10, 100, None, None)], "alternate": [("enterprise", 8, 120, 10, 100), ("self_serve", 16, 100, 17, 100)]},
            {"id": "p07", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": [("enterprise", 14, 100, 14, 100), ("self_serve", 14, 100, 14, 100)], "alternate": [("enterprise", 8, 100, 9, 100), ("self_serve", 18, 100, 20, 100)]},
            {"id": "p08", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": [("enterprise", 5, 50, 12, 60), ("self_serve", 20, 200, 12, 140)], "alternate": [("enterprise", 7, 50, 10, 60), ("self_serve", 24, 200, 20, 140)]},
        ],
        "redwood-fulfillment": [
            {"id": "p05", "role": "fresh", "coverage": "complete", "semantic_status": "definition-conflict", "primary": {"north": [30, 35], "south": [20, 23]}, "alternate": {"north": [55, 70], "south": [35, 48]}},
            {"id": "p06", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"north": [30, 50], "south": [20, 25]}, "alternate": {"north": [40, 55], "south": [25, 35]}},
            {"id": "p07", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"north": [40, 50], "south": [30, 22]}, "alternate": {"north": [45, 60], "south": [35, 30]}},
            {"id": "p08", "role": "fresh", "coverage": "complete", "semantic_status": "aligned", "primary": {"north": [30, 50], "south": [40, 20]}, "alternate": {"north": [45, 65], "south": [35, 28]}},
        ],
    }


def cases() -> list[dict[str, Any]]:
    """Return the three approved companies with fresh p05--p08 periods."""
    fresh = _fresh_periods()
    result: list[dict[str, Any]] = []
    for company_id in _COMPANY_IDS:
        spec = deepcopy(next(company for company in _COMPANIES if company["id"] == company_id))
        spec["periods"] = deepcopy(fresh[company_id])
        if company_id == "northstar-cart":
            # The inherited generator reads this private route with spec.get().
            # The original three-period fixture never exercised this gap route.
            spec["coverage_route"] = "data-operations"
        runs = [_build_run(spec, period, index) for index, period in enumerate(spec["periods"], start=4)]
        result.append(_public_company(spec, runs))
    return result
