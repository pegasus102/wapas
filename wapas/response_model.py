"""
wapas.response_model
---------------------
The "physics" of the simulator: given the TRUE hidden cause and the action
actually taken, what is P(recovered) and P(complaint)?

Every number here is a documented ASSUMPTION (see RESPONSE_MODEL.md), not a
measurement. The honest response to "isn't this just your simulator?" is
(a) publish every knob here, (b) sweep them in measurement.sensitivity and
report where the result stops holding.

Model:
    p_recover = organic[cause]
              + share(action) * uplift[cause] * fatigue_decay ** prior_contacts

    share = 1.0            if action is the policy-correct one for the cause
          = human_share    if escalated to a (competent, capacity-limited) human
          = generic_share  if a harmless-but-mismatched action
          = 0.0            for a retry on an already-debited payment, or a refund
    fraud_hold never "recovers" — its only good outcome is not doing harm.

Complaints happen only when someone is CONTACTED (no_action never
complains), rise with fatigue, spike for a retry on a debited payment, and
spike hardest for contacting a risk-flagged customer.

The knobs a sceptic would turn live in ResponseParams; the sweep that
answers them is `make sensitivity` (step 6).
"""

from __future__ import annotations
import random
from dataclasses import dataclass, asdict

from .schema import CAUSES, ACTIONS, CAUSE_ACTION_POLICY, NEVER_RETRY_CAUSES, RETRY_SHAPED_ACTIONS


@dataclass(frozen=True)
class ResponseParams:
    advantage_scale: float = 1.0          # multiplies uplift[cause]; the "does targeting matter" knob
    generic_share: float = 0.30           # fraction of uplift a mismatched-but-harmless action still gets
    human_share: float = 0.80             # competent human, slower than automation
    fatigue_decay: float = 0.85           # per prior contact in window, applied to uplift only
    organic_scale: float = 1.0            # multiplies organic[cause]
    base_complaint: float = 0.02          # per contact
    fatigue_complaint_bump: float = 0.03  # additive per prior contact
    wrong_never_retry_complaint: float = 0.22   # retry-shaped action on a debited payment
    fraud_contact_complaint: float = 0.50       # any non-escalate action on a risk-flagged payment

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_PARAMS = ResponseParams()

# Organic (no-agent) recovery: customer retries on their own / pending settles.
# Directional, from public reporting that a minority self-retry; debited-
# pending payments mostly settle without anyone acting. ASSUMPTIONS.
ORGANIC_RECOVERY = {
    "bank_decline": 0.14,
    "insufficient_funds": 0.10,
    "auth_3ds_drop": 0.15,
    "expired_mandate": 0.04,
    "wrong_vpa": 0.12,
    "gateway_timeout": 0.20,
    "fraud_hold": 0.00,
    "debited_pending": 0.45,
    "bank_outage": 0.18,
    "upi_daily_limit": 0.16,
    "intent_drop": 0.12,
    "card_expired": 0.06,
}

# Additional recovery probability when the policy-correct action is taken.
MATCHED_UPLIFT = {
    "bank_decline": 0.12,
    "insufficient_funds": 0.14,
    "auth_3ds_drop": 0.18,
    "expired_mandate": 0.30,
    "wrong_vpa": 0.22,
    "gateway_timeout": 0.15,
    "fraud_hold": 0.00,
    "debited_pending": 0.10,
    "bank_outage": 0.16,
    "upi_daily_limit": 0.14,
    "intent_drop": 0.14,
    "card_expired": 0.22,
}
assert set(ORGANIC_RECOVERY) == set(CAUSES) == set(MATCHED_UPLIFT)

# Typical hours until the money lands, by action (organic = the customer
# eventually retries on their own).
TIME_TO_RECOVERY_HOURS = {
    "retry_now": 0.5,
    "retry_alternate_method": 2.0,
    "send_payment_link": 6.0,
    "verify_then_reassure": 12.0,
    "send_reauth_mandate_link": 24.0,
    "escalate_human": 36.0,
    "retry_delayed": 48.0,
    "refund": 0.0,
    "no_action": 72.0,
}
P_CAP = 0.95


def _share(true_cause: str, action: str, params: ResponseParams) -> float:
    if action == "no_action" or action == "refund":
        return 0.0
    if true_cause in NEVER_RETRY_CAUSES and action in RETRY_SHAPED_ACTIONS:
        return 0.0                      # a retry adds nothing to an already-debited payment
    if action == CAUSE_ACTION_POLICY[true_cause]:
        return 1.0
    if action == "escalate_human":
        return params.human_share
    return params.generic_share


def recovery_probability(true_cause: str, action: str, prior_contacts: int,
                         params: ResponseParams = DEFAULT_PARAMS) -> float:
    if true_cause == "fraud_hold":
        return 0.0
    organic = min(P_CAP, ORGANIC_RECOVERY[true_cause] * params.organic_scale)
    if action == "no_action":
        return organic
    uplift = MATCHED_UPLIFT[true_cause] * params.advantage_scale
    fatigue = params.fatigue_decay ** max(0, prior_contacts)
    return min(P_CAP, organic + _share(true_cause, action, params) * uplift * fatigue)


def complaint_probability(true_cause: str, action: str, prior_contacts: int,
                          params: ResponseParams = DEFAULT_PARAMS) -> float:
    if action == "no_action":
        return 0.0                      # nobody was contacted
    p = params.base_complaint + params.fatigue_complaint_bump * max(0, prior_contacts)
    if true_cause == "fraud_hold" and action != "escalate_human":
        p += params.fraud_contact_complaint
    if true_cause == "debited_pending" and action in RETRY_SHAPED_ACTIONS:
        p += params.wrong_never_retry_complaint
    return min(0.90, p)


def simulate_outcome(
    true_cause: str,
    action: str,
    prior_contacts: int,
    rng: random.Random,
    params: ResponseParams | None = None,
) -> dict:
    """
    prior_contacts = contacts already made to this customer in the active
    window BEFORE this action (fatigue). Draw order is fixed (recovery,
    complaint, timing) so common-random-number comparisons across lines
    stay valid.
    """
    params = params or DEFAULT_PARAMS
    assert action in ACTIONS, action

    p_rec = recovery_probability(true_cause, action, prior_contacts, params)
    p_cmp = complaint_probability(true_cause, action, prior_contacts, params)

    u_rec = rng.random()
    u_cmp = rng.random()
    u_time = rng.random()

    recovered = (action != "refund") and (u_rec < p_rec)
    complaint = u_cmp < p_cmp
    hours = None
    if recovered:
        hours = round(TIME_TO_RECOVERY_HOURS[action] * (0.6 + 0.8 * u_time), 1)

    return {
        "recovered": recovered,
        "complaint": complaint,
        "time_to_recovery_hours": hours,
        "goodwill_saved": (action == "refund" and true_cause == "debited_pending"),
        "chargeback_risk": (true_cause == "fraud_hold" and action not in ("escalate_human", "no_action")),
    }


def describe(params: ResponseParams = DEFAULT_PARAMS) -> dict:
    """Everything a reader needs to reproduce the physics — for RESPONSE_MODEL.md and the run manifest."""
    return {
        "params": params.to_dict(),
        "organic_recovery": ORGANIC_RECOVERY,
        "matched_uplift": MATCHED_UPLIFT,
        "time_to_recovery_hours": TIME_TO_RECOVERY_HOURS,
        "p_cap": P_CAP,
    }