"""
wapas.rules_tier
-----------------
Deterministic, no-LLM diagnosis. Resolves every event whose error_reason is
NOT one of the deliberately-ambiguous buckets, plus the two special-cased
hard rules (debit confirmation, and later, the gate's own never-retry
enforcement — that's a SEPARATE, second check in policy_gate.py, not here).

Returns a dict: {root_cause, confidence, action, resolved, needs_llm}
`resolved=True` means "rules are confident, do not call the LLM."
"""

from __future__ import annotations
from .schema import EvidencePacket, ORACLE_ACTION
from .data_foundry import CAUSE_TO_REASON

# Invert CAUSE_TO_REASON for the UNAMBIGUOUS reasons only (reasons mapped to
# exactly one cause). Built once at import time.
_REASON_COUNTS: dict[str, int] = {}
for _c, _r in CAUSE_TO_REASON.items():
    _REASON_COUNTS[_r] = _REASON_COUNTS.get(_r, 0) + 1
UNAMBIGUOUS_REASON_TO_CAUSE = {
    r: c for c, r in CAUSE_TO_REASON.items() if _REASON_COUNTS[r] == 1
}


def diagnose(evidence: EvidencePacket) -> dict:
    # Rule 0 — hard, evidence-based signal: bank confirms money was debited.
    # This does not depend on error_reason at all.
    if evidence.debit_confirmation_flag:
        return _resolved("debited_pending", 0.90, "rule:debit_confirmation_flag")

    reason = evidence.error_reason

    # Rule 1 — unambiguous 1:1 reasons resolve directly.
    if reason in UNAMBIGUOUS_REASON_TO_CAUSE:
        cause = UNAMBIGUOUS_REASON_TO_CAUSE[reason]
        return _resolved(cause, 0.92, f"rule:unambiguous_reason:{reason}")

    # Rule 2 — BANK_DECLINED bucket: shared by bank_decline / bank_outage /
    # upi_daily_limit. Use bank_health_score + attempts_today to try to
    # disambiguate with hard thresholds; only the genuine gray zone escalates.
    if reason == "BANK_DECLINED":
        # Thresholds are deliberately TIGHTER than the generator's own
        # ranges for bank_outage / upi_daily_limit, so genuine overlap
        # exists at the edges — rules resolve the clear-cut majority and
        # leave the honestly ambiguous remainder for the diagnosis agent.
        if evidence.bank_health_score < 0.08:
            return _resolved("bank_outage", 0.82, "rule:bank_health<0.08")
        if evidence.attempts_today >= 5:
            return _resolved("upi_daily_limit", 0.82, "rule:attempts_today>=5")
        if evidence.bank_health_score > 0.80 and evidence.attempts_today == 0:
            return _resolved("bank_decline", 0.78, "rule:bank_health>0.80_zero_attempts")
        # Gray zone: everything else in this bucket.
        return _needs_llm("bank_decline", 0.45, "rule:bank_declined_gray_zone")

    # Rule 3 — PAYMENT_FAILED: generic, low-information reason. Rules can
    # make a weak guess but should not act on it with confidence.
    if reason == "PAYMENT_FAILED":
        return _needs_llm("intent_drop", 0.35, "rule:payment_failed_generic")

    # Fallback (should not happen given the fixed taxonomy, but never crash).
    return _needs_llm("intent_drop", 0.30, "rule:unmapped_reason")


def _resolved(cause: str, confidence: float, basis: str) -> dict:
    return {
        "root_cause": cause,
        "confidence": confidence,
        "action": ORACLE_ACTION[cause],
        "resolved": True,
        "needs_llm": False,
        "source": "rules",
        "basis": basis,
    }


def _needs_llm(best_guess: str, confidence: float, basis: str) -> dict:
    return {
        "root_cause": best_guess,
        "confidence": confidence,
        "action": ORACLE_ACTION[best_guess],
        "resolved": False,
        "needs_llm": True,
        "source": "rules_hint",
        "basis": basis,
    }
