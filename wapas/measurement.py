"""
wapas.measurement
-------------------
Runs the full experiment and produces the Floor -> Rules -> Real -> Ceiling
table (Control is the implicit zero line). Every arm/line is logged to its
own ledger file so the whole run is auditable and CI can regenerate it
byte-for-byte from the same seed.

Design notes (see ARCHITECTURE.md / HYPOTHESES.md for the full writeup):
  - Control, Floor, and WAPAS are the three RANDOMLY ASSIGNED, EXECUTED arms.
  - Rules-only and Oracle are ANALYTIC lines computed on the SAME event set
    assigned to the WAPAS arm (not additional randomized arms) — they
    answer "what if we used rules alone" / "what if diagnosis were
    perfect", holding the exact same events and gate constant.
  - Every arm/line uses its OWN Gate instance (own contact/budget/breaker
    state) because they represent counterfactual "what if we had run this
    policy against this batch" universes, not a shared, contended resource.
"""

from __future__ import annotations
import random
from datetime import datetime
from pathlib import Path

from . import diagnosis as diagnosis_mod
from . import rules_tier, baselines, detector, executor
from .schema import ORACLE_ACTION
from .policy_gate import Gate
from .ledger import Ledger
from .stats_utils import wilson_ci, two_proportion_ztest, approx_power

RUN_TIME = datetime(2026, 9, 4, 12, 0, 0)  # fixed simulated "now": mid-afternoon, not quiet hours


def _oracle_diagnosis(true_cause: str) -> dict:
    return {
        "root_cause": true_cause,
        "confidence": 1.0,
        "action": ORACLE_ACTION[true_cause],
        "source": "oracle",
    }


def _rules_only_diagnosis(evidence) -> dict:
    hint = rules_tier.diagnose(evidence)
    return {
        "root_cause": hint["root_cause"],
        "confidence": max(hint["confidence"], 0.56),  # rules always commits to its best guess
        "action": hint["action"],
        "source": "rules_only_line",
    }


def run_line(
    name: str,
    events: list[tuple],
    diagnose_fn,
    ledger_path: Path,
    seed: int,
) -> dict:
    """events: list of (EvidencePacket, true_cause). diagnose_fn(evidence) -> diagnosis dict."""
    gate = Gate()
    ledger = Ledger(ledger_path)
    packets = [p for p, _ in events]
    detector.annotate(packets)

    rows = []
    for packet, true_cause in events:
        d = diagnose_fn(packet)
        decision = gate.decide(packet, d, RUN_TIME)
        outcome = executor.execute_sim(decision, true_cause, decision["contacts_before"])
        gate.circuit_breaker_record(decision["root_cause"], decision["final_action"], outcome["complaint"])

        row = {**decision, "true_cause": true_cause, **outcome, "amount": packet.amount}
        ledger.append(row)
        rows.append(row)

    return _summarize(name, rows)


def _summarize(name: str, rows: list[dict]) -> dict:
    n = len(rows)
    recovered = sum(1 for r in rows if r["recovered"])
    complaints = sum(1 for r in rows if r["complaint"])
    recovered_amount = sum(r["amount"] for r in rows if r["recovered"])
    at_risk_amount = sum(r["amount"] for r in rows)
    n_actioned = sum(1 for r in rows if r["final_action"] != "no_action")
    lo, hi = wilson_ci(recovered, n)
    return {
        "arm": name,
        "n": n,
        "recovered": recovered,
        "recovery_rate": recovered / n if n else 0.0,
        "ci_95": (round(lo, 4), round(hi, 4)),
        "recovered_amount": round(recovered_amount, 2),
        "at_risk_amount": round(at_risk_amount, 2),
        "complaints": complaints,
        "complaint_rate": complaints / n if n else 0.0,
        "n_actioned": n_actioned,
        "rows": rows,
    }


def run_experiment(events: list[tuple], out_dir: Path, seed: int = 2026) -> dict:
    from .stratify import stratified_split

    out_dir.mkdir(parents=True, exist_ok=True)
    arms = stratified_split(events, seed=seed)

    control_diagnose = lambda ev: {"root_cause": "unknown", "confidence": 1.0, "action": "no_action", "source": "control"}
    floor_diagnose = baselines.floor_diagnose
    wapas_diagnose = lambda ev: diagnosis_mod.diagnose_event(ev, live=False)

    results = {}
    results["control"] = run_line("control", arms["control"], control_diagnose, out_dir / "ledger_control.jsonl", seed + 1)
    results["floor"] = run_line("floor", arms["floor"], floor_diagnose, out_dir / "ledger_floor.jsonl", seed + 2)
    results["wapas"] = run_line("wapas", arms["wapas"], wapas_diagnose, out_dir / "ledger_wapas.jsonl", seed + 3)
    # Analytic lines, computed on the SAME events as the wapas arm.
    results["rules_only"] = run_line("rules_only", arms["wapas"], _rules_only_diagnosis, out_dir / "ledger_rules_only.jsonl", seed + 4)
    true_cause_by_event = {p.event_id: c for p, c in arms["wapas"]}
    results["oracle"] = run_line(
        "oracle", arms["wapas"],
        lambda ev: _oracle_diagnosis(true_cause_by_event[ev.event_id]),
        out_dir / "ledger_oracle.jsonl", seed + 5,
    )

    # Confirmatory stats: two-proportion z-tests on the RANDOMIZED arms only.
    c, f, w = results["control"], results["floor"], results["wapas"]
    stats = {
        "control_vs_floor": two_proportion_ztest(c["recovered"], c["n"], f["recovered"], f["n"]),
        "floor_vs_wapas": two_proportion_ztest(f["recovered"], f["n"], w["recovered"], w["n"]),
        "control_vs_wapas": two_proportion_ztest(c["recovered"], c["n"], w["recovered"], w["n"]),
        "power_floor_vs_wapas_at_observed_effect": approx_power(
            f["recovery_rate"], w["recovery_rate"], n_per_arm=min(f["n"], w["n"])
        ),
    }
    ceiling_capture = w["recovery_rate"] / results["oracle"]["recovery_rate"] if results["oracle"]["recovery_rate"] else 0.0

    return {"results": results, "stats": stats, "ceiling_capture_pct": round(ceiling_capture * 100, 1)}
