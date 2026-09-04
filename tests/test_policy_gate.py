import inspect
import pytest
from datetime import datetime, timezone
from wapas.schema import EvidencePacket, IST
from wapas import policy_gate
from wapas.policy_gate import Gate, GateConfig


def ev(**o) -> EvidencePacket:
    base = dict(
        event_id="evt_t", customer_id="cust_1", invoice_id="inv_1", attempt_no=1,
        amount=500.0, method="upi", geo_tier="metro", timestamp_ist="2026-08-15T12:00:00+05:30",
        tenure_days=100, mandate_status="none", retry_count=0,
        error_code="GATEWAY_ERROR", error_source="bank", error_reason="BANK_DECLINED",
        error_step="payment_authorization", bank_health_score=0.8, attempts_today=0,
        debit_confirmation_flag=False, free_text=None, predebit_notified=False,
    )
    base.update(o)
    return EvidencePacket(**base)


def diag(action, cause="bank_decline", conf=0.9):
    return {"root_cause": cause, "confidence": conf, "action": action, "source": "test"}


DAY = datetime(2026, 8, 15, 12, 0, tzinfo=IST)
NIGHT = datetime(2026, 8, 15, 23, 0, tzinfo=IST)


def test_duplicate_key_never_executes_twice():
    g = Gate()
    first = g.decide(ev(), diag("send_payment_link"), DAY)
    second = g.decide(ev(), diag("send_payment_link"), DAY)
    assert first["final_action"] == "send_payment_link"
    assert second["policy_result"] == "duplicate" and second["final_action"] == "no_action"


def test_confirmed_debit_redirects_retries_and_links_to_verify():
    for a in ("retry_now", "retry_alternate_method", "send_payment_link"):
        d = Gate().decide(ev(debit_confirmation_flag=True), diag(a), DAY)
        assert d["final_action"] == "verify_then_reassure", a
        assert d["authority"] == "L1"


def test_risk_flagged_allows_human_only():
    for a in ("retry_now", "send_payment_link", "verify_then_reassure"):
        d = Gate().decide(ev(error_reason="RISK_BLOCKED"), diag(a, cause="fraud_hold"), DAY)
        assert d["final_action"] == "escalate_human" and d["authority"] == "L3", a


def test_low_confidence_escalates_instead_of_dropping():
    d = Gate().decide(ev(), diag("retry_now", conf=0.10), DAY)
    assert d["final_action"] == "escalate_human"
    assert d["authority"] == "L3"
    assert d["policy_result"] == "modified"


def test_quiet_hours_defer_to_nine_am_ist_not_drop():
    d = Gate().decide(ev(), diag("send_payment_link"), NIGHT)
    assert d["final_action"] == "send_payment_link"
    assert d["policy_result"] == "deferred"
    assert d["scheduled_for"] == "2026-08-16T09:00:00+05:30"
    assert d["deferred_hours"] == 10.0


def test_quiet_hours_are_evaluated_in_ist_whatever_tz_the_caller_uses():
    late_utc = datetime(2026, 8, 15, 17, 30, tzinfo=timezone.utc)     # 23:00 IST
    morning_utc = datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc)    # 09:30 IST
    assert Gate().decide(ev(), diag("send_payment_link"), late_utc)["policy_result"] == "deferred"
    assert Gate().decide(ev(), diag("send_payment_link"), morning_utc)["policy_result"] == "approved"


def test_naive_datetimes_are_treated_as_ist():
    d = Gate().decide(ev(), diag("send_payment_link"), datetime(2026, 8, 15, 23, 0))
    assert d["policy_result"] == "deferred"


def test_contact_cap_blocks_third_contact_in_window():
    g = Gate()
    out = [g.decide(ev(event_id=f"e{i}", invoice_id=f"inv_{i}"), diag("send_payment_link"), DAY) for i in range(3)]
    assert [d["final_action"] for d in out[:2]] == ["send_payment_link"] * 2
    assert out[2]["final_action"] == "no_action" and "contact cap" in out[2]["blocked_reason"]


def test_retry_without_mandate_becomes_a_link_the_customer_approves():
    d = Gate().decide(ev(mandate_status="none"), diag("retry_delayed", cause="insufficient_funds"), DAY)
    assert d["final_action"] == "send_payment_link"
    assert d["authority"] == "L1" and d["policy_result"] == "modified"


def test_mandate_retry_now_requires_predebit_notice():
    notified = Gate().decide(ev(mandate_status="active", predebit_notified=True), diag("retry_now"), DAY)
    assert notified["final_action"] == "retry_now" and notified["authority"] == "L2"
    unnotified = Gate().decide(ev(mandate_status="active", predebit_notified=False), diag("retry_now"), DAY)
    assert unnotified["final_action"] == "retry_delayed" and unnotified["authority"] == "L2"


def test_alternate_method_is_never_covered_by_a_mandate():
    d = Gate().decide(ev(mandate_status="active", predebit_notified=True), diag("retry_alternate_method"), DAY)
    assert d["final_action"] == "send_payment_link" and d["authority"] == "L1"


def test_breaker_needs_volume_trips_and_only_a_named_human_reenables():
    g = Gate()
    for _ in range(20):
        g.circuit_breaker_record("bank_decline", "retry_now", True)
    assert g.circuit_breaker_check("bank_decline", "retry_now")[0]          # below min volume
    for _ in range(10):
        g.circuit_breaker_record("bank_decline", "retry_now", True)
    assert not g.circuit_breaker_check("bank_decline", "retry_now")[0]
    assert g.breaker_events[-1]["type"] == "breaker_tripped"

    d = g.decide(ev(mandate_status="active", predebit_notified=True), diag("retry_now"), DAY)
    assert d["final_action"] == "escalate_human" and d["authority"] == "L3"
    assert any("breaker" in t for t in d["gate_trace"])

    with pytest.raises(ValueError):
        g.reenable("bank_decline", "retry_now", operator_id="")
    g.reenable("bank_decline", "retry_now", operator_id="ops_priya")
    d2 = g.decide(ev(customer_id="cust_2", invoice_id="inv_2", mandate_status="active", predebit_notified=True),
                  diag("retry_now"), DAY)
    assert d2["final_action"] == "retry_now"


def test_breaker_ignores_no_action_rows():
    g = Gate()
    for _ in range(100):
        g.circuit_breaker_record("unknown", "no_action", True)
    assert g.breaker_status()["suspended"] == []


def test_human_capacity_is_a_real_stopping_rule():
    g = Gate(cfg=GateConfig(human_capacity_per_day=2))
    out = [g.decide(ev(customer_id=f"c{i}", invoice_id=f"i{i}"), diag("retry_now", conf=0.1), DAY) for i in range(3)]
    assert [d["final_action"] for d in out[:2]] == ["escalate_human"] * 2
    assert out[2]["final_action"] == "no_action" and "human capacity" in out[2]["blocked_reason"]


def test_kill_switch_halts_everything_and_cancels_scheduled():
    g = Gate()
    g.decide(ev(customer_id="c1", invoice_id="i1"), diag("send_payment_link"), NIGHT)   # scheduled
    info = g.halt("ops_priya")
    assert info["scheduled_cancelled"] == 1
    assert g.key_state("c1", "i1", 1) == "cancelled"
    d = g.decide(ev(customer_id="c2", invoice_id="i2"), diag("send_payment_link"), DAY)
    assert d["final_action"] == "no_action" and "kill switch" in d["blocked_reason"]
    with pytest.raises(ValueError):
        g.halt("")


def test_dnc_blocks_every_contact():
    d = Gate(dnc={"cust_1"}).decide(ev(), diag("send_payment_link"), DAY)
    assert d["final_action"] == "no_action" and "do-not-contact" in d["blocked_reason"]


def test_off_menu_action_goes_to_a_human():
    d = Gate().decide(ev(), diag("wire_money_to_founder"), DAY)
    assert d["final_action"] == "escalate_human"
    assert any("off-menu" in t for t in d["gate_trace"])


def test_every_row_carries_authority_cost_amount_and_trace():
    d = Gate().decide(ev(amount=1234.5), diag("send_payment_link"), DAY)
    assert d["authority"] == "L1" and d["action_cost_inr"] == 0.35 and d["amount"] == 1234.5
    assert d["gate_trace"] and d["decided_at"].endswith("+05:30")
    blocked = Gate(dnc={"cust_1"}).decide(ev(), diag("send_payment_link"), DAY)
    assert "authority" in blocked and blocked["action_cost_inr"] == 0.0


def test_gate_never_sees_ground_truth():
    src = inspect.getsource(policy_gate)
    assert "true_cause" not in src
    assert "CAUSE_ACTION_POLICY" not in src and "ORACLE" not in src