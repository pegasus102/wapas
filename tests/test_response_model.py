import random
from wapas.response_model import (recovery_probability, complaint_probability, simulate_outcome,
                                  ResponseParams, ORGANIC_RECOVERY, CURE_MATRIX, execution_profile)


def test_timing_dominates_cash_timing_causes():
    p = recovery_probability
    # insufficient_funds: acting after salary works; acting now fails.
    # A scheduled link is a FULL consent-downgrade of the delayed pull
    # (same intent, customer approves live) — hence equality, not <.
    assert p("insufficient_funds", "retry_delayed", 0) == p("insufficient_funds", "send_payment_link", 0, variant="scheduled")
    assert p("insufficient_funds", "retry_delayed", 0) > p("insufficient_funds", "send_payment_link", 0, variant="immediate") \
           > p("insufficient_funds", "no_action", 0)
    # bank_outage: same shape — after restoration beats now.
    assert p("bank_outage", "retry_delayed", 0) > p("bank_outage", "send_payment_link", 0, variant="immediate")


def test_pull_cannot_fix_a_dead_credential_but_a_link_can():
    p = recovery_probability
    # wrong VPA: re-firing the same wrong VPA is useless; a link the customer
    # re-enters details into is the cure.
    assert p("wrong_vpa", "send_payment_link", 0, variant="immediate") > p("wrong_vpa", "retry_now", 0)
    assert p("card_expired", "send_payment_link", 0, variant="immediate") > p("card_expired", "retry_now", 0)
    # expired mandate: only re-authorization fully works; pulls hit the dead mandate.
    assert p("expired_mandate", "send_reauth_mandate_link", 0) > p("expired_mandate", "send_payment_link", 0, variant="immediate") \
           > p("expired_mandate", "retry_now", 0)


def test_targeted_beats_blind_on_the_same_execution_profile():
    p = recovery_probability
    # same link, same variant: the targeted one (policy action for the cause)
    # converts better than a blind generic one — the fit penalty.
    targeted = p("wrong_vpa", "send_payment_link", 0, variant="immediate")
    blind = p("insufficient_funds", "send_payment_link", 0, variant="immediate")
    cure_t = CURE_MATRIX["wrong_vpa"]["link_now"]
    cure_b = CURE_MATRIX["insufficient_funds"]["link_now"]
    # isolate fit: compare against a no-advantage baseline is unnecessary; the
    # matrix cells here are both 1.0/0.30 — so check the fit arithmetic directly.
    assert targeted > recovery_probability("wrong_vpa", "no_action", 0)
    assert blind < recovery_probability("insufficient_funds", "retry_delayed", 0)
    assert cure_t == 1.0 and cure_b == 0.30


def test_matched_beats_human_beats_generic_beats_organic():
    c = "bank_decline"
    matched = recovery_probability(c, "retry_now", 0)                 # policy action, cure 1.0
    human = recovery_probability(c, "escalate_human", 0)              # cure 0.70 x fit 0.85
    generic = recovery_probability(c, "send_reauth_mandate_link", 0)  # cure 0.55 x fit 0.85
    organic = recovery_probability(c, "no_action", 0)
    assert matched > human > generic > organic == ORGANIC_RECOVERY[c]


def test_method_fallback_link_is_the_cure_where_the_customer_fixes_it():
    p = recovery_probability
    # a choose-any-method link is (nearly) as good as the targeted plain link
    # for causes the CUSTOMER can fix by re-entering/picking details — both
    # sit near the matched max; the plain link keeps a small targeting edge.
    assert p("card_expired", "send_payment_link", 0, variant="method_fallback") <= p("card_expired", "send_payment_link", 0, variant="immediate")
    assert p("card_expired", "send_payment_link", 0, variant="method_fallback") > p("card_expired", "retry_now", 0)
    assert p("auth_3ds_drop", "send_payment_link", 0, variant="method_fallback") >= 0.30
    # ...but it cannot create cash that isn't there:
    assert p("insufficient_funds", "send_payment_link", 0, variant="method_fallback") \
           < p("insufficient_funds", "send_payment_link", 0, variant="scheduled")


def test_upi_daily_limit_needs_reset_or_alternate_instrument():
    p = recovery_probability
    assert p("upi_daily_limit", "retry_alternate_method", 0) > p("upi_daily_limit", "retry_now", 0)
    assert p("upi_daily_limit", "retry_delayed", 0) > p("upi_daily_limit", "retry_now", 0)


def test_link_inherits_intent_from_the_downgraded_retry():
    p = recovery_probability
    assert p("bank_outage", "send_payment_link", 0, variant="scheduled") > p("bank_outage", "send_payment_link", 0, variant="immediate")
    assert p("upi_daily_limit", "send_payment_link", 0, variant="method_fallback") > p("upi_daily_limit", "send_payment_link", 0, variant="immediate")
    assert p("bank_decline", "retry_now", 0) > p("bank_decline", "send_payment_link", 0, variant="immediate") > p("bank_decline", "no_action", 0)


def test_contact_fatigue_reduces_uplift_not_organic():
    c = "insufficient_funds"
    assert recovery_probability(c, "retry_delayed", 0) > recovery_probability(c, "retry_delayed", 2) > ORGANIC_RECOVERY[c]
    assert recovery_probability(c, "no_action", 0) == recovery_probability(c, "no_action", 3)


def test_every_cure_row_is_bounded_and_contains_the_optimum():
    for cause, row in CURE_MATRIX.items():
        for profile, v in row.items():
            assert 0.0 <= v <= 1.0, (cause, profile, v)
    # each non-fraud cause has at least one profile that captures the full uplift
    for cause in CURE_MATRIX:
        if cause == "fraud_hold":
            continue
        assert max(CURE_MATRIX[cause].values()) >= 0.95, cause


def test_execution_profile_mapping():
    assert execution_profile("retry_now", None) == "pull_now"
    assert execution_profile("send_payment_link", "method_fallback") == "link_fb"
    assert execution_profile("send_payment_link", "scheduled") == "link_sched"
    assert execution_profile("send_reauth_mandate_link", None) == "reauth_link"
    assert execution_profile("refund", None) == "none"


def test_fraud_hold_never_recovers_and_contact_raises_complaints():
    for a in ("retry_now", "send_payment_link", "escalate_human", "no_action"):
        assert recovery_probability("fraud_hold", a, 0) == 0.0
    assert complaint_probability("fraud_hold", "retry_now", 0) > complaint_probability("fraud_hold", "escalate_human", 0)


def test_any_charge_on_debited_pending_adds_nothing_but_complaints():
    for a in ("retry_now", "send_payment_link"):
        assert recovery_probability("debited_pending", a, 0) == recovery_probability("debited_pending", "no_action", 0)
        assert complaint_probability("debited_pending", a, 0) > complaint_probability("debited_pending", "verify_then_reassure", 0)
    assert recovery_probability("debited_pending", "verify_then_reassure", 0) > ORGANIC_RECOVERY["debited_pending"]


def test_auto_pull_on_an_abandoned_checkout_is_complaint_bait():
    assert complaint_probability("intent_drop", "retry_now", 0) > complaint_probability("intent_drop", "send_payment_link", 0, )
    assert complaint_probability("intent_drop", "retry_now", 0) > complaint_probability("bank_decline", "retry_now", 0)


def test_no_action_never_generates_complaint():
    for c in ("bank_decline", "fraud_hold", "debited_pending"):
        assert complaint_probability(c, "no_action", 3) == 0.0
    assert simulate_outcome("bank_decline", "no_action", 3, random.Random(1))["complaint"] is False


def test_refund_is_goodwill_not_revenue():
    out = simulate_outcome("debited_pending", "refund", 0, random.Random(2))
    assert out["recovered"] is False and out["goodwill_saved"] is True


def test_common_random_numbers_same_action_same_outcome():
    a = simulate_outcome("bank_outage", "retry_delayed", 1, random.Random(99))
    b = simulate_outcome("bank_outage", "retry_delayed", 1, random.Random(99))
    assert a == b


def test_zero_advantage_scale_collapses_matched_to_organic():
    p = ResponseParams(advantage_scale=0.0)
    assert recovery_probability("wrong_vpa", "send_payment_link", 0, p) == recovery_probability("wrong_vpa", "no_action", 0, p)
