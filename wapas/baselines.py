"""
wapas.baselines
----------------
Arm B — the "floor". This is deliberately NOT a strawman: it is the
generic playbook Razorpay's own public guidance on payment-success-rate
optimization recommends for a merchant who hasn't built a diagnosis layer —
retry, fall back to an alternate method, and send one templated recovery
message. It goes through the EXACT SAME policy gate as WAPAS (same
authority rules, same caps, same idempotency, same hard never-retry
protections). The only thing missing is diagnosis: every event gets the
same proposed action, regardless of why it actually failed.

This is what "contact parity" is protecting: if WAPAS beats this arm, the
gap can only be attributable to diagnosis quality, not to being more
polite, more frequent, or safer in some other dimension.
"""

from __future__ import annotations
from .schema import EvidencePacket

FLOOR_ACTION = "retry_alternate_method"
FLOOR_CONFIDENCE = 0.90  # not a diagnostic confidence — this policy never
                          # varies its proposal, so "confidence" here just
                          # needs to clear the gate's threshold like any
                          # other proposal would.


def floor_diagnose(evidence: EvidencePacket) -> dict:
    return {
        "root_cause": "unknown",   # never diagnosed — that's the point
        "confidence": FLOOR_CONFIDENCE,
        "action": FLOOR_ACTION,
        "source": "floor_baseline",
        "routed_to_llm": False,
        "routed_to_human": False,
        "basis": "razorpay_published_playbook:generic_retry_plus_fallback_method",
    }
