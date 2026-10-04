"""Deployment liveness and readiness checks.

The HTTP process can be alive while its Jev runtime, source registry, or
identity boundary is unusable.  Keep this report deliberately local and
non-secret: it checks startup configuration and object wiring, not provider
connectivity or a paid Jev request.
"""

from __future__ import annotations

from typing import Any

from .runtime import Runtime


def deployment_readiness(
    runtime: Runtime,
    *,
    request_scoped_principal: bool = False,
) -> dict[str, Any]:
    """Return a safe startup-readiness report for a deployed runtime.

    A provider credential may still be expired or lack permission after this
    passes; provider access belongs to the bounded source/bootstrap probes.
    The report therefore calls that state ``startup_ready`` rather than
    pretending it is a live connectivity check.
    """

    judger = runtime.engine.judger
    judger_name = str(getattr(judger, "name", ""))
    checks = {
        "jev_decision_path": judger_name.startswith("jev"),
        "source_adapter": bool(runtime.sources.adapter_names()),
        "durable_card_store": runtime.card_store is not None,
        "durable_receipt_store": runtime.decision_receipts is not None,
        "identity_boundary": bool(runtime.principal) or request_scoped_principal,
    }
    ready = all(checks.values())
    principal_mode = (
        "request_scoped"
        if request_scoped_principal
        else "static"
        if runtime.principal
        else "unconfigured"
    )
    return {
        "status": "ready" if ready else "not_ready",
        "service": "signal-weave",
        "startup_ready": ready,
        "checks": checks,
        "source_adapters": runtime.sources.adapter_names(),
        "decision_path": judger_name or "unconfigured",
        "principal_mode": principal_mode,
        "network_checks": 0,
        "jev_requests": 0,
        "note": "Provider credentials and permissions require a separate bounded bootstrap probe.",
    }
