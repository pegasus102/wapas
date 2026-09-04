"""
wapas.stats_utils
------------------
Pure-Python implementations (no scipy/numpy) of:
  - Wilson 95% confidence interval for a single proportion
  - Two-proportion z-test (returns z, two-sided p-value)
  - A crude but honest power estimate for a two-proportion comparison

Using stdlib `math.erf` for the normal CDF keeps the whole project
dependency-free, which is itself part of the "boring tech on purpose"
argument in ADR/why-no-heavy-deps.
"""

from __future__ import annotations
import math

Z_95 = 1.959963985


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def wilson_ci(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z ** 2 / n
    center = p + z ** 2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    return (max(0.0, lo), min(1.0, hi))


def two_proportion_ztest(successes_a: int, n_a: int, successes_b: int, n_b: int) -> dict:
    """H0: p_a == p_b. Returns z, two-sided p-value, and the pooled proportion."""
    if n_a == 0 or n_b == 0:
        return {"z": 0.0, "p_value": 1.0, "p_pool": 0.0}
    p_a = successes_a / n_a
    p_b = successes_b / n_b
    p_pool = (successes_a + successes_b) / (n_a + n_b)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return {"z": 0.0, "p_value": 1.0, "p_pool": p_pool}
    z = (p_b - p_a) / se
    p_value = 2 * (1 - _norm_cdf(abs(z)))
    return {"z": z, "p_value": p_value, "p_pool": p_pool}


def approx_power(p1: float, p2: float, n_per_arm: int, alpha: float = 0.05) -> float:
    """Approximate power for a two-proportion test with equal arm sizes.
    Standard normal-approximation power formula — good enough for an
    honest one-line README statement, not a substitute for a real stats
    package in production."""
    p_bar = (p1 + p2) / 2
    se0 = math.sqrt(2 * p_bar * (1 - p_bar) / n_per_arm)
    se1 = math.sqrt(p1 * (1 - p1) / n_per_arm + p2 * (1 - p2) / n_per_arm)
    z_alpha = Z_95 / math.sqrt(2) * math.sqrt(2)  # z for two-sided alpha=0.05 -> 1.96
    z_alpha = 1.959963985
    if se1 == 0:
        return 1.0
    z_beta = (abs(p2 - p1) - z_alpha * se0) / se1
    return _norm_cdf(z_beta)
