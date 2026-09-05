| Line | n | Recovered | Recovery rate | 95% CI | ₹ recovered | Complaints |
|---|---|---|---|---|---|---|
| Control (no action) | 3203 | 439 | 13.7% | [12.6%, 14.9%] | ₹1,261,981 | 0 |
| Floor (Razorpay's own playbook) | 3203 | 754 | 23.5% | [22.1%, 25.0%] | ₹2,339,150 | 77 |
| Rules-only (no LLM) | 3194 | 886 | 27.7% | [26.2%, 29.3%] | ₹2,777,199 | 80 |
| WAPAS (rules + LLM on ambiguous) | 3194 | 888 | 27.8% | [26.3%, 29.4%] | ₹2,783,613 | 80 |
| Oracle (ceiling, perfect diagnosis) | 3194 | 900 | 28.2% | [26.6%, 29.8%] | ₹2,823,458 | 77 |

- Control vs WAPAS: z=13.90, p=0.0000
- Floor vs WAPAS:   z=3.90, p=0.0001
- WAPAS captures **98.7%** of the theoretical oracle ceiling.
- Approx. power (Floor vs WAPAS, observed effect, per-arm n): 0.97
