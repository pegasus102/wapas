"""
wapas.schema
------------
Single source of truth for the FIXED taxonomy of the system:
  - the 12 hidden ground-truth causes
  - the evidence packet (Razorpay-shaped) — the ONLY thing the detector,
    rules tier, diagnosis agent and policy gate ever see
  - the fixed action menu (the LLM may only ever pick from this list)
  - the cause -> action policy table, and each action's INTENT
  - the asymmetric confusion-cost matrix used by eval

Nothing in this file is randomised.

CAUSE_ACTION_POLICY is a *policy table* ("if the cause is X, the right
action is Y"). The live pipeline applies it to the PREDICTED cause; the
oracle line applies the same table to the TRUE cause. Same table, perfect
diagnosis = a fair ceiling, not leakage.

INTENTS: the authority ladder often cannot execute the policy action as
written (no mandate -> no pull). It downgrades to a payment link, but the
link keeps the action's intent: an immediate link, a link SCHEDULED for
later, or a link with METHOD FALLBACK. The response model scores what was
actually executed by its intent, so diagnosis survives the downgrade.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

CAUSES = [
    "bank_decline", "insufficient_funds", "auth_3ds_drop", "expired_mandate",
    "wrong_vpa", "gateway_timeout", "fraud_hold", "debited_pending",
    "bank_outage", "upi_daily_limit", "intent_drop", "card_expired",
]
NEVER_RETRY_CAUSES = {"fraud_hold", "debited_pending"}

ACTIONS = [
    "retry_now", "retry_delayed", "retry_alternate_method",
    "send_payment_link", "send_reauth_mandate_link",
    "verify_then_reassure", "refund", "escalate_human", "no_action",
]
RETRY_SHAPED_ACTIONS = {"retry_now", "retry_delayed", "retry_alternate_method"}
LINK_ACTIONS = {"send_payment_link", "send_reauth_mandate_link"}
CHARGE_SHAPED = RETRY_SHAPED_ACTIONS | LINK_ACTIONS   # anything that could move money again

CAUSE_ACTION_POLICY = {
    "bank_decline": "retry_now",
    "insufficient_funds": "retry_delayed",
    "auth_3ds_drop": "send_payment_link",
    "expired_mandate": "send_reauth_mandate_link",
    "wrong_vpa": "send_payment_link",
    "gateway_timeout": "retry_now",
    "fraud_hold": "escalate_human",
    "debited_pending": "verify_then_reassure",
    "bank_outage": "retry_delayed",
    "upi_daily_limit": "retry_alternate_method",
    "intent_drop": "send_payment_link",
    "card_expired": "send_payment_link",
}
ORACLE_ACTION = CAUSE_ACTION_POLICY  # backward-compatible alias

# --- intents ---------------------------------------------------------------
LINK_VARIANTS = ["immediate", "scheduled", "method_fallback"]
ACTION_INTENTS = {
    "retry_now": {"now"},
    "retry_delayed": {"delayed"},
    "retry_alternate_method": {"alt_method"},
    "send_reauth_mandate_link": {"reauth"},
    "verify_then_reassure": {"verify"},
    "refund": {"refund"},
    "escalate_human": {"human"},
    "no_action": set(),
}
LINK_VARIANT_INTENTS = {
    "immediate": {"now"},
    "scheduled": {"delayed"},
    "method_fallback": {"now", "alt_method"},   # a fallback link also lets the customer pay now
}


def action_intents(action: str, variant: Optional[str] = None) -> set[str]:
    if action == "send_payment_link":
        return set(LINK_VARIANT_INTENTS[variant or "immediate"])
    return set(ACTION_INTENTS[action])


CAUSE_IDEAL_INTENT = {c: next(iter(action_intents(a))) for c, a in CAUSE_ACTION_POLICY.items()}

# --- Razorpay-shaped error vocabulary ---------------------------------------
ERROR_CODES = ["BAD_REQUEST_ERROR", "GATEWAY_ERROR", "SERVER_ERROR"]
ERROR_SOURCES = ["bank", "customer", "gateway", "business", "internal"]
ERROR_STEPS = ["payment_initiation", "payment_authentication", "payment_authorization", "payment_capture"]
ERROR_REASONS = [
    "BANK_DECLINED", "PAYMENT_FAILED", "INSUFFICIENT_FUNDS", "AUTHENTICATION_FAILED",
    "MANDATE_EXPIRED", "INVALID_VPA", "GATEWAY_TIMEOUT", "RISK_BLOCKED",
    "PAYMENT_PENDING_CONFIRMATION", "CARD_EXPIRED",
]
AMBIGUOUS_REASONS = {"BANK_DECLINED", "PAYMENT_FAILED"}


def confusion_cost(true_cause: str, predicted_cause: str) -> float:
    if true_cause == predicted_cause:
        return 0.0
    if true_cause in NEVER_RETRY_CAUSES and predicted_cause not in NEVER_RETRY_CAUSES:
        return 10.0
    if predicted_cause in NEVER_RETRY_CAUSES and true_cause not in NEVER_RETRY_CAUSES:
        return 2.0
    return 1.0


@dataclass
class EvidencePacket:
    event_id: str
    customer_id: str
    invoice_id: str
    attempt_no: int
    amount: float
    method: str
    geo_tier: str
    timestamp_ist: str
    tenure_days: int
    mandate_status: str
    retry_count: int
    error_code: str
    error_source: str
    error_reason: str
    error_step: str
    bank_health_score: float
    attempts_today: int
    debit_confirmation_flag: bool
    free_text: Optional[str] = None
    predebit_notified: bool = False
    is_subscription: bool = False
    value_band: str = "mid"
    is_repeat_failure: bool = False
    is_ambiguous_reason: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def event_time(self) -> datetime:
        return datetime.fromisoformat(self.timestamp_ist).astimezone(IST)