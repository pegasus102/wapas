"""
wapas.detector
--------------
Deterministic, no-LLM detection of "at risk" revenue events. In this build,
data_foundry already only emits failed/at-risk events, so the detector's
job is to compute two derived FEATURES that the rest of the pipeline
depends on (this is genuinely rule-based work, not just a pass-through):

  - is_repeat_failure: same customer, 2nd+ failure in the batch window
  - is_ambiguous_reason: error_reason is one of the coarse, overlapping
    buckets that cannot be resolved by a 1:1 lookup

Nothing here uses randomness or sees the hidden true_cause.
"""

from __future__ import annotations
from collections import defaultdict
from .schema import EvidencePacket

AMBIGUOUS_REASONS = {"BANK_DECLINED", "PAYMENT_FAILED"}


def annotate(events: list[EvidencePacket]) -> None:
    """Mutates events in place, adding detector-derived fields."""
    seen_count: dict[str, int] = defaultdict(int)
    for p in events:
        seen_count[p.customer_id] += 1
        p.is_repeat_failure = seen_count[p.customer_id] > 1          # type: ignore[attr-defined]
        p.is_ambiguous_reason = p.error_reason in AMBIGUOUS_REASONS  # type: ignore[attr-defined]