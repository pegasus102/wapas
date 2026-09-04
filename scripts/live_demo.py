#!/usr/bin/env python3
"""
scripts/live_demo.py
--------------------
Proves the AI slot is REAL: takes ambiguous at-risk events (the ones the
rules tier cannot resolve), gets a genuine LLM diagnosis for each via
OpenRouter, and prints it next to what the offline stand-in would have said.

Honesty guarantees:
  * A case is counted "real" ONLY if its source is an actual provider
    (llm_openrouter:... / llm_live). The stand-in ("llm_heuristic") is
    labelled FALLBACK, never "real".
  * Every fallback shows WHY (HTTP status / exception) — silent failure
    masquerading as AI is the one bug this script must never have.

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

        is_real = llm_agent.is_real_provider(live.get("source", ""))
        ok += is_real
        fallback += not is_real

        label = "real LLM" if is_real else "FALLBACK!"
        print(f"[{i:2d}] {pk.event_id} · ₹{pk.amount:,.0f} · {pk.error_reason}"
              f" · free_text: {(pk.free_text or '-')[:48]!r}")
        print(f"     rules hint : {hint['root_cause']} ({hint['confidence']:.2f})")
        print(f"     stand-in   : {standin['root_cause']} ({standin['confidence']:.2f})")
        print(f"     {label:<10s}: {live['root_cause']} ({live['confidence']:.2f}) "
              f"-> {live['action']}  [source={live.get('source')}]")
        if is_real:
            agree = "AGREE" if live["root_cause"] == standin["root_cause"] else "DIFFER"
            print(f"     vs stand-in: {agree}")
            print(f"     draft      : {live.get('draft_message') or standin.get('draft_message','')}")
        else:
            reason = llm_agent.LAST_LIVE_ERROR or "(unknown — no key? provider unreachable?)"
            print(f"     why        : {reason}")
        print(f"     (ground truth hidden from all three: not revealed)")
        print()

    print(f"Done: {ok} REAL LLM responses, {fallback} fallbacks.")
    if ok == 0:
        print()
        print("!!  NONE of these came from a real model — the stand-in answered instead.")
        print("    This is a configuration problem, not a code problem. Check:")
        print()
        print("    1) Is the key valid?  (output shows key status, never the key itself)")
        print("       curl -s https://openrouter.ai/api/v1/auth/key -H \"Authorization: Bearer PASTE_YOUR_KEY\"")
        print()
        print("    2) Does the model still exist?  Free catalogs churn — gems disappear.")
        print("       curl -s https://openrouter.ai/api/v1/models | python3 -c 'import sys,json; [print(m[\"id\"]) for m in json.load(sys.stdin)[\"data\"] if m[\"id\"].endswith(\":free\")]'", "| head -20", sep="")
        print()
        print("    3) Put a live model id from that list into .env as OPENROUTER_MODEL=... and rerun.")
        sys.exit(2)

    print(f"\nReal responses saved to {llm_agent.LIVE_CACHE_PATH.name} — commit it so a future")
    print("official --live run (and the judges) need no key.")


if __name__ == "__main__":
    main()
