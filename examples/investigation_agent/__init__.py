"""Optional caller-owned investigation agent for SignalWeave.

This package is deliberately outside ``src/signalweave``.  It demonstrates one
way an agent can consume SignalWeave's typed workflow handoffs, gather
authorized evidence, re-evaluate a card, and deliver the resulting evidence
bundle.  SignalWeave remains the decision boundary; this package is an example
caller and is not required by the core service.
"""

from .agent import (
    AgentRun,
    InvestigationAgent,
    InvestigationRequest,
    SignalWeaveGateway,
)

__all__ = [
    "AgentRun",
    "InvestigationAgent",
    "InvestigationRequest",
    "SignalWeaveGateway",
]
