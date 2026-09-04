import inspect
from wapas.schema import EvidencePacket
from wapas.rules_tier import diagnose
from wapas.data_foundry import generate_events


def ev(**overrides) -> EvidencePacket:
    base = dict(
        event_id="evt_t", customer_id="cust_1", invoice_id="inv_1", attempt_no=1,
        amount=500.0, method="upi", geo_tier="metro", timestamp_ist="2026-08-15T12:00:00+05:30",
        tenure_days=100, mandate_status="none", retry_count=0,
        error_code="GATEWAY_ERROR", error_source="bank", error_reason="BANK_DECLINED",
        error_step="payment_authorization", bank_health_score=0.8, attempts_today=0,
        debit_confirmation_flag=False, free_text=None,
    )
    base.update(overrides)
    return EvidencePacket(**base)


def test_debit_flag_resolves_debited_pending():
    d = diagnose(ev(debit_confirmation_flag=True))
    assert d["root_cause"] == "debited_pending" and d["resolved"]
    assert d["action"] == "verify_then_reassure"


def test_debit_keywords_resolve_debited_pending():
    d = diagnose(ev(error_reason="PAYMENT_FAILED", free_text="paise kat gaye par order nahi hua"))
    assert d["root_cause"] == "debited_pending" and d["resolved"]
    assert "keyword" in d["basis"]


def test_unambiguous_reason_resolves_directly():
    d = diagnose(ev(error_reason="INSUFFICIENT_FUNDS"))
    assert d["root_cause"] == "insufficient_funds" and d["resolved"]
    assert d["action"] == "retry_delayed"
    assert diagnose(ev(error_reason="RISK_BLOCKED"))["action"] == "escalate_human"


def test_bank_declined_clear_cases_resolve():
    assert diagnose(ev(attempts_today=5))["root_cause"] == "upi_daily_limit"
    assert diagnose(ev(bank_health_score=0.10))["root_cause"] == "bank_outage"
    d = diagnose(ev(bank_health_score=0.90, attempts_today=0))
    assert d["root_cause"] == "bank_decline" and d["resolved"]


def test_bank_declined_gray_zone_needs_llm():
    d = diagnose(ev(bank_health_score=0.35, attempts_today=2))
    assert d["needs_llm"] and not d["resolved"]
    assert d["confidence"] < 0.55


def test_payment_failed_always_needs_llm_without_debit_signal():
    for step, source in [("payment_authentication", "bank"),
                         ("payment_initiation", "customer"),
                         ("payment_initiation", "internal")]:
        d = diagnose(ev(error_reason="PAYMENT_FAILED", error_step=step, error_source=source))
        assert d["needs_llm"], (step, source)


def test_rules_never_see_true_cause():
    params = inspect.signature(diagnose).parameters
    assert list(params) == ["evidence"]


def test_llm_share_on_generated_data_is_a_minority():
    events = generate_events(3000, seed=11)
    share = sum(1 for p, _ in events if diagnose(p)["needs_llm"]) / len(events)
    assert 0.12 < share < 0.45, share