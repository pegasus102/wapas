from pathlib import Path
from wapas.data_foundry import generate_events
from wapas.measurement import run_experiment
from wapas.stats_utils import wilson_ci, two_proportion_ztest


def test_oracle_is_never_worse_than_wapas_or_rules_only(tmp_path):
    events = generate_events(1500, seed=42)
    result = run_experiment(events, tmp_path, seed=2026)
    oracle = result["results"]["oracle"]["recovery_rate"]
    wapas = result["results"]["wapas"]["recovery_rate"]
    rules_only = result["results"]["rules_only"]["recovery_rate"]
    assert oracle >= wapas - 1e-9
    assert oracle >= rules_only - 1e-9


def test_run_is_deterministic_given_same_seed(tmp_path):
    events_a = generate_events(300, seed=1)
    events_b = generate_events(300, seed=1)
    r_a = run_experiment(events_a, tmp_path / "a", seed=5)
    r_b = run_experiment(events_b, tmp_path / "b", seed=5)
    assert r_a["results"]["wapas"]["recovered"] == r_b["results"]["wapas"]["recovered"]
    assert r_a["results"]["oracle"]["recovered"] == r_b["results"]["oracle"]["recovered"]


def test_reproducibility_is_the_ci_results_verify_invariant(tmp_path):
    """This IS the check `scripts/verify_readme.sh` relies on: same seed,
    same cache -> byte-identical numbers, every time."""
    events = generate_events(500, seed=42)
    r1 = run_experiment(events, tmp_path / "run1", seed=2026)
    r2 = run_experiment(events, tmp_path / "run2", seed=2026)
    assert r1["results"]["wapas"]["recovered_amount"] == r2["results"]["wapas"]["recovered_amount"]


def test_wilson_ci_contains_point_estimate():
    lo, hi = wilson_ci(80, 500)
    assert lo < 80 / 500 < hi


def test_ztest_no_difference_gives_high_p_value():
    result = two_proportion_ztest(100, 500, 100, 500)
    assert result["p_value"] > 0.9


def test_ztest_large_difference_gives_low_p_value():
    result = two_proportion_ztest(50, 500, 150, 500)
    assert result["p_value"] < 0.01
