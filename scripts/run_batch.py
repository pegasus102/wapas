#!/usr/bin/env python3
"""
scripts/run_batch.py
---------------------
The single entry point that reproduces every number in the README.
`make batch` runs this. It is deterministic: same code + same seed +
same committed cache => byte-identical output, every time (see
scripts/verify_readme.py, the CI results-verify check).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wapas.data_foundry import generate_events, train_eval_split
from wapas.measurement import run_experiment
from wapas.eval_diagnosis import evaluate

N_EVENTS = 12000         # synthetic budget: n is a design parameter in a
                         # simulator, and the honest effect of diagnosis is
                         # ~3pp — 4,000/arm gives ~80%+ power for it (see
                         # HYPOTHESES.md amendment v2; runtime still <1 min)
GEN_SEED = 42
EXPERIMENT_SEED = 2026


def render_table(result: dict) -> str:
    lines = []
    lines.append("| Line | n | Recovered | Recovery rate | 95% CI | ₹ recovered | Complaints |")
    lines.append("|---|---|---|---|---|---|---|")
    order = ["control", "floor", "rules_only", "wapas", "oracle"]
    labels = {
        "control": "Control (no action)",
        "floor": "Floor (Razorpay's own playbook)",
        "rules_only": "Rules-only (no LLM)",
        "wapas": "WAPAS (rules + LLM on ambiguous)",
        "oracle": "Oracle (ceiling, perfect diagnosis)",
    }
    for key in order:
        r = result["results"][key]
        lo, hi = r["ci_95"]
        lines.append(
            f"| {labels[key]} | {r['n']} | {r['recovered']} | {r['recovery_rate']:.1%} "
            f"| [{lo:.1%}, {hi:.1%}] | ₹{r['recovered_amount']:,.0f} | {r['complaints']} |"
        )
    lines.append("")
    stats = result["stats"]
    lines.append(f"- Control vs WAPAS: z={stats['control_vs_wapas']['z']:.2f}, p={stats['control_vs_wapas']['p_value']:.4f}")
    lines.append(f"- Floor vs WAPAS:   z={stats['floor_vs_wapas']['z']:.2f}, p={stats['floor_vs_wapas']['p_value']:.4f}")
    lines.append(f"- WAPAS captures **{result['ceiling_capture_pct']}%** of the theoretical oracle ceiling.")
    lines.append(f"- Approx. power (Floor vs WAPAS, observed effect, per-arm n): {stats['power_floor_vs_wapas_at_observed_effect']:.2f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=N_EVENTS)
    parser.add_argument("--live", action="store_true",
                        help="let the diagnosis agent make REAL LLM calls via OpenRouter "
                             "(OPENROUTER_API_KEY in .env) on ambiguous events; responses "
                             "are cached so this only costs API calls once")
    parser.add_argument("--out", type=str, default="out")
    args = parser.parse_args()

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    all_events = generate_events(args.n, seed=GEN_SEED)
    train_events, eval_events = train_eval_split(all_events)

    print(f"Generated {len(all_events)} at-risk events "
          f"({len(train_events)} train / {len(eval_events)} held-out eval).")

    print("\nRunning 3-arm experiment + oracle + rules-only lines...")
    result = run_experiment(train_events, out_dir, seed=EXPERIMENT_SEED, live=args.live)
    if args.live:
        mix = result.get("wapas_diagnosis_source_mix", {})
        total = sum(mix.values()) or 1
        print("\nDiagnosis provenance (wapas arm):")
        for src, n in mix.items():
            print(f"  {src:40s} {n:5d}  ({n / total:.1%})")

    table = render_table(result)
    print("\n" + table)

    print("\nEvaluating diagnosis accuracy on the held-out split...")
    eval_result = evaluate(eval_events)
    print(f"Diagnosis accuracy: {eval_result['accuracy']:.1%}  "
          f"(avg confusion cost: {eval_result['avg_confusion_cost']:.3f})")

    (out_dir / "RESULTS.md").write_text(table + "\n")
    (out_dir / "results.json").write_text(json.dumps(
        {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in result["results"].items()},
        indent=2, default=str,
    ))
    (out_dir / "eval.json").write_text(json.dumps(eval_result, indent=2, default=str))
    print(f"\nWrote {out_dir / 'RESULTS.md'}, {out_dir / 'results.json'}, {out_dir / 'eval.json'}")


if __name__ == "__main__":
    main()