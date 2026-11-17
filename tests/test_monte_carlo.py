"""Tests for the full-chain Monte-Carlo uncertainty propagation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from cnt_tid.monte_carlo import (
    ASSUMPTION_RANGES,
    SUMMARY_KEYS,
    plot_monte_carlo,
    run_monte_carlo,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "parameters" / "tid_parameters.csv"
METRICS = ROOT / "data" / "literature" / "cui2023_topgate" / "fig3_metrics_digitized.csv"


def test_monte_carlo_is_deterministic_under_a_fixed_seed(tmp_path: Path):
    first = run_monte_carlo(REGISTRY, METRICS, draws=3, seed=7, output_dir=tmp_path / "a")
    second = run_monte_carlo(REGISTRY, METRICS, draws=3, seed=7, output_dir=tmp_path / "b")
    assert first.draws.equals(second.draws)
    assert first.scan.equals(second.scan)
    assert len(first.draws) == 3


def test_summary_quantiles_are_monotone_and_keys_complete(tmp_path: Path):
    artifacts = run_monte_carlo(REGISTRY, METRICS, draws=5, seed=11, output_dir=tmp_path / "mc")
    assert set(artifacts.summary) == set(SUMMARY_KEYS)
    for key, stats in artifacts.summary.items():
        ordered = [stats["p5"], stats["p16"], stats["median"], stats["p84"], stats["p95"]]
        assert ordered == sorted(ordered), key
        assert stats["p5"] <= stats["mean"] <= stats["p95"], key
    payload = json.loads((tmp_path / "mc" / "mc_summary.json").read_text(encoding="utf-8"))
    assert payload["draws_completed"] == len(artifacts.draws)
    assert (tmp_path / "mc" / "mc_scan.csv").exists()
    plot_monte_carlo(artifacts.scan, tmp_path / "mc" / "fig8.png")
    assert (tmp_path / "mc" / "fig8.png").exists()


def test_registry_drift_from_the_sampling_nominal_is_rejected(tmp_path: Path):
    rows = REGISTRY.read_text(encoding="utf-8").replace(
        "sim.vdd_v,VDD,2.0,", "sim.vdd_v,VDD,2.1,"
    )
    drifted = tmp_path / "registry.csv"
    drifted.write_text(rows, encoding="utf-8")
    with pytest.raises(ValueError, match="ASSUMPTION_RANGES"):
        run_monte_carlo(drifted, METRICS, draws=2, seed=1, output_dir=tmp_path / "mc")


def test_assumption_ranges_cover_the_registered_intervals():
    # The sampling spec must stay inside the documented uncertainty intervals.
    expected = {
        "dev.oxide_relative_permittivity": (12.0, 20.0),
        "assume.n_p_dose_response_ratio": (0.5, 1.5),
        "sim.vdd_v": (1.5, 2.5),
        "sim.temperature_k": (295.0, 305.0),
    }
    for param_id, (low, nominal, high) in ASSUMPTION_RANGES.items():
        assert np.isclose(low, expected[param_id][0])
        assert np.isclose(high, expected[param_id][1])
        assert low < nominal < high


def test_metric_perturbation_stays_within_the_digitized_bars(tmp_path: Path):
    from cnt_tid.metric_calibration import load_digitized_metrics
    from cnt_tid.monte_carlo import _perturb_metrics

    metrics = load_digitized_metrics(METRICS)
    rng = np.random.default_rng(0)
    for _ in range(20):
        perturbed = _perturb_metrics(metrics, rng)
        sigma = 0.5 * (
            metrics["err_minus"].to_numpy(dtype=float)
            + metrics["err_plus"].to_numpy(dtype=float)
        )
        deviation = np.abs(
            perturbed["value"].to_numpy(dtype=float) - metrics["value"].to_numpy(dtype=float)
        )
        # Drawn normal values can exceed sigma occasionally, but never wildly;
        # positivity of Gm/SS is enforced by the pull-back rule.
        assert (deviation <= 4.0 * sigma + 1e-12).all()
        assert (perturbed.loc[perturbed["metric"] != "vth_v", "value"] > 0).all()
