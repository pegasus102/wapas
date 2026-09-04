"""
tests/test_thesis_guard.py
--------------------------
THE thesis of WAPAS is: diagnosis-first recovery beats a competent generic
playbook. The response model can silently violate that — it did once (the
first intent-coverage model let a blanket method_fallback link score full
credit on 9 of 12 causes, collapsing Floor == WAPAS == Oracle). This test
exists so that can never happen again without a red test.

Runs a seeded mini-experiment (small n for speed) through the REAL pipeline
(detector -> diagnosis -> gate -> executor) and asserts the staircase:

    control < floor < wapas <= oracle
    wapas - floor >= GUARD_GAP_PP   (a real, non-trivial diagnosis effect)

If this fails, the causal model no longer discriminates diagnosis from
blindness — do not "fix" the test; fix the assumptions (CURE_MATRIX etc.),
documented, in response_model.py.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wapas.data_foundry import generate_events, train_eval_split
from wapas.measurement import run_line, _oracle_diagnosis
from wapas import baselines, diagnosis as dm

GUARD_GAP_PP = 1.0


def test_thesis_staircase_holds(tmp_path):
    events = generate_events(2500, seed=42)
    train, _eval = train_eval_split(events)
    truth = {p.event_id: c for p, c in train}

    control = lambda ev: {"root_cause": "unknown", "confidence": 1.0,
                          "action": "no_action", "source": "control"}
    res = {
        "control": run_line("control", train, control, tmp_path / "c.jsonl", 11),
        "floor": run_line("floor", train, baselines.floor_diagnose, tmp_path / "f.jsonl", 12),
        "wapas": run_line("wapas", train, lambda e: dm.diagnose_event(e, live=False), tmp_path / "w.jsonl", 13),
        "oracle": run_line("oracle", train, lambda e: _oracle_diagnosis(truth[e.event_id]), tmp_path / "o.jsonl", 14),
    }
    rate = {k: v["recovery_rate"] for k, v in res.items()}

    assert rate["control"] < rate["floor"], rate
    assert rate["floor"] < rate["wapas"], rate
    assert rate["wapas"] <= rate["oracle"] + 0.001, rate
    gap_pp = (rate["wapas"] - rate["floor"]) * 100
    assert gap_pp >= GUARD_GAP_PP, (
        f"Diagnosis effect collapsed to {gap_pp:.2f}pp (< {GUARD_GAP_PP}pp). "
        f"Rates: {rate}. The causal model no longer separates targeted "
        f"recovery from generic recovery — fix the documented assumptions, "
        f"not this test."
    )
