"""
wapas.data_foundry
-------------------
Seeded synthetic generator for a 30-day D2C merchant on Razorpay rails.

Produces a list of (EvidencePacket, true_cause) pairs. `true_cause` is
returned SEPARATELY from the EvidencePacket on purpose: any code that is
allowed to see it (measurement, eval, the oracle) imports it explicitly;
any code that should never see it (detector, rules tier, diagnosis agent,
policy gate) only ever receives the EvidencePacket.

Deliberate ambiguity (~35% of events): several causes share a coarse
`error_reason` and can only be told apart using bank_health_score /
attempts_today / debit_confirmation_flag / free_text — which is exactly
the evidence the rules tier and diagnosis agent are given to work with.
"""

from __future__ import annotations
import random
from datetime import datetime, timedelta
from .schema import EvidencePacket, CAUSES

# Cause -> coarse error_reason. Several causes deliberately SHARE a reason
# so the taxonomy cannot be solved by a lookup table alone.
CAUSE_TO_REASON = {
    "bank_decline": "BANK_DECLINED",
    "bank_outage": "BANK_DECLINED",          # ambiguous w/ bank_decline
    "upi_daily_limit": "BANK_DECLINED",      # ambiguous w/ bank_decline
    "insufficient_funds": "INSUFFICIENT_FUNDS",
    "auth_3ds_drop": "AUTHENTICATION_FAILED",
    "expired_mandate": "MANDATE_EXPIRED",
    "wrong_vpa": "INVALID_VPA",
    "gateway_timeout": "GATEWAY_TIMEOUT",
    "fraud_hold": "RISK_BLOCKED",
    "debited_pending": "PAYMENT_PENDING_CONFIRMATION",
    "intent_drop": "PAYMENT_FAILED",         # generic / low-information reason
    "card_expired": "CARD_EXPIRED",
}

FREE_TEXT_HINTS = {
    "debited_pending": ["paise kat gaye par order nahi hua", "amount deducted, no confirmation"],
    "card_expired": ["card is expired I think", "purana card tha shayad"],
    "expired_mandate": ["autopay stopped working", "mandate expired lagta hai"],
}

# Base cause prior (roughly reflects: UPI dominant method, tier-3 congestion,
# fraud/mandate/debited-pending as minority-but-important classes).
CAUSE_WEIGHTS = {
    "bank_decline": 0.16,
    "insufficient_funds": 0.14,
    "auth_3ds_drop": 0.10,
    "expired_mandate": 0.08,
    "wrong_vpa": 0.06,
    "gateway_timeout": 0.10,
    "fraud_hold": 0.04,
    "debited_pending": 0.06,
    "bank_outage": 0.08,
    "upi_daily_limit": 0.06,
    "intent_drop": 0.07,
    "card_expired": 0.05,
}

GEO_TIERS = ["metro", "tier2", "tier3"]
GEO_WEIGHTS = [0.45, 0.30, 0.25]
METHODS = ["upi", "card", "netbanking"]
METHOD_WEIGHTS = [0.70, 0.20, 0.10]


def _sample_cause(rng: random.Random) -> str:
    causes, weights = zip(*CAUSE_WEIGHTS.items())
    return rng.choices(causes, weights=weights, k=1)[0]


def _bank_health_for(cause: str, rng: random.Random) -> float:
    if cause == "bank_outage":
        return round(rng.uniform(0.02, 0.30), 3)
    if cause == "bank_decline":
        return round(rng.uniform(0.35, 0.85), 3)
    return round(rng.uniform(0.55, 0.98), 3)


def _attempts_today_for(cause: str, rng: random.Random) -> int:
    if cause == "upi_daily_limit":
        return rng.randint(3, 6)
    return rng.randint(0, 2)


def _debit_confirmation_flag_for(cause: str, rng: random.Random) -> bool:
    if cause == "debited_pending":
        return rng.random() < 0.90        # 10% false negative
    return rng.random() < 0.03             # 3% false positive noise elsewhere


def _timestamp(day: int, rng: random.Random) -> datetime:
    base = datetime(2026, 8, 1) + timedelta(days=day)
    # salary-cycle effect handled by caller via day selection; here just hour
    if rng.random() < 0.18:
        hour = rng.choice([0, 1, 2, 3, 22, 23])   # night congestion window
    else:
        hour = rng.randint(7, 21)
    return base.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))


def generate_events(n: int, seed: int, ambiguity_rate: float = 0.35) -> list[tuple[EvidencePacket, str]]:
    """
    Deterministic generator: same (n, seed) always produces the same events.
    Returns a list of (EvidencePacket, true_cause).
    """
    rng = random.Random(seed)
    out = []
    for i in range(n):
        cause = _sample_cause(rng)
        geo = rng.choices(GEO_TIERS, weights=GEO_WEIGHTS, k=1)[0]
        method = rng.choices(METHODS, weights=METHOD_WEIGHTS, k=1)[0]
        # salary-cycle skew: bias insufficient_funds / bank_decline into days 1-7
        day = rng.randint(0, 29)
        if cause in ("insufficient_funds", "bank_decline") and rng.random() < 0.5:
            day = rng.randint(0, 6)
        ts = _timestamp(day, rng)

        reason = CAUSE_TO_REASON[cause]
        # Deliberate ambiguity: for the two reasons that are inherently
        # coarse (BANK_DECLINED shared by 3 causes, PAYMENT_FAILED generic),
        # only reveal disambiguating signal quality probabilistically.
        is_ambiguous_bucket = reason in ("BANK_DECLINED", "PAYMENT_FAILED")

        free_text = None
        hints = FREE_TEXT_HINTS.get(cause)
        if hints and rng.random() < 0.55:
            free_text = rng.choice(hints)
        elif is_ambiguous_bucket and rng.random() < ambiguity_rate:
            free_text = rng.choice(["payment did not go through", "try nahi ho raha"])

        amount = round(rng.uniform(199, 12999), 2)
        value_band = "low" if amount < 999 else ("mid" if amount < 4999 else "high")

        packet = EvidencePacket(
            event_id=f"evt_{i:05d}",
            customer_id=f"cust_{rng.randint(0, n // 2):05d}",
            invoice_id=f"inv_{i:05d}",
            attempt_no=1,
            amount=amount,
            method=method,
            geo_tier=geo,
            timestamp_ist=ts.isoformat(),
            tenure_days=rng.randint(0, 900),
            mandate_status=("active" if cause != "expired_mandate" else "expired")
            if rng.random() < 0.9 else rng.choice(["none", "active", "expired"]),
            retry_count=rng.randint(0, 2),
            error_code=f"BAD_REQUEST_{rng.randint(100,999)}" if cause == "wrong_vpa" else f"E{rng.randint(1000,9999)}",
            error_source=rng.choice(["bank", "customer", "gateway", "business"]),
            error_reason=reason,
            error_step=rng.choice(["payment_authentication", "authorization", "capture"]),
            bank_health_score=_bank_health_for(cause, rng),
            attempts_today=_attempts_today_for(cause, rng),
            debit_confirmation_flag=_debit_confirmation_flag_for(cause, rng),
            free_text=free_text,
        )
        # value_band is derived, stash it via a private attribute for convenience
        packet.value_band = value_band  # type: ignore[attr-defined]
        out.append((packet, cause))
    return out


def train_eval_split(events: list, eval_fraction: float = 0.2, seed: int = 7):
    """Held-out split used ONLY by eval/confusion.py — never by the live pipeline."""
    rng = random.Random(seed)
    shuffled = events[:]
    rng.shuffle(shuffled)
    n_eval = int(len(shuffled) * eval_fraction)
    return shuffled[n_eval:], shuffled[:n_eval]   # train, eval
