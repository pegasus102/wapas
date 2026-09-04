"""
wapas.data_foundry
-------------------
Seeded synthetic generator for a 30-day D2C merchant on Razorpay rails.

Returns a list of (EvidencePacket, true_cause). `true_cause` is returned
SEPARATELY on purpose: code allowed to see it (measurement, eval, the
oracle) unpacks it explicitly; code that must never see it (detector,
rules tier, diagnosis agent, policy gate) only ever receives the packet.

Where the ambiguity comes from (all of it is documented here, nothing is
hidden in thresholds elsewhere):
  * Two coarse error_reason buckets are shared by several causes:
      BANK_DECLINED  <- bank_decline | bank_outage | upi_daily_limit
      PAYMENT_FAILED <- intent_drop | auth_3ds_drop (40%) | wrong_vpa (35%)
                        | debited_pending (15%, and in that variant the
                          debit flag is FALSE — only the customer's own
                          words carry the signal)
  * The disambiguating features are DISTRIBUTIONS WITH OVERLAPPING TAILS,
    not disjoint ranges: bank_health_score ~ clipped Normal, attempts_today
    ~ Poisson. Rules can resolve the bulk; the tails are honestly ambiguous.
  * Free text is a real signal (Hinglish/English customer or support notes)
    with cause-specific phrasing, plus generic filler that carries nothing.

Same (n, seed) => byte-identical output, always.
"""

from __future__ import annotations
import math
import random
from datetime import datetime, timedelta
from .schema import EvidencePacket, CAUSES, IST

# ---------------------------------------------------------------------------
# Cause prior (UPI-dominant merchant; fraud/mandate/debited-pending are
# minority-but-important classes).
# ---------------------------------------------------------------------------
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
assert abs(sum(CAUSE_WEIGHTS.values()) - 1.0) < 1e-9
assert set(CAUSE_WEIGHTS) == set(CAUSES)

# Cause -> (error_reason, probability). Several causes SHARE a reason.
CAUSE_REASON_MIX = {
    "bank_decline":       [("BANK_DECLINED", 1.0)],
    "bank_outage":        [("BANK_DECLINED", 1.0)],
    "upi_daily_limit":    [("BANK_DECLINED", 1.0)],
    "insufficient_funds": [("INSUFFICIENT_FUNDS", 1.0)],
    "auth_3ds_drop":      [("AUTHENTICATION_FAILED", 0.60), ("PAYMENT_FAILED", 0.40)],
    "expired_mandate":    [("MANDATE_EXPIRED", 1.0)],
    "wrong_vpa":          [("INVALID_VPA", 0.65), ("PAYMENT_FAILED", 0.35)],
    "gateway_timeout":    [("GATEWAY_TIMEOUT", 1.0)],
    "fraud_hold":         [("RISK_BLOCKED", 1.0)],
    "debited_pending":    [("PAYMENT_PENDING_CONFIRMATION", 0.85), ("PAYMENT_FAILED", 0.15)],
    "intent_drop":        [("PAYMENT_FAILED", 1.0)],
    "card_expired":       [("CARD_EXPIRED", 1.0)],
}
# Primary reason per cause (back-compat) and the inverse map used by rules.
CAUSE_TO_REASON = {c: mix[0][0] for c, mix in CAUSE_REASON_MIX.items()}
REASON_TO_CAUSES: dict[str, set[str]] = {}
for _c, _mix in CAUSE_REASON_MIX.items():
    for _r, _ in _mix:
        REASON_TO_CAUSES.setdefault(_r, set()).add(_c)

# Feature distributions ------------------------------------------------------
HEALTH_PARAMS = {                      # (mu, sigma) of clipped Normal on [0,1]
    "bank_outage": (0.22, 0.15),
    "bank_decline": (0.55, 0.18),
    "gateway_timeout": (0.65, 0.15),
}
DEFAULT_HEALTH_PARAMS = (0.80, 0.12)

ATTEMPTS_LAMBDA = {"upi_daily_limit": 3.5}   # Poisson rate
DEFAULT_ATTEMPTS_LAMBDA = 0.9
ATTEMPTS_MAX = 8

DEBIT_FLAG_TRUE_POSITIVE = 0.90
DEBIT_FLAG_FALSE_POSITIVE = 0.02

STEP_MIX = {
    "auth_3ds_drop":   [("payment_authentication", 0.80), ("payment_authorization", 0.20)],
    "wrong_vpa":       [("payment_initiation", 0.55), ("payment_authorization", 0.45)],
    "intent_drop":     [("payment_initiation", 0.65), ("payment_authentication", 0.35)],
    "debited_pending": [("payment_capture", 0.70), ("payment_authorization", 0.30)],
    "gateway_timeout": [("payment_authorization", 0.60), ("payment_capture", 0.40)],
    "fraud_hold":      [("payment_authorization", 1.0)],
    "expired_mandate": [("payment_initiation", 0.70), ("payment_authorization", 0.30)],
}
DEFAULT_STEP_MIX = [("payment_authorization", 0.70), ("payment_authentication", 0.30)]

SOURCE_MIX = {
    "wrong_vpa":          [("customer", 0.70), ("bank", 0.20), ("gateway", 0.10)],
    "intent_drop":        [("customer", 0.60), ("internal", 0.25), ("gateway", 0.15)],
    "auth_3ds_drop":      [("bank", 0.50), ("customer", 0.40), ("gateway", 0.10)],
    "debited_pending":    [("bank", 0.80), ("gateway", 0.20)],
    "gateway_timeout":    [("gateway", 0.80), ("internal", 0.20)],
    "fraud_hold":         [("business", 0.80), ("internal", 0.20)],
    "insufficient_funds": [("customer", 0.70), ("bank", 0.30)],
    "card_expired":       [("customer", 0.60), ("bank", 0.40)],
    "expired_mandate":    [("customer", 0.50), ("bank", 0.50)],
}
DEFAULT_SOURCE_MIX = [("bank", 0.70), ("gateway", 0.20), ("customer", 0.10)]

METHOD_MIX = {
    "card_expired":    [("card", 1.0)],
    "auth_3ds_drop":   [("card", 0.90), ("netbanking", 0.10)],
    "upi_daily_limit": [("upi", 1.0)],
    "wrong_vpa":       [("upi", 1.0)],
    "intent_drop":     [("upi", 1.0)],
    "debited_pending": [("upi", 0.90), ("netbanking", 0.10)],
    "expired_mandate": [("upi", 0.85), ("card", 0.15)],
}
DEFAULT_METHOD_MIX = [("upi", 0.70), ("card", 0.18), ("netbanking", 0.12)]

GEO_MIX = {
    "bank_outage":  [("metro", 0.30), ("tier2", 0.30), ("tier3", 0.40)],
    "bank_decline": [("metro", 0.35), ("tier2", 0.30), ("tier3", 0.35)],
}
DEFAULT_GEO_MIX = [("metro", 0.45), ("tier2", 0.30), ("tier3", 0.25)]

# Free text: (probability, phrases). Cause-specific phrasing = real signal.
FREE_TEXT = {
    "debited_pending":    (0.75, ["paise kat gaye par order nahi hua",
                                  "amount deducted, no confirmation",
                                  "money debited from account but showing failed",
                                  "balance kam ho gaya lekin order confirm nahi hua"]),
    "auth_3ds_drop":      (0.45, ["OTP nahi aaya", "otp time out ho gaya",
                                  "bank page kept loading", "3d secure page stuck"]),
    "wrong_vpa":          (0.45, ["galat UPI id daal di", "typed wrong upi id i think",
                                  "invalid upi address bol raha"]),
    "intent_drop":        (0.40, ["app khul ke band ho gaya", "phonepe pe redirect hua fir kuch nahi",
                                  "got distracted, didn't finish", "payment page pe atak gaya"]),
    "bank_outage":        (0.25, ["bank server down lag raha hai", "sab transactions fail ho rahe aaj",
                                  "bank app bhi nahi khul raha"]),
    "upi_daily_limit":    (0.30, ["limit exceed bol raha hai", "aaj bahut transactions kiye",
                                  "daily limit reached message aaya"]),
    "card_expired":       (0.35, ["card is expired I think", "purana card tha shayad"]),
    "expired_mandate":    (0.35, ["autopay stopped working", "mandate expired lagta hai"]),
    "insufficient_funds": (0.20, ["salary abhi aayi nahi", "balance kam tha", "will pay after 1st"]),
}
TEXT_ONLY_VARIANT_PROB = 0.95     # debited_pending reported as PAYMENT_FAILED: words are the only signal
GENERIC_TEXT = ["payment did not go through", "try nahi ho raha", "failed again", "kya karu?"]
GENERIC_TEXT_PROB = 0.12

SUBSCRIBER_SHARE = 0.22
PREDEBIT_NOTIFIED_SHARE = 0.70
AMOUNT_RANGES = {"low": (199, 998), "mid": (999, 4998), "high": (4999, 12999)}
NIGHT_HOURS = [22, 23, 0, 1, 2, 3]
NIGHT_SHARE = {"bank_outage": 0.45, "gateway_timeout": 0.40}
DEFAULT_NIGHT_SHARE = 0.12
PRE_PAYDAY_DAYS = [23, 24, 25, 26, 27, 28, 29]   # end-of-month cash crunch


# ---------------------------------------------------------------------------
# helpers (all randomness goes through the one rng passed in)
# ---------------------------------------------------------------------------
def _weighted(rng: random.Random, mix):
    values = [v for v, _ in mix]
    weights = [w for _, w in mix]
    return rng.choices(values, weights=weights, k=1)[0]


def _clipped_normal(rng: random.Random, mu: float, sigma: float) -> float:
    return round(min(1.0, max(0.0, rng.gauss(mu, sigma))), 3)


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return min(k, ATTEMPTS_MAX)
        k += 1


def _bank_health_for(cause: str, rng: random.Random) -> float:
    mu, sigma = HEALTH_PARAMS.get(cause, DEFAULT_HEALTH_PARAMS)
    return _clipped_normal(rng, mu, sigma)


def _attempts_today_for(cause: str, rng: random.Random) -> int:
    return _poisson(rng, ATTEMPTS_LAMBDA.get(cause, DEFAULT_ATTEMPTS_LAMBDA))


def _debit_flag_for(cause: str, rng: random.Random) -> bool:
    if cause == "debited_pending":
        return rng.random() < DEBIT_FLAG_TRUE_POSITIVE
    return rng.random() < DEBIT_FLAG_FALSE_POSITIVE


def _error_code_for(source: str, rng: random.Random) -> str:
    if source in ("customer", "business"):
        return "BAD_REQUEST_ERROR"
    if source == "internal":
        return "SERVER_ERROR"
    return "GATEWAY_ERROR" if rng.random() < 0.80 else "BAD_REQUEST_ERROR"


def _day_for(cause: str, rng: random.Random) -> int:
    if cause == "insufficient_funds" and rng.random() < 0.60:
        return rng.choice(PRE_PAYDAY_DAYS)
    if cause == "bank_decline" and rng.random() < 0.30:
        return rng.choice(PRE_PAYDAY_DAYS)
    return rng.randint(0, 29)


def _timestamp(cause: str, day: int, rng: random.Random) -> datetime:
    base = datetime(2026, 8, 1, tzinfo=IST) + timedelta(days=day)
    if rng.random() < NIGHT_SHARE.get(cause, DEFAULT_NIGHT_SHARE):
        hour = rng.choice(NIGHT_HOURS)
    else:
        hour = rng.randint(7, 21)
    return base.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))


def _free_text_for(cause: str, text_only_variant: bool, rng: random.Random):
    if text_only_variant:
        return rng.choice(FREE_TEXT["debited_pending"][1]) if rng.random() < TEXT_ONLY_VARIANT_PROB else None
    spec = FREE_TEXT.get(cause)
    if spec and rng.random() < spec[0]:
        return rng.choice(spec[1])
    if rng.random() < GENERIC_TEXT_PROB:
        return rng.choice(GENERIC_TEXT)
    return None


def _mandate_status(cause: str, is_sub: bool, rng: random.Random) -> str:
    if cause == "expired_mandate":
        return "expired"
    if is_sub:
        return "active" if rng.random() < 0.95 else "expired"
    return "none"


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def generate_events(n: int, seed: int, id_prefix: str = "evt") -> list[tuple[EvidencePacket, str]]:
    """Deterministic: same (n, seed, id_prefix) always produces the same events."""
    rng = random.Random(seed)
    customer_pool = max(1, int(n * 0.7))
    out: list[tuple[EvidencePacket, str]] = []

    for i in range(n):
        cause = _weighted(rng, list(CAUSE_WEIGHTS.items()))
        reason = _weighted(rng, CAUSE_REASON_MIX[cause])
        method = _weighted(rng, METHOD_MIX.get(cause, DEFAULT_METHOD_MIX))
        geo = _weighted(rng, GEO_MIX.get(cause, DEFAULT_GEO_MIX))
        day = _day_for(cause, rng)
        ts = _timestamp(cause, day, rng)
        step = _weighted(rng, STEP_MIX.get(cause, DEFAULT_STEP_MIX))
        source = _weighted(rng, SOURCE_MIX.get(cause, DEFAULT_SOURCE_MIX))
        code = _error_code_for(source, rng)
        health = _bank_health_for(cause, rng)
        attempts = _attempts_today_for(cause, rng)

        text_only_variant = (cause == "debited_pending" and reason == "PAYMENT_FAILED")
        debit_flag = False if text_only_variant else _debit_flag_for(cause, rng)
        free_text = _free_text_for(cause, text_only_variant, rng)

        is_sub = (cause == "expired_mandate") or (rng.random() < SUBSCRIBER_SHARE)
        mandate = _mandate_status(cause, is_sub, rng)
        predebit = (mandate == "active") and (rng.random() < PREDEBIT_NOTIFIED_SHARE)

        retry_count = _weighted(rng, [(0, 0.60), (1, 0.30), (2, 0.10)])
        band = _weighted(rng, [("low", 0.45), ("mid", 0.35), ("high", 0.20)])
        lo, hi = AMOUNT_RANGES[band]
        amount = round(rng.uniform(lo, hi), 2)

        packet = EvidencePacket(
            event_id=f"{id_prefix}_{i:05d}",
            customer_id=f"cust_{rng.randint(0, customer_pool - 1):05d}",
            invoice_id=f"inv_{id_prefix}_{i:05d}",
            attempt_no=retry_count + 1,
            amount=amount,
            method=method,
            geo_tier=geo,
            timestamp_ist=ts.isoformat(),
            tenure_days=rng.randint(0, 900),
            mandate_status=mandate,
            retry_count=retry_count,
            error_code=code,
            error_source=source,
            error_reason=reason,
            error_step=step,
            bank_health_score=health,
            attempts_today=attempts,
            debit_confirmation_flag=debit_flag,
            free_text=free_text,
            predebit_notified=predebit,
            is_subscription=is_sub,
            value_band=band,
        )
        out.append((packet, cause))
    return out


def train_eval_split(events: list, eval_fraction: float = 0.2, seed: int = 7):
    """Kept for backward compatibility with the step-1 run_batch; step 3
    replaces it with a separately-seeded diagnosis-eval set."""
    rng = random.Random(seed)
    shuffled = events[:]
    rng.shuffle(shuffled)
    n_eval = int(len(shuffled) * eval_fraction)
    return shuffled[n_eval:], shuffled[:n_eval]