import random
from wapas.response_model import (
    recovery_probability, complaint_probability, simulate_outcome,
    ResponseParams, ORGANIC_RECOVERY,
)


def test_matched_beats_human_beats_generic_beats_organic():
    c = "bank_decline"
    matched = recovery_probability(c, "retry_now", 0)
    human = recovery_probability(c, "escalate_human", 0)
    generic = recovery_probability(c, "send_payment_link", 0)
    organic = recovery_probability(c, "no_action", 0)
    assert matched > human > generic > organic == ORGANIC_RECOVERY[c]


def test_contact_fatigue_reduces_uplift_not_organic():
    c = "insufficient_funds"
    fresh = recovery_probability(c, "retry_delayed", 0)
    tired = recovery_probability(c, "retry_delayed", 2)
    assert fresh > tired > ORGANIC_RECOVERY[c]
    assert recovery_probability(c, "no_action", 0) == recovery_probability(c, "no_action", 3)


def test_fraud_hold_never_recovers_and_contact_raises_complaints():
    for a in ("retry_now", "send_payment_link", "escalate_human", "no_action"):
        assert recovery_probability("fraud_hold", a, 0) == 0.0
    assert complaint_probability("fraud_hold", "retry_now", 0) > complaint_probability("fraud_hold", "escalate_human", 0)


def test_retry_on_debited_pending_adds_nothing_but_complaints():
    assert recovery_probability("debited_pending", "retry_now", 0) == recovery_probability("debited_pending", "no_action", 0)
    assert recovery_probability("debited_pending", "verify_then_reassure", 0) > ORGANIC_RECOVERY["debited_pending"]
    assert complaint_probability("debited_pending", "retry_now", 0) > complaint_probability("debited_pending", "verify_then_reassure", 0)


def test_no_action_never_generates_complaint():
    for c in ("bank_decline", "fraud_hold", "debited_pending"):
        assert complaint_probability(c, "no_action", 3) == 0.0
    out = simulate_outcome("bank_decline", "no_action", 3, random.Random(1))
    assert out["complaint"] is False


def test_refund_is_goodwill_not_revenue():
    out = simulate_outcome("debited_pending", "refund", 0, random.Random(2))
    assert out["recovered"] is False
    assert out["goodwill_saved"] is True


def test_common_random_numbers_same_action_same_outcome():
    a = simulate_outcome("bank_outage", "retry_delayed", 1, random.Random(99))
    b = simulate_outcome("bank_outage", "retry_delayed", 1, random.Random(99))
    assert a == b


def test_zero_advantage_scale_collapses_matched_to_organic():
    p = ResponseParams(advantage_scale=0.0)
    assert recovery_probability("wrong_vpa", "send_payment_link", 0, p) == recovery_probability("wrong_vpa", "no_action", 0, p)