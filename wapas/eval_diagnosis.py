"""
wapas.eval_diagnosis
----------------------
Runs the FULL diagnosis pipeline (rules tier + diagnosis agent) against the
held-out eval split (never used for anything else) and reports:
  - plain accuracy
  - a COST-WEIGHTED confusion total (schema.confusion_cost) — a flat
    accuracy number treats "confused two harmless causes" the same as
    "told a fraud-hold customer to retry", which is not the risk profile
    that matters in this domain
  - a calibration check: does a diagnosis stated at confidence~X actually
    turn out right about X% of the time?
"""

from __future__ import annotations
from collections import defaultdict
from . import diagnosis as diagnosis_mod
from . import detector
from .schema import CAUSES, confusion_cost


def evaluate(eval_events: list[tuple]) -> dict:
    packets = [p for p, _ in eval_events]
    detector.annotate(packets)

    confusion = defaultdict(lambda: defaultdict(int))
    total_cost = 0.0
    correct = 0
    calib_buckets = defaultdict(lambda: {"n": 0, "correct": 0})  # bucketed by confidence decile

    for packet, true_cause in eval_events:
        d = diagnosis_mod.diagnose_event(packet)
        pred = d["root_cause"]
        confusion[true_cause][pred] += 1
        total_cost += confusion_cost(true_cause, pred)
        is_correct = pred == true_cause
        correct += is_correct

        bucket = round(d["confidence"], 1)
        calib_buckets[bucket]["n"] += 1
        calib_buckets[bucket]["correct"] += is_correct

    n = len(eval_events)
    calibration = {
        conf: {"n": v["n"], "empirical_accuracy": round(v["correct"] / v["n"], 3) if v["n"] else None}
        for conf, v in sorted(calib_buckets.items())
    }

    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "avg_confusion_cost": round(total_cost / n, 4) if n else 0.0,
        "confusion_matrix": {t: dict(preds) for t, preds in confusion.items()},
        "calibration": calibration,
    }