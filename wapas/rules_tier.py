"""
wapas.rules_tier
-----------------
Deterministic, no-LLM diagnosis. Sees ONLY the evidence packet.

Contract: {root_cause, confidence, action, resolved, needs_llm, source, basis}
`resolved=True` means "rules are confident enough that the LLM is not
called." `needs_llm=True` carries the rules' best guess as a HINT for the
diagnosis agent (and for the disagreement rule).

Thresholds below sit at the NATURAL decision boundaries of the generator's
overlapping distributions (see data_foundry.HEALTH_PARAMS /
ATTEMPTS_LAMBDA). They are not tuned to manufacture work for the LLM; the
ambiguity that remains is the overlap of the tails.
"""

from __future__ import annotations
from .schema import EvidencePacket, CAUSE_ACTION_POLICY
from .data_foundry import REASON_TO_CAUSES

# Reasons that map to exactly one cause resolve by lookup.
UNAMBIGUOUS_REASON_TO_CAUSE = {
    r: next(iter(cs)) for r, cs in REASON_TO_CAUSES.items() if len(cs) == 1
}

# Customer explicitly says money left the account. A deterministic keyword
# rule is the right tool for a safety-critical, unambiguous phrase.
DEBIT_KEYWORDS = ("kat gaye", "deducted", "debited")

# BANK_DECLINED bucket boundaries (natural, see module docstring)
LIMIT_ATTEMPTS_MIN = 4        # P(Poisson 0.9 >= 4) ~ 1.3%; P(Poisson 3.5 >= 4) ~ 46%
OUTAGE_HEALTH_MAX = 0.25      # ~58% of outages, ~5% of plain declines fall below
DECLINE_HEALTH_MIN = 0.45     # ~70% of plain declines, ~9% of outages sit above
DECLINE_ATTEMPTS_MAX = 1


def diagnose(evidence: EvidencePacket) -> dict:
    # Rule 0 — bank confirms debit. Independent of error_reason.
    if evidence.debit_confirmation_flag:
        return _resolved("debited_pending", 0.90, "rule:debit_confirmation_flag")

    # Rule 0b — customer says money was debited.
    text = (evidence.free_text or "").lower()
    if any(k in text for k in DEBIT_KEYWORDS):
        return _resolved("debited_pending", 0.80, "rule:debit_keyword_in_free_text")

    reason = evidence.error_reason

    # Rule 1 — 1:1 reasons resolve directly.
    if reason in UNAMBIGUOUS_REASON_TO_CAUSE:
        cause = UNAMBIGUOUS_REASON_TO_CAUSE[reason]
        return _resolved(cause, 0.92, f"rule:unambiguous_reason:{reason}")

    # Rule 2 — BANK_DECLINED: bank_decline | bank_outage | upi_daily_limit
    if reason == "BANK_DECLINED":
        if evidence.attempts_today >= LIMIT_ATTEMPTS_MIN:
            return _resolved("upi_daily_limit", 0.85, f"rule:attempts_today>={LIMIT_ATTEMPTS_MIN}")
        if evidence.bank_health_score < OUTAGE_HEALTH_MAX:
            return _resolved("bank_outage", 0.80, f"rule:bank_health<{OUTAGE_HEALTH_MAX}")
        if evidence.bank_health_score >= DECLINE_HEALTH_MIN and evidence.attempts_today <= DECLINE_ATTEMPTS_MAX:
            return _resolved("bank_decline", 0.75, f"rule:bank_health>={DECLINE_HEALTH_MIN}_low_attempts")
        # Gray zone: mid health and/or 2-3 attempts. Best guess as a hint only.
        if evidence.attempts_today >= 2:
            return _needs_llm("upi_daily_limit", 0.45, "rule:bank_declined_gray_zone:attempts2-3")
        if evidence.bank_health_score < 0.35:
            return _needs_llm("bank_outage", 0.45, "rule:bank_declined_gray_zone:low_mid_health")
        return _needs_llm("bank_decline", 0.45, "rule:bank_declined_gray_zone")

    # Rule 3 — PAYMENT_FAILED: intent_drop | auth_3ds_drop | wrong_vpa | debited_pending
    # Step/source give a weak prior; the free text (if any) is where the
    # information is, and reading it is the LLM's job.
    if reason == "PAYMENT_FAILED":
        if evidence.error_step == "payment_authentication":
            return _needs_llm("auth_3ds_drop", 0.40, "rule:payment_failed:step_authentication")
        if evidence.error_step == "payment_initiation" and evidence.error_source == "customer":
            return _needs_llm("wrong_vpa", 0.40, "rule:payment_failed:initiation_customer")
        return _needs_llm("intent_drop", 0.40, "rule:payment_failed:generic")

    # Fallback — cannot happen with the fixed taxonomy; never crash.
    return _needs_llm("intent_drop", 0.30, "rule:unmapped_reason")


def _resolved(cause: str, confidence: float, basis: str) -> dict:
    return {
        "root_cause": cause,
        "confidence": confidence,
        "action": CAUSE_ACTION_POLICY[cause],
        "resolved": True,
        "needs_llm": False,
        "source": "rules",
        "basis": basis,
    }


def _needs_llm(best_guess: str, confidence: float, basis: str) -> dict:
    return {
        "root_cause": best_guess,
        "confidence": confidence,
        "action": CAUSE_ACTION_POLICY[best_guess],
        "resolved": False,
        "needs_llm": True,
        "source": "rules_hint",
        "basis": basis,
    }