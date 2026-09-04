"""
wapas.schema
------------
Single source of truth for the FIXED taxonomy of the system:
  - the 12 hidden ground-truth causes
  - the evidence packet (Razorpay-shaped) — the ONLY thing the detector,
    rules tier, diagnosis agent and policy gate ever see
  - the fixed action menu (the LLM may only ever pick from this list)
  - the cause -> action policy table
  - the asymmetric confusion-cost matrix used by eval

Nothing in this file is randomised. All randomness lives in
data_foundry.py and response_model.py, so the taxonomy is a fixed,
auditable contract.

A note on CAUSE_ACTION_POLICY: it is a *policy table* ("if the cause is X,
the right action is Y"). The live pipeline applies it to the PREDICTED
cause; the oracle line applies the same table to the TRUE cause. Using the
same table in both places is not ground-truth leakage — it is what makes
the oracle a fair ceiling (same policy, perfect diagnosis).
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# 1. Hidden ground-truth causes
# ---------------------------------------------------------------------------
CAUSES = [
    "bank_decline",
    "insufficient_funds",
    "auth_3ds_drop",
    "expired_mandate",
    "wrong_vpa",
    "gateway_timeout",
    "fraud_hold",
    "debited_pending",
    "bank_outage",
    "upi_daily_limit",
    "intent_drop",
    "card_expired",
]

# Causes where a retry is actively harmful (double-charge / contacting a
# risk-flagged customer). The policy gate enforces these as HARD rules
# using EVIDENCE fields only — never the hidden cause.
NEVER_RETRY_CAUSES = {"fraud_hold", "debited_pending"}

# ---------------------------------------------------------------------------
# 2. Fixed action menu
# ---------------------------------------------------------------------------
ACTIONS = [
    "retry_now",
    "retry_delayed",
    "retry_alternate_method",
    "send_payment_link",
    "send_reauth_mandate_link",
    "verify_then_reassure",
    "refund",
    "escalate_human",
    "no_action",
]
RETRY_SHAPED_ACTIONS = {"retry_now", "retry_delayed", "retry_alternate_method"}
LINK_ACTIONS = {"send_payment_link", "send_reauth_mandate_link"}

# ---------------------------------------------------------------------------
# 3. Cause -> action policy table
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 4. Razorpay-shaped error vocabulary
#    error_code / error_source / error_step follow the shape of Razorpay's
#    payment entity error fields. error_reason values are this project's
#    coarse buckets (several causes deliberately SHARE a reason).
# ---------------------------------------------------------------------------
ERROR_CODES = ["BAD_REQUEST_ERROR", "GATEWAY_ERROR", "SERVER_ERROR"]
ERROR_SOURCES = ["bank", "customer", "gateway", "business", "internal"]
ERROR_STEPS = [
    "payment_initiation",
    "payment_authentication",
    "payment_authorization",
    "payment_capture",
]
ERROR_REASONS = [
    "BANK_DECLINED",                 # shared: bank_decline / bank_outage / upi_daily_limit
    "PAYMENT_FAILED",                # shared: intent_drop / auth_3ds_drop / wrong_vpa / debited_pending
    "INSUFFICIENT_FUNDS",
    "AUTHENTICATION_FAILED",
    "MANDATE_EXPIRED",
    "INVALID_VPA",
    "GATEWAY_TIMEOUT",
    "RISK_BLOCKED",
    "PAYMENT_PENDING_CONFIRMATION",
    "CARD_EXPIRED",
]
AMBIGUOUS_REASONS = {"BANK_DECLINED", "PAYMENT_FAILED"}

# ---------------------------------------------------------------------------
# 5. Cost-weighted confusion (asymmetric on purpose — see RESPONSE_MODEL.md)
# ---------------------------------------------------------------------------
def confusion_cost(true_cause: str, predicted_cause: str) -> float:
    if true_cause == predicted_cause:
        return 0.0
    # Treating a never-retry cause as retryable is the worst mistake in this
    # domain: double-charge, or contacting a risk-flagged customer.
    if true_cause in NEVER_RETRY_CAUSES and predicted_cause not in NEVER_RETRY_CAUSES:
        return 10.0
    # The over-cautious mistake is cheap.
    if predicted_cause in NEVER_RETRY_CAUSES and true_cause not in NEVER_RETRY_CAUSES:
        return 2.0
    return 1.0


# ---------------------------------------------------------------------------
# 6. Evidence packet. `true_cause` deliberately lives OUTSIDE this class, in
#    the generator's ground-truth tuple, so leakage is a type-level
#    impossibility rather than a discipline problem.
# ---------------------------------------------------------------------------
@dataclass
class EvidencePacket:
    event_id: str
    customer_id: str
    invoice_id: str
    attempt_no: int
    amount: float
    method: str                    # upi | card | netbanking
    geo_tier: str                  # metro | tier2 | tier3
    timestamp_ist: str             # ISO8601 WITH +05:30 offset
    tenure_days: int
    mandate_status: str            # none | active | expired
    retry_count: int
    error_code: str                # BAD_REQUEST_ERROR | GATEWAY_ERROR | SERVER_ERROR
    error_source: str              # bank | customer | gateway | business | internal
    error_reason: str              # coarse bucket, sometimes ambiguous by design
    error_step: str                # payment_initiation | _authentication | _authorization | _capture
    bank_health_score: float       # 0..1, rolling 15-min bank/PSP health proxy (1 = healthy)
    attempts_today: int
    debit_confirmation_flag: bool  # noisy: bank says money WAS debited
    free_text: Optional[str] = None      # customer/support note, Hinglish OK
    predebit_notified: bool = False      # RBI e-mandate pre-debit notification sent (active mandates only)
    is_subscription: bool = False
    value_band: str = "mid"              # low | mid | high (derived from amount)
    # detector-derived (filled by detector.annotate)
    is_repeat_failure: bool = False
    is_ambiguous_reason: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def event_time(self) -> datetime:
        """Timezone-aware IST datetime of the failed attempt."""
        return datetime.fromisoformat(self.timestamp_ist).astimezone(IST)