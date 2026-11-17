"""Tests for the P0 pipeline and the model extensions it relies on."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from cnt_tid.circuit import solve_inverter
from cnt_tid.config import DeviceConfig
from cnt_tid.device import state_at_dose
from cnt_tid.p0 import run_p0

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "parameters" / "tid_parameters.csv"
METRICS = ROOT / "data" / "literature" / "cui2023_topgate" / "fig3_metrics_digitized.csv"


def test_dose_exponent_changes_the_charge_law():
    base = dict(
        polarity="p",
        oxide_thickness_nm=10.0,
        oxide_relative_permittivity=15.0,
        qot_slope_c_cm2_per_krad=1e-8,
        qit_slope_c_cm2_per_krad=0.0,
    )
    linear = state_at_dose(DeviceConfig(**base), 400.0)
    square_root = state_at_dose(DeviceConfig(**base, dose_exponent=0.5), 400.0)
    assert linear.qot_c_cm2 == pytest.approx(4e-6)
    assert square_root.qot_c_cm2 == pytest.approx(1e-8 * 20.0)
    assert state_at_dose(DeviceConfig(**base, dose_exponent=0.5), 0.0).qot_c_cm2 == 0.0


def test_invalid_exponent_is_rejected():
    with pytest.raises(ValueError, match="dose_exponent"):
        DeviceConfig(polarity="n", dose_exponent=0.0)
    with pytest.raises(ValueError, match="dose_exponent"):
        DeviceConfig(polarity="n", dose_exponent=3.5)


def test_inverter_stays_inside_the_rails_for_extreme_thresholds():
    n_device = DeviceConfig(polarity="n", threshold_v=8.0, mobility_m2_vs=1e-3)
    p_device = DeviceConfig(polarity="p", threshold_v=8.0, mobility_m2_vs=1e-3)
    n_state = state_at_dose(n_device, 0.0)
    p_state = state_at_dose(p_device, 0.0)
    result = solve_inverter(n_state, p_state, 2.0, 201)
    assert np.isfinite(result.vout_v).all()
    assert (result.vout_v >= -1e-12).all() and (result.vout_v <= 2.0 + 1e-12).all()


def test_tid_shifts_the_inverter_switching_point_down():
    n_device = DeviceConfig(polarity="n", threshold_v=0.5, oxide_thickness_nm=10.0,
                            oxide_relative_permittivity=15.0,
                            qot_slope_c_cm2_per_krad=2.2e-8, dose_exponent=0.5,
                            qit_slope_c_cm2_per_krad=8.9e-9)
    p_device = DeviceConfig(polarity="p", threshold_v=0.5, oxide_thickness_nm=10.0,
                            oxide_relative_permittivity=15.0,
                            qot_slope_c_cm2_per_krad=2.2e-8, dose_exponent=0.5,
                            qit_slope_c_cm2_per_krad=8.9e-9)
    zero = solve_inverter(state_at_dose(n_device, 0.0), state_at_dose(p_device, 0.0), 2.0, 401)
    high = solve_inverter(
        state_at_dose(n_device, 3000.0), state_at_dose(p_device, 3000.0), 2.0, 401
    )
    assert zero.vm_v == pytest.approx(1.0, abs=0.02)
    assert high.vm_v < zero.vm_v - 0.2


def _fast_registry(tmp_path: Path) -> Path:
    with REGISTRY.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["param_id"] == "sim.transfer_points":
            row["value"] = "101"
        if row["param_id"] == "sim.inverter_points":
            row["value"] = "201"
    destination = tmp_path / "registry.csv"
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return destination


def test_p0_pipeline_writes_every_artifact(tmp_path):
    result = run_p0(_fast_registry(tmp_path), METRICS, tmp_path / "p0")
    output = result.output_dir
    for name in (
        "config_resolved.toml",
        "parameters_resolved.csv",
        "key_numbers.json",
        "manifest.json",
        "calibration/residuals.csv",
        "validation/model_vs_literature.csv",
        "dose_sweep/summary.csv",
        "figures/fig1_structure.png",
        "figures/fig2_validation.png",
        "figures/fig3_inverter.png",
        "figures/fig4_sensitivity.png",
    ):
        assert (output / name).is_file(), name

    numbers = json.loads((output / "key_numbers.json").read_text(encoding="utf-8"))
    assert 0.2 < numbers["dose_exponent"] < 1.0
    assert numbers["vth_shift_at_max_dose_v"] == pytest.approx(1.108, abs=0.05)
    assert numbers["inverter_switching_maintained"] is True

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["inputs"]) and set(manifest["outputs"])
    assert all(len(value) == 64 for value in manifest["outputs"].values())

    resolved = (output / "parameters_resolved.csv").read_text(encoding="utf-8")
    for provenance in ("reported", "assumed", "calibrated", "derived"):
        assert provenance in resolved
