from wapas.schema import EvidencePacket
from wapas import llm_agent
from wapas.diagnosis import diagnose_event


def ev(**o) -> EvidencePacket:
    base = dict(
        event_id="evt_t", customer_id="cust_1", invoice_id="inv_1", attempt_no=1,
        amount=500.0, method="upi", geo_tier="metro", timestamp_ist="2026-08-15T12:00:00+05:30",
        tenure_days=100, mandate_status="none", retry_count=0,
        error_code="GATEWAY_ERROR", error_source="bank", error_reason="PAYMENT_FAILED",
        error_step="payment_authorization", bank_health_score=0.8, attempts_today=0,
        debit_confirmation_flag=False, free_text=None,
    )
    base.update(o)
    return EvidencePacket(**base)


def test_rules_resolved_cases_never_call_the_llm(monkeypatch):
    called = []
    monkeypatch.setattr(llm_agent, "diagnose", lambda *a, **k: called.append(1))
    d = diagnose_event(ev(error_reason="INSUFFICIENT_FUNDS"))
    assert d["source"] == "rules" and d["routed_to_llm"] is False and not called


def test_llm_action_inconsistent_with_its_cause_routes_to_human(monkeypatch):
    monkeypatch.setattr(llm_agent, "diagnose", lambda *a, **k: {
        "root_cause": "fraud_hold", "confidence": 0.9, "action": "retry_now", "source": "stub"})
    d = diagnose_event(ev())
    assert d["routed_to_human"] and d["action"] == "escalate_human"
    assert "inconsistent" in d["human_reason"]


def test_llm_disagreement_at_low_confidence_routes_to_human(monkeypatch):
    monkeypatch.setattr(llm_agent, "diagnose", lambda *a, **k: {
        "root_cause": "wrong_vpa", "confidence": 0.30, "action": "send_payment_link", "source": "stub"})
    d = diagnose_event(ev())                      # rules hint for this packet = intent_drop
    assert d["routed_to_human"] and d["action"] == "escalate_human"
    good = diagnose_event.__globals__  # noqa: F841  (keeps linters quiet about unused import paths)


def test_llm_agreement_uses_policy_action(monkeypatch):
    monkeypatch.setattr(llm_agent, "diagnose", lambda *a, **k: {
        "root_cause": "intent_drop", "confidence": 0.70, "action": "send_payment_link", "source": "stub"})
    d = diagnose_event(ev())
    assert not d["routed_to_human"] and d["action"] == "send_payment_link" and d["routed_to_llm"]