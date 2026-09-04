# WAPAS — AI Revenue Recovery (Razorpay Buildathon, Track 03)

वापस (wapas) = "back." Diagnoses **why** a payment/subscription/checkout
event is at risk before acting, executes the cheapest bounded recovery
behind a 100%-deterministic policy gate, and proves — Control vs Floor
(Razorpay's own published playbook) vs Rules-only vs WAPAS vs Oracle
ceiling — that diagnosis-first wins.

## 60-second judge path

```bash
git clone <this repo> && cd wapas
make all
```

That's it — no API key, no external services, no database server. `make
all` runs the test suite, regenerates the full experiment from the
committed cache, verifies every ledger's hash chain, and confirms the
results are byte-for-byte reproducible. Read `out/RESULTS.md` for the
headline table.

## What you're looking at

```
wapas/
├── wapas/                  the engine (stdlib only — no pip install required to run it)
│   ├── schema.py            hidden causes, fixed action menu, oracle map, cost-weighted confusion
│   ├── data_foundry.py      seeded generator, deliberate ~24%-ambiguous evidence
│   ├── response_model.py    P(recover | cause, action, contacts) — every knob documented
│   ├── detector.py          deterministic feature annotation, no LLM
│   ├── rules_tier.py        resolves the unambiguous majority for free
│   ├── llm_agent.py         cached / offline-heuristic / --live diagnosis on the ambiguous rest
│   ├── diagnosis.py         orchestrator: rules -> LLM -> disagreement-routes-to-human
│   ├── policy_gate.py       authority, static safety, adaptive circuit breaker, idempotency
│   ├── baselines.py         Arm B: Razorpay's own generic playbook, same gate, same caps
│   ├── executor.py          turns an approved decision into a simulated outcome
│   ├── ledger.py            hash-chained audit log + tamper verification
│   ├── measurement.py       runs all 3 randomized arms + 2 analytic lines + stats
│   ├── stratify.py          balanced random assignment to arms
│   ├── stats_utils.py       two-proportion z-test, Wilson CI, power (pure stdlib)
│   └── eval_diagnosis.py    held-out accuracy, cost-weighted confusion, calibration
├── scripts/
│   ├── run_batch.py         the one command that produces every number below
│   ├── verify_ledger.py     `make verify` — the live tamper demo
│   └── verify_readme.py     `make verify-results` — regenerate & diff against committed numbers
├── tests/                   16 tests: gate safety rules, ledger tamper detection, stats sanity
├── cache/diagnosis_cache.json   committed LLM responses — offline-first, forever
└── HYPOTHESES.md            pre-registered claims (tag this before your official run)
```

## Setup

**Requirements:** Python 3.10+. Nothing else — the core engine (data
generation, diagnosis, gate, executor, ledger, measurement, eval) uses
only the standard library on purpose (see "why no heavy deps" below), so
`make all` cannot fail because of a broken `pip install` on a judge's
machine.

```bash
# 1. clone
git clone <this repo> && cd wapas

# 2. (optional) dev environment for running tests explicitly
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. run everything
make all
```

Individual targets:

| Command | What it does |
|---|---|
| `make test` | runs the test suite (74 tests: engine, ledger, dashboard contract, live-LLM tier) |
| `make batch` | regenerates data + runs the 3-arm experiment + writes `out/RESULTS.md` |
| `make verify` | recomputes every ledger's hash chain, reports tamper if any |
| `make verify-results` | regenerates results from scratch and diffs against the committed copy |
| `make clean` | wipes generated `out/` only — never the committed diagnosis cache |
| `make live-demo` | diagnoses ambiguous cases with a REAL LLM (needs `OPENROUTER_API_KEY` in `.env`) |
| `make live-batch` | full experiment with real LLM diagnoses (needs key; fallbacks stay honest) |

### Optional: `--live` mode (real LLM calls)

By default, the diagnosis agent replays from `cache/diagnosis_cache.json`
or falls back to a deterministic, feature-based heuristic — it never needs
an API key. To let it call the real Claude API on ambiguous events
instead:

```bash
cp .env.example .env      # then fill in ANTHROPIC_API_KEY
pip install anthropic --break-system-packages
export ANTHROPIC_API_KEY=sk-...
python3 scripts/run_batch.py --live
```

Every response gets cached, so the second run onward is offline again
regardless of the flag.

## Dashboard (optional UI layer)

The engine is a CLI/experiment system; the dashboard is a read-only command
center over its artifacts — plus two SAFE live labs (the tamper lab forges a
record on a temp copy; the kill-switch lab runs a 40-event in-memory
simulation through the real gate and pulls the switch mid-flight):

```bash
pip install streamlit --break-system-packages   # the only extra dependency
make dash                                        # → http://localhost:8501
```

- **Mission Control** — the staircase chart, stats (p-values, power, ceiling
  capture), diagnosis accuracy, per-arm net ₹ and complaint counts. Recomputed
  from `out/` on every load; if someone edits `RESULTS.md`, CI fails — the
  dashboard doesn't trust the markdown either, it recomputes.
- **Case Files** — browse any ledger arm, filter by outcome/cause, open one
  payment end-to-end: AI diagnosis → gate decision → plain-English trace →
  consent level → outcome. The `gate_trace` is written to be read.
- **Tamper Lab** — forge `recovered` on a temp copy of the chain, watch
  verification scream `CHAIN BROKEN at entry #N`.
- **Kill-Switch Lab** — real Gate, real diagnosis, mid-flight halt: scheduled
  actions cancelled, everything after refused with a written reason.

Nothing in the dashboard mutates `out/` — it's the projector, not the engine.

## Results (regenerate with `make batch`; numbers below are one real run, n=12,000)

| Line | n | Recovered | Recovery rate | 95% CI | ₹ recovered | Complaints |
|---|---|---|---|---|---|---|
| Control (no action) | 3,203 | 439 | 13.7% | [12.6%, 14.9%] | ₹12,61,981 | 0 |
| Floor (Razorpay's own playbook) | 3,203 | 754 | 23.5% | [22.1%, 25.0%] | ₹23,39,150 | 77 |
| Rules-only (no LLM) | 3,194 | 886 | 27.7% | [26.2%, 29.3%] | ₹27,77,199 | 80 |
| **WAPAS** (rules + LLM on ambiguous) | 3,194 | 888 | **27.8%** | [26.3%, 29.4%] | **₹27,83,613** | 80 |
| Oracle (ceiling, perfect diagnosis) | 3,194 | 900 | 28.2% | [26.6%, 29.8%] | ₹28,23,458 | 77 |

- Control vs WAPAS: z=13.90, **p<0.0001** — recovery beats doing nothing, decisively
- Floor vs WAPAS: z=3.90, **p=0.0001**, power 0.97 — diagnosis-first beats Razorpay's own published generic playbook at identical contact caps, by **+4.3pp absolute (+18% relative)**
- WAPAS captures **98.7%** of the theoretical oracle ceiling; the un-captured gap is a *diagnosis-accuracy* problem, not a gate/execution problem
- The uplift concentrates exactly where the thesis predicts (⚠️ exploratory, per-cause): insufficient_funds **+10.2pp**, expired_mandate **+14.3pp**, bank_outage **+6.4pp** — the timing-bound and mandate-bound causes — and ≈0 where a generic method-fallback link is genuinely the right action anyway (wrong_vpa, card_expired, auth_3ds)
- Net ₹ (after action costs + ₹150/complaint churn cost): WAPAS ₹27.8L vs Floor ₹23.4L — **+₹4.4L per ~3,200 at-risk events**
- Diagnosis accuracy on the 2,400-event held-out split: **81.5%** (avg confusion cost 0.236 — see `out/eval.json`)
- ~20% of events are ambiguous enough to need the LLM tier; the other ~80% resolve for free via deterministic rules

**Honest readings of this run (we pre-registered these checks in
HYPOTHESES.md amendment v2 and report the misses too):**

1. *Rules ≈ WAPAS on recovery rate* (+0.1pp, within noise). The LLM's
   measurable recovery contribution on this merchant mix is small. Its
   defensible value: reading free text in the ambiguous ~20%, robustness to
   reason-code drift, and the natural-language audit explainer — not raw
   recovery rate. Rules-first routing is what keeps it cheap.
2. *Complaint asymmetry did not materialize* (Floor 77 vs WAPAS 80). The
   contact-cap gate protects both arms equally; we do NOT claim a
   goodwill advantage from this experiment.
3. The v1 response model scored recovery by coarse intent coverage and
   collapsed the whole staircase (Floor == Oracle, p=0.997). The
   pre-registered experiment caught it; `response_model.py` v2 (cure
   matrix, documented per cell in HYPOTHESES.md amendment v2) replaced it,
   and `tests/test_thesis_guard.py` now fails the suite if the staircase
   ever collapses again.

## Where AI is and isn't used

The diagnosis agent (rules tier + LLM) is the **only** place any AI
judgment happens, and it never touches money. Its output is a proposal;
`policy_gate.py` is 100% deterministic and can override or reject it
outright — e.g. `debit_confirmation_flag` and `RISK_BLOCKED` hard-block
any retry-shaped action **no matter what the diagnosis said**, and this is
tested (`tests/test_policy_gate.py`).

## Guardrails implemented

- **Consent ladder / authority field** — every ledger entry records L1
  (live customer approval) / L2 (standing mandate) / L3 (human) / blocked.
- **Contact cap** — 2 contacts / customer / 7 days, enforced by the gate.
- **Quiet hours** — 21:00–09:00 IST, per TRAI's TCCCPR restrictions on
  unsolicited commercial communication.
- **Confidence threshold** — anything below 0.55 routes to a human instead
  of acting.
- **Idempotency** — keyed on (customer, invoice, attempt), unique per gate
  instance; replaying the same action is structurally a no-op (tested).
- **Adaptive circuit breaker** — if the rolling complaint rate for a
  (root_cause, action) pair crosses 30% over a minimum volume, that pair
  auto-suspends (fail-closed; re-enable is human-only).
- **Hash-chained ledger** — `make verify` recomputes the chain; editing
  any row is detectable and localized to the exact entry.

## Honest limits

- ₹ figures are **simulated** — from a documented response model
  (`wapas/response_model.py`), not real transactions. Production path:
  shadow mode against real data first, then a live A/B.
- The response model's parameters (`MATCHED_ACTION_MULTIPLIER` etc.) are
  assumptions, not measurements — see `HYPOTHESES.md`.
- No real customer data anywhere in this repo.
- `--live` mode exists but is not required or exercised by `make all`.

## Roadmap (not built — cut deliberately for time, listed honestly)

- `make sensitivity`: sweep the response-model assumptions and report the
  break-even point where WAPAS stops beating Floor.
- Real Razorpay **test-mode** executor backend (Orders / Payment Links /
  Refunds) for a live-money-link demo on camera.
- Streamlit dashboard (live ₹ counter, case-file timeline, chaos toggle,
  kill switch).
- Read-only natural-language explainer over the ledger.
- CI workflow wiring `make all` into GitHub Actions on every push.