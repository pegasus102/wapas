"""
wapas.policy_gate
-------------------
The deterministic core. Upstream produced a PROPOSAL; this module decides
what actually happens, in a fixed order:

  0 kill switch  1 idempotency  2 allowlist  3 confidence->human
  4 hard safety (evidence-only: risk-flag->human only; confirmed debit->verify)
  5 authority ladder — L1 live approval | L2 mandate | L3 human.
      "No authority, no action": a pull with no mandate becomes a LINK THE
      CUSTOMER APPROVES — and the link keeps the pull's intent (immediate /
      scheduled / method fallback). An immediate mandate debit without the
      RBI pre-debit notice becomes a delayed one.
  6 circuit breaker  7 static safety (DNC, cap, human capacity, budget)
  8 scheduling — delayed intents run 48h out; TRAI quiet hours defer to 09:00 IST
  9 execute — record contact, spend, consume key

Nothing here reads the hidden cause (tests/test_policy_gate.py enforces it).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional

from .schema import EvidencePacket, ACTIONS, RETRY_SHAPED_ACTIONS, LINK_ACTIONS, CHARGE_SHAPED, IST

HUMAN_ONLY = {"escalate_human", "no_action"}

ACTION_COST_INR = {
    "send_payment_link": 0.35, "send_reauth_mandate_link": 0.35, "verify_then_reassure": 0.10,
    "retry_now": 0.05, "retry_delayed": 0.05, "retry_alternate_method": 0.05,
    "refund": 0.0, "escalate_human": 8.0, "no_action": 0.0,
}


@dataclass(frozen=True)
class GateConfig:
    contact_cap_per_window: int = 2
    contact_window_days: int = 7
    quiet_start: time = time(21, 0)
    quiet_end: time = time(9, 0)
    confidence_threshold: float = 0.55
    daily_budget_inr: float = 2000.0
    human_capacity_per_day: int = 6
    delayed_retry_hours: int = 48
    breaker_window: int = 50
    breaker_min_volume: int = 30
    breaker_complaint_rate: float = 0.30


DEFAULT_CONFIG = GateConfig()


def to_ist(now: datetime) -> datetime:
    return now.replace(tzinfo=IST) if now.tzinfo is None else now.astimezone(IST)


def is_quiet_hours(now: datetime, cfg: GateConfig = DEFAULT_CONFIG) -> bool:
    t = to_ist(now).time()
    return t >= cfg.quiet_start or t < cfg.quiet_end


def next_allowed_time(now: datetime, cfg: GateConfig = DEFAULT_CONFIG) -> datetime:
    now = to_ist(now)
    day = now.date() if now.time() < cfg.quiet_end else now.date() + timedelta(days=1)
    return datetime.combine(day, cfg.quiet_end, tzinfo=IST)


def hard_safety(evidence: EvidencePacket, action: str) -> tuple[str, Optional[str]]:
    if evidence.error_reason == "RISK_BLOCKED" and action not in HUMAN_ONLY:
        return "escalate_human", "hard_block: risk-flagged payment -> human only"
    if evidence.debit_confirmation_flag and action in CHARGE_SHAPED:
        return "verify_then_reassure", "hard_block: bank confirmed debit -> verify, never re-charge"
    return action, None


def authority(evidence: EvidencePacket, action: str, variant: Optional[str] = None
              ) -> tuple[Optional[str], str, Optional[str], str]:
    """Returns (level, action, link_variant, reason)."""
    if action == "no_action":
        return None, action, None, "no action; no authority needed"
    if action == "escalate_human":
        return "L3", action, None, "human agent owns the case"
    if action == "send_payment_link":
        return "L1", action, variant or "immediate", "customer authenticates live (PIN/OTP) on the link"
    if action in ("send_reauth_mandate_link", "verify_then_reassure", "refund"):
        return "L1", action, None, "customer authenticates live (PIN/OTP) or merchant-side reversal"
    if action in RETRY_SHAPED_ACTIONS:
        if action == "retry_alternate_method":
            return "L1", "send_payment_link", "method_fallback", \
                "alternate method is never covered by a mandate -> link with method fallback"
        if evidence.mandate_status == "active":
            if action == "retry_now" and not evidence.predebit_notified:
                return "L2", "retry_delayed", None, \
                    "standing mandate; RBI pre-debit notice not yet sent -> delayed retry after notice"
            return "L2", action, None, "standing mandate within cap; pre-debit notice respected"
        v = "scheduled" if action == "retry_delayed" else "immediate"
        return "L1", "send_payment_link", v, \
            f"no standing mandate -> cannot pull; {v} link the customer approves (intent of {action} preserved)"
    return None, "escalate_human", None, f"no authority path for '{action}'"


@dataclass
class Gate:
    cfg: GateConfig = field(default_factory=lambda: DEFAULT_CONFIG)
    dnc: set = field(default_factory=set)
    halted: bool = False
    halted_by: Optional[str] = None
    breaker_events: list = field(default_factory=list)
    _contacts: dict = field(default_factory=dict)
    _keys: dict = field(default_factory=dict)
    _budget_by_day: dict = field(default_factory=dict)
    _human_by_day: dict = field(default_factory=dict)
    _breaker_outcomes: dict = field(default_factory=dict)
    _breaker_suspended: set = field(default_factory=set)
    _scheduled: list = field(default_factory=list)

    def contacts_in_window(self, customer_id: str, now: datetime) -> int:
        cutoff = to_ist(now) - timedelta(days=self.cfg.contact_window_days)
        return sum(1 for t in self._contacts.get(customer_id, []) if t >= cutoff)

    def record_contact(self, customer_id: str, when: datetime) -> None:
        self._contacts.setdefault(customer_id, []).append(to_ist(when))

    def budget_spent_today(self, now: datetime) -> float:
        return self._budget_by_day.get(to_ist(now).date().isoformat(), 0.0)

    def humans_today(self, now: datetime) -> int:
        return self._human_by_day.get(to_ist(now).date().isoformat(), 0)

    def key_state(self, customer_id: str, invoice_id: str, attempt_no: int) -> Optional[str]:
        return self._keys.get((customer_id, invoice_id, attempt_no))

    def halt(self, operator_id: str) -> dict:
        if not operator_id:
            raise ValueError("kill switch requires a named operator")
        self.halted, self.halted_by = True, operator_id
        return {"type": "kill_switch", "by": operator_id, "scheduled_cancelled": self.cancel_scheduled()}

    def resume(self, operator_id: str) -> None:
        if not operator_id:
            raise ValueError("resume requires a named operator")
        self.halted, self.halted_by = False, None

    def cancel_scheduled(self) -> int:
        n = 0
        for key, _when in self._scheduled:
            if self._keys.get(key) == "scheduled":
                self._keys[key] = "cancelled"
                n += 1
        self._scheduled.clear()
        return n

    def circuit_breaker_check(self, root_cause: str, action: str) -> tuple[bool, str]:
        if (root_cause, action) in self._breaker_suspended:
            return False, f"circuit breaker: ({root_cause}, {action}) suspended"
        return True, "breaker ok"

    def circuit_breaker_record(self, root_cause: str, action: str, complaint: bool) -> None:
        if action == "no_action":
            return
        key = (root_cause, action)
        if key in self._breaker_suspended:
            return
        hist = self._breaker_outcomes.setdefault(key, [])
        hist.append(bool(complaint))
        if len(hist) > self.cfg.breaker_window:
            del hist[0]
        if len(hist) >= self.cfg.breaker_min_volume:
            rate = sum(hist) / len(hist)
            if rate >= self.cfg.breaker_complaint_rate:
                self._breaker_suspended.add(key)
                self.breaker_events.append({"type": "breaker_tripped", "root_cause": root_cause,
                                            "action": action, "complaint_rate": round(rate, 3), "volume": len(hist)})

    def reenable(self, root_cause: str, action: str, operator_id: str) -> dict:
        if not operator_id:
            raise ValueError("fail-closed: re-enable requires a named human operator")
        key = (root_cause, action)
        self._breaker_suspended.discard(key)
        self._breaker_outcomes.pop(key, None)
        event = {"type": "breaker_reenabled", "root_cause": root_cause, "action": action, "by": operator_id}
        self.breaker_events.append(event)
        return event

    def breaker_status(self) -> dict:
        return {
            "suspended": sorted(list(k) for k in self._breaker_suspended),
            "rates": {f"{c}|{a}": round(sum(h) / len(h), 3) for (c, a), h in self._breaker_outcomes.items() if h},
        }

    def decide(self, evidence: EvidencePacket, diagnosis: dict, now: datetime) -> dict:
        cfg = self.cfg
        now = to_ist(now)
        day = now.date().isoformat()
        root_cause = diagnosis["root_cause"]
        proposed = diagnosis["action"]
        confidence = float(diagnosis.get("confidence", 0.0))
        trace: list[str] = []
        contacts_before = self.contacts_in_window(evidence.customer_id, now)
        key = (evidence.customer_id, evidence.invoice_id, evidence.attempt_no)

        def row(final_action, variant, level, auth_reason, policy_result, blocked_reason=None, scheduled_for=None):
            deferred_h = round((scheduled_for - now).total_seconds() / 3600, 2) if scheduled_for else 0.0
            return {
                "event_id": evidence.event_id, "customer_id": evidence.customer_id,
                "invoice_id": evidence.invoice_id, "attempt_no": evidence.attempt_no,
                "amount": evidence.amount, "decided_at": now.isoformat(),
                "proposed_action": proposed, "final_action": final_action,
                "action_variant": variant if final_action == "send_payment_link" else None,
                "root_cause": root_cause, "confidence": confidence,
                "diagnosis_source": diagnosis.get("source"),
                "authority": level, "authority_reason": auth_reason,
                "policy_result": policy_result, "blocked_reason": blocked_reason,
                "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
                "deferred_hours": deferred_h, "gate_trace": list(trace),
                "contacts_before": contacts_before,
                "action_cost_inr": ACTION_COST_INR.get(final_action, 0.0) if final_action != "no_action" else 0.0,
            }

        if self.halted:
            trace.append(f"kill switch active (halted by {self.halted_by})")
            return row("no_action", None, None, "kill switch", "blocked", blocked_reason="blocked: kill switch active")

        if self._keys.get(key) in ("executed", "scheduled"):
            trace.append("idempotency: key already consumed")
            return row("no_action", None, None, "duplicate", "duplicate",
                       blocked_reason="blocked: duplicate action (idempotency key already consumed)")

        action, variant = proposed, None
        if action not in ACTIONS:
            trace.append(f"allowlist: '{action}' is off-menu -> escalate_human")
            action = "escalate_human"

        if action not in HUMAN_ONLY and confidence < cfg.confidence_threshold:
            trace.append(f"confidence {confidence:.2f} < {cfg.confidence_threshold} -> escalate_human")
            action = "escalate_human"

        action, hard_reason = hard_safety(evidence, action)
        if hard_reason:
            trace.append(hard_reason)

        level, action, variant, auth_reason = authority(evidence, action, variant)
        trace.append(f"authority {level or 'none'}: {auth_reason}")

        ok_breaker, breaker_reason = self.circuit_breaker_check(root_cause, action)
        if not ok_breaker:
            trace.append(breaker_reason + " -> escalate_human")
            action, variant, level, auth_reason = "escalate_human", None, "L3", "circuit breaker redirected to human"

        if action == "no_action":
            self._keys[key] = "cancelled"
            return row("no_action", None, None, auth_reason, "approved")

        cost = ACTION_COST_INR.get(action, 0.0)
        blocked = None
        if evidence.customer_id in self.dnc:
            blocked = "blocked: customer on do-not-contact list"
        elif contacts_before >= cfg.contact_cap_per_window:
            blocked = f"blocked: contact cap ({cfg.contact_cap_per_window}/{cfg.contact_window_days}d) reached"
        elif action == "escalate_human" and self.humans_today(now) >= cfg.human_capacity_per_day:
            blocked = f"blocked: human capacity ({cfg.human_capacity_per_day}/day) exhausted"
        elif self.budget_spent_today(now) + cost > cfg.daily_budget_inr:
            blocked = "blocked: daily recovery budget exceeded"
        if blocked:
            trace.append(blocked)
            self._keys[key] = "cancelled"
            return row("no_action", None, None, auth_reason, "blocked", blocked_reason=blocked)

        scheduled_for = None
        if action == "retry_delayed" or (action == "send_payment_link" and variant == "scheduled"):
            scheduled_for = now + timedelta(hours=cfg.delayed_retry_hours)
            trace.append(f"delayed intent -> scheduled {cfg.delayed_retry_hours}h out")
        effective = scheduled_for or now
        if is_quiet_hours(effective, cfg):
            scheduled_for = next_allowed_time(effective, cfg)
            trace.append(f"TRAI quiet hours (21:00-09:00 IST) -> deferred to {scheduled_for.isoformat()}")

        self.record_contact(evidence.customer_id, scheduled_for or now)
        self._budget_by_day[day] = self._budget_by_day.get(day, 0.0) + cost
        if action == "escalate_human":
            self._human_by_day[day] = self._human_by_day.get(day, 0) + 1
        if scheduled_for:
            self._keys[key] = "scheduled"
            self._scheduled.append((key, scheduled_for))
            result = "deferred"
        else:
            self._keys[key] = "executed"
            result = "approved" if action == proposed else "modified"
        return row(action, variant, level, auth_reason, result, scheduled_for=scheduled_for)