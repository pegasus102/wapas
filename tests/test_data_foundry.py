from datetime import timedelta
from wapas.data_foundry import generate_events, CAUSE_WEIGHTS, REASON_TO_CAUSES
from wapas.schema import EvidencePacket


def test_generation_is_deterministic():
    a = generate_events(200, seed=7)
    b = generate_events(200, seed=7)
    assert [p.to_dict() for p, _ in a] == [p.to_dict() for p, _ in b]
    assert [c for _, c in a] == [c for _, c in b]


def test_different_seeds_differ():
    a = generate_events(200, seed=1)
    b = generate_events(200, seed=2)
    assert [c for _, c in a] != [c for _, c in b]


def test_cause_mix_matches_declared_weights():
    events = generate_events(4000, seed=3)
    n = len(events)
    for cause, w in CAUSE_WEIGHTS.items():
        freq = sum(1 for _, c in events if c == cause) / n
        assert abs(freq - w) < 0.03, (cause, freq, w)


def test_bank_health_distributions_genuinely_overlap():
    events = generate_events(4000, seed=4)
    decline = [p.bank_health_score for p, c in events if c == "bank_decline"]
    outage = [p.bank_health_score for p, c in events if c == "bank_outage"]
    # tails cross: some plain declines look like outages and vice versa
    assert any(h < 0.30 for h in decline)
    assert any(h > 0.35 for h in outage)
    # but the bulk is still separable
    assert sum(decline) / len(decline) > sum(outage) / len(outage) + 0.2


def test_payment_failed_reason_is_shared_by_multiple_causes():
    assert len(REASON_TO_CAUSES["PAYMENT_FAILED"]) >= 3
    assert len(REASON_TO_CAUSES["BANK_DECLINED"]) == 3
    events = generate_events(4000, seed=5)
    causes_seen = {c for p, c in events if p.error_reason == "PAYMENT_FAILED"}
    assert len(causes_seen) >= 3


def test_free_text_is_real_signal_not_decoration():
    events = generate_events(4000, seed=6)
    share_with_text = sum(1 for p, _ in events if p.free_text) / len(events)
    assert share_with_text >= 0.15
    # the video case must be able to occur: debited_pending reported as a
    # generic failure, flag FALSE, only the customer's words carry it
    text_only = [p for p, c in events
                 if c == "debited_pending" and p.error_reason == "PAYMENT_FAILED"]
    assert text_only, "text-only debited_pending variant never generated"
    assert all(not p.debit_confirmation_flag for p in text_only)
    assert any(p.free_text for p in text_only)


def test_mandates_only_for_subscriber_cohort():
    events = generate_events(4000, seed=8)
    non_mandate = [p for p, c in events if c != "expired_mandate"]
    share_none = sum(1 for p in non_mandate if p.mandate_status == "none") / len(non_mandate)
    assert 0.65 < share_none < 0.90
    assert all(p.mandate_status == "expired" for p, c in events if c == "expired_mandate")
    assert all(p.mandate_status == "active" for p, _ in events if p.predebit_notified)


def test_timestamps_are_ist_aware_and_fields_consistent():
    events = generate_events(500, seed=9)
    for p, _ in events:
        t = p.event_time()
        assert t.utcoffset() == timedelta(hours=5, minutes=30)
        assert p.attempt_no == p.retry_count + 1
        band = "low" if p.amount < 999 else ("mid" if p.amount < 4999 else "high")
        assert p.value_band == band
        assert p.error_code in ("BAD_REQUEST_ERROR", "GATEWAY_ERROR", "SERVER_ERROR")


def test_true_cause_never_inside_evidence_packet():
    p, cause = generate_events(1, seed=10)[0]
    assert isinstance(p, EvidencePacket)
    assert "true_cause" not in p.to_dict()
    assert cause not in p.to_dict().values() or cause in ("upi", "card")  # cause names never leak as field values