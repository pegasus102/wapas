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
