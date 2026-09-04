"""
wapas.schema
------------
Single source of truth for:
  - the 12 hidden ground-truth causes
  - the Razorpay-shaped evidence packet fields
  - the FIXED action menu (the LLM may only ever pick from this list)
  - the oracle cause -> correct-action map (used ONLY by measurement/eval,
    never by the diagnosis or gate code — that would be ground-truth leakage)

Nothing in this file is randomised. All randomness lives in data_foundry.py
and response_model.py so the taxonomy itself is a fixed, auditable contract.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional

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

# Causes where retrying is actively harmful (double-charge / contacting a
# fraud hold / burning goodwill). The policy gate enforces these as HARD
# never-retry rules using EVIDENCE fields only (never the hidden cause).
NEVER_RETRY_CAUSES = {"fraud_hold", "debited_pending"}

# ---------------------------------------------------------------------------
# 2. The fixed action menu — the ONLY actions any policy in this system may
#    take. The LLM (or rules tier) picks one of these; it cannot invent one.
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

# ---------------------------------------------------------------------------
# 3. Oracle map: the "correct" action IF the cause were known with certainty.
#    Used only by measurement.oracle() and eval — a controlled-experiment
#    scoring device, not something the live pipeline is allowed to see.
# ---------------------------------------------------------------------------
ORACLE_ACTION = {
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

# ---------------------------------------------------------------------------
# 4. Cost-weighted confusion cost matrix (eval/confusion.py).
#    Rows = true cause, cols = predicted cause. Only the "dangerous"
#    confusions are weighted above 1; everything else defaults to 1.
#    This is a documented ASSUMPTION (see RESPONSE_MODEL.md) — the specific
#    numbers are illustrative, the STRUCTURE (asymmetric cost) is the point.
# ---------------------------------------------------------------------------
def confusion_cost(true_cause: str, predicted_cause: str) -> float:
    if true_cause == predicted_cause:
        return 0.0
    # Acting on a never-retry cause as if it were retryable is the worst
    # possible mistake in this domain: double-charge or contacting a
    # flagged-fraud customer.
    if true_cause in NEVER_RETRY_CAUSES and predicted_cause not in NEVER_RETRY_CAUSES:
        return 10.0
    # Missing a never-retry cause the other way (over-cautious) is cheap.
    if predicted_cause in NEVER_RETRY_CAUSES and true_cause not in NEVER_RETRY_CAUSES:
        return 2.0
    return 1.0


# ---------------------------------------------------------------------------
# 5. Evidence packet — this is the ONLY thing the detector, rules tier and
#    diagnosis agent ever see. `true_cause` deliberately lives OUTSIDE this
#    dataclass in the generator's ground-truth table, never passed down the
#    pipeline, to make leakage a type-level impossibility rather than a
#    discipline problem.
# ---------------------------------------------------------------------------
@dataclass
class EvidencePacket:
    event_id: str
    customer_id: str
    invoice_id: str
    attempt_no: int
    amount: float
    method: str                 # upi | card | netbanking
    geo_tier: str                # metro | tier2 | tier3
    timestamp_ist: str           # ISO8601, IST
    tenure_days: int
    mandate_status: str           # none | active | expired
    retry_count: int
    error_code: str
    error_source: str            # bank | customer | gateway | business | internal
    error_reason: str            # coarse, sometimes ambiguous by design
    error_step: str               # payment_authentication | authorization | capture
    bank_health_score: float      # 0..1, rolling 15-min bank/PSP failure-rate proxy
    attempts_today: int
    debit_confirmation_flag: bool  # noisy signal: bank says money WAS debited
    free_text: Optional[str] = None  # optional customer/support note, Hinglish OK

    def to_dict(self) -> dict:
        return asdict(self)
