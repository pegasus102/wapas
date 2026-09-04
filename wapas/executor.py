"""
wapas.executor
--------------
Turns a gate decision into an outcome. This is the ONLY module allowed to
see the hidden true cause — it stands in for the real world (the customer's
bank either does or doesn't recover the payment), not for any part of the
diagnosis/decision pipeline.

Common random numbers: each event's outcome draw is seeded from the
event_id, not from a shared sequential stream, so two lines that pick the
same action for the same event get the same outcome and any measured gap
is attributable to where their actions actually differ.

Backends:
  - sim (this file): response_model.simulate_outcome() against hidden truth
  - razorpay_test (later step): real test-mode Orders / Payment Links /
    Refunds for the on-camera demo
"""

from __future__ import annotations
import hashlib
import random
from .response_model import simulate_outcome, ResponseParams


def event_rng(event_id: str, salt: str = "outcome") -> random.Random:
    h = hashlib.sha256(f"{event_id}:{salt}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def execute_sim(
    decision: dict,
    true_cause: str,
    prior_contacts: int,
    rng: random.Random | None = None,
    params: ResponseParams | None = None,
) -> dict:
    action = decision["final_action"]
    r = rng if rng is not None else event_rng(decision["event_id"])
    outcome = simulate_outcome(true_cause, action, prior_contacts, r, params)

    ttr = outcome["time_to_recovery_hours"]
    if ttr is not None:
        ttr = round(ttr + float(decision.get("deferred_hours") or 0.0), 1)

    amount = float(decision.get("amount", 0.0))
    cost = float(decision.get("action_cost_inr", 0.0))
    recovered_inr = amount if outcome["recovered"] else 0.0
    return {
        "event_id": decision["event_id"],
        "action_executed": action,
        **outcome,
        "time_to_recovery_hours": ttr,
        "recovered_inr": recovered_inr,
        "action_cost_inr": cost,
        "net_inr": round(recovered_inr - cost, 2),
    }