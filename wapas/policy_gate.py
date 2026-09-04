"""
wapas.policy_gate
-------------------
The deterministic core. The LLM NEVER executes here — it only produced a
*proposed* root_cause/action upstream. This module decides whether that
proposal is allowed to happen, and if not, what happens instead.

Four checks, in order, any of which can veto the LLM's proposal:
  1. AUTHORITY  (consent ladder)      -> policy_gate.authority()
  2. STATIC SAFETY (caps, hours, DNC) -> policy_gate.static_safety()
  3. ADAPTIVE SAFETY (circuit breaker)-> Gate.circuit_breaker_check()
  4. IDEMPOTENCY (dedupe)             -> Gate.idempotency_check()

"No authority, no action" — every decision carries an `authority` field
into the ledger, even blocked ones.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, time

from .schema import EvidencePacket, NEVER_RETRY_CAUSES, ACTIONS

RETRY_SHAPED_ACTIONS = {"retry_now", "retry_delayed", "retry_alternate_method"}
LINK_ACTIONS = {"send_payment_link", "send_reauth_mandate_link"}

QUIET_HOURS_START = time(21, 0)   # 21:00 IST — TRAI TCCCPR unsolicited-comms window
QUIET_HOURS_END = time(9, 0)      # 09:00 IST

CONTACT_CAP_PER_WINDOW = 2
CONTACT_WINDOW_DAYS = 7
CONFIDENCE_THRESHOLD = 0.55
DAILY_BUDGET = 5000.0            # ₹, simulated
ACTION_COST = {                  # ₹ cost per contact channel, simulated
    "send_payment_link": 0.35,
    "send_reauth_mandate_link": 0.35,
    "verify_then_reassure": 0.10,
    "retry_now": 0.05,
    "retry_delayed": 0.05,
    "retry_alternate_method": 0.05,
    "refund": 0.0,
    "escalate_human": 8.0,       # human time, simulated
    "no_action": 0.0,
}

# Adaptive circuit breaker parameters
BREAKER_MIN_VOLUME = 8
BREAKER_COMPLAINT_RATE_THRESHOLD = 0.30


def authority(evidence: EvidencePacket, root_cause: str, action: str) -> tuple[str | None, str]:
    """Returns (authority_level, reason). authority_level in {L1, L2, L3, None}."""
    if action == "no_action":
        return None, "no action taken; no authority needed"

    # Hard never-retry rules, evidence-based (NOT hidden-truth-based) so they
    # protect the system even against a policy that ignores diagnosis
    # entirely (e.g. the naive baseline arm B): if the bank confirms debit,
    # or the merchant's own risk system already flagged this payment, no
    # retry-shaped action may proceed no matter what was proposed.
    if evidence.debit_confirmation_flag and action in RETRY_SHAPED_ACTIONS:
        return None, "hard_block:debit_confirmation_flag forbids retry-shaped action"
    if evidence.error_reason == "RISK_BLOCKED" and action in RETRY_SHAPED_ACTIONS:
        return None, "hard_block:risk_flagged forbids retry-shaped action"

    if action == "escalate_human":
        return "L3", "routed to human agent"

    if action in LINK_ACTIONS or action == "verify_then_reassure" or action == "refund":
        # A payment link / reassurance / refund always requires the customer
        # to actively authenticate (PIN/OTP) or is a merchant-side reversal —
        # this is "live approval", not a standing mandate being pulled.
        return "L1", "requires live customer action (PIN/OTP) or merchant-side refund"

    if action in RETRY_SHAPED_ACTIONS:
        if evidence.mandate_status == "active":
            return "L2", "standing mandate, within RBI pre-debit-notification terms"
        return None, "blocked: no active mandate and no live approval for a retry"

    return None, f"blocked: action '{action}' has no defined authority path"


def static_safety(
    evidence: EvidencePacket,
    root_cause: str,
    action: str,
    confidence: float,
    contacts_in_window: int,
    now: datetime,
    dnc: set[str],
    budget_spent_today: float,
) -> tuple[bool, str]:
    if action not in ACTIONS:
        return False, "blocked: action not in fixed allowlist"

    if evidence.customer_id in dnc:
        return False, "blocked: customer on do-not-contact list"

    if action != "no_action" and confidence < CONFIDENCE_THRESHOLD:
        return False, "blocked: confidence below threshold, requires human"

    if action != "no_action" and contacts_in_window >= CONTACT_CAP_PER_WINDOW:
        return False, f"blocked: contact cap ({CONTACT_CAP_PER_WINDOW}/{CONTACT_WINDOW_DAYS}d) reached"

    t = now.time()
    is_quiet = t >= QUIET_HOURS_START or t < QUIET_HOURS_END
    if action != "no_action" and is_quiet:
        return False, "blocked: within TRAI quiet hours (21:00-09:00 IST)"

    cost = ACTION_COST.get(action, 0.0)
    if budget_spent_today + cost > DAILY_BUDGET:
        return False, "blocked: daily recovery budget exceeded"

    return True, "static safety passed"


@dataclass
class Gate:
    """Stateful gate: tracks contacts, budget, DNC, idempotency keys, and
    the adaptive circuit breaker across a batch run."""

    dnc: set[str] = field(default_factory=set)
    _contacts: dict[str, list[datetime]] = field(default_factory=dict)
    _used_keys: set[tuple] = field(default_factory=set)
    _budget_spent_by_day: dict[str, float] = field(default_factory=dict)
    _breaker_outcomes: dict[tuple, list[bool]] = field(default_factory=dict)
    _breaker_suspended: set[tuple] = field(default_factory=set)

    def contacts_in_window(self, customer_id: str, now: datetime) -> int:
        history = self._contacts.get(customer_id, [])
        cutoff = now.timestamp() - CONTACT_WINDOW_DAYS * 86400
        return sum(1 for t in history if t.timestamp() >= cutoff)

    def record_contact(self, customer_id: str, now: datetime) -> None:
        self._contacts.setdefault(customer_id, []).append(now)

    def idempotency_check(self, customer_id: str, invoice_id: str, attempt_no: int) -> bool:
        """Returns True if this is a NEW action (safe to proceed), False if a
        duplicate (must not execute again)."""
        key = (customer_id, invoice_id, attempt_no)
        if key in self._used_keys:
            return False
        self._used_keys.add(key)
        return True

    def circuit_breaker_check(self, root_cause: str, action: str) -> tuple[bool, str]:
        key = (root_cause, action)
        if key in self._breaker_suspended:
            return False, f"blocked: circuit breaker tripped for ({root_cause}, {action})"
        return True, "breaker ok"

    def circuit_breaker_record(self, root_cause: str, action: str, complaint: bool) -> None:
        key = (root_cause, action)
        outcomes = self._breaker_outcomes.setdefault(key, [])
        outcomes.append(complaint)
        if len(outcomes) >= BREAKER_MIN_VOLUME:
            recent = outcomes[-BREAKER_MIN_VOLUME:]
            rate = sum(recent) / len(recent)
            if rate >= BREAKER_COMPLAINT_RATE_THRESHOLD:
                self._breaker_suspended.add(key)  # fail-closed; human-only re-enable

    def spend(self, now: datetime, action: str) -> None:
        day = now.date().isoformat()
        self._budget_spent_by_day[day] = self._budget_spent_by_day.get(day, 0.0) + ACTION_COST.get(action, 0.0)

    def budget_spent_today(self, now: datetime) -> float:
        return self._budget_spent_by_day.get(now.date().isoformat(), 0.0)

    def decide(self, evidence: EvidencePacket, diagnosis: dict, now: datetime) -> dict:
        """Full pipeline: authority -> static safety -> breaker -> idempotency.
        Returns a decision dict ready to be logged to the ledger."""
        root_cause = diagnosis["root_cause"]
        proposed_action = diagnosis["action"]
        confidence = diagnosis["confidence"]
        contacts_before = self.contacts_in_window(evidence.customer_id, now)

        auth_level, auth_reason = authority(evidence, root_cause, proposed_action)
        final_action = proposed_action
        blocked_reason = None

        if auth_level is None and proposed_action != "no_action":
            blocked_reason = auth_reason
            if auth_reason.startswith("hard_block:debit_confirmation_flag"):
                final_action = "verify_then_reassure"
            elif auth_reason.startswith("hard_block:risk_flagged"):
                final_action = "escalate_human"
            else:
                # No clear authority path (e.g. retry with no active
                # mandate and no live approval) -> hand to a human rather
                # than silently drop it or invent authority.
                final_action = "escalate_human"
            auth_level, _ = authority(evidence, root_cause, final_action)

        ok_static, static_reason = static_safety(
            evidence, root_cause, final_action, confidence,
            contacts_before,
            now, self.dnc, self.budget_spent_today(now),
        )
        if not ok_static:
            blocked_reason = blocked_reason or static_reason
            final_action = "no_action"
            auth_level = None

        ok_breaker, breaker_reason = self.circuit_breaker_check(root_cause, final_action)
        if not ok_breaker:
            blocked_reason = blocked_reason or breaker_reason
            final_action = "escalate_human"
            auth_level = "L3"

        is_new = self.idempotency_check(evidence.customer_id, evidence.invoice_id, evidence.attempt_no)
        if not is_new:
            blocked_reason = "blocked: duplicate action (idempotency key already used)"
            final_action = "no_action"
            auth_level = None

        approved = final_action != "no_action" or proposed_action == "no_action"
        if final_action != "no_action":
            self.record_contact(evidence.customer_id, now)
            self.spend(now, final_action)

        return {
            "event_id": evidence.event_id,
            "customer_id": evidence.customer_id,
            "invoice_id": evidence.invoice_id,
            "proposed_action": proposed_action,
            "final_action": final_action,
            "root_cause": root_cause,
            "confidence": confidence,
            "authority": auth_level,
            "blocked_reason": blocked_reason,
            "diagnosis_source": diagnosis.get("source"),
            "policy_result": "approved" if blocked_reason is None else "modified_or_blocked",
            "contacts_before": contacts_before,
        }
