# Core shadow-pilot contract

This is the smallest complete SignalWeave loop:

```text
human intent
  -> Jev-ranked candidate review
  -> explicit approval
  -> Jev-backed delivery-disabled run
  -> durable shadow receipt
  -> operator label
```

SignalWeave owns the typed decision and evidence boundary. The caller owns the
UI, scheduler, agent, delivery destination, and any later card or graph change.
No Slack, email, incident, or other destination is contacted by the shadow
run.

## Contract

1. `onboard_insight_card` or `draft_insight_card` creates a draft and exposes
   the bounded candidates, blockers, questions, plan, and evidence bundle.
2. `approve_insight_card` re-runs the onboarding review and requires an explicit
   human approval.
3. `evaluate_insight_card` runs only an approved card through the Jev runtime.
   The stored receipt has `delivery_mode="shadow"`,
   `status="delivery_disabled"`, the card version that ran, context provider
   and version, selected delivery methods, the full result, and retrieval
   evidence.
4. `get_decision_receipt` recovers that result by the scheduler's idempotency
   key or by receipt id. It also returns labels already attached to the run.
5. `record_decision_feedback` appends a human or agent label without changing
   Jev state or card policy. A caller-supplied `feedback_id` makes retries
   idempotent; reusing it for different content fails closed.

## Proof in this repository

The focused contract test covers:

- delivery-disabled shadow status and explicit shadow mode;
- result recovery by receipt id and scheduler idempotency key;
- SQLite restart durability for both receipts and feedback;
- stable feedback replay without duplicate labels;
- feedback retaining the receipt's card version after a later card revision;
- existing tenant-scoped card and receipt boundaries; and
- the existing Jev-only runtime requirement.

Run the proof without spending TypeSafe credits:

```bash
./.venv/bin/pytest tests/test_onboarding.py -q
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests evaluations
./.venv/bin/python -m evaluations.onboarding_adversarial_review --format markdown
```

The last local run produced 27 focused onboarding tests passing, 224 repository
tests passing with 2 skips, clean Ruff output, and a passing 30-scenario
independent onboarding review. The review intentionally retained one warning:
an ambiguous metric-definition candidate was surfaced for human review rather
than silently treated as approval-ready.

This proves the product contract, not universal business accuracy. A customer
pilot still needs owner-labeled historical or shadow outcomes, time-split
replay, real source permissions, and a deployment-owned shared receipt store
before enabling autonomous delivery.
