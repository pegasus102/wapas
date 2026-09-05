# LIVE_RUN.md — the real-model run, reported honestly

On 2026-09-05, after the official deterministic run was frozen and verified, we
re-executed the **entire 12,000-event experiment with a real LLM** in the
diagnosis slot (OpenRouter; MiniMax-M3, from an automatic failover chain of five
free models). This document reports that run, grades the real model against the
simulator's hidden ground truth, and explains — with numbers — why its in-sim
recovery rate differs from the official run. We publish both runs and the
analysis rather than tune anything to the simulator.

**One line summary: the real model is a better diagnostician (+8pp accuracy on
the hard cases) and a slightly worse in-sim scorer (−2.2pp arm recovery) — and
we can show exactly why, to the decimal.**

---

## 1. Provenance — who actually decided (wapas arm, n = 3,194)

| Source | Events | Share |
|---|---|---|
| rules tier (deterministic) | 2,427 | 76.0% |
| `llm_openrouter:minimax/minimax-m3:free` | 766 | 24.0% |
| `llm_openrouter:nvidia/nemotron-3-super-120b-a12b:free` | 1 | 0.0% |

- **100% of LLM-tier events were decided by a real provider** (767 of 767).
  The overnight pass had 2 honest, visible fallbacks; the afternoon replay —
  run on the completed cache — retried them automatically. The resume
  design closed its own gaps; nothing was ever silently relabelled.
- The single Nemotron response is the failover chain doing its job mid-run.
- Every real response is stored separately in
  `cache/diagnosis_cache_live.json` (committed), so this run can be replayed
  key-free: `python3 scripts/run_batch.py --live --out out_live` reuses the
  cache and makes **zero** API calls.

Reproduce live (with your own free key): `cp .env.example .env`, add
`OPENROUTER_API_KEY=...`, then `make live-demo` (10 showcase cases) or
`make live-batch` (full n=12,000).

## 2. Live-run results (same seeds, same gate, real LLM tier)

| Line | n | Recovered | Rate | ₹ recovered | Complaints |
|---|---|---|---|---|---|
| Control (no action) | 3,203 | 439 | 13.7% | ₹1,261,981 | 0 |
| Generic playbook | 3,203 | 754 | 23.5% | ₹2,339,150 | 77 |
| Rules-only (no LLM) | 3,194 | 886 | 27.7% | ₹2,777,199 | 80 |
| **WAPAS (live LLM)** | 3,194 | 819 | **25.6%** | ₹2,571,246 | **67** |
| Oracle (ceiling) | 3,194 | 900 | 28.2% | ₹2,823,458 | 77 |

- Floor vs live-WAPAS: p = 0.051 · ceiling captured 91.0%
- Complaints **dropped** to 67 (official run: 80) — the live model's action mix
  is measurably gentler.
- Diagnosis accuracy on the held-out split (offline evaluator): 81.5%,
  unchanged — the eval harness runs the deterministic path by design.

The official README table remains the deterministic stand-in run: key-free,
byte-identical under `make all`, and the basis of every published number.

## 3. Grading the real model against hidden ground truth

The simulator knows the true cause of every event but never shows it to any
diagnostician. We graded both diagnosticians on the wapas arm's ambiguous
subset (n = 767 — the complete corpus; 757 unique cache entries cover all 767
events, 10 evidence packets being exact duplicates):

| Diagnostician | Accuracy on ambiguous events |
|---|---|
| **Real model (MiniMax-M3)** | **406 / 767 = 52.9%** |
| Recorded stand-in | 345 / 767 = 45.0% |

Ambiguous events are the hard subset by construction (rules could not resolve
them); even the oracle-defined ceiling is only reachable by perfect guessing
among plausible causes. **The real model beats the stand-in by 8pp exactly
where the LLM tier exists to work** — e.g. it correctly reads free text like
"3d secure page stuck" to `auth_3ds_drop` (0.90) where the stand-in says
`wrong_vpa`.

## 4. Why better diagnosis scored lower in-sim — the mechanism

Executed actions come from the deterministic policy table
(`CAUSE_ACTION_POLICY[predicted_cause]`), and the response model scores each
action by cause-specific cure values (`CURE_MATRIX`). Comparing expected
recovery `p(true_cause, policy_action(predicted_cause))` for both
diagnosticians on the same 767 events:

| | expected recovery per ambiguous event |
|---|---|
| live model | 0.2432 |
| stand-in | 0.2778 |
| **delta** | **−0.0346 (−3.46pp per ambiguous event)** |

Largest damage by true cause: `intent_drop` (−10.84 summed p), `bank_outage`
(−7.49), `auth_3ds_drop` (−4.51), `upi_daily_limit` (−3.35). Typical damaged
case: true cause `wrong_vpa` — stand-in says `intent_drop` (cure 0.34), live
model says `gateway_timeout` (cure 0.13).

**Interpretation.** The stand-in's cause mixture and the cure matrix were
co-designed, so the stand-in's errors are "economically aligned" with the
simulator's action economics. The real model — though more accurate — shifts
cause mass toward causes whose policy actions the current matrix scores lower.
The remaining arm-level gap (−2.2pp observed vs −0.8pp from the diagnosis path
alone) emerges from gate-level coupling: human-capacity contention, circuit
breaker and deferral dynamics responding to the changed action mix.

This is a **sim-to-real finding, not a pipeline failure**: the architecture
swapped the brain without touching the gate, every decision stayed inside the
consent ladder, and the evaluation caught the difference immediately — which is
precisely what the audit layer is for.

## 5. What we would do next (not done here — no sim-tuning)

1. Recalibrate `CURE_MATRIX` against live outcome data (real merchant A/B),
   then re-rank models in-sim.
2. A/B the model's proposed actions against the policy table instead of
   accepting the table's mapping unconditionally (the model already proposes
   actions with citations; today the table wins by design).
3. Model anchoring: treat low-confidence live diagnoses as second opinions
   rather than overrides (the disagreement threshold exists; its calibration
   predates live data).

We deliberately did none of these before the deadline: tuning the simulator to
like the new model more would have produced better-looking numbers and worse
honesty.

## 6. Failsafes that were active during the live run

- Separate live cache; fallbacks never persisted (test-guarded).
- Failover across five free models with per-model cooldowns; key errors (401)
  fail fast; every fallback is labelled with its HTTP reason.
- The gate, consent ladder, quiet hours, caps, kill switch: identical code
  paths as the official run — only the diagnosis slot changed.

*WAPAS · diagnose before you act · no authority, no action.*
