"""
wapas.measurement  (interim — full rewrite lands in step 3)
"""

from __future__ import annotations
from pathlib import Path

from . import diagnosis as diagnosis_mod
from . import rules_tier, baselines, detector, executor
from .schema import CAUSE_ACTION_POLICY
from .policy_gate import Gate
from .ledger import Ledger
from .stats_utils import wilson_ci, two_proportion_ztest, approx_power


def _oracle_diagnosis(true_cause: str) -> dict:
    return {"root_cause": true_cause, "confidence": 1.0,
            "action": CAUSE_ACTION_POLICY[true_cause], "source": "oracle"}


def _rules_only_diagnosis(evidence) -> dict:
    hint = rules_tier.diagnose(evidence)
    return {"root_cause": hint["root_cause"], "confidence": max(hint["confidence"], 0.56),
            "action": hint["action"], "source": "rules_only_line"}


def run_line(name: str, events: list[tuple], diagnose_fn, ledger_path: Path, seed: int) -> dict:
    gate = Gate()
    ledger_path.unlink(missing_ok=True)          # fresh chain per run; never append to an old one
    ledger = Ledger(ledger_path)
    packets = [p for p, _ in events]
    detector.annotate(packets)

    # Chronological order: contact windows, quiet hours, daily budget and
    # human capacity are all functions of WHEN the event happened.
    ordered = sorted(events, key=lambda ec: ec[0].event_time())

    rows = []
    for packet, true_cause in ordered:
        now = packet.event_time()
        d = diagnose_fn(packet)
        decision = gate.decide(packet, d, now)
        outcome = executor.execute_sim(decision, true_cause, decision["contacts_before"])
        gate.circuit_breaker_record(decision["root_cause"], decision["final_action"], outcome["complaint"])
        row = {**decision, "true_cause": true_cause, **outcome}
        ledger.append(row)
        rows.append(row)
    for ev in gate.breaker_events:
        ledger.append({"event_id": None, "gate_event": ev})
    return _summarize(name, rows)


def _summarize(name: str, rows: list[dict]) -> dict:
    n = len(rows)
    recovered = sum(1 for r in rows if r["recovered"])
    complaints = sum(1 for r in rows if r["complaint"])
    lo, hi = wilson_ci(recovered, n)
    return {
        "arm": name,
        "n": n,
        "recovered": recovered,
        "recovery_rate": recovered / n if n else 0.0,
        "ci_95": (round(lo, 4), round(hi, 4)),
        "recovered_amount": round(sum(r["recovered_inr"] for r in rows), 2),
        "at_risk_amount": round(sum(r["amount"] for r in rows), 2),
        "net_amount": round(sum(r["net_inr"] for r in rows), 2),
        "complaints": complaints,
        "complaint_rate": complaints / n if n else 0.0,
        "n_actioned": sum(1 for r in rows if r["final_action"] != "no_action"),
        "n_deferred": sum(1 for r in rows if r["policy_result"] == "deferred"),
        "n_human": sum(1 for r in rows if r["final_action"] == "escalate_human"),
        "n_blocked": sum(1 for r in rows if r["policy_result"] == "blocked"),
        "rows": rows,
    }


def run_experiment(events: list[tuple], out_dir: Path, seed: int = 2026,
                   live: bool = False) -> dict:
    from .stratify import stratified_split
    out_dir.mkdir(parents=True, exist_ok=True)
    arms = stratified_split(events, seed=seed)

    control = lambda ev: {"root_cause": "unknown", "confidence": 1.0, "action": "no_action", "source": "control"}
    wapas = lambda ev: diagnosis_mod.diagnose_event(ev, live=live)

    results = {}
    results["control"] = run_line("control", arms["control"], control, out_dir / "ledger_control.jsonl", seed + 1)
    results["floor"] = run_line("floor", arms["floor"], baselines.floor_diagnose, out_dir / "ledger_floor.jsonl", seed + 2)
    results["wapas"] = run_line("wapas", arms["wapas"], wapas, out_dir / "ledger_wapas.jsonl", seed + 3)
    results["rules_only"] = run_line("rules_only", arms["wapas"], _rules_only_diagnosis, out_dir / "ledger_rules_only.jsonl", seed + 4)
    truth = {p.event_id: c for p, c in arms["wapas"]}
    results["oracle"] = run_line("oracle", arms["wapas"], lambda ev: _oracle_diagnosis(truth[ev.event_id]),
                                 out_dir / "ledger_oracle.jsonl", seed + 5)

    c, f, w = results["control"], results["floor"], results["wapas"]
    stats = {
        "control_vs_floor": two_proportion_ztest(c["recovered"], c["n"], f["recovered"], f["n"]),
        "floor_vs_wapas": two_proportion_ztest(f["recovered"], f["n"], w["recovered"], w["n"]),
        "control_vs_wapas": two_proportion_ztest(c["recovered"], c["n"], w["recovered"], w["n"]),
        "power_floor_vs_wapas_at_observed_effect": approx_power(f["recovery_rate"], w["recovery_rate"], n_per_arm=min(f["n"], w["n"])),
    }
    ceiling_capture = w["recovery_rate"] / results["oracle"]["recovery_rate"] if results["oracle"]["recovery_rate"] else 0.0
    out = {"results": results, "stats": stats, "ceiling_capture_pct": round(ceiling_capture * 100, 1)}
    if live:
        # Honest provenance: how much of the wapas arm was actually decided
        # by the real LLM provider vs the documented offline fallbacks.
        mix: dict[str, int] = {}
        for row in w["rows"]:
            src = row.get("diagnosis_source") or "unknown"
            mix[src] = mix.get(src, 0) + 1
        out["wapas_diagnosis_source_mix"] = dict(sorted(mix.items(), key=lambda kv: -kv[1]))
    return out