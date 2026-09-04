#!/usr/bin/env python3
"""
scripts/live_demo.py
--------------------
Proves the AI slot is REAL: takes ambiguous at-risk events (the ones the
rules tier cannot resolve), gets a genuine LLM diagnosis for each via
OpenRouter, and prints it next to what the offline stand-in would have said.

Every real response is cached (cache/diagnosis_cache_live.json), so running
this twice costs zero extra API calls.

Usage:
    python3 scripts/live_demo.py --n 10
Set OPENROUTER_API_KEY (and optionally OPENROUTER_MODEL) in .env first.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wapas.data_foundry import generate_events
from wapas import rules_tier, llm_agent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=10, help="how many ambiguous cases to diagnose live")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    if not (llm_agent.os.environ.get("OPENROUTER_API_KEY") or llm_agent.os.environ.get("ANTHROPIC_API_KEY")):
        print("No API key found. Add OPENROUTER_API_KEY=... to .env (see .env.example).")
        sys.exit(1)

    model = llm_agent.os.environ.get("OPENROUTER_MODEL", llm_agent.OPENROUTER_DEFAULT_MODEL)
    print(f"Provider: OpenRouter · model: {model}")
    print(f"Live cache: {llm_agent.LIVE_CACHE_PATH.name} (real responses cached; reruns are free)\n")

    events = generate_events(4000, seed=args.seed)
    ambiguous = [(pk, tc) for pk, tc in events if rules_tier.diagnose(pk)["needs_llm"]]
    print(f"{len(ambiguous)} ambiguous events available; diagnosing {min(args.n, len(ambiguous))} live.\n")

    ok = fallback = 0
    for i, (pk, true_cause) in enumerate(ambiguous[: args.n], 1):
        hint = rules_tier.diagnose(pk)
        live = llm_agent.diagnose(pk, rules_hint=hint, live=True)
        standin = llm_agent._heuristic_diagnose(pk, hint)

        is_real = str(live.get("source", "")).startswith("llm_")
        ok += is_real
        fallback += not is_real

        agree = "AGREE" if live["root_cause"] == standin["root_cause"] else "DIFFER"
        print(f"[{i:2d}] {pk.event_id} · ₹{pk.amount:,.0f} · {pk.error_reason}"
              f" · free_text: {(pk.free_text or '-')[:48]!r}")
        print(f"     rules hint : {hint['root_cause']} ({hint['confidence']:.2f})")
        print(f"     stand-in   : {standin['root_cause']} ({standin['confidence']:.2f})")
        print(f"     real LLM   : {live['root_cause']} ({live['confidence']:.2f}) "
              f"-> {live['action']}  [{agree}; source={live.get('source')}]")
        print(f"     draft      : {live.get('draft_message') or standin.get('draft_message','')}")
        print(f"     (ground truth hidden from all three: not revealed)")
        print()

    print(f"Done: {ok} real LLM responses, {fallback} fallbacks (rate limit/no key).")
    print("The live cache is committed, so `make batch` judges still need no key —")
    print("and a future official --live re-run reuses these responses for free.")


if __name__ == "__main__":
    main()
