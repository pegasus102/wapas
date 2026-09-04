"""
wapas.response_model
---------------------
This is the "physics" of the simulator: given a true hidden cause and an
action taken, what is the probability the payment gets recovered, and what
is the probability the customer complains / unsubscribes?

Every number here is a documented ASSUMPTION, not a measurement. That's
unavoidable for a synthetic simulation — the honest response to "isn't this
just your simulator?" is (a) publish every knob, (b) show where the result
stops holding if the knob moves. See RESPONSE_MODEL.md and
measurement.sensitivity for (b).

Design rules encoded here, matching the thesis:
  1. The MATCHED action (oracle-correct for that cause) recovers more often
     than any mismatched action — that's the entire hypothesis under test.
  2. Contact fatigue: each extra contact on the same customer reduces the
     marginal recovery probability and raises complaint probability.
  3. no_action still recovers sometimes (organic/self-retry) — the control
     arm is not a strawman zero.
  4. Acting on a never-retry cause (fraud_hold, debited_pending) as if it
     were retryable barely helps and disproportionately raises complaints.
"""

from __future__ import annotations
import random
from .schema import CAUSES, ACTIONS, ORACLE_ACTION, NEVER_RETRY_CAUSES

# ---------------------------------------------------------------------------
# Base organic recovery rate (customer retries on their own, no agent action)
# Source: directional, from industry reporting that a minority of failed-
# payment customers self-retry without prompting. Documented as an ASSUMPTION.
# ---------------------------------------------------------------------------
BASE_ORGANIC_RECOVERY = 0.14

# Recovery probability uplift multiplier for a MATCHED action (oracle-correct
# for the true cause) vs a mismatched-but-plausible action.
# This is the single most important number in the whole simulator: it is the
# knob measurement.sensitivity sweeps to find the break-even point.
MATCHED_ACTION_MULTIPLIER = 1.6

# Mismatched-but-harmless action multiplier (e.g. a generic retry on a
# bank_decline when the "right" answer was retry_delayed) — still helps a
# little over doing nothing.
MISMATCHED_ACTION_MULTIPLIER = 1.15

# Acting on a never-retry cause with a retry-shaped action: barely helps,
# and is exactly what raises complaints (see COMPLAINT_PROB below).
WRONG_ON_NEVER_RETRY_MULTIPLIER = 1.05

# Contact fatigue: recovery probability decays and complaint probability
# rises with each additional contact on the same customer within the window.
CONTACT_FATIGUE_DECAY = 0.85     # multiplies recovery prob per extra contact
CONTACT_FATIGUE_COMPLAINT_BUMP = 0.03  # additive complaint prob per extra contact

# Base complaint/unsubscribe probability per contact, and the penalty for
# a retry-shaped action landing on a never-retry cause.
BASE_COMPLAINT_PROB = 0.02
WRONG_NEVER_RETRY_COMPLAINT_PENALTY = 0.22

RETRY_SHAPED_ACTIONS = {"retry_now", "retry_delayed", "retry_alternate_method"}

# Human escalation multiplier: a human agent who actually investigates an
# edge case is assumed to be COMPETENT (roughly as effective as a matched
# automated action) but slower to engage than an automated retry/link —
# reflected in time_to_recovery in a fuller build, not in this probability.
# Without this, routing a hard case to a human would be modelled as if a
# human were no better than a random guess, which is not a credible
# assumption and would perversely penalise the system for being cautious.
HUMAN_ESCALATION_MULTIPLIER = 1.45


def _action_multiplier(true_cause: str, action: str) -> float:
    oracle = ORACLE_ACTION[true_cause]
    if action == "no_action":
        return 1.0
    if true_cause in NEVER_RETRY_CAUSES and action in RETRY_SHAPED_ACTIONS:
        return WRONG_ON_NEVER_RETRY_MULTIPLIER
    if action == oracle:
        return MATCHED_ACTION_MULTIPLIER
    return MISMATCHED_ACTION_MULTIPLIER


def simulate_outcome(
    true_cause: str,
    action: str,
    prior_contacts: int,
    rng: random.Random,
    matched_multiplier: float = MATCHED_ACTION_MULTIPLIER,
    mismatched_multiplier: float = MISMATCHED_ACTION_MULTIPLIER,
    base_organic: float = BASE_ORGANIC_RECOVERY,
) -> dict:
    """
    Returns {"recovered": bool, "complaint": bool, "net_value_multiplier": float}
    prior_contacts = number of PRIOR contacts already made to this customer
    in the active window (used for fatigue). Does not include this contact.
    """
    if action == "no_action":
        p_recover = base_organic
    else:
        if true_cause in NEVER_RETRY_CAUSES and action in RETRY_SHAPED_ACTIONS:
            mult = WRONG_ON_NEVER_RETRY_MULTIPLIER
        elif action == ORACLE_ACTION[true_cause]:
            mult = matched_multiplier
        elif action == "escalate_human":
            mult = HUMAN_ESCALATION_MULTIPLIER
        else:
            mult = mismatched_multiplier
        p_recover = min(0.95, base_organic * mult)
        p_recover *= CONTACT_FATIGUE_DECAY ** prior_contacts

    complaint_prob = BASE_COMPLAINT_PROB + CONTACT_FATIGUE_COMPLAINT_BUMP * prior_contacts
    if action != "no_action" and true_cause in NEVER_RETRY_CAUSES and action in RETRY_SHAPED_ACTIONS:
        complaint_prob += WRONG_NEVER_RETRY_COMPLAINT_PENALTY

    recovered = rng.random() < p_recover
    complaint = rng.random() < min(0.9, complaint_prob)
    return {"recovered": recovered, "complaint": complaint}
