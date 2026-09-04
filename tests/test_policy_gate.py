import pytest
from datetime import datetime
from wapas.schema import EvidencePacket
from wapas.policy_gate import Gate


def make_evidence(**overrides) -> EvidencePacket:
    base = dict(
        event_id="evt_test", customer_id="cust_1", invoice_id="inv_1", attempt_no=1,
        amount=500.0, method="upi", geo_tier="metro", timestamp_ist="2026-08-15T12:00:00",
        tenure_days=100, mandate_status="active", retry_count=0,
        error_code="E1", error_source="bank", error_reason="BANK_DECLINED",
        error_step="authorization", bank_health_score=0.8, attempts_today=0,
        debit_confirmation_flag=False, free_text=None,
    )
    base.update(overrides)
    return EvidencePacket(**base)


DAYTIME = datetime(2026, 8, 15, 12, 0, 0)
QUIET_TIME = datetime(2026, 8, 15, 23, 0, 0)


def test_idempotency_blocks_duplicate_action():
    gate = Gate()
    ev = make_evidence()
    diag = {"root_cause": "bank_decline", "confidence": 0.9, "action": "retry_now", "source": "test"}
    first = gate.decide(ev, diag, DAYTIME)
    second = gate.decide(ev, diag, DAYTIME)
    assert first["final_action"] != "no_action"
    assert second["final_action"] == "no_action"
    assert "idempotency" in second["blocked_reason"]


def test_debit_confirmation_blocks_retry_even_if_diagnosis_says_retry():
    gate = Gate()
    ev = make_evidence(debit_confirmation_flag=True)
    # Diagnosis (wrongly, or from a naive policy) proposes a retry-shaped action.
    diag = {"root_cause": "bank_decline", "confidence": 0.9, "action": "retry_now", "source": "test"}
    decision = gate.decide(ev, diag, DAYTIME)
    assert decision["final_action"] != "retry_now"
    assert decision["final_action"] == "verify_then_reassure"


def test_risk_flagged_blocks_retry_regardless_of_proposed_action():
    gate = Gate()
    ev = make_evidence(error_reason="RISK_BLOCKED")
    diag = {"root_cause": "fraud_hold", "confidence": 0.9, "action": "retry_now", "source": "test"}
    decision = gate.decide(ev, diag, DAYTIME)
    assert decision["final_action"] == "escalate_human"


def test_quiet_hours_blocks_contact():
    gate = Gate()
    ev = make_evidence()
    diag = {"root_cause": "bank_decline", "confidence": 0.9, "action": "retry_now", "source": "test"}
    decision = gate.decide(ev, diag, QUIET_TIME)
    assert decision["final_action"] == "no_action"
    assert "quiet hours" in decision["blocked_reason"]


def test_low_confidence_is_blocked_not_actioned():
    gate = Gate()
    ev = make_evidence()
    diag = {"root_cause": "bank_decline", "confidence": 0.1, "action": "retry_now", "source": "test"}
    decision = gate.decide(ev, diag, DAYTIME)
    assert decision["final_action"] == "no_action"
    assert "confidence" in decision["blocked_reason"]


def test_contact_cap_enforced_within_window():
    gate = Gate()
    diag = {"root_cause": "bank_decline", "confidence": 0.9, "action": "retry_now", "source": "test"}
    results = []
    for i in range(4):
        ev = make_evidence(event_id=f"evt_{i}", invoice_id=f"inv_{i}")
        results.append(gate.decide(ev, diag, DAYTIME))
    actioned = [r for r in results if r["final_action"] != "no_action"]
    assert len(actioned) == 2  # CONTACT_CAP_PER_WINDOW = 2


def test_no_active_mandate_blocks_retry_and_routes_to_human():
    gate = Gate()
    ev = make_evidence(mandate_status="none")
    diag = {"root_cause": "insufficient_funds", "confidence": 0.9, "action": "retry_delayed", "source": "test"}
    decision = gate.decide(ev, diag, DAYTIME)
    assert decision["final_action"] == "escalate_human"
    assert decision["authority"] == "L3"
