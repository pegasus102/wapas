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
| `make test` | runs the 16-test suite |
| `make batch` | regenerates data + runs the 3-arm experiment + writes `out/RESULTS.md` |
| `make verify` | recomputes every ledger's hash chain, reports tamper if any |
| `make verify-results` | regenerates results from scratch and diffs against the committed copy |
| `make clean` | wipes generated output and the diagnosis cache |

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

## Results (regenerate with `make batch`; numbers below are one real run)

| Line | n | Recovered | Recovery rate | 95% CI | ₹ recovered | Complaints |
|---|---|---|---|---|---|---|
| Control (no action) | 397 | 40 | 10.1% | [7.5%, 13.4%] | ₹270,328 | 8 |
| Floor (Razorpay's own playbook) | 398 | 51 | 12.8% | [9.9%, 16.5%] | ₹320,649 | 6 |
| Rules-only (no LLM) | 405 | 80 | 19.8% | [16.2%, 23.9%] | ₹538,040 | 15 |
| **WAPAS** (rules + LLM on ambiguous) | 405 | 83 | **20.5%** | [16.9%, 24.7%] | ₹554,679 | 15 |
| Oracle (ceiling, perfect diagnosis) | 405 | 84 | 20.7% | [17.1%, 25.0%] | ₹560,724 | 15 |

- Control vs WAPAS: z=4.09, **p<0.0001**
- Floor vs WAPAS: z=2.92, **p=0.0035** — diagnosis beats Razorpay's own generic playbook at identical contact caps
- WAPAS captures **98.8%** of the theoretical oracle ceiling
- Diagnosis accuracy on the held-out eval split: **97.3%** (cost-weighted confusion: 0.043 — see `out/eval.json`)
- ~24% of events are ambiguous enough to need the LLM tier; the other ~76% resolve for free via deterministic rules

**Honesty note:** at n≈400/arm the Floor-vs-WAPAS gap is real but its
significance is sensitive to the exact seed and n — see
`tests/test_measurement.py` and `HYPOTHESES.md` for what's confirmatory
vs exploratory, and increase `--n` for a better-powered official run.

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
