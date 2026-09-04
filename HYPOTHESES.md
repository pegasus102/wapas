# HYPOTHESES.md — pre-registered before the official results run

Tag this file (`git tag prereg-v1`) and push it **before** running the
official `make batch` whose numbers go into the README. If you ever change
a response-model parameter after that tag, that's a documented,
after-the-fact change, not silent tuning — write it down here and re-tag.

## Confirmatory (the pre-registered claims)

1. **H1 — Floor vs Control:** Razorpay's own published generic recovery
   playbook (Arm B) recovers more than doing nothing (Arm A).
2. **H2 — WAPAS vs Floor:** diagnosis-first recovery (Arm C) recovers
   strictly more than the generic playbook, at identical contact caps
   (contact parity) — this is the thesis the whole project exists to test.
3. **H3 — Rules-only vs WAPAS:** adding the diagnosis-agent tier (rules +
   LLM on the ambiguous ~24% of events) recovers more than rules alone.
4. **H4 — Ceiling capture:** WAPAS's recovery rate, as a fraction of the
   analytic oracle ceiling (perfect diagnosis under the same gate),
   exceeds 85%.

Test: two-proportion z-test, Wilson 95% CI, α = 0.05 two-sided, on the
aggregate recovery-rate comparison only.

## Exploratory (reported, not confirmatory — labelled ⚠️ in the README)

- Segment-level uplift by (root_cause × geo_tier × value_band): smaller
  per-cell n, directional only.
- Time-to-recovery by arm.
- Complaint/goodwill rate by (root_cause, action) pair.

## What would falsify the thesis

- H2 fails (Floor ≥ WAPAS): diagnosis doesn't help once a merchant already
  has a competent generic playbook — the whole premise is wrong.
- H3 fails (Rules-only ≥ WAPAS): the LLM tier adds cost without adding
  recovery — cut it, ship rules-only.
- Ceiling capture is low (<70%): diagnosis quality, not the gate or
  execution layer, is the bottleneck — the next 3 months of work should go
  into a better diagnosis model, not more guardrails.

## Known simulator assumptions (see RESPONSE_MODEL.md)

`MATCHED_ACTION_MULTIPLIER`, `MISMATCHED_ACTION_MULTIPLIER`,
`CONTACT_FATIGUE_DECAY`, and `BASE_ORGANIC_RECOVERY` are documented
assumptions, not measurements. `make sensitivity` (not yet built — see
roadmap) is meant to sweep these and report the break-even point.

---

# AMENDMENT v2 — documented, after-the-fact (re-tag as `prereg-v2`)

This amendment exists because the v1 run FALSIFIED our own framing, and we
are writing down what we found and changed rather than quietly tuning.

## What happened (the bug the experiment caught)

The v1 response model scored recovery by coarse *intent coverage*: any
action whose intent set contained the cause's ideal intent got full credit.
The gate's authority ladder honestly converts every blanket retry into a
customer-approved `method_fallback` link (a pull with no mandate cannot
execute — consent first). That link's intent set `{now, alt_method}` covered
the ideal intent of **9 of 12 causes**, so the generic floor's single
undifferentiated action scored full targeted credit almost everywhere.
Result: Floor == Rules-only == WAPAS == Oracle (p=0.997 for Floor vs WAPAS).
The experiment machine worked exactly as designed — and correctly told us
our causal model couldn't discriminate diagnosis from blindness.

## What changed (all documented assumptions, same interface)

1. **`response_model.py` v2 — cure matrix replaces intent coverage.**
   Recovery now depends on the executed *profile* (pull vs link × now vs
   delayed × same-credential vs customer-entered details) per cause, via
   `CURE_MATRIX` (every cell commented with its domain rationale), plus a
   targeting `fit` factor (1.0 for the policy action or its honest
   consent-downgrade; 0.85 for a blind action that merely lands on the same
   profile; 0.92 for a near-miss within the link family). The floor is NOT
   strawmanned: its method-fallback link remains the genuinely ideal action
   for the four customer-fixable causes.
2. **Complaint cost.** `net_inr` now subtracts ₹150 per complaint (expected
   churn/support cost — conservative vs dunning benchmarks).
3. **n raised 1,500 → 12,000** (4,000/arm). The honest effect of diagnosis
   under v2 is ~3pp; the README's own honesty note called for a
   better-powered official run. In a simulator, n is a design parameter and
   compute is free; the thing under test is the causal model, not sampling
   luck.
4. Diagnosis accuracy expectation corrected: the v1 claim of "97.3%" came
   from the same run family as the collapsed causal model; the corrected,
   honest figure at the larger eval split is ~82%.

## v2 confirmatory expectations (pre-registered before the official run)

- H2′: WAPAS − Floor ≥ +2.0pp aggregate recovery rate, p < 0.05.
- Staircase: Control < Floor < Rules-only ≤ WAPAS ≤ Oracle (strict except
  Rules/WAPAS may tie within noise).
- Floor complaints > WAPAS complaints; Floor net ₹ < WAPAS net ₹.
- Ceiling capture ≥ 90%.

## What would still falsify the thesis (unchanged in spirit)

If H2′ fails at adequate power, the honest conclusion is "a competent
generic playbook is enough for this merchant mix, and a diagnosis layer is
not justified on recovery-rate grounds" — that would go in the README
verbatim.