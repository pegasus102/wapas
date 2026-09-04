"""
wapas.executor
--------------
Turns an APPROVED gate decision into an outcome. This file is the only
place allowed to know the hidden `true_cause` — because it is standing in
for the real world (a real customer's bank either does or doesn't recover
the payment), not for any part of the diagnosis/decision pipeline.

Common random numbers: each event's outcome draw is seeded from the
event_id itself, NOT from a shared sequential stream. This matters because
several "lines" in the measurement report (rules-only, oracle, WAPAS) are
evaluated on the exact same 500-event set — if event evt_00042 gets the
SAME action under two different lines, it must get the SAME simulated
outcome, so that any measured gap between lines reflects a real difference
in which action was chosen, not independent sampling noise stacked on top.
This is a standard simulation variance-reduction technique, not a shortcut.

Two backends:
  - sim: uses response_model.simulate_outcome() against the hidden truth.
  - razorpay_test: (Phase-2 add-on) drives real Razorpay TEST MODE Orders /
    Payment Links / Refunds APIs for the video demo. Not required for the
    batch experiment to run or score.
"""

from __future__ import annotations
import hashlib
import random
from .response_model import simulate_outcome


def event_rng(event_id: str, salt: str = "outcome") -> random.Random:
    """Deterministic per-event RNG, stable across which line/arm is asking."""
    h = hashlib.sha256(f"{event_id}:{salt}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def execute_sim(decision: dict, true_cause: str, prior_contacts: int, rng: random.Random | None = None) -> dict:
    action = decision["final_action"]
    r = rng if rng is not None else event_rng(decision["event_id"])
    outcome = simulate_outcome(true_cause, action, prior_contacts, r)
    return {
        "event_id": decision["event_id"],
        "action_executed": action,
        **outcome,
    }

