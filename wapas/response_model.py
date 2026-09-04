"""
wapas.response_model
---------------------
The "physics" of the simulator: given the TRUE hidden cause and what was
ACTUALLY executed, P(recovered) and P(complaint). Every number is a
documented ASSUMPTION (see CURE_MATRIX comments + RESPONSE_MODEL notes in
README); `make sensitivity` sweeps them.

    p_recover = organic[cause]
              + advantage_scale * uplift[cause] * CURE[cause][profile] * fit * fatigue_decay**prior_contacts

The cure fraction answers ONE question with a number: if you execute this
kind of action against this cause, what fraction of the achievable uplift
do you capture? It encodes three mechanics that intent-coverage alone
cannot express:

  1. CHANNEL: a PULL re-fires the stored instrument; a LINK makes the
     customer act (re-enter details, pick a method, re-authorize). A link
     can fix bad credentials (wrong VPA, expired card); a pull cannot.
  2. TIMING: for cash-timing causes (insufficient_funds) and transient
     system causes (bank_outage, upi_daily_limit), WHEN you act dominates
     HOW you act. Acting now fails; acting after salary/repair/reset works.
  3. CREDENTIAL: for wrong_vpa / card_expired / expired_mandate, re-firing
     the same instrument is near-useless no matter the intent.

`fit` = message/action-targeting: executing the exact action the cause's
policy prescribes scores 1.0; an action that lands on the same execution
profile but was chosen blind (generic templated messaging, no diagnosis)
scores FIT_PENALTY (0.85) — generic dunning converts worse than targeted
recovery even when the mechanics are right (well-documented in dunning
practice). This is deliberately mild: the floor must not be a strawman.

fraud_hold never recovers; its only good outcome is doing no harm.
Complaints only when someone is contacted; rise with fatigue; spike for a
charge attempt on a debited payment; spike for re-charging an abandoned
checkout (intent_drop) — nobody likes being auto-charged for a cart they
left; spike hardest for contacting a risk-flagged customer.
"""

from __future__ import annotations
import random
from dataclasses import dataclass, asdict

from .schema import (CAUSES, ACTIONS, CAUSE_ACTION_POLICY, RETRY_SHAPED_ACTIONS,
                     CHARGE_SHAPED)

# Execution profiles — the (channel, timing, credential) shape of what was
# actually executed, after the gate's authority ladder did its (honest,
# consent-driven) conversions.
PROFILES = [
    "pull_now",       # auto re-fire, same instrument, now          (retry_now; link a customer pays immediately is NOT this)
    "pull_delayed",   # auto re-fire, same instrument, later       (retry_delayed)
    "pull_alt",       # auto re-fire, different stored instrument  (retry_alternate_method)
    "link_now",       # customer-facing link, pay now, re-enter details (send_payment_link / immediate)
    "link_sched",     # customer-facing link, timed later          (send_payment_link / scheduled)
    "link_fb",        # customer-facing link, pay now, choose any method (send_payment_link / method_fallback)
    "reauth_link",    # mandate re-authorization link              (send_reauth_mandate_link)
    "verify",         # human-in-loop verification, no charge      (verify_then_reassure)
    "human",          # human agent owns the case                  (escalate_human)
    "none",           # refund / no_action
]

ACTION_PROFILE = {
    "retry_now": "pull_now",
    "retry_delayed": "pull_delayed",
    "retry_alternate_method": "pull_alt",
    "send_reauth_mandate_link": "reauth_link",
    "verify_then_reassure": "verify",
    "refund": "none",
    "escalate_human": "human",
    "no_action": "none",
}


def execution_profile(action: str, variant: str | None) -> str:
    if action == "send_payment_link":
        return {"immediate": "link_now", "scheduled": "link_sched",
                "method_fallback": "link_fb"}.get(variant or "immediate", "link_now")
    return ACTION_PROFILE[action]


# CURE[cause][profile] — fraction of the cause's max achievable uplift.
# Column commentary (rows below) documents every assumption:
#   bank_decline      soft decline; pull-now when healthy is ideal (1.0);
#                     a link re-asks the same bank -> weaker (0.55), though
#                     picking another instrument helps some (0.65)
#   insufficient_funds pure cash timing: anything NOW fails (0.25-0.30);
#                     anything AFTER salary lands works (1.0)
#   auth_3ds_drop     sticky auth session: a fresh link re-starts it (1.0);
#                     re-firing the same session often re-drops (0.55)
#   expired_mandate   only re-authorization fully works (1.0); a one-time
#                     link recovers this payment but not the mandate (0.45);
#                     pulls hit the dead mandate (0.05-0.10)
#   wrong_vpa         the stored VPA is WRONG: pulls re-fire it (0.05); any
#                     customer-entered link fixes it (1.0 / 0.85 sched)
#   gateway_timeout   transient: pull-now is ideal (1.0); link also fine (0.80)
#   fraud_hold        nothing recovers; do no harm
#   debited_pending   never re-charge (handled separately); verify reassure
#   bank_outage       timing dominates: after restoration (1.0); now fails (0.25);
#                     another bank via link_fb partially escapes (0.55)
#   upi_daily_limit   limit resets at midnight OR another instrument works:
#                     delayed (0.85), alt-method (1.0), same-instrument now (0.20)
#   intent_drop       customer abandoned checkout: a customer-initiated link
#                     is right (1.0); an AUTO-PULL for an abandoned cart is
#                     near-wrong (0.15) and complaint-worthy
#   card_expired      the stored card is dead: pulls fail (0.05-0.65 alt);
#                     customer-entered fresh instrument works (0.95-1.0)
CURE_MATRIX = {
    "bank_decline":       {"pull_now": 1.00, "pull_delayed": 0.75, "pull_alt": 0.65,
                           "link_now": 0.55, "link_sched": 0.70, "link_fb": 0.55,
                           "reauth_link": 0.55, "verify": 0.10, "human": 0.70, "none": 0.0},
    "insufficient_funds": {"pull_now": 0.25, "pull_delayed": 1.00, "pull_alt": 0.40,
                           "link_now": 0.30, "link_sched": 1.00, "link_fb": 0.30,
                           "reauth_link": 0.30, "verify": 0.10, "human": 0.60, "none": 0.0},
    "auth_3ds_drop":      {"pull_now": 0.55, "pull_delayed": 0.45, "pull_alt": 0.60,
                           "link_now": 1.00, "link_sched": 0.80, "link_fb": 1.00,
                           "reauth_link": 0.60, "verify": 0.10, "human": 0.65, "none": 0.0},
    "expired_mandate":    {"pull_now": 0.05, "pull_delayed": 0.10, "pull_alt": 0.35,
                           "link_now": 0.45, "link_sched": 0.45, "link_fb": 0.50,
                           "reauth_link": 1.00, "verify": 0.10, "human": 0.70, "none": 0.0},
    "wrong_vpa":          {"pull_now": 0.05, "pull_delayed": 0.05, "pull_alt": 0.60,
                           "link_now": 1.00, "link_sched": 0.85, "link_fb": 1.00,
                           "reauth_link": 0.85, "verify": 0.10, "human": 0.70, "none": 0.0},
    "gateway_timeout":    {"pull_now": 1.00, "pull_delayed": 0.70, "pull_alt": 0.75,
                           "link_now": 0.80, "link_sched": 0.65, "link_fb": 0.80,
                           "reauth_link": 0.70, "verify": 0.10, "human": 0.70, "none": 0.0},
    "fraud_hold":         {p: 0.0 for p in PROFILES},
    "debited_pending":    {"pull_now": 0.0, "pull_delayed": 0.0, "pull_alt": 0.0,
                           "link_now": 0.0, "link_sched": 0.0, "link_fb": 0.0,
                           "reauth_link": 0.0, "verify": 1.00, "human": 0.80, "none": 0.0},
    "bank_outage":        {"pull_now": 0.25, "pull_delayed": 1.00, "pull_alt": 0.50,
                           "link_now": 0.30, "link_sched": 1.00, "link_fb": 0.55,
                           "reauth_link": 0.30, "verify": 0.10, "human": 0.65, "none": 0.0},
    "upi_daily_limit":    {"pull_now": 0.20, "pull_delayed": 0.85, "pull_alt": 1.00,
                           "link_now": 0.35, "link_sched": 0.85, "link_fb": 1.00,
                           "reauth_link": 0.35, "verify": 0.10, "human": 0.65, "none": 0.0},
    "intent_drop":        {"pull_now": 0.15, "pull_delayed": 0.35, "pull_alt": 0.40,
                           "link_now": 1.00, "link_sched": 0.70, "link_fb": 0.90,
                           "reauth_link": 0.60, "verify": 0.10, "human": 0.60, "none": 0.0},
    "card_expired":       {"pull_now": 0.05, "pull_delayed": 0.05, "pull_alt": 0.65,
                           "link_now": 0.95, "link_sched": 0.80, "link_fb": 1.00,
                           "reauth_link": 0.80, "verify": 0.10, "human": 0.70, "none": 0.0},
}
assert set(CURE_MATRIX) == set(CAUSES)
for _c, _row in CURE_MATRIX.items():
    assert set(_row) == set(PROFILES), _c


@dataclass(frozen=True)
class ResponseParams:
    advantage_scale: float = 1.0
    fit_penalty: float = 0.85          # blind-but-right-profile vs targeted
    human_share: float = 1.00          # cure matrix already encodes human skill per cause
    fatigue_decay: float = 0.85
    organic_scale: float = 1.0
    base_complaint: float = 0.02
    fatigue_complaint_bump: float = 0.03
    wrong_never_retry_complaint: float = 0.22
    fraud_contact_complaint: float = 0.50
    abandoned_pull_complaint: float = 0.18   # auto-charge on an abandoned checkout

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_PARAMS = ResponseParams()

ORGANIC_RECOVERY = {
    "bank_decline": 0.14, "insufficient_funds": 0.10, "auth_3ds_drop": 0.15,
    "expired_mandate": 0.04, "wrong_vpa": 0.12, "gateway_timeout": 0.20,
    "fraud_hold": 0.00, "debited_pending": 0.45, "bank_outage": 0.18,
    "upi_daily_limit": 0.16, "intent_drop": 0.12, "card_expired": 0.06,
}
MATCHED_UPLIFT = {
    "bank_decline": 0.12, "insufficient_funds": 0.14, "auth_3ds_drop": 0.18,
    "expired_mandate": 0.30, "wrong_vpa": 0.22, "gateway_timeout": 0.15,
    "fraud_hold": 0.00, "debited_pending": 0.10, "bank_outage": 0.16,
    "upi_daily_limit": 0.14, "intent_drop": 0.14, "card_expired": 0.22,
}
assert set(ORGANIC_RECOVERY) == set(CAUSES) == set(MATCHED_UPLIFT)

# Hours from EXECUTION to money landing. The gate's scheduling (48h for a
# delayed intent, quiet-hour deferral) is added on top by the executor.
TIME_TO_RECOVERY_HOURS = {
    "retry_now": 0.5, "retry_delayed": 0.5, "retry_alternate_method": 2.0,
    "send_payment_link": 6.0, "verify_then_reassure": 12.0,
    "send_reauth_mandate_link": 24.0, "escalate_human": 36.0,
    "refund": 0.0, "no_action": 72.0,
}
P_CAP = 0.95


def _is_policy_action(true_cause: str, action: str) -> bool:
    """True when the executed action is exactly what the cause's policy
    prescribes (targeted recovery), as opposed to a blind action that merely
    lands on a compatible profile."""
    if action == "send_payment_link":
        return CAUSE_ACTION_POLICY[true_cause] == "send_payment_link"
    return action == CAUSE_ACTION_POLICY[true_cause]


# Consent downgrades preserve TARGETING: when the authority ladder converts a
# prescribed pull into the customer-approved link that carries the same intent
# (now / delayed / alternate-method), what was executed IS the targeted
# intervention — the customer just approves it live instead of being pulled.
# A blind action that lands on the same profile by luck is different: generic
# templated messaging converts worse than targeted recovery (FIT_PENALTY).
PROFILE_FIT_CONSENT_PAIRS = {
    # (prescribed profile -> executed profile after authority ladder)
    frozenset({"pull_now", "link_now"}),          # retry_now      -> immediate link
    frozenset({"pull_delayed", "link_sched"}),    # retry_delayed  -> scheduled link
    frozenset({"pull_alt", "link_fb"}),           # retry_alt      -> method-fallback link
}


def _fit(true_cause: str, action: str, params: ResponseParams, variant: str | None) -> float:
    prescribed_profile = execution_profile(CAUSE_ACTION_POLICY[true_cause], None)
    executed = execution_profile(action, variant)
    if prescribed_profile == executed:
        return 1.0
    if frozenset({prescribed_profile, executed}) in PROFILE_FIT_CONSENT_PAIRS:
        return 1.0
    # near-miss within the link family (method-fallback vs plain link): the
    # intervention family is right, the targeting is partial
    if {prescribed_profile, executed} <= {"link_now", "link_sched", "link_fb", "reauth_link"}:
        return min(1.0, params.fit_penalty + 0.07)
    return params.fit_penalty


def recovery_probability(true_cause: str, action: str, prior_contacts: int,
                         params: ResponseParams = DEFAULT_PARAMS, variant: str | None = None) -> float:
    if true_cause == "fraud_hold":
        return 0.0
    organic = min(P_CAP, ORGANIC_RECOVERY[true_cause] * params.organic_scale)
    if action == "no_action":
        return organic
    if true_cause == "debited_pending" and action in CHARGE_SHAPED:
        return organic                      # never re-charge a confirmed debit
    cure = CURE_MATRIX[true_cause][execution_profile(action, variant)]
    if action == "escalate_human":
        cure = cure * params.human_share
    uplift = MATCHED_UPLIFT[true_cause] * params.advantage_scale
    fatigue = params.fatigue_decay ** max(0, prior_contacts)
    p = organic + uplift * cure * _fit(true_cause, action, params, variant) * fatigue
    return min(P_CAP, p)


def complaint_probability(true_cause: str, action: str, prior_contacts: int,
                          params: ResponseParams = DEFAULT_PARAMS) -> float:
    if action == "no_action":
        return 0.0
    p = params.base_complaint + params.fatigue_complaint_bump * max(0, prior_contacts)
    if true_cause == "fraud_hold" and action != "escalate_human":
        p += params.fraud_contact_complaint
    if true_cause == "debited_pending" and action in CHARGE_SHAPED:
        p += params.wrong_never_retry_complaint
    if true_cause == "intent_drop" and action in RETRY_SHAPED_ACTIONS:
        p += params.abandoned_pull_complaint
    return min(0.90, p)


def simulate_outcome(true_cause: str, action: str, prior_contacts: int, rng: random.Random,
                     params: ResponseParams | None = None, variant: str | None = None) -> dict:
    params = params or DEFAULT_PARAMS
    assert action in ACTIONS, action
    p_rec = recovery_probability(true_cause, action, prior_contacts, params, variant)
    p_cmp = complaint_probability(true_cause, action, prior_contacts, params)
    u_rec, u_cmp, u_time = rng.random(), rng.random(), rng.random()
    recovered = (action != "refund") and (u_rec < p_rec)
    hours = round(TIME_TO_RECOVERY_HOURS[action] * (0.6 + 0.8 * u_time), 1) if recovered else None
    return {
        "recovered": recovered,
        "complaint": u_cmp < p_cmp,
        "time_to_recovery_hours": hours,
        "goodwill_saved": (action == "refund" and true_cause == "debited_pending"),
        "chargeback_risk": (true_cause == "fraud_hold" and action not in ("escalate_human", "no_action")),
    }


def describe(params: ResponseParams = DEFAULT_PARAMS) -> dict:
    return {
        "params": params.to_dict(),
        "organic_recovery": ORGANIC_RECOVERY,
        "matched_uplift": MATCHED_UPLIFT,
        "cure_matrix": CURE_MATRIX,
        "execution_profiles": PROFILES,
        "fit_penalty": params.fit_penalty,
        "time_to_recovery_hours": TIME_TO_RECOVERY_HOURS,
        "p_cap": P_CAP,
    }
