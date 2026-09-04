"""
wapas.executor
--------------
Turns a gate decision into an outcome. The ONLY module allowed to see the
hidden true cause — it stands in for the real world, not for any part of
the diagnosis/decision pipeline. Common random numbers: each event's draw
is seeded from its event_id, so two lines that execute the same action on
the same event get the same outcome.
"""

from __future__ import annotations
import hashlib
import random
from .response_model import simulate_outcome, ResponseParams

# A complaint is not free: expected churn/support cost per complaint, in ₹.
# Conservative (dunning benchmarks put churn-per-abusive-contact higher);
# documented in HYPOTHESES.md amendment v2 and swept by `make sensitivity`.
COMPLAINT_COST_INR = 150.0


def event_rng(event_id: str, salt: str = "outcome") -> random.Random:
    h = hashlib.sha256(f"{event_id}:{salt}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def execute_sim(decision: dict, true_cause: str, prior_contacts: int,
                rng: random.Random | None = None, params: ResponseParams | None = None) -> dict:
    action = decision["final_action"]
    r = rng if rng is not None else event_rng(decision["event_id"])
    outcome = simulate_outcome(true_cause, action, prior_contacts, r, params, decision.get("action_variant"))
    ttr = outcome["time_to_recovery_hours"]
    if ttr is not None:
        ttr = round(ttr + float(decision.get("deferred_hours") or 0.0), 1)
    amount = float(decision.get("amount", 0.0))
    cost = float(decision.get("action_cost_inr", 0.0))
    recovered_inr = amount if outcome["recovered"] else 0.0
    net_inr = recovered_inr - cost - (COMPLAINT_COST_INR if outcome["complaint"] else 0.0)
    return {
        "event_id": decision["event_id"], "action_executed": action, **outcome,
        "time_to_recovery_hours": ttr, "recovered_inr": recovered_inr,
        "action_cost_inr": cost, "net_inr": round(net_inr, 2),
    }