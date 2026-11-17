"""Tests for the traceable parameter registry."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from cnt_tid.registry import (
    REQUIRED_IDS,
    build_simulation_config,
    load_registry,
    numbers,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "parameters" / "tid_parameters.csv"


def write_registry(path: Path, rows: list[dict[str, str]]) -> Path:
    columns = ["param_id", "symbol", "value", "unit", "provenance", "source", "derivation", "uncertainty", "notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
    return path


def base_rows() -> list[dict[str, str]]:
    with REGISTRY.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_repository_registry_covers_every_required_id():
    registry = load_registry(REGISTRY)
    missing = [param_id for param_id in REQUIRED_IDS if param_id not in registry]
    assert missing == []
    assert numbers(registry, "sim.doses_krad") == (0.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0)


def test_assumption_without_uncertainty_is_rejected(tmp_path):
    rows = base_rows()
    for row in rows:
        if row["param_id"] == "sim.vdd_v":
            row["uncertainty"] = ""
    path = write_registry(tmp_path / "registry.csv", rows)
    with pytest.raises(ValueError, match="uncertainty"):
        load_registry(path)


def test_missing_required_id_is_rejected(tmp_path):
    rows = [row for row in base_rows() if row["param_id"] != "dev.length_nm"]
    path = write_registry(tmp_path / "registry.csv", rows)
    with pytest.raises(ValueError, match="missing required ids"):
        load_registry(path)


def test_unknown_provenance_is_rejected(tmp_path):
    rows = base_rows()
    rows[3]["provenance"] = "vibes"
    path = write_registry(tmp_path / "registry.csv", rows)
    with pytest.raises(ValueError, match="provenance"):
        load_registry(path)


def test_duplicate_id_is_rejected(tmp_path):
    rows = base_rows()
    rows.append(dict(rows[0]))
    path = write_registry(tmp_path / "registry.csv", rows)
    with pytest.raises(ValueError, match="duplicate"):
        load_registry(path)


def test_build_config_applies_the_n_p_ratio_and_clears_linear_swing():
    registry = load_registry(REGISTRY)
    registry = dict(registry)
    from dataclasses import replace

    registry["assume.n_p_dose_response_ratio"] = replace(
        registry["assume.n_p_dose_response_ratio"], value="0.8"
    )
    config = build_simulation_config(
        registry,
        vth0_mag_v=0.53,
        mobility_m2_vs=2.1e-3,
        slope_factor0=3.49,
        q_ot_c_cm2_per_krad=2.2e-8,
        q_it_c_cm2_per_krad=8.9e-9,
        mobility_degradation_per_krad=5.5e-4,
        dose_exponent=0.48,
    )
    assert config.vdd_v == 2.0
    assert config.n_device.qot_slope_c_cm2_per_krad == pytest.approx(0.8 * 2.2e-8)
    assert config.p_device.qot_slope_c_cm2_per_krad == pytest.approx(2.2e-8)
    assert config.p_device.slope_factor_per_krad == 0.0
    assert config.p_device.slope_factor_from_qit is True
    assert config.p_device.dose_exponent == pytest.approx(0.48)
    assert config.n_device.threshold_v == config.p_device.threshold_v
