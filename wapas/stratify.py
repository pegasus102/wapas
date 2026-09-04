"""
wapas.stratify
--------------
Stratified 3-way random split. Stratifying on (true_cause, geo_tier,
value_band) and splitting each stratum as evenly as possible across the
three arms keeps the arms balanced on exactly the dimensions that could
otherwise confound the result (e.g. if Control happened to get more
easy-to-recover causes by chance).

This is the EXPERIMENTER's randomization step — it is allowed to see
true_cause because assigning events to arms is a design decision, not a
diagnosis. The arms themselves never see true_cause once assigned.
"""

from __future__ import annotations
import random
from collections import defaultdict

ARMS = ["control", "floor", "wapas"]


def stratified_split(events: list[tuple], seed: int) -> dict[str, list[tuple]]:
    """events: list of (EvidencePacket, true_cause). Returns dict arm -> events."""
    rng = random.Random(seed)
    strata: dict[tuple, list[tuple]] = defaultdict(list)
    for packet, cause in events:
        value_band = getattr(packet, "value_band", "mid")
        strata[(cause, packet.geo_tier, value_band)].append((packet, cause))

    result: dict[str, list[tuple]] = {arm: [] for arm in ARMS}
    for key, group in strata.items():
        rng.shuffle(group)
        offset = rng.randrange(3)  # randomise which arm absorbs a stratum's remainder
        for i, item in enumerate(group):
            arm = ARMS[(i + offset) % 3]
            result[arm].append(item)
    return result
